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

test("WP3 keeps stable launchpad centers with a bounded custom physics solver", () => {
  assert.match(viewSource, /packClusters/);
  assert.match(viewSource, /#ensureHubLayout/);
  assert.match(viewSource, /#stepPhysics/);
  assert.match(viewSource, /activeLaunchpads/);
  assert.match(viewSource, /PHYSICS_STABLE_FRAMES/);
  assert.doesNotMatch(viewSource, /forceSimulation|forceManyBody|forceCollide|d3\./);
});

test("user launchpad visibility is authoritative across later renders", () => {
  assert.match(viewSource, /userDisabledLaunchpads/);
  assert.match(viewSource, /launchpads\.filter\(launchpad => !this\.userDisabledLaunchpads\.has\(launchpad\)\)/);
  assert.doesNotMatch(viewSource, /selectedToken[\s\S]{0,180}enabledLaunchpads\.add/);
});

test("age is a logarithmic soft radial force rather than a fixed position", () => {
  assert.match(viewSource, /CORE_AGE_DAYS = 30/);
  assert.match(viewSource, /AGE_SCALE_DAYS = 0\.25/);
  assert.match(viewSource, /freshnessFromAge/);
  assert.match(viewSource, /currentAgeSeconds/);
  assert.match(viewSource, /preferredRadialDistance/);
  assert.match(viewSource, /AGE_SPRING/);
  assert.match(viewSource, /\(preferred - distance\) \* AGE_SPRING/);
  assert.match(viewSource, /Age = soft radial gravity · 30d\+ core attraction/);
  assert.doesNotMatch(viewSource, /CORE_RADIAL_FRACTION|AGE_RADIAL_SPREAD_FRACTION|anchorX|anchorY/);
});

test("collision uses force, damping and size-dependent mass instead of position correction", () => {
  assert.match(viewSource, /COLLISION_SPRING/);
  assert.match(viewSource, /VELOCITY_DAMPING/);
  assert.match(viewSource, /massFromRadius/);
  assert.match(viewSource, /collisionGap/);
  assert.match(viewSource, /node\.fx \+= nx \* force/);
  assert.match(viewSource, /node\.vx = \(node\.vx \+ ax \* step\) \* damping/);
  assert.doesNotMatch(viewSource, /node\.x \+= nx \* overlap|other\.x -= nx \* overlap/);
});

test("cluster capacity follows current bubble area and can grow or shrink", () => {
  assert.match(viewSource, /CLUSTER_PACKING_DENSITY/);
  assert.match(viewSource, /targetRadius: spec\.radius/);
  assert.match(viewSource, /hub\.targetRadius = spec\.radius/);
  assert.match(viewSource, /targetHubRadius - hub\.radius/);
  assert.doesNotMatch(viewSource, /hub\.radius = Math\.max\(hub\.radius, spec\.radius\)/);
});

test("market cap owns bubble radius while liquidity is contextual", () => {
  assert.match(viewSource, /radiusFromMarket/);
  assert.match(viewSource, /this\.marketRange/);
  assert.match(viewSource, /this\.liquidityRange/);
  assert.match(viewSource, /Bubble radius = robust log market cap/);
  assert.match(viewSource, /Liquidity = focus halo/);
  assert.match(viewSource, /\(selected \|\| hovered\) && node\.liquidityScore != null/);
  assert.doesNotMatch(viewSource, /Liquidity = outer halo/);
  assert.doesNotMatch(viewSource, /Economic mix|SCALE_MODES/);
});

test("new tokens start near their age preference without owning an angular anchor", () => {
  assert.match(viewSource, /initialPositionForNode/);
  assert.match(viewSource, /unitHash\(`\$\{node\.mint\}:angle`\)/);
  assert.doesNotMatch(viewSource, /this\.slots|nextSlots|slot \* GOLDEN_ANGLE/);
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

test("retirement holds before the remaining cluster is re-energized", () => {
  assert.match(viewSource, /RETIRE_HOLD_MS = 700/);
  assert.match(viewSource, /RETIRE_MS = 2400/);
  assert.match(viewSource, /pendingSettleAt/);
  assert.match(viewSource, /#activatePendingSettles/);
  assert.match(viewSource, /#drawRetirement/);
  assert.match(viewSource, /RETIRING/);
  assert.match(viewSource, /token_retired/);
});
