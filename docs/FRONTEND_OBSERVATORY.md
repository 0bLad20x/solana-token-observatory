# Frontend Observatory

## Status

**Authority:** frontend product, interaction and implementation direction  
**Scope:** read-only visual and analytical consumer of operational token data  
**Current checkpoint:** V0–V2 merged; V3-A implementation awaits real-browser validation
**V3 spatial authority:** `docs/FRONTEND_SPATIAL_MODEL.md`

This document defines the durable product and architecture principles of the Token Observatory. Slice-specific spatial behavior is refined in the V3 spatial contract instead of accumulating special-case rules here.

## 1. Product definition

The frontend is not a trading terminal with an attached chatbot.

It is a **visual token observatory** for observing, selecting, comparing and interpreting the creation, development and retirement of freshly discovered Solana tokens.

The core interaction is:

```text
SEE
 ↓
SELECT
 ↓
COMPARE
 ↓
INTERPRET
 ↓
REFINE
 ↓
DISCOVER
```

The primary object of the interface is the data space, not a table. Tables remain useful for precise values and drill-down, but they are not the main navigation model.

## 2. System boundary

The Observatory is a read-only downstream consumer.

```text
Operational Core
Discovery -> Jupiter Monitoring -> Persistence -> Lifecycle
                                      │
                                      ▼
                              Read-only projection
                                      │
                         ┌────────────┴────────────┐
                         ▼                         ▼
                    Visualization             LLM Analyst
```

Frontend and analyst may read operational data. They may not mutate:

- `tracking_enabled`;
- priority;
- lifecycle state;
- collector-owned observation state;
- lifecycle thresholds or decision semantics.

Lifecycle v0.1 remains independent and deterministic.

## 3. First principles

### 3.1 Data space first

The visual workspace should dominate the interface. Navigation, cards, controls and analyst UI support the data space rather than compete with it.

Target: roughly 80% of useful desktop area should remain available for visual investigation whenever practical.

### 3.2 Progressive disclosure

```text
LEVEL 1  form / position / movement / cluster
   ↓
LEVEL 2  essential metrics
   ↓
LEVEL 3  token history / lifecycle / derived metrics
   ↓
LEVEL 4  raw evidence / detailed analysis / LLM investigation
```

The system must remain understandable with thousands of tokens visible without requiring the user to read thousands of rows.

### 3.3 Spatial continuity

A token has visual identity inside a view.

A new observation must not cause unrelated tokens to globally reorganize unless the active view explicitly represents a dimension or population that changed.

```text
one token changes
      ↓
primarily that token and its necessary local context change visually
```

### 3.4 Delta locality

Live updates are local visual events.

```text
TOKEN_ADDED   -> enter the scene
TOKEN_UPDATED -> update or pulse the affected token
TOKEN_RETIRED -> explicit retirement transition
```

A delta must not feel like a full-screen refresh.

### 3.5 Motion has meaning

Animation is semantic, not decorative.

```text
enter       = token becomes visible in this population
move        = represented position or population changed
resize      = represented size value changed
pulse       = one relevant new delta
selection   = stable halo / focus
retire      = collapse, fade or transfer out of active population
```

No permanent screensaver-style motion.

### 3.6 Stable visual semantics

Color, shape, halo, line and motion have consistent meanings across views.

Renderers consume the visual contract. They do not invent category colors independently.

### 3.7 Visualizations are projections

Bubble maps, trees, radar charts, flow views and timelines are projections of the same underlying data. They do not own business truth.

### 3.8 Vertical delivery

Every implementation slice should leave a visible, testable improvement in the running frontend.

Avoid long horizontal infrastructure phases that produce no observable product behavior.

## 4. Truth model

The interface distinguishes three epistemic levels.

### SYSTEM TRUTH

Directly observed or deterministically persisted facts:

- mint addresses;
- Jupiter snapshots;
- timestamps;
- lifecycle result and reason;
- current measurements;
- later: persisted discovery provenance.

### ANALYSIS

Deterministically derived values:

- growth rates;
- medians;
- cohort membership;
- distributions;
- threshold crossings;
- comparisons;
- derived trajectories.

### LLM HYPOTHESIS

Interpretive analytical objects:

- hypotheses;
- possible explanations;
- suggested comparisons;
- temporary groupings;
- proposed investigation directions.

LLM interpretation must never be rendered as system truth.

## 5. Design language

The visual DNA combines:

- Bubblemaps-style spatial simplicity;
- Arkham-style investigative workspace;
- the speed and density of modern Solana terminals;
- memecoin immediacy and token personality;
- an LLM-native analytical layer.

The system chrome stays calm and professional while the market data itself may remain visually chaotic and expressive.

```text
CALM SYSTEM
    containing
CHAOTIC MARKET
```

### 5.1 Base palette

```text
--bg              #080B14
--surface         #0F1420
--surface-raised  #151B2A
--border          #252C3D

--text-primary    #F3F5F8
--text-secondary  #929BAD
--text-muted      #626C7E
```

