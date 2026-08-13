import { count, money, tokenIdentity } from "../format.js";
import { normalizedLaunchpad } from "../state.js";

const GOLDEN_ANGLE = Math.PI * (3 - Math.sqrt(5));
const MIN_ZOOM = 0.16;
const MAX_ZOOM = 5;
const NODE_RADIUS_MIN = 5;
const NODE_RADIUS_MAX = 30;
const SLOT_SPACING = 32;
const HUB_RADIUS = 26;
const TRANSITION_MS = 520;
const RETIRE_MS = 760;
const SCALE_MODES = [
  ["market_cap", "Market cap"],
  ["liquidity", "Liquidity"],
  ["economic", "Economic mix"],
];

function finitePositive(value) {
  return Number.isFinite(value) && value > 0 ? value : null;
}

function hashString(value) {
  let hash = 2166136261;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

function percentile(sorted, fraction) {
  if (!sorted.length) return null;
  const position = Math.max(0, Math.min(sorted.length - 1, fraction * (sorted.length - 1)));
  const lower = Math.floor(position);
  const upper = Math.ceil(position);
  if (lower === upper) return sorted[lower];
  const weight = position - lower;
  return sorted[lower] * (1 - weight) + sorted[upper] * weight;
}

function robustLogRange(tokens, field) {
  const values = tokens
    .map(token => finitePositive(token[field]))
    .filter(value => value != null)
    .map(value => Math.log10(value + 1))
    .sort((left, right) => left - right);
  if (!values.length) return null;
  const low = percentile(values, 0.02);
  const high = percentile(values, 0.98);
  return {
    low,
    high: high > low ? high : low + 1,
  };
}

function normalizedLog(value, range) {
  const positive = finitePositive(value);
  if (positive == null || !range) return null;
  const logged = Math.log10(positive + 1);
  return Math.max(0, Math.min(1, (logged - range.low) / (range.high - range.low)));
}

function buildSizeScores(tokens, mode) {
  const marketRange = robustLogRange(tokens, "market_cap");
  const liquidityRange = robustLogRange(tokens, "liquidity");
  const scores = new Map();

  for (const token of tokens) {
    const market = normalizedLog(token.market_cap, marketRange);
    const liquidity = normalizedLog(token.liquidity, liquidityRange);
    let score = null;
    if (mode === "market_cap") score = market;
    else if (mode === "liquidity") score = liquidity;
    else if (market != null && liquidity != null) score = (market + liquidity) / 2;
    scores.set(token.mint, score);
  }
  return scores;
}

function radiusForScore(score) {
  if (score == null) return NODE_RADIUS_MIN;
  const minArea = NODE_RADIUS_MIN ** 2;
  const maxArea = NODE_RADIUS_MAX ** 2;
  return Math.sqrt(minArea + score * (maxArea - minArea));
}

function buildHolderScale(tokens) {
  const values = tokens
    .map(token => finitePositive(token.holders))
    .filter(value => value != null)
    .map(value => Math.log10(value + 1))
    .sort((left, right) => left - right);
  const ceiling = percentile(values, 0.95);
  return holders => {
    const value = finitePositive(holders);
    if (value == null || ceiling == null || ceiling <= 0) return null;
    return Math.max(0, Math.min(1, Math.log10(value + 1) / ceiling));
  };
}

function easeOutCubic(value) {
  const t = Math.max(0, Math.min(1, value));
  return 1 - (1 - t) ** 3;
}

function shortLabel(token) {
  return token.symbol || token.name || token.mint.slice(0, 6);
}

export class TokenUniverseView {
  constructor(stageElement, { onSelect } = {}) {
    this.stageElement = stageElement;
    this.onSelect = onSelect || (() => {});
    this.root = null;
    this.canvas = null;
    this.context = null;
    this.launchpadControls = null;
    this.scaleControls = null;
    this.status = null;
    this.resizeObserver = null;
    this.nodes = new Map();
    this.hubs = new Map();
    this.slots = new Map();
    this.nextSlots = new Map();
    this.enabledLaunchpads = new Set();
    this.knownLaunchpads = [];
    this.tokens = [];
    this.selectedMint = null;
    this.lastSelectedMint = null;
    this.selectionOrigin = null;
    this.scaleMode = "market_cap";
    this.viewport = { x: 0, y: 0, k: 1 };
    this.fitted = false;
    this.drag = null;
    this.exitGhosts = [];
    this.frame = null;
    this.worldBounds = null;
  }

  init() {
    this.root = document.createElement("div");
    this.root.className = "token-universe-view";
    this.root.setAttribute("data-view", "token-universe");

    const controls = document.createElement("div");
    controls.className = "token-universe-controls";

    const launchpadGroup = document.createElement("div");
    launchpadGroup.className = "token-universe-control-group launchpad-group";
    const launchpadLabel = document.createElement("span");
    launchpadLabel.className = "token-universe-control-label";
    launchpadLabel.textContent = "Launchpads";
    this.launchpadControls = document.createElement("div");
    this.launchpadControls.className = "token-universe-launchpads";
    launchpadGroup.append(launchpadLabel, this.launchpadControls);

    const scaleGroup = document.createElement("div");
    scaleGroup.className = "token-universe-control-group scale-group";
    const scaleLabel = document.createElement("span");
    scaleLabel.className = "token-universe-control-label";
    scaleLabel.textContent = "Bubble area";
    this.scaleControls = document.createElement("div");
    this.scaleControls.className = "token-universe-scale";
    for (const [value, label] of SCALE_MODES) {
      const button = document.createElement("button");
      button.type = "button";
      button.dataset.scaleMode = value;
      button.textContent = label;
      button.addEventListener("click", () => {
        this.scaleMode = value;
        this.#syncScaleControls();
        this.#buildLayout([]);
        this.#draw();
      });
      this.scaleControls.append(button);
    }
    scaleGroup.append(scaleLabel, this.scaleControls);

    const reset = document.createElement("button");
    reset.type = "button";
    reset.className = "token-universe-reset";
    reset.textContent = "Fit all";
    reset.addEventListener("click", () => this.fitAll());

    this.status = document.createElement("span");
    this.status.className = "token-universe-status";

    controls.append(launchpadGroup, scaleGroup, reset, this.status);

    this.canvas = document.createElement("canvas");
    this.canvas.className = "token-universe-canvas";
    this.canvas.setAttribute("aria-label", "Launchpad-centered active token universe");
    this.canvas.tabIndex = 0;
    this.context = this.canvas.getContext("2d");

    const legend = document.createElement("div");
    legend.className = "token-universe-legend";
    legend.innerHTML = "<span>Bubble area = selected economic scale</span><span>Spoke strength = holders</span><span>Scroll = zoom · drag = pan</span>";

    this.root.append(this.canvas, controls, legend);
    this.stageElement.replaceChildren(this.root);
    this.#bindCanvas();
    this.#syncScaleControls();

    this.resizeObserver = new ResizeObserver(() => {
      this.#resizeCanvas();
      if (!this.fitted) this.fitAll();
      else this.#draw();
    });
    this.resizeObserver.observe(this.root);
    this.#resizeCanvas();
  }

  render({ tokens, selectedMint, events = [] }) {
    const previousNodes = this.nodes;
    const active = tokens.filter(token => token.tracking_enabled);
    const launchpads = [...new Set(active.map(normalizedLaunchpad))].sort((a, b) => a.localeCompare(b));

    if (!this.knownLaunchpads.length) {
      for (const launchpad of launchpads) this.enabledLaunchpads.add(launchpad);
    } else {
      for (const launchpad of launchpads) {
        if (!this.knownLaunchpads.includes(launchpad)) this.enabledLaunchpads.add(launchpad);
      }
    }

    this.knownLaunchpads = launchpads;
    this.tokens = active;
    this.selectedMint = selectedMint;

    const selectedToken = selectedMint ? active.find(token => token.mint === selectedMint) : null;
    if (selectedToken) this.enabledLaunchpads.add(normalizedLaunchpad(selectedToken));

    const now = performance.now();
    for (const event of events) {
      if (event?.type !== "token_retired" || !event?.token?.mint) continue;
      const previous = previousNodes.get(event.token.mint);
      if (!previous) continue;
      this.exitGhosts.push({
        ...previous,
        retiredAt: now,
        retireUntil: now + RETIRE_MS,
      });
    }

    this.#syncLaunchpadControls();
    this.#buildLayout(events);

    const selectionChanged = selectedMint && selectedMint !== this.lastSelectedMint;
    if (selectionChanged && this.selectionOrigin !== "view") this.#focusSelected();
    this.lastSelectedMint = selectedMint;
    this.selectionOrigin = null;

    if (!this.fitted) this.fitAll();
    else this.#draw();
  }

  destroy() {
    if (this.frame) cancelAnimationFrame(this.frame);
    this.resizeObserver?.disconnect();
    this.root?.remove();
    this.nodes.clear();
    this.hubs.clear();
    this.root = null;
  }

  fitAll() {
    if (!this.canvas || !this.worldBounds) return;
    const width = this.canvas.clientWidth;
    const height = this.canvas.clientHeight;
    if (!width || !height) return;

    const margin = 90;
    const bounds = this.worldBounds;
    const worldWidth = Math.max(1, bounds.maxX - bounds.minX + margin * 2);
    const worldHeight = Math.max(1, bounds.maxY - bounds.minY + margin * 2);
    const k = Math.max(MIN_ZOOM, Math.min(1.2, width / worldWidth, height / worldHeight));
    const centerX = (bounds.minX + bounds.maxX) / 2;
    const centerY = (bounds.minY + bounds.maxY) / 2;
    this.viewport = {
      k,
      x: width / 2 - centerX * k,
      y: height / 2 - centerY * k,
    };
    this.fitted = true;
    this.#draw();
  }

  #syncScaleControls() {
    for (const button of this.scaleControls?.querySelectorAll("button") || []) {
      const active = button.dataset.scaleMode === this.scaleMode;
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", String(active));
    }
  }

  #syncLaunchpadControls() {
    if (!this.launchpadControls) return;
    this.launchpadControls.replaceChildren();

    const all = document.createElement("button");
    all.type = "button";
    all.textContent = "All";
    all.className = this.knownLaunchpads.every(item => this.enabledLaunchpads.has(item)) ? "active" : "";
    all.addEventListener("click", () => {
      const allEnabled = this.knownLaunchpads.every(item => this.enabledLaunchpads.has(item));
      this.enabledLaunchpads = new Set(allEnabled ? [] : this.knownLaunchpads);
      this.#syncLaunchpadControls();
      this.#buildLayout([]);
      this.fitAll();
    });
    this.launchpadControls.append(all);

    for (const launchpad of this.knownLaunchpads) {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = launchpad;
      const active = this.enabledLaunchpads.has(launchpad);
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", String(active));
      button.addEventListener("click", () => {
        if (this.enabledLaunchpads.has(launchpad)) this.enabledLaunchpads.delete(launchpad);
        else this.enabledLaunchpads.add(launchpad);
        this.#syncLaunchpadControls();
        this.#buildLayout([]);
        this.fitAll();
      });
      this.launchpadControls.append(button);
    }
  }

  #ensureSlots(groups) {
    for (const [launchpad, group] of groups) {
      if (!this.slots.has(launchpad)) this.slots.set(launchpad, new Map());
      const slots = this.slots.get(launchpad);
      let next = this.nextSlots.get(launchpad) || 0;
      const unassigned = group
        .filter(token => !slots.has(token.mint))
        .sort((left, right) => left.mint.localeCompare(right.mint));
      for (const token of unassigned) {
        slots.set(token.mint, next);
        next += 1;
      }
      this.nextSlots.set(launchpad, next);
    }
  }

  #buildLayout(events) {
    const groups = new Map();
    for (const launchpad of this.knownLaunchpads) groups.set(launchpad, []);
    for (const token of this.tokens) groups.get(normalizedLaunchpad(token))?.push(token);
    this.#ensureSlots(groups);

    const maxCount = Math.max(1, ...[...groups.values()].map(group => group.length));
    const clusterRadius = 90 + SLOT_SPACING * Math.sqrt(maxCount);
    const cellWidth = clusterRadius * 2 + 220;
    const cellHeight = clusterRadius * 2 + 180;
    const columns = Math.max(1, Math.ceil(Math.sqrt(this.knownLaunchpads.length * 1.45)));
    const rows = Math.max(1, Math.ceil(this.knownLaunchpads.length / columns));

    this.hubs = new Map();
    for (let index = 0; index < this.knownLaunchpads.length; index += 1) {
      const launchpad = this.knownLaunchpads[index];
      const column = index % columns;
      const row = Math.floor(index / columns);
      const x = (column - (columns - 1) / 2) * cellWidth;
      const y = (row - (rows - 1) / 2) * cellHeight;
      this.hubs.set(launchpad, { launchpad, x, y, count: groups.get(launchpad)?.length || 0 });
    }

    const sizeScores = buildSizeScores(this.tokens, this.scaleMode);
    const holderScale = buildHolderScale(this.tokens);
    const eventByMint = new Map(events.filter(event => event?.token?.mint).map(event => [event.token.mint, event]));
    const now = performance.now();
    const nextNodes = new Map();

    for (const token of this.tokens) {
      const launchpad = normalizedLaunchpad(token);
      const hub = this.hubs.get(launchpad);
      const slot = this.slots.get(launchpad)?.get(token.mint) || 0;
      const phase = (hashString(launchpad) % 360) * Math.PI / 180;
      const angle = phase + slot * GOLDEN_ANGLE;
      const radial = 62 + SLOT_SPACING * Math.sqrt(slot);
      const targetRadius = radiusForScore(sizeScores.get(token.mint));
      const previous = this.nodes.get(token.mint);
      const event = eventByMint.get(token.mint);
      const transitioning = event?.type === "token_added" || event?.type === "token_updated";
      const holderScore = holderScale(token.holders);

      nextNodes.set(token.mint, {
        mint: token.mint,
        token,
        launchpad,
        x: hub.x + Math.cos(angle) * radial,
        y: hub.y + Math.sin(angle) * radial,
        radius: targetRadius,
        fromRadius: event?.type === "token_added" ? 1 : previous?.radius ?? targetRadius,
        targetRadius,
        transitionStart: transitioning ? now : 0,
        transitionUntil: transitioning ? now + TRANSITION_MS : 0,
        transitionType: event?.type || null,
        holderScore,
        missingScale: sizeScores.get(token.mint) == null,
      });
    }

    this.nodes = nextNodes;
    const visibleHubs = [...this.hubs.values()].filter(hub => this.enabledLaunchpads.has(hub.launchpad));
    const visibleNodes = [...this.nodes.values()].filter(node => this.enabledLaunchpads.has(node.launchpad));
    const positions = [
      ...visibleHubs.map(hub => ({ x: hub.x, y: hub.y, radius: HUB_RADIUS })),
      ...visibleNodes.map(node => ({ x: node.x, y: node.y, radius: node.radius })),
    ];
    if (positions.length) {
      this.worldBounds = {
        minX: Math.min(...positions.map(item => item.x - item.radius)),
        maxX: Math.max(...positions.map(item => item.x + item.radius)),
        minY: Math.min(...positions.map(item => item.y - item.radius)),
        maxY: Math.max(...positions.map(item => item.y + item.radius)),
      };
    } else {
      this.worldBounds = { minX: -100, maxX: 100, minY: -100, maxY: 100 };
    }

    this.status.textContent = `${visibleNodes.length.toLocaleString()} visible · ${this.enabledLaunchpads.size}/${this.knownLaunchpads.length} launchpads`;
    this.#scheduleFrame();
  }

  #focusSelected() {
    const node = this.selectedMint ? this.nodes.get(this.selectedMint) : null;
    if (!node || !this.enabledLaunchpads.has(node.launchpad) || !this.canvas) return;
    const width = this.canvas.clientWidth;
    const height = this.canvas.clientHeight;
    const k = Math.max(this.viewport.k, 1.15);
    this.viewport = {
      k,
      x: width / 2 - node.x * k,
      y: height / 2 - node.y * k,
    };
  }

  #bindCanvas() {
    this.canvas.addEventListener("wheel", event => {
      event.preventDefault();
      const rect = this.canvas.getBoundingClientRect();
      const px = event.clientX - rect.left;
      const py = event.clientY - rect.top;
      const oldK = this.viewport.k;
      const nextK = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, oldK * Math.exp(-event.deltaY * 0.0014)));
      const worldX = (px - this.viewport.x) / oldK;
      const worldY = (py - this.viewport.y) / oldK;
      this.viewport.k = nextK;
      this.viewport.x = px - worldX * nextK;
      this.viewport.y = py - worldY * nextK;
      this.fitted = true;
      this.#draw();
    }, { passive: false });

    this.canvas.addEventListener("pointerdown", event => {
      this.canvas.setPointerCapture(event.pointerId);
      this.drag = {
        pointerId: event.pointerId,
        startX: event.clientX,
        startY: event.clientY,
        originX: this.viewport.x,
        originY: this.viewport.y,
        moved: false,
      };
    });

    this.canvas.addEventListener("pointermove", event => {
      if (this.drag?.pointerId === event.pointerId) {
        const dx = event.clientX - this.drag.startX;
        const dy = event.clientY - this.drag.startY;
        if (Math.hypot(dx, dy) > 3) this.drag.moved = true;
        if (this.drag.moved) {
          this.viewport.x = this.drag.originX + dx;
          this.viewport.y = this.drag.originY + dy;
          this.fitted = true;
          this.#draw();
        }
        return;
      }
      this.canvas.style.cursor = this.#hitNode(event.clientX, event.clientY) ? "pointer" : "grab";
    });

    const finish = event => {
      if (!this.drag || this.drag.pointerId !== event.pointerId) return;
      const moved = this.drag.moved;
      this.drag = null;
      if (!moved) {
        const node = this.#hitNode(event.clientX, event.clientY);
        if (node) {
          this.selectionOrigin = "view";
          this.onSelect(node.mint);
        }
      }
    };
    this.canvas.addEventListener("pointerup", finish);
    this.canvas.addEventListener("pointercancel", finish);
  }

  #hitNode(clientX, clientY) {
    const rect = this.canvas.getBoundingClientRect();
    const x = clientX - rect.left;
    const y = clientY - rect.top;
    const visible = [...this.nodes.values()].filter(node => this.enabledLaunchpads.has(node.launchpad));
    for (let index = visible.length - 1; index >= 0; index -= 1) {
      const node = visible[index];
      const sx = node.x * this.viewport.k + this.viewport.x;
      const sy = node.y * this.viewport.k + this.viewport.y;
      const radius = Math.max(5, node.radius * this.viewport.k);
      if (Math.hypot(x - sx, y - sy) <= radius + 3) return node;
    }
    return null;
  }

  #resizeCanvas() {
    if (!this.canvas || !this.context) return;
    const rect = this.canvas.getBoundingClientRect();
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const width = Math.max(1, Math.round(rect.width * dpr));
    const height = Math.max(1, Math.round(rect.height * dpr));
    if (this.canvas.width === width && this.canvas.height === height) return;
    this.canvas.width = width;
    this.canvas.height = height;
    this.canvas.dataset.dpr = String(dpr);
  }

  #scheduleFrame() {
    if (this.frame) return;
    this.frame = requestAnimationFrame(timestamp => {
      this.frame = null;
      const animate = this.#draw(timestamp);
      if (animate) this.#scheduleFrame();
    });
  }

  #draw(timestamp = performance.now()) {
    if (!this.canvas || !this.context) return false;
    this.#resizeCanvas();
    const context = this.context;
    const dpr = Number(this.canvas.dataset.dpr || 1);
    const width = this.canvas.width / dpr;
    const height = this.canvas.height / dpr;
    context.setTransform(dpr, 0, 0, dpr, 0, 0);
    context.clearRect(0, 0, width, height);

    const visibleNodes = [...this.nodes.values()].filter(node => this.enabledLaunchpads.has(node.launchpad));
    let animating = false;

    context.save();
    context.translate(this.viewport.x, this.viewport.y);
    context.scale(this.viewport.k, this.viewport.k);

    for (const node of visibleNodes) {
      const hub = this.hubs.get(node.launchpad);
      const score = node.holderScore;
      context.beginPath();
      context.moveTo(hub.x, hub.y);
      context.lineTo(node.x, node.y);
      if (score == null) {
        context.setLineDash([4 / this.viewport.k, 6 / this.viewport.k]);
        context.strokeStyle = "rgba(146,155,173,.10)";
        context.lineWidth = 0.7 / this.viewport.k;
      } else {
        context.setLineDash([]);
        context.strokeStyle = `rgba(20,241,217,${0.08 + score * 0.42})`;
        context.lineWidth = (0.65 + score * 1.7) / this.viewport.k;
      }
      context.stroke();
    }
    context.setLineDash([]);

    for (const hub of this.hubs.values()) {
      if (!this.enabledLaunchpads.has(hub.launchpad)) continue;
      context.beginPath();
      context.arc(hub.x, hub.y, HUB_RADIUS, 0, Math.PI * 2);
      context.fillStyle = "#151b2a";
      context.fill();
      context.strokeStyle = "rgba(153,69,255,.9)";
      context.lineWidth = 2 / this.viewport.k;
      context.stroke();

      context.fillStyle = "#f3f5f8";
      context.font = `${Math.max(11, 14 / this.viewport.k)}px Inter, system-ui, sans-serif`;
      context.textAlign = "center";
      context.textBaseline = "middle";
      context.fillText(hub.launchpad, hub.x, hub.y - 2);
      context.fillStyle = "#929bad";
      context.font = `${Math.max(9, 10 / this.viewport.k)}px Inter, system-ui, sans-serif`;
      context.fillText(String(hub.count), hub.x, hub.y + 15 / this.viewport.k);
    }

    for (const node of visibleNodes) {
      const progress = node.transitionUntil > timestamp
        ? easeOutCubic((timestamp - node.transitionStart) / TRANSITION_MS)
        : 1;
      if (node.transitionUntil > timestamp) animating = true;
      const radius = node.transitionUntil > timestamp
        ? node.fromRadius + (node.targetRadius - node.fromRadius) * progress
        : node.targetRadius;
      node.radius = radius;

      const selected = node.mint === this.selectedMint;
      const pulse = node.transitionUntil > timestamp ? 1 - progress : 0;
      context.beginPath();
      context.arc(node.x, node.y, radius, 0, Math.PI * 2);
      context.fillStyle = selected ? "rgba(20,241,217,.17)" : "rgba(15,20,32,.94)";
      context.fill();
      if (node.missingScale) context.setLineDash([3 / this.viewport.k, 3 / this.viewport.k]);
      context.strokeStyle = selected
        ? "#14f1d9"
        : node.transitionType === "token_added" && pulse > 0
          ? `rgba(61,220,151,${0.55 + pulse * 0.4})`
          : `rgba(73,217,255,${0.28 + pulse * 0.42})`;
      context.lineWidth = (selected ? 2.4 : 1.1) / this.viewport.k;
      context.stroke();
      context.setLineDash([]);

      if (pulse > 0) {
        context.beginPath();
        context.arc(node.x, node.y, radius + (1 - pulse) * 12 + 3, 0, Math.PI * 2);
        context.strokeStyle = `rgba(183,124,255,${pulse * 0.28})`;
        context.lineWidth = 1.2 / this.viewport.k;
        context.stroke();
      }

      this.#drawNodeLabel(context, node, radius);
    }

    this.exitGhosts = this.exitGhosts.filter(ghost => ghost.retireUntil > timestamp);
    for (const ghost of this.exitGhosts) {
      if (!this.enabledLaunchpads.has(ghost.launchpad)) continue;
      animating = true;
      const progress = Math.max(0, Math.min(1, (timestamp - ghost.retiredAt) / RETIRE_MS));
      const radius = ghost.radius * (1 - progress * 0.35);
      context.beginPath();
      context.arc(ghost.x, ghost.y, radius, 0, Math.PI * 2);
      context.fillStyle = `rgba(255,92,119,${0.25 * (1 - progress)})`;
      context.fill();
      context.strokeStyle = `rgba(255,92,119,${0.9 * (1 - progress)})`;
      context.lineWidth = 2 / this.viewport.k;
      context.stroke();
    }

    context.restore();
    return animating;
  }

  #drawNodeLabel(context, node, radius) {
    const screenRadius = radius * this.viewport.k;
    if (screenRadius < 10) return;

    const label = shortLabel(node.token);
    const fontSize = Math.max(8, Math.min(12, screenRadius * 0.52)) / this.viewport.k;
    context.fillStyle = "#f3f5f8";
    context.font = `700 ${fontSize}px Inter, system-ui, sans-serif`;
    context.textAlign = "center";
    context.textBaseline = "middle";
    context.fillText(label.slice(0, 10), node.x, node.y - (screenRadius >= 21 ? 5 / this.viewport.k : 0));

    if (screenRadius < 21) return;
    context.fillStyle = "#929bad";
    context.font = `${Math.max(7, 8.5 / this.viewport.k)}px Inter, system-ui, sans-serif`;
    const metric = this.scaleMode === "liquidity"
      ? `L ${money(node.token.liquidity)}`
      : this.scaleMode === "economic"
        ? `${money(node.token.market_cap)} · ${money(node.token.liquidity)}`
        : `MC ${money(node.token.market_cap)}`;
    context.fillText(metric, node.x, node.y + 8 / this.viewport.k);

    if (screenRadius >= 34) {
      context.fillStyle = "#626c7e";
      context.font = `${Math.max(7, 8 / this.viewport.k)}px Inter, system-ui, sans-serif`;
      context.fillText(`${count(node.token.holders)} holders`, node.x, node.y + 19 / this.viewport.k);
    }
  }
}
