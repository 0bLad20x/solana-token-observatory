import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  MARKET_PULSE_RETENTION_MS,
  MARKET_PULSE_SAMPLE_INTERVAL_MS,
  MarketPulseSeries,
  deriveMarketPulse,
} from "../src/observatory/static/js/market-pulse.js";

function token(overrides = {}) {
  return {
    tracking_enabled: true,
    volume_5m: 100,
    buy_volume_5m: 60,
    sell_volume_5m: 40,
    liquidity: 1000,
    ...overrides,
  };
}

test("market pulse aggregates only the active canonical population", () => {
  const pulse = deriveMarketPulse([
    token(),
    token({ volume_5m: 300, buy_volume_5m: 100, sell_volume_5m: 200, liquidity: 3000 }),
    token({ tracking_enabled: false, volume_5m: 9999, liquidity: 9999 }),
  ], 123);

  assert.equal(pulse.timestamp, 123);
  assert.equal(pulse.active_count, 2);
  assert.equal(pulse.volume_5m.total, 400);
  assert.equal(pulse.pressure_5m.buy_volume, 160);
  assert.equal(pulse.pressure_5m.sell_volume, 240);
  assert.equal(pulse.pressure_5m.buy_share_pct, 40);
  assert.equal(pulse.liquidity.total, 4000);
  assert.equal(pulse.liquidity.median, 2000);
});

test("missing buy or sell values are not reinterpreted as zero", () => {
  const pulse = deriveMarketPulse([
    token(),
    token({ buy_volume_5m: null, sell_volume_5m: 50 }),
    token({ volume_5m: null, buy_volume_5m: null, sell_volume_5m: null, liquidity: null }),
  ]);

  assert.equal(pulse.active_count, 3);
  assert.equal(pulse.volume_5m.total, 200);
  assert.equal(pulse.volume_5m.known_tokens, 2);
  assert.equal(pulse.pressure_5m.known_tokens, 1);
  assert.equal(pulse.pressure_5m.buy_volume, 60);
  assert.equal(pulse.pressure_5m.sell_volume, 40);
  assert.equal(pulse.liquidity.known_tokens, 2);
});

test("breadth and concentration use known rolling volume values", () => {
  const pulse = deriveMarketPulse([
    token({ volume_5m: 90 }),
    token({ volume_5m: 10 }),
    token({ volume_5m: 0 }),
    token({ volume_5m: null }),
  ]);

  assert.ok(Math.abs(pulse.volume_5m.breadth_pct - 200 / 3) < 1e-9);
  assert.equal(pulse.volume_5m.top10_share_pct, 100);
});

test("market pulse series samples every second and retains a bounded six hour window", () => {
  const series = new MarketPulseSeries();
  assert.equal(MARKET_PULSE_SAMPLE_INTERVAL_MS, 1000);
  assert.equal(series.sample([token()], 0), true);
  assert.equal(series.sample([token()], MARKET_PULSE_SAMPLE_INTERVAL_MS - 1), false);
  assert.equal(series.sample([token()], MARKET_PULSE_SAMPLE_INTERVAL_MS), true);
  assert.equal(series.history().length, 2);

  const future = MARKET_PULSE_RETENTION_MS + MARKET_PULSE_SAMPLE_INTERVAL_MS;
  assert.equal(series.sample([token()], future), true);
  assert.equal(series.history().length, 2);
  assert.equal(series.history()[0].timestamp, MARKET_PULSE_SAMPLE_INTERVAL_MS);
});


test("pulse is a third primary view without owning token-universe presentation", () => {
  const indexSource = readFileSync(new URL("../src/observatory/static/index.html", import.meta.url), "utf8");
  const appSource = readFileSync(new URL("../src/observatory/static/js/app.js", import.meta.url), "utf8");

  assert.match(indexSource, /id="view-market-pulse"/);
  assert.match(indexSource, /id="market-pulse-stage"/);
  assert.match(appSource, /MarketPulseView/);
  assert.match(appSource, /setPrimaryMode\("pulse"\)/);
  assert.doesNotMatch(appSource, /token-universe-view\.js[\s\S]{0,200}market pulse/i);
});
