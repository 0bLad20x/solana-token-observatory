import { count, money } from "../format.js";
import { normalizedLaunchpad } from "../state.js";

const GOLDEN_ANGLE = Math.PI * (3 - Math.sqrt(5));
const MIN_ZOOM = 0.16;
const MAX_ZOOM = 5;
const NODE_RADIUS_MIN = 4;
const NODE_RADIUS_MAX = 54;
const HUB_RADIUS = 28;
const NODE_GAP = 3;
const NODE_GAP_RADIUS_FACTOR = 0.06;
const CLUSTER_MIN_RADIUS = 88;
const CLUSTER_PADDING = 30;
const CLUSTER_PACKING_DENSITY = 0.64;
const CLUSTER_GAP = 72;
const ADD_MS = 720;
const UPDATE_MS = 1250;
const RETIRE_HOLD_MS = 700;
const RETIRE_MS = 2400;
const AGE_TICK_MS = 60_000;
const COLLISION_CELL = NODE_RADIUS_MAX * 2 + NODE_GAP * 2 + 8;
const MARKET_LOW_QUANTILE = 0.05;
const MARKET_HIGH_QUANTILE = 0.995;
const LIQUIDITY_HIGH_QUANTILE = 0.98;
const MARKET_CHANGE_VISIBLE = 0.03;
const MARKET_CHANGE_STRONG = 0.10;
const DAY_SECONDS = 24 * 60 * 60;
const CORE_AGE_DAYS = 30;
const AGE_SCALE_DAYS = 0.25;
const CORE_AGE_SECONDS = CORE_AGE_DAYS * DAY_SECONDS;
const AGE_SCALE_SECONDS = AGE_SCALE_DAYS * DAY_SECONDS;
const AGE_SPRING = 0.008;
const COLLISION_SPRING = 0.32;
const BOUNDARY_SPRING = 0.22;
const VELOCITY_DAMPING = 0.82;
const HUB_RADIUS_RESPONSE = 0.08;
const MAX_ACCELERATION = 2.4;
const MAX_SPEED = 4;
const PHYSICS_STABLE_SPEED = 0.025;
const PHYSICS_STABLE_ACCELERATION = 0.012;
const PHYSICS_STABLE_FRAMES = 18;
const FRAME_MS = 1000 / 60;
const MAX_FRAME_STEP = 2;

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

function unitHash(value) {
  return hashString(value) / 0xffffffff;
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
  return { low, high: high > low ? high : low + 1 };
}

function normalizedLog(value, range) {
  const positive = finitePositive(value);
  if (positive == null || !range) return null;
  const logged = Math.log10(positive + 1);
  return Math.max(0, Math.min(1, (logged - range.low) / (range.high - range.low)));
}

function radiusFromMarket(value, range) {
  const score = normalizedLog(value, range);
  if (score == null) return null;
  return NODE_RADIUS_MIN + (NODE_RADIUS_MAX - NODE_RADIUS_MIN) * (score ** 1.45);
}

function freshnessFromAge(ageSeconds) {
  if (!Number.isFinite(ageSeconds) || ageSeconds < 0) return null;
  if (ageSeconds >= CORE_AGE_SECONDS) return 0;
  const normalized = Math.log1p(ageSeconds / AGE_SCALE_SECONDS)
    / Math.log1p(CORE_AGE_SECONDS / AGE_SCALE_SECONDS);
  return Math.max(0, Math.min(1, 1 - normalized));
}

function currentAgeSeconds(node, timestamp) {
  if (!Number.isFinite(node.ageBaseSeconds) || node.ageBaseSeconds < 0) return null;
  const elapsed = Math.max(0, timestamp - node.ageBaseAt) / 1000;
  return node.ageBaseSeconds + elapsed;
}

function preferredRadialDistance(node, hub, timestamp) {
  const freshness = freshnessFromAge(currentAgeSeconds(node, timestamp));
  if (freshness == null) return null;
  const inner = HUB_RADIUS + node.radius + 12;
  const outer = Math.max(inner + 1, hub.radius - node.radius - 9);
  return inner + freshness * (outer - inner);
}

