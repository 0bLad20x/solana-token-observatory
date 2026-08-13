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

test("WP3 uses bounded local settling while preserving stable launchpad centers", () => {
  assert.match(viewSource, /packClusters/);
  assert.match(viewSource, /#ensureHubLayout/);
  assert.match(viewSource, /Centers never move during normal SSE updates/);
  assert.match(viewSource, /#stepPhysics/);
  assert.match(viewSource, /SETTLE_MS/);
  assert.doesNotMatch(viewSource, /forceSimulation|forceManyBody|forceCollide|d3\./);
});

test("user launchpad visibility is authoritative across later renders", () => {
  assert.match(viewSource, /userDisabledLaunchpads/);
  assert.match(viewSource, /launchpads\.filter\(launchpad => !this\.userDisabledLaunchpads\.has\(launchpad\)\)/);
  assert.doesNotMatch(viewSource, /selectedToken[\s\S]{0,180}enabledLaunchpads\.add/);
});

test("market cap owns bubble radius while liquidity remains a separate halo", () => {
  assert.match(viewSource, /radiusFromMarket/);
  assert.match(viewSource, /this\.marketRange/);
  assert.match(viewSource, /this\.liquidityRange/);
  assert.match(viewSource, /Bubble radius = robust log market cap/);
  assert.match(viewSource, /Liquidity = outer halo/);
  assert.doesNotMatch(viewSource, /Economic mix|SCALE_MODES/);
});

test("meaningful market-cap updates have directed visual semantics", () => {
  assert.match(viewSource, /MARKET_CHANGE_VISIBLE = 0\.03/);
  assert.match(viewSource, /MARKET_CHANGE_STRONG = 0\.10/);
  assert.match(viewSource, /market_cap_updated/);
  assert.match(viewSource, /#drawMarketChangeSignal/);
  assert.match(viewSource, /▲/);
  assert.match(viewSource, /▼/);
});

test("membership spokes are contextual and holder-scaled", () => {
  assert.match(viewSource, /buildHolderScale/);
  assert.match(viewSource, /#drawContextSpokes/);
  assert.match(viewSource, /this\.hoverMint/);
  assert.match(viewSource, /this\.selectedMint/);
});

test("retirement holds before collapse and cluster gap closure is deferred", () => {
  assert.match(viewSource, /RETIRE_HOLD_MS = 700/);
  assert.match(viewSource, /RETIRE_MS = 2400/);
  assert.match(viewSource, /pendingSettleAt/);
  assert.match(viewSource, /#drawRetirement/);
  assert.match(viewSource, /RETIRING/);
  assert.match(viewSource, /token_retired/);
});
