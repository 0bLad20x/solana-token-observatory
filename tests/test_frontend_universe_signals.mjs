import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  SIGNAL_DEFAULTS,
  buildPopulationRatioScale,
  marketMoveFromEvent,
  marketSignalLevel,
  ratioValue,
  volumeIntensityChange,
} from "../src/observatory/static/js/views/universe-signals.js";

const indexSource = readFileSync(
  new URL("../src/observatory/static/index.html", import.meta.url),
  "utf8",
);
const signalSource = readFileSync(
  new URL("../src/observatory/static/js/views/universe-signals.js", import.meta.url),
  "utf8",
);

test("volume intensity compares activity to token size rather than raw volume", () => {
  assert.equal(ratioValue(100_000, 500_000), 0.2);
  assert.equal(ratioValue(1_000_000, 100_000_000), 0.01);
  assert.equal(ratioValue(100, 0), null);
});

test("population-relative volume threshold can surface small high-intensity tokens", () => {
  const tokens = [
    { mint: "small-hot", volume_5m: 100_000, market_cap: 500_000 },
    { mint: "large-calm", volume_5m: 1_000_000, market_cap: 100_000_000 },
    { mint: "middle", volume_5m: 50_000, market_cap: 1_000_000 },
  ];
  const scale = buildPopulationRatioScale(tokens, "volume_5m", "market_cap", 0.5, 1);
  const smallScore = scale.score(ratioValue(100_000, 500_000));
  const largeScore = scale.score(ratioValue(1_000_000, 100_000_000));

  assert.ok(smallScore > 0);
  assert.equal(largeScore, null);
});

test("market move thresholds preserve ordinary and strong signals", () => {
  const settings = { ...SIGNAL_DEFAULTS, marketMove: 0.03, strongMarketMove: 0.10 };
  assert.equal(marketSignalLevel(0.029, settings), "none");
  assert.equal(marketSignalLevel(-0.031, settings), "move");
  assert.equal(marketSignalLevel(0.10, settings), "strong");

  const event = {
    type: "token_updated",
    changes: { market_cap: { percent: -12.5 } },
  };
  assert.equal(marketMoveFromEvent(event), -0.125);
});

test("volume surge is change in rolling volume-to-market-cap intensity", () => {
  const event = {
    type: "token_updated",
    token: { volume_5m: 30_000, market_cap: 500_000 },
    changes: {
      volume_5m: { absolute: 10_000 },
      market_cap: { absolute: 0 },
    },
  };
  assert.ok(Math.abs(volumeIntensityChange(event) - 0.02) < 1e-12);
});

test("signal layer is presentation-only and bootstraps before the existing app", () => {
  assert.match(indexSource, /app-with-signals\.js/);
  assert.match(signalSource, /installUniverseSignals/);
  assert.match(signalSource, /baseEvents = events\.filter\(event => event\?\.type !== "token_updated"\)/);
  assert.match(signalSource, /Volume intensity = rolling 5m volume \/ market cap/);
  assert.match(signalSource, /Data updates/);
  assert.match(signalSource, /Market move/);
  assert.match(signalSource, /Strong move/);
  assert.match(signalSource, /Volume \/ MC/);
  assert.doesNotMatch(signalSource, /fetch\(|EventSource|WebSocket|localStorage|sessionStorage/);
});
