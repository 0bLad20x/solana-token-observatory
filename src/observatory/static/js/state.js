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
    this.activityEvents = [];
  }

  load(tokens) {
    this.tokens.clear();
    for (const token of tokens) this.tokens.set(token.mint, token);
  }

  upsert(token) {
    this.tokens.set(token.mint, token);
  }

  applyEvent(event, timestamp = Date.now()) {
    const token = event.token;
    if (!token?.mint) return;

    const observedAt = Number.isFinite(timestamp) ? timestamp : Date.parse(timestamp);
    const eventTime = Number.isFinite(observedAt) ? observedAt : Date.now();
    this.recentChanges.push({ mint: token.mint, timestamp: eventTime });
    this.recordVolumeActivity(event, eventTime);

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

  recordVolumeActivity(event, timestamp) {
    if (event.type !== "token_updated") return;

    const volumeAfter = event.token.volume_5m;
    const marketCapAfter = event.token.market_cap;
    const volumeChange = event.changes?.volume_5m?.absolute;
    const marketCapChange = event.changes?.market_cap?.absolute;
    if (![volumeAfter, marketCapAfter, volumeChange, marketCapChange].every(Number.isFinite)) return;

    const volumeBefore = volumeAfter - volumeChange;
    const marketCapBefore = marketCapAfter - marketCapChange;
    if (volumeBefore < 0 || marketCapBefore <= 0 || marketCapAfter <= 0) return;

    const ratioBefore = volumeBefore / marketCapBefore;
    const ratioAfter = volumeAfter / marketCapAfter;
    if (volumeAfter <= volumeBefore || ratioAfter <= ratioBefore) return;

    this.activityEvents.push({
      mint: event.token.mint,
      timestamp,
      volumeBefore,
      volumeAfter,
      marketCapBefore,
      marketCapAfter,
      ratioBefore,
      ratioAfter,
    });
  }

  topVolumeActivity(now = Date.now(), windowMs = 60_000, limit = 5) {
    const cutoff = now - windowMs;
    this.activityEvents = this.activityEvents.filter(event => event.timestamp >= cutoff);

    const byMint = new Map();
    for (const event of this.activityEvents) {
      const aggregate = byMint.get(event.mint);
      if (!aggregate) {
        byMint.set(event.mint, { ...event, latestTimestamp: event.timestamp });
        continue;
      }
      if (event.timestamp < aggregate.timestamp) {
        aggregate.timestamp = event.timestamp;
        aggregate.volumeBefore = event.volumeBefore;
        aggregate.marketCapBefore = event.marketCapBefore;
        aggregate.ratioBefore = event.ratioBefore;
      }
      if (event.timestamp >= aggregate.latestTimestamp) {
        aggregate.latestTimestamp = event.timestamp;
        aggregate.volumeAfter = event.volumeAfter;
        aggregate.marketCapAfter = event.marketCapAfter;
        aggregate.ratioAfter = event.ratioAfter;
      }
    }

    return [...byMint.values()]
      .map(event => ({
        ...event,
        timestamp: event.latestTimestamp ?? event.timestamp,
        volumeChange: event.volumeAfter - event.volumeBefore,
        ratioChange: event.ratioAfter - event.ratioBefore,
      }))
      .filter(event => event.volumeChange > 0 && event.ratioChange > 0)
      .sort((left, right) =>
        right.ratioChange - left.ratioChange
        || right.volumeChange - left.volumeChange
        || left.mint.localeCompare(right.mint))
      .slice(0, Math.max(0, limit));
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
    this.recentChanges = this.recentChanges.filter(event => event.timestamp >= cutoff);

    const active = [...this.tokens.values()].filter(token => token.tracking_enabled);
    return {
      active: active.length,
      launchpads: new Set(active.map(normalizedLaunchpad)).size,
      changed: new Set(this.recentChanges.map(event => event.mint)).size,
    };
  }
}
