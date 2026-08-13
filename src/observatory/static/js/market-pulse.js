const DEFAULT_SAMPLE_INTERVAL_MS = 1_000;
const DEFAULT_RETENTION_MS = 6 * 60 * 60 * 1000;

function finiteNumber(value) {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function knownValues(tokens, field) {
  const values = [];
  for (const token of tokens) {
    const value = finiteNumber(token?.[field]);
    if (value !== null) values.push(value);
  }
  return values;
}

function sum(values) {
  return values.length ? values.reduce((total, value) => total + value, 0) : null;
}

function median(values) {
  if (!values.length) return null;
  const sorted = [...values].sort((left, right) => left - right);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2
    ? sorted[middle]
    : (sorted[middle - 1] + sorted[middle]) / 2;
}

function coverage(known, total) {
  return total > 0 ? known / total * 100 : null;
}

function share(part, total) {
  return total > 0 ? part / total * 100 : null;
}

function topShare(values, count) {
  const total = sum(values);
  if (total === null || total <= 0) return null;
  const top = [...values]
    .sort((left, right) => right - left)
    .slice(0, count)
    .reduce((result, value) => result + value, 0);
  return top / total * 100;
}

export function deriveMarketPulse(tokens, timestamp = Date.now()) {
  const active = (Array.isArray(tokens) ? tokens : []).filter(token => token?.tracking_enabled);
  const activeCount = active.length;
  const volumeValues = knownValues(active, "volume_5m");
  const liquidityValues = knownValues(active, "liquidity");

  const pressurePairs = [];
  for (const token of active) {
    const buyVolume = finiteNumber(token?.buy_volume_5m);
    const sellVolume = finiteNumber(token?.sell_volume_5m);
    if (buyVolume !== null && sellVolume !== null) {
      pressurePairs.push([buyVolume, sellVolume]);
    }
  }

  const buyVolume = pressurePairs.length
    ? pressurePairs.reduce((total, pair) => total + pair[0], 0)
    : null;
  const sellVolume = pressurePairs.length
    ? pressurePairs.reduce((total, pair) => total + pair[1], 0)
    : null;
  const pairedVolume = buyVolume !== null && sellVolume !== null ? buyVolume + sellVolume : null;

  return {
    timestamp,
    active_count: activeCount,
    volume_5m: {
      total: sum(volumeValues),
      known_tokens: volumeValues.length,
      coverage_pct: coverage(volumeValues.length, activeCount),
      breadth_pct: volumeValues.length
        ? volumeValues.filter(value => value > 0).length / volumeValues.length * 100
        : null,
      top10_share_pct: topShare(volumeValues, 10),
    },
    pressure_5m: {
      buy_volume: buyVolume,
      sell_volume: sellVolume,
      net_volume: pairedVolume === null ? null : buyVolume - sellVolume,
      buy_share_pct: pairedVolume === null ? null : share(buyVolume, pairedVolume),
      known_tokens: pressurePairs.length,
      coverage_pct: coverage(pressurePairs.length, activeCount),
    },
    liquidity: {
      total: sum(liquidityValues),
      median: median(liquidityValues),
      known_tokens: liquidityValues.length,
      coverage_pct: coverage(liquidityValues.length, activeCount),
    },
  };
}

export class MarketPulseSeries {
  constructor({
    sampleIntervalMs = DEFAULT_SAMPLE_INTERVAL_MS,
    retentionMs = DEFAULT_RETENTION_MS,
  } = {}) {
    this.sampleIntervalMs = sampleIntervalMs;
    this.retentionMs = retentionMs;
    this.points = [];
  }

  sample(tokens, timestamp = Date.now()) {
    const at = Number.isFinite(timestamp) ? timestamp : Date.now();
    const previous = this.points.at(-1);
    if (previous && at - previous.timestamp < this.sampleIntervalMs) return false;

    this.points.push(deriveMarketPulse(tokens, at));
    const cutoff = at - this.retentionMs;
    while (this.points.length && this.points[0].timestamp < cutoff) this.points.shift();
    return true;
  }

  current() {
    return this.points.at(-1) || null;
  }

  history() {
    return [...this.points];
  }
}

export const MARKET_PULSE_SAMPLE_INTERVAL_MS = DEFAULT_SAMPLE_INTERVAL_MS;
export const MARKET_PULSE_RETENTION_MS = DEFAULT_RETENTION_MS;
