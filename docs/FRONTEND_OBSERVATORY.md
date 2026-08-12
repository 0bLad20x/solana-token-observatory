# Frontend Observatory

## Status

**Authority:** funktionale Frontend-/Analyst-Grenzen  
**Scope:** read-only Consumer des operativen Token-Systems  
**Current checkpoint:** Functional Core abgeschlossen; Live Operational Telemetry als flüchtiger read-only Runtime-Proof ergänzt  
**Analyst:** Current Data, Web, Temporal und RugCheck produktiv bewiesen  
**Visual design:** bewusst getrennt; Operational-Flow-Visualisierung kann auf bewiesener Telemetrie aufbauen, Issue #9 bleibt separater Token-Visual-/Spatial-Research-Schritt

Dieses Dokument beschreibt den stabilen funktionalen Vertrag des Observatory. Es definiert keine finale Bubble-, Farb-, Layout-, Panel- oder Motion-Semantik.

## 1. Product Boundary

Das Observatory ist ein read-only Workspace zum Beobachten, Finden, Selektieren und Analysieren von Solana Tokens sowie zum Beobachten des flüchtigen operativen Datenflusses.

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

Frontend, Analyst und Telemetry-UI dürfen lesen bzw. Runtime-Ereignisse darstellen. Sie dürfen keine operative Authority übernehmen. Insbesondere keine Mutation von:

- `tracking_enabled`;
- Lifecycle State oder Thresholds;
- Collector-owned Observation State;
- Priority;
- operativer Persistenz.

## 2. Truth Model

### SYSTEM TRUTH

Direkt gelesene oder deterministisch persistierte Fakten, beispielsweise:

- Mint;
- Jupiter Snapshot Values;
- Timestamps;
- Tracking/Lifecycle State;
- aktuelle Market Cap, Liquidity, Holder und Activity Values.

### DETERMINISTIC ANALYSIS

Reproduzierbar abgeleitete Werte, beispielsweise:

- bounded Query Rankings;
- WP4 Volume Activity;
- Current-vs-Median Summary Facts;
- Drawdown/Range;
- kompakter Temporal Summary.

### RUNTIME TELEMETRY

Flüchtige Beobachtung tatsächlich ausgeführter operativer Arbeit, beispielsweise:

- Discovery intake;
- Search-Lane RPM, latency und requested/received;
- WriteQueue polls/source versions/snapshots;
- Lifecycle Rule-1–7-Breakdown und `tracking` count.

Runtime Telemetry ist keine persistente System Truth und besitzt keine operative Authority.

### EXTERNAL EVIDENCE

Web Search und RugCheck sind externe Evidenz. Sie werden nicht stillschweigend zu Jupiter System Truth oder Lifecycle Evidence.

### LLM INTERPRETATION

LLM-Antworten sind probabilistische Interpretation. Sie besitzen keine operative Authority.

## 3. First Principle: No Presentation Truth in the Functional Core

Der Functional Core bewahrt Domain-Fakten und gemeinsame Interaktionszustände. Er speichert keine verlustbehafteten Visualisierungsartefakte als Wahrheit.

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
telemetry card layout
```

Eine zukünftige View darf denselben Domain- oder Telemetrie-Wert auf X, Y, Größe, Farbe, Text oder gar nicht abbilden, ohne den Functional Core ändern zu müssen.

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

Kein DOM Element, Tabellenrow, View-Node oder Analyst Scope besitzt die Selection. Operational Telemetry besitzt keine Mint-Selection und transportiert keine Mint-Listen.

Ein bereits selektierter Token darf nach Retirement als Kontext erhalten bleiben.

## 5. Browser Responsibility Split

Die Browser-Verantwortlichkeiten sind nach realen Gründen für Änderung getrennt:

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
├── telemetry-ui.js
└── views/
    └── simple-token-view.js
```

### `app.js`

Composition und Wiring:

- Module erzeugen;
- gemeinsame Selection verbinden;
- Bootstrap koordinieren;
- Token-Stream-Snapshot und Deltas verteilen;
- Telemetry-Stream an die Telemetry-UI weiterreichen;
- Shell-Level Connection Status.

### `api.js`

Ein Browser-Owner für HTTP/SSE:

- `GET /api/universe`;
- `GET /api/token/{mint}`;
- `POST /api/analyst`;
- `EventSource /api/events`;
- `EventSource /api/telemetry/events`.

