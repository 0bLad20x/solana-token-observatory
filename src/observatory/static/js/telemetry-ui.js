import { OperationalFlowView } from "./views/operational-flow-view.js";

function laneNumber(lane) {
  const match = String(lane || "").match(/(\d+)$/);
  return match ? Number(match[1]) : Number.MAX_SAFE_INTEGER;
}

export class TelemetryUI {
  constructor(stage) {
    this.discovery = new Map();
    this.lanes = new Map();
    this.flush = null;
    this.lifecycle = null;
    this.windowSeconds = 600;
    this.receivedCount = 0;
    this.connection = "Connecting";
    this.view = new OperationalFlowView(stage);
  }

  async init() {
    await this.view.init();
    this.view.setVisible(false);
  }

  setVisible(visible) {
    this.view.setVisible(visible);
    if (visible) this.render();
  }

  setConnection(label) {
    this.connection = label;
  }

  reset() {
    this.discovery.clear();
    this.lanes.clear();
    this.flush = null;
    this.lifecycle = null;
  }

  load(snapshot) {
    this.reset();
    this.windowSeconds = Number(snapshot?.window_seconds) || 600;
    this.receivedCount = Number(snapshot?.received_count) || 0;
    for (const event of snapshot?.events || []) this.apply(event, false);
    this.render();
  }

  apply(event, increment = true) {
    if (!event?.type) return;
    if (event.type === "discovery_tick") this.discovery.set(event.source, event);
    else if (event.type === "search_lane_tick") this.lanes.set(event.lane, event);
    else if (event.type === "search_flush") this.flush = event;
    else if (event.type === "lifecycle_tick") this.lifecycle = event;

    if (increment) {
      this.receivedCount += 1;
      // Only live telemetry events create motion. Snapshot replay establishes
      // current state without fabricating historical animation.
      this.view.observe(event);
    }
  }

  render(now = Date.now()) {
    this.view.render({
      now,
      connection: this.connection,
      windowSeconds: this.windowSeconds,
      receivedCount: this.receivedCount,
      discovery: [...this.discovery.values()].sort((a, b) => String(a.source).localeCompare(String(b.source))),
      lanes: [...this.lanes.values()].sort((a, b) => laneNumber(a.lane) - laneNumber(b.lane)),
      flush: this.flush,
      lifecycle: this.lifecycle,
    });
  }
}
