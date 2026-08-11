# Frontend Spatial Model — V3 Reset

## Status

**Authority:** V3 spatial behavior and `ViewSpec` boundaries  
**Parent authority:** `docs/FRONTEND_OBSERVATORY.md`  
**Branch:** `agent/generic-bubble-physics-v3`  
**Checkpoint:** both live-physics attempts failed browser validation; V3-A is reset to a static semantic-zoom proof

V3-B remains blocked until this reduced V3-A is readable and stable in the real browser.

## 1. Browser evidence overrides the former contract

The browser test with roughly 1,400 Pump.fun tokens disproved the assumption that all active tokens can be presented simultaneously as freely draggable, colliding bubbles.

Observed failures:

- raw launchpad variants could create separate groups while receiving the same color;
- newly added nodes did not enlarge their group domain;
- a group that could not find free space fell back to the viewport center;
- a logarithmic, capped radius made materially different market caps look alike;
- fast drag propagated displacement through large contact chains;
- pointer release and return-to-home were not reliable browser invariants;
- rendering every token at overview scale produced density without readable information.

The first velocity-based solver and the second positional constraint solver are both rejected. Their code must not be revived through further parameter tuning.

## 2. First principle

```text
Movement is allowed only when it communicates data.
Interaction is allowed only when it changes analytical context.
Containment must be structural, not simulated.
```

User drag had no analytical meaning. It is removed.

Collision physics had no durable product responsibility. It is removed.

The new V3-A proves a smaller proposition:

```text
large population
      ↓
aggregate overview
      ↓ click launchpad
bounded token detail
```

## 3. Two deterministic levels

### Overview

The overview renders one aggregate bubble per canonical launchpad.

```text
position    = stable equal slot
area        = active token count relative to the largest group
color       = launchpad
label       = launchpad + exact count
interaction = focus this launchpad
```

No individual token exists in the overview. A Pump.fun population of 1,400 tokens is therefore one truthful aggregate, not 1,400 illegible marks.

### Launchpad focus

The focus renders a viewport-derived budget of the highest-market-cap tokens in one launchpad.

```text
position    = stable equal slot
area        = market cap
label       = symbol for sufficiently large marks
interaction = select token
```

The toolbar always states `shown / total`. Hidden tokens are not silently implied to be visible.

The visible budget is derived from viewport area and bounded to keep marks selectable. Ranking is deterministic:

```text
market_cap descending
mint ascending as tie-breaker
```

Re-entering the focus or resizing performs an explicit refit. Ordinary SSE updates do not reorder the visible set.

## 4. Size semantics

Circle area, not radius, represents the mapped value.

```text
radius ∝ sqrt(value / reference)
```

For token focus, the reference is the visible population's 95th percentile, bounded between $1M and $10M. This prevents a single extreme outlier from flattening the rest while preserving a clear area difference between $100k and $1M.

For overview, the reference is the largest launchpad count. A minimum display radius keeps small launchpads clickable; the exact count remains authoritative in the label.

## 5. Structural invariants

1. Every item owns one immutable slot until explicit refit.
2. The rendered bubble is always smaller than its slot.
3. Slots never overlap.
4. A token focus contains exactly one canonical `groupKey`.
5. There is no drag state, velocity, collision solver, attraction, group-domain fallback or free-coordinate search.
6. An idle scene executes no spatial work.

These properties make cross-cluster drift impossible by construction.

## 6. Live semantics

### Ordinary update

Token data is replaced. If the token is visible and market cap changed, its radius eases toward the new value at the same slot center. No other token moves.

### Added token

Overview count updates in place. A focused visible set is not reordered mid-session; the next explicit focus/refit recomputes its deterministic ranking.

### Group change

The token immediately leaves a focus it no longer belongs to. Overview counts update. No spatial transition is simulated between groups.

### Retirement

A visible token turns red, collapses and leaves its slot empty. The vacancy is not physically filled. The next explicit refit compacts the static presentation.

### Resize or focus change

This is an explicit analytical context change and may recompute all slots once.

## 7. Visual semantics

```text
overview bubble area = population count
token bubble area    = market cap
launchpad accent     = grouping context
cyan stroke          = selection
red                  = retirement
symbol text          = identity on readable marks
motion               = mapped radius or exit only
```

Freshness, liquidity and generic update activity remain outside the active visual channels.

## 8. Implementation boundary

```text
bubble-layout.js
    equal non-overlapping slots
    viewport detail budget
    percentile reference
    area-to-radius mapping

universe.js
    Pixi rendering
    overview/focus navigation
    selection and finite animations
```

The layout uses D3 hierarchy packing only to allocate equal stable slots. There is no force or quadtree dependency.

## 9. V3-A acceptance

V3-A passes only if the real browser proves all of the following:

```text
overview          → one readable aggregate per launchpad
focus             → one launchpad only
idle              → no movement
ordinary update   → only the changed radius moves
retirement        → red collapse, then a stable empty slot
market-cap scale  → $100k and $1M are visibly distinct
membership        → no token can appear in another launchpad focus
density           → shown / total remains explicit
```

## 10. V3-B and later work

V3-B does not begin until this contract passes browser validation.

Later work may add another grouping preset, search/filter, deeper progressive disclosure or a true analytical projection. It must not reintroduce free drag or live collision merely to make the view feel dynamic.

Flow, Tree, Network, LLM Cohorts and Discovery Provenance remain outside V3-A.