### 5.2 Solana accents

```text
--sol-purple      #9945FF
--sol-cyan        #14F1D9
```

Purple/cyan may be used for brand-level emphasis, active selection or transitions, but not as a default fill for every object.

### 5.3 Semantic colors

```text
--positive        #3DDC97   surviving / constructive change
--destructive     #FF5C77   actual destructive event / retirement
--warning         #FFB454   warning / uncertainty
--analyst         #B77CFF   LLM interpretation
--selection       #49D9FF   user selection / interactive focus
--inactive        #5E6678   inactive / dead / background population
```

Rules:

- green is not generic decoration;
- red is reserved for actual destructive state or event;
- purple means analyst/interpretation when used semantically;
- cyan means selection/interaction;
- grey means inactive/background;
- arbitrary hash-to-color category generation is not the default design mechanism.

### 5.4 Shape and state

Status should not depend on color alone.

```text
○  active
◉  signal / emphasized
◎  watched / selected context
×  deactivated
◇  analytical / LLM-created cohort
```

Exact glyphs may evolve, but the principle of redundant coding through form + color + text remains.

### 5.5 Source identity

Discovery source should later be recognizable through a subtle, constant secondary encoding such as a ring, chip or small marker rather than large logos.

This capability is blocked until discovery provenance is persistently available.

## 6. Live mode contract

The backend separates initial state from SSE deltas. The frontend must preserve that distinction visually.

### Bootstrap

```text
load current universe
      ↓
calculate initial layout
      ↓
stabilize
      ↓
enter LIVE mode
```

### Ordinary live delta

A normal SSE update must not trigger global force reheating or a full repack.

This behavior was validated and merged in V2.

### New token

A new token enters the represented population locally. The exact local physics is defined by the active spatial model and `ViewSpec`.

### Updated token

Only visual channels controlled by changed values should update.

Examples:

- if Market Cap controls radius, the bubble may resize;
- if Market Cap does not control geometry, the bubble should not move merely because Market Cap changed;
- a relevant change may pulse once.

### Retired token

Retirement is a visible event. The node may collapse, fade or later transfer toward a retirement/graveyard representation.

### Resize / View change

Viewport resize or an explicit ViewSpec switch may perform a controlled global refit. Ordinary live deltas may not use the same global behavior.

## 7. ViewSpec

A view is described by data-to-visual mappings rather than being hard-coded into one renderer.

Minimal conceptual contract:

```json
{
  "type": "bubble",
  "layout": "cluster",
  "group": "launchpad",
  "size": "market_cap",
  "color": null,
  "x": null,
  "y": null
}
```

Projection example:

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

Initial supported mappings remain deliberately small and explicit. V3 defines how grouping, size and positional constraints interact with generic physics in `docs/FRONTEND_SPATIAL_MODEL.md`.

## 8. Current application structure

```text
src/
├── frontend.py
└── observatory/
    ├── __init__.py
    ├── app.py
    ├── data.py
    └── static/
        ├── index.html
        ├── styles.css
        └── js/
            ├── app.js
            ├── cluster-physics.js
            ├── state.js
            ├── universe.js
            ├── view-spec.js
            └── theme.js
```

Responsibilities:

```text
frontend.py       tiny executable entry point
app.py            FastAPI, HTTP and SSE boundary
data.py           read-only PostgreSQL projections
app.js            application bootstrap and wiring
cluster-physics.js finite local D3 cluster relaxation
state.js          token state, selection, active view, deltas
universe.js       Pixi rendering, animation and pointer interaction
view-spec.js      supported mappings and presets
theme.js          semantic visual tokens
```

New modules are introduced only when a real responsibility appears.

When LLM integration becomes real, likely additions are limited initially to:

```text
observatory/analyst.py
observatory/tools.py
static/js/analyst.js
```

## 9. Backend contract

Current minimal endpoints:

```text
GET /api/health
GET /api/universe
GET /api/token/{mint}
GET /api/events
```

`/api/universe` is bootstrap state.

`/api/events` is the live delta channel.

Current event classes:

```text
token_added
token_updated
token_retired
```

The payload may carry the complete current token projection for simplicity. The browser still applies the change locally rather than replacing the whole visual state.

## 10. LLM analyst model

The LLM is an analytical controller over bounded read-only tools, not a database authority and not a generic chat widget.

Two modes are planned.

### Interactive Analyst

```text
user question / visual selection
            ↓
          LLM
            ↓
     read-only tools
            ↓
 structured analytical object
            ↓
 answer + evidence + visual actions
```

### Freeflow Observer

A configurable periodic process may autonomously use the same read-only tools and emit findings without requiring an explicit user selection.

Cadence is runtime configuration, not part of this contract.

### Initial tool vocabulary

```text
observe()
query()
compare()
aggregate()
```

Tools expose bounded structured read-only data.

