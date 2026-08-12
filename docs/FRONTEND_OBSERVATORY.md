# Frontend Observatory

## Status

**Authority:** funktionale Frontend-/Analyst-Grenzen  
**Scope:** read-only Consumer des operativen Token-Systems  
**Current checkpoint:** WP1–WP5 gemergt; Issue #20 Functional Core Consolidation aktiv  
**Visual design:** bewusst deferred; Issue #9 bleibt separater Research-Schritt

Dieses Dokument beschreibt den stabilen funktionalen Vertrag des Observatory. Es legt
keine finale Bubble-, Farb-, Layout-, Panel- oder Motion-Semantik fest.

## 1. Product Boundary

Das Observatory ist ein read-only Workspace zum Beobachten, Finden, Selektieren und
Analysieren von Solana Tokens.

```text
Operational Core
Discovery -> Jupiter Monitoring -> Persistence -> Lifecycle
                                      │
                                      ▼
                              read-only projection
                                      │
                         ┌────────────┴────────────┐
                         ▼                         ▼
                    Browser Workspace          LLM Analyst
```

Frontend und Analyst dürfen lesen. Sie dürfen keine operative Authority übernehmen.
Insbesondere keine Mutation von:

- `tracking_enabled`;
- Lifecycle State oder Thresholds;
- Collector-owned Observation State;
- Priority;
- operativer Persistenz.

## 2. Truth Model

### SYSTEM TRUTH

Direkt beobachtete oder deterministisch persistierte Fakten, beispielsweise:

- Mint;
- Jupiter Snapshot Values;
- Timestamps;
- Tracking/Lifecycle State;
- aktuelle Market Cap, Liquidity, Holder und Activity Values.

### DETERMINISTIC ANALYSIS

Reproduzierbar abgeleitete Werte, beispielsweise:

- Current-vs-Median Summary Facts;
- Drawdown/Range;
- WP4 Volume Activity;
- bounded Query Rankings.

### EXTERNAL EVIDENCE

Web Search und zukünftige Quellen wie RugCheck bleiben externe Evidenz. Sie werden nicht
stillschweigend zu Jupiter System Truth oder Lifecycle Evidence.

### LLM INTERPRETATION

LLM-Antworten sind Interpretation. Sie besitzen keine operative Authority.

## 3. First Principle: No Presentation Truth in the Functional Core

Der funktionale Kern bewahrt Domain-Fakten und gemeinsame Interaktionszustände.

Er speichert keine verlustbehafteten Visualisierungsartefakte als Wahrheit.

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

NOT FUNCTIONAL CORE
x / y
radius
color
opacity
stroke
cluster center
panel position
Pixi object
D3 force state
```

Eine zukünftige View darf denselben Domain-Wert auf X, Y, Größe, Farbe, Text oder gar
nicht abbilden, ohne den funktionalen Kern ändern zu müssen.

## 4. Selection Contract

Die gemeinsame Selection ist ausschließlich der ausgewählte Mint.

```text
Search ──────────┐
Current View ────┤
Activity Result ─┼──> selected Mint
Analyst Result ──┘          │
                            ├──> Inspector
                            ├──> Current View
                            └──> selected-token Analyst use cases
```

Kein Bubble Node, DOM Element, Tabellenrow oder Analyst Scope besitzt die Selection.

Ein bereits selektierter Token darf nach Retirement als Kontext erhalten bleiben.

## 5. Browser Responsibility Split

Issue #20 konsolidiert die Browser-Verantwortlichkeiten auf reale Gründe für Änderung.

```text
static/js/
├── app.js
├── api.js
├── state.js
├── search.js
├── activity.js
├── format.js
├── token-ui.js
├── activity-ui.js
├── analyst-ui.js
└── views/
    └── simple-token-view.js
