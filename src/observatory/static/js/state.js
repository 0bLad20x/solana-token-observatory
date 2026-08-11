import { DEFAULT_VIEW_ID } from "./view-spec.js";

export function normalizedLaunchpad(token) {
  return token?.launchpad && token.launchpad !== "" ? token.launchpad : "unknown";
}

export class ObservatoryState {
  constructor() {
    this.tokens = new Map();
    this.selectedMint = null;
    this.activeView = DEFAULT_VIEW_ID;
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

  searchTokens(query, limit = 8) {
    const raw = String(query || "").trim();
    if (!raw || limit < 1) return [];
    const needle = raw.toLowerCase();

    const matches = [];
    for (const token of this.tokens.values()) {
      if (!token.tracking_enabled) continue;
      const mint = String(token.mint || "");
      const symbol = String(token.symbol || "");
      const name = String(token.name || "");
      const values = [mint, symbol, name].map(value => value.toLowerCase());

      if (!values.some(value => value.includes(needle))) continue;

      matches.push({
        token,
        exactMint: mint === raw,
        marketCap: Number.isFinite(token.market_cap) ? token.market_cap : null,
        label: `${symbol}\u0000${name}\u0000${mint}`.toLowerCase(),
      });
    }

    return matches
      .sort((left, right) => {
        if (left.exactMint !== right.exactMint) return left.exactMint ? -1 : 1;
        if (left.marketCap !== right.marketCap) {
          if (left.marketCap == null) return 1;
          if (right.marketCap == null) return -1;
          return right.marketCap - left.marketCap;
        }
        return left.label.localeCompare(right.label);
      })
      .slice(0, limit)
      .map(match => match.token);
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
