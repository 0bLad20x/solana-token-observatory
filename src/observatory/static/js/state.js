export function normalizedLaunchpad(token) {
  return token?.launchpad && token.launchpad !== "" ? token.launchpad : "unknown";
}

export class ObservatoryState {
  constructor() {
    this.tokens = new Map();
    this.selectedMint = null;
    this.activeView = "launchpad-cluster";
    this.recentChanges = [];
    this.eventCount = 0;
  }

  load(tokens) {
    this.tokens.clear();
    for (const token of tokens) this.tokens.set(token.mint, token);
  }

  upsert(token) {
    this.tokens.set(token.mint, token);
  }

  applyEvent(event) {
    const token = event.token;
    if (!token?.mint) return;

    this.eventCount += 1;
    this.recentChanges.push(Date.now());

    if (event.type === "token_retired") {
      const previous = this.tokens.get(token.mint) || {};
      this.tokens.set(token.mint, {
        ...previous,
        ...token,
        tracking_enabled: false,
        disabled_reason: event.reason || token.disabled_reason,
      });
      return;
    }

    this.tokens.set(token.mint, token);
  }

  select(mint) {
    this.selectedMint = mint;
  }

  setView(viewId) {
    this.activeView = viewId;
  }

  token(mint) {
    return this.tokens.get(mint) || null;
  }

  selectedToken() {
    return this.selectedMint ? this.token(this.selectedMint) : null;
  }

  stats(now = Date.now()) {
    const cutoff = now - 60_000;
    this.recentChanges = this.recentChanges.filter(timestamp => timestamp >= cutoff);

    const active = [...this.tokens.values()].filter(token => token.tracking_enabled);
    return {
      active: active.length,
      launchpads: new Set(active.map(normalizedLaunchpad)).size,
      changed: this.recentChanges.length,
      events: this.eventCount,
    };
  }
}
