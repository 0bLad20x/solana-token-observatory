import { Application, Container, Graphics, Text, TextStyle } from "https://cdn.jsdelivr.net/npm/pixi.js@8.19.0/dist/pixi.min.mjs";
import { forceCollide, forceManyBody, forceSimulation, forceX, forceY } from "https://cdn.jsdelivr.net/npm/d3-force@3.0.0/+esm";

import { normalizedLaunchpad } from "./state.js";
import { COLORS, launchpadAccent } from "./theme.js";

const NODE_GAP = 1.6;
const VIEW_PADDING = 14;
const CLUSTER_GAP = 18;
const PACKING_DENSITY = 0.72;
const TARGET_NODE_AREA_SHARE = 0.48;
const BOOTSTRAP_TICKS = 240;
const LOCAL_SEARCH_ATTEMPTS = 1600;
const GOLDEN_ANGLE = Math.PI * (3 - Math.sqrt(5));

function clamp(value, minimum, maximum) {
  if (minimum > maximum) return (minimum + maximum) / 2;
  return Math.max(minimum, Math.min(maximum, value));
}

function hash(text) {
  let h = 2166136261;
  for (let i = 0; i < text.length; i += 1) {
    h ^= text.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

function baseRadiusForMarketCap(marketCap) {
  const value = Math.max(1, marketCap || 1);
  const log = Math.log10(value);
  return Math.max(4.5, Math.min(28, 4 + (log - 2) * 5.2));
}

function liquidityStroke(liquidity, marketCap) {
  if (!liquidity || !marketCap) return 1;
  const ratio = Math.max(0, Math.min(1, liquidity / marketCap));
  return 1 + ratio * 4;
}

function freshnessAlpha(changeAgeSeconds) {
  if (changeAgeSeconds == null) return 0.58;
  if (changeAgeSeconds < 15) return 1;
  if (changeAgeSeconds < 60) return 0.88;
  if (changeAgeSeconds < 300) return 0.72;
  return 0.5;
}

export class TokenUniverse {
  constructor(stageElement, { onSelect } = {}) {
    this.stageElement = stageElement;
    this.onSelect = onSelect || (() => {});
    this.app = null;
    this.clusterLayer = null;
    this.tokenLayer = null;
    this.labelLayer = null;
    this.nodes = new Map();
    this.clusterViews = new Map();
    this.clusterCenters = new Map();
    this.selectedMint = null;
    this.sceneScale = 1;
    this.resizeTimer = null;
    this.resizeObserver = null;
  }

  async init() {
    this.app = new Application();
    await this.app.init({
      resizeTo: this.stageElement,
      backgroundAlpha: 0,
      antialias: true,
      autoDensity: true,
      resolution: Math.min(window.devicePixelRatio || 1, 2),
      preference: "webgl",
    });
    this.stageElement.appendChild(this.app.canvas);

    this.clusterLayer = new Container();
    this.tokenLayer = new Container();
    this.labelLayer = new Container();
    this.app.stage.addChild(this.clusterLayer, this.tokenLayer, this.labelLayer);
    this.app.ticker.add(() => this._tick());

    this.resizeObserver = new ResizeObserver(() => {
      clearTimeout(this.resizeTimer);
      this.resizeTimer = setTimeout(() => {
        if (!this.nodes.size) return;
        this._layoutScene({ refit: true });
      }, 180);
    });
    this.resizeObserver.observe(this.stageElement);
  }

  load(tokens) {
    for (const token of tokens) this._addToken(token, false);
    this._layoutScene({ refit: true });
  }

  setSelectedMint(mint) {
    const previous = this.selectedMint;
    this.selectedMint = mint;
    if (previous && this.nodes.has(previous)) this._redrawNode(this.nodes.get(previous));
    if (mint && this.nodes.has(mint)) this._redrawNode(this.nodes.get(mint));
  }

  applyEvents(events) {
    for (const event of events) {
      if (event.type === "token_added") {
        const node = this._addToken(event.token, true);
        this._ensureClusterCenter(node.cluster, Math.max(42, node.radius * 4));
        this._placeNodeLocally(node, { preserveCurrent: false });
        continue;
      }

      if (event.type === "token_updated") {
        const result = this._updateToken(event.token, true);
        const node = result.node;
        if (!node) continue;

        if (result.clusterChanged) {
          this._ensureClusterCenter(node.cluster, Math.max(42, node.radius * 4));
          this._placeNodeLocally(node, { preserveCurrent: false });
        } else if (result.geometryChanged) {
          this._placeNodeLocally(node, { preserveCurrent: true });
        }
        continue;
      }

      if (event.type === "token_retired") {
        this._retireToken(event.token, event.reason);
      }
    }

    this._refreshClusterVisuals();
  }

  _activeNodes() {
    return [...this.nodes.values()].filter(node => !node.retiringAt);
  }

  _updateNodeGeometry(node) {
    node.baseRadius = baseRadiusForMarketCap(node.token.market_cap);
    node.radius = node.baseRadius * this.sceneScale;
    node.cluster = normalizedLaunchpad(node.token);
  }

  _createView(node) {
    const view = new Graphics();
    node.view = view;
    view.eventMode = "static";
    view.cursor = "pointer";
    view.on("pointertap", () => this.onSelect(node.token.mint));
    this.tokenLayer.addChild(view);
    this._redrawNode(node);
  }

  _redrawNode(node) {
    const token = node.token;
    const color = launchpadAccent(node.cluster);
    const freshness = freshnessAlpha(token.change_age_seconds);
    const selected = token.mint === this.selectedMint;
    const strokeWidth = liquidityStroke(token.liquidity, token.market_cap) + (selected ? 1.5 : 0);

    node.view.clear()
      .circle(0, 0, node.radius)
      .fill({ color, alpha: 0.18 + freshness * 0.42 })
      .stroke({
        color: selected ? COLORS.selection : COLORS.textPrimary,
        alpha: selected ? 0.92 : 0.14 + freshness * 0.25,
        width: strokeWidth,
      });
  }

  _addToken(token, animate = true) {
    const existing = this.nodes.get(token.mint);
    if (existing) {
      this._updateToken(token, false);
      return existing;
    }

    const cluster = normalizedLaunchpad(token);
    const center = this.clusterCenters.get(cluster);
    const baseRadius = baseRadiusForMarketCap(token.market_cap);
    const node = {
      token,
      cluster,
      baseRadius,
      radius: baseRadius * this.sceneScale,
      x: center?.x ?? this.app.screen.width / 2,
      y: center?.y ?? this.app.screen.height / 2,
      vx: 0,
      vy: 0,
      pulseUntil: 0,
      bornAt: animate ? performance.now() : 0,
      retiringAt: 0,
    };

    this.nodes.set(token.mint, node);
    this._createView(node);
    node.view.scale.set(animate ? 0.02 : 1);
    return node;
  }

  _updateToken(token, pulse = true) {
    const node = this.nodes.get(token.mint);
    if (!node) {
      const added = this._addToken(token, true);
      return {
        node: added,
        clusterChanged: true,
        geometryChanged: true,
      };
    }

    const previousCluster = node.cluster;
    const previousRadius = node.radius;
    node.token = token;
    this._updateNodeGeometry(node);
    this._redrawNode(node);
    if (pulse) node.pulseUntil = performance.now() + 900;

    return {
      node,
      clusterChanged: previousCluster !== node.cluster,
      geometryChanged: Math.abs(previousRadius - node.radius) > 0.15,
    };
  }

  _retireToken(token, reason) {
    const node = this.nodes.get(token.mint);
    if (!node || node.retiringAt) return false;

    node.token = {
      ...node.token,
      ...token,
      tracking_enabled: false,
      disabled_reason: reason || token.disabled_reason,
    };
    node.retiringAt = performance.now();
    return true;
  }

  _computeSceneScale(items) {
    if (!items.length) return 1;

    const width = Math.max(1, this.app.screen.width - VIEW_PADDING * 2);
    const height = Math.max(1, this.app.screen.height - VIEW_PADDING * 2);
    const usableArea = width * height;

    let rawArea = 0;
    const clusterSquares = new Map();
    for (const node of items) {
      const radius = node.baseRadius + NODE_GAP;
      rawArea += Math.PI * radius * radius;
      clusterSquares.set(node.cluster, (clusterSquares.get(node.cluster) || 0) + radius * radius);
    }

    const areaScale = rawArea > 0
      ? Math.sqrt((usableArea * TARGET_NODE_AREA_SHARE) / rawArea)
      : 1;
    const largestClusterSquares = Math.max(0, ...clusterSquares.values());
    const largestClusterCore = largestClusterSquares > 0
      ? Math.sqrt(largestClusterSquares / PACKING_DENSITY)
      : 1;
    const maxClusterCore = Math.min(width, height) * 0.42;
    const clusterScale = largestClusterCore > 0 ? maxClusterCore / largestClusterCore : 1;

    return Math.min(1, areaScale, clusterScale);
  }

  _clusterMetrics(items) {
    const metrics = new Map();
    for (const node of items) {
      let metric = metrics.get(node.cluster);
      if (!metric) {
        metric = {
          name: node.cluster,
          total: 0,
          sumSquares: 0,
          color: launchpadAccent(node.cluster),
        };
        metrics.set(node.cluster, metric);
      }
      metric.total += 1;
      metric.sumSquares += Math.pow(node.radius + NODE_GAP, 2);
    }

    for (const metric of metrics.values()) {
      metric.radius = Math.sqrt(metric.sumSquares / PACKING_DENSITY) + 14;
    }
    return metrics;
  }

  _computeClusterCenters(metrics) {
    const width = this.app.screen.width;
    const height = this.app.screen.height;
    const entries = [...metrics.values()].sort((a, b) => b.radius - a.radius);
    if (!entries.length) return new Map();

    const orbitBase = Math.min(width, height) * 0.24;
    const layoutNodes = entries.map((metric, index) => {
      if (index === 0) {
        return { ...metric, x: width / 2, y: height / 2, vx: 0, vy: 0 };
      }
      const angle = (index - 1) * GOLDEN_ANGLE;
      const orbit = orbitBase + Math.floor((index - 1) / 6) * Math.min(width, height) * 0.14;
      return {
        ...metric,
        x: width / 2 + Math.cos(angle) * orbit,
        y: height / 2 + Math.sin(angle) * orbit,
        vx: 0,
        vy: 0,
      };
    });

    const metaSimulation = forceSimulation(layoutNodes)
      .stop()
      .velocityDecay(0.44)
      .alphaDecay(0.045)
      .force("x", forceX(width / 2).strength(0.035))
      .force("y", forceY(height / 2).strength(0.035))
      .force("charge", forceManyBody().strength(node => -Math.max(30, node.radius * 2.5)))
      .force("collide", forceCollide(node => node.radius + CLUSTER_GAP).strength(1).iterations(3));

    for (let i = 0; i < 180; i += 1) {
      metaSimulation.tick();
      for (const node of layoutNodes) {
        const horizontalPadding = node.radius + VIEW_PADDING;
        const verticalPadding = node.radius + VIEW_PADDING + 10;
        node.x = clamp(node.x, horizontalPadding, width - horizontalPadding);
        node.y = clamp(node.y, verticalPadding, height - verticalPadding);
      }
    }
    metaSimulation.stop();

    return new Map(layoutNodes.map(node => [
      node.name,
      {
        x: node.x,
        y: node.y,
        radius: node.radius,
        total: node.total,
        color: node.color,
      },
    ]));
  }

  _clusterPositionFree(x, y, radius, ignoreName = null) {
    for (const [name, center] of this.clusterCenters.entries()) {
      if (name === ignoreName) continue;
      const dx = x - center.x;
      const dy = y - center.y;
      const minimum = radius + center.radius + CLUSTER_GAP;
      if (dx * dx + dy * dy < minimum * minimum) return false;
    }
    return true;
  }

  _ensureClusterCenter(name, radius) {
    const existing = this.clusterCenters.get(name);
    if (existing) return existing;

    const width = this.app.screen.width;
    const height = this.app.screen.height;
    const seed = hash(name);
    const angleOffset = ((seed & 0xffff) / 0xffff) * Math.PI * 2;
    const maxDistance = Math.hypot(width, height) * 0.55;

    for (let index = 0; index < 360; index += 1) {
      const distance = Math.min(maxDistance, 24 + Math.sqrt(index) * Math.max(26, radius * 0.72));
      const angle = angleOffset + index * GOLDEN_ANGLE;
      const x = clamp(width / 2 + Math.cos(angle) * distance, radius + VIEW_PADDING, width - radius - VIEW_PADDING);
      const y = clamp(height / 2 + Math.sin(angle) * distance, radius + VIEW_PADDING, height - radius - VIEW_PADDING);
      if (!this._clusterPositionFree(x, y, radius)) continue;

      const center = {
        x,
        y,
        radius,
        total: 0,
        color: launchpadAccent(name),
      };
      this.clusterCenters.set(name, center);
      return center;
    }

    const fallback = {
      x: clamp(width / 2, radius + VIEW_PADDING, width - radius - VIEW_PADDING),
      y: clamp(height / 2, radius + VIEW_PADDING, height - radius - VIEW_PADDING),
      radius,
      total: 0,
      color: launchpadAccent(name),
    };
    this.clusterCenters.set(name, fallback);
    return fallback;
  }

  _nodePositionFree(node, x, y) {
    for (const other of this.nodes.values()) {
      if (other === node || other.retiringAt || other.cluster !== node.cluster) continue;
      const dx = x - other.x;
      const dy = y - other.y;
      const minimum = node.radius + other.radius + NODE_GAP;
      if (dx * dx + dy * dy < minimum * minimum) return false;
    }
    return true;
  }

  _placeNodeLocally(node, { preserveCurrent = true } = {}) {
    const center = this.clusterCenters.get(node.cluster)
      || this._ensureClusterCenter(node.cluster, Math.max(42, node.radius * 4));

    if (preserveCurrent && this._nodePositionFree(node, node.x, node.y)) {
      return;
    }

    const width = this.app.screen.width;
    const height = this.app.screen.height;
    const seed = hash(node.token.mint);
    const angleOffset = ((seed & 0xffff) / 0xffff) * Math.PI * 2;
    const step = Math.max(8, (node.radius + NODE_GAP) * 1.8);
    const maxDistance = Math.max(center.radius + node.radius + 24, step * 8);

    for (let index = 0; index < LOCAL_SEARCH_ATTEMPTS; index += 1) {
      const distance = Math.min(maxDistance, step * Math.sqrt(index));
      const angle = angleOffset + index * GOLDEN_ANGLE;
      const x = clamp(
        center.x + Math.cos(angle) * distance,
        node.radius + VIEW_PADDING,
        width - node.radius - VIEW_PADDING,
      );
      const y = clamp(
        center.y + Math.sin(angle) * distance,
        node.radius + VIEW_PADDING,
        height - node.radius - VIEW_PADDING,
      );

      if (!this._nodePositionFree(node, x, y)) continue;
      node.x = x;
      node.y = y;
      node.vx = 0;
      node.vy = 0;
      return;
    }

    const fallbackDistance = Math.min(maxDistance, Math.max(24, center.radius * 0.8));
    node.x = clamp(
      center.x + Math.cos(angleOffset) * fallbackDistance,
      node.radius + VIEW_PADDING,
      width - node.radius - VIEW_PADDING,
    );
    node.y = clamp(
      center.y + Math.sin(angleOffset) * fallbackDistance,
      node.radius + VIEW_PADDING,
      height - node.radius - VIEW_PADDING,
    );
    node.vx = 0;
    node.vy = 0;
  }

  _updateClusterViews(metrics) {
    for (const [name, view] of this.clusterViews.entries()) {
      if (metrics.has(name)) continue;
      view.halo.removeFromParent();
      view.label.removeFromParent();
      view.halo.destroy();
      view.label.destroy();
      this.clusterViews.delete(name);
      this.clusterCenters.delete(name);
    }

    const labelStyle = new TextStyle({
      fill: COLORS.textSecondary,
      fontFamily: "Inter, system-ui, sans-serif",
      fontSize: 11,
      fontWeight: "600",
      letterSpacing: 1.1,
    });

    for (const [name, metric] of metrics.entries()) {
      const center = this.clusterCenters.get(name)
        || this._ensureClusterCenter(name, metric.radius);
      center.radius = metric.radius;
      center.total = metric.total;
      center.color = metric.color;

      let view = this.clusterViews.get(name);
      if (!view) {
        const halo = new Graphics();
        const label = new Text({ text: "", style: labelStyle });
        label.anchor.set(0.5);
        label.alpha = 0.66;
        this.clusterLayer.addChild(halo);
        this.labelLayer.addChild(label);
        view = { halo, label };
        this.clusterViews.set(name, view);
      }

      view.halo.clear()
        .circle(center.x, center.y, center.radius)
        .fill({ color: center.color, alpha: 0.025 })
        .stroke({ color: center.color, alpha: 0.1, width: 1 });
      view.label.text = `${name.toUpperCase()}  ·  ${center.total}`;
      view.label.position.set(center.x, Math.max(14, center.y - center.radius - 14));
    }
  }

  _forceBounds(padding) {
    let forceNodes = [];
    const universe = this;

    function force() {
      const width = universe.app.screen.width;
      const height = universe.app.screen.height;
      for (const node of forceNodes) {
        const radius = node.radius + padding;
        const nextX = node.x + node.vx;
        const nextY = node.y + node.vy;
        if (nextX < radius) node.vx += (radius - nextX) * 0.45;
        else if (nextX > width - radius) node.vx -= (nextX - (width - radius)) * 0.45;
        if (nextY < radius) node.vy += (radius - nextY) * 0.45;
        else if (nextY > height - radius) node.vy -= (nextY - (height - radius)) * 0.45;
      }
    }

    force.initialize = items => {
      forceNodes = items;
    };
    return force;
  }

  _seedNode(node, center) {
    const value = hash(node.token.mint);
    const angle = ((value & 0xffff) / 0xffff) * Math.PI * 2;
    const radialUnit = Math.sqrt(((value >>> 16) & 0xffff) / 0xffff);
    const distance = radialUnit * Math.max(8, center.radius * 0.72);
    node.x = center.x + Math.cos(angle) * distance;
    node.y = center.y + Math.sin(angle) * distance;
    node.vx = 0;
    node.vy = 0;
  }

  _settleBootstrap(items) {
    const targetX = node => this.clusterCenters.get(node.cluster)?.x ?? this.app.screen.width / 2;
    const targetY = node => this.clusterCenters.get(node.cluster)?.y ?? this.app.screen.height / 2;

    const simulation = forceSimulation(items)
      .stop()
      .velocityDecay(0.34)
      .alphaDecay(0.038)
      .force("x", forceX(targetX).strength(0.115))
      .force("y", forceY(targetY).strength(0.115))
      .force("collide", forceCollide(node => node.radius + NODE_GAP).strength(0.94).iterations(2))
      .force("bounds", this._forceBounds(VIEW_PADDING));

    simulation.alpha(1);
    for (let index = 0; index < BOOTSTRAP_TICKS; index += 1) simulation.tick();
    simulation.stop();

    for (const node of items) {
      node.vx = 0;
      node.vy = 0;
      node.view.position.set(node.x, node.y);
    }
  }

  _refreshClusterVisuals() {
    this._updateClusterViews(this._clusterMetrics(this._activeNodes()));
  }

  _layoutScene({ refit = false } = {}) {
    const items = this._activeNodes();
    if (!items.length) return;

    if (refit) {
      for (const node of items) node.baseRadius = baseRadiusForMarketCap(node.token.market_cap);
      this.sceneScale = this._computeSceneScale(items);
      for (const node of items) {
        this._updateNodeGeometry(node);
        this._redrawNode(node);
      }
    }

    const metrics = this._clusterMetrics(items);
    this.clusterCenters = this._computeClusterCenters(metrics);
    for (const node of items) {
      const center = this.clusterCenters.get(node.cluster);
      if (center) this._seedNode(node, center);
    }

    this._settleBootstrap(items);
    this._updateClusterViews(metrics);
  }

  _tick() {
    const now = performance.now();
    for (const [mint, node] of this.nodes.entries()) {
      if (node.retiringAt) {
        const progress = Math.min(1, (now - node.retiringAt) / 720);
        node.view.scale.set(Math.max(0.01, 1 - progress));
        node.view.alpha = 1 - progress;
        if (progress >= 1) {
          node.view.removeFromParent();
          node.view.destroy();
          this.nodes.delete(mint);
        }
        continue;
      }

      if (node.bornAt) {
        const progress = Math.min(1, (now - node.bornAt) / 620);
        const eased = 1 - Math.pow(1 - progress, 3);
        node.view.scale.set(Math.max(0.02, eased));
        if (progress >= 1) node.bornAt = 0;
      } else if (node.pulseUntil > now) {
        const remaining = (node.pulseUntil - now) / 900;
        node.view.scale.set(1 + Math.sin((1 - remaining) * Math.PI) * 0.14);
      } else {
        node.view.scale.set(1);
      }

      node.view.position.set(node.x, node.y);
    }
  }
}
