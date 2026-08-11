# Frontend Observatory

## Status

**Authority:** Frontend product, interaction and implementation direction  
**Scope:** read-only visual and analytical consumer of the operational token data  
**Current branch:** `agent/live-token-universe` / Draft PR #5

This document turns the frontend concept into an executable contract. It describes what the frontend is, which design semantics are stable, how live changes must behave, which architectural boundaries apply, and which vertical slices are currently in scope.

It is deliberately not a catalog of every future feature. New modules and abstractions are introduced only when a real responsibility exists.

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

The primary object of the interface is the data space, not a table.

Tables remain useful for precise values and drill-down. They are not the main navigation model.

## 2. System boundary

The frontend is a read-only downstream consumer.

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

The frontend and analyst may read operational data. They may not mutate:

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

A new observation must not cause unrelated tokens to globally reorganize unless the active view explicitly represents a dimension that changed.

```text
one token changes
      ↓
primarily that token changes visually
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
move        = represented dimension or population changed
pulse       = one relevant new delta
selection   = stable halo / focus
retire      = collapse, fade or transfer out of active population
```

No permanent screensaver-style motion.

### 3.6 Stable visual semantics

Color, shape, halo, line and motion have consistent meanings across views.

Renderers consume the visual contract. They do not invent category colors independently.

### 3.7 Visualizations are projections

Bubble maps, trees, radar charts, flow views and timelines are projections of the same underlying data.

They do not own business truth.

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

The palette is dark graphite/navy rather than pure black.

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

Solana-derived accent colors are used selectively, not as universal decoration.

```text
--sol-purple      #9945FF
--sol-cyan        #14F1D9
```

A purple/cyan gradient may be used for brand-level emphasis, active selection or transitions, but not as a default fill for every object.

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

## 6. Live mode visual contract

The current backend already separates initial state from SSE deltas. The frontend must preserve that semantic distinction visually.

### Bootstrap

```text
load current universe
      ↓
calculate initial layout once
      ↓
stabilize positions
      ↓
enter LIVE mode
```

### New token

Existing nodes remain stable. The new node enters locally and is inserted into the relevant spatial region.

A new token must not trigger a global refit or global force reheating.

### Updated token

Only visual channels controlled by changed values should update.

Example:

- if Market Cap controls radius, the affected bubble may resize;
- if Market Cap is not mapped to geometry, a Market Cap update must not move the bubble;
- a relevant change may pulse once;
- unrelated nodes remain visually stable.

### Retired token

Retirement is a visible event. The node may collapse, fade or transfer toward a retirement/graveyard representation.

The surrounding population should not immediately collapse into the empty space in a way that destroys spatial memory.

### Resize

Viewport resize may cause an explicit controlled refit. Live data deltas must not use the same global refit behavior.

## 7. ViewSpec

A view is described by data-to-visual mappings rather than being hard-coded into one renderer.

Minimal contract:

```json
{
  "type": "bubble",
  "layout": "projection",
  "x": "age_seconds",
  "y": "market_cap",
  "size": "liquidity",
  "color": "lifecycle_state",
  "group": null
}
```

The current launchpad force view becomes one possible preset rather than the architecture itself:

```json
{
  "type": "bubble",
  "layout": "cluster",
  "x": null,
  "y": null,
  "size": "market_cap",
  "color": "launchpad",
  "group": "launchpad"
}
```

Initial supported mappings should remain deliberately small and expand only when real views require them.

## 8. Initial application structure

The first structural refactor should create only responsibilities that already exist or are immediately being implemented.

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
state.js          token state, selection, active view, deltas
universe.js       Pixi/D3 rendering and local motion
view-spec.js      supported view mappings and presets
theme.js          semantic visual tokens
```

When LLM integration becomes real in the same draft, only then add:

```text
observatory/analyst.py
observatory/tools.py
static/js/analyst.js
```

No deeper directory hierarchy is justified yet.

## 9. Backend contract

The existing minimal endpoints remain useful:

```text
GET /api/health
GET /api/universe
GET /api/token/{mint}
GET /api/events
```

`/api/universe` is bootstrap state.

`/api/events` is the live delta channel.

The current event classes are sufficient for the first vertical slices:

```text
token_added
token_updated
token_retired
```

The event payload may carry the complete current token projection for simplicity. The frontend must still apply the update locally rather than replacing the whole visual state.

## 10. LLM analyst model

The LLM is an analytical controller over read-only tools, not a database authority and not a generic chat widget.

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

The cadence is runtime configuration, not part of this contract.

### Initial tool vocabulary

Use a few general primitives rather than one tool per analysis:

```text
observe()
query()
compare()
aggregate()
```

These tools must expose bounded, structured, read-only data.

No arbitrary SQL tool and no arbitrary Python execution tool is part of the initial analyst contract.

### LLM response shape

The LLM should return analytical objects rather than only chat text.

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

Possible visual actions include:

```text
highlight mints
select cohort
change ViewSpec
open token
request comparison
```

The browser decides how approved action types are rendered. The LLM does not manipulate Pixi, DOM or SQL directly.

### Configuration

LLM credentials remain server-side in environment configuration. No provider API key is exposed to JavaScript.

The first implementation should prefer a small provider boundary configured through environment variables rather than coupling the frontend to one vendor SDK.

## 11. Analyst UI pattern

The analyst should appear as an investigation layer, not as a ChatGPT-shaped sidebar.

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

The persistent inspector can later switch context between:

```text
TOKEN
COHORT
ANALYST
```

Longer-term analyst history may become notebook-like rather than one endless message thread.

## 12. Selection and navigation direction

The long-term navigation model is population-first:

```text
Universe
  / Source
  / Cohort
  / Lifecycle State
  / Derived Population
