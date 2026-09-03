import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const appSource = readFileSync(new URL("../src/observatory/static/js/app.js", import.meta.url), "utf8");
const telemetrySource = readFileSync(new URL("../src/observatory/static/js/telemetry-ui.js", import.meta.url), "utf8");
const flowSource = readFileSync(new URL("../src/observatory/static/js/views/operational-flow-view.js", import.meta.url), "utf8");
const indexSource = readFileSync(new URL("../src/observatory/static/index.html", import.meta.url), "utf8");

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

test("live telemetry events drive event motion while snapshot replay stays static", () => {
  assert.match(telemetrySource, /if \(increment\) \{/);
  assert.match(telemetrySource, /this\.view\.observe\(event\)/);
  assert.match(telemetrySource, /this\.apply\(event, false\)/);
  assert.match(flowSource, /observe\(event\)/);
  assert.match(flowSource, /Discovery bursts = bounded candidate counts/);
  assert.doesNotMatch(flowSource, /#drawParticles/);
});

test("Discovery uses one intake field plus a dedupe gate and new admission output", () => {
  assert.match(flowSource, /ADMISSION/);
  assert.match(flowSource, /intake → dedupe → new/);
  assert.match(flowSource, /response_items/);
  assert.match(flowSource, /unique_candidates/);
  assert.match(flowSource, /new_mints/);
  assert.match(flowSource, /RAW INTAKE/);
  assert.match(flowSource, /DEDUPE/);
  assert.match(flowSource, /new Mints admitted/);
  assert.doesNotMatch(flowSource, /context\.fillText\("UNIQUE"/);
});

test("Discovery burst magnitude is data-driven instead of a single decorative packet", () => {
  assert.match(flowSource, /burstUnits\(raw, 24\)/);
  assert.match(flowSource, /burstUnits\(unique, 22\)/);
  assert.match(flowSource, /#drawBurstTrain/);
  assert.match(flowSource, /latency_ms/);
});

test("Write owns a large condensation region and flushes visibly toward Lifecycle", () => {
  assert.match(flowSource, /regionWidth=252|regionWidth = 252/);
  assert.match(flowSource, /regionHeight=270|regionHeight = 270/);
  assert.match(flowSource, /\["POLLS","VERSIONS","SNAPSHOTS"\]|\["POLLS", "VERSIONS", "SNAPSHOTS"\]/);
  assert.match(flowSource, /search_flush/);
  assert.match(flowSource, /toLifecycle/);
  assert.match(flowSource, /#drawFieldPulse/);
});

test("Lifecycle uses an observed gate sweep and compact retirement sink", () => {
  assert.match(flowSource, /Lifecycle R1–R7/);
  assert.match(flowSource, /gate sweep = observed lifecycle_tick/);
  assert.match(flowSource, /RETIRED/);
  assert.match(flowSource, /sinkY/);
  assert.match(flowSource, /survivorPath/);
});

test("Tracking uses canonical ACTIVE while preserving last Lifecycle count as context", () => {
  assert.match(appSource, /syncFlowPopulation/);
  assert.match(appSource, /telemetryUI\.setActiveCount\(state\.activeTokens\(\)\.length\)/);
  assert.match(telemetrySource, /activeCount: this\.activeCount/);
  assert.match(flowSource, /current Observatory ACTIVE/);
  assert.match(flowSource, /at last Lifecycle cycle/);
  assert.match(flowSource, /ACTIVE TRACKED/);
});

test("Monitoring loop motion is rate-coded rather than one packet per lane event", () => {
  assert.match(flowSource, /aggregateRpm/);
  assert.match(flowSource, /rateIntensity/);
  assert.match(flowSource, /MONITORING LOOP/);
  assert.match(flowSource, /monitoring current encodes observed Search rate/);
  assert.doesNotMatch(flowSource, /recentSearch\.forEach/);
});

test("WP4 count marks never claim Mint provenance", () => {
  assert.match(flowSource, /no dot is a Mint identity/);
  assert.doesNotMatch(flowSource, /sourceMint|mintProvenance|discoveryMint/);
});

test("legacy telemetry tables are removed as the primary presentation", () => {
  assert.doesNotMatch(indexSource, /telemetry-grid/);
  assert.doesNotMatch(indexSource, /telemetry-discovery/);
  assert.doesNotMatch(indexSource, /telemetry-lanes/);
  assert.doesNotMatch(indexSource, /telemetry-flush/);
  assert.doesNotMatch(indexSource, /telemetry-lifecycle/);
});
