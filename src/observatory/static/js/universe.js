import { Application, Container, Graphics, Text, TextStyle } from "https://cdn.jsdelivr.net/npm/pixi.js@8.19.0/dist/pixi.min.mjs";
import { packEnclose, packSiblings } from "https://cdn.jsdelivr.net/npm/d3-hierarchy@3.1.2/+esm";

import { ClusterLayout } from "./cluster-layout.js";
import { normalizedLaunchpad } from "./state.js";
import { COLORS, launchpadAccent } from "./theme.js";

const COLLISION_GAP = 1.2;
const PACK_GAP = 3;
const VIEW_PADDING = 18;
const CLUSTER_GAP = 24;
const CLUSTER_PADDING = 12;
const PACKING_DENSITY = 0.72;
const TARGET_NODE_AREA_SHARE = 0.46;
const MIN_VISIBLE_RADIUS_DELTA = 0.6;
const GOLDEN_ANGLE = Math.PI * (3 - Math.sqrt(5));

function clamp(value, minimum, maximum) {
  if (minimum > maximum) return (minimum + maximum) / 2;
  return Math.max(minimum, Math.min(maximum, value));
}

function hash(text) {
  let value = 2166136261;
  for (let index = 0; index < text.length; index += 1) {
    value ^= text.charCodeAt(index);
    value = Math.imul(value, 16777619);
  }
  return value >>> 0;
}

function baseRadiusForMarketCap(marketCap) {
  const value = Math.max(1, marketCap || 1);
  return Math.max(4.5, Math.min(28, 4 + (Math.log10(value) - 2) * 5.2));
}

