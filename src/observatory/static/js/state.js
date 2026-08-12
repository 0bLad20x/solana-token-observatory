export function normalizedLaunchpad(token) {
  return token?.launchpad && token.launchpad !== "" ? token.launchpad : "unknown";
}

export class ObservatoryState {
  constructor() {
    this.tokens = new Map();
    this.selectedMint = null;
  }

  load(tokens) {
    this.tokens.clear();
    for (const token of tokens) this.tokens.set(token.mint, token);
    if (this.selectedMint && !this.tokens.has(this.selectedMint)) this.selectedMint = null;
  }

  upsert(token) {
    if (!token?.mint) return false;
    this.tokens.set(token.mint, token);
    return true;
  }

  applyEvent(event) {
    const token = event?.token;
    if (!token?.mint) return false;

    if (event.type === "token_retired") {
      const previous = this.tokens.get(token.mint) || {};
      this.tokens.set(token.mint, {
        ...previous,
        ...token,
        tracking_enabled: false,
        disabled_reason: event.reason || token.disabled_reason,
      });
      return true;
    }

    if (event.type !== "token_added" && event.type !== "token_updated") return false;
    this.tokens.set(token.mint, token);
    return true;
  }

  select(mint) {
    if (!this.tokens.has(mint)) return false;
    this.selectedMint = mint;
    return true;
  }

  token(mint) {
    return this.tokens.get(mint) || null;
  }

  selectedToken() {
    return this.selectedMint ? this.token(this.selectedMint) : null;
  }

  values() {
    return [...this.tokens.values()];
  }

  activeTokens() {
    return this.values().filter(token => token.tracking_enabled);
  }

  stats() {
    const active = this.activeTokens();
    return {
      active: active.length,
      launchpads: new Set(active.map(normalizedLaunchpad)).size,
    };
  }
}