```

Lasso selection, breadcrumbs, pinning and command palette are valuable future interaction primitives.

They are not prerequisites for the first stable merge unless needed by the active vertical slice.

## 13. Known data gaps

### Discovery provenance

The current core inserts discovered mints without persistently preserving which discovery source observed each mint and when.

Therefore the following views cannot yet be implemented truthfully:

- source-resolved discovery flow;
- discovery overlap between sources;
- source-specific discovery cohort history;
- exact token travel from source to Jupiter observation.

This must be solved as a separate explicit core evidence contract. The frontend must not infer or fake provenance.

### Historical analysis

The database contains immutable `mint_snapshots`, but the current frontend API exposes only current token projection.

Token timelines, peak metrics, detailed trajectories and historical comparisons require bounded read-only history queries before those views are implemented.

## 14. Vertical execution plan

The active draft is developed in short vertical slices. Every slice should end with a visible running result.

### V0 — Observatory contract

Deliver:

- this document;
- milestone pointer;
- explicit design, motion, truth and scope contracts.

Visible product change: none. This slice exists to prevent architectural drift before code movement.

### V1 — Structural refactor + design system

Deliver:

- move backend into the minimal `observatory` responsibility split;
- split monolithic frontend state/rendering/theme responsibilities;
- preserve current endpoints and behavior;
- apply the semantic dark/Solana design tokens.

Visible result:

- same working Universe;
- calmer, consistent visual chrome;
- no arbitrary launchpad hash palette as the primary design system.

### V2 — Stable Live Universe

Deliver:

- bootstrap layout once;
- stop global force reheating for ordinary live deltas;
- local entry for new token;
- local visual update for changed token;
- explicit retirement animation;
- stable visual selection;
- preserve spatial memory with ~1,200 active tokens.

Visible result:

- the user can see which token changed without the whole universe contracting or expanding.

### V3 — Minimal ViewSpec

Deliver:

- `ViewSpec` state;
- current cluster map as a preset;
- at least one true projection preset, preferably `Age × Market Cap` with `Liquidity` as size;
- minimal visible controls or preset switcher.

Visible result:

- the same population can be viewed from two analytically distinct perspectives without rewriting the renderer.

### V4 — First LLM vertical slice

Deliver only after V1–V3 remain working.

Minimum useful slice:

- server-side analyst configuration;
- `POST /api/analyst`;
- two or more bounded read-only tools from the general vocabulary;
- one visible analyst object in the inspector;
- one approved visual action such as highlight/select;
- facts and hypotheses rendered as different truth levels.

Visible result:

- user asks a question about current/selected tokens;
- backend model performs at least one real tool call;
- answer and evidence return to the frontend;
- the frontend visibly highlights or selects the referenced token set.

A minimal Freeflow Observer may follow immediately if this manual path is stable. It must reuse the same analyst/tool boundary rather than introduce a parallel mechanism.

## 15. First draft merge target

Draft PR #5 should not remain open until the whole product vision exists.

The merge target is a coherent vertical foundation:

```text
V0 contract
+
V1 structural split / theme
+
V2 stable live delta behavior
+
V3 ViewSpec foundation
+
optional V4 thin analyst slice if stable
```

The first merge is ready when:

- the frontend starts independently;
- the operational core and Lifecycle v0.1 are untouched;
- database access remains read-only;
- the Universe is visually stable under live deltas;
- semantic design tokens are used consistently;
- code responsibilities are separated without speculative framework layers;
- at least two view configurations can use the same state/rendering contract;
- any included LLM path is server-side, bounded and read-only;
- the branch remains understandable as one coherent frontend feature.

## 16. Explicit non-goals of the foundation

The foundation does not require:

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
- density/semantic zoom for 20k+ tokens;
- OHLC/time-bucket work;
- permanent LLM-generated lifecycle classifications.

These may be added vertically after the foundation proves the interaction model.

## 17. Validation principle

Each slice must be validated through the real running frontend, not only static checks.

At minimum retain:

```text
Python compile check
JavaScript syntax check
read-only API smoke check
live SSE observation
visual verification in browser
```

The success criterion is not file count or abstraction depth. It is a stable, understandable, visibly working Observatory that can grow without turning `app.js` or the backend into a new monolith.
