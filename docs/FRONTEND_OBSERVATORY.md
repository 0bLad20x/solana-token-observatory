# Frontend Observatory

## Status

**Authority:** Frontend product, interaction and implementation direction  
**Scope:** read-only visual and analytical consumer of the operational token data  
**Current checkpoint:** V0–V2 and WP1–WP4 merged; WP5 Temporal Token Analysis is the active next slice; spatial redesign remains separate

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

### EXTERNAL EVIDENCE

Web-search results retain their source URLs and remain external evidence. A cited web
claim is neither persisted Jupiter truth nor Lifecycle Evidence. If no source connects a
claim to the exact mint, the interface must show that no reliable evidence was found.

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
    ├── analyst.py
    ├── app.py
    ├── data.py
    ├── tools.py
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
analyst.py        Mistral protocol, tool orchestration and web-reference parsing
data.py           read-only PostgreSQL projections
tools.py          bounded internal query_tokens contract and execution
app.js            application bootstrap and wiring
state.js          token state, search, selection, active view, deltas
universe.js       Pixi/D3 rendering and local motion
view-spec.js      supported view mappings and presets
theme.js          semantic visual tokens
```

`tools.py` exists because WP2 introduces the first real internal tool responsibility. It
is not a generic registry and exposes no SQL, plugin or mutation framework.

## 9. Backend contract

The existing minimal endpoints remain useful:

```text
GET /api/health
GET /api/universe
GET /api/token/{mint}
GET /api/events
POST /api/analyst
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

For `token_updated`, `changes` includes `volume_5m`. The compact activity feed derives
observed before/after values from that delta and the current token snapshot. It retains
only a rolling 60-second browser window, aggregates by Mint and ranks the five greatest
positive increases of:

```text
volume_5m / market_cap
```

Both volume and ratio must rise, and both Market Cap values must be positive. Missing
inputs are excluded. `volume_5m` remains Jupiter's rolling five-minute value; the feed
must not describe it as exact volume produced since the SSE event.

## 10. Current LLM analyst contract

WP1 provides token-scoped external research:

```text
selected token + free question
             ↓
server-side Mistral Conversations API
             ↓
web_search | web_search_premium
             ↓
answer + source references
```

The selected token is grounded with its exact mint and existing name, symbol and
launchpad. The mint is authoritative for web identity; matching names or symbols are not.
The backend rejects a provider response that did not execute Web Search.

The current response is deliberately small:

```json
{
  "answer": "...",
  "sources": [{"title": "...", "url": "..."}],
  "search_mode": "web_search"
}
```

No internal database tool, arbitrary SQL, Python execution, conversation memory,
provider framework or visual action belongs to WP1.

WP2 adds one separate current-data interaction:

```text
free population question
          ↓
Mistral function arguments
          ↓
bounded query_tokens
          ↓
at most 20 current rows
          ↓
grounded answer
```

`query_tokens` can use only current `market_cap`, `liquidity`, `holders`, `trades_5m`,
`traders_5m`, `volume_5m`, `age_seconds` and `change_age_seconds`. It may filter by an
available canonical launchpad, then sort and limit the result. The default limit is five
and the hard maximum is twenty. Missing remains `null` and is excluded when it is the
ranking field.

One central field vocabulary supplies descriptions, canonical keys, Tool Schema and the
visible capabilities response. Current launchpad values and counts are derived from the
active population for every request. Mistral translates paraphrases, spelling and
punctuation variants to those canonical arguments. The available fields remain the
semantic boundary: a question about an unavailable field such as five-minute price
change must not use another metric as a proxy. If no unambiguous supported query exists,
the backend returns the current fields, sort directions, launchpads and result limits.
No SQL or full dataset is sent to the model.

WP5 adds one explicit selected-token temporal interaction. It is not a general history
query and does not extend `query_tokens`:

```text
selected token + free temporal question
              ↓
Mistral Tool Call
              ↓
get_token_temporal_context
              ↓
exact selected Mint only
              ↓
1m <= 6h, otherwise 5m
              ↓
token + summary + temporal_history
              ↓
grounded temporal diagnosis
```

`get_token_temporal_context` has exactly one identity argument, the Mint. The server must
validate that it equals the currently selected Mint. The model cannot choose a time
range, resolution or another token. The returned data follows the semantic contract
validated by `tools/inspect_token_history.py` and merged in PR #16.

The deterministic `summary` is analysis support, not a diagnosis. The temporal system
prompt must require the model to inspect the actual `temporal_history`, use it to confirm,
qualify or contradict the Summary, and explicitly surface contradictions. `stats1h`
values are rolling one-hour values and must never be summed across buckets. Missing stays
Missing, and no claim may extend outside the delivered observation span.

### Configuration

LLM credentials remain server-side in environment configuration. No provider API key is exposed to JavaScript.

