import { Application, Container, Graphics, Text, TextStyle } from "https://cdn.jsdelivr.net/npm/pixi.js@8.19.0/dist/pixi.min.mjs";

import { areaRadius, equalSlots, percentile, visibleCapacity } from "./bubble-layout.js";
import { normalizedLaunchpad } from "./state.js";
import { COLORS, launchpadAccent } from "./theme.js";

const VIEW_PADDING = 22;
const OVERVIEW_PADDING = 14;
const TOKEN_PADDING = 3;
const RETIRE_DURATION = 420;
const RADIUS_EPSILON = 0.08;
const MIN_MARKET_CAP_REFERENCE = 1_000_000;
const MAX_MARKET_CAP_REFERENCE = 10_000_000;

function marketCap(token) {
  const value = Number(token?.market_cap);
  return Number.isFinite(value) && value > 0 ? value : 0;
}

function tokenOrder(a, b) {
  return marketCap(b.token) - marketCap(a.token) || a.token.mint.localeCompare(b.token.mint);
}

function shortLabel(value, maximum = 14) {
  const text = String(value || "unknown");
  return text.length <= maximum ? text : `${text.slice(0, maximum - 1)}…`;
}

export class TokenUniverse {
  constructor(stageElement, { onSelect, onViewChange } = {}) {
    this.stageElement = stageElement;
    this.onSelect = onSelect || (() => {});
    this.onViewChange = onViewChange || (() => {});
    this.app = null;
    this.groupLayer = null;
    this.tokenLayer = null;
    this.nodes = new Map();
    this.groupViews = new Map();
    this.visibleMints = new Set();
    this.animatingNodes = new Set();
    this.selectedMint = null;
    this.focusedGroupKey = null;
    this.focusCap = 1;
    this.resizeObserver = null;
    this.resizeTimer = null;
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

    this.groupLayer = new Container();
    this.tokenLayer = new Container();
    this.app.stage.addChild(this.groupLayer, this.tokenLayer);
    this.app.ticker.add(() => this._tick());

    this.resizeObserver = new ResizeObserver(() => {
      clearTimeout(this.resizeTimer);
      this.resizeTimer = setTimeout(() => this._renderCurrent(), 160);
    });
    this.resizeObserver.observe(this.stageElement);
  }

  load(tokens) {
    this.nodes.clear();
    for (const token of tokens) this._upsert(token);
    this.showOverview();
  }

  showOverview() {
    this.focusedGroupKey = null;
    this._renderOverview();
  }

  focusGroup(groupKey) {
    if (!this._nodesForGroup(groupKey).length) return;
    this.focusedGroupKey = groupKey;
    this._renderFocus();
  }

  setSelectedMint(mint) {
    const previous = this.selectedMint;
    this.selectedMint = mint;
    if (previous) this._redrawToken(this.nodes.get(previous));
    if (mint) this._redrawToken(this.nodes.get(mint));
  }

  applyEvents(events) {
    const previousGroups = new Set(this._groups().keys());
    let membershipChanged = false;

    for (const event of events) {
      const token = event.token;
      if (!token?.mint) continue;

      const existing = this.nodes.get(token.mint);
      const previousGroup = existing?.groupKey;
      const previousTracking = existing?.token?.tracking_enabled !== false;
      const node = this._upsert(event.type === "token_retired"
        ? { ...existing?.token, ...token, tracking_enabled: false }
        : token);

      if (event.type === "token_retired") {
        membershipChanged = true;
        if (node.view) {
          node.retiringAt = performance.now();
          this.animatingNodes.add(node);
          this._redrawToken(node);
        }
        continue;
      }

      const groupChanged = previousGroup != null && previousGroup !== node.groupKey;
      const entered = !existing || !previousTracking;
      membershipChanged ||= groupChanged || entered;
      if (groupChanged && node.view && node.groupKey !== this.focusedGroupKey) {
        node.view.destroy({ children: true });
        node.view = null;
        node.bubble = null;
        node.label = null;
        node.slot = null;
        this.visibleMints.delete(node.token.mint);
        this.animatingNodes.delete(node);
      }
      if (node.view && this.visibleMints.has(token.mint)) this._updateVisibleRadius(node);
    }

    if (this.focusedGroupKey) {
      this._notifyFocus();
      if (!this._nodesForGroup(this.focusedGroupKey).length) this.showOverview();
      return;
    }

    const nextGroups = new Set(this._groups().keys());
    const groupSetChanged = previousGroups.size !== nextGroups.size
      || [...previousGroups].some(group => !nextGroups.has(group));
    if (groupSetChanged) this._renderOverview();
    else if (membershipChanged) this._updateOverviewValues();
  }

