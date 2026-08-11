import { Application, Container, Graphics, Text, TextStyle } from "https://cdn.jsdelivr.net/npm/pixi.js@8.19.0/dist/pixi.min.mjs";
import { forceCollide, forceManyBody, forceSimulation, forceX, forceY } from "https://cdn.jsdelivr.net/npm/d3-force@3.0.0/+esm";

const stageElement = document.querySelector("#universe-stage");
const activeCount = document.querySelector("#active-count");
const launchpadCount = document.querySelector("#launchpad-count");
const changedCount = document.querySelector("#changed-count");
const streamStatus = document.querySelector("#stream-status");
const eventFeed = document.querySelector("#event-feed");
const feedRate = document.querySelector("#feed-rate");
const emptyDetail = document.querySelector("#empty-detail");
const tokenDetail = document.querySelector("#token-detail");

const app = new Application();
await app.init({
  resizeTo: stageElement,
  backgroundAlpha: 0,
  antialias: true,
  autoDensity: true,
  resolution: Math.min(window.devicePixelRatio || 1, 2),
  preference: "webgl",
});
stageElement.appendChild(app.canvas);

const clusterLayer = new Container();
const tokenLayer = new Container();
const labelLayer = new Container();
app.stage.addChild(clusterLayer, tokenLayer, labelLayer);

const nodes = new Map();
const clusterViews = new Map();
let clusterCenters = new Map();
let simulation = null;
let selectedMint = null;
let recentChanges = [];
let eventCount = 0;
let sceneScale = 1;
let resizeTimer = null;

const NODE_GAP = 1.6;
const VIEW_PADDING = 14;
const CLUSTER_GAP = 18;
const PACKING_DENSITY = 0.72;
const TARGET_NODE_AREA_SHARE = 0.48;

const numberCompact = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 });
const integerFormat = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });

const clusterLabelStyle = new TextStyle({
  fill: 0xd9dfe7,
  fontFamily: "Inter, system-ui, sans-serif",
  fontSize: 11,
  fontWeight: "600",
  letterSpacing: 1.1,
});

function money(value) {
  return value == null ? "—" : `$${numberCompact.format(value)}`;
}

function count(value) {
  return value == null ? "—" : integerFormat.format(value);
}

