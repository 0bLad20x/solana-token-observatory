# Frontend Spatial Model — V3

## Status

**Authority scope:** generic Bubble Map physics and ViewSpec behavior for Observatory V3  
**Parent authority:** `docs/FRONTEND_OBSERVATORY.md`  
**Current branch:** `agent/generic-bubble-physics-v3`

This document defines the next spatial model after V2.

V2 solved one narrow problem: ordinary live deltas no longer reheat and repack the whole Universe. It intentionally did **not** define the final physics of a Bubble Map.

V3 now defines that physics together with the first real `ViewSpec` contract.

## 1. First principle

A cluster is **not** a hard-coded property of the renderer.

A cluster is the result of the active view.

```text
Token data
   +
ViewSpec
   ↓
group membership
radius / position constraints
visual semantics
   ↓
generic spatial model
```

Examples of valid grouping rules:

```text
group = launchpad
group = market-cap bucket
group = age bucket
group = lifecycle state
group = deterministic cohort
group = later temporary LLM cohort
```

The renderer must not contain a separate physics implementation for each grouping mode.

## 2. Why V2 stops where it does

Two extremes have already been observed.

### Global force field

```text
one live delta
   ↓
large force reheat
   ↓
many unrelated tokens move
```

Result: spatial memory is lost.

### Fully fixed coordinates

```text
one live delta
   ↓
only one token changes
   ↓
no local physical response
```

Result: the scene becomes rigid, vacancies remain open and bubbles no longer feel related.

V3 must implement the middle ground:

```text
GLOBAL STABILITY
      +
LOCAL ELASTICITY
```

## 3. Node model

Every rendered token node needs only the spatial state required by the active view.

Conceptually:

```text
Node
├── mint                 stable identity
├── token                current read-only projection
├── groupKey             result of ViewSpec grouping
├── radius               result of ViewSpec size mapping
├── x / y                current rendered position
├── targetX / targetY    optional semantic target
├── selected             UI state
├── pinned               optional user constraint
└── lifecycle animation  enter / retire / pulse state
```

The node does not own business truth. `groupKey`, `radius` and positional targets are derived from the active `ViewSpec`.

## 4. ViewSpec contract

V3 should keep `ViewSpec` deliberately small.

```json
{
  "type": "bubble",
  "layout": "cluster",
  "group": "launchpad",
  "size": "market_cap",
  "color": "group",
  "x": null,
  "y": null
}
```

A projection view may instead define axes:

```json
{
  "type": "bubble",
  "layout": "projection",
  "group": null,
  "size": "liquidity",
  "color": "lifecycle_state",
  "x": "age_seconds",
  "y": "market_cap"
}
```

V3 does **not** need an arbitrary expression language.

Supported mappings should be explicit and finite in `view-spec.js`. New mappings are added only when a real view requires them.

## 5. Grouping semantics

`group` answers only one question:

> Which population is this token currently attracted to in this view?

Initial useful groupings may include:

```text
launchpad
market_cap_tier
age_tier
```

Example market-cap tiers may be defined explicitly as a preset rather than through arbitrary user code:

```text
< 10k
10k–100k
>= 100k
```

Example age tiers:

```text
fresh
< 24h
24h–48h
>= 48h
```

Exact thresholds belong to the view preset, not to the renderer.

## 6. The only reasons a token should move

A token should not move merely because new data arrived.

Movement needs a semantic cause.

### 6.1 Radius changed

If the mapped size value changes:

```text
same group
same semantic position
radius grows or shrinks in place
nearby nodes yield locally
```

The token should not be assigned an unrelated free coordinate.

### 6.2 Group changed

If the active grouping rule changes the token's `groupKey`:

```text
old group
   ↓
visible transition
   ↓
new group
```

This is a legitimate A → B movement because the represented population actually changed.

### 6.3 Projection value changed

If `x` or `y` maps a value that changed, the target coordinate changes.

Movement is then analytically meaningful because position itself encodes data.

### 6.4 User drag

Dragging is an explicit temporary user constraint.

It must not silently change the token's `groupKey` or business state.

### 6.5 Explicit global refit

Viewport resize, ViewSpec change or a deliberate reset may perform a controlled global refit.

Ordinary SSE deltas may not.

## 7. Generic physics

The physical model should be produced from a few general forces rather than special-case relocation rules.

