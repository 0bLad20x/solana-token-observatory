import { quadtree } from "https://cdn.jsdelivr.net/npm/d3-quadtree@3.0.1/+esm";

const MAX_STEPS = 80;
const MAX_RETURN_STEPS = 120;
const MIN_STEPS = 6;
const OVERLAP_ITERATIONS = 3;
const ALPHA_DECAY = 0.82;
const POSITION_EPSILON = 0.035;
const CENTER_PULL = 0.018;
const MAX_CENTER_STEP = 1.25;

function stableDirection(a, b) {
  const text = `${a.token?.mint || "a"}:${b.token?.mint || "b"}`;
  let value = 2166136261;
  for (let index = 0; index < text.length; index += 1) {
    value ^= text.charCodeAt(index);
    value = Math.imul(value, 16777619);
  }
  const angle = (value >>> 0) / 0xffffffff * Math.PI * 2;
  return { x: Math.cos(angle), y: Math.sin(angle) };
}

export class ClusterLayout {
  constructor({ getNodes, groupKeyFor, centerFor, gap }) {
    this.getNodes = getNodes;
    this.groupKeyFor = groupKeyFor;
    this.centerFor = centerFor;
    this.gap = gap;
    this.active = new Map();
  }

  settle(groupKey, { seeds, anchors = [] }) {
    const nodes = this.getNodes(groupKey);
    if (!nodes.length || !seeds.length) return;

    const state = this.active.get(groupKey) || {
      groupKey,
      mobile: new Set(),
      anchors: new Set(),
      dragged: null,
      dragHomes: null,
      returnHomes: null,
      alpha: 1,
      steps: 0,
      stableSteps: 0,
    };

    for (const anchor of anchors) state.anchors.add(anchor);
    this._wake(state, nodes, seeds);
    state.alpha = Math.max(state.alpha, 0.72);
    state.steps = 0;
    state.stableSteps = 0;
    this.active.set(groupKey, state);
  }

  constrain(node, x, y) {
    const center = this.centerFor(this.groupKeyFor(node));
    if (!center) return { x, y };

    const dx = x - center.x;
    const dy = y - center.y;
    const distance = Math.hypot(dx, dy);
    const limit = Math.max(0, center.radius - node.radius - this.gap);
    if (!distance || distance <= limit) return { x, y };

    const scale = limit / distance;
    return {
      x: center.x + dx * scale,
      y: center.y + dy * scale,
    };
  }

  beginDrag(node, x, y) {
    const groupKey = this.groupKeyFor(node);
    const point = this.constrain(node, x, y);
    node.dragging = true;
    node.dragX = point.x;
    node.dragY = point.y;
    node.x = point.x;
    node.y = point.y;
    this.settle(groupKey, { seeds: [node], anchors: [node] });
    const state = this.active.get(groupKey);
    state.dragged = node;
    state.returnHomes = null;
    state.dragHomes = new Map();
    this._captureHomes(state);
  }

  moveDrag(node, x, y) {
    if (!node.dragging) return;
    const groupKey = this.groupKeyFor(node);
    const point = this.constrain(node, x, y);
    node.dragX = point.x;
    node.dragY = point.y;
    node.x = point.x;
    node.y = point.y;

    const nodes = this.getNodes(groupKey);
    const state = this.active.get(groupKey);
    if (!state) {
      this.beginDrag(node, point.x, point.y);
      return;
    }
    this._wake(state, nodes, [node]);
    this._captureHomes(state);
    state.alpha = Math.max(state.alpha, 0.78);
    state.steps = 0;
    state.stableSteps = 0;
  }

  endDrag(node) {
    if (!node.dragging) return;
    const groupKey = this.groupKeyFor(node);
    node.dragging = false;
    delete node.dragX;
    delete node.dragY;

    const state = this.active.get(groupKey);
    if (!state) {
      this.settle(groupKey, { seeds: [node] });
      return;
    }
    state.dragged = null;
    state.returnHomes = state.dragHomes;
    state.dragHomes = null;
    state.anchors.delete(node);
    state.alpha = 1;
    state.steps = 0;
    state.stableSteps = 0;
    this._wake(state, this.getNodes(groupKey), [node]);
  }

