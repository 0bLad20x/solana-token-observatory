export class ActivityTracker {
  constructor() {
    this.recentChanges = [];
    this.volumeEvents = [];
  }

  applyEvent(event, timestamp = Date.now()) {
    const token = event?.token;
    if (!token?.mint) return;

    const parsed = Number.isFinite(timestamp) ? timestamp : Date.parse(timestamp);
    const eventTime = Number.isFinite(parsed) ? parsed : Date.now();
    this.recentChanges.push({ mint: token.mint, timestamp: eventTime });
    this.#recordVolumeActivity(event, eventTime);
  }

  changedCount(now = Date.now(), windowMs = 60_000) {
    const cutoff = now - windowMs;
    this.recentChanges = this.recentChanges.filter(event => event.timestamp >= cutoff);
    return new Set(this.recentChanges.map(event => event.mint)).size;
  }

  #recordVolumeActivity(event, timestamp) {
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

    this.volumeEvents.push({
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
    this.volumeEvents = this.volumeEvents.filter(event => event.timestamp >= cutoff);

    const byMint = new Map();
    for (const event of this.volumeEvents) {
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
}
