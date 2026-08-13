import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const appSource = readFileSync(
  new URL("../src/observatory/static/js/app.js", import.meta.url),
  "utf8",
);
const viewSource = readFileSync(
  new URL("../src/observatory/static/js/views/token-universe-view.js", import.meta.url),
  "utf8",
);
const indexSource = readFileSync(
  new URL("../src/observatory/static/index.html", import.meta.url),
  "utf8",
);

test("Token Universe replaces the disposable 200-card proof", () => {
  assert.match(appSource, /TokenUniverseView/);
  assert.doesNotMatch(appSource, /SimpleTokenView/);
  assert.match(indexSource, /token-universe\.css/);
  assert.doesNotMatch(viewSource, /MAX_VISIBLE_TOKENS|slice\(0,\s*200\)/);
});

test("Token Universe consumes canonical state and delta context without owning transport", () => {
  assert.match(viewSource, /render\(\{ tokens, selectedMint, events = \[\] \}\)/);
  assert.match(viewSource, /tokens\.filter\(token => token\.tracking_enabled\)/);
  assert.match(viewSource, /this\.onSelect\(node\.mint\)/);
  assert.doesNotMatch(viewSource, /fetch\(|EventSource|WebSocket/);
});

test("WP3 uses bounded local settling instead of permanent force physics", () => {
  assert.match(viewSource, /packClusters/);
  assert.match(viewSource, /clusterRadiusForNodes/);
  assert.match(viewSource, /#stepPhysics/);
  assert.match(viewSource, /SETTLE_MS/);
  assert.doesNotMatch(viewSource, /forceSimulation|forceManyBody|forceCollide|d3\./);
});

test("market cap is the primary bubble-size signal and liquidity is separate", () => {
  assert.match(viewSource, /buildMarketRadiusScale/);
  assert.match(viewSource, /buildLiquidityScale/);
  assert.match(viewSource, /Bubble radius = robust log market cap/);
  assert.match(viewSource, /Liquidity = outer halo/);
  assert.doesNotMatch(viewSource, /Economic mix|SCALE_MODES/);
});

test("membership spokes are contextual and holder-scaled", () => {
  assert.match(viewSource, /buildHolderScale/);
  assert.match(viewSource, /#drawContextSpokes/);
  assert.match(viewSource, /this\.hoverMint/);
  assert.match(viewSource, /this\.selectedMint/);
});

test("live transitions are quiet and retirement remains visible", () => {
  assert.match(viewSource, /ADD_MS = 720/);
  assert.match(viewSource, /UPDATE_MS = 900/);
  assert.match(viewSource, /RETIRE_MS = 1800/);
  assert.match(viewSource, /token_retired/);
  assert.match(viewSource, /token_added/);
  assert.match(viewSource, /token_updated/);
});
