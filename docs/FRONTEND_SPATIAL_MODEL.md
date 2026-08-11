# Frontend Spatial Model — V3

## Status

**Authority scope:** generic Bubble Map physics and ViewSpec behavior for Observatory V3  
**Parent authority:** `docs/FRONTEND_OBSERVATORY.md`  
**Current branch:** `agent/generic-bubble-physics-v3`

V2 solved one narrow problem: ordinary live deltas no longer reheat and repack the whole Universe. It intentionally did **not** define the final physics of a Bubble Map.

V3 defines that reusable physics together with the first real `ViewSpec` contract.

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

Valid grouping rules may later include:

```text
group = launchpad
group = market-cap bucket
group = age bucket
group = lifecycle state
group = deterministic cohort
group = temporary LLM cohort
```

The renderer must not contain separate physics implementations for these grouping modes.

## 2. Why V2 stops where it does

Two undesirable extremes have already been observed.

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

V3 targets the middle ground:

```text
GLOBAL STABILITY
      +
LOCAL ELASTICITY
```

## 3. Node model

Every rendered token node carries only spatial state required by the active view.

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

V3 keeps `ViewSpec` deliberately small.

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

V3 does **not** introduce an arbitrary expression language. Supported mappings remain explicit and finite in `view-spec.js` and expand only when a real view requires them.

## 5. Grouping semantics

`group` answers one question:

> Which population is this token currently attracted to in this view?

Initial useful groupings may include:

```text
launchpad
market_cap_tier
age_tier
```

Example tiers belong to presets, not to the renderer:

```text
Market Cap
< 10k
10k–100k
>= 100k

Age
fresh
< 24h
24h–48h
>= 48h
```

Exact thresholds are view configuration.

## 6. The only reasons a token should move

A token should not move merely because new data arrived.

### 6.1 Radius changed

If the mapped size value changes:

```text
same group
same semantic position
radius grows or shrinks in place
nearby nodes yield locally
```

The token is not assigned an unrelated free coordinate.

### 6.2 Group changed

If the active grouping rule changes the token's `groupKey`:

```text
old group
   ↓
visible transition
   ↓
new group
```

This is legitimate A → B movement because represented population membership actually changed.

### 6.3 Projection value changed

If `x` or `y` maps a value that changed, the positional target changes. Movement is analytically meaningful because position itself encodes data.

### 6.4 User drag

Dragging is an explicit temporary user constraint. It must not silently change `groupKey` or business state.

### 6.5 Explicit global refit

Viewport resize, ViewSpec change or a deliberate reset may perform a controlled global refit. Ordinary SSE deltas may not.

## 7. Generic physics

The desired behavior should emerge from a few general constraints rather than special-case relocation rules.

### Collision

Bubbles may not overlap beyond an allowed visual tolerance.

```text
minimum distance = radiusA + radiusB + gap
```

### Group attraction

Cluster layouts have weak attraction toward their group's spatial region. This provides cohesion without requiring fixed coordinates.

### Local relaxation

A local geometry change affects only the neighborhood required to resolve that change.

```text
one bubble grows
   ↓
near neighbors yield
   ↓
local equilibrium
```

Far-away nodes retain spatial memory.

### Vacancy closing

When a bubble shrinks or retires, the same local attraction should naturally close nearby vacancy. There is no separate `fillHole()` business rule.

### Drag constraint

```text
dragged node follows pointer
nearby nodes obey collision
far-away population stays stable
```

After release, the node settles according to the active view.

## 8. Avoid special-case relocation

V3 rejects architectures such as:

```text
if radius grew      -> search free coordinate
if token retired    -> run hole filler
if token added      -> search another free coordinate
if group changed    -> custom relocation rule
```

Preferred model:

```text
ViewSpec derives constraints
        +
small set of generic forces
        ↓
layout behavior emerges
```

## 9. Cluster centers are view state

Cluster centers are not durable token truth. They are temporary spatial anchors belonging to the active view.

Changing from:

```text
group = launchpad
```

to:

```text
group = market_cap_tier
```

may replace cluster centers completely because the represented populations changed. That global rearrangement is legitimate because the **view changed**, not because one token received an SSE update.

## 10. Projection layouts

Cluster and projection layouts share the same node/state model but use different positional constraints.

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

A `ViewSpec` switch therefore reuses the renderer and state while changing the constraint model.

## 11. Research gate before implementation

V3-A must **not** begin by inventing another custom physics engine from scratch.

Before implementation, perform a short targeted research pass to determine whether established layout/physics mechanisms already provide the required behavior more simply and robustly.

Research should answer only implementation-relevant questions:

```text
1. Can the existing D3 force primitives express local elasticity without global reheating?
2. Can fixed / partially fixed nodes and bounded simulations preserve spatial memory?
3. What is the simplest reliable way to select a local neighborhood at ~1.5k+ nodes?
4. Do quadtree / spatial-grid approaches materially simplify local collision work?
5. Which circle-packing / overlap-removal approaches naturally support growth and vacancy closing?
6. How should drag constraints interact with collision and weak group attraction?
7. Can the current Pixi + D3 stack solve this cleanly without another dependency?
```

Evaluate candidate approaches against the actual V3 behavior, not against theoretical completeness:

```text
local delta       -> no global movement
radius growth     -> grow in place; neighbors yield
radius shrink     -> local vacancy can close
retirement        -> local population settles naturally
drag              -> local physical response
view/group change -> semantic transition allowed
population        -> remains practical around current 1.5k+ tokens
implementation    -> minimal state, minimal code, minimal dependencies
```

Decision rule:

> Prefer the smallest established mechanism that satisfies the observable V3 contract. Reuse the current D3/Pixi stack if it is sufficient. Add a dependency or custom algorithm only when a concrete gap is demonstrated.

The research output should be concise. Before substantial V3-A coding, record directly under **Research decision** below:

```text
selected mechanism
why it satisfies the V3 contract
main alternatives considered
why those alternatives were rejected
new dependency required? yes/no + reason
```

This is a **research gate**, not a separate research project.

### Research decision

Status: **PENDING V3-R**

This section is filled only after the targeted research pass. It becomes the implementation premise for V3-A.

## 12. Initial V3 vertical slice

### V3-R — Physics research gate — FIRST

Deliver:

- review established force, packing and local-relaxation options;
- identify the smallest viable mechanism for the V3 contract;
- prefer existing D3/Pixi capabilities where sufficient;
- document the selected approach and why obvious alternatives were rejected;
- no speculative framework or dependency expansion.

Visible result is not required for V3-R itself; it exists only to make V3-A smaller and more deliberate.

### V3-A — generic cluster physics

Deliver:

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

## 13. V3 acceptance criteria

V3 is successful when all of the following are observable:

```text
ordinary update
→ no global repack

radius growth
→ bubble grows where it is
→ immediate neighbors yield

radius shrink / retirement
→ local neighborhood closes vacancy naturally

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

In addition, the implementation must trace back to the V3-R research decision rather than an accumulated set of event-specific relocation rules.

## 14. Boundaries

V3 changes frontend spatial semantics only.

It must not change:

- PostgreSQL schema;
- collector behavior;
- Lifecycle v0.1;
- operational token state;
- backend write permissions.

No arbitrary SQL, arbitrary Python execution or LLM-controlled physics enters this slice.

## 15. Consequences for later work

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

The objective is not to perfect one Launchpad Bubble Map. It is to create one small spatial grammar that many later Observatory views can reuse.
