import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const appSource = readFileSync(
  new URL("../src/observatory/static/js/app.js", import.meta.url),
  "utf8",
);
const telemetrySource = readFileSync(
  new URL("../src/observatory/static/js/telemetry-ui.js", import.meta.url),
  "utf8",
);
const flowSource = readFileSync(
  new URL("../src/observatory/static/js/views/operational-flow-view.js", import.meta.url),
  "utf8",
);
const indexSource = readFileSync(
  new URL("../src/observatory/static/index.html", import.meta.url),
  "utf8",
);

test("WP4 adds Operational Flow as a primary view without replacing Token Universe", () => {
  assert.match(indexSource, /id="view-token-universe"/);
  assert.match(indexSource, /id="view-operational-flow"/);
  assert.match(indexSource, /id="universe-stage"/);
  assert.match(indexSource, /id="operational-flow-stage"/);
  assert.match(appSource, /setPrimaryMode\("flow"\)/);
  assert.match(appSource, /TokenUniverseView/);
});

test("WP4 presentation cannot gate the functional Observatory streams", () => {
  const universeConnect = appSource.indexOf("connectUniverseStream({");
  const telemetryConnect = appSource.indexOf("connectTelemetryStream({");
  const flowInit = appSource.indexOf("ensureOperationalFlow().catch");

  assert.ok(universeConnect >= 0);
  assert.ok(telemetryConnect >= 0);
  assert.ok(flowInit >= 0);
  assert.ok(universeConnect < flowInit);
  assert.ok(telemetryConnect < flowInit);
  assert.match(appSource, /operational_flow_init_failed/);
});

test("WP4 consumes only the existing volatile telemetry event types", () => {
  assert.match(telemetrySource, /discovery_tick/);
  assert.match(telemetrySource, /search_lane_tick/);
  assert.match(telemetrySource, /search_flush/);
  assert.match(telemetrySource, /lifecycle_tick/);
  assert.doesNotMatch(telemetrySource, /fetch\(|EventSource|WebSocket/);
  assert.doesNotMatch(flowSource, /fetch\(|EventSource|WebSocket/);
});

test("live telemetry events drive motion while snapshot replay stays static", () => {
  assert.match(telemetrySource, /if \(increment\) \{/);
  assert.match(telemetrySource, /this\.view\.observe\(event\)/);
  assert.match(telemetrySource, /this\.apply\(event, false\)/);
  assert.match(flowSource, /observe\(event\)/);
  assert.match(flowSource, /Motion = observed work/);
  assert.doesNotMatch(flowSource, /#drawParticles/);
});

test("Discovery visualizes the real raw unique new admission funnel", () => {
  assert.match(flowSource, /MINT FILTER/);
  assert.match(flowSource, /raw → unique → new/);
  assert.match(flowSource, /response_items/);
  assert.match(flowSource, /unique_candidates/);
  assert.match(flowSource, /new_mints/);
  assert.match(flowSource, /new Mints admitted/);
});

test("Operational Flow exposes Search Write Lifecycle and compact monitoring return", () => {
  assert.match(flowSource, /SEARCH/);
  assert.match(flowSource, /POLLS/);
  assert.match(flowSource, /VERSIONS/);
  assert.match(flowSource, /SNAPSHOTS/);
  assert.match(flowSource, /Lifecycle R1–R7/);
  assert.match(flowSource, /RETIRED/);
  assert.match(flowSource, /TRACKING → SEARCH MONITORING/);
});

test("WP4 count marks never claim Mint provenance", () => {
  assert.match(flowSource, /candidate dots = bounded counts, never Mint identities/);
  assert.doesNotMatch(flowSource, /sourceMint|mintProvenance|discoveryMint/);
});

test("legacy telemetry tables are removed as the primary presentation", () => {
  assert.doesNotMatch(indexSource, /telemetry-grid/);
  assert.doesNotMatch(indexSource, /telemetry-discovery/);
  assert.doesNotMatch(indexSource, /telemetry-lanes/);
  assert.doesNotMatch(indexSource, /telemetry-flush/);
  assert.doesNotMatch(indexSource, /telemetry-lifecycle/);
});