```

### `app.js`

Nur Composition und Wiring:

- Module erzeugen;
- gemeinsame Selection verbinden;
- Bootstrap koordinieren;
- Live Delta an State, Derived Signals und View weiterreichen;
- Shell-Level Connection Status.

`app.js` rendert keine Search Results, Analyst Results oder Activity Rows selbst.

### `api.js`

Ein Browser-Owner für:

- `GET /api/universe`;
- `GET /api/token/{mint}`;
- `POST /api/analyst`;
- `EventSource /api/events`.

UI-Module kennen keine Fetch-/EventSource-Details.

### `state.js`

Besitzt nur langlebigen Application State:

- Token Population;
- selected Mint;
- add/update/retire Event Application;
- kleine direkte Population-Projektionen wie Active/Launchpad Count.

Search, WP4 Activity und Visual State gehören nicht hinein.

### `search.js`

Pure Search/Ranking über Domain Tokens. Search ist unabhängig von der aktuellen View.

### `activity.js`

WP4 Volume Activity und 60s Changed-Mint Count sind deterministische Derived Signals,
keine Population Truth.

### `token-ui.js`

Search- und Inspector-DOM. Konsumiert State und fordert Selection über einen Callback an.

### `activity-ui.js`

Rendert ausschließlich die bereits deterministisch berechnete Activity-Projektion.

### `analyst-ui.js`

Besitzt die heutige Analyst-UI und die sichtbaren Scopes. Die Anwendung selbst wird nicht
an die Drei-Button-Struktur gekoppelt. Ein späterer AI Router kann diesen Bereich ersetzen,
ohne Population, Search oder Views umzubauen.

### `views/*`

Konkrete Darstellung als Consumer des funktionalen Zustands.

Issue #20 verwendet absichtlich einen einfachen `SimpleTokenView` als vertikalen Proof.
Er ist kein Designvorschlag.

## 6. Current View Contract

Der aktuelle Proof-View braucht nur die heute reale Integrationsfläche:

```text
init()
load(tokens)
applyEvents(events)
setSelectedMint(mint)
destroy()
```

Diese Methoden sind **kein universeller Visualization Standard**.

Erst wenn eine reale zweite View existiert, wird anhand beider Implementierungen geprüft,
welche gemeinsame Abstraktion tatsächlich existiert.

Keine generische ViewSpec-/Visualization-DSL wird im Functional Core vorgebaut.

## 7. Backend Contract

Stabile Endpoints:

```text
GET  /api/health
GET  /api/universe
GET  /api/token/{mint}
GET  /api/events
POST /api/analyst
```

### `/api/universe`

Bootstrap der aktuellen aktiven Population.

### `/api/token/{mint}`

Aktuelle selected-token Projektion, einschließlich kürzlich retired Context wenn der
Backend-Vertrag dies zulässt.

### `/api/events`

SSE Live Delta Channel mit:

```text
token_added
token_updated
token_retired
```

`src/observatory/delta.py` besitzt den kanonischen numerischen Change-Vertrag:

```text
market_cap
liquidity
holders
trades_5m
traders_5m
volume_5m
```

Fingerprint und numerische Changes werden aus demselben Contract abgeleitet. Missing
bleibt unknown.

## 8. Analyst Contract

Der Analyst besitzt aktuell drei bewiesene Use Cases.

### Current Data

```text
free population question
      ↓
Mistral function arguments
      ↓
bounded query_tokens
      ↓
current rows
      ↓
grounded answer
```

Kein arbitrary SQL und kein vollständiger Dataset-Dump an das LLM.

### Web Research

```text
selected exact Mint + question
      ↓
Mistral Web Search
      ↓
answer + external source references
```

Exact Mint ist die Identitätsgrenze.

### Temporal Summary

```text
selected exact Mint
      ↓
deterministic <=24h Summary
      ↓
ONE Mistral request
      ↓
expert interpretation
```

Keine Raw-History, keine 1m/5m/15m-Time-Buckets und kein vorgeschalteter Temporal Tool
Call.

Die heutige Scope-Umschaltung ist UI-Verhalten, kein dauerhaftes Routing-Modell. Ein
späterer einheitlicher AI Workspace oder Tool Router wird separat aus realen Use Cases
abgeleitet.

## 9. Vertical Functional Proof

Ein Observatory-Slice gilt nur als funktional, wenn der reale Browserpfad funktioniert:

```text
PostgreSQL
   ↓
/api/universe
   ↓
Population State
   ↓
Current disposable View
   ↓
Search arbitrary active Mint/Symbol/Name
   ↓
shared selected Mint
   ├── View
   ├── Inspector
   └── selected-token Analyst
   ↓
SSE add/update/retire
   ├── State
   ├── View
   ├── Inspector
   └── WP4 Activity
```

Regression Proof zusätzlich:

```text
Current Data      ✓
Web Research      ✓
Temporal Summary  ✓
Read-only         ✓
```

Visuelle Ähnlichkeit zum vorherigen Bubble-Frontend ist kein Acceptance-Kriterium.

## 10. Evidence Readiness Before Design

Nach Issue #20 wird nicht sofort ein neues Design implementiert.

Zuerst werden fehlende fachliche Evidence-/Relation-Grenzen geprüft.

### RugCheck — Issue #18

Exact-Mint Token Report als separate externe Safety-/On-Chain-Evidenz. Keine implizite
Lifecycle-Mutation und keine Umdeutung zu Jupiter Truth.

### Discovery Provenance

Aktuell kann eine zukünftige Flow-/Tunnel-Darstellung nur Beziehungen zeigen, die
persistiert oder anderweitig read-only beweisbar sind.

Beispiel einer möglichen später benötigten Relation:

```text
Discovery Source
      ↓
Mint
      ↓
Jupiter Observation
      ↓
Lifecycle / Analyst Evidence
```

Wenn diese Relation fachlich nicht persistiert ist, darf das Frontend sie nicht erfinden.

### Bounded Comparison / weitere Evidence

Multi-Mint-Vergleich, zusätzliche Summaries oder weitere Quellen werden nur anhand einer
konkreten Benutzerfrage ergänzt.

## 11. Visual / Spatial Design Is Separate

Issue #9 entscheidet später die tatsächliche Darstellung.

Der Designprozess beginnt nicht mit Bubble Physics, sondern mit einer analytischen Frage.
Erst danach werden festgelegt:

- Daten → Position;
- Daten → Größe;
- Daten → Farbe/Opacity/Text;
- Missing- und Outlier-Regeln;
- Scales;
- Density/Zoom/Aggregation;
- Motion mit expliziter Bedeutung;
- reale Population-/Viewport-Akzeptanz.

Bubble, Scatter/Projection, Tunnel/Flow, Tree oder Network dürfen unterschiedliche
Semantiken besitzen. Der Functional Core versucht nicht, sie heute in eine universelle
Visualisierungssprache zu zwingen.

## 12. Non-Goals of the Functional Core

- finales UI/UX Design;
- Bubble Physics;
- finale Farben oder Category Palette;
- generische Visualization Engine;
- ViewSpec DSL;
- Tunnel/Tree/Network Implementierung;
- automatischer AI Router;
- RugCheck-Integration in Issue #20;
- Discovery-Provenance-Implementierung in Issue #20;
- Multi-Mint-Vergleich in Issue #20;
- operative Mutation.

## Completion Principle

Der Functional Core ist richtig geschnitten, wenn eine heute unbekannte zukünftige View
hinzugefügt werden kann, ohne Search, Selection, SSE, Inspector oder Analyst grundlegend
neu zu bauen.
