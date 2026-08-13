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

test("WP3 uses deterministic layout instead of force physics", () => {
  assert.match(viewSource, /GOLDEN_ANGLE/);
  assert.match(viewSource, /SLOT_SPACING/);
  assert.doesNotMatch(viewSource, /forceSimulation|forceManyBody|forceCollide|d3\./);
});

test("draft exposes the three explicit bubble-scale candidates", () => {
  assert.match(viewSource, /\["market_cap", "Market cap"\]/);
  assert.match(viewSource, /\["liquidity", "Liquidity"\]/);
  assert.match(viewSource, /\["economic", "Economic mix"\]/);
  assert.match(viewSource, /robustLogRange/);
  assert.match(viewSource, /radiusForScore/);
});

test("holder count only controls bounded spoke presentation", () => {
  assert.match(viewSource, /buildHolderScale/);
  assert.match(viewSource, /Spoke strength = holders/);
  assert.match(viewSource, /token_retired/);
  assert.match(viewSource, /token_added/);
  assert.match(viewSource, /token_updated/);
});