`MISTRAL_WEB_SEARCH_MODE` selects `web_search` or `web_search_premium`. Both use the
same Conversations endpoint. No provider SDK is required because the existing HTTP
client is sufficient.

## 11. Analyst UI pattern

The analyst card uses explicit scopes rather than hidden routing guesses:

```text
CURRENT DATA          WEB RESEARCH          TEMPORAL ANALYSIS
population question   selected token        selected token
query_tokens           web search            temporal context
current answer         sourced answer        grounded diagnosis
```

The Temporal Analysis scope requires an existing token selection. Its visible result must
show at least the covered time span and selected temporal resolution so the user can see
what evidence the answer received.

Switching scope changes the tool boundary; it is not an LLM routing guess.

## 12. Selection and navigation direction

WP3 establishes one current navigation path:

```text
Mint / Symbol / Name search ─┐
                             ├─> shared token selection -> Inspector -> Web Research
query_tokens result ─────────┘
```

Search uses the complete active population already delivered by `/api/universe`. A
backend search endpoint is not introduced without a measured client-side limitation.
Only active tokens are search results. They are ordered by current Market Cap and expose
Market Cap, Liquidity and Holders as identity context; missing remains visible as
missing. A selected token may remain visible as retired context after a live retirement
event.

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

The operational database retains approximately the latest 24 hours of high-resolution
`mint_snapshots`. PR #16 validated one bounded temporal projection over that retained
window, but the current frontend API does not expose it yet. WP5 adds only this selected-
token bounded context. Arbitrary historical ranges, persisted long-term series and cross-
token history remain outside the current contract.

## 14. Vertical execution plan

The Observatory is developed in short vertical slices. Every slice should end with a visible running result.

`DONE / MERGED` means that the narrow proof and its stop condition were validated. It
does not mean that the broader product area or the original Observatory vision is
finished.

### Implemented proofs

| Slice | Purpose | What is actually proven | What is not claimed |
|---|---|---|---|
| V0 — Contract | Establish truth, read-only and interaction boundaries before implementation. | This document defines the product and system constraints. | No user-facing capability. |
| V1 — Application foundation | Separate existing backend, state, rendering and theme responsibilities. | The Observatory starts independently and its minimal modules have explicit owners. | No finished design system or satisfactory spatial visualization. |
| V2 — Live data foundation | Prove current backend state reaches the browser and remains live. | Active tokens, current facts, SSE updates and retirements are visible and locally applied. | No claim that Bubble Map layout, scaling, motion or information design is solved. |
| WP1 — Token Web Research | Prove one selected exact Mint can execute external LLM Web Search. | A free question returns a sourced answer or explicit lack of evidence; standard and premium search are configurable. | No guarantee that arbitrary web claims are true and no general research agent. |
| WP2 — Current Population Query | Prove natural language can become one bounded internal read-only Tool Call. | `query_tokens` filters, ranks and limits the current active projection using an explicit vocabulary. | No SQL, arbitrary aggregation, unavailable metrics or full-dataset LLM access. |
| WP3 — Token Search & Selection | Make every active token reachable without relying on the visualization. | Mint, Symbol and Name search plus `query_tokens` results use one shared Selection for Inspector and Web Research. | No complete navigation system or visual redesign. |
| WP4 — Volume Activity Deltas | Replace a long, low-information event list with one current, inspectable signal. | PR #13 ranks at most five distinct Mints by positive 60-second change of `volume_5m / market_cap`; rows are selectable and expire. | No historical analysis, price-change proxy or effect on Bubble size, pulse, color, layout or Physics. |
| Temporal Context Research | Establish one bounded LLM payload over retained history before frontend integration. | PR #16 proves 1m/5m adaptive projection, deterministic Summary and a single `llm_context` on real long histories. | No frontend Tool Call or LLM diagnosis yet. |

Together these slices prove a functional foundation:

```text
current backend state -> live browser state -> find/select token
                                      ├-> bounded population question
                                      ├-> exact-mint Web Research
                                      └-> inspect current volume activity
```

They do not complete the original visual Observatory vision.

### WP5 — Temporal Token Analysis — ACTIVE

**Purpose:** answer how the currently selected token arrived at its current state within
the retained observation history, using one bounded read-only temporal Tool Call.

**Why this is next:** the Inspector research proof has already established a compact
context that preserves the meaningful trajectory. The remaining question is whether that
same deterministic context can ground a useful LLM diagnosis through the real Observatory
without introducing arbitrary history queries or a second implementation of the
projection logic.

#### Data contract

The selected Mint is read from the existing `mint_snapshots` 24h Raw-Buffer. The same
semantics proven by the Inspector apply:

```text
available history <= 6h -> 1m buckets
available history >  6h -> 5m buckets
```