UI-Module kennen keine Fetch-/EventSource-Details.

### `state.js`

Besitzt ausschließlich langlebigen Application State:

- Token Population;
- `selectedMint`;
- Full-Snapshot Load;
- add/update/retire Event Application;
- kleine direkte Population-Projektionen wie Active/Launchpad Count.

Es gibt keinen beliebigen `upsert()`-Pfad für Selected-Detail-Reads. Search, Activity, Telemetry und Visual State gehören nicht in `state.js`.

### `search.js`

Pure Search/Ranking über Domain Tokens, unabhängig von der aktuellen View.

### `activity.js`

WP4 Volume Activity und 60s Changed-Mint Count sind deterministische Derived Signals, keine Population Truth. Bei einem Stream-Resync werden unvollständig rekonstruierbare Rolling-Signale zurückgesetzt.

### `token-ui.js`

Search- und Inspector-DOM. Der Selected-Detail-Read darf aktuelle Detaildarstellung aktualisieren, aber nicht die Population als zweiten Domain-Updatepfad überschreiben.

### `activity-ui.js`

Rendert ausschließlich die bereits deterministisch berechnete Activity-Projektion.

### `analyst-ui.js`

Besitzt die heutige Analyst-UI und die sichtbaren vier Scopes. Die Anwendung selbst ist nicht an diese Button-Struktur als dauerhaftes Routing-Modell gekoppelt.

### `telemetry-ui.js`

Rendert ausschließlich flüchtige Runtime-Telemetrie. Der Browser aggregiert bzw. aktualisiert die Darstellung maximal ungefähr einmal pro Sekunde. Die UI verändert weder Lifecycle noch Collector-State.

### `views/*`

Konkrete Darstellung als Consumer des funktionalen Zustands.

`SimpleTokenView` ist absichtlich ein kleiner vertikaler Proof und kein Designvorschlag. Erst bei einer realen zweiten View wird geprüft, welche gemeinsame View-Abstraktion tatsächlich existiert.

## 6. Current View Contract

Der aktuelle Proof-View benötigt nur die heute reale Integrationsfläche:

```text
init()
load(tokens)
applyEvents(events)
setSelectedMint(mint)
destroy()
```

Diese Methoden sind kein universeller Visualization Standard. Es gibt keine generische ViewSpec-/Visualization-DSL im Functional Core.

## 7. Backend Contract

Stabile Endpoints:

```text
GET  /api/health
GET  /api/universe
GET  /api/token/{mint}
GET  /api/events
GET  /api/telemetry
GET  /api/telemetry/events
GET  /api/evidence/rugcheck/{mint}
POST /api/analyst
```

### `/api/universe`

Bootstrap der aktuellen Observatory-Population.

### `/api/token/{mint}`

Selected-token Detail-Read, einschließlich kürzlich retired Context wenn verfügbar. Die Antwort wird nicht als zweiter Population-Updatepfad verwendet.

### `/api/events`

SSE besitzt eine explizite Synchronisationsgrenze:

```text
connect / reconnect
      ↓
universe_snapshot
      ↓
universe_delta*
```

Jede Verbindung beginnt mit genau einem vollständigen `universe_snapshot`. Derselbe Snapshot ist die Server-Baseline für alle nachfolgenden Deltas. Damit existiert keine undefinierte Lücke zwischen Browserzustand und Stream-Baseline.

Delta-Typen:

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

Fingerprint und numerische Changes werden aus demselben Contract abgeleitet. Missing bleibt unknown.

Der Server erzeugt Deltas heute weiterhin per Connection durch Snapshot/Diff-Polling. Das ist akzeptierte Skalierungsschuld, aber kein fachlicher Browser-Vertrag. Ein Broadcaster/Event-Replay-System wird nicht vorsorglich eingeführt.

## 8. Live Operational Telemetry Contract

Die Telemetrie beantwortet ausschließlich die Frage: **Was tut das operative System gerade?**

```text
Discovery / Search / WriteQueue / Lifecycle
                ↓
       localhost UDP best effort
                ↓
      Observatory 10m RAM buffer
                ↓
      telemetry snapshot + SSE
                ↓
       deterministic <=1 Hz UI
```

Event-Typen:

```text
discovery_tick
search_lane_tick
search_flush
lifecycle_tick
```

Transport:

```text
GET /api/telemetry
GET /api/telemetry/events
```

