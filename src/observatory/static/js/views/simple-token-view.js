import { money, tokenIdentity } from "../format.js";

const MAX_VISIBLE_TOKENS = 200;

export class SimpleTokenView {
  constructor(stageElement, { onSelect } = {}) {
    this.stageElement = stageElement;
    this.onSelect = onSelect || (() => {});
    this.tokens = new Map();
    this.selectedMint = null;
    this.root = null;
  }

  async init() {
    this.root = document.createElement("div");
    this.root.setAttribute("data-proof-view", "token-list");
    this.root.style.height = "100%";
    this.root.style.overflow = "auto";
    this.root.style.padding = "14px";
    this.root.style.boxSizing = "border-box";
    this.stageElement.replaceChildren(this.root);
  }

  load(tokens) {
    this.tokens.clear();
    for (const token of tokens) this.tokens.set(token.mint, token);
    this.#render();
  }

  applyEvents(events) {
    for (const event of events) {
      const token = event?.token;
      if (!token?.mint) continue;
      if (event.type === "token_retired") {
        const previous = this.tokens.get(token.mint) || {};
        this.tokens.set(token.mint, { ...previous, ...token, tracking_enabled: false });
      } else if (event.type === "token_added" || event.type === "token_updated") {
        this.tokens.set(token.mint, token);
      }
    }
    this.#render();
  }

  setSelectedMint(mint) {
    this.selectedMint = mint;
    this.#render();
  }

  destroy() {
    this.tokens.clear();
    this.root?.remove();
    this.root = null;
  }

  #visibleTokens() {
    const active = [...this.tokens.values()]
      .filter(token => token.tracking_enabled)
      .sort((left, right) => {
        const leftCap = Number.isFinite(left.market_cap) ? left.market_cap : -Infinity;
        const rightCap = Number.isFinite(right.market_cap) ? right.market_cap : -Infinity;
        return rightCap - leftCap || left.mint.localeCompare(right.mint);
      })
      .slice(0, MAX_VISIBLE_TOKENS);

    const selected = this.selectedMint ? this.tokens.get(this.selectedMint) : null;
    if (selected && !active.some(token => token.mint === selected.mint)) active.unshift(selected);
    return active;
  }

  #render() {
    if (!this.root) return;
    this.root.replaceChildren();

    const note = document.createElement("p");
    note.textContent = "Disposable proof view · up to 200 active tokens shown · search covers the full active population";
    note.style.margin = "0 0 12px";
    note.style.color = "#929BAD";
    note.style.fontSize = "12px";
    this.root.append(note);

    const list = document.createElement("div");
    list.style.display = "grid";
    list.style.gridTemplateColumns = "repeat(auto-fill, minmax(155px, 1fr))";
    list.style.gap = "8px";

    for (const token of this.#visibleTokens()) {
      const button = document.createElement("button");
      button.type = "button";
      button.style.textAlign = "left";
      button.style.padding = "10px";
      button.style.borderRadius = "8px";
      button.style.border = token.mint === this.selectedMint
        ? "1px solid #49D9FF"
        : "1px solid #252C3D";
      button.style.background = "#0F1420";
      button.style.color = "#F3F5F8";
      button.style.cursor = "pointer";
      button.setAttribute("aria-pressed", token.mint === this.selectedMint ? "true" : "false");
      button.addEventListener("click", () => this.onSelect(token.mint));

      const identity = document.createElement("strong");
      identity.textContent = tokenIdentity(token);
      identity.style.display = "block";
      const cap = document.createElement("span");
      cap.textContent = `MC ${money(token.market_cap)}${token.tracking_enabled ? "" : " · RETIRED"}`;
      cap.style.display = "block";
      cap.style.marginTop = "4px";
      cap.style.color = "#929BAD";
      cap.style.fontSize = "11px";
      button.append(identity, cap);
      list.append(button);
    }

    this.root.append(list);
  }
}