The context contains:

```json
{
  "token": {},
  "summary": {},
  "temporal_history": {
    "resolution_minutes": 5,
    "buckets": []
  }
}
```

The Summary may include only deterministically computed facts supported by the supplied
history: Market Cap trajectory, peak and drawdown; Liquidity and Liquidity/Market-Cap;
Holders; Ownership; rolling `stats1h` activity and flow ratios; Organic Evidence; and
other already validated fields from the Inspector contract.

#### One semantic owner

WP5 introduces the second real consumer of the Temporal Projection. The implementation
must therefore avoid copying the Inspector algorithm or shelling out to the CLI. The pure
Projection/Summary logic gets one shared code owner. `tools/inspect_token_history.py`
remains a thin Research/CLI consumer and the Observatory calls the same logic directly.

No generic history framework is created around this extraction.

#### Tool contract

Exactly one new bounded internal Tool is added:

```text
get_token_temporal_context
```

Constraints:

- required argument: exact Mint;
- Mint must equal the current frontend selection;
- no arbitrary SQL;
- no caller-selected time range;
- no caller-selected resolution;
- no other Mint or cross-token comparison;
- read-only database access;
- no persistence or lifecycle mutation.

#### LLM evidence contract

The System Prompt must prevent Summary anchoring. The model must:

- inspect both `summary` and `temporal_history`;
- identify relevant temporal changes from the buckets itself;
- use history to confirm, qualify or contradict the Summary;
- explicitly mention contradictions instead of silently following Summary;
- distinguish System Truth, deterministic Analysis and LLM Hypothesis;
- preserve Missing as unknown;
- treat `stats1h` as rolling values, never additive bucket volume;
- avoid claims outside the covered time span.

A diagnosis based only on `summary` fails the WP5 contract.

#### Visible proof

The existing Analyst card gains one explicit `TEMPORAL ANALYSIS` scope. A successful
browser path is:

```text
select token
   ↓
choose TEMPORAL ANALYSIS
   ↓
ask free question
   ↓
one real get_token_temporal_context Tool Call
   ↓
show resolution + covered span
   ↓
grounded answer using temporal_history
```

The UI does not need a chart for this slice.

#### Stop condition

WP5 is complete only after the real browser proves:

1. a token with `<= 6h` available history produces `1m` buckets;
2. a token with `> 6h` available history produces `5m` buckets;
3. a token with missing partial fields keeps them missing and receives a qualified answer;
4. Tool Mint always equals the currently selected Mint;
5. the answer demonstrably uses the historical trajectory and not only Summary;
6. no operational state changes.

Not part of WP5:

- Raw-, Full- or 15m-LLM payloads;
- arbitrary time ranges or user-selectable resolution;
- persisted OHLC or long-term historical storage;
- charts, Bubble changes or broader design work;
- cross-token historical comparison;
- forecasts, autonomous trading decisions or lifecycle mutation;
- Conversation Memory or autonomous multi-tool routing.

### Foundation stop after WP5

No WP6 is currently defined. After WP5 browser validation, the functional foundation is
complete enough to reassess the product from evidence. The following remain separate
open topics, not scheduled work packages:

- visual and spatial redesign;
- additional internal questions such as cross-token comparison or cohorts;
- discovery provenance, which is blocked by missing Core Evidence;
- richer LLM orchestration, memory or visual actions.

A topic becomes the next WP only when one concrete user question, bounded data contract
and visible stop condition are agreed. This prevents optional future ideas from becoming
premature architecture.

## 15. Merge checkpoints

Vertical delivery also applies to Git history. A working slice does not stay artificially unmerged while unrelated future slices accumulate.

### Checkpoint 1 — V0 + V1

Draft PR #5 is the first merge checkpoint and contains:

```text
V0 Observatory contract
+
V1 structural split / semantic design system
```

This checkpoint is ready because:

- the frontend starts independently;
- the operational core and Lifecycle v0.1 are untouched;
- database access remains read-only;
- existing API/SSE behavior is preserved;
- semantic design tokens are applied;
- responsibilities are separated without a speculative frontend framework;
- the real browser/API path has been validated.

WP1 was merged as PR #10, WP2 as PR #11, WP3 as PR #12 and WP4 as PR #13 after their
real browser paths were validated. WP5 will be an independent merge checkpoint and does
not reopen spatial or design work.

## 16. Explicit non-goals of the foundation

The foundation does not require:

- full Cohort engine;
- Graveyard explorer;
- persisted LLM notebooks;
- autonomous long-running analyst workflows;
- unbounded web search;
- arbitrary SQL or Python execution;
- radar charts;
- population trees;
- complete discovery flow;
- time scrubber;
- density/semantic zoom for 20k+ tokens;
- persisted OHLC/time-bucket work;
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