Der SSE-Stream beginnt mit `telemetry_snapshot` und liefert danach `telemetry_event`. Er ist absichtlich vom Token-Stream `/api/events` getrennt.

Harte Grenzen:

- maximal zehn Minuten flüchtiger RAM-Buffer;
- keine DB- oder Disk-Persistenz;
- best effort, kein Retry-/Delivery-Vertrag;
- keine API Keys;
- keine Mint-Listen;
- kein Alerting, Broker oder Event Sourcing;
- keine operative Mutation.

### `ACTIVE` versus `TRACKING`

Die beiden sichtbaren Population-Zähler haben unterschiedliche Semantik:

- Topbar `ACTIVE`: Größe der aktuell vom Observatory-Read-Model sichtbaren Population. Der heutige `FrontendReader` benötigt dafür `tracking_enabled=true` und einen verfügbaren jüngsten Raw-Snapshot.
- Lifecycle `TRACKING`: `active_remaining`, also `COUNT(*) FROM mints WHERE tracking_enabled=true` nach dem jeweiligen Lifecycle-Cycle.

Sie sollen im stabilen Betrieb eng zusammenliegen, sind aber **nicht als exakt derselbe Messpunkt definiert**. Abweichungen können durch unabhängige Read-Zeitpunkte und die unterschiedliche Projektionsgrenze entstehen. Lifecycle v0.3 / Rule 7 hat die frühere große Differenz durch dauerhaft source-inaktive, aber weiterhin getrackte Mints praktisch beseitigt.

`lifecycle_tick.breakdown` zeigt R1 bis R7. Die Telemetry-UI verändert oder interpretiert die Lifecycle-Regeln nicht.

## 9. Analyst Contract

Der Analyst besitzt vier bewiesene Use Cases.

### Model Policy

Modellwahl erfolgt serverseitig nach kognitiver Verantwortung:

```text
current_data -> FAST   -> ministral-14b-latest
web          -> STRONG -> mistral-large-latest
temporal     -> STRONG -> mistral-large-latest
rugcheck     -> STRONG -> mistral-large-latest
```

Die UI kennt keine Modellnamen. Der FAST-Default wurde gegen den realen `query_tokens`-Contract ausgewählt; der Tool-Vertrag wurde nicht abgeschwächt, um ein kleineres Modell passend zu machen.

### Current Data

```text
free population question
      ↓
FAST model
      ↓
bounded query_tokens arguments
      ↓
current rows
      ↓
grounded answer
```

Kein arbitrary SQL und kein vollständiger Dataset-Dump an das LLM. Unsupported oder mehrdeutige Fragen dürfen keine Proxy-Metrik erfinden.

### Web Research

```text
selected exact Mint + question
      ↓
Mistral Web Search
      ↓
answer + external source references
```

Exact Mint ist die Identitätsgrenze. Web-Ergebnisse bleiben External Evidence.

### Temporal Summary

```text
selected exact Mint
      ↓
deterministic <=24h Summary
      ↓
ONE STRONG-model request
      ↓
expert interpretation
```

Der produktive Temporal-Pfad sendet keine Raw-History und keine 1m/5m/15m-Time-Buckets an das LLM. Es gibt keinen vorgeschalteten Temporal Tool Call.

### RugCheck

```text
selected exact Mint
      ↓
direct RugCheck full-report fetch
      ↓
deterministic rugcheck_analysis_v4 metadata
      ↓
ONE STRONG-model request
      ↓
grounded safety-evidence interpretation
```

Der Provider-Fetch selbst verwendet keinen LLM Tool Call. Der vollständige Report bleibt als direkte Provider-Evidence verfügbar; an das LLM geht eine kompakte deterministische Safety-Projektion ohne einzelne Wallet-Adressen oder komplette Holder-/Market-Rohzeilen.

RugCheck-Fakten bleiben RugCheck-Fakten. Missing bleibt Missing. Es gibt keinen internen Safety Score, keine Persistence und keine Lifecycle-Mutation.

## 10. Vertical Functional Proof

Der bewiesene Browserpfad ist:

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
SSE connect/reconnect snapshot
   ↓
SSE add/update/retire deltas
   ├── State
   ├── View
   ├── Inspector
   └── WP4 Activity
```

Zusätzlich bewiesen:

```text
Discovery / Search / WriteQueue / Lifecycle
               ↓