function duration(seconds) {
  if (seconds == null || !Number.isFinite(seconds)) return "—";
  if (seconds < 60) return `${Math.max(0, Math.round(seconds))}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
  if (seconds < 86400) return `${(seconds / 3600).toFixed(seconds < 18000 ? 1 : 0)}h`;
  return `${(seconds / 86400).toFixed(1)}d`;
}

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

function hslToHex(h, s, l) {
  s /= 100;
  l /= 100;
  const c = (1 - Math.abs(2 * l - 1)) * s;
  const x = c * (1 - Math.abs((h / 60) % 2 - 1));
  const m = l - c / 2;
  let r = 0, g = 0, b = 0;
  if (h < 60) [r, g] = [c, x];
  else if (h < 120) [r, g] = [x, c];
  else if (h < 180) [g, b] = [c, x];
  else if (h < 240) [g, b] = [x, c];
  else if (h < 300) [r, b] = [x, c];
  else [r, b] = [c, x];
  return (Math.round((r + m) * 255) << 16)
    | (Math.round((g + m) * 255) << 8)
    | Math.round((b + m) * 255);
}

function clusterColor(launchpad) {
  return hslToHex(hash(launchpad) % 360, 58, 61);
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

function normalizedLaunchpad(token) {
  return token.launchpad && token.launchpad !== "" ? token.launchpad : "unknown";
}

function activeNodes() {
  return [...nodes.values()].filter(node => !node.retiringAt);
}

function activeClusterNames() {
  return new Set(activeNodes().map(node => node.cluster));
}

function sameSet(left, right) {
  if (left.size !== right.size) return false;
  for (const value of left) {
    if (!right.has(value)) return false;
  }
  return true;
}

function updateNodeGeometry(node) {
  node.baseRadius = baseRadiusForMarketCap(node.token.market_cap);
  node.radius = node.baseRadius * sceneScale;
  node.cluster = normalizedLaunchpad(node.token);
}

function createView(node) {
  const view = new Graphics();
  node.view = view;
  view.eventMode = "static";
  view.cursor = "pointer";
  view.on("pointertap", () => selectToken(node.token.mint));
  tokenLayer.addChild(view);
  redrawNode(node);
}

function redrawNode(node) {
  const token = node.token;
  const color = clusterColor(node.cluster);
  const alpha = freshnessAlpha(token.change_age_seconds);
  const strokeWidth = liquidityStroke(token.liquidity, token.market_cap);

  node.view.clear()
    .circle(0, 0, node.radius)
    .fill({ color, alpha: alpha * 0.76 })
    .stroke({
      color: 0xffffff,
      alpha: 0.18 + alpha * 0.28,
      width: strokeWidth,
    });
}

function seedNode(node, center) {
  const value = hash(node.token.mint);
  const angle = ((value & 0xffff) / 0xffff) * Math.PI * 2;
  const radialUnit = Math.sqrt(((value >>> 16) & 0xffff) / 0xffff);
  const distance = radialUnit * Math.max(8, center.radius * 0.72);

  node.x = center.x + Math.cos(angle) * distance;
  node.y = center.y + Math.sin(angle) * distance;
  node.vx = 0;
  node.vy = 0;
  node.seeded = true;
}

function addToken(token, animate = true) {
  if (nodes.has(token.mint)) {
    updateToken(token, false);
    return;
  }

  const cluster = normalizedLaunchpad(token);
  const center = clusterCenters.get(cluster);
  const node = {
    token,
    cluster,
    baseRadius: baseRadiusForMarketCap(token.market_cap),
    radius: baseRadiusForMarketCap(token.market_cap) * sceneScale,
    x: center?.x ?? app.screen.width / 2,
    y: center?.y ?? app.screen.height / 2,
    vx: 0,
    vy: 0,
    pulseUntil: 0,
    bornAt: animate ? performance.now() : 0,
    retiringAt: 0,
    seeded: false,
  };

  nodes.set(token.mint, node);
  if (center) seedNode(node, center);
  createView(node);
  node.view.scale.set(animate ? 0.02 : 1);
}

function updateToken(token, pulse = true) {
  const node = nodes.get(token.mint);
  if (!node) {
    addToken(token, true);
    return { topologyChanged: true, clusterChanged: false, geometryChanged: true };
  }

  const previousCluster = node.cluster;
  const previousRadius = node.radius;
  node.token = token;
  updateNodeGeometry(node);
  redrawNode(node);

  if (pulse) node.pulseUntil = performance.now() + 900;
  if (selectedMint === token.mint) renderDetail(token);

  return {
    topologyChanged: false,
    clusterChanged: previousCluster !== node.cluster,
    geometryChanged: Math.abs(previousRadius - node.radius) > 0.15,
  };
}

function retireToken(token, reason) {
  const node = nodes.get(token.mint);
  if (!node || node.retiringAt) return false;

  node.token = {
    ...node.token,
    ...token,
    disabled_reason: reason || token.disabled_reason,
  };
  node.retiringAt = performance.now();
  if (selectedMint === token.mint) renderDetail(node.token);
  return true;
}

function computeSceneScale(items) {
  if (!items.length) return 1;

  const width = Math.max(1, app.screen.width - VIEW_PADDING * 2);
  const height = Math.max(1, app.screen.height - VIEW_PADDING * 2);
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
  const clusterScale = largestClusterCore > 0
    ? maxClusterCore / largestClusterCore
    : 1;

  return Math.min(1, areaScale, clusterScale);
}

function clusterMetrics(items) {
  const metrics = new Map();

  for (const node of items) {
    let metric = metrics.get(node.cluster);
    if (!metric) {
      metric = {
        name: node.cluster,
        total: 0,
        sumSquares: 0,
        color: clusterColor(node.cluster),
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

function computeClusterCenters(metrics) {
  const width = app.screen.width;
  const height = app.screen.height;
  const entries = [...metrics.values()].sort((a, b) => b.radius - a.radius);
  if (!entries.length) return new Map();

  const goldenAngle = Math.PI * (3 - Math.sqrt(5));
  const orbitBase = Math.min(width, height) * 0.24;

  const layoutNodes = entries.map((metric, index) => {
    const previous = clusterCenters.get(metric.name);
    if (previous) {
      return {
        ...metric,
        x: previous.x,
        y: previous.y,
        vx: 0,
        vy: 0,
      };
    }

    if (index === 0) {
      return {
        ...metric,
        x: width / 2,
        y: height / 2,
        vx: 0,
        vy: 0,
      };
    }

    const angle = (index - 1) * goldenAngle;
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
      node.y = clamp(node.y, verticalPadding, height - horizontalPadding);
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

function updateClusterViews(metrics) {
  for (const [name, view] of clusterViews.entries()) {
    if (metrics.has(name)) continue;
    view.halo.removeFromParent();
    view.label.removeFromParent();
    view.halo.destroy();
    view.label.destroy();
    clusterViews.delete(name);
    clusterCenters.delete(name);
  }

  for (const [name, metric] of metrics.entries()) {
    const center = clusterCenters.get(name);
    if (!center) continue;

    center.radius = metric.radius;
    center.total = metric.total;
    center.color = metric.color;

    let view = clusterViews.get(name);
    if (!view) {
      const halo = new Graphics();
      const label = new Text({ text: "", style: clusterLabelStyle });
      label.anchor.set(0.5);
      label.alpha = 0.72;
      clusterLayer.addChild(halo);
      labelLayer.addChild(label);
      view = { halo, label };
      clusterViews.set(name, view);
    }

    view.halo.clear()
      .circle(center.x, center.y, center.radius)
      .fill({ color: center.color, alpha: 0.035 })
      .stroke({ color: center.color, alpha: 0.12, width: 1 });

    view.label.text = `${name.toUpperCase()}  ·  ${center.total}`;
    view.label.position.set(
      center.x,
      Math.max(14, center.y - center.radius - 14),
    );
  }
}

function forceBounds(padding) {
  let forceNodes = [];

  function force() {
    const width = app.screen.width;
    const height = app.screen.height;

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

function configureSimulation(items, reheat = 0.1) {
  const targetX = node => clusterCenters.get(node.cluster)?.x ?? app.screen.width / 2;
  const targetY = node => clusterCenters.get(node.cluster)?.y ?? app.screen.height / 2;

  if (!simulation) {
    simulation = forceSimulation(items)
      .velocityDecay(0.34)
      .alphaDecay(0.038)
      .force("x", forceX(targetX).strength(0.115))
      .force("y", forceY(targetY).strength(0.115))
      .force("collide", forceCollide(node => node.radius + NODE_GAP).strength(0.94).iterations(2))
      .force("bounds", forceBounds(VIEW_PADDING));
  } else {
    simulation.nodes(items);
    simulation.force("x").x(targetX);
    simulation.force("y").y(targetY);
    simulation.force("collide").radius(node => node.radius + NODE_GAP);
  }

  simulation.alpha(Math.max(simulation.alpha(), reheat)).restart();
}

function refreshCollision(reheat = 0.035) {
  if (!simulation) return;
  simulation.force("collide").radius(node => node.radius + NODE_GAP);
  simulation.alpha(Math.max(simulation.alpha(), reheat)).restart();
}

function refreshClusterVisuals() {
  const items = activeNodes();
  const metrics = clusterMetrics(items);
  updateClusterViews(metrics);
}

function layoutScene({ refit = false, seedUnplaced = false, reheat = 0.16 } = {}) {
  const items = activeNodes();
  if (!items.length) return;

  if (refit) {
    for (const node of items) node.baseRadius = baseRadiusForMarketCap(node.token.market_cap);
    sceneScale = computeSceneScale(items);
    for (const node of items) {
      updateNodeGeometry(node);
      redrawNode(node);
    }
  }

  const metrics = clusterMetrics(items);
  clusterCenters = computeClusterCenters(metrics);
  updateClusterViews(metrics);

  if (seedUnplaced) {
    for (const node of items) {
      if (node.seeded) continue;
      const center = clusterCenters.get(node.cluster);
      if (center) seedNode(node, center);
    }
  }

  configureSimulation(items, reheat);
}

function updateStats() {
  const active = activeNodes();
  activeCount.textContent = integerFormat.format(active.length);
  launchpadCount.textContent = new Set(active.map(node => node.cluster)).size;

  const cutoff = Date.now() - 60_000;
  recentChanges = recentChanges.filter(timestamp => timestamp >= cutoff);
  changedCount.textContent = integerFormat.format(recentChanges.length);
  feedRate.textContent = `${eventCount} event${eventCount === 1 ? "" : "s"}`;
}

function selectToken(mint) {
  selectedMint = mint;
  const node = nodes.get(mint);
  if (node) renderDetail(node.token);
}

function renderDetail(token) {
  emptyDetail.classList.add("hidden");
  tokenDetail.classList.remove("hidden");
  document.querySelector("#detail-launchpad").textContent = normalizedLaunchpad(token);
  document.querySelector("#detail-name").textContent = token.name || token.symbol || "Unnamed token";
  document.querySelector("#detail-symbol").textContent = token.symbol || "—";

  const state = document.querySelector("#detail-state");
  state.textContent = token.tracking_enabled ? "ACTIVE" : "RETIRED";
  state.style.color = token.tracking_enabled ? "var(--accent)" : "var(--danger)";

  document.querySelector("#detail-mcap").textContent = money(token.market_cap);
  document.querySelector("#detail-liquidity").textContent = money(token.liquidity);
  document.querySelector("#detail-holders").textContent = count(token.holders);
  document.querySelector("#detail-traders").textContent = count(token.traders_5m);
  document.querySelector("#detail-trades").textContent = count(token.trades_5m);
  document.querySelector("#detail-volume").textContent = money(token.volume_5m);
  document.querySelector("#detail-poll").textContent = `${duration(token.poll_age_seconds)} ago`;
  document.querySelector("#detail-change").textContent = `${duration(token.change_age_seconds)} ago`;
  document.querySelector("#detail-age").textContent = duration(token.age_seconds);
  document.querySelector("#detail-mint").textContent = token.mint;
}

function eventSummary(event) {
  const token = event.token;

  if (event.type === "token_added") {
    return `entered ${normalizedLaunchpad(token)} · ${money(token.market_cap)}`;
  }

  if (event.type === "token_retired") {
    return event.reason || token.disabled_reason || "tracking disabled";
  }

  const percent = event.changes?.market_cap?.percent;
  if (percent != null && Math.abs(percent) >= 0.1) {
    return `market cap ${percent > 0 ? "+" : ""}${percent.toFixed(1)}% · ${money(token.market_cap)}`;
  }

  return `state changed · ${duration(token.change_age_seconds)} since update`;
}

function pushFeed(event) {
  eventCount += 1;
  const item = document.createElement("li");
  item.className = "event-item";
  const type = event.type.replace("token_", "");

  item.innerHTML = `
    <span class="event-type ${type}">${type.toUpperCase()}</span>
    <span class="event-copy"><strong></strong><span></span></span>
  `;

  item.querySelector("strong").textContent =
    event.token.symbol || event.token.name || event.token.mint.slice(0, 8);
  item.querySelector(".event-copy span").textContent = eventSummary(event);
  eventFeed.prepend(item);

  while (eventFeed.children.length > 36) {
    eventFeed.lastElementChild.remove();
  }
}

function applyDelta(events) {
  const beforeClusters = activeClusterNames();
  let topologyChanged = false;
  let clusterChanged = false;
  let geometryChanged = false;

  for (const event of events) {
    recentChanges.push(Date.now());
    pushFeed(event);

    if (event.type === "token_added") {
      addToken(event.token, true);
      topologyChanged = true;
      continue;
    }

    if (event.type === "token_updated") {
      const result = updateToken(event.token, true);
      topologyChanged ||= result.topologyChanged;
      clusterChanged ||= result.clusterChanged;
      geometryChanged ||= result.geometryChanged;
      continue;
    }

    if (event.type === "token_retired") {
      topologyChanged ||= retireToken(event.token, event.reason);
    }
  }

  const afterClusters = activeClusterNames();
  const clusterSetChanged = !sameSet(beforeClusters, afterClusters);

  if (clusterSetChanged) {
    layoutScene({ refit: false, seedUnplaced: true, reheat: 0.16 });
  } else {
    refreshClusterVisuals();

    if (topologyChanged || clusterChanged) {
      configureSimulation(activeNodes(), 0.085);
    } else if (geometryChanged) {
      refreshCollision(0.03);
    }
  }

  updateStats();
}

app.ticker.add(() => {
  const now = performance.now();

  for (const [mint, node] of nodes.entries()) {
    if (node.retiringAt) {
      const progress = Math.min(1, (now - node.retiringAt) / 720);
      node.view.scale.set(Math.max(0.01, 1 - progress));
      node.view.alpha = 1 - progress;

      if (progress >= 1) {
        node.view.removeFromParent();
        node.view.destroy();
        nodes.delete(mint);
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
});

async function bootstrap() {
  const response = await fetch("/api/universe");
  if (!response.ok) {
    throw new Error(`Universe request failed: ${response.status}`);
  }

  const payload = await response.json();
  payload.tokens.forEach(token => addToken(token, false));
  layoutScene({ refit: true, seedUnplaced: true, reheat: 0.55 });
  updateStats();

  const stream = new EventSource("/api/events");

  stream.addEventListener("open", () => {
    streamStatus.className = "stream-status live";
    streamStatus.querySelector("span").textContent = "Live";
  });

  stream.addEventListener("error", () => {
    streamStatus.className = "stream-status error";
    streamStatus.querySelector("span").textContent = "Reconnecting";
  });

  stream.addEventListener("universe_delta", message => {
    const delta = JSON.parse(message.data);
    applyDelta(delta.events);
  });
}

const resizeObserver = new ResizeObserver(() => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => {
    if (!nodes.size) return;
    layoutScene({ refit: true, seedUnplaced: false, reheat: 0.14 });
  }, 180);
});

resizeObserver.observe(stageElement);
setInterval(updateStats, 1000);

setInterval(async () => {
  if (!selectedMint) return;

  try {
    const response = await fetch(`/api/token/${encodeURIComponent(selectedMint)}`);
    if (!response.ok) return;

    const token = await response.json();
    const node = nodes.get(token.mint);
    if (node) node.token = token;
    renderDetail(token);
  } catch (_) {
    // The live stream remains authoritative; detail refresh is best-effort only.
  }
}, 5000);

bootstrap().catch(error => {
  console.error(error);
  streamStatus.className = "stream-status error";
  streamStatus.querySelector("span").textContent = "Offline";
});