### Collision

Bubbles may not overlap beyond the allowed visual tolerance.

```text
minimum distance = radiusA + radiusB + gap
```

### Group attraction

Cluster layouts have a weak attraction toward their group's spatial region.

This force gives a population cohesion without requiring fixed coordinates.

### Local relaxation

A local geometry change should affect only the nearby neighborhood required to resolve the change.

```text
one bubble grows
   ↓
near neighbors yield
   ↓
local equilibrium
```

Far-away nodes retain their spatial memory.

### Vacancy closing

When a bubble shrinks or retires, the same weak local attraction should naturally close the nearby vacancy.

There should be no separate "find a hole" or "fill a hole" business rule.

### Drag constraint

While the user drags a bubble:

```text
dragged node follows pointer
nearby nodes obey collision
far-away population stays stable
```

After release, the node settles according to the active view.

## 8. Avoid special-case relocation

V3 explicitly rejects an architecture such as:

```text
if radius grew      -> search free coordinate
if token retired    -> run hole filler
if token added      -> search another free coordinate
if group changed    -> search destination coordinate
```

That approach accumulates exceptions and makes later ViewSpecs harder.

Preferred model:

```text
ViewSpec derives constraints
        +
small set of generic forces
        ↓
layout behavior emerges
```

## 9. Cluster centers are view state

Cluster centers are not durable token truth.

For a cluster layout they are temporary spatial anchors belonging to the active view.

Changing from:

```text
group = launchpad
```

to:

```text
group = market_cap_tier
```

may replace the cluster centers completely because the represented populations changed.

That global rearrangement is legitimate because the **view changed**, not because one token received a new SSE update.

## 10. Projection layouts

Cluster physics and projection physics share the same node/state model but use different positional constraints.

### Cluster layout

```text
position = emergent
forces = group attraction + collision + local relaxation
```

### Projection layout

```text
x target = scale(token[x field])
y target = scale(token[y field])
forces = target attraction + collision
```

A `ViewSpec` switch may therefore reuse the same renderer and state while changing only the constraint model.

## 11. Initial V3 vertical slice

V3 should remain small enough to validate in one real browser session.

### V3-A — generic cluster physics

Deliver:

- remove special-case free-coordinate relocation from the intended design;
- one generic local-elastic cluster model;
- radius changes grow/shrink in place;
- nearby collision response;
- vacancy closing through local attraction;
- drag support with local response;
- group transition only when `groupKey` actually changes;
- no return of global live breathing.

Visible success:

- the current Launchpad view feels physically connected without losing global spatial memory.

### V3-B — ViewSpec proof

Deliver:

- current Launchpad grouping as one preset;
- one genuinely different grouping preset, preferably `market_cap_tier` or `age_tier`;
- minimal visible preset switch;
- same renderer and physics engine for both.

Visible success:

- switching the view creates different populations without adding a second Bubble Map implementation.

A projection preset such as `Age × Market Cap` may follow in the same PR only if V3-A and V3-B are already stable. It is not required to prove the generic cluster model.

## 12. V3 acceptance criteria

V3 is successful when all of the following are observable:

```text
ordinary update
→ no global repack

radius growth
→ bubble grows where it is
→ immediate neighbors yield

radius shrink / retirement
→ local neighborhood closes the vacancy naturally

drag
→ dragged bubble follows pointer
→ nearby bubbles react
→ far-away population remains stable

group change
→ visible movement toward the new group
→ only because membership actually changed

ViewSpec switch
→ different grouping population
→ same renderer / same generic physics
```

## 13. Boundaries

V3 changes frontend spatial semantics only.

It must not change:

- PostgreSQL schema;
- collector behavior;
- Lifecycle v0.1;
- operational token state;
- backend write permissions.

No arbitrary SQL, arbitrary Python execution or LLM-controlled physics enters this slice.

## 14. Consequences for later work

Once V3 exists, later capabilities become simpler:

```text
Cohort view
→ produces groupKey
→ existing physics renders it

LLM temporary cohort
→ produces bounded temporary group membership
→ existing physics renders it

Lifecycle populations
→ produce groupKey
→ existing physics renders it

projection view
→ provides x/y targets
→ existing renderer transitions semantically
```

The objective is therefore not to perfect one Launchpad Bubble Map. It is to create one small spatial grammar that many later Observatory views can reuse.
