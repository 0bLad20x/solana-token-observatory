# Frontend Observatory

## Status und Scope

`src/observatory/` ist ein read-only Consumer des operativen Token-Systems. Das Observatory darf Domain- und Telemetry-Fakten darstellen und analysieren, aber keine operative Mutation oder erfundene Datenbeziehung erzeugen.

```text
Operational Core
Discovery -> Jupiter Monitoring -> Persistence -> Lifecycle
                                      │
                                      ▼
                              read-only projection
                                      │
                 ┌────────────────────┼────────────────────┐
                 ▼                    ▼                    ▼
          Browser Workspace      LLM Analyst      Runtime Telemetry
```

## 1. Truth Model

### System Truth

Direkt gelesene oder deterministisch persistierte operative Fakten wie Mint, Jupiter-Werte, Timestamps und Tracking-/Lifecycle-State.

### Deterministic Analysis

Reproduzierbar abgeleitete Werte wie Rankings, Activity oder Temporal Summary.

### Runtime Telemetry

Flüchtige Beobachtung tatsächlich ausgeführter Arbeit: Discovery, Search-Lanes, WriteQueue und Lifecycle-Cycles. Telemetry ist keine persistente System Truth und besitzt keine operative Authority.

### External Evidence

Web Search und RugCheck bleiben externe Evidence.

### LLM Interpretation

LLM-Antworten sind probabilistische Interpretation ohne operative Authority.

Keine Ebene darf stillschweigend in eine stärkere Truth-Klasse hochgestuft werden.

## 2. Functional Core vs Presentation

Der Functional Core bewahrt Domain-Fakten und gemeinsame Interaktionszustände, keine Visualisierungsartefakte.

```text
FUNCTIONAL CORE
mint
market_cap
liquidity
holders
launchpad
timestamps
tracking state
selected Mint
live token events

PRESENTATION
x / y
radius
color / opacity / stroke
cluster center
panel width
Canvas state
animation progress
```

Presentation ist austauschbar und keine Domain-Authority.

## 3. Population und Selection

Der Browser besitzt genau eine kanonische aktive Population und genau einen `selectedMint`.

```text
Search ──────────┐
Token Universe ──┤
Activity Result ─┼──> selected Mint
Analyst Result ──┘          │
                            ├──> Inspector
                            ├──> Token Universe
                            └──> selected-token Analyst scopes
```

Operational Flow besitzt keine Mint-Selection und transportiert keine Mint-Listen.

Ein bereits selektierter Token darf nach Retirement als Kontext erhalten bleiben, ohne wieder Teil der aktiven Population zu werden.

## 4. Browser Responsibility Split

```text
static/js/
├── app.js                  composition / wiring
├── api.js                  HTTP + SSE
├── state.js                population + selection + event application
├── search.js               pure search / ranking
├── activity.js             derived live signals
├── token-ui.js             Search + Inspector DOM
├── activity-ui.js          Live Deltas DOM
├── analyst-ui.js           Analyst interaction
├── markdown.js             safe Markdown subset
├── telemetry-ui.js         volatile telemetry projection
└── views/
    ├── token-universe-view.js
    └── operational-flow-view.js
```

`state.js` besitzt ausschließlich Population, `selectedMint`, Full-Snapshot Load und add/update/retire Event Application. Search, Activity, Telemetry und Presentation State gehören nicht hinein.

Views konsumieren State; sie besitzen weder Transport noch eine zweite Population.

## 5. Synchronisationsvertrag

`/api/events` ist die autoritative Browser-Synchronisationsgrenze:

```text
connect / reconnect
      ↓
universe_snapshot
      ↓
universe_delta*
```

Delta-Typen:

```text
token_added
token_updated
token_retired
```

Der Snapshot ist zugleich die Server-Baseline für nachfolgende Deltas. `GET /api/token/{mint}` bleibt eine read-only Detail-Capability und ist kein zweiter Population-Updatepfad.

## 6. Aktuelle Main-Stage Views

### Token Universe

Die aktive Token-Population wird als räumliche Bubble-Map dargestellt. Die View konsumiert die kanonische Population, gemeinsame Selection und lokale Token-Deltas. Konkrete Position, Größe, Farbe, Halo, Motion und andere visuelle Kodierungen sind Presentation und keine Domain Truth.

### Operational Flow

Die Runtime wird aus vorhandener flüchtiger Telemetry dargestellt:

```text
Discovery -> Admission -> Search -> Write -> Lifecycle -> Tracking
                                              └-> retired
                         ^                         |
                         └──── monitoring loop ────┘
```

Count-Marks und Work-Pakete repräsentieren Mengen bzw. Arbeit und niemals behauptete Mint-Identitäten.

## 7. Runtime Telemetry

Telemetry ist ein separater best-effort Beobachtungspfad:

```text
Discovery / Search / WriteQueue / Lifecycle
                ↓
       localhost UDP
                ↓
      bounded RAM buffer
                ↓
      telemetry snapshot + SSE
                ↓
       Operational Flow
```

Event-Typen:

```text
discovery_tick
search_lane_tick
search_flush
lifecycle_tick
```

Harte Grenzen:

- keine DB-/Disk-Persistenz;
- keine API Keys;
- keine Mint-Listen;
- kein Alerting oder Event Sourcing;
- keine operative Mutation.

## 8. Analyst Contract

Der Analyst besitzt vier explizite read-only Use Cases:

```text
current_data
web
temporal
rugcheck
```

- Current Data verwendet bounded `query_tokens` statt arbitrary SQL.
- Web Research verwendet Exact Mint als Identitätsgrenze.
- Temporal verwendet einen deterministischen `<=24h` Summary statt Raw-History-Dump.
- RugCheck trennt direkte Provider-Evidence von deterministischer Projektion und LLM-Interpretation.
- Modellwahl und API Keys bleiben serverseitig.

LLM-Antworten dürfen keine operative Mutation oder Lifecycle-Entscheidung auslösen.

## 9. Non-Goals ohne neuen fachlichen Grund

- generische Visualization Engine;
- ViewSpec DSL;
- Event Bus / Event Sourcing Framework;
- vorsorglicher serverweiter Token-Stream-Broadcaster;
- automatischer AI Router;
- Discovery-Provenance-Persistenz;
- operative Mutation durch Frontend, Analyst oder Telemetry.

Neue Presentation- oder Evidence-Arbeit muss aus einer konkreten Produktfrage, einem beobachteten Problem oder einem neuen beweisbaren Datenvertrag abgeleitet werden.