function stableNodeOrder(a, b) {
  return b.radius - a.radius || a.token.mint.localeCompare(b.token.mint);
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
    this.animatingNodes = new Set();
    this.selectedMint = null;
    this.sceneScale = 1;
    this.resizeTimer = null;
    this.resizeObserver = null;
    this.layout = null;
    this.draggedNode = null;
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
    this.app.stage.eventMode = "static";
    this.app.stage.hitArea = this.app.screen;
    this.app.stage.on("globalpointermove", event => this._moveDrag(event));
    this.app.stage.on("pointerup", () => this._endDrag(this.draggedNode));
    this.app.stage.on("pointerupoutside", () => this._endDrag(this.draggedNode));

    this.layout = new ClusterLayout({
      getNodes: groupKey => this._spatialNodes(groupKey),
      groupKeyFor: node => node.groupKey,
      centerFor: groupKey => this.clusterCenters.get(groupKey),
      gap: COLLISION_GAP,
    });
    this.app.ticker.add(() => this._tick());

    this.resizeObserver = new ResizeObserver(() => {
      clearTimeout(this.resizeTimer);
      this.resizeTimer = setTimeout(() => {
        if (this.nodes.size) this._layoutScene({ refit: true });
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
    const settlements = new Map();
    let clusterVisualsChanged = false;
    const queueSettlement = (groupKey, seed, anchor = null) => {
      let request = settlements.get(groupKey);
      if (!request) {
        request = { seeds: [], anchors: [] };
        settlements.set(groupKey, request);
      }
      request.seeds.push(seed);
      if (anchor) request.anchors.push(anchor);
    };

    for (const event of events) {
      if (event.type === "token_added") {
        clusterVisualsChanged = true;
        const node = this._addToken(event.token, true);
        const center = this._ensureClusterCenter(node.groupKey, Math.max(42, node.radius * 4));
        this._seedNode(node, center);
        queueSettlement(node.groupKey, node, node);
        continue;
      }

      if (event.type === "token_updated") {
        const result = this._updateToken(event.token);
        const node = result.node;
        if (!node) continue;

        if (result.wasAdded) {
          clusterVisualsChanged = true;
          const center = this._ensureClusterCenter(node.groupKey, Math.max(42, node.radius * 4));
          this._seedNode(node, center);
          queueSettlement(node.groupKey, node, node);
        } else if (result.groupChanged) {
          clusterVisualsChanged = true;
          queueSettlement(result.previousGroupKey, result.previousPosition);
          const center = this._ensureClusterCenter(node.groupKey, Math.max(42, node.radius * 4));
          this._seedNode(node, center);
          queueSettlement(node.groupKey, node, node);
        } else if (result.geometryChanged) {
          queueSettlement(node.groupKey, node, node);
        }
        continue;
      }

      if (event.type === "token_retired") {
        this._retireToken(event.token, event.reason);
      }
    }

    if (clusterVisualsChanged) this._refreshClusterVisuals();
    for (const [groupKey, request] of settlements.entries()) {
      this.layout.settle(groupKey, request);
    }
  }

  _spatialNodes(groupKey = null) {
    const nodes = [...this.nodes.values()];
    return groupKey == null ? nodes : nodes.filter(node => node.groupKey === groupKey);
  }

  _activeNodes() {
    return [...this.nodes.values()].filter(node => !node.retiringAt);
  }

  _updateNodeGeometry(node, { force = false } = {}) {
    const baseRadius = baseRadiusForMarketCap(node.token.market_cap);
    const nextRadius = baseRadius * this.sceneScale;
    node.baseRadius = baseRadius;
    if (!force && node.radius != null && Math.abs(node.radius - nextRadius) < MIN_VISIBLE_RADIUS_DELTA) {
      return false;
    }
    node.radius = nextRadius;
    return true;
  }

  _createView(node) {
    const view = new Graphics();
    node.view = view;
    view.eventMode = "static";
    view.cursor = "pointer";
    view.on("pointerdown", event => this._beginDrag(node, event));
    view.on("pointerup", () => this._endDrag(node));
    view.on("pointerupoutside", () => this._endDrag(node));
    view.on("pointertap", () => {
      if (!node.dragMoved) this.onSelect(node.token.mint);
    });
    this.tokenLayer.addChild(view);
    this._redrawNode(node);
  }

  _pointerPosition(node, event) {
    return this.layout.constrain(
      node,
      event.global.x + (node.dragOffsetX || 0),
      event.global.y + (node.dragOffsetY || 0),
    );
  }

  _beginDrag(node, event) {
    if (node.retiringAt) return;
    this.draggedNode = node;
    node.dragPointerStartX = event.global.x;
    node.dragPointerStartY = event.global.y;
    node.dragOffsetX = node.x - event.global.x;
    node.dragOffsetY = node.y - event.global.y;
    node.dragMoved = false;
    node.view.cursor = "grabbing";
    this.layout.beginDrag(node, node.x, node.y);
  }

  _moveDrag(event) {
    const node = this.draggedNode;
    if (!node) return;
    const point = this._pointerPosition(node, event);
    if (Math.hypot(
      event.global.x - node.dragPointerStartX,
      event.global.y - node.dragPointerStartY,
    ) > 3) node.dragMoved = true;
    this.layout.moveDrag(node, point.x, point.y);
  }

  _endDrag(node) {
    if (!node || this.draggedNode !== node) return;
    this.draggedNode = null;
    node.view.cursor = "pointer";
    delete node.dragPointerStartX;
    delete node.dragPointerStartY;
    delete node.dragOffsetX;
    delete node.dragOffsetY;
    this.layout.endDrag(node);
  }

  _redrawNode(node) {
    const color = node.retiringAt ? COLORS.destructive : launchpadAccent(node.groupKey);
    const selected = node.token.mint === this.selectedMint;
    node.view.clear()
      .circle(0, 0, node.radius)
      .fill({ color, alpha: node.retiringAt ? 0.78 : 0.58 })
      .stroke({
        color: selected ? COLORS.selection : color,
        alpha: selected ? 1 : 0.78,
        width: selected ? 2.4 : 0.9,
      });
  }

  _addToken(token, animate = true) {
    const existing = this.nodes.get(token.mint);
    if (existing) {
      this._updateToken(token);
      return existing;
    }

    const node = {
      token,
      groupKey: normalizedLaunchpad(token),
      baseRadius: baseRadiusForMarketCap(token.market_cap),
      radius: null,
      x: this.app.screen.width / 2,
      y: this.app.screen.height / 2,
      bornAt: animate ? performance.now() : 0,
      retiringAt: 0,
    };
    node.radius = node.baseRadius * this.sceneScale;

    this.nodes.set(token.mint, node);
    this._createView(node);
    node.view.position.set(node.x, node.y);
    node.view.scale.set(animate ? 0.02 : 1);
    if (animate) this.animatingNodes.add(node);
    return node;
  }

  _updateToken(token) {
    const node = this.nodes.get(token.mint);
    if (!node) {
      const added = this._addToken(token, true);
      return {
        node: added,
        previousGroupKey: null,
        groupChanged: true,
        geometryChanged: true,
        wasAdded: true,
      };
    }

    const previousGroupKey = node.groupKey;
    const previousRadius = node.radius;
    const previousPosition = { x: node.x, y: node.y, radius: previousRadius };
    node.token = token;
    node.groupKey = normalizedLaunchpad(token);
    const geometryChanged = this._updateNodeGeometry(node);
    const groupChanged = previousGroupKey !== node.groupKey;
    if (geometryChanged || groupChanged) this._redrawNode(node);

    return {
      node,
      previousGroupKey,
      groupChanged,
      geometryChanged,
      previousPosition,
      wasAdded: false,
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
    this.animatingNodes.add(node);
    this._redrawNode(node);
    return true;
  }

  _computeSceneScale(items) {
    if (!items.length) return 1;
    const width = Math.max(1, this.app.screen.width - VIEW_PADDING * 2);
    const height = Math.max(1, this.app.screen.height - VIEW_PADDING * 2 - 24);
    const usableArea = width * height;

    let rawArea = 0;
    const clusterSquares = new Map();
    for (const node of items) {
      const radius = node.baseRadius + PACK_GAP / 2;
      rawArea += Math.PI * radius * radius;
      clusterSquares.set(node.groupKey, (clusterSquares.get(node.groupKey) || 0) + radius * radius);
    }

    const areaScale = Math.sqrt((usableArea * TARGET_NODE_AREA_SHARE) / Math.max(1, rawArea));
    const largestCluster = Math.sqrt(Math.max(1, ...clusterSquares.values()) / PACKING_DENSITY);
    const clusterScale = Math.min(width, height) * 0.42 / largestCluster;
    return Math.min(1, areaScale, clusterScale);
  }

  _packScene(items) {
    const groups = new Map();
    for (const node of items) {
      if (!groups.has(node.groupKey)) groups.set(node.groupKey, []);
      groups.get(node.groupKey).push(node);
    }

    const packedGroups = [];
    for (const [name, nodes] of groups.entries()) {
      const circles = [...nodes].sort(stableNodeOrder).map(node => ({
        node,
        r: node.radius + PACK_GAP / 2,
      }));
      packSiblings(circles);
      const enclosure = packEnclose(circles);
      packedGroups.push({
        name,
        nodes,
        circles,
        radius: enclosure.r + PACK_GAP / 2 + CLUSTER_PADDING,
        localX: enclosure.x,
        localY: enclosure.y,
        color: launchpadAccent(name),
      });
    }

    const clusterCircles = packedGroups
      .sort((a, b) => b.radius - a.radius || a.name.localeCompare(b.name))
      .map(group => ({ group, r: group.radius + CLUSTER_GAP / 2 }));
    packSiblings(clusterCircles);
    const enclosure = packEnclose(clusterCircles);
    return { clusterCircles, enclosure };
  }

  _packedSceneFit(packed) {
    const width = Math.max(1, this.app.screen.width - VIEW_PADDING * 2);
    const height = Math.max(1, this.app.screen.height - VIEW_PADDING * 2 - 24);
    let minX = Infinity;
    let maxX = -Infinity;
    let minY = Infinity;
    let maxY = -Infinity;
    for (const circle of packed.clusterCircles) {
      minX = Math.min(minX, circle.x - circle.r);
      maxX = Math.max(maxX, circle.x + circle.r);
      minY = Math.min(minY, circle.y - circle.r);
      maxY = Math.max(maxY, circle.y + circle.r);
    }
    return Math.min(1, width / Math.max(1, maxX - minX), height / Math.max(1, maxY - minY));
  }

  _clusterPositionFree(x, y, radius, ignoreName = null) {
    for (const [name, center] of this.clusterCenters.entries()) {
      if (name === ignoreName) continue;
      if (Math.hypot(x - center.x, y - center.y) < radius + center.radius + CLUSTER_GAP) {
        return false;
      }
    }
    return true;
  }

  _ensureClusterCenter(name, radius) {
    const existing = this.clusterCenters.get(name);
    if (existing) return existing;

    const width = this.app.screen.width;
    const height = this.app.screen.height;
    const angleOffset = (hash(name) / 0xffffffff) * Math.PI * 2;
    for (let index = 0; index < 360; index += 1) {
      const distance = 24 + Math.sqrt(index) * Math.max(28, radius * 0.8);
      const angle = angleOffset + index * GOLDEN_ANGLE;
      const x = clamp(width / 2 + Math.cos(angle) * distance, radius + VIEW_PADDING, width - radius - VIEW_PADDING);
      const y = clamp(height / 2 + Math.sin(angle) * distance, radius + VIEW_PADDING, height - radius - VIEW_PADDING);
      if (!this._clusterPositionFree(x, y, radius)) continue;
      const center = { x, y, radius, total: 0, color: launchpadAccent(name) };
      this.clusterCenters.set(name, center);
      return center;
    }

    const center = {
      x: width / 2,
      y: height / 2,
      radius,
      total: 0,
      color: launchpadAccent(name),
    };
    this.clusterCenters.set(name, center);
    return center;
  }

  _seedNode(node, center) {
    const angle = (hash(node.token.mint) / 0xffffffff) * Math.PI * 2;
    const distance = Math.max(0, center.radius - node.radius - COLLISION_GAP);
    node.x = center.x + Math.cos(angle) * distance;
    node.y = center.y + Math.sin(angle) * distance;
    node.view.position.set(node.x, node.y);
  }

  _refreshClusterVisuals() {
    const groups = new Map();
    for (const node of this._spatialNodes()) {
      groups.set(node.groupKey, (groups.get(node.groupKey) || 0) + 1);
    }

    for (const [name, view] of this.clusterViews.entries()) {
      if (groups.has(name)) continue;
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

    for (const [name, total] of groups.entries()) {
      const center = this.clusterCenters.get(name) || this._ensureClusterCenter(name, 42);
      center.total = total;
      center.color = launchpadAccent(name);

      let view = this.clusterViews.get(name);
      if (!view) {
        const halo = new Graphics();
        const label = new Text({ text: "", style: labelStyle });
        label.anchor.set(0.5);
        this.clusterLayer.addChild(halo);
        this.labelLayer.addChild(label);
        view = { halo, label };
        this.clusterViews.set(name, view);
      }

      view.halo.clear()
        .circle(center.x, center.y, center.radius)
        .fill({ color: center.color, alpha: 0.045 })
        .stroke({ color: center.color, alpha: 0.22, width: 1 });
      view.label.text = `${name.toUpperCase()}  ·  ${total}`;
      view.label.alpha = 0.82;
      view.label.position.set(center.x, Math.max(14, center.y - center.radius - 14));
    }
  }

  _layoutScene({ refit = false } = {}) {
    this.layout?.stop();
    const items = this._activeNodes();
    if (!items.length) return;

    if (refit) {
      for (const node of items) node.baseRadius = baseRadiusForMarketCap(node.token.market_cap);
      this.sceneScale = this._computeSceneScale(items);
      for (const node of items) {
        this._updateNodeGeometry(node, { force: true });
        this._redrawNode(node);
      }
    }

    let packed = this._packScene(items);
    const fit = this._packedSceneFit(packed);
    if (fit < 0.995) {
      this.sceneScale *= fit * 0.98;
      for (const node of items) {
        this._updateNodeGeometry(node, { force: true });
        this._redrawNode(node);
      }
      packed = this._packScene(items);
    }

    const offsetX = this.app.screen.width / 2 - packed.enclosure.x;
    const offsetY = this.app.screen.height / 2 - packed.enclosure.y + 10;
    this.clusterCenters = new Map();

    for (const clusterCircle of packed.clusterCircles) {
      const group = clusterCircle.group;
      const center = {
        x: offsetX + clusterCircle.x,
        y: offsetY + clusterCircle.y,
        radius: group.radius,
        total: group.nodes.length,
        color: group.color,
      };
      this.clusterCenters.set(group.name, center);
      for (const circle of group.circles) {
        circle.node.x = center.x + circle.x - group.localX;
        circle.node.y = center.y + circle.y - group.localY;
        circle.node.view.position.set(circle.node.x, circle.node.y);
      }
    }
    this._refreshClusterVisuals();
  }

  _tick() {
    const moved = this.layout?.step();
    if (moved) {
      for (const node of moved) node.view.position.set(node.x, node.y);
    }

    if (!this.animatingNodes.size) return;
    const now = performance.now();
    const vacancies = [];

    for (const node of [...this.animatingNodes]) {
      if (node.retiringAt) {
        const elapsed = now - node.retiringAt;
        if (elapsed < 160) {
          node.view.alpha = 1;
          node.view.scale.set(1);
          continue;
        }
        const progress = Math.min(1, (elapsed - 160) / 460);
        const eased = progress * progress;
        node.view.scale.set(Math.max(0.01, 1 - eased));
        node.view.alpha = 1 - progress;
        if (progress < 1) continue;

        vacancies.push({
          groupKey: node.groupKey,
          seed: { x: node.x, y: node.y, radius: node.radius },
        });
        this.animatingNodes.delete(node);
        node.view.destroy();
        this.nodes.delete(node.token.mint);
        continue;
      }

      const progress = Math.min(1, (now - node.bornAt) / 420);
      const eased = 1 - Math.pow(1 - progress, 3);
      node.view.scale.set(Math.max(0.02, eased));
      if (progress >= 1) {
        node.bornAt = 0;
        this.animatingNodes.delete(node);
      }
    }

    if (vacancies.length) {
      this._refreshClusterVisuals();
      for (const vacancy of vacancies) {
        this.layout.settle(vacancy.groupKey, { seeds: [vacancy.seed] });
      }
    }
  }
}
