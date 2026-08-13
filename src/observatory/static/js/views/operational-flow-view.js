const TAU = Math.PI * 2;
const FLOW_PADDING_X = 46;
const FLOW_PADDING_Y = 70;
const STAGE_DOT_RADIUS = 3;
const MAX_TRANSIENTS = 240;
const DISCOVERY_BURST_MS = 1350;
const SEARCH_PACKET_MS = 1500;
const WRITE_BURST_MS = 1550;
const LIFECYCLE_BURST_MS = 2600;

function finite(value, fallback = 0) {
  return Number.isFinite(value) ? value : fallback;
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function formatNumber(value) {
  return Number.isFinite(value) ? Math.round(value).toLocaleString() : "—";
}

function formatMs(value) {
  return Number.isFinite(value) ? `${Math.round(value)} ms` : "—";
}

function hashString(value) {
  let hash = 2166136261;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

function bezierPoint(path, t) {
  const mt = 1 - t;
  return {
    x: mt ** 3 * path.x0 + 3 * mt ** 2 * t * path.x1 + 3 * mt * t ** 2 * path.x2 + t ** 3 * path.x3,
    y: mt ** 3 * path.y0 + 3 * mt ** 2 * t * path.y1 + 3 * mt * t ** 2 * path.y2 + t ** 3 * path.y3,
  };
}

function curve(x0, y0, x3, y3, bend = 0.42) {
  const dx = x3 - x0;
  return { x0, y0, x1: x0 + dx * bend, y1: y0, x2: x3 - dx * bend, y2: y3, x3, y3 };
}

function drawCurve(context, path) {
  context.beginPath();
  context.moveTo(path.x0, path.y0);
  context.bezierCurveTo(path.x1, path.y1, path.x2, path.y2, path.x3, path.y3);
  context.stroke();
}

function stageColor(kind) {
  if (kind === "discovery") return "20,241,217";
  if (kind === "filter") return "49,196,255";
  if (kind === "search") return "73,217,255";
  if (kind === "write") return "153,69,255";
  if (kind === "lifecycle") return "214,88,255";
  if (kind === "tracking") return "20,241,217";
  return "146,155,173";
}

function eventId(event) {
  if (!event?.type) return "unknown";
  if (event.type === "discovery_tick") return `${event.type}:${event.source}:${event.at}`;
  if (event.type === "search_lane_tick") return `${event.type}:${event.lane}:${event.at}`;
  return `${event.type}:${event.at}`;
}

function boundedDots(value, maxValue, limit = 36) {
  if (!Number.isFinite(value) || value <= 0) return 0;
  if (!Number.isFinite(maxValue) || maxValue <= 0) return 1;
  return clamp(Math.round((Math.sqrt(value) / Math.sqrt(maxValue)) * limit), 1, limit);
}

export class OperationalFlowView {
  constructor(stage) {
    this.stage = stage;
    this.canvas = null;
    this.context = null;
    this.tooltip = null;
    this.meta = null;
    this.model = null;
    this.visible = false;
    this.frame = null;
    this.hitTargets = [];
    this.resizeObserver = null;
    this.transients = [];
    this.seenEvents = new Set();
  }

  async init() {
    this.stage.replaceChildren();
    this.stage.classList.add("operational-flow-stage");

    const chrome = document.createElement("div");
    chrome.className = "flow-chrome";

    const title = document.createElement("div");
    title.className = "flow-title";
    const eyebrow = document.createElement("span");
    eyebrow.className = "flow-eyebrow";
    eyebrow.textContent = "LIVE OPERATIONAL FLOW";
    const heading = document.createElement("strong");
    heading.textContent = "Discovery → Mint filter → Search → Write → Lifecycle → Tracking";
    title.append(eyebrow, heading);

    this.meta = document.createElement("div");
    this.meta.className = "flow-meta";
    this.meta.textContent = "Waiting for telemetry…";
    chrome.append(title, this.meta);

    this.canvas = document.createElement("canvas");
    this.canvas.className = "flow-canvas";
    this.canvas.setAttribute("aria-label", "Live operational pipeline flow");
    this.context = this.canvas.getContext("2d");

    const legend = document.createElement("div");
    legend.className = "flow-legend";
    legend.textContent = "Motion = observed work · candidate dots = bounded counts, never Mint identities · no decorative continuous particles";

    this.tooltip = document.createElement("div");
    this.tooltip.className = "flow-tooltip hidden";
    this.stage.append(chrome, this.canvas, legend, this.tooltip);

    this.canvas.addEventListener("pointermove", event => this.#pointerMove(event));
    this.canvas.addEventListener("pointerleave", () => this.#hideTooltip());
    this.resizeObserver = new ResizeObserver(() => this.#resize());
    this.resizeObserver.observe(this.stage);
    this.#resize();
  }

  destroy() {
    if (this.frame) cancelAnimationFrame(this.frame);
    this.frame = null;
    this.resizeObserver?.disconnect();
    this.stage.replaceChildren();
  }

  setVisible(visible) {
    this.visible = Boolean(visible);
    this.stage.classList.toggle("hidden", !this.visible);
    if (this.visible) {
      this.#resize();
      this.#schedule();
    } else if (this.frame) {
      cancelAnimationFrame(this.frame);
      this.frame = null;
    }
  }

  observe(event) {
    if (!event?.type) return;
    const id = eventId(event);
    if (this.seenEvents.has(id)) return;
    this.seenEvents.add(id);
    if (this.seenEvents.size > 4000) this.seenEvents.clear();

    const now = performance.now();
    const duration = event.type === "discovery_tick"
      ? DISCOVERY_BURST_MS
      : event.type === "search_lane_tick"
        ? SEARCH_PACKET_MS
        : event.type === "search_flush"
          ? WRITE_BURST_MS
          : event.type === "lifecycle_tick"
            ? LIFECYCLE_BURST_MS
            : 0;
    if (!duration) return;

    this.transients.push({ id, event: { ...event }, startedAt: now, duration });
    if (this.transients.length > MAX_TRANSIENTS) {
      this.transients.splice(0, this.transients.length - MAX_TRANSIENTS);
    }
    if (this.visible) this.#schedule();
  }

  render(model) {
    this.model = model;
    if (this.meta) {
      const laneCount = model?.lanes?.length || 0;
      const discoveryCount = model?.discovery?.length || 0;
      const minutes = Math.round((model?.windowSeconds || 600) / 60);
      this.meta.textContent = `${laneCount} lanes · ${discoveryCount} discovery paths · ${minutes}m volatile · ${model?.connection || "Connecting"}`;
    }
    if (this.visible) this.#schedule();
  }

  #resize() {
    if (!this.canvas || !this.context) return;
    const rect = this.stage.getBoundingClientRect();
    const width = Math.max(720, Math.floor(rect.width));
    const height = Math.max(560, Math.floor(rect.height));
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const pixelWidth = Math.round(width * dpr);
    const pixelHeight = Math.round(height * dpr);
    if (this.canvas.width === pixelWidth && this.canvas.height === pixelHeight) return;
    this.canvas.width = pixelWidth;
    this.canvas.height = pixelHeight;
    this.canvas.style.width = `${width}px`;
    this.canvas.style.height = `${height}px`;
    this.canvas.dataset.dpr = String(dpr);
  }

  #schedule() {
    if (!this.visible || this.frame) return;
    this.frame = requestAnimationFrame(timestamp => {
      this.frame = null;
      this.#draw(timestamp);
      if (this.visible) this.#schedule();
    });
  }

  #geometry() {
    const dpr = Number(this.canvas?.dataset.dpr || 1);
    const width = (this.canvas?.width || 1) / dpr;
    const height = (this.canvas?.height || 1) / dpr;
    const innerWidth = width - FLOW_PADDING_X * 2;
    const top = FLOW_PADDING_Y + 60;
    const bottom = height - FLOW_PADDING_Y - 34;
    const center = (top + bottom) / 2;
    return {
      width,
      height,
      top,
      bottom,
      center,
      sourceX: FLOW_PADDING_X + innerWidth * 0.035,
      rawX: FLOW_PADDING_X + innerWidth * 0.13,
      uniqueX: FLOW_PADDING_X + innerWidth * 0.205,
      newX: FLOW_PADDING_X + innerWidth * 0.265,
      searchX: FLOW_PADDING_X + innerWidth * 0.355,
      writeX: FLOW_PADDING_X + innerWidth * 0.565,
      lifecycleX: FLOW_PADDING_X + innerWidth * 0.755,
      trackingX: FLOW_PADDING_X + innerWidth * 0.925,
    };
  }

  #draw(timestamp) {
    if (!this.canvas || !this.context) return;
    this.#resize();
    this.transients = this.transients.filter(item => timestamp - item.startedAt <= item.duration);

    const context = this.context;
    const dpr = Number(this.canvas.dataset.dpr || 1);
    const g = this.#geometry();
    context.setTransform(dpr, 0, 0, dpr, 0, 0);
    context.clearRect(0, 0, g.width, g.height);
    this.hitTargets = [];

    this.#drawBackground(context, g);
    this.#drawLayerHeadings(context, g);
    this.#drawDiscovery(context, g, timestamp);
    this.#drawSearch(context, g, timestamp);
    this.#drawWrite(context, g, timestamp);
    this.#drawLifecycle(context, g, timestamp);
    this.#drawTracking(context, g, timestamp);
  }

  #drawBackground(context, g) {
    const gradient = context.createLinearGradient(0, 0, g.width, g.height);
    gradient.addColorStop(0, "rgba(8,13,24,.98)");
    gradient.addColorStop(0.5, "rgba(8,12,23,.96)");
    gradient.addColorStop(1, "rgba(7,15,25,.98)");
    context.fillStyle = gradient;
    context.fillRect(0, 0, g.width, g.height);

    const glow = context.createRadialGradient(g.writeX, g.center, 10, g.writeX, g.center, Math.min(g.width, g.height) * 0.5);
    glow.addColorStop(0, "rgba(153,69,255,.12)");
    glow.addColorStop(0.48, "rgba(73,217,255,.035)");
    glow.addColorStop(1, "rgba(0,0,0,0)");
    context.fillStyle = glow;
    context.fillRect(0, 0, g.width, g.height);
  }

  #drawLayerHeadings(context, g) {
    const filterX = (g.rawX + g.newX) / 2;
    const headings = [
      ["DISCOVERY", g.sourceX, "discovery", this.#stageMetric("discovery")],
      ["MINT FILTER", filterX, "filter", "raw → unique → new"],
      ["SEARCH", g.searchX, "search", this.#stageMetric("search")],
      ["WRITE", g.writeX, "write", this.#stageMetric("write")],
      ["LIFECYCLE", g.lifecycleX, "lifecycle", this.#stageMetric("lifecycle")],
      ["TRACKING", g.trackingX, "tracking", this.#stageMetric("tracking")],
    ];
    context.textAlign = "center";
    context.textBaseline = "middle";
    for (const [label, x, kind, metric] of headings) {
      context.fillStyle = `rgba(${stageColor(kind)},.64)`;
      context.font = "700 10px Inter, system-ui, sans-serif";
      context.fillText(label, x, FLOW_PADDING_Y + 8);
      context.fillStyle = "rgba(243,245,248,.92)";
      context.font = "700 12px Inter, system-ui, sans-serif";
      context.fillText(metric, x, FLOW_PADDING_Y + 29);
    }
  }

  #stageMetric(kind) {
    const model = this.model || {};
    if (kind === "discovery") {
      const raw = (model.discovery || []).reduce((sum, event) => sum + finite(event.response_items), 0);
      const fresh = (model.discovery || []).reduce((sum, event) => sum + finite(event.new_mints), 0);
      return `${formatNumber(raw)} raw · ${formatNumber(fresh)} new`;
    }
    if (kind === "search") {
      const rpm = (model.lanes || []).reduce((sum, event) => sum + finite(event.rpm60), 0);
      return `${formatNumber(rpm)} rpm`;
    }
    if (kind === "write") return model.flush ? `${formatNumber(model.flush.new_snapshots)} snapshots` : "waiting";
    if (kind === "lifecycle") return model.lifecycle ? `${formatNumber(model.lifecycle.affected_count)} affected` : "waiting";
    if (kind === "tracking") return model.lifecycle ? `${formatNumber(model.lifecycle.active_remaining)} tracking` : "waiting";
    return "—";
  }

  #drawDiscovery(context, g, timestamp) {
    const events = this.model?.discovery || [];
    const count = Math.max(events.length, 1);
    const span = Math.min(g.bottom - g.top - 80, 400);
    const startY = g.center - span / 2;
    const rawMax = Math.max(...events.map(event => finite(event.response_items)), 1);
    const uniqueMax = Math.max(...events.map(event => finite(event.unique_candidates)), 1);
    const newMax = Math.max(...events.map(event => finite(event.new_mints)), 1);

    if (!events.length) {
      this.#drawEmptyLayer(context, g.sourceX, g.center, "waiting for discovery");
      return;
    }

    events.forEach((event, index) => {
      const y = count === 1 ? g.center : startY + (span * index) / Math.max(count - 1, 1);
      const raw = finite(event.response_items);
      const unique = finite(event.unique_candidates);
      const fresh = finite(event.new_mints);
      const livePulse = this.transients.findLast(item => item.event.type === "discovery_tick" && item.event.source === event.source);
      const pulseProgress = livePulse ? clamp((timestamp - livePulse.startedAt) / livePulse.duration, 0, 1) : null;

      context.textAlign = "right";
      context.fillStyle = "rgba(243,245,248,.90)";
      context.font = "650 10px Inter, system-ui, sans-serif";
      context.fillText(String(event.source), g.sourceX - 14, y - 2);
      context.fillStyle = "rgba(146,155,173,.64)";
      context.font = "9px Inter, system-ui, sans-serif";
      context.fillText(`${formatNumber(raw)} raw`, g.sourceX - 14, y + 12);

      context.beginPath();
      context.arc(g.sourceX, y, 7, 0, TAU);
      context.fillStyle = "rgba(9,23,34,.98)";
      context.fill();
      context.strokeStyle = "rgba(20,241,217,.68)";
      context.stroke();

      this.#drawCountField(context, g.rawX, y, raw, rawMax, "20,241,217", 18);
      this.#drawCountField(context, g.uniqueX, y, unique, uniqueMax, "49,196,255", 18);
      this.#drawCountField(context, g.newX, y, fresh, newMax, "73,217,255", 14);

      const sourceToRaw = curve(g.sourceX + 9, y, g.rawX - 17, y, 0.4);
      const rawToUnique = curve(g.rawX + 18, y, g.uniqueX - 18, y, 0.4);
      const uniqueToNew = curve(g.uniqueX + 18, y, g.newX - 16, y, 0.4);
      const newToSearch = curve(g.newX + 16, y, g.searchX - 38, g.center + (y - g.center) * 0.42, 0.48);
      for (const [path, alpha] of [[sourceToRaw, .12], [rawToUnique, .14], [uniqueToNew, .16], [newToSearch, fresh > 0 ? .30 : .08]]) {
        context.strokeStyle = `rgba(20,241,217,${alpha})`;
        context.lineWidth = 1;
        drawCurve(context, path);
      }

      if (pulseProgress != null) {
        const phases = [
          [sourceToRaw, clamp(pulseProgress * 3.2, 0, 1), "20,241,217", raw],
          [rawToUnique, clamp(pulseProgress * 3.2 - .75, 0, 1), "49,196,255", unique],
          [uniqueToNew, clamp(pulseProgress * 3.2 - 1.5, 0, 1), "73,217,255", fresh],
          [newToSearch, clamp(pulseProgress * 3.2 - 2.2, 0, 1), "73,217,255", fresh],
        ];
        for (const [path, progress, color, value] of phases) {
          if (progress <= 0 || progress >= 1 || value <= 0) continue;
          this.#drawPacket(context, path, progress, color, clamp(2 + Math.log10(value + 1) * 1.8, 2, 7));
        }
      }

      this.hitTargets.push({
        x: g.sourceX - 105,
        y: y - 23,
        width: g.newX - g.sourceX + 125,
        height: 46,
        title: String(event.source),
        lines: [
          `${formatNumber(raw)} raw intake`,
          `${formatNumber(unique)} unique candidates`,
          `${formatNumber(fresh)} new Mints admitted`,
          `latency ${formatMs(event.latency_ms)}`,
        ],
      });
    });

    context.textAlign = "center";
    context.fillStyle = "rgba(146,155,173,.48)";
    context.font = "700 8px Inter, system-ui, sans-serif";
    context.fillText("RAW", g.rawX, g.bottom - 4);
    context.fillText("UNIQUE", g.uniqueX, g.bottom - 4);
    context.fillText("NEW", g.newX, g.bottom - 4);
  }

  #drawCountField(context, x, y, value, maxValue, color, limit) {
    const dots = boundedDots(value, maxValue, limit);
    const columns = dots > 10 ? 5 : 4;
    const gap = 6;
    const rows = Math.ceil(Math.max(dots, 1) / columns);
    for (let index = 0; index < dots; index += 1) {
      const col = index % columns;
      const row = Math.floor(index / columns);
      const px = x + (col - (columns - 1) / 2) * gap;
      const py = y + (row - (rows - 1) / 2) * gap;
      context.beginPath();
      context.arc(px, py, 1.8, 0, TAU);
      context.fillStyle = `rgba(${color},${0.34 + 0.5 * (index + 1) / Math.max(dots, 1)})`;
      context.fill();
    }
    if (!dots) {
      context.beginPath();
      context.arc(x, y, 2, 0, TAU);
      context.strokeStyle = `rgba(${color},.18)`;
      context.stroke();
    }
  }

  #searchLayout(g) {
    const lanes = this.model?.lanes || [];
    const laneCount = Math.max(lanes.length, 1);
    const rows = Math.min(16, Math.ceil(Math.sqrt(laneCount * 2)));
    const columns = Math.ceil(laneCount / rows);
    const cellX = 12;
    const cellY = 16;
    const width = Math.max(36, columns * cellX);
    const height = Math.max(130, rows * cellY);
    const left = g.searchX - width / 2;
    const top = g.center - height / 2;
    return { lanes, rows, columns, cellX, cellY, width, height, left, top };
  }

  #drawSearch(context, g, timestamp) {
    const layout = this.#searchLayout(g);
    const { lanes, rows, cellX, cellY, width, height, left, top } = layout;

    context.fillStyle = "rgba(10,19,32,.70)";
    context.strokeStyle = "rgba(73,217,255,.20)";
    context.lineWidth = 1;
    context.beginPath();
    context.roundRect(left - 20, top - 22, width + 40, height + 44, 18);
    context.fill();
    context.stroke();

    if (!lanes.length) {
      this.#drawEmptyLayer(context, g.searchX, g.center, "waiting for lanes");
      return;
    }

    const lanePositions = new Map();
    lanes.forEach((lane, index) => {
      const row = index % rows;
      const column = Math.floor(index / rows);
      const x = left + column * cellX + cellX / 2;
      const y = top + row * cellY + cellY / 2;
      lanePositions.set(String(lane.lane), { x, y, row });
      const rpm = finite(lane.rpm60);
      const statusGood = lane.status === 200;
      const intensity = clamp(rpm / 58, 0.15, 1);
      context.beginPath();
      context.arc(x, y, STAGE_DOT_RADIUS + intensity * 1.5, 0, TAU);
      context.fillStyle = statusGood
        ? `rgba(73,217,255,${0.34 + intensity * 0.60})`
        : "rgba(255,92,119,.92)";
      context.fill();

      const path = curve(x, y, g.writeX - 86, g.center + (row / Math.max(rows - 1, 1) - 0.5) * 235, 0.55);
      context.strokeStyle = statusGood
        ? `rgba(73,217,255,${0.035 + intensity * 0.08})`
        : "rgba(255,92,119,.15)";
      context.lineWidth = 0.6 + intensity * 0.7;
      drawCurve(context, path);
    });

    const searchBursts = this.transients.filter(item => item.event.type === "search_lane_tick");
    for (const burst of searchBursts) {
      const lane = burst.event;
      const position = lanePositions.get(String(lane.lane));
      if (!position) continue;
      const latency = clamp(finite(lane.latency_ms, 900), 120, 2600);
      const duration = clamp(latency * 1.15, 280, 1500);
      const progress = clamp((timestamp - burst.startedAt) / duration, 0, 1);
      if (progress <= 0 || progress >= 1) continue;
      const path = curve(position.x, position.y, g.writeX - 86, g.center + (position.row / Math.max(rows - 1, 1) - 0.5) * 235, 0.55);
      const widthScale = clamp(finite(lane.requested) / 100, 0.25, 1);
      const color = lane.status === 200 ? "73,217,255" : "255,92,119";
      this.#drawPacket(context, path, progress, color, 2.5 + widthScale * 3.5);
    }

    this.hitTargets.push({
      x: left - 20,
      y: top - 22,
      width: width + 40,
      height: height + 44,
      title: "Jupiter Search",
      lines: [
        `${lanes.length} parallel lanes`,
        `${formatNumber(lanes.reduce((sum, lane) => sum + finite(lane.rpm60), 0))} aggregate rpm`,
        `median latency ${formatMs(this.#median(lanes.map(lane => lane.latency_ms)))}`,
        "live packets = observed lane work",
      ],
    });
  }

  #drawWrite(context, g, timestamp) {
    const flush = this.model?.flush;
    const values = flush
      ? [finite(flush.polled_tokens), finite(flush.source_versions), finite(flush.new_snapshots)]
      : [0, 0, 0];
    const labels = ["POLLS", "VERSIONS", "SNAPSHOTS"];
    const xs = [g.writeX - 62, g.writeX, g.writeX + 62];
    const maxValue = Math.max(...values, 1);
    const fieldWidth = 42;
    const fieldHeight = 180;

    for (let index = 0; index < 3; index += 1) {
      const ratio = Math.sqrt(values[index] / maxValue);
      const maxDots = 70;
      const dots = boundedDots(values[index], maxValue, maxDots);
      const columns = 7;
      const rows = 10;
      for (let slot = 0; slot < maxDots; slot += 1) {
        const row = slot % rows;
        const col = Math.floor(slot / rows);
        const x = xs[index] + (col - 3) * 7;
        const y = g.center + (row - 4.5) * 13;
        const active = slot < dots;
        context.beginPath();
        context.arc(x, y, active ? 3.0 : 1.6, 0, TAU);
        context.fillStyle = active
          ? `rgba(153,69,255,${0.36 + ratio * 0.58})`
          : "rgba(153,69,255,.045)";
        context.fill();
      }

      context.textAlign = "center";
      context.fillStyle = "rgba(146,155,173,.62)";
      context.font = "700 8px Inter, system-ui, sans-serif";
      context.fillText(labels[index], xs[index], g.center + fieldHeight / 2 + 9);
      context.fillStyle = "rgba(243,245,248,.94)";
      context.font = "800 12px Inter, system-ui, sans-serif";
      context.fillText(formatNumber(values[index]), xs[index], g.center + fieldHeight / 2 + 25);
    }

    if (flush) {
      for (let index = 0; index < 2; index += 1) {
        const ratio = clamp(values[index + 1] / Math.max(values[index], 1), 0, 1);
        const path = curve(xs[index] + fieldWidth / 2, g.center, xs[index + 1] - fieldWidth / 2, g.center, 0.46);
        context.strokeStyle = `rgba(153,69,255,${0.10 + ratio * 0.32})`;
        context.lineWidth = 1.2 + ratio * 5.5;
        drawCurve(context, path);
      }
    }

    const burst = this.transients.findLast(item => item.event.type === "search_flush");
    if (burst) {
      const p = clamp((timestamp - burst.startedAt) / burst.duration, 0, 1);
      const first = curve(xs[0] + fieldWidth / 2, g.center, xs[1] - fieldWidth / 2, g.center, 0.46);
      const second = curve(xs[1] + fieldWidth / 2, g.center, xs[2] - fieldWidth / 2, g.center, 0.46);
      const p1 = clamp(p * 2, 0, 1);
      const p2 = clamp(p * 2 - 1, 0, 1);
      if (p1 > 0 && p1 < 1) this.#drawPacket(context, first, p1, "183,124,255", 7);
      if (p2 > 0 && p2 < 1) this.#drawPacket(context, second, p2, "183,124,255", 5);
    }

    this.hitTargets.push({
      x: g.writeX - 96,
      y: g.center - 110,
      width: 192,
      height: 230,
      title: "WriteQueue condensation",
      lines: flush ? [
        `${formatNumber(flush.polled_tokens)} polls`,
        `${formatNumber(flush.source_versions)} source versions`,
        `${formatNumber(flush.new_snapshots)} new snapshots`,
        `queue ${formatNumber(flush.queue_size)} · write ${formatMs(flush.write_ms)}`,
      ] : ["Waiting for first flush"],
    });

    const toLifecycle = curve(g.writeX + 92, g.center, g.lifecycleX - 82, g.center, 0.5);
    context.strokeStyle = "rgba(183,124,255,.15)";
    context.lineWidth = 2;
    drawCurve(context, toLifecycle);
    if (burst) {
      const progress = clamp((timestamp - burst.startedAt) / burst.duration, 0, 1);
      if (progress > .48 && progress < 1) this.#drawPacket(context, toLifecycle, (progress - .48) / .52, "183,124,255", 5);
    }
  }

  #drawLifecycle(context, g, timestamp) {
    const lifecycle = this.model?.lifecycle;
    const breakdown = lifecycle?.breakdown || {};
    const ruleKeys = ["rule1", "rule2", "rule3", "rule4", "rule5", "rule6", "rule7"];
    const gateLeft = g.lifecycleX - 70;
    const gateRight = g.lifecycleX + 54;
    const gateGap = (gateRight - gateLeft) / (ruleKeys.length - 1);
    const mainY = g.center;
    const sinkY = g.center + 118;

    context.strokeStyle = "rgba(214,88,255,.18)";
    context.lineWidth = 2;
    context.beginPath();
    context.moveTo(g.lifecycleX - 98, mainY);
    context.lineTo(g.lifecycleX + 82, mainY);
    context.stroke();

    const burst = this.transients.findLast(item => item.event.type === "lifecycle_tick");
    const burstProgress = burst ? clamp((timestamp - burst.startedAt) / burst.duration, 0, 1) : null;

    ruleKeys.forEach((key, index) => {
      const x = gateLeft + gateGap * index;
      const affected = finite(breakdown[key]);
      const burstAffected = finite(burst?.event?.breakdown?.[key]);
      const activeBurst = burstProgress != null && burstAffected > 0;
      const intensity = clamp(Math.log10(affected + 1) / 2, 0, 1);
      context.beginPath();
      context.roundRect(x - 9, mainY - 18, 18, 36, 7);
      context.fillStyle = activeBurst
        ? `rgba(214,88,255,${0.58 + (1 - burstProgress) * 0.30})`
        : affected > 0
          ? `rgba(214,88,255,${0.26 + intensity * 0.34})`
          : "rgba(26,22,42,.96)";
      context.fill();
      context.strokeStyle = activeBurst ? "rgba(255,154,255,.95)" : "rgba(214,88,255,.28)";
      context.stroke();

      context.textAlign = "center";
      context.fillStyle = "rgba(243,245,248,.90)";
      context.font = "700 9px Inter, system-ui, sans-serif";
      context.fillText(`R${index + 1}`, x, mainY - 28);
      context.fillStyle = affected > 0 ? "rgba(255,188,255,.90)" : "rgba(146,155,173,.58)";
      context.font = "700 9px Inter, system-ui, sans-serif";
      context.fillText(formatNumber(affected), x, mainY + 31);

      if (activeBurst) {
        const branch = curve(x, mainY + 18, g.lifecycleX, sinkY - 24, 0.46);
        context.strokeStyle = "rgba(255,92,119,.24)";
        context.lineWidth = 1 + clamp(Math.log10(burstAffected + 1), 0, 2.5);
        drawCurve(context, branch);
        const branchProgress = clamp((burstProgress - .16 - index * .018) / .52, 0, 1);
        if (branchProgress > 0 && branchProgress < 1) {
          this.#drawPacket(context, branch, branchProgress, "255,92,119", clamp(3 + Math.log10(burstAffected + 1) * 2, 3, 8));
        }
      }
    });

    const survivorPath = curve(g.lifecycleX + 82, mainY, g.trackingX - 48, mainY, 0.5);
    context.strokeStyle = "rgba(20,241,217,.24)";
    context.lineWidth = 2.4;
    drawCurve(context, survivorPath);

    if (burstProgress != null) {
      const survivorProgress = clamp((burstProgress - .25) / .50, 0, 1);
      if (survivorProgress > 0 && survivorProgress < 1) {
        this.#drawPacket(context, survivorPath, survivorProgress, "20,241,217", 5.5);
      }
    }

    const affectedCount = finite(lifecycle?.affected_count);
    context.beginPath();
    context.arc(g.lifecycleX, sinkY, 26, 0, TAU);
    context.fillStyle = affectedCount > 0 ? "rgba(54,14,28,.92)" : "rgba(22,15,30,.88)";
    context.fill();
    context.strokeStyle = affectedCount > 0 ? "rgba(255,92,119,.62)" : "rgba(255,92,119,.18)";
    context.lineWidth = 1.2;
    context.stroke();
    context.textAlign = "center";
    context.fillStyle = affectedCount > 0 ? "rgba(255,155,171,.95)" : "rgba(146,155,173,.52)";
    context.font = "800 12px Inter, system-ui, sans-serif";
    context.fillText(formatNumber(affectedCount), g.lifecycleX, sinkY - 2);
    context.font = "700 8px Inter, system-ui, sans-serif";
    context.fillText(lifecycle?.apply ? "RETIRED" : "CANDIDATES", g.lifecycleX, sinkY + 12);

    this.hitTargets.push({
      x: gateLeft - 18,
      y: mainY - 46,
      width: gateRight - gateLeft + 36,
      height: 205,
      title: "Lifecycle R1–R7",
      lines: lifecycle ? [
        `${formatNumber(lifecycle.affected_count)} ${lifecycle.apply ? "retired" : "candidates"}`,
        `duration ${formatMs(lifecycle.duration_ms)}`,
        ...ruleKeys.map((key, index) => `R${index + 1} ${formatNumber(breakdown[key] || 0)}`),
      ] : ["Waiting for lifecycle cycle"],
    });
  }

  #drawTracking(context, g, timestamp) {
    const lifecycle = this.model?.lifecycle;
    const tracking = finite(lifecycle?.active_remaining);
    const radius = clamp(42 + Math.log10(tracking + 1) * 10, 44, 78);

    const glow = context.createRadialGradient(g.trackingX, g.center, 3, g.trackingX, g.center, radius + 28);
    glow.addColorStop(0, "rgba(20,241,217,.23)");
    glow.addColorStop(0.5, "rgba(20,241,217,.055)");
    glow.addColorStop(1, "rgba(20,241,217,0)");
    context.fillStyle = glow;
    context.beginPath();
    context.arc(g.trackingX, g.center, radius + 28, 0, TAU);
    context.fill();

    const dots = 72;
    for (let index = 0; index < dots; index += 1) {
      const ring = Math.floor(index / 18) + 1;
      const position = index % 18;
      const angle = (position / 18) * TAU + ring * 0.19;
      const r = radius * (0.22 + ring * 0.17);
      context.beginPath();
      context.arc(g.trackingX + Math.cos(angle) * r, g.center + Math.sin(angle) * r, 1.8 + (index % 5 === 0 ? 0.8 : 0), 0, TAU);
      context.fillStyle = `rgba(20,241,217,${0.18 + (index % 7) * 0.035})`;
      context.fill();
    }

    context.textAlign = "center";
    context.fillStyle = "rgba(243,245,248,.96)";
    context.font = "800 20px Inter, system-ui, sans-serif";
    context.fillText(formatNumber(tracking), g.trackingX, g.center - 2);
    context.fillStyle = "rgba(20,241,217,.75)";
    context.font = "700 9px Inter, system-ui, sans-serif";
    context.fillText("TRACKING", g.trackingX, g.center + 17);

    const loopY = Math.min(g.bottom - 22, g.center + 182);
    const down = curve(g.trackingX - 8, g.center + radius + 3, g.trackingX - 28, loopY, 0.40);
    const returnPath = curve(g.trackingX - 28, loopY, g.searchX, loopY, 0.42);
    const up = curve(g.searchX, loopY, g.searchX, g.center + 92, 0.40);
    context.strokeStyle = "rgba(20,241,217,.13)";
    context.lineWidth = 2;
    drawCurve(context, down);
    drawCurve(context, returnPath);
    drawCurve(context, up);

    const recentSearch = this.transients.filter(item => item.event.type === "search_lane_tick").slice(-18);
    recentSearch.forEach((burst, index) => {
      const progress = clamp((timestamp - burst.startedAt) / burst.duration, 0, 1);
      const offset = index / Math.max(recentSearch.length, 1) * 0.16;
      const p = clamp(progress + offset, 0, 1);
      if (p <= 0 || p >= 1) return;
      if (p < .20) this.#drawPacket(context, down, p / .20, "20,241,217", 2.8);
      else if (p < .82) this.#drawPacket(context, returnPath, (p - .20) / .62, "20,241,217", 2.8);
      else this.#drawPacket(context, up, (p - .82) / .18, "20,241,217", 2.8);
    });

    context.textAlign = "center";
    context.fillStyle = "rgba(20,241,217,.46)";
    context.font = "700 9px Inter, system-ui, sans-serif";
    context.fillText("TRACKING → SEARCH MONITORING", (g.trackingX + g.searchX) / 2, loopY + 18);

    this.hitTargets.push({
      x: g.trackingX - radius,
      y: g.center - radius,
      width: radius * 2,
      height: radius * 2,
      title: "Tracking survivors",
      lines: lifecycle ? [
        `${formatNumber(lifecycle.active_remaining)} tracking`,
        "survivor reservoir feeding Jupiter Search monitoring",
        "return motion is driven by observed search work",
        "not identical to Observatory ACTIVE",
      ] : ["Waiting for lifecycle telemetry"],
    });
  }

  #drawPacket(context, path, progress, color, width = 4) {
    const t = clamp(progress, 0, 1);
    const point = bezierPoint(path, t);
    const tail = bezierPoint(path, clamp(t - 0.055, 0, 1));
    const gradient = context.createLinearGradient(tail.x, tail.y, point.x, point.y);
    gradient.addColorStop(0, `rgba(${color},0)`);
    gradient.addColorStop(1, `rgba(${color},.95)`);
    context.strokeStyle = gradient;
    context.lineWidth = width;
    context.beginPath();
    context.moveTo(tail.x, tail.y);
    context.lineTo(point.x, point.y);
    context.stroke();
    context.beginPath();
    context.arc(point.x, point.y, Math.max(2.2, width * .58), 0, TAU);
    context.fillStyle = `rgba(${color},.95)`;
    context.fill();
  }

  #drawEmptyLayer(context, x, y, label) {
    context.beginPath();
    context.arc(x, y, 8, 0, TAU);
    context.strokeStyle = "rgba(146,155,173,.22)";
    context.stroke();
    context.textAlign = "center";
    context.fillStyle = "rgba(146,155,173,.42)";
    context.font = "10px Inter, system-ui, sans-serif";
    context.fillText(label, x, y + 24);
  }

  #median(values) {
    const finiteValues = values.filter(Number.isFinite).sort((a, b) => a - b);
    if (!finiteValues.length) return null;
    const middle = Math.floor(finiteValues.length / 2);
    return finiteValues.length % 2
      ? finiteValues[middle]
      : (finiteValues[middle - 1] + finiteValues[middle]) / 2;
  }

  #pointerMove(event) {
    if (!this.canvas || !this.tooltip) return;
    const rect = this.canvas.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const y = event.clientY - rect.top;
    const target = [...this.hitTargets].reverse().find(item => (
      x >= item.x && x <= item.x + item.width && y >= item.y && y <= item.y + item.height
    ));
    if (!target) {
      this.#hideTooltip();
      return;
    }

    this.tooltip.replaceChildren();
    const title = document.createElement("strong");
    title.textContent = target.title;
    this.tooltip.append(title);
    for (const line of target.lines) {
      const item = document.createElement("span");
      item.textContent = line;
      this.tooltip.append(item);
    }
    this.tooltip.classList.remove("hidden");
    const tooltipRect = this.tooltip.getBoundingClientRect();
    this.tooltip.style.left = `${clamp(x + 18, 12, rect.width - tooltipRect.width - 12)}px`;
    this.tooltip.style.top = `${clamp(y + 18, 12, rect.height - tooltipRect.height - 12)}px`;
  }

  #hideTooltip() {
    this.tooltip?.classList.add("hidden");
  }
}