  _upsert(token) {
    let node = this.nodes.get(token.mint);
    if (!node) {
      node = {
        token,
        groupKey: normalizedLaunchpad(token),
        view: null,
        bubble: null,
        label: null,
        slot: null,
        radius: 0,
        targetRadius: 0,
        retiringAt: 0,
      };
      this.nodes.set(token.mint, node);
      return node;
    }
    node.token = token;
    node.groupKey = normalizedLaunchpad(token);
    return node;
  }

  _activeNodes() {
    return [...this.nodes.values()].filter(node => node.token.tracking_enabled !== false && !node.retiringAt);
  }

  _nodesForGroup(groupKey) {
    return this._activeNodes().filter(node => node.groupKey === groupKey);
  }

  _groups() {
    const groups = new Map();
    for (const node of this._activeNodes()) {
      if (!groups.has(node.groupKey)) groups.set(node.groupKey, []);
      groups.get(node.groupKey).push(node);
    }
    return groups;
  }

  _stageSize() {
    return {
      width: Math.max(1, this.app.screen.width - VIEW_PADDING * 2),
      height: Math.max(1, this.app.screen.height - VIEW_PADDING * 2),
    };
  }

  _renderCurrent() {
    if (!this.nodes.size) return;
    if (this.focusedGroupKey) this._renderFocus();
    else this._renderOverview();
  }

  _clearGroups() {
    this.groupLayer.removeChildren().forEach(view => view.destroy({ children: true }));
    this.groupViews.clear();
  }

  _clearTokens() {
    this.tokenLayer.removeChildren().forEach(view => view.destroy({ children: true }));
    for (const mint of this.visibleMints) {
      const node = this.nodes.get(mint);
      if (!node) continue;
      node.view = null;
      node.bubble = null;
      node.label = null;
      node.slot = null;
    }
    this.visibleMints.clear();
    this.animatingNodes.clear();
  }

  _renderOverview() {
    this._clearTokens();
    this._clearGroups();
    const groups = [...this._groups().entries()]
      .map(([groupKey, nodes]) => ({ groupKey, nodes }))
      .sort((a, b) => b.nodes.length - a.nodes.length || a.groupKey.localeCompare(b.groupKey));
    if (!groups.length) return;

    const { width, height } = this._stageSize();
    const slots = equalSlots(groups.map(group => group.groupKey), width, height, OVERVIEW_PADDING);
    const slotByGroup = new Map(slots.map(slot => [slot.id, slot]));
    const countCap = Math.max(...groups.map(group => group.nodes.length));

    for (const group of groups) {
      const slot = slotByGroup.get(group.groupKey);
      const accent = launchpadAccent(group.groupKey);
      const view = new Container();
      const bubble = new Graphics();
      const name = new Text({
        text: shortLabel(group.groupKey.toUpperCase(), 18),
        style: new TextStyle({
          fill: COLORS.textPrimary,
          fontFamily: "Inter, system-ui, sans-serif",
          fontSize: Math.max(9, Math.min(14, slot.radius * 0.16)),
          fontWeight: "700",
          letterSpacing: 0.8,
        }),
      });
      const count = new Text({
        text: group.nodes.length.toLocaleString("en-US"),
        style: new TextStyle({
          fill: COLORS.textSecondary,
          fontFamily: "Inter, system-ui, sans-serif",
          fontSize: Math.max(11, Math.min(24, slot.radius * 0.3)),
          fontWeight: "700",
        }),
      });
      name.anchor.set(0.5);
      count.anchor.set(0.5);
      name.position.set(0, -9);
      count.position.set(0, 13);
      view.position.set(slot.x + VIEW_PADDING, slot.y + VIEW_PADDING);
      view.eventMode = "static";
      view.cursor = "pointer";
      view.on("pointertap", () => this.focusGroup(group.groupKey));
      view.addChild(bubble, name, count);
      this.groupLayer.addChild(view);
      this.groupViews.set(group.groupKey, { view, bubble, name, count, slot, accent });
      this._drawGroup(group.groupKey, group.nodes.length, countCap);
    }

    this.onViewChange({ mode: "overview", groups: groups.length, total: this._activeNodes().length });
  }

  _drawGroup(groupKey, total, countCap) {
    const item = this.groupViews.get(groupKey);
    if (!item) return;
    const radius = areaRadius(total, countCap, item.slot.radius, Math.min(18, item.slot.radius * 0.34));
    item.bubble.clear()
      .circle(0, 0, radius)
      .fill({ color: item.accent, alpha: 0.16 })
      .stroke({ color: item.accent, alpha: 0.82, width: 1.4 });
    item.count.text = total.toLocaleString("en-US");
  }

  _updateOverviewValues() {
    const groups = this._groups();
    const countCap = Math.max(1, ...[...groups.values()].map(nodes => nodes.length));
    for (const [groupKey, nodes] of groups.entries()) this._drawGroup(groupKey, nodes.length, countCap);
    this.onViewChange({ mode: "overview", groups: groups.size, total: this._activeNodes().length });
  }