volatile telemetry
               ↓
separate SSE
               ↓
Operational dataflow proof
```

Bewiesene Analyst-Pfade:

```text
Current Data      ✓
Web Research      ✓
Temporal Summary  ✓
RugCheck          ✓
Read-only         ✓
```

Visuelle Ähnlichkeit zu früheren Bubble-Experimenten ist kein Acceptance-Kriterium.

## 11. Evidence Readiness Before Design

Der Functional Core und der Live-Telemetrie-Proof sind abgeschlossen. Daraus folgt **nicht**, dass eine bestimmte Visualisierung bereits festgelegt ist.

Für den nächsten Operational-Flow-Visual-Slice existieren jetzt reale Metriken für Discovery, Search, WriteQueue und Lifecycle. Diese können strukturell visualisiert werden, ohne neue Domain-Evidence zu erfinden.

Für Token-bezogene Spatial Views bleibt weiterhin zu prüfen, ob eine zukünftige Benutzerfrage zusätzliche Evidence-/Relation-Grenzen benötigt.

### Discovery Provenance

Eine zukünftige per-Mint Flow-/Tunnel-/Tree-Darstellung darf nur Beziehungen zeigen, die persistiert oder anderweitig read-only beweisbar sind.

Mögliche spätere Relation:

```text
Discovery Source
      ↓
Mint
      ↓
Jupiter Observation
      ↓
Lifecycle / Analyst Evidence
```

Diese Relation ist heute nicht automatisch ein Produktvertrag. Die bestehende Operational Telemetry zeigt Source-Massen und Durchsatz, aber keine persistente per-Mint Discovery-Provenance.

### Bounded Comparison / weitere Evidence

Multi-Mint-Vergleich, zusätzliche Summaries oder weitere externe Quellen werden nur anhand einer konkreten Benutzerfrage ergänzt.

### Unified AI Router

Ein späterer einheitlicher Frageeingang könnte die bereits bewiesenen Evidence-Pfade routen. Ob Routing deterministisch, LLM-basiert, hybrid oder parallel erfolgt, ist noch nicht entschieden und wird nicht aus den heutigen vier UI-Buttons abgeleitet.

## 12. Visual / Spatial Design Is Separate

Operational-Flow-Visualisierung und Token-Spatial-Research sind getrennte Fragen.

Der Operational-Flow-Slice kann unmittelbar auf den bewiesenen Telemetrie-Fakten aufbauen:

```text
Discovery intake
      ↓
Search lanes
      ↓
WriteQueue
      ↓
Lifecycle R1-R7
      ↓
Tracking survivors ↺ Search
```

Zuerst wird eine strukturelle Data-to-Visual-Semantik definiert; Motion wird nur ergänzt, wenn sie einen realen Zustandswechsel oder Durchsatz transportiert.

Issue #9 bleibt der separate Design-/Research-Schritt für Token-/Spatial-Darstellungen. Dort beginnt Design weiterhin mit einer analytischen Frage, nicht mit Bubble Physics. Erst danach werden festgelegt:

- Daten → Position;
- Daten → Größe;
- Daten → Farbe/Opacity/Text;
- Missing- und Outlier-Regeln;
- Scales;
- Density/Zoom/Aggregation;
- Motion mit expliziter Bedeutung;
- reale Population-/Viewport-Akzeptanz.

## 13. Frozen-Core Non-Goals

Ohne einen neuen expliziten fachlichen Grund wird der Functional Core nicht erweitert um:

- finale Bubble Physics;
- finale Farben oder Category Palette;
- generische Visualization Engine;
- ViewSpec DSL;
- Event Bus / Event Sourcing Framework;
- vorsorglichen serverweiten Token-Stream-Broadcaster;
- automatischen AI Router;
- Discovery-Provenance-Persistenz;
- Multi-Mint-Vergleich;
- operative Mutation durch Frontend, Analyst oder Telemetry.

## Completion Principle

Der Functional Core ist richtig geschnitten, wenn eine heute unbekannte zukünftige View oder ein zusätzlicher read-only Evidence-Consumer hinzugefügt werden kann, ohne Population, Search, Selection, SSE, Inspector oder bestehende Analyst-Pfade grundlegend neu zu bauen. Der Telemetrie-Pfad ist richtig geschnitten, wenn er den realen operativen Flow beobachtbar macht, ohne selbst Teil dieses operativen Flows zu werden.
