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

test("WP4 consumes only the existing volatile telemetry event types", () => {
  assert.match(telemetrySource, /discovery_tick/);
  assert.match(telemetrySource, /search_lane_tick/);
  assert.match(telemetrySource, /search_flush/);
  assert.match(telemetrySource, /lifecycle_tick/);
  assert.doesNotMatch(telemetrySource, /fetch\(|EventSource|WebSocket/);
  assert.doesNotMatch(flowSource, /fetch\(|EventSource|WebSocket/);
});

test("Operational Flow exposes the real pipeline and monitoring loop", () => {
  assert.match(flowSource, /DISCOVERY/);
  assert.match(flowSource, /SEARCH/);
  assert.match(flowSource, /WRITE/);
  assert.match(flowSource, /LIFECYCLE/);
  assert.match(flowSource, /TRACKING/);
  assert.match(flowSource, /MONITORING LOOP/);
  assert.match(flowSource, /R1–R7/);
});

test("WP4 makes particle semantics explicit and does not claim Mint provenance", () => {
  assert.match(flowSource, /Particles = work pulses/);
  assert.match(flowSource, /no particle represents a Mint/);
  assert.doesNotMatch(flowSource, /sourceMint|mintProvenance|discoveryMint/);
});

test("legacy telemetry tables are removed as the primary presentation", () => {
  assert.doesNotMatch(indexSource, /telemetry-grid/);
  assert.doesNotMatch(indexSource, /telemetry-discovery/);
  assert.doesNotMatch(indexSource, /telemetry-lanes/);
  assert.doesNotMatch(indexSource, /telemetry-flush/);
  assert.doesNotMatch(indexSource, /telemetry-lifecycle/);
});