  stop() {
    this.active.clear();
  }

  step() {
    if (!this.active.size) return null;
    const moved = new Set();

    for (const [groupKey, state] of this.active.entries()) {
      const nodes = this.getNodes(groupKey);
      const available = new Set(nodes);
      for (const node of state.mobile) {
        if (!available.has(node)) state.mobile.delete(node);
      }
      for (const node of state.anchors) {
        if (!available.has(node)) state.anchors.delete(node);
      }
      if (!state.mobile.size) {
        this.active.delete(groupKey);
        continue;
      }

      let maximumMove = 0;
      if (state.dragged?.dragging) {
        const point = this.constrain(state.dragged, state.dragged.dragX, state.dragged.dragY);
        maximumMove = Math.max(
          maximumMove,
          Math.hypot(state.dragged.x - point.x, state.dragged.y - point.y),
        );
        state.dragged.x = point.x;
        state.dragged.y = point.y;
        moved.add(state.dragged);
      } else {
        maximumMove = Math.max(maximumMove, this._compact(state, moved));
      }

      for (let iteration = 0; iteration < OVERLAP_ITERATIONS; iteration += 1) {
        maximumMove = Math.max(
          maximumMove,
          this._resolveOverlaps(state, nodes, moved),
          this._contain(state, moved),
        );
      }

      state.steps += 1;
      state.alpha *= ALPHA_DECAY;
      if (state.steps >= MIN_STEPS && maximumMove < POSITION_EPSILON) {
        state.stableSteps += 1;
      } else {
        state.stableSteps = 0;
      }

      const stepLimit = state.returnHomes ? MAX_RETURN_STEPS : MAX_STEPS;
      if (!state.dragged && (state.steps >= stepLimit || state.stableSteps >= 3)) {
        if (state.returnHomes) {
          let restored = true;
          for (const [node, home] of state.returnHomes.entries()) {
            if (Math.abs(node.radius - home.radius) > 0.001) {
              restored = false;
              continue;
            }
            node.x = home.x;
            node.y = home.y;
            moved.add(node);
          }
          if (!restored) {
            state.returnHomes = null;
            state.steps = 0;
            state.stableSteps = 0;
            state.alpha = 0.72;
            continue;
          }
        }
        this.active.delete(groupKey);
      }
    }

    return moved;
  }

  _wake(state, nodes, seeds) {
    if (!nodes.length) return;
    const largestRadius = Math.max(...nodes.map(node => node.radius));
    const tree = quadtree(nodes, node => node.x, node => node.y);

    for (const seed of seeds) {
      const seedRadius = seed.radius || 0;
      const reach = Math.max(32, seedRadius * 2 + largestRadius * 2 + this.gap);
      const x0 = seed.x - reach;
      const y0 = seed.y - reach;
      const x1 = seed.x + reach;
      const y1 = seed.y + reach;

      tree.visit((quad, left, top, right, bottom) => {
        if (left > x1 || right < x0 || top > y1 || bottom < y0) return true;
        if (quad.length) return false;

        let leaf = quad;
        while (leaf) {
          const node = leaf.data;
          if (Math.hypot(node.x - seed.x, node.y - seed.y) <= reach + node.radius) {
            state.mobile.add(node);
          }
          leaf = leaf.next;
        }
        return false;
      });
    }
  }

  _captureHomes(state) {
    if (!state.dragHomes) return;
    for (const node of state.mobile) {
      if (!state.dragHomes.has(node)) {
        state.dragHomes.set(node, { x: node.x, y: node.y, radius: node.radius });
      }
    }
  }

