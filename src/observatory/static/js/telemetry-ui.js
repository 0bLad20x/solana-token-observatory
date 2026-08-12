function number(value, fallback = "—") {
  return Number.isFinite(value) ? value.toLocaleString() : fallback;
}

function latency(value) {
  return Number.isFinite(value) ? `${Math.round(value)} ms` : "—";
}

function ageLabel(at, now = Date.now()) {
  const timestamp = Date.parse(at || "");
  if (!Number.isFinite(timestamp)) return "—";
  const seconds = Math.max(0, Math.floor((now - timestamp) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  return `${Math.floor(seconds / 60)}m ago`;
}

function row(className, cells) {
  const element = document.createElement("div");
  element.className = className;
  for (const [label, value] of cells) {
    const cell = document.createElement("span");
    cell.dataset.label = label;
    cell.textContent = value;
    element.append(cell);
  }
  return element;
}

function laneNumber(lane) {
  const match = String(lane || "").match(/(\d+)$/);
  return match ? Number(match[1]) : Number.MAX_SAFE_INTEGER;
}

export class TelemetryUI {
  constructor() {
    this.discovery = new Map();
    this.lanes = new Map();
    this.flush = null;
    this.lifecycle = null;
    this.windowSeconds = 600;
    this.receivedCount = 0;
    this.connection = "Connecting";

    this.status = document.querySelector("#telemetry-status");
    this.summary = document.querySelector("#telemetry-summary");
    this.discoveryElement = document.querySelector("#telemetry-discovery");
    this.lanesElement = document.querySelector("#telemetry-lanes");
    this.flushElement = document.querySelector("#telemetry-flush");
    this.lifecycleElement = document.querySelector("#telemetry-lifecycle");
  }

  setConnection(label) {
    this.connection = label;
    if (this.status) this.status.textContent = label;
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
    for (const event of snapshot?.events || []) this.apply(event);
    this.render();
  }

  apply(event) {
    if (!event?.type) return;
    if (event.type === "discovery_tick") this.discovery.set(event.source, event);
    else if (event.type === "search_lane_tick") this.lanes.set(event.lane, event);
    else if (event.type === "search_flush") this.flush = event;
    else if (event.type === "lifecycle_tick") this.lifecycle = event;
    this.receivedCount += 1;
  }

  render(now = Date.now()) {
    if (!this.summary) return;

    this.summary.textContent = `${this.lanes.size} lanes · ${this.discovery.size} discovery paths · ${Math.round(this.windowSeconds / 60)}m volatile window`;
    this.status.textContent = this.connection;

    this.discoveryElement.replaceChildren();
    const discoveryEvents = [...this.discovery.values()].sort((a, b) => String(a.source).localeCompare(String(b.source)));
    if (!discoveryEvents.length) {
      this.discoveryElement.append(row("telemetry-empty", [["state", "Waiting for discovery telemetry…"]]));
    } else {
      for (const event of discoveryEvents) {
        this.discoveryElement.append(row("telemetry-row discovery", [
          ["source", String(event.source)],
          ["response", `${number(event.response_items)} raw`],
          ["unique", `${number(event.unique_candidates)} unique`],
          ["new", `${number(event.new_mints)} new`],
          ["latency", latency(event.latency_ms)],
          ["age", ageLabel(event.at, now)],
        ]));
      }
    }

    this.lanesElement.replaceChildren();
    const lanes = [...this.lanes.values()].sort((a, b) => laneNumber(a.lane) - laneNumber(b.lane));
    if (!lanes.length) {
      this.lanesElement.append(row("telemetry-empty", [["state", "Waiting for Jupiter Search lanes…"]]));
    } else {
      for (const event of lanes) {
        const status = event.status == null ? "ERR" : String(event.status);
        this.lanesElement.append(row("telemetry-lane", [
          ["lane", String(event.lane)],
          ["rpm", `${number(event.rpm60)} rpm`],
          ["latency", latency(event.latency_ms)],
          ["io", `${number(event.requested)}/${number(event.received)}`],
          ["status", status],
          ["age", ageLabel(event.at, now)],
        ]));
      }
    }

    this.flushElement.replaceChildren();
    if (!this.flush) {
      this.flushElement.append(row("telemetry-empty", [["state", "Waiting for WriteQueue flush…"]]));
    } else {
      const event = this.flush;
      this.flushElement.append(row("telemetry-row flush", [
        ["flow", `${number(event.polled_tokens)} polls → ${number(event.source_versions)} versions → ${number(event.new_snapshots)} snapshots`],
        ["queue", `q ${number(event.queue_size)}`],
        ["write", latency(event.write_ms)],
        ["age", ageLabel(event.at, now)],
      ]));
    }

    this.lifecycleElement.replaceChildren();
    if (!this.lifecycle) {
      this.lifecycleElement.append(row("telemetry-empty", [["state", "Waiting for lifecycle cycle…"]]));
    } else {
      const event = this.lifecycle;
      const breakdown = event.breakdown || {};
      const affectedLabel = event.apply ? "retired" : "candidates";
      this.lifecycleElement.append(row("telemetry-row lifecycle", [
        ["active", `${number(event.active_remaining)} active`],
        ["affected", `${number(event.affected_count)} ${affectedLabel}`],
        ["rules", `R1 ${number(breakdown.rule1, "0")} · R2 ${number(breakdown.rule2, "0")} · R3 ${number(breakdown.rule3, "0")} · R4 ${number(breakdown.rule4, "0")} · R5 ${number(breakdown.rule5, "0")}`],
        ["duration", latency(event.duration_ms)],
        ["age", ageLabel(event.at, now)],
      ]));
    }
  }
}
