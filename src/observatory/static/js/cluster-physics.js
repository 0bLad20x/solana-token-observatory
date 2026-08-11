import { forceCollide, forceSimulation, forceX, forceY } from "https://cdn.jsdelivr.net/npm/d3-force@3.0.0/+esm";
import { quadtree } from "https://cdn.jsdelivr.net/npm/d3-quadtree@3.0.1/+esm";

const MIN_INFLUENCE_RADIUS = 96;
const INFLUENCE_MULTIPLIER = 10;
const TICKS_PER_FRAME = 1;
const MAX_TICKS = 80;
const MIN_TICKS = 12;
const STABLE_SPEED = 0.035;
const STABLE_FRAMES = 4;

function restoreFixed(node, previous) {
  if (previous.fx === undefined) delete node.fx;
  else node.fx = previous.fx;
  if (previous.fy === undefined) delete node.fy;
  else node.fy = previous.fy;
}

function nodesNearPoints(nodes, points) {
  const selected = new Set();
  if (!nodes.length || !points.length) return selected;

  const tree = quadtree(nodes, node => node.x, node => node.y);
  for (const point of points) {
    const influence = Math.max(
      MIN_INFLUENCE_RADIUS,
      (point.radius || 0) * INFLUENCE_MULTIPLIER,
    );
    const x0 = point.x - influence;
    const y0 = point.y - influence;
    const x1 = point.x + influence;
    const y1 = point.y + influence;

    tree.visit((quad, left, top, right, bottom) => {
      if (left > x1 || right < x0 || top > y1 || bottom < y0) return true;
      if (quad.length) return false;

      let leaf = quad;
      while (leaf) {
        const node = leaf.data;
        const dx = node.x - point.x;
        const dy = node.y - point.y;
        const reach = influence + node.radius;
        if (dx * dx + dy * dy <= reach * reach) selected.add(node);
        leaf = leaf.next;
      }
      return false;
    });
  }
  return selected;
}

export function createBoundsForce(getBounds) {
  let nodes = [];

  function force() {
    const bounds = getBounds();
    for (const node of nodes) {
      const radius = node.radius + bounds.padding;
      const nextX = node.x + node.vx;
      const nextY = node.y + node.vy;
      if (nextX < radius) node.vx += (radius - nextX) * 0.45;
      else if (nextX > bounds.width - radius) {
        node.vx -= (nextX - (bounds.width - radius)) * 0.45;
      }
      if (nextY < radius) node.vy += (radius - nextY) * 0.45;
      else if (nextY > bounds.height - radius) {
        node.vy -= (nextY - (bounds.height - radius)) * 0.45;
      }
    }
  }

  force.initialize = current => {
    nodes = current;
  };
  return force;
}

export class LocalClusterPhysics {
  constructor({ getNodes, groupKeyFor, centerFor, getBounds, gap }) {
    this.getNodes = getNodes;
    this.groupKeyFor = groupKeyFor;
    this.centerFor = centerFor;
    this.getBounds = getBounds;
    this.gap = gap;
    this.active = null;
  }

  relax({ points, anchors = [], movers = [] }) {
    this.stop();

    const nodes = this.getNodes();
    if (!nodes.length || !points.length) return;

    const anchorSet = new Set(anchors);
    const moverSet = new Set(movers);
    const mobile = nodesNearPoints(nodes, points);
    for (const node of anchors) mobile.add(node);
    for (const node of movers) mobile.add(node);

    const temporaryFixed = new Map();
    for (const node of nodes) {
      if (node.dragging) {
        node.fx = node.dragX;
        node.fy = node.dragY;
        continue;
      }
      if (!mobile.has(node) || anchorSet.has(node)) {
        temporaryFixed.set(node, { fx: node.fx, fy: node.fy });
        node.fx = node.x;
        node.fy = node.y;
      }
    }

    const targetX = node => this.centerFor(this.groupKeyFor(node))?.x ?? node.x;
    const targetY = node => this.centerFor(this.groupKeyFor(node))?.y ?? node.y;
    const strength = node => {
      if (!mobile.has(node) || anchorSet.has(node)) return 0;
      return moverSet.has(node) ? 0.075 : 0.012;
    };

    const simulation = forceSimulation(nodes)
      .stop()
      .velocityDecay(0.42)
      .alphaDecay(0.055)
      .force("x", forceX(targetX).strength(strength))
      .force("y", forceY(targetY).strength(strength))
      .force(
        "collide",
        forceCollide(node => node.radius + this.gap).strength(0.96).iterations(2),
      )
      .force("bounds", createBoundsForce(this.getBounds))
      .alpha(0.7);

    this.active = {
      simulation,
      nodes,
      mobile,
      temporaryFixed,
      ticks: 0,
      stableFrames: 0,
    };
  }

  step() {
    const active = this.active;
    if (!active) return false;

    for (const node of active.nodes) {
      if (!node.dragging) continue;
      node.fx = node.dragX;
      node.fy = node.dragY;
    }
    for (let index = 0; index < TICKS_PER_FRAME; index += 1) {
      active.simulation.tick();
    }
    active.ticks += TICKS_PER_FRAME;

    let maxSpeed = 0;
    for (const node of active.mobile) {
      maxSpeed = Math.max(maxSpeed, Math.hypot(node.vx || 0, node.vy || 0));
    }
    if (active.ticks >= MIN_TICKS && maxSpeed < STABLE_SPEED) active.stableFrames += 1;
    else active.stableFrames = 0;

    if (active.ticks >= MAX_TICKS || active.stableFrames >= STABLE_FRAMES) {
      this.stop();
    }
    return true;
  }

  beginDrag(node, x, y) {
    node.dragging = true;
    node.dragX = x;
    node.dragY = y;
    node.dragNeighborhoodX = x;
    node.dragNeighborhoodY = y;
    node.x = x;
    node.y = y;
    this.relax({ points: [node], anchors: [node] });
  }

  moveDrag(node, x, y) {
    if (!node.dragging) return;
    node.dragX = x;
    node.dragY = y;
    node.x = x;
    node.y = y;
    if (this.active) {
      node.fx = x;
      node.fy = y;
    }
    const neighborhoodShift = Math.hypot(
      x - node.dragNeighborhoodX,
      y - node.dragNeighborhoodY,
    );
    if (!this.active || neighborhoodShift >= MIN_INFLUENCE_RADIUS / 3) {
      node.dragNeighborhoodX = x;
      node.dragNeighborhoodY = y;
      this.relax({ points: [node], anchors: [node] });
    }
  }

  endDrag(node) {
    if (!node.dragging) return;
    this.stop();
    node.dragging = false;
    delete node.dragX;
    delete node.dragY;
    delete node.dragNeighborhoodX;
    delete node.dragNeighborhoodY;
    delete node.fx;
    delete node.fy;
    this.relax({ points: [node] });
  }

  stop() {
    const active = this.active;
    if (!active) return;

    active.simulation.stop();
    for (const [node, previous] of active.temporaryFixed.entries()) {
      restoreFixed(node, previous);
    }
    for (const node of active.nodes) {
      node.vx = 0;
      node.vy = 0;
    }
    this.active = null;
  }
}