  _renderFocus() {
    this._clearGroups();
    this._clearTokens();
    const all = this._nodesForGroup(this.focusedGroupKey).sort(tokenOrder);
    if (!all.length) {
      this.showOverview();
      return;
    }

    const { width, height } = this._stageSize();
    const capacity = visibleCapacity(width, height);
    const visible = all.slice(0, capacity);
    const slots = equalSlots(visible.map(node => node.token.mint), width, height, TOKEN_PADDING);
    const slotByMint = new Map(slots.map(slot => [slot.id, slot]));
    this.focusCap = Math.min(
      MAX_MARKET_CAP_REFERENCE,
      Math.max(
        MIN_MARKET_CAP_REFERENCE,
        percentile(visible.map(node => marketCap(node.token)), 0.95),
      ),
    );

    for (const node of visible) {
      const slot = slotByMint.get(node.token.mint);
      node.slot = slot;
      node.radius = areaRadius(marketCap(node.token), this.focusCap, slot.radius);
      node.targetRadius = node.radius;
      this._createTokenView(node);
      node.view.position.set(slot.x + VIEW_PADDING, slot.y + VIEW_PADDING);
      this.tokenLayer.addChild(node.view);
      this.visibleMints.add(node.token.mint);
    }
    this._notifyFocus(all.length);
  }

  _createTokenView(node) {
    const view = new Container();
    const bubble = new Graphics();
    view.eventMode = "static";
    view.cursor = "pointer";
    view.on("pointertap", () => this.onSelect(node.token.mint));
    view.addChild(bubble);
    node.view = view;
    node.bubble = bubble;
    this._redrawToken(node);
  }

  _updateVisibleRadius(node) {
    if (!node.slot || node.retiringAt) return;
    node.targetRadius = areaRadius(marketCap(node.token), this.focusCap, node.slot.radius);
    if (Math.abs(node.targetRadius - node.radius) > RADIUS_EPSILON) this.animatingNodes.add(node);
    else this._redrawToken(node);
  }

  _redrawToken(node) {
    if (!node?.bubble) return;
    const selected = node.token.mint === this.selectedMint;
    const color = node.retiringAt ? COLORS.destructive : launchpadAccent(node.groupKey);
    node.bubble.clear()
      .circle(0, 0, node.radius)
      .fill({ color, alpha: node.retiringAt ? 0.38 : 0.22 })
      .stroke({
        color: selected ? COLORS.selection : color,
        alpha: selected ? 1 : 0.82,
        width: selected ? 2.4 : 1,
      });

    const shouldLabel = node.radius >= 13;
    if (!shouldLabel) {
      if (node.label) {
        node.label.destroy();
        node.label = null;
      }
      return;
    }
    if (!node.label) {
      node.label = new Text({
        text: "",
        style: new TextStyle({
          fill: COLORS.textPrimary,
          fontFamily: "Inter, system-ui, sans-serif",
          fontWeight: "650",
          align: "center",
        }),
      });
      node.label.anchor.set(0.5);
      node.label.eventMode = "none";
      node.view.addChild(node.label);
    }
    node.label.text = shortLabel(node.token.symbol || node.token.name || node.token.mint.slice(0, 6), 7);
    node.label.style.fontSize = Math.max(7, Math.min(12, node.radius * 0.48));
  }

  _notifyFocus(total = null) {
    const currentTotal = total ?? this._nodesForGroup(this.focusedGroupKey).length;
    const shown = [...this.visibleMints].filter(mint => {
      const node = this.nodes.get(mint);
      return node?.token.tracking_enabled !== false && node.groupKey === this.focusedGroupKey;
    }).length;
    this.onViewChange({
      mode: "focus",
      groupKey: this.focusedGroupKey,
      shown,
      total: currentTotal,
    });
  }

  _tick() {
    if (!this.animatingNodes.size) return;
    const now = performance.now();

    for (const node of [...this.animatingNodes]) {
      if (!node.view) {
        this.animatingNodes.delete(node);
        continue;
      }

      if (node.retiringAt) {
        const progress = Math.min(1, (now - node.retiringAt) / RETIRE_DURATION);
        node.view.scale.set(Math.max(0.01, 1 - progress * progress));
        node.view.alpha = 1 - progress;
        if (progress < 1) continue;
        node.view.destroy({ children: true });
        node.view = null;
        node.bubble = null;
        node.label = null;
        this.visibleMints.delete(node.token.mint);
        this.animatingNodes.delete(node);
        continue;
      }

      const delta = node.targetRadius - node.radius;
      if (Math.abs(delta) <= RADIUS_EPSILON) {
        node.radius = node.targetRadius;
        this.animatingNodes.delete(node);
      } else {
        node.radius += delta * 0.22;
      }
      this._redrawToken(node);
    }
  }
}