function massFromRadius(radius) {
  const normalized = Math.max(0, Math.min(1, radius / NODE_RADIUS_MAX));
  return 1 + 2.8 * (normalized ** 1.35);
}

function collisionGap(left, right) {
  return NODE_GAP + NODE_GAP_RADIUS_FACTOR * Math.min(left.radius, right.radius);
}

function initialPositionForNode(node, hub, timestamp) {
  const radius = node.targetRadius;
  const inner = HUB_RADIUS + radius + 12;
  const outer = Math.max(inner + 1, hub.radius - radius - 9);
  const span = Math.max(1, outer - inner);
  const preferred = preferredRadialDistance({ ...node, radius }, hub, timestamp);
  const fallback = inner + Math.sqrt(unitHash(`${node.mint}:radial`)) * span;
  const outwardSeed = unitHash(`${node.mint}:radial-seed`) * Math.min(56, span * 0.20);
  const radial = Math.max(inner, Math.min(outer, (preferred ?? fallback) + outwardSeed));
  const angle = unitHash(`${node.mint}:angle`) * Math.PI * 2;
  return {
    x: hub.x + Math.cos(angle) * radial,
    y: hub.y + Math.sin(angle) * radial,
  };
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

function marketChange(previous, next) {
  const before = finitePositive(previous);
  const after = finitePositive(next);
  if (before == null || after == null) return null;
  return (after - before) / before;
}

function easeOutCubic(value) {
  const t = Math.max(0, Math.min(1, value));
  return 1 - (1 - t) ** 3;
}

function easeInOutCubic(value) {
  const t = Math.max(0, Math.min(1, value));
  return t < 0.5 ? 4 * t ** 3 : 1 - ((-2 * t + 2) ** 3) / 2;
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
  const packed = Math.sqrt(occupied / (Math.PI * CLUSTER_PACKING_DENSITY));
  return Math.max(CLUSTER_MIN_RADIUS, packed + CLUSTER_PADDING);
}

function circlesOverlap(left, right, gap = CLUSTER_GAP) {
  return Math.hypot(left.x - right.x, left.y - right.y) < left.radius + right.radius + gap;
}

function placeCluster(spec, existing) {
  if (!existing.length) return { ...spec, x: 0, y: 0, targetRadius: spec.radius };
  const phase = (hashString(spec.launchpad) % 360) * Math.PI / 180;
  for (let attempt = 1; attempt < 6000; attempt += 1) {
    const angle = phase + attempt * GOLDEN_ANGLE;
    const distance = 24 * Math.sqrt(attempt) + spec.radius;
    const candidate = {
      ...spec,
      x: Math.cos(angle) * distance,
      y: Math.sin(angle) * distance,
      targetRadius: spec.radius,
    };
    if (existing.every(item => !circlesOverlap(candidate, item))) return candidate;
  }
  return {
    ...spec,
    x: (existing.length + 1) * (spec.radius + CLUSTER_GAP),
    y: 0,
    targetRadius: spec.radius,
  };
}

function packClusters(specs) {
  const ordered = [...specs].sort((left, right) =>
    right.radius - left.radius || left.launchpad.localeCompare(right.launchpad)
  );
  const placed = [];
  for (const spec of ordered) placed.push(placeCluster(spec, placed));
  return placed;
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

    this.knownLaunchpads = [];
    this.enabledLaunchpads = new Set();
    this.userDisabledLaunchpads = new Set();

    this.tokens = [];
    this.selectedMint = null;
    this.lastSelectedMint = null;
    this.selectionOrigin = null;
    this.hoverMint = null;

    this.viewport = { x: 0, y: 0, k: 1 };
    this.fitted = false;
    this.drag = null;

    this.exitGhosts = [];
    this.pendingSettleAt = new Map();
    this.activeLaunchpads = new Set();
    this.stableFrames = new Map();
    this.lastPhysicsAt = 0;
    this.ageTimer = null;

    this.frame = null;
    this.worldBounds = null;

    this.marketRange = null;
    this.liquidityRange = null;
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
      "<span><strong>Gravity</strong> age · fresh outside</span>",
      "<span><strong>Liquidity</strong> on focus</span>",
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
      "<span>Age = soft radial gravity · 30d+ core attraction</span>",
      "<span>Liquidity = focus halo</span>",
      "<span>MC change = directed transition</span>",
      "<span>Retirement = red exit</span>",
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

    this.ageTimer = window.setInterval(() => {
      for (const launchpad of this.knownLaunchpads) this.#activateCluster(launchpad);
    }, AGE_TICK_MS);
  }

  render({ tokens, selectedMint, events = [] }) {
    const previousNodes = this.nodes;
    const active = tokens.filter(token => token.tracking_enabled);
    const launchpads = [...new Set(active.map(normalizedLaunchpad))].sort((a, b) =>
      a.localeCompare(b)
    );

    this.knownLaunchpads = launchpads;
    this.enabledLaunchpads = new Set(
      launchpads.filter(launchpad => !this.userDisabledLaunchpads.has(launchpad)),
    );
    this.tokens = active;
    this.selectedMint = selectedMint;

    if (!this.marketRange && active.length) {
      this.marketRange = robustLogRange(
        active,
        "market_cap",
        MARKET_LOW_QUANTILE,
        MARKET_HIGH_QUANTILE,
      );
      this.liquidityRange = robustLogRange(active, "liquidity", 0.05, LIQUIDITY_HIGH_QUANTILE);
    }

    const now = performance.now();
    const retiringLaunchpads = new Set();
    for (const event of events) {
      if (event?.type !== "token_retired" || !event?.token?.mint) continue;
      const previous = previousNodes.get(event.token.mint);
      if (!previous) continue;
      this.exitGhosts.push({
        ...previous,
        retiredAt: now,
        retireUntil: now + RETIRE_MS,
      });
      retiringLaunchpads.add(previous.launchpad);
      const settleAt = now + RETIRE_MS;
      this.pendingSettleAt.set(
        previous.launchpad,
        Math.max(this.pendingSettleAt.get(previous.launchpad) || 0, settleAt),
      );
    }

    this.#syncLaunchpadControls();
    this.#buildLayout(events, previousNodes, retiringLaunchpads);

    const selectionChanged = selectedMint && selectedMint !== this.lastSelectedMint;
    if (selectionChanged && this.selectionOrigin !== "view") this.#focusSelected();
    this.lastSelectedMint = selectedMint;
    this.selectionOrigin = null;

    if (!this.fitted) this.fitAll();
    else this.#draw();
  }

  destroy() {
    if (this.frame) cancelAnimationFrame(this.frame);
    if (this.ageTimer) window.clearInterval(this.ageTimer);
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

    const allEnabled = this.knownLaunchpads.every(
      launchpad => !this.userDisabledLaunchpads.has(launchpad),
    );
    const all = document.createElement("button");
    all.type = "button";
    all.textContent = "All";
    all.className = allEnabled ? "active" : "";
    all.setAttribute("aria-pressed", String(allEnabled));
    all.addEventListener("click", () => {
      if (allEnabled) {
        for (const launchpad of this.knownLaunchpads) this.userDisabledLaunchpads.add(launchpad);
      } else {
        for (const launchpad of this.knownLaunchpads) this.userDisabledLaunchpads.delete(launchpad);
      }
      this.#applyLaunchpadVisibility();
    });
    this.launchpadControls.append(all);

    for (const launchpad of this.knownLaunchpads) {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = launchpad;
      const active = !this.userDisabledLaunchpads.has(launchpad);
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", String(active));
      button.addEventListener("click", () => {
        if (this.userDisabledLaunchpads.has(launchpad)) {
          this.userDisabledLaunchpads.delete(launchpad);
        } else {
          this.userDisabledLaunchpads.add(launchpad);
        }
        this.#applyLaunchpadVisibility();
      });
      this.launchpadControls.append(button);
    }
  }

  #applyLaunchpadVisibility() {
    this.enabledLaunchpads = new Set(
      this.knownLaunchpads.filter(launchpad => !this.userDisabledLaunchpads.has(launchpad)),
    );
    this.hoverMint = null;
    this.#syncLaunchpadControls();
    this.#updateWorldBounds();
    this.fitAll();
  }

  #ensureHubLayout(clusterSpecs, deferredLaunchpads) {
    if (!this.hubs.size) {
      const packed = packClusters(clusterSpecs);
      this.hubs = new Map(packed.map(cluster => [cluster.launchpad, cluster]));
      return;
    }

    const specByLaunchpad = new Map(clusterSpecs.map(spec => [spec.launchpad, spec]));
    for (const launchpad of [...this.hubs.keys()]) {
      if (!specByLaunchpad.has(launchpad)) {
        this.hubs.delete(launchpad);
        this.activeLaunchpads.delete(launchpad);
        this.stableFrames.delete(launchpad);
      }
    }

    const existing = [...this.hubs.values()];
    for (const spec of clusterSpecs) {
      const hub = this.hubs.get(spec.launchpad);
      if (hub) {
        const changed = Math.abs((hub.targetRadius ?? hub.radius) - spec.radius) > 0.5;
        hub.targetRadius = spec.radius;
        hub.count = spec.count;
        if (changed && !deferredLaunchpads.has(spec.launchpad)) this.#activateCluster(spec.launchpad);
        continue;
      }
      const placed = placeCluster(spec, existing);
      this.hubs.set(spec.launchpad, placed);
      existing.push(placed);
      this.#activateCluster(spec.launchpad);
    }
  }

  #buildLayout(events, previousNodes, retiringLaunchpads = new Set()) {
    const groups = new Map();
    for (const launchpad of this.knownLaunchpads) groups.set(launchpad, []);
    for (const token of this.tokens) groups.get(normalizedLaunchpad(token))?.push(token);

    const holderScale = buildHolderScale(this.tokens);
    const eventByMint = new Map(
      events.filter(event => event?.token?.mint).map(event => [event.token.mint, event]),
    );
    const now = performance.now();

    const preparedByLaunchpad = new Map();
    for (const [launchpad, group] of groups) {
      const prepared = group.map(token => {
        const radius = radiusFromMarket(token.market_cap, this.marketRange);
        return {
          mint: token.mint,
          token,
          launchpad,
          targetRadius: radius ?? NODE_RADIUS_MIN,
          missingMarketCap: radius == null,
          liquidityScore: normalizedLog(token.liquidity, this.liquidityRange),
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
    this.#ensureHubLayout(clusterSpecs, retiringLaunchpads);

    const nextNodes = new Map();
    for (const [launchpad, prepared] of preparedByLaunchpad) {
      const hub = this.hubs.get(launchpad);
      if (!hub) continue;

      for (const item of prepared) {
        const previous = previousNodes.get(item.mint);
        const event = eventByMint.get(item.mint);
        const isAdded = event?.type === "token_added" || !previous;
        const rawMarketChange = previous
          ? marketChange(previous.token?.market_cap, item.token.market_cap)
          : null;
        const visibleMarketChange = event?.type === "token_updated"
          && rawMarketChange != null
          && Math.abs(rawMarketChange) >= MARKET_CHANGE_VISIBLE;
        const strongMarketChange = visibleMarketChange
          && Math.abs(rawMarketChange) >= MARKET_CHANGE_STRONG;
        const observedAge = Number.isFinite(item.token.age_seconds) && item.token.age_seconds >= 0
          ? item.token.age_seconds
          : null;
        const ageSourceChanged = !previous
          || previous.token?.age_seconds !== item.token.age_seconds;
        const ageBaseSeconds = ageSourceChanged ? observedAge : previous.ageBaseSeconds;
        const ageBaseAt = ageSourceChanged ? now : previous.ageBaseAt;

        const fromRadius = isAdded
          ? Math.max(1, item.targetRadius * 0.3)
          : previous?.radius ?? item.targetRadius;
        const transitionMs = isAdded ? ADD_MS : UPDATE_MS;
        const transitionType = isAdded
          ? "token_added"
          : visibleMarketChange
            ? "market_cap_updated"
            : null;

        const node = {
          ...item,
          x: previous?.x ?? hub.x,
          y: previous?.y ?? hub.y,
          vx: previous?.vx || 0,
          vy: previous?.vy || 0,
          radius: transitionType ? fromRadius : item.targetRadius,
          fromRadius,
          ageBaseSeconds,
          ageBaseAt,
          transitionStart: transitionType ? now : 0,
          transitionUntil: transitionType ? now + transitionMs : 0,
          transitionMs,
          transitionType,
          marketChange: visibleMarketChange ? rawMarketChange : null,
          marketChangeStrong: Boolean(strongMarketChange),
        };

        if (!previous) {
          const initial = initialPositionForNode(node, hub, now);
          node.x = initial.x;
          node.y = initial.y;
        }

        nextNodes.set(item.mint, node);

        const physicalRadiusChanged = previous
          && Math.abs((previous.targetRadius ?? previous.radius) - item.targetRadius) > 0.05;
        if (isAdded || physicalRadiusChanged) this.#activateCluster(launchpad);
      }
    }

    this.nodes = nextNodes;
    if (!previousNodes.size) {
      for (const launchpad of this.knownLaunchpads) this.#activateCluster(launchpad);
    }

    this.#updateWorldBounds();
    const visibleCount = [...this.nodes.values()].filter(
      node => this.enabledLaunchpads.has(node.launchpad),
    ).length;
    this.status.textContent =
      `${visibleCount.toLocaleString()} visible · ${this.enabledLaunchpads.size}/${this.knownLaunchpads.length} launchpads`;
    this.#scheduleFrame();
  }

  #activateCluster(launchpad) {
    if (!launchpad || !this.hubs.has(launchpad)) return;
    this.activeLaunchpads.add(launchpad);
    this.stableFrames.set(launchpad, 0);
    this.#scheduleFrame();
  }

  #activatePendingSettles(timestamp) {
    for (const [launchpad, at] of [...this.pendingSettleAt]) {
      if (at > timestamp) continue;
      this.pendingSettleAt.delete(launchpad);
      this.#activateCluster(launchpad);
    }
  }

  #updateWorldBounds() {
    const visible = [...this.hubs.values()].filter(hub =>
      this.enabledLaunchpads.has(hub.launchpad)
    );
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
      const nextK = Math.max(
        MIN_ZOOM,
        Math.min(MAX_ZOOM, oldK * Math.exp(-event.deltaY * 0.0014)),
      );
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
    const visible = [...this.nodes.values()].filter(node =>
      this.enabledLaunchpads.has(node.launchpad)
    );
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
    this.#activatePendingSettles(timestamp);
    if (!this.activeLaunchpads.size) {
      this.lastPhysicsAt = timestamp;
      return false;
    }

    const previousTimestamp = this.lastPhysicsAt || timestamp - FRAME_MS;
    const step = Math.max(0.25, Math.min(MAX_FRAME_STEP, (timestamp - previousTimestamp) / FRAME_MS));
    this.lastPhysicsAt = timestamp;
    const damping = VELOCITY_DAMPING ** step;
    let boundsChanged = false;

    for (const launchpad of [...this.activeLaunchpads]) {
      const hub = this.hubs.get(launchpad);
      if (!hub) {
        this.activeLaunchpads.delete(launchpad);
        this.stableFrames.delete(launchpad);
        continue;
      }

      const nodes = [...this.nodes.values()].filter(node => node.launchpad === launchpad);
      if (!nodes.length) {
        this.activeLaunchpads.delete(launchpad);
        this.stableFrames.delete(launchpad);
        continue;
      }

      const targetHubRadius = hub.targetRadius ?? hub.radius;
      const hubDelta = targetHubRadius - hub.radius;
      if (Math.abs(hubDelta) > 0.02) {
        hub.radius += hubDelta * Math.min(1, HUB_RADIUS_RESPONSE * step);
        boundsChanged = true;
      }

      for (const node of nodes) {
        node.fx = 0;
        node.fy = 0;

        let dx = node.x - hub.x;
        let dy = node.y - hub.y;
        let distance = Math.hypot(dx, dy);
        if (distance < 0.001) {
          const angle = unitHash(`${node.mint}:center`) * Math.PI * 2;
          dx = Math.cos(angle);
          dy = Math.sin(angle);
          distance = 1;
        }
        const nx = dx / distance;
        const ny = dy / distance;

        const preferred = preferredRadialDistance(node, hub, timestamp);
        if (preferred != null) {
          const force = (preferred - distance) * AGE_SPRING;
          node.fx += nx * force;
          node.fy += ny * force;
        }

        const inner = HUB_RADIUS + node.radius + 12;
        const outer = Math.max(inner + 1, hub.radius - node.radius - 9);
        if (distance < inner) {
          const force = (inner - distance) * BOUNDARY_SPRING;
          node.fx += nx * force;
          node.fy += ny * force;
        } else if (distance > outer) {
          const force = (distance - outer) * BOUNDARY_SPRING;
          node.fx -= nx * force;
          node.fy -= ny * force;
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
              const minimum = node.radius + other.radius + collisionGap(node, other);
              if (distance >= minimum) continue;
              if (distance < 0.001) {
                const angle = unitHash(`${node.mint}:${other.mint}`) * Math.PI * 2;
                dx = Math.cos(angle);
                dy = Math.sin(angle);
                distance = 1;
              }
              const overlap = minimum - distance;
              const force = Math.min(8, overlap * COLLISION_SPRING);
              const nx = dx / distance;
              const ny = dy / distance;
              node.fx += nx * force;
              node.fy += ny * force;
              other.fx -= nx * force;
              other.fy -= ny * force;
            }
          }
        }
        const key = `${gx}:${gy}`;
        if (!grid.has(key)) grid.set(key, []);
        grid.get(key).push(node);
      }

      let maxSpeed = 0;
      let maxAcceleration = 0;
      const transitionActive = nodes.some(node => node.transitionUntil > timestamp);
      for (const node of nodes) {
        const mass = massFromRadius(node.radius);
        let ax = node.fx / mass;
        let ay = node.fy / mass;
        const acceleration = Math.hypot(ax, ay);
        if (acceleration > MAX_ACCELERATION) {
          const scale = MAX_ACCELERATION / acceleration;
          ax *= scale;
          ay *= scale;
        }

        node.vx = (node.vx + ax * step) * damping;
        node.vy = (node.vy + ay * step) * damping;
        const speed = Math.hypot(node.vx, node.vy);
        if (speed > MAX_SPEED) {
          const scale = MAX_SPEED / speed;
          node.vx *= scale;
          node.vy *= scale;
        }
        node.x += node.vx * step;
        node.y += node.vy * step;

        maxSpeed = Math.max(maxSpeed, Math.hypot(node.vx, node.vy));
        maxAcceleration = Math.max(maxAcceleration, Math.min(acceleration, MAX_ACCELERATION));
        node.fx = 0;
        node.fy = 0;
      }

      const stable = !transitionActive
        && Math.abs(targetHubRadius - hub.radius) < 0.05
        && maxSpeed < PHYSICS_STABLE_SPEED
        && maxAcceleration < PHYSICS_STABLE_ACCELERATION;
      const stableCount = stable ? (this.stableFrames.get(launchpad) || 0) + 1 : 0;
      this.stableFrames.set(launchpad, stableCount);
      if (stableCount >= PHYSICS_STABLE_FRAMES) {
        this.activeLaunchpads.delete(launchpad);
        this.stableFrames.delete(launchpad);
      }
    }

    if (boundsChanged) this.#updateWorldBounds();
    return this.activeLaunchpads.size > 0;
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

    const visibleNodes = [...this.nodes.values()].filter(node =>
      this.enabledLaunchpads.has(node.launchpad)
    );
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
        ? easeInOutCubic((timestamp - node.transitionStart) / node.transitionMs)
        : 1;
      if (hasTransition) animating = true;
      const radius = hasTransition
        ? node.fromRadius + (node.targetRadius - node.fromRadius) * progress
        : node.targetRadius;
      node.radius = radius;

      const selected = node.mint === this.selectedMint;
      const hovered = node.mint === this.hoverMint;
      const appearance = node.transitionType === "token_added" && hasTransition ? progress : 1;

      if ((selected || hovered) && node.liquidityScore != null) {
        const haloRadius = radius + 2.5 + node.liquidityScore * 5.5;
        context.beginPath();
        context.arc(node.x, node.y, haloRadius, 0, Math.PI * 2);
        context.strokeStyle =
          `rgba(20,241,217,${(0.12 + node.liquidityScore * 0.52) * appearance})`;
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

      if (node.missingMarketCap) {
        context.setLineDash([3 / this.viewport.k, 3 / this.viewport.k]);
      }
      context.strokeStyle = selected
        ? "#14f1d9"
        : hovered
          ? "rgba(183,124,255,.92)"
          : "rgba(73,217,255,.36)";
      context.lineWidth = (selected ? 2.5 : hovered ? 2 : 1.05) / this.viewport.k;
      context.stroke();
      context.setLineDash([]);
      context.globalAlpha = 1;

      if (node.transitionType === "market_cap_updated" && hasTransition) {
        this.#drawMarketChangeSignal(context, node, radius, progress);
      }

      this.#drawNodeLabel(context, node, radius, selected || hovered);
    }

    this.exitGhosts = this.exitGhosts.filter(ghost => ghost.retireUntil > timestamp);
    for (const ghost of this.exitGhosts) {
      if (!this.enabledLaunchpads.has(ghost.launchpad)) continue;
      animating = true;
      this.#drawRetirement(context, ghost, timestamp);
    }

    context.restore();
    return animating || this.pendingSettleAt.size > 0;
  }

  #drawMarketChangeSignal(context, node, radius, progress) {
    const direction = Math.sign(node.marketChange || 0);
    if (!direction) return;

    const strong = node.marketChangeStrong;
    const baseAlpha = strong ? 0.72 : 0.38;
    const fade = Math.sin(Math.PI * progress);
    const color = direction > 0 ? "61,220,151" : "255,92,119";
    const offset = direction > 0
      ? 4 + progress * (strong ? 18 : 10)
      : 4 + (1 - progress) * (strong ? 14 : 8);

    context.beginPath();
    context.arc(node.x, node.y, Math.max(2, radius + offset), 0, Math.PI * 2);
    context.strokeStyle = `rgba(${color},${baseAlpha * fade})`;
    context.lineWidth = (strong ? 2.4 : 1.4) / this.viewport.k;
    context.stroke();

    if (strong && this.viewport.k >= 0.72) {
      const pct = Math.abs(node.marketChange * 100);
      const label = `${direction > 0 ? "▲" : "▼"} ${pct >= 100 ? pct.toFixed(0) : pct.toFixed(1)}% MC`;
      context.fillStyle = `rgba(${color},${0.88 * fade})`;
      context.font = `700 ${Math.max(8, 10 / this.viewport.k)}px Inter, system-ui, sans-serif`;
      context.textAlign = "center";
      context.textBaseline = "bottom";
      context.fillText(label, node.x, node.y - radius - 9 / this.viewport.k);
    }
  }

  #drawRetirement(context, ghost, timestamp) {
    const elapsed = Math.max(0, timestamp - ghost.retiredAt);
    const holdProgress = Math.min(1, elapsed / RETIRE_HOLD_MS);
    const collapseProgress = elapsed <= RETIRE_HOLD_MS
      ? 0
      : Math.min(1, (elapsed - RETIRE_HOLD_MS) / (RETIRE_MS - RETIRE_HOLD_MS));
    const eased = easeInOutCubic(collapseProgress);
    const radius = Math.max(1, ghost.radius * (1 - eased * 0.92));
    const alpha = collapseProgress === 0 ? 1 : 1 - collapseProgress;
    const pulse = 0.5 + 0.5 * Math.sin(holdProgress * Math.PI);

    const hub = this.hubs.get(ghost.launchpad);
    if (hub) {
      context.beginPath();
      context.moveTo(hub.x, hub.y);
      context.lineTo(ghost.x, ghost.y);
      context.strokeStyle = `rgba(255,92,119,${0.34 * alpha})`;
      context.lineWidth = 1.3 / this.viewport.k;
      context.stroke();
    }

    context.beginPath();
    context.arc(
      ghost.x,
      ghost.y,
      radius + 5 + (collapseProgress === 0 ? pulse * 5 : collapseProgress * 8),
      0,
      Math.PI * 2,
    );
    context.strokeStyle = `rgba(255,92,119,${(collapseProgress === 0 ? 0.96 : 0.8) * alpha})`;
    context.lineWidth = 2.4 / this.viewport.k;
    context.stroke();

    context.beginPath();
    context.arc(ghost.x, ghost.y, radius, 0, Math.PI * 2);
    context.fillStyle = `rgba(255,92,119,${0.17 * alpha})`;
    context.fill();
    context.strokeStyle = `rgba(255,140,160,${0.95 * alpha})`;
    context.lineWidth = 1.8 / this.viewport.k;
    context.stroke();

    if (this.viewport.k >= 0.62 && collapseProgress < 0.82) {
      context.fillStyle = `rgba(255,200,210,${0.95 * alpha})`;
      context.font = `800 ${Math.max(8, 9.5 / this.viewport.k)}px Inter, system-ui, sans-serif`;
      context.textAlign = "center";
      context.textBaseline = "bottom";
      context.fillText("RETIRING", ghost.x, ghost.y - radius - 8 / this.viewport.k);
    }

    if (collapseProgress < 0.55 && ghost.token) {
      context.fillStyle = `rgba(255,220,226,${0.9 * alpha})`;
      context.font = `700 ${Math.max(8, 10 / this.viewport.k)}px Inter, system-ui, sans-serif`;
      context.textAlign = "center";
      context.textBaseline = "middle";
      context.fillText(shortLabel(ghost.token).slice(0, 10), ghost.x, ghost.y);
    }
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
    const showMarketCap = force || screenRadius >= 24;
    const nameFontScreen = Math.max(
      8,
      Math.min(13, Math.max(screenRadius, 14) * 0.44),
    );
    const marketFontScreen = Math.max(7, Math.min(11, nameFontScreen * 0.82));
    const lineGapScreen = 2.5;
    const nameOffsetScreen = showMarketCap
      ? (marketFontScreen + lineGapScreen) / 2
      : 0;

    context.fillStyle = "#f3f5f8";
    context.font = `700 ${nameFontScreen / this.viewport.k}px Inter, system-ui, sans-serif`;
    context.textAlign = "center";
    context.textBaseline = "middle";
    context.fillText(
      label.slice(0, 10),
      node.x,
      node.y - nameOffsetScreen / this.viewport.k,
    );

    if (!showMarketCap) return;

    const marketOffsetScreen = (nameFontScreen + lineGapScreen) / 2;
    context.fillStyle = "#929bad";
    context.font = `500 ${marketFontScreen / this.viewport.k}px Inter, system-ui, sans-serif`;
    context.fillText(
      `MC ${money(node.token.market_cap)}`,
      node.x,
      node.y + marketOffsetScreen / this.viewport.k,
    );

    if (force && this.viewport.k >= 1.05) {
      const holderFontScreen = Math.max(7, Math.min(9, marketFontScreen * 0.82));
      const holderOffsetScreen = marketOffsetScreen
        + (marketFontScreen + holderFontScreen) / 2
        + lineGapScreen;
      context.fillStyle = "#626c7e";
      context.font = `500 ${holderFontScreen / this.viewport.k}px Inter, system-ui, sans-serif`;
      context.fillText(
        `${count(node.token.holders)} holders`,
        node.x,
        node.y + holderOffsetScreen / this.viewport.k,
      );
    }
  }
}