const TAU = Math.PI * 2;
const FLOW_PADDING_X = 54;
const FLOW_PADDING_Y = 72;
const PARTICLE_RADIUS = 2.2;
const STAGE_DOT_RADIUS = 3;

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

function ageSeconds(at, now) {
  const timestamp = Date.parse(at || "");
  return Number.isFinite(timestamp) ? Math.max(0, (now - timestamp) / 1000) : Infinity;
}

function hashString(value) {
  let hash = 2166136261;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

function bezierPoint(curve, t) {
  const mt = 1 - t;
  const x = mt ** 3 * curve.x0
    + 3 * mt ** 2 * t * curve.x1
    + 3 * mt * t ** 2 * curve.x2
    + t ** 3 * curve.x3;
  const y = mt ** 3 * curve.y0
    + 3 * mt ** 2 * t * curve.y1
    + 3 * mt * t ** 2 * curve.y2
    + t ** 3 * curve.y3;
  return { x, y };
}

function curve(x0, y0, x3, y3, bend = 0.42) {
  const dx = x3 - x0;
  return {
    x0,
    y0,
    x1: x0 + dx * bend,
    y1: y0,
    x2: x3 - dx * bend,
    y2: y3,
    x3,
    y3,
  };
}

function drawCurve(context, path) {
  context.beginPath();
  context.moveTo(path.x0, path.y0);
  context.bezierCurveTo(path.x1, path.y1, path.x2, path.y2, path.x3, path.y3);
  context.stroke();
}

function stageColor(kind) {
  if (kind === "discovery") return "20,241,217";
  if (kind === "search") return "73,217,255";
  if (kind === "write") return "153,69,255";
  if (kind === "lifecycle") return "214,88,255";
  if (kind === "tracking") return "20,241,217";
  return "146,155,173";
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
    this.pointer = null;
    this.hitTargets = [];
    this.resizeObserver = null;
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
    heading.textContent = "Discovery → Search → Write → Lifecycle → Tracking";
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
    legend.textContent = "Particles = work pulses · density = observed rate/count · no particle represents a Mint";

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
    const top = FLOW_PADDING_Y + 58;
    const bottom = height - FLOW_PADDING_Y - 30;
    const center = (top + bottom) / 2;
    return {
      width,
      height,
      top,
      bottom,
      center,
      discoveryX: FLOW_PADDING_X + innerWidth * 0.06,
      searchX: FLOW_PADDING_X + innerWidth * 0.29,
      writeX: FLOW_PADDING_X + innerWidth * 0.50,
      lifecycleX: FLOW_PADDING_X + innerWidth * 0.70,
      trackingX: FLOW_PADDING_X + innerWidth * 0.91,
    };
  }

  #draw(timestamp) {
    if (!this.canvas || !this.context) return;
    this.#resize();
    const context = this.context;
    const dpr = Number(this.canvas.dataset.dpr || 1);
    const geometry = this.#geometry();
    context.setTransform(dpr, 0, 0, dpr, 0, 0);
    context.clearRect(0, 0, geometry.width, geometry.height);
    this.hitTargets = [];

    this.#drawBackground(context, geometry);
    this.#drawLayerHeadings(context, geometry);
    this.#drawDiscovery(context, geometry, timestamp);
    this.#drawSearch(context, geometry, timestamp);
    this.#drawWrite(context, geometry, timestamp);
    this.#drawLifecycle(context, geometry, timestamp);
    this.#drawTracking(context, geometry, timestamp);
  }

  #drawBackground(context, g) {
    const gradient = context.createLinearGradient(0, 0, g.width, g.height);
    gradient.addColorStop(0, "rgba(8,13,24,.98)");
    gradient.addColorStop(0.5, "rgba(8,12,23,.96)");
    gradient.addColorStop(1, "rgba(7,15,25,.98)");
    context.fillStyle = gradient;
    context.fillRect(0, 0, g.width, g.height);

    const glow = context.createRadialGradient(g.writeX, g.center, 10, g.writeX, g.center, Math.min(g.width, g.height) * 0.5);
    glow.addColorStop(0, "rgba(153,69,255,.10)");
    glow.addColorStop(0.42, "rgba(73,217,255,.035)");
    glow.addColorStop(1, "rgba(0,0,0,0)");
    context.fillStyle = glow;
    context.fillRect(0, 0, g.width, g.height);
  }

  #drawLayerHeadings(context, g) {
    const headings = [
      ["DISCOVERY", g.discoveryX, "discovery"],
      ["SEARCH", g.searchX, "search"],
      ["WRITE", g.writeX, "write"],
      ["LIFECYCLE", g.lifecycleX, "lifecycle"],
      ["TRACKING", g.trackingX, "tracking"],
    ];
    context.textAlign = "center";
    context.textBaseline = "middle";
    for (const [label, x, kind] of headings) {
      context.fillStyle = `rgba(${stageColor(kind)},.62)`;
      context.font = "700 10px Inter, system-ui, sans-serif";
      context.fillText(label, x, FLOW_PADDING_Y + 8);
      context.fillStyle = "rgba(243,245,248,.92)";
      context.font = "700 13px Inter, system-ui, sans-serif";
      context.fillText(this.#stageMetric(kind), x, FLOW_PADDING_Y + 29);
    }
  }

  #stageMetric(kind) {
    const model = this.model || {};
    if (kind === "discovery") {
      const total = (model.discovery || []).reduce((sum, event) => sum + finite(event.new_mints), 0);
      return `${formatNumber(total)} new / latest ticks`;
    }
    if (kind === "search") {
      const rpm = (model.lanes || []).reduce((sum, event) => sum + finite(event.rpm60), 0);
      return `${formatNumber(rpm)} rpm`;
    }
    if (kind === "write") {
      return model.flush ? `${formatNumber(model.flush.new_snapshots)} snapshots` : "waiting";
    }
    if (kind === "lifecycle") {
      return model.lifecycle ? `${formatNumber(model.lifecycle.affected_count)} affected` : "waiting";
    }
    if (kind === "tracking") {
      return model.lifecycle ? `${formatNumber(model.lifecycle.active_remaining)} tracking` : "waiting";
    }
    return "—";
  }

  #drawDiscovery(context, g, timestamp) {
    const events = this.model?.discovery || [];
    const count = Math.max(events.length, 1);
    const span = Math.min(g.bottom - g.top, 360);
    const startY = g.center - span / 2;
    const searchEntryX = g.searchX - 32;

    if (!events.length) {
      this.#drawEmptyLayer(context, g.discoveryX, g.center, "waiting for discovery");
      return;
    }

    events.forEach((event, index) => {
      const y = count === 1 ? g.center : startY + (span * index) / (count - 1);
      const newMints = finite(event.new_mints);
      const unique = finite(event.unique_candidates);
      const density = clamp(Math.log10(newMints + 1) / 1.5, 0.08, 1);
      const path = curve(g.discoveryX + 18, y, searchEntryX, g.center + (y - g.center) * 0.38, 0.48);

      context.strokeStyle = `rgba(20,241,217,${0.10 + density * 0.20})`;
      context.lineWidth = 0.8 + density * 1.5;
      drawCurve(context, path);
      this.#drawParticles(context, path, timestamp, {
        count: 1 + Math.round(density * 4),
        speed: 0.00010 + density * 0.00011,
        phase: hashString(String(event.source)) / 0xffffffff,
        color: "20,241,217",
        alpha: 0.35 + density * 0.55,
      });

      context.beginPath();
      context.arc(g.discoveryX, y, 8 + density * 3, 0, TAU);
      context.fillStyle = "rgba(9,23,34,.98)";
      context.fill();
      context.strokeStyle = "rgba(20,241,217,.72)";
      context.lineWidth = 1.2;
      context.stroke();

      context.textAlign = "right";
      context.fillStyle = "rgba(243,245,248,.90)";
      context.font = "650 11px Inter, system-ui, sans-serif";
      context.fillText(String(event.source), g.discoveryX - 15, y - 2);
      context.fillStyle = "rgba(146,155,173,.72)";
      context.font = "10px Inter, system-ui, sans-serif";
      context.fillText(`${formatNumber(unique)} unique · ${formatNumber(newMints)} new`, g.discoveryX - 15, y + 13);

      this.hitTargets.push({
        x: g.discoveryX - 90,
        y: y - 22,
        width: 105,
        height: 44,
        title: String(event.source),
        lines: [
          `${formatNumber(event.response_items)} raw`,
          `${formatNumber(event.unique_candidates)} unique`,
          `${formatNumber(event.new_mints)} new`,
          `latency ${formatMs(event.latency_ms)}`,
        ],
      });
    });
  }

  #drawSearch(context, g, timestamp) {
    const lanes = this.model?.lanes || [];
    const laneCount = Math.max(lanes.length, 1);
    const rows = Math.min(16, Math.ceil(Math.sqrt(laneCount * 2)));
    const columns = Math.ceil(laneCount / rows);
    const cellX = 12;
    const cellY = 16;
    const width = Math.max(34, columns * cellX);
    const height = Math.max(120, rows * cellY);
    const left = g.searchX - width / 2;
    const top = g.center - height / 2;

    context.fillStyle = "rgba(10,19,32,.68)";
    context.strokeStyle = "rgba(73,217,255,.18)";
    context.lineWidth = 1;
    context.beginPath();
    context.roundRect(left - 18, top - 20, width + 36, height + 40, 18);
    context.fill();
    context.stroke();

    if (!lanes.length) {
      this.#drawEmptyLayer(context, g.searchX, g.center, "waiting for lanes");
      return;
    }

    lanes.forEach((lane, index) => {
      const row = index % rows;
      const column = Math.floor(index / rows);
      const x = left + column * cellX + cellX / 2;
      const y = top + row * cellY + cellY / 2;
      const rpm = finite(lane.rpm60);
      const latency = Math.max(80, finite(lane.latency_ms, 900));
      const statusGood = lane.status === 200;
      const intensity = clamp(rpm / 58, 0.15, 1);

      context.beginPath();
      context.arc(x, y, STAGE_DOT_RADIUS + intensity * 1.4, 0, TAU);
      context.fillStyle = statusGood
        ? `rgba(73,217,255,${0.36 + intensity * 0.58})`
        : "rgba(255,92,119,.92)";
      context.fill();

      const path = curve(x, y, g.writeX - 58, g.center + (row / Math.max(rows - 1, 1) - 0.5) * 210, 0.55);
      context.strokeStyle = statusGood
        ? `rgba(73,217,255,${0.035 + intensity * 0.065})`
        : "rgba(255,92,119,.12)";
      context.lineWidth = 0.55 + intensity * 0.65;
      drawCurve(context, path);

      const speed = clamp(1 / latency, 0.00035, 0.004) * 0.55;
      this.#drawParticles(context, path, timestamp, {
        count: statusGood ? 1 + Math.round(intensity * 2) : 1,
        speed,
        phase: (hashString(String(lane.lane)) % 1000) / 1000,
        color: statusGood ? "73,217,255" : "255,92,119",
        alpha: statusGood ? 0.28 + intensity * 0.58 : 0.72,
      });
    });

    this.hitTargets.push({
      x: left - 18,
      y: top - 20,
      width: width + 36,
      height: height + 40,
      title: "Jupiter Search",
      lines: [
        `${lanes.length} lanes`,
        `${formatNumber(lanes.reduce((sum, lane) => sum + finite(lane.rpm60), 0))} aggregate rpm`,
        `median latency ${formatMs(this.#median(lanes.map(lane => lane.latency_ms)))}`,
      ],
    });
  }

  #drawWrite(context, g, timestamp) {
    const flush = this.model?.flush;
    const values = flush
      ? [finite(flush.polled_tokens), finite(flush.source_versions), finite(flush.new_snapshots)]
      : [0, 0, 0];
    const labels = ["POLLS", "VERSIONS", "SNAPSHOTS"];
    const xs = [g.writeX - 44, g.writeX, g.writeX + 44];
    const maxValue = Math.max(...values, 1);

    for (let index = 0; index < 3; index += 1) {
      const ratio = Math.sqrt(values[index] / maxValue);
      const rows = 11;
      const cols = 4;
      for (let row = 0; row < rows; row += 1) {
        for (let col = 0; col < cols; col += 1) {
          const normalized = (row * cols + col) / (rows * cols - 1);
          const active = normalized <= ratio;
          const x = xs[index] + (col - 1.5) * 8;
          const y = g.center + (row - (rows - 1) / 2) * 12;
          context.beginPath();
          context.arc(x, y, active ? 2.6 : 1.8, 0, TAU);
          context.fillStyle = active
            ? `rgba(153,69,255,${0.38 + ratio * 0.54})`
            : "rgba(153,69,255,.08)";
          context.fill();
        }
      }

      context.textAlign = "center";
      context.fillStyle = "rgba(146,155,173,.62)";
      context.font = "700 8px Inter, system-ui, sans-serif";
      context.fillText(labels[index], xs[index], g.center + 86);
      context.fillStyle = "rgba(243,245,248,.92)";
      context.font = "700 11px Inter, system-ui, sans-serif";
      context.fillText(formatNumber(values[index]), xs[index], g.center + 102);
    }

    if (flush) {
      for (let index = 0; index < 2; index += 1) {
        const ratio = clamp(values[index + 1] / Math.max(values[index], 1), 0, 1);
        const path = curve(xs[index] + 18, g.center, xs[index + 1] - 18, g.center, 0.46);
        context.strokeStyle = `rgba(153,69,255,${0.12 + ratio * 0.30})`;
        context.lineWidth = 1.5 + ratio * 5;
        drawCurve(context, path);
        this.#drawParticles(context, path, timestamp, {
          count: 2 + Math.round(ratio * 5),
          speed: 0.00016,
          phase: 0.21 + index * 0.31,
          color: "183,124,255",
          alpha: 0.58,
        });
      }
    }

    this.hitTargets.push({
      x: g.writeX - 78,
      y: g.center - 92,
      width: 156,
      height: 210,
      title: "WriteQueue condensation",
      lines: flush ? [
        `${formatNumber(flush.polled_tokens)} polls`,
        `${formatNumber(flush.source_versions)} source versions`,
        `${formatNumber(flush.new_snapshots)} new snapshots`,
        `queue ${formatNumber(flush.queue_size)} · write ${formatMs(flush.write_ms)}`,
      ] : ["Waiting for first flush"],
    });

    const toLifecycle = curve(g.writeX + 64, g.center, g.lifecycleX - 55, g.center, 0.5);
    context.strokeStyle = "rgba(183,124,255,.14)";
    context.lineWidth = 1.4;
    drawCurve(context, toLifecycle);
    if (flush) this.#drawParticles(context, toLifecycle, timestamp, {
      count: clamp(1 + Math.round(Math.log10(finite(flush.new_snapshots) + 1) * 2), 1, 6),
      speed: 0.00014,
      phase: 0.4,
      color: "183,124,255",
      alpha: 0.62,
    });
  }

  #drawLifecycle(context, g, timestamp) {
    const lifecycle = this.model?.lifecycle;
    const breakdown = lifecycle?.breakdown || {};
    const ruleKeys = ["rule1", "rule2", "rule3", "rule4", "rule5", "rule6", "rule7"];
    const span = 280;
    const startY = g.center - span / 2;

    ruleKeys.forEach((key, index) => {
      const y = startY + (span * index) / (ruleKeys.length - 1);
      const affected = finite(breakdown[key]);
      const intensity = clamp(Math.log10(affected + 1) / 2, 0, 1);
      context.beginPath();
      context.arc(g.lifecycleX, y, 8 + intensity * 4, 0, TAU);
      context.fillStyle = affected > 0
        ? `rgba(214,88,255,${0.42 + intensity * 0.48})`
        : "rgba(26,22,42,.96)";
      context.fill();
      context.strokeStyle = affected > 0 ? "rgba(214,88,255,.92)" : "rgba(214,88,255,.24)";
      context.lineWidth = 1.2;
      context.stroke();

      context.textAlign = "left";
      context.fillStyle = "rgba(243,245,248,.82)";
      context.font = "700 10px Inter, system-ui, sans-serif";
      context.fillText(`R${index + 1}`, g.lifecycleX + 17, y + 1);
      context.fillStyle = "rgba(146,155,173,.72)";
      context.font = "9px Inter, system-ui, sans-serif";
      context.fillText(formatNumber(affected), g.lifecycleX + 17, y + 13);
    });

    const survivorPath = curve(g.lifecycleX + 28, g.center, g.trackingX - 46, g.center, 0.50);
    context.strokeStyle = "rgba(20,241,217,.22)";
    context.lineWidth = 2.2;
    drawCurve(context, survivorPath);
    if (lifecycle) this.#drawParticles(context, survivorPath, timestamp, {
      count: 5,
      speed: 0.00013,
      phase: 0.13,
      color: "20,241,217",
      alpha: 0.72,
    });

    if (lifecycle && finite(lifecycle.affected_count) > 0 && ageSeconds(lifecycle.at, Date.now()) < 30) {
      const exit = curve(g.lifecycleX, g.center + 46, g.lifecycleX + 70, g.bottom + 18, 0.35);
      const intensity = clamp(Math.log10(finite(lifecycle.affected_count) + 1) / 2.5, 0.25, 1);
      context.strokeStyle = `rgba(255,92,119,${0.18 + intensity * 0.48})`;
      context.lineWidth = 1.5 + intensity * 4;
      drawCurve(context, exit);
      this.#drawParticles(context, exit, timestamp, {
        count: 2 + Math.round(intensity * 7),
        speed: 0.00018,
        phase: 0.7,
        color: "255,92,119",
        alpha: 0.88,
      });
      context.textAlign = "left";
      context.fillStyle = "rgba(255,125,147,.90)";
      context.font = "700 10px Inter, system-ui, sans-serif";
      context.fillText(`${formatNumber(lifecycle.affected_count)} ${lifecycle.apply ? "RETIRED" : "CANDIDATES"}`, g.lifecycleX + 80, g.bottom - 2);
    }

    this.hitTargets.push({
      x: g.lifecycleX - 22,
      y: startY - 18,
      width: 95,
      height: span + 42,
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
      const x = g.trackingX + Math.cos(angle) * r;
      const y = g.center + Math.sin(angle) * r;
      context.beginPath();
      context.arc(x, y, 1.8 + (index % 5 === 0 ? 0.8 : 0), 0, TAU);
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

    const loop = {
      x0: g.trackingX - 12,
      y0: g.center - radius - 4,
      x1: g.trackingX - 90,
      y1: g.top - 80,
      x2: g.searchX + 90,
      y2: g.top - 80,
      x3: g.searchX + 18,
      y3: g.center - 78,
    };
    context.strokeStyle = "rgba(20,241,217,.13)";
    context.lineWidth = 1.4;
    drawCurve(context, loop);
    if (lifecycle) this.#drawParticles(context, loop, timestamp, {
      count: 7,
      speed: 0.000075,
      phase: 0.08,
      color: "20,241,217",
      alpha: 0.55,
    });
    context.textAlign = "center";
    context.fillStyle = "rgba(20,241,217,.46)";
    context.font = "700 9px Inter, system-ui, sans-serif";
    context.fillText("MONITORING LOOP", (g.trackingX + g.searchX) / 2, g.top - 43);

    this.hitTargets.push({
      x: g.trackingX - radius,
      y: g.center - radius,
      width: radius * 2,
      height: radius * 2,
      title: "Tracking survivors",
      lines: lifecycle ? [
        `${formatNumber(lifecycle.active_remaining)} tracking`,
        "returns to Jupiter Search monitoring",
        "not identical to Observatory ACTIVE",
      ] : ["Waiting for lifecycle telemetry"],
    });
  }

  #drawParticles(context, path, timestamp, options) {
    const count = Math.max(1, Math.round(options.count || 1));
    const speed = options.speed || 0.0001;
    for (let index = 0; index < count; index += 1) {
      const phase = (options.phase || 0) + index / count;
      const t = ((timestamp * speed + phase) % 1 + 1) % 1;
      const point = bezierPoint(path, t);
      const tail = bezierPoint(path, clamp(t - 0.035, 0, 1));
      const gradient = context.createLinearGradient(tail.x, tail.y, point.x, point.y);
      gradient.addColorStop(0, `rgba(${options.color},0)`);
      gradient.addColorStop(1, `rgba(${options.color},${options.alpha || 0.6})`);
      context.strokeStyle = gradient;
      context.lineWidth = 1.3;
      context.beginPath();
      context.moveTo(tail.x, tail.y);
      context.lineTo(point.x, point.y);
      context.stroke();
      context.beginPath();
      context.arc(point.x, point.y, PARTICLE_RADIUS, 0, TAU);
      context.fillStyle = `rgba(${options.color},${options.alpha || 0.6})`;
      context.fill();
    }
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
    const left = clamp(x + 18, 12, rect.width - tooltipRect.width - 12);
    const top = clamp(y + 18, 12, rect.height - tooltipRect.height - 12);
    this.tooltip.style.left = `${left}px`;
    this.tooltip.style.top = `${top}px`;
  }

  #hideTooltip() {
    this.tooltip?.classList.add("hidden");
  }
}