  _compact(state, moved) {
    const center = this.centerFor(state.groupKey);
    if (!center) return 0;

    let maximumMove = 0;
    let homesPending = 0;
    for (const node of state.mobile) {
      if (state.anchors.has(node) || node.dragging || node.retiringAt) continue;
      const home = state.returnHomes?.get(node);
      const targetX = home?.x ?? center.x;
      const targetY = home?.y ?? center.y;
      const dx = targetX - node.x;
      const dy = targetY - node.y;
      const distance = Math.hypot(dx, dy);
      if (home && distance < 0.08) {
        node.x = targetX;
        node.y = targetY;
        continue;
      }
      if (!distance) continue;
      const step = home
        ? Math.min(12, distance * 0.28)
        : Math.min(MAX_CENTER_STEP, distance * CENTER_PULL * state.alpha);
      node.x += dx / distance * step;
      node.y += dy / distance * step;
      maximumMove = Math.max(maximumMove, step);
      moved.add(node);
      if (home) homesPending += 1;
    }
    if (state.returnHomes && homesPending === 0) state.returnHomes = null;
    return maximumMove;
  }

  _resolveOverlaps(state, nodes, moved) {
    if (nodes.length < 2) return 0;

    const largestRadius = Math.max(...nodes.map(node => node.radius));
    const tree = quadtree(nodes, node => node.x, node => node.y);
    const order = new Map(nodes.map((node, index) => [node, index]));
    let maximumMove = 0;

    for (const node of [...state.mobile]) {
      const reach = node.radius + largestRadius + this.gap;
      tree.visit((quad, left, top, right, bottom) => {
        if (
          left > node.x + reach || right < node.x - reach
          || top > node.y + reach || bottom < node.y - reach
        ) return true;
        if (quad.length) return false;

        let leaf = quad;
        while (leaf) {
          const other = leaf.data;
          if (
            other !== node
            && (!state.mobile.has(other) || order.get(node) < order.get(other))
          ) {
            maximumMove = Math.max(
              maximumMove,
              this._separate(state, node, other, moved),
            );
          }
          leaf = leaf.next;
        }
        return false;
      });
    }
    return maximumMove;
  }

  _separate(state, a, b, moved) {
    const minimum = a.radius + b.radius + this.gap;
    let dx = b.x - a.x;
    let dy = b.y - a.y;
    let distance = Math.hypot(dx, dy);
    if (distance >= minimum) return 0;

    if (!distance) {
      const direction = stableDirection(a, b);
      dx = direction.x;
      dy = direction.y;
      distance = 1;
    }

    const fixedA = state.anchors.has(a) || a.dragging || a.retiringAt;
    const fixedB = state.anchors.has(b) || b.dragging || b.retiringAt;
    if (fixedA && fixedB) return 0;

    const homes = state.dragHomes || state.returnHomes;
    if (homes) {
      if (!homes.has(a)) homes.set(a, { x: a.x, y: a.y, radius: a.radius });
      if (!homes.has(b)) homes.set(b, { x: b.x, y: b.y, radius: b.radius });
    }
    state.mobile.add(a);
    state.mobile.add(b);
    const overlap = (minimum - distance + 0.001) * 1.08;
    const shareA = fixedA ? 0 : fixedB ? 1 : 0.5;
    const shareB = fixedB ? 0 : fixedA ? 1 : 0.5;
    const ux = dx / distance;
    const uy = dy / distance;

    if (shareA) {
      a.x -= ux * overlap * shareA;
      a.y -= uy * overlap * shareA;
      moved.add(a);
    }
    if (shareB) {
      b.x += ux * overlap * shareB;
      b.y += uy * overlap * shareB;
      moved.add(b);
    }
    return overlap * Math.max(shareA, shareB);
  }

  _contain(state, moved) {
    let maximumMove = 0;
    for (const node of state.mobile) {
      const point = this.constrain(node, node.x, node.y);
      const distance = Math.hypot(point.x - node.x, point.y - node.y);
      if (!distance) continue;
      node.x = point.x;
      node.y = point.y;
      maximumMove = Math.max(maximumMove, distance);
      moved.add(node);
    }
    return maximumMove;
  }
}
