const TAU = Math.PI * 2;
const FLOW_PADDING_X = 44;
const FLOW_PADDING_Y = 70;
const STAGE_DOT_RADIUS = 3;
const MAX_TRANSIENTS = 360;
const LIFECYCLE_BURST_MS = 2400;
const ACTIVE_PULSE_MS = 1100;

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

function relativeDots(value, maxValue, limit = 72) {
  if (!Number.isFinite(value) || value <= 0) return 0;
  if (!Number.isFinite(maxValue) || maxValue <= 0) return 1;
  return clamp(Math.round((Math.sqrt(value) / Math.sqrt(maxValue)) * limit), 1, limit);
}

function magnitudeDots(value, limit = 52) {
  if (!Number.isFinite(value) || value <= 0) return 0;
  return clamp(Math.round(4 + Math.log10(value + 1) * 14), 1, limit);
}

function burstUnits(value, limit = 24) {
  if (!Number.isFinite(value) || value <= 0) return 0;
  return clamp(Math.round(2 + Math.log10(value + 1) * 6), 1, limit);
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
    this.lastActiveCount = null;
    this.activeDelta = 0;
    this.activeChangedAt = 0;
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
    heading.textContent = "Discovery → Admission → Search → Write → Lifecycle → Tracking";
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
    legend.textContent = "Discovery bursts = bounded candidate counts · Search packets = observed lane work · Monitoring current = aggregate Search rate · no dot is a Mint identity";

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
    if (this.seenEvents.size > 5000) this.seenEvents.clear();

    let duration = 0;
    if (event.type === "discovery_tick") {
      duration = clamp(finite(event.latency_ms, 250) * 4.2, 650, 1350);
    } else if (event.type === "search_lane_tick") {
      duration = clamp(finite(event.latency_ms, 900) * 1.2, 280, 1500);
    } else if (event.type === "search_flush") {
      duration = 1350;
    } else if (event.type === "lifecycle_tick") {
      duration = LIFECYCLE_BURST_MS;
    }
    if (!duration) return;

    this.transients.push({
      id,
      event: { ...event },
      startedAt: performance.now(),
      duration,
    });
    if (this.transients.length > MAX_TRANSIENTS) {
      this.transients.splice(0, this.transients.length - MAX_TRANSIENTS);
    }
    if (this.visible) this.#schedule();
  }

  render(model) {
    this.model = model;
    const activeCount = Number(model?.activeCount);
    if (Number.isFinite(activeCount) && activeCount !== this.lastActiveCount) {
      if (this.lastActiveCount != null) {
        this.activeDelta = activeCount - this.lastActiveCount;
        this.activeChangedAt = performance.now();
      }
      this.lastActiveCount = activeCount;
    }

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
      sourceX: FLOW_PADDING_X + innerWidth * 0.025,
      intakeX: FLOW_PADDING_X + innerWidth * 0.145,
      gateX: FLOW_PADDING_X + innerWidth * 0.235,
      newX: FLOW_PADDING_X + innerWidth * 0.295,
      searchX: FLOW_PADDING_X + innerWidth * 0.39,
      writeX: FLOW_PADDING_X + innerWidth * 0.61,
      lifecycleX: FLOW_PADDING_X + innerWidth * 0.79,
      trackingX: FLOW_PADDING_X + innerWidth * 0.94,
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
    glow.addColorStop(0, "rgba(153,69,255,.13)");
    glow.addColorStop(0.48, "rgba(73,217,255,.035)");
    glow.addColorStop(1, "rgba(0,0,0,0)");
    context.fillStyle = glow;
    context.fillRect(0, 0, g.width, g.height);
  }

  #drawLayerHeadings(context, g) {
    const admissionX = (g.intakeX + g.newX) / 2;
    const headings = [
      ["DISCOVERY", g.sourceX, "discovery", this.#stageMetric("discovery")],
      ["ADMISSION", admissionX, "filter", "intake → dedupe → new"],
      ["SEARCH", g.searchX, "search", this.#stageMetric("search")],
      ["WRITE", g.writeX, "write", this.#stageMetric("write")],
      ["LIFECYCLE", g.lifecycleX, "lifecycle", this.#stageMetric("lifecycle")],
      ["TRACKING", g.trackingX, "tracking", this.#stageMetric("tracking")],
    ];
    context.textAlign = "center";
    context.textBaseline = "middle";
    for (const [label, x, kind, metric] of headings) {
      context.fillStyle = `rgba(${stageColor(kind)},.66)`;
      context.font = "700 10px Inter, system-ui, sans-serif";
      context.fillText(label, x, FLOW_PADDING_Y + 8);
      context.fillStyle = "rgba(243,245,248,.94)";
      context.font = "700 12px Inter, system-ui, sans-serif";
      context.fillText(metric, x, FLOW_PADDING_Y + 29);
    }
  }

  #stageMetric(kind) {
    const model = this.model || {};
    if (kind === "discovery") {
      const raw = (model.discovery || []).reduce((sum, event) => sum + finite(event.response_items), 0);
      const fresh = (model.discovery || []).reduce((sum, event) => sum + finite(event.new_mints), 0);
      return `${formatNumber(raw)} intake · ${formatNumber(fresh)} new`;
    }
    if (kind === "search") {
      const rpm = (model.lanes || []).reduce((sum, event) => sum + finite(event.rpm60), 0);
      return `${formatNumber(rpm)} rpm`;
    }
    if (kind === "write") {
      return model.flush ? `${formatNumber(model.flush.polled_tokens)} → ${formatNumber(model.flush.new_snapshots)}` : "waiting";
    }
    if (kind === "lifecycle") {
      return model.lifecycle ? `${formatNumber(model.lifecycle.affected_count)} affected` : "waiting";
    }
    if (kind === "tracking") {
      const active = Number(model.activeCount);
      return Number.isFinite(active) ? `${formatNumber(active)} active` : "waiting";
    }
    return "—";
  }

  #drawDiscovery(context, g, timestamp) {
    const events = this.model?.discovery || [];
    const count = Math.max(events.length, 1);
    const span = Math.min(g.bottom - g.top - 70, 410);
    const startY = g.center - span / 2;

    if (!events.length) {
      this.#drawEmptyLayer(context, g.sourceX, g.center, "waiting for discovery");
      return;
    }

    events.forEach((event, index) => {
      const y = count === 1 ? g.center : startY + (span * index) / Math.max(count - 1, 1);
      const raw = finite(event.response_items);
      const unique = finite(event.unique_candidates);
      const fresh = finite(event.new_mints);
      const uniqueRatio = clamp(unique / Math.max(raw, 1), 0, 1);
      const livePulse = this.transients.findLast(item => item.event.type === "discovery_tick" && item.event.source === event.source);
      const pulseProgress = livePulse ? clamp((timestamp - livePulse.startedAt) / livePulse.duration, 0, 1) : null;

      context.textAlign = "right";
      context.fillStyle = "rgba(243,245,248,.92)";
      context.font = "650 10px Inter, system-ui, sans-serif";
      context.fillText(String(event.source), g.sourceX - 13, y - 2);
      context.fillStyle = "rgba(146,155,173,.68)";
      context.font = "9px Inter, system-ui, sans-serif";
      context.fillText(`${formatNumber(raw)} raw · ${formatMs(event.latency_ms)}`, g.sourceX - 13, y + 12);

      context.beginPath();
      context.arc(g.sourceX, y, 7, 0, TAU);
      context.fillStyle = "rgba(9,23,34,.98)";
      context.fill();
      context.strokeStyle = "rgba(20,241,217,.72)";
      context.stroke();

      this.#drawMagnitudeField(context, g.intakeX, y, raw, "20,241,217", 52);

      const gateRadius = 12 + uniqueRatio * 4;
      context.beginPath();
      context.arc(g.gateX, y, gateRadius, 0, TAU);
      context.fillStyle = "rgba(8,18,31,.98)";
      context.fill();
      context.strokeStyle = `rgba(49,196,255,${0.30 + uniqueRatio * 0.58})`;
      context.lineWidth = 1.2 + uniqueRatio * 1.4;
      context.stroke();
      context.textAlign = "center";
      context.fillStyle = "rgba(224,245,255,.94)";
      context.font = "800 8px Inter, system-ui, sans-serif";
      context.fillText(formatNumber(unique), g.gateX, y + 2);

      context.fillStyle = "rgba(146,155,173,.58)";
      context.font = "700 7px Inter, system-ui, sans-serif";
      context.fillText(`${Math.round(uniqueRatio * 100)}% unique`, g.gateX, y + gateRadius + 12);

      this.#drawNewField(context, g.newX, y, fresh);

      const sourceToIntake = curve(g.sourceX + 9, y, g.intakeX - 24, y, 0.42);
      const intakeToGate = curve(g.intakeX + 24, y, g.gateX - gateRadius - 4, y, 0.42);
      const gateToNew = curve(g.gateX + gateRadius + 4, y, g.newX - 14, y, 0.42);
      const newToSearch = curve(g.newX + 14, y, g.searchX - 42, g.center + (y - g.center) * 0.42, 0.50);

      for (const [path, alpha, width] of [
        [sourceToIntake, .16, 1.1],
        [intakeToGate, .14, 1.1],
        [gateToNew, fresh > 0 ? .24 : .07, 1.0],
        [newToSearch, fresh > 0 ? .34 : .06, fresh > 0 ? 1.4 : .8],
      ]) {
        context.strokeStyle = `rgba(20,241,217,${alpha})`;
        context.lineWidth = width;
        drawCurve(context, path);
      }

      if (pulseProgress != null) {
        const rawUnits = burstUnits(raw, 24);
        const uniqueUnits = burstUnits(unique, 22);
        const freshUnits = clamp(Math.round(fresh), 0, 12);
        const p0 = clamp(pulseProgress / .42, 0, 1);
        const p1 = clamp((pulseProgress - .18) / .42, 0, 1);
        const p2 = clamp((pulseProgress - .48) / .28, 0, 1);
        const p3 = clamp((pulseProgress - .62) / .36, 0, 1);

        if (p0 > 0 && p0 < 1) this.#drawBurstTrain(context, sourceToIntake, p0, "20,241,217", rawUnits, 1.7);
        if (p1 > 0 && p1 < 1) this.#drawBurstTrain(context, intakeToGate, p1, "49,196,255", uniqueUnits, 1.7);
        if (freshUnits > 0 && p2 > 0 && p2 < 1) this.#drawBurstTrain(context, gateToNew, p2, "73,217,255", freshUnits, 2.2);
        if (freshUnits > 0 && p3 > 0 && p3 < 1) this.#drawBurstTrain(context, newToSearch, p3, "73,217,255", freshUnits, 2.6);
      }

      this.hitTargets.push({
        x: g.sourceX - 108,
        y: y - 26,
        width: g.newX - g.sourceX + 132,
        height: 52,
        title: String(event.source),
        lines: [
          `${formatNumber(raw)} raw intake`,
          `${formatNumber(unique)} unique candidates`,
          `${formatNumber(fresh)} new Mints admitted`,
          `latency ${formatMs(event.latency_ms)}`,
          "burst density is a bounded count encoding",
        ],
      });
    });

    context.textAlign = "center";
    context.fillStyle = "rgba(146,155,173,.48)";
    context.font = "700 8px Inter, system-ui, sans-serif";
    context.fillText("RAW INTAKE", g.intakeX, g.bottom - 4);
    context.fillText("DEDUPE", g.gateX, g.bottom - 4);
    context.fillText("NEW", g.newX, g.bottom - 4);
  }

  #drawMagnitudeField(context, x, y, value, color, limit) {
    const dots = magnitudeDots(value, limit);
    const columns = 8;
    const gapX = 5.5;
    const gapY = 5.5;
    const rows = Math.ceil(Math.max(dots, 1) / columns);
    for (let index = 0; index < dots; index += 1) {
      const col = index % columns;
      const row = Math.floor(index / columns);
      const px = x + (col - (columns - 1) / 2) * gapX;
      const py = y + (row - (rows - 1) / 2) * gapY;
      context.beginPath();
      context.arc(px, py, 1.8, 0, TAU);
      context.fillStyle = `rgba(${color},${0.28 + 0.60 * (index + 1) / Math.max(dots, 1)})`;
      context.fill();
    }
    if (!dots) {
      context.beginPath();
      context.arc(x, y, 2, 0, TAU);
      context.strokeStyle = `rgba(${color},.18)`;
      context.stroke();
    }
  }

  #drawNewField(context, x, y, fresh) {
    const dots = clamp(Math.round(fresh), 0, 14);
    if (!dots) {
      context.beginPath();
      context.arc(x, y, 2.5, 0, TAU);
      context.strokeStyle = "rgba(73,217,255,.18)";
      context.stroke();
      return;
    }
    for (let index = 0; index < dots; index += 1) {
      const angle = (index / Math.max(dots, 1)) * TAU;
      const ring = index < 6 ? 6 : 10;
      context.beginPath();
      context.arc(x + Math.cos(angle) * ring, y + Math.sin(angle) * ring, 2.1, 0, TAU);
      context.fillStyle = "rgba(73,217,255,.88)";
      context.fill();
    }
    context.textAlign = "center";
    context.fillStyle = "rgba(243,245,248,.90)";
    context.font = "800 8px Inter, system-ui, sans-serif";
    context.fillText(formatNumber(fresh), x, y + 2);
  }

  #searchLayout(g) {
    const lanes = this.model?.lanes || [];
    const laneCount = Math.max(lanes.length, 1);
    const rows = Math.min(16, Math.ceil(Math.sqrt(laneCount * 2)));
    const columns = Math.ceil(laneCount / rows);
    const cellX = 12;
    const cellY = 16;
    const width = Math.max(38, columns * cellX);
    const height = Math.max(140, rows * cellY);
    const left = g.searchX - width / 2;
    const top = g.center - height / 2;
    return { lanes, rows, columns, cellX, cellY, width, height, left, top };
  }

  #drawSearch(context, g, timestamp) {
    const layout = this.#searchLayout(g);
    const { lanes, rows, cellX, cellY, width, height, left, top } = layout;

    context.fillStyle = "rgba(10,19,32,.72)";
    context.strokeStyle = "rgba(73,217,255,.22)";
    context.lineWidth = 1;
    context.beginPath();
    context.roundRect(left - 20, top - 24, width + 40, height + 48, 18);
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

      const targetY = g.center + (row / Math.max(rows - 1, 1) - 0.5) * 255;
      const path = curve(x, y, g.writeX - 124, targetY, 0.56);
      context.strokeStyle = statusGood
        ? `rgba(73,217,255,${0.04 + intensity * 0.09})`
        : "rgba(255,92,119,.15)";
      context.lineWidth = 0.65 + intensity * 0.75;
      drawCurve(context, path);
    });

    const searchBursts = this.transients.filter(item => item.event.type === "search_lane_tick");
    for (const burst of searchBursts) {
      const lane = burst.event;
      const position = lanePositions.get(String(lane.lane));
      if (!position) continue;
      const progress = clamp((timestamp - burst.startedAt) / burst.duration, 0, 1);
      if (progress <= 0 || progress >= 1) continue;
      const targetY = g.center + (position.row / Math.max(rows - 1, 1) - 0.5) * 255;
      const path = curve(position.x, position.y, g.writeX - 124, targetY, 0.56);
      const requested = finite(lane.requested);
      const units = clamp(Math.round(requested / 32), 1, 4);
      const widthScale = clamp(requested / 100, 0.25, 1);
      const color = lane.status === 200 ? "73,217,255" : "255,92,119";
      this.#drawBurstTrain(context, path, progress, color, units, 2.0 + widthScale * 2.4, .075);
    }

    this.hitTargets.push({
      x: left - 20,
      y: top - 24,
      width: width + 40,
      height: height + 48,
      title: "Jupiter Search",
      lines: [
        `${lanes.length} parallel lanes`,
        `${formatNumber(lanes.reduce((sum, lane) => sum + finite(lane.rpm60), 0))} aggregate rpm`,
        `median latency ${formatMs(this.#median(lanes.map(lane => lane.latency_ms)))}`,
        "each live packet = observed lane work",
      ],
    });
  }

  #drawWrite(context, g, timestamp) {
    const flush = this.model?.flush;
    const values = flush
      ? [finite(flush.polled_tokens), finite(flush.source_versions), finite(flush.new_snapshots)]
      : [0, 0, 0];
    const labels = ["POLLS", "VERSIONS", "SNAPSHOTS"];
    const xs = [g.writeX - 84, g.writeX, g.writeX + 84];
    const maxValue = Math.max(...values, 1);
    const regionWidth = 252;
    const regionHeight = 270;

    context.beginPath();
    context.roundRect(g.writeX - regionWidth / 2, g.center - regionHeight / 2, regionWidth, regionHeight, 22);
    context.fillStyle = "rgba(20,13,38,.34)";
    context.fill();
    context.strokeStyle = "rgba(153,69,255,.16)";
    context.lineWidth = 1;
    context.stroke();

    for (let index = 0; index < 3; index += 1) {
      const ratio = Math.sqrt(values[index] / maxValue);
      const maxDots = 90;
      const dots = relativeDots(values[index], maxValue, maxDots);
      const columns = 9;
      const rows = 10;
      for (let slot = 0; slot < maxDots; slot += 1) {
        const row = slot % rows;
        const col = Math.floor(slot / rows);
        const x = xs[index] + (col - 4) * 7.3;
        const y = g.center + (row - 4.5) * 14;
        const active = slot < dots;
        context.beginPath();
        context.arc(x, y, active ? 3.2 : 1.5, 0, TAU);
        context.fillStyle = active
          ? `rgba(153,69,255,${0.34 + ratio * 0.62})`
          : "rgba(153,69,255,.04)";
        context.fill();
      }

      context.textAlign = "center";
      context.fillStyle = "rgba(146,155,173,.66)";
      context.font = "700 8px Inter, system-ui, sans-serif";
      context.fillText(labels[index], xs[index], g.center + 92);
      context.fillStyle = "rgba(243,245,248,.96)";
      context.font = "800 13px Inter, system-ui, sans-serif";
      context.fillText(formatNumber(values[index]), xs[index], g.center + 110);
    }

    const bridge1 = curve(xs[0] + 32, g.center, xs[1] - 32, g.center, 0.46);
    const bridge2 = curve(xs[1] + 32, g.center, xs[2] - 32, g.center, 0.46);
    for (const [path, next, current] of [
      [bridge1, values[1], values[0]],
      [bridge2, values[2], values[1]],
    ]) {
      const ratio = clamp(next / Math.max(current, 1), 0, 1);
      context.strokeStyle = `rgba(153,69,255,${0.12 + ratio * 0.34})`;
      context.lineWidth = 1.5 + ratio * 5.5;
      drawCurve(context, path);
    }

    const toLifecycle = curve(g.writeX + 126, g.center, g.lifecycleX - 92, g.center, 0.5);
    context.strokeStyle = "rgba(183,124,255,.17)";
    context.lineWidth = 2.3;
    drawCurve(context, toLifecycle);

    const burst = this.transients.findLast(item => item.event.type === "search_flush");
    if (burst) {
      const p = clamp((timestamp - burst.startedAt) / burst.duration, 0, 1);
      const wave1 = clamp(p / .42, 0, 1);
      const wave2 = clamp((p - .23) / .42, 0, 1);
      const out = clamp((p - .52) / .46, 0, 1);
      const pollUnits = burstUnits(finite(burst.event.polled_tokens), 14);
      const versionUnits = burstUnits(finite(burst.event.source_versions), 12);
      const snapshotUnits = burstUnits(finite(burst.event.new_snapshots), 10);

      this.#drawFieldPulse(context, xs[0], g.center, wave1, "183,124,255", 52, 150);
      if (wave1 > 0 && wave1 < 1) this.#drawBurstTrain(context, bridge1, wave1, "183,124,255", pollUnits, 2.3);
      this.#drawFieldPulse(context, xs[1], g.center, wave2, "183,124,255", 52, 150);
      if (wave2 > 0 && wave2 < 1) this.#drawBurstTrain(context, bridge2, wave2, "183,124,255", versionUnits, 2.1);
      this.#drawFieldPulse(context, xs[2], g.center, out, "207,164,255", 52, 150);
      if (snapshotUnits > 0 && out > 0 && out < 1) {
        this.#drawBurstTrain(context, toLifecycle, out, "207,164,255", snapshotUnits, 2.4);
      }
    }

    this.hitTargets.push({
      x: g.writeX - regionWidth / 2,
      y: g.center - regionHeight / 2,
      width: regionWidth,
      height: regionHeight,
      title: "WriteQueue condensation",
      lines: flush ? [
        `${formatNumber(flush.polled_tokens)} polls`,
        `${formatNumber(flush.source_versions)} source versions`,
        `${formatNumber(flush.new_snapshots)} new snapshots`,
        `queue ${formatNumber(flush.queue_size)} · write ${formatMs(flush.write_ms)}`,
        "flush wave = observed search_flush",
      ] : ["Waiting for first flush"],
    });
  }

  #drawLifecycle(context, g, timestamp) {
    const lifecycle = this.model?.lifecycle;
    const breakdown = lifecycle?.breakdown || {};
    const ruleKeys = ["rule1", "rule2", "rule3", "rule4", "rule5", "rule6", "rule7"];
    const gateLeft = g.lifecycleX - 72;
    const gateRight = g.lifecycleX + 58;
    const gateGap = (gateRight - gateLeft) / (ruleKeys.length - 1);
    const mainY = g.center;
    const sinkY = g.center + 118;

    context.strokeStyle = "rgba(214,88,255,.20)";
    context.lineWidth = 2.2;
    context.beginPath();
    context.moveTo(g.lifecycleX - 102, mainY);
    context.lineTo(g.lifecycleX + 86, mainY);
    context.stroke();

    const burst = this.transients.findLast(item => item.event.type === "lifecycle_tick");
    const burstProgress = burst ? clamp((timestamp - burst.startedAt) / burst.duration, 0, 1) : null;

    if (burstProgress != null && burstProgress < .58) {
      const sweepX = (g.lifecycleX - 100) + (186 * (burstProgress / .58));
      const gradient = context.createLinearGradient(sweepX - 18, 0, sweepX + 18, 0);
      gradient.addColorStop(0, "rgba(214,88,255,0)");
      gradient.addColorStop(.5, "rgba(214,88,255,.42)");
      gradient.addColorStop(1, "rgba(214,88,255,0)");
      context.fillStyle = gradient;
      context.fillRect(sweepX - 18, mainY - 34, 36, 68);
    }

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
        const branch = curve(x, mainY + 18, g.lifecycleX, sinkY - 25, 0.46);
        context.strokeStyle = "rgba(255,92,119,.26)";
        context.lineWidth = 1 + clamp(Math.log10(burstAffected + 1), 0, 2.5);
        drawCurve(context, branch);
        const branchProgress = clamp((burstProgress - .14 - index * .018) / .50, 0, 1);
        if (branchProgress > 0 && branchProgress < 1) {
          this.#drawBurstTrain(
            context,
            branch,
            branchProgress,
            "255,92,119",
            burstUnits(burstAffected, 12),
            2.5,
            .08,
          );
        }
      }
    });

    const survivorPath = curve(g.lifecycleX + 86, mainY, g.trackingX - 50, mainY, 0.50);
    context.strokeStyle = "rgba(20,241,217,.26)";
    context.lineWidth = 2.6;
    drawCurve(context, survivorPath);

    if (burstProgress != null) {
      const survivorProgress = clamp((burstProgress - .28) / .54, 0, 1);
      if (survivorProgress > 0 && survivorProgress < 1) {
        this.#drawBurstTrain(context, survivorPath, survivorProgress, "20,241,217", 7, 2.8, .09);
      }
    }

    const affectedCount = finite(lifecycle?.affected_count);
    context.beginPath();
    context.arc(g.lifecycleX, sinkY, 29, 0, TAU);
    context.fillStyle = affectedCount > 0 ? "rgba(54,14,28,.94)" : "rgba(22,15,30,.88)";
    context.fill();
    context.strokeStyle = affectedCount > 0 ? "rgba(255,92,119,.68)" : "rgba(255,92,119,.18)";
    context.lineWidth = 1.3;
    context.stroke();

    context.textAlign = "center";
    context.fillStyle = affectedCount > 0 ? "rgba(255,155,171,.96)" : "rgba(146,155,173,.52)";
    context.font = "800 13px Inter, system-ui, sans-serif";
    context.fillText(formatNumber(affectedCount), g.lifecycleX, sinkY - 2);
    context.font = "700 8px Inter, system-ui, sans-serif";
    context.fillText(lifecycle?.apply ? "RETIRED" : "CANDIDATES", g.lifecycleX, sinkY + 13);

    this.hitTargets.push({
      x: gateLeft - 20,
      y: mainY - 48,
      width: gateRight - gateLeft + 40,
      height: 210,
      title: "Lifecycle R1–R7",
      lines: lifecycle ? [
        `${formatNumber(lifecycle.affected_count)} ${lifecycle.apply ? "retired" : "candidates"}`,
        `duration ${formatMs(lifecycle.duration_ms)}`,
        ...ruleKeys.map((key, index) => `R${index + 1} ${formatNumber(breakdown[key] || 0)}`),
        "gate sweep = observed lifecycle_tick",
      ] : ["Waiting for lifecycle cycle"],
    });
  }

  #drawTracking(context, g, timestamp) {
    const lifecycle = this.model?.lifecycle;
    const canonicalActive = Number(this.model?.activeCount);
    const tracking = Number.isFinite(canonicalActive)
      ? canonicalActive
      : finite(lifecycle?.active_remaining);
    const radius = clamp(44 + Math.log10(tracking + 1) * 10, 46, 80);

    const glow = context.createRadialGradient(g.trackingX, g.center, 3, g.trackingX, g.center, radius + 30);
    glow.addColorStop(0, "rgba(20,241,217,.25)");
    glow.addColorStop(0.5, "rgba(20,241,217,.060)");
    glow.addColorStop(1, "rgba(20,241,217,0)");
    context.fillStyle = glow;
    context.beginPath();
    context.arc(g.trackingX, g.center, radius + 30, 0, TAU);
    context.fill();

    const reservoirDots = clamp(Math.round(28 + Math.log10(tracking + 1) * 24), 28, 120);
    for (let index = 0; index < reservoirDots; index += 1) {
      const ring = Math.floor(index / 24) + 1;
      const position = index % 24;
      const angle = (position / 24) * TAU + ring * 0.17;
      const r = radius * clamp(0.18 + ring * 0.13, .18, .88);
      context.beginPath();
      context.arc(
        g.trackingX + Math.cos(angle) * r,
        g.center + Math.sin(angle) * r,
        1.6 + (index % 7 === 0 ? 0.9 : 0),
        0,
        TAU,
      );
      context.fillStyle = `rgba(20,241,217,${0.18 + (index % 7) * 0.035})`;
      context.fill();
    }

    const activePulseAge = timestamp - this.activeChangedAt;
    if (this.activeChangedAt && activePulseAge >= 0 && activePulseAge < ACTIVE_PULSE_MS) {
      const p = activePulseAge / ACTIVE_PULSE_MS;
      context.beginPath();
      context.arc(g.trackingX, g.center, radius + 7 + p * 24, 0, TAU);
      context.strokeStyle = this.activeDelta >= 0
        ? `rgba(20,241,217,${.62 * (1 - p)})`
        : `rgba(255,92,119,${.62 * (1 - p)})`;
      context.lineWidth = 2.2;
      context.stroke();

      context.textAlign = "center";
      context.fillStyle = this.activeDelta >= 0 ? "rgba(130,255,236,.92)" : "rgba(255,145,163,.92)";
      context.font = "800 9px Inter, system-ui, sans-serif";
      context.fillText(`${this.activeDelta >= 0 ? "+" : ""}${formatNumber(this.activeDelta)} active`, g.trackingX, g.center - radius - 15);
    }

    context.textAlign = "center";
    context.fillStyle = "rgba(243,245,248,.98)";
    context.font = "800 20px Inter, system-ui, sans-serif";
    context.fillText(formatNumber(tracking), g.trackingX, g.center - 2);
    context.fillStyle = "rgba(20,241,217,.78)";
    context.font = "700 9px Inter, system-ui, sans-serif";
    context.fillText("ACTIVE TRACKED", g.trackingX, g.center + 17);

    const loopY = Math.min(g.bottom - 20, g.center + 188);
    const down = curve(g.trackingX - 8, g.center + radius + 3, g.trackingX - 28, loopY, 0.40);
    const returnPath = curve(g.trackingX - 28, loopY, g.searchX, loopY, 0.42);
    const up = curve(g.searchX, loopY, g.searchX, g.center + 96, 0.40);

    const lanes = this.model?.lanes || [];
    const aggregateRpm = lanes.reduce((sum, lane) => sum + finite(lane.rpm60), 0);
    const medianLatency = this.#median(lanes.map(lane => lane.latency_ms));
    const rateCapacity = Math.max(1, lanes.length * 60);
    const rateIntensity = clamp(aggregateRpm / rateCapacity, 0, 1);
    const lineWidth = 1.4 + rateIntensity * 2.2;

    context.strokeStyle = `rgba(20,241,217,${0.10 + rateIntensity * .12})`;
    context.lineWidth = lineWidth;
    drawCurve(context, down);
    drawCurve(context, returnPath);
    drawCurve(context, up);

    if (aggregateRpm > 0) {
      const trainCount = clamp(Math.round(3 + rateIntensity * 8), 3, 11);
      const latencyFactor = clamp(1000 / Math.max(finite(medianLatency, 900), 100), .45, 2.0);
      const speed = 0.000045 * latencyFactor;
      const phase = ((timestamp * speed) % 1 + 1) % 1;
      for (let index = 0; index < trainCount; index += 1) {
        const p = (phase + index / trainCount) % 1;
        if (p < .16) this.#drawPacket(context, down, p / .16, "20,241,217", 2.2 + rateIntensity * 1.4);
        else if (p < .84) this.#drawPacket(context, returnPath, (p - .16) / .68, "20,241,217", 2.2 + rateIntensity * 1.4);
        else this.#drawPacket(context, up, (p - .84) / .16, "20,241,217", 2.2 + rateIntensity * 1.4);
      }
    }

    context.textAlign = "center";
    context.fillStyle = "rgba(20,241,217,.50)";
    context.font = "700 9px Inter, system-ui, sans-serif";
    context.fillText(`MONITORING LOOP · ${formatNumber(aggregateRpm)} rpm`, (g.trackingX + g.searchX) / 2, loopY + 18);

    const lifecycleTracking = Number(lifecycle?.active_remaining);
    this.hitTargets.push({
      x: g.trackingX - radius,
      y: g.center - radius,
      width: radius * 2,
      height: radius * 2,
      title: "Tracking survivors",
      lines: [
        `${formatNumber(tracking)} current Observatory ACTIVE`,
        Number.isFinite(lifecycleTracking)
          ? `${formatNumber(lifecycleTracking)} at last Lifecycle cycle`
          : "Lifecycle cycle not observed yet",
        `${formatNumber(aggregateRpm)} aggregate Search rpm`,
        "reservoir count follows canonical browser state",
        "monitoring current encodes observed Search rate",
      ],
    });
  }

  #drawBurstTrain(context, path, progress, color, units, width = 3, spacing = .045) {
    const count = Math.max(0, Math.round(units));
    for (let index = 0; index < count; index += 1) {
      const t = progress - index * spacing;
      if (t <= 0 || t >= 1) continue;
      const fade = clamp(1 - index / Math.max(count, 1) * .62, .28, 1);
      this.#drawPacket(context, path, t, color, width * (0.78 + fade * .22), fade);
    }
  }

  #drawFieldPulse(context, x, y, progress, color, width, height) {
    if (progress <= 0 || progress >= 1) return;
    const alpha = Math.sin(progress * Math.PI) * .30;
    context.beginPath();
    context.roundRect(x - width / 2, y - height / 2, width, height, 13);
    context.strokeStyle = `rgba(${color},${alpha})`;
    context.lineWidth = 2 + Math.sin(progress * Math.PI) * 2;
    context.stroke();
  }

  #drawPacket(context, path, progress, color, width = 4, alpha = 1) {
    const t = clamp(progress, 0, 1);
    const point = bezierPoint(path, t);
    const tail = bezierPoint(path, clamp(t - 0.045, 0, 1));
    const gradient = context.createLinearGradient(tail.x, tail.y, point.x, point.y);
    gradient.addColorStop(0, `rgba(${color},0)`);
    gradient.addColorStop(1, `rgba(${color},${.95 * alpha})`);
    context.strokeStyle = gradient;
    context.lineWidth = width;
    context.beginPath();
    context.moveTo(tail.x, tail.y);
    context.lineTo(point.x, point.y);
    context.stroke();
    context.beginPath();
    context.arc(point.x, point.y, Math.max(1.8, width * .50), 0, TAU);
    context.fillStyle = `rgba(${color},${.95 * alpha})`;
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
