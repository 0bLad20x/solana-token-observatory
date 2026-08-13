import { count, money } from "../format.js";
import { normalizedLaunchpad } from "../state.js";

const GOLDEN_ANGLE = Math.PI * (3 - Math.sqrt(5));
const MIN_ZOOM = 0.16;
const MAX_ZOOM = 5;
const NODE_RADIUS_MIN = 4;
const NODE_RADIUS_MAX = 54;
const HUB_RADIUS = 28;
const NODE_GAP = 3;
const CLUSTER_MIN_RADIUS = 88;
const CLUSTER_PADDING = 42;
const CLUSTER_GAP = 72;
const ADD_MS = 720;
const UPDATE_MS = 900;
const RETIRE_MS = 1800;
const SETTLE_MS = 950;
const COLLISION_CELL = NODE_RADIUS_MAX * 2 + NODE_GAP * 2;
const MARKET_LOW_QUANTILE = 0.05;
const MARKET_HIGH_QUANTILE = 0.995;
const LIQUIDITY_HIGH_QUANTILE = 0.98;

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

function robustLogRange(tokens, field, lowFraction = 0.05, highFraction = 0.98) {
  const values = tokens
    .map(token => finitePositive(token[field]))
    .filter(value => value != null)
    .map(value => Math.log10(value + 1))
    .sort((left, right) => left - right);
  if (!values.length) return null;
  const low = percentile(values, lowFraction);
  const high = percentile(values, highFraction);
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

function buildMarketRadiusScale(tokens) {
  const range = robustLogRange(
    tokens,
    "market_cap",
    MARKET_LOW_QUANTILE,
    MARKET_HIGH_QUANTILE,
  );
  return value => {
    const score = normalizedLog(value, range);
    if (score == null) return null;
    // Radius, not area, carries the robust log-scaled market-cap signal.
    // The >1 exponent keeps the long tail visibly distinct without allowing one outlier
    // to consume the whole stage.
    return NODE_RADIUS_MIN + (NODE_RADIUS_MAX - NODE_RADIUS_MIN) * (score ** 1.45);
  };
}

function buildLiquidityScale(tokens) {
  const range = robustLogRange(tokens, "liquidity", 0.05, LIQUIDITY_HIGH_QUANTILE);
  return value => normalizedLog(value, range);
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

function clusterRadiusForNodes(nodes) {
  if (!nodes.length) return CLUSTER_MIN_RADIUS;
  const occupied = nodes.reduce((sum, node) => {
    const radius = node.targetRadius + NODE_GAP + 2;
    return sum + Math.PI * radius * radius;
  }, Math.PI * (HUB_RADIUS + 18) ** 2);
  const packed = Math.sqrt(occupied / (Math.PI * 0.58));
  return Math.max(CLUSTER_MIN_RADIUS, packed + CLUSTER_PADDING);
}

function circlesOverlap(left, right, gap = CLUSTER_GAP) {
  return Math.hypot(left.x - right.x, left.y - right.y) < left.radius + right.radius + gap;
}

function packClusters(specs) {
  const ordered = [...specs].sort((left, right) =>
    right.radius - left.radius || left.launchpad.localeCompare(right.launchpad)
  );
  const placed = [];
  for (const spec of ordered) {
    if (!placed.length) {
      placed.push({ ...spec, x: 0, y: 0 });
      continue;
    }

    const phase = (hashString(spec.launchpad) % 360) * Math.PI / 180;
    let candidate = null;
    for (let attempt = 1; attempt < 6000; attempt += 1) {
      const angle = phase + attempt * GOLDEN_ANGLE;
      const distance = 24 * Math.sqrt(attempt) + spec.radius;
      const next = {
        ...spec,
        x: Math.cos(angle) * distance,
        y: Math.sin(angle) * distance,
      };
      if (placed.every(existing => !circlesOverlap(next, existing))) {
        candidate = next;
        break;
      }
    }

    placed.push(candidate || {
      ...spec,
      x: (placed.length + 1) * (spec.radius + CLUSTER_GAP),
      y: 0,
    });
  }
  return placed;
}

function anchorForNode(node, hub, slot, total) {
  const usable = Math.max(20, hub.radius - HUB_RADIUS - node.targetRadius - 18);
  const normalized = Math.sqrt((slot + 0.65) / Math.max(1, total + 0.5));
  const phase = (hashString(node.launchpad) % 360) * Math.PI / 180;
  const mintJitter = ((hashString(node.mint) % 1000) / 1000 - 0.5) * 0.38;
  const angle = phase + slot * GOLDEN_ANGLE + mintJitter;
  const radial = Math.min(usable, HUB_RADIUS + 24 + normalized * Math.max(0, usable - HUB_RADIUS - 24));
  return {
    x: hub.x + Math.cos(angle) * radial,
    y: hub.y + Math.sin(angle) * radial,
  };
}

export class TokenUniverseView {
  constructor(stageElement, { onSelect } = {}) {
    this.stageElement = stageElement;
    this.onSelect = onSelect || (() => {});
    this.root = null;
    this.canvas = null;
    this.context = null;
    this.launchpadControls = null;
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
    this.hoverMint = null;
    this.viewport = { x: 0, y: 0, k: 1 };
    this.fitted = false;
    this.drag = null;
    this.exitGhosts = [];
    this.frame = null;
    this.worldBounds = null;
    this.settleUntil = new Map();
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

    const semantics = document.createElement("div");
    semantics.className = "token-universe-semantics";
    semantics.innerHTML = [
      "<span><strong>Size</strong> market cap</span>",
      "<span><strong>Halo</strong> liquidity</span>",
      "<span><strong>Spoke</strong> holders on focus</span>",
    ].join("");

    const reset = document.createElement("button");
    reset.type = "button";
    reset.className = "token-universe-reset";
    reset.textContent = "Fit all";
    reset.addEventListener("click", () => this.fitAll());

    this.status = document.createElement("span");
    this.status.className = "token-universe-status";

    controls.append(launchpadGroup, semantics, reset, this.status);

    this.canvas = document.createElement("canvas");
    this.canvas.className = "token-universe-canvas";
    this.canvas.setAttribute("aria-label", "Launchpad-centered active token universe");
    this.canvas.tabIndex = 0;
    this.context = this.canvas.getContext("2d");

    const legend = document.createElement("div");
    legend.className = "token-universe-legend";
    legend.innerHTML = [
      "<span>Bubble radius = robust log market cap</span>",
      "<span>Liquidity = outer halo</span>",
      "<span>Membership line appears on hover / selection</span>",
      "<span>Scroll = zoom · drag = pan</span>",
    ].join("");

    this.root.append(this.canvas, controls, legend);
    this.stageElement.replaceChildren(this.root);
    this.#bindCanvas();

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
    const previousHubs = this.hubs;
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
      this.#activateCluster(previous.launchpad, RETIRE_MS);
    }

    this.#syncLaunchpadControls();
    this.#buildLayout(events, previousNodes, previousHubs);

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
    const k = Math.max(MIN_ZOOM, Math.min(1.25, width / worldWidth, height / worldHeight));
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
      this.#updateWorldBounds();
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
        this.#updateWorldBounds();
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

  #buildLayout(events, previousNodes, previousHubs) {
    const groups = new Map();
    for (const launchpad of this.knownLaunchpads) groups.set(launchpad, []);
    for (const token of this.tokens) groups.get(normalizedLaunchpad(token))?.push(token);
    this.#ensureSlots(groups);

    const marketRadius = buildMarketRadiusScale(this.tokens);
    const liquidityScale = buildLiquidityScale(this.tokens);
    const holderScale = buildHolderScale(this.tokens);
    const eventByMint = new Map(events.filter(event => event?.token?.mint).map(event => [event.token.mint, event]));
    const now = performance.now();

    const preparedByLaunchpad = new Map();
    for (const [launchpad, group] of groups) {
      const prepared = group.map(token => {
        const radius = marketRadius(token.market_cap);
        return {
          mint: token.mint,
          token,
          launchpad,
          targetRadius: radius ?? NODE_RADIUS_MIN,
          missingMarketCap: radius == null,
          liquidityScore: liquidityScale(token.liquidity),
          holderScore: holderScale(token.holders),
        };
      });
      preparedByLaunchpad.set(launchpad, prepared);
    }

    const clusterSpecs = [...preparedByLaunchpad].map(([launchpad, nodes]) => ({
      launchpad,
      count: nodes.length,
      radius: clusterRadiusForNodes(nodes),
    }));
    const packed = packClusters(clusterSpecs);
    this.hubs = new Map(packed.map(cluster => [cluster.launchpad, cluster]));

    const nextNodes = new Map();
    for (const [launchpad, prepared] of preparedByLaunchpad) {
      const hub = this.hubs.get(launchpad);
      const previousHub = previousHubs.get(launchpad);
      const slots = this.slots.get(launchpad);
      const total = prepared.length;

      for (const item of prepared) {
        const previous = previousNodes.get(item.mint);
        const slot = slots?.get(item.mint) || 0;
        const anchor = anchorForNode(item, hub, slot, total);
        const event = eventByMint.get(item.mint);
        const isAdded = event?.type === "token_added";
        const radiusChanged = previous
          ? Math.abs(item.targetRadius - (previous.targetRadius ?? previous.radius ?? item.targetRadius)) > 1.25
          : true;

        let x = anchor.x;
        let y = anchor.y;
        if (previous && previousHub) {
          x = hub.x + (previous.x - previousHub.x);
          y = hub.y + (previous.y - previousHub.y);
        } else if (isAdded) {
          const phase = (hashString(item.mint) % 360) * Math.PI / 180;
          x = hub.x + Math.cos(phase) * (HUB_RADIUS + 12);
          y = hub.y + Math.sin(phase) * (HUB_RADIUS + 12);
        }

        const transitionMs = isAdded ? ADD_MS : UPDATE_MS;
        nextNodes.set(item.mint, {
          ...item,
          x,
          y,
          vx: previous?.vx || 0,
          vy: previous?.vy || 0,
          anchorX: anchor.x,
          anchorY: anchor.y,
          radius: isAdded ? Math.max(1, item.targetRadius * 0.3) : previous?.radius ?? item.targetRadius,
          fromRadius: isAdded ? Math.max(1, item.targetRadius * 0.3) : previous?.radius ?? item.targetRadius,
          transitionStart: event && (isAdded || radiusChanged) ? now : 0,
          transitionUntil: event && (isAdded || radiusChanged) ? now + transitionMs : 0,
          transitionMs,
          transitionType: isAdded ? "token_added" : radiusChanged && event ? "token_updated" : null,
        });

        if (!previous || isAdded) this.#activateCluster(launchpad, SETTLE_MS + 250);
        else if (radiusChanged && event) this.#activateCluster(launchpad, SETTLE_MS);
      }
    }

    this.nodes = nextNodes;
    if (!previousNodes.size) {
      for (const launchpad of this.knownLaunchpads) this.#activateCluster(launchpad, SETTLE_MS + 500);
    }

    this.#updateWorldBounds();
    const visibleCount = [...this.nodes.values()].filter(node => this.enabledLaunchpads.has(node.launchpad)).length;
    this.status.textContent = `${visibleCount.toLocaleString()} visible · ${this.enabledLaunchpads.size}/${this.knownLaunchpads.length} launchpads`;
    this.#scheduleFrame();
  }

  #activateCluster(launchpad, duration) {
    const until = performance.now() + duration;
    this.settleUntil.set(launchpad, Math.max(this.settleUntil.get(launchpad) || 0, until));
  }

  #updateWorldBounds() {
    const visible = [...this.hubs.values()].filter(hub => this.enabledLaunchpads.has(hub.launchpad));
    if (!visible.length) {
      this.worldBounds = { minX: -100, maxX: 100, minY: -100, maxY: 100 };
      return;
    }
    this.worldBounds = {
      minX: Math.min(...visible.map(hub => hub.x - hub.radius)),
      maxX: Math.max(...visible.map(hub => hub.x + hub.radius)),
      minY: Math.min(...visible.map(hub => hub.y - hub.radius)),
      maxY: Math.max(...visible.map(hub => hub.y + hub.radius)),
    };
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

      const node = this.#hitNode(event.clientX, event.clientY);
      const nextHover = node?.mint || null;
      if (nextHover !== this.hoverMint) {
        this.hoverMint = nextHover;
        this.#draw();
      }
      this.canvas.style.cursor = node ? "pointer" : "grab";
    });

    this.canvas.addEventListener("pointerleave", () => {
      if (this.drag) return;
      if (this.hoverMint) {
        this.hoverMint = null;
        this.#draw();
      }
      this.canvas.style.cursor = "grab";
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
      if (Math.hypot(x - sx, y - sy) <= radius + 4) return node;
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

  #stepPhysics(timestamp) {
    const activeLaunchpads = new Set(
      [...this.settleUntil]
        .filter(([, until]) => until > timestamp)
        .map(([launchpad]) => launchpad),
    );
    if (!activeLaunchpads.size) return false;

    for (const launchpad of activeLaunchpads) {
      const hub = this.hubs.get(launchpad);
      if (!hub) continue;
      const nodes = [...this.nodes.values()].filter(node => node.launchpad === launchpad);
      for (let iteration = 0; iteration < 2; iteration += 1) {
        for (const node of nodes) {
          node.vx = (node.vx + (node.anchorX - node.x) * 0.024) * 0.76;
          node.vy = (node.vy + (node.anchorY - node.y) * 0.024) * 0.76;
          node.x += node.vx;
          node.y += node.vy;

          const hubDx = node.x - hub.x;
          const hubDy = node.y - hub.y;
          const hubDistance = Math.hypot(hubDx, hubDy) || 1;
          const hubMinimum = HUB_RADIUS + node.radius + 12;
          if (hubDistance < hubMinimum) {
            const push = hubMinimum - hubDistance;
            node.x += hubDx / hubDistance * push;
            node.y += hubDy / hubDistance * push;
          }

          const maximum = Math.max(hubMinimum + 1, hub.radius - node.radius - 9);
          if (hubDistance > maximum) {
            const pull = hubDistance - maximum;
            node.x -= hubDx / hubDistance * pull;
            node.y -= hubDy / hubDistance * pull;
          }
        }

        const grid = new Map();
        for (const node of nodes) {
          const gx = Math.floor(node.x / COLLISION_CELL);
          const gy = Math.floor(node.y / COLLISION_CELL);
          for (let ox = -1; ox <= 1; ox += 1) {
            for (let oy = -1; oy <= 1; oy += 1) {
              const neighbors = grid.get(`${gx + ox}:${gy + oy}`);
              if (!neighbors) continue;
              for (const other of neighbors) {
                let dx = node.x - other.x;
                let dy = node.y - other.y;
                let distance = Math.hypot(dx, dy);
                const minimum = node.radius + other.radius + NODE_GAP;
                if (distance >= minimum) continue;
                if (distance < 0.001) {
                  const angle = (hashString(node.mint + other.mint) % 360) * Math.PI / 180;
                  dx = Math.cos(angle);
                  dy = Math.sin(angle);
                  distance = 1;
                }
                const overlap = (minimum - distance) * 0.52;
                const nx = dx / distance;
                const ny = dy / distance;
                node.x += nx * overlap;
                node.y += ny * overlap;
                other.x -= nx * overlap;
                other.y -= ny * overlap;
              }
            }
          }
          const key = `${gx}:${gy}`;
          if (!grid.has(key)) grid.set(key, []);
          grid.get(key).push(node);
        }
      }
    }

    for (const [launchpad, until] of [...this.settleUntil]) {
      if (until <= timestamp) this.settleUntil.delete(launchpad);
    }
    return true;
  }

  #draw(timestamp = performance.now()) {
    if (!this.canvas || !this.context) return false;
    this.#resizeCanvas();
    const physicsActive = this.#stepPhysics(timestamp);
    const context = this.context;
    const dpr = Number(this.canvas.dataset.dpr || 1);
    const width = this.canvas.width / dpr;
    const height = this.canvas.height / dpr;
    context.setTransform(dpr, 0, 0, dpr, 0, 0);
    context.clearRect(0, 0, width, height);

    const visibleNodes = [...this.nodes.values()].filter(node => this.enabledLaunchpads.has(node.launchpad));
    let animating = physicsActive;

    context.save();
    context.translate(this.viewport.x, this.viewport.y);
    context.scale(this.viewport.k, this.viewport.k);

    this.#drawClusterFields(context);
    this.#drawContextSpokes(context);

    for (const hub of this.hubs.values()) {
      if (!this.enabledLaunchpads.has(hub.launchpad)) continue;
      context.beginPath();
      context.arc(hub.x, hub.y, HUB_RADIUS, 0, Math.PI * 2);
      context.fillStyle = "#151b2a";
      context.fill();
      context.strokeStyle = "rgba(153,69,255,.88)";
      context.lineWidth = 2 / this.viewport.k;
      context.stroke();

      context.fillStyle = "#f3f5f8";
      context.font = `700 ${Math.max(11, 14 / this.viewport.k)}px Inter, system-ui, sans-serif`;
      context.textAlign = "center";
      context.textBaseline = "middle";
      context.fillText(hub.launchpad, hub.x, hub.y - 2);
      context.fillStyle = "#929bad";
      context.font = `${Math.max(9, 10 / this.viewport.k)}px Inter, system-ui, sans-serif`;
      context.fillText(String(hub.count), hub.x, hub.y + 15 / this.viewport.k);
    }

    for (const node of visibleNodes) {
      const hasTransition = node.transitionUntil > timestamp;
      const progress = hasTransition
        ? easeOutCubic((timestamp - node.transitionStart) / node.transitionMs)
        : 1;
      if (hasTransition) animating = true;
      const radius = hasTransition
        ? node.fromRadius + (node.targetRadius - node.fromRadius) * progress
        : node.targetRadius;
      node.radius = radius;

      const selected = node.mint === this.selectedMint;
      const hovered = node.mint === this.hoverMint;
      const appearance = node.transitionType === "token_added" && hasTransition ? progress : 1;

      if (node.liquidityScore != null) {
        const haloRadius = radius + 2.5 + node.liquidityScore * 5.5;
        context.beginPath();
        context.arc(node.x, node.y, haloRadius, 0, Math.PI * 2);
        context.strokeStyle = `rgba(20,241,217,${(0.12 + node.liquidityScore * 0.52) * appearance})`;
        context.lineWidth = (0.7 + node.liquidityScore * 2.2) / this.viewport.k;
        context.stroke();
      }

      context.globalAlpha = appearance;
      context.beginPath();
      context.arc(node.x, node.y, radius, 0, Math.PI * 2);
      context.fillStyle = selected
        ? "rgba(20,241,217,.20)"
        : hovered
          ? "rgba(28,38,56,.98)"
          : "rgba(15,20,32,.96)";
      context.fill();

      if (node.missingMarketCap) context.setLineDash([3 / this.viewport.k, 3 / this.viewport.k]);
      context.strokeStyle = selected
        ? "#14f1d9"
        : hovered
          ? "rgba(183,124,255,.92)"
          : "rgba(73,217,255,.36)";
      context.lineWidth = (selected ? 2.5 : hovered ? 2 : 1.05) / this.viewport.k;
      context.stroke();
      context.setLineDash([]);
      context.globalAlpha = 1;

      if (node.transitionType === "token_updated" && hasTransition) {
        const quiet = 1 - progress;
        context.beginPath();
        context.arc(node.x, node.y, radius + 3 + quiet * 4, 0, Math.PI * 2);
        context.strokeStyle = `rgba(183,124,255,${quiet * 0.10})`;
        context.lineWidth = 1 / this.viewport.k;
        context.stroke();
      }

      this.#drawNodeLabel(context, node, radius, selected || hovered);
    }

    this.exitGhosts = this.exitGhosts.filter(ghost => ghost.retireUntil > timestamp);
    for (const ghost of this.exitGhosts) {
      if (!this.enabledLaunchpads.has(ghost.launchpad)) continue;
      animating = true;
      const progress = Math.max(0, Math.min(1, (timestamp - ghost.retiredAt) / RETIRE_MS));
      const eased = easeOutCubic(progress);
      const radius = Math.max(1, ghost.radius * (1 - eased * 0.82));
      const alpha = 1 - progress;

      const hub = this.hubs.get(ghost.launchpad);
      if (hub) {
        context.beginPath();
        context.moveTo(hub.x, hub.y);
        context.lineTo(ghost.x, ghost.y);
        context.strokeStyle = `rgba(255,92,119,${0.30 * alpha})`;
        context.lineWidth = 1.2 / this.viewport.k;
        context.stroke();
      }

      context.beginPath();
      context.arc(ghost.x, ghost.y, radius + 4 * alpha, 0, Math.PI * 2);
      context.fillStyle = `rgba(255,92,119,${0.16 * alpha})`;
      context.fill();
      context.strokeStyle = `rgba(255,92,119,${0.92 * alpha})`;
      context.lineWidth = 2.2 / this.viewport.k;
      context.stroke();

      if (progress < 0.62 && ghost.token) {
        context.fillStyle = `rgba(255,190,201,${0.9 * alpha})`;
        context.font = `700 ${Math.max(8, 10 / this.viewport.k)}px Inter, system-ui, sans-serif`;
        context.textAlign = "center";
        context.textBaseline = "middle";
        context.fillText(shortLabel(ghost.token).slice(0, 10), ghost.x, ghost.y);
      }
    }

    context.restore();
    return animating;
  }

  #drawClusterFields(context) {
    for (const hub of this.hubs.values()) {
      if (!this.enabledLaunchpads.has(hub.launchpad)) continue;
      context.beginPath();
      context.arc(hub.x, hub.y, hub.radius, 0, Math.PI * 2);
      context.fillStyle = "rgba(18,24,38,.18)";
      context.fill();
      context.strokeStyle = "rgba(146,155,173,.055)";
      context.lineWidth = 1 / this.viewport.k;
      context.stroke();
    }
  }

  #drawContextSpokes(context) {
    const mints = new Set([this.selectedMint, this.hoverMint].filter(Boolean));
    for (const mint of mints) {
      const node = this.nodes.get(mint);
      if (!node || !this.enabledLaunchpads.has(node.launchpad)) continue;
      const hub = this.hubs.get(node.launchpad);
      if (!hub) continue;
      const score = node.holderScore;
      context.beginPath();
      context.moveTo(hub.x, hub.y);
      context.lineTo(node.x, node.y);
      if (score == null) {
        context.setLineDash([4 / this.viewport.k, 5 / this.viewport.k]);
        context.strokeStyle = "rgba(146,155,173,.35)";
        context.lineWidth = 1 / this.viewport.k;
      } else {
        context.setLineDash([]);
        context.strokeStyle = `rgba(20,241,217,${0.36 + score * 0.54})`;
        context.lineWidth = (1.1 + score * 3.2) / this.viewport.k;
      }
      context.stroke();
      context.setLineDash([]);
    }
  }

  #drawNodeLabel(context, node, radius, force = false) {
    const screenRadius = radius * this.viewport.k;
    if (!force && screenRadius < 11) return;

    const label = shortLabel(node.token);
    const fontSize = Math.max(8, Math.min(13, Math.max(screenRadius, 14) * 0.52)) / this.viewport.k;
    context.fillStyle = "#f3f5f8";
    context.font = `700 ${fontSize}px Inter, system-ui, sans-serif`;
    context.textAlign = "center";
    context.textBaseline = "middle";
    context.fillText(label.slice(0, 10), node.x, node.y - (screenRadius >= 24 || force ? 5 / this.viewport.k : 0));

    if (!force && screenRadius < 24) return;
    context.fillStyle = "#929bad";
    context.font = `${Math.max(7, 8.7 / this.viewport.k)}px Inter, system-ui, sans-serif`;
    context.fillText(`MC ${money(node.token.market_cap)}`, node.x, node.y + 8 / this.viewport.k);

    if ((force && this.viewport.k >= 1.05) || screenRadius >= 38) {
      context.fillStyle = "#626c7e";
      context.font = `${Math.max(7, 8 / this.viewport.k)}px Inter, system-ui, sans-serif`;
      context.fillText(`${count(node.token.holders)} holders`, node.x, node.y + 19 / this.viewport.k);
    }
  }
}