No arbitrary SQL tool and no arbitrary Python execution tool belongs to the initial analyst contract.

### Response shape

Conceptually:

```json
{
  "answer": "...",
  "facts": [],
  "derived": [],
  "hypotheses": [],
  "visual_actions": []
}
```

Possible visual actions:

```text
highlight mints
select cohort
change ViewSpec
open token
request comparison
```

The browser decides how approved action types are rendered. The LLM does not manipulate Pixi, DOM or SQL directly.

LLM credentials remain server-side in environment configuration.

## 11. Analyst UI pattern

The analyst should appear as an investigation layer, not as a generic chat sidebar.

Preferred object:

```text
ANALYSIS

Question
Evidence
Derived metrics
Hypothesis
Confidence
Actions
```

The persistent inspector may later switch context between:

```text
TOKEN
COHORT
ANALYST
```

## 12. Selection and navigation direction

Long-term navigation is population-first:

```text
Universe
  / Source
  / Cohort
  / Lifecycle State
  / Derived Population
```

Lasso selection, breadcrumbs, pinning and command palette are valuable future interaction primitives but are introduced only when an active slice needs them.

## 13. Known data gaps

### Discovery provenance

The core currently inserts discovered mints without persistently preserving which discovery source observed each mint and when.

Therefore the following cannot yet be represented truthfully:

- source-resolved discovery flow;
- discovery overlap between sources;
- source-specific discovery cohort history;
- exact token travel from source to Jupiter observation.

The frontend must not infer or fake provenance.

### Historical analysis

The database contains immutable `mint_snapshots`, but the current frontend API exposes only current token projection.

Token timelines, peak metrics, detailed trajectories and historical comparisons require bounded read-only history queries before those views are implemented.

## 14. Vertical execution plan

### V0 — Observatory contract — DONE

Established product, architecture, truth, design and delivery principles.

### V1 — Structural refactor + design system — DONE / MERGED

Delivered:

- minimal Observatory module split;
- semantic theme;
- independent FastAPI frontend;
- real browser/API validation with more than 1.500 tokens.

Merge checkpoint: PR #5.

### V2 — Stable Live Deltas — DONE / MERGED

Delivered and validated:

- bootstrap layout once;
- ordinary live deltas no longer globally reheat the population;
- local update/pulse;
- local entry;
- local retirement;
- explicit resize refit remains allowed.

Merge checkpoint: PR #6.

V2 deliberately stops before final Bubble Map physics.

### V3 — Generic Bubble Physics + ViewSpec — ACTIVE

Technical authority: `docs/FRONTEND_SPATIAL_MODEL.md`.

The central rule is:

```text
Cluster != hard-coded renderer category
Cluster = result of active ViewSpec
```

V3-R selected the existing D3/Pixi stack for V3-A: `forceCollide`, weak positional forces, quadtree neighborhood selection, temporary `fx/fy` constraints and a finite frame-bounded simulation. No new physics dependency is required.

V3 then establishes:

- generic collision;
- weak group attraction;
- local relaxation;
- radius growth/shrink in place;
- local vacancy closing;
- drag as a temporary user constraint;
- semantic movement only when group or positional mapping changes;
- at least two grouping configurations using the same renderer/physics.

### V4 — Thin LLM Analyst — LATER

Minimum useful slice:

- server-side analyst configuration;
- `POST /api/analyst`;
- at least two bounded read-only tools;
- one visible analyst object;
- one approved visual action;
- facts and hypotheses rendered as different truth levels.

A minimal Freeflow Observer may follow if the manual path is stable and must reuse the same analyst/tool boundary.

## 15. Merge checkpoints

Working slices merge when their narrow contract is validated. One long-lived frontend PR is explicitly avoided.

```text
PR #5  V0 + V1  Observatory foundation
PR #6  V2       Stable Live Deltas
PR #7  V3       Generic Physics + ViewSpec    active draft
```

The success criterion is a visible working improvement with a clear responsibility boundary, not completion of the whole Observatory vision.

## 16. Explicit non-goals of the current foundation

The current foundation does not require:

- full Cohort engine;
- Graveyard explorer;
- persisted LLM notebooks;
- autonomous long-running analyst workflows;
- arbitrary web search;
- arbitrary SQL or Python execution;
- radar charts;
- population trees;
- complete discovery flow;
- time scrubber;
- semantic zoom for 20k+ tokens;
- OHLC/time-bucket work;
- permanent LLM-generated lifecycle classifications.

These may be added vertically after their preceding contracts prove useful.

## 17. Validation principle

Each slice is validated through the real running frontend, not only static checks.

Minimum validation remains:

```text
Python compile check
JavaScript syntax check
read-only API smoke check
live SSE observation
visual verification in browser
```

The success criterion is not file count or abstraction depth. It is a stable, understandable, visibly working Observatory that can grow without turning the renderer, `app.js` or the backend into a new monolith.
