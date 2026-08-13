import { count, duration, integerFormat, money, tokenIdentity } from "./format.js";
import { searchTokens } from "./search.js";
import { normalizedLaunchpad } from "./state.js";

export class TokenUI {
  constructor({ state, onSelect }) {
    this.state = state;
    this.onSelect = onSelect;
    this.activeCount = document.querySelector("#active-count");
    this.launchpadCount = document.querySelector("#launchpad-count");
    this.changedCount = document.querySelector("#changed-count");
    this.emptyDetail = document.querySelector("#empty-detail");
    this.tokenDetail = document.querySelector("#token-detail");
    this.detailMint = document.querySelector("#detail-mint");
    this.detailMintCopy = document.querySelector("#detail-mint-copy");
    this.searchRoot = document.querySelector(".token-search");
    this.searchForm = document.querySelector("#token-search-form");
    this.searchInput = document.querySelector("#token-search-input");
    this.searchResults = document.querySelector("#token-search-results");
    this.copyResetTimer = null;

    this.searchInput.addEventListener("input", () => this.refreshSearch(true));
    this.searchInput.addEventListener("keydown", event => {
      if (event.key !== "Escape") return;
      this.searchInput.value = "";
      this.closeSearch();
    });
    this.searchForm.addEventListener("submit", event => {
      event.preventDefault();
      const [first] = this.refreshSearch(true);
      if (!first || !this.onSelect(first.mint)) return;
      this.searchInput.value = tokenIdentity(first);
      this.closeSearch();
    });
    this.detailMintCopy.addEventListener("click", () => this.copySelectedMint());
    document.addEventListener("pointerdown", event => {
      if (!this.searchRoot.contains(event.target)) this.closeSearch();
    });
  }

  enableSearch() {
    this.searchInput.disabled = false;
  }

  renderStats(changed = 0) {
    const stats = this.state.stats();
    this.activeCount.textContent = integerFormat.format(stats.active);
    this.launchpadCount.textContent = integerFormat.format(stats.launchpads);
    this.changedCount.textContent = integerFormat.format(changed);
  }

  renderSelected() {
    this.renderDetail(this.state.selectedToken());
  }

  renderDetail(token) {
    this.resetCopyButton();
    if (!token) {
      this.emptyDetail.classList.remove("hidden");
      this.tokenDetail.classList.add("hidden");
      return;
    }

    this.emptyDetail.classList.add("hidden");
    this.tokenDetail.classList.remove("hidden");
    document.querySelector("#detail-launchpad").textContent = normalizedLaunchpad(token);
    document.querySelector("#detail-name").textContent = token.name || token.symbol || "Unnamed token";
    document.querySelector("#detail-symbol").textContent = token.symbol || "—";

    const stateBadge = document.querySelector("#detail-state");
    stateBadge.textContent = token.tracking_enabled ? "ACTIVE" : "RETIRED";
    stateBadge.className = token.tracking_enabled
      ? "state-badge active hidden"
      : "state-badge retired";

    document.querySelector("#detail-mcap").textContent = money(token.market_cap);
    document.querySelector("#detail-liquidity").textContent = money(token.liquidity);
    document.querySelector("#detail-holders").textContent = count(token.holders);
    document.querySelector("#detail-traders").textContent = count(token.traders_5m);
    document.querySelector("#detail-trades").textContent = count(token.trades_5m);
    document.querySelector("#detail-volume").textContent = money(token.volume_5m);
    document.querySelector("#detail-poll").textContent = `${duration(token.poll_age_seconds)} ago`;
    document.querySelector("#detail-change").textContent = `${duration(token.change_age_seconds)} ago`;
    document.querySelector("#detail-age").textContent = duration(token.age_seconds);
    this.detailMint.textContent = token.mint;
  }

  async copySelectedMint() {
    const token = this.state.selectedToken();
    if (!token?.mint) return;

    try {
      await navigator.clipboard.writeText(token.mint);
      this.detailMintCopy.textContent = "Copied";
    } catch (error) {
      console.warn("Mint copy failed", error);
      this.detailMintCopy.textContent = "Copy failed";
    }

    clearTimeout(this.copyResetTimer);
    this.copyResetTimer = setTimeout(() => this.resetCopyButton(), 1400);
  }

  resetCopyButton() {
    clearTimeout(this.copyResetTimer);
    this.copyResetTimer = null;
    this.detailMintCopy.textContent = "Copy";
  }

  closeSearch() {
    this.searchResults.classList.add("hidden");
    this.searchInput.setAttribute("aria-expanded", "false");
  }

  refreshSearch(forceOpen = false) {
    if (!forceOpen && this.searchResults.classList.contains("hidden")) return [];
    const query = this.searchInput.value.trim();
    this.searchResults.replaceChildren();
    if (!query) {
      this.closeSearch();
      return [];
    }

    const matches = searchTokens(this.state.values(), query);
    if (!matches.length) {
      const empty = document.createElement("li");
      empty.className = "token-search-empty";
      empty.textContent = "No active token found";
      this.searchResults.append(empty);
    } else {
      for (const token of matches) {
        const item = document.createElement("li");
        item.append(this.#tokenChoice(token));
        this.searchResults.append(item);
      }
    }

    this.searchResults.classList.remove("hidden");
    this.searchInput.setAttribute("aria-expanded", "true");
    return matches;
  }

  #tokenChoice(token) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "token-search-choice";

    const identity = document.createElement("strong");
    identity.textContent = tokenIdentity(token);
    const detail = document.createElement("span");
    detail.textContent = `${token.name || "Unnamed token"} · ${normalizedLaunchpad(token)}`;
    const metrics = document.createElement("span");
    metrics.className = "token-choice-metrics";
    metrics.textContent = `MC ${money(token.market_cap)} · LIQ ${money(token.liquidity)} · ${count(token.holders)} holders`;
    const mint = document.createElement("small");
    mint.textContent = token.mint;
    button.append(identity, detail, metrics, mint);

    button.addEventListener("click", () => {
      if (!this.onSelect(token.mint)) return;
      this.searchInput.value = tokenIdentity(token);
      this.closeSearch();
    });
    return button;
  }
}
