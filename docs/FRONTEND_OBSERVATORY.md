# Frontend Observatory

## Status

**Authority:** funktionale Frontend-/Analyst-/Telemetry-Grenzen  
**Scope:** read-only Consumer des operativen Token-Systems  
**Current checkpoint:** Functional Core, Live Operational Telemetry und Visual WP1–WP4 abgeschlossen  
**Analyst:** Current Data, Web, Temporal und RugCheck produktiv bewiesen  
**Primary views:** Token Universe + Operational Flow

Dieses Dokument beschreibt den stabilen funktionalen und akzeptierten visuellen Vertrag des Observatory. Presentation darf Domain- und Telemetry-Fakten darstellen, aber keine neue operative Authority oder erfundene Datenbeziehung erzeugen.

## 1. Product Boundary

Das Observatory ist ein read-only One-Screen-Workspace zum Beobachten, Finden, Selektieren und Analysieren von Solana Tokens sowie zum Beobachten des flüchtigen operativen Datenflusses.

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

Primäre Benutzeraktionen:

```text
ansehen -> suchen -> selektieren -> fragen -> analysieren
```

Frontend, Analyst und Telemetry-UI dürfen keine Mutation übernehmen von:

- `tracking_enabled`;
- Lifecycle State oder Thresholds;
- Collector-owned Observation State;
- Priority;
- operativer Persistenz.

## 2. Truth Model

### SYSTEM TRUTH

Direkt gelesene oder deterministisch persistierte Fakten, beispielsweise Mint, Jupiter-Werte, Timestamps, Tracking-/Lifecycle-State, Market Cap, Liquidity, Holder und Activity Values.

### DETERMINISTIC ANALYSIS

Reproduzierbar abgeleitete Werte wie Rankings, Activity oder Temporal Summary.

### RUNTIME TELEMETRY

Flüchtige Beobachtung tatsächlich ausgeführter Arbeit:

- Discovery intake;
- Search-Lane RPM, latency und requested/received;
- WriteQueue polls/source versions/snapshots;
- Lifecycle Rule-1–7-Breakdown und Cycle-State.

Runtime Telemetry ist keine persistente System Truth und besitzt keine operative Authority.

### EXTERNAL EVIDENCE

Web Search und RugCheck bleiben externe Evidence.

### LLM INTERPRETATION

LLM-Antworten sind probabilistische Interpretation ohne operative Authority.

## 3. No Presentation Truth in the Functional Core

Der Functional Core bewahrt Domain-Fakten und gemeinsame Interaktionszustände, keine verlustbehafteten Visualisierungsartefakte.

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
color / halo / opacity
stroke
cluster center
panel position / width
Canvas/D3/Pixi state
animation progress
```

## 4. Selection Contract

Die gemeinsame Selection ist ausschließlich der ausgewählte Mint.

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

Ein bereits selektierter Token darf nach Retirement als Kontext erhalten bleiben.

## 5. Browser Responsibility Split

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
├── markdown.js
├── telemetry-ui.js
└── views/
    ├── token-universe-view.js
    └── operational-flow-view.js
```

### `app.js`

Composition und Wiring:

- Module erzeugen;
- gemeinsame Selection verbinden;
- `/api/events` als einzigen Browser-Population-Bootstrap verbinden;
- `universe_snapshot` und `universe_delta` auf den kanonischen State anwenden;
- Universe/Flow als zwei Presentation-Views schalten;
- Telemetry-Stream an `TelemetryUI` weiterreichen;
- Right-Context Collapse/Resize steuern.

Ein Fehler in der Operational-Flow-Presentation darf den Functional Core nicht offline setzen. Token- und Telemetry-SSE werden vor der optionalen Flow-Presentation etabliert.

### `api.js`

Ein Browser-Owner für HTTP/SSE:

- `POST /api/analyst`;
- `EventSource /api/events`;
- `EventSource /api/telemetry/events`.

`GET /api/universe` und `GET /api/token/{mint}` bleiben read-only Backend-Capabilities, sind aber keine parallelen Population-State-Owner.

### `state.js`

Besitzt ausschließlich:

- Token Population;
- `selectedMint`;
- Full-Snapshot Load;
- add/update/retire Event Application;
- kleine direkte Population-Projektionen.

Search, Activity, Telemetry und Visual State gehören nicht hinein.

### `telemetry-ui.js`

Besitzt ausschließlich die flüchtige Browser-Projektion der vier Telemetry-Eventtypen und reicht sie an die Flow-View weiter. Snapshot-Replay stellt Zustand her; nur frisch eintreffende Events erzeugen eventgebundene Motion.

## 6. Accepted Visual Shell — WP1

Akzeptiert:

- dunkle Solana-/Crypto-Farbwelt und bestehender System-Font-Stack;
- größere Typografie und Abstände;
- dominante Main Stage;
- Right Context auf Desktop zwischen 360px und 640px resizebar;
- Collapse/Restore ohne Verlust von Selection oder Analyst-State;
- Search über die vollständige aktive Population;
- Inspector mit bestehenden Token-Fakten;
- vollständige Mint-Adresse mit Copy.

Panelbreite und Collapse-State sind Presentation State.

## 7. Analyst Focus — WP2

Akzeptiert:

- Analyst lebt idle im Right Context;
- `Focus` zeigt denselben Analyst als großen Research-Workspace über der Main Stage;
- Submit öffnet Focus automatisch;
- Close/Escape erhält Selection, Frage und Antwort;
- Current Data, Web, Temporal und RugCheck bleiben dieselben vier Scopes;
- Frage, LLM-Antwort und Evidence/Sources sind visuell getrennt;
- lange Antworten scrollen im Research-Bereich;
- Antwort ist kopierbar;
- `markdown.js` rendert Headings, Bold/Italic, Inline-Code, Listen, Trennlinien und Tabellen über explizite DOM-Nodes;
- kein ungefiltertes Modell-HTML und kein Mermaid-Renderer im aktuellen Vertrag;
- keine Conversation-/Scope-History.

## 8. Token Universe — WP3

Analytische Frage:

> Wie verteilt sich die aktive Token-Population auf Launchpads und welche Tokens sind relativ wirtschaftlich groß?

Akzeptierter Data-to-Visual-Vertrag:

```text
cluster       = launchpad membership
bubble area   = market cap
liquidity     = separate halo
focus spoke   = membership connection; holder count influences intensity
```

Weitere Eigenschaften:

- Launchpads einzeln ein-/ausblendbar;
- Zoom/Pan + Fit all;
- Click -> bestehende Selection -> Inspector/Analyst;
- adaptive stabile Cluster;
- keine permanente Force-Physics;
- `token_added` = sichtbarer Eintritt;
- relevante Market-Cap-Veränderung = gerichtete Größenanimation;
- `token_retired` = klarer mehrstufiger Exit vor Cluster-Gap-Closure;
- User-Filter bleibt Authority über Launchpad-Sichtbarkeit.

## 9. Live Operational Flow — WP4

Analytische Frage:

> Wo befindet sich die Datenmasse gerade, wie wird sie durch das System verarbeitet und wo wird Population reduziert oder weiter überwacht?

```text
Discovery -> Admission -> Search -> Write -> Lifecycle -> Tracking
                                              └-> retired
                         ^                         |
                         └──── monitoring loop ────┘
```

### Discovery / Admission

Jeder reale `discovery_tick` besitzt `response_items`, `unique_candidates`, `new_mints` und Latenz.

Visualisierung:

```text
SOURCE -> RAW INTAKE -> DEDUPE -> NEW -> Search
```

- Raw Intake = bounded Mengenfeld;
- Dedupe = Gate mit realem Unique Count / Verhältnis;
- New = admitted output;
- frische Discovery-Ticks erzeugen mengenabhängige Bursts;
- Bewegungsdauer wird durch beobachtete Latenz begrenzt;
- Count-Marks repräsentieren Mengen, nicht konkrete Mints.

### Search

- reale parallele Lane-Struktur;
- `search_lane_tick` erzeugt Work-Pakete auf der beobachteten Lane;
- `requested` beeinflusst bounded Paketmenge/-breite;
- `latency_ms` beeinflusst bounded Laufzeit;
- keine globale bewegliche Layout-Physics.

### WriteQueue

Große Kondensationsregion:

```text
POLLS -> SOURCE VERSIONS -> SNAPSHOTS
```

`search_flush` erzeugt eine sichtbare Kompressionswelle durch die drei Mengenfelder und einen Output-Burst Richtung Lifecycle.

### Lifecycle

- R1–R7 als Gates;
- `lifecycle_tick` erzeugt einen Sweep;
- reale non-zero Rule-Breakdowns speisen bounded Units in einen kompakten `RETIRED` / `CANDIDATES`-Sink;
- Survivors laufen weiter zu Tracking.

### Tracking

Die große sichtbare Tracking-Zahl verwendet **die kanonische Browser-Population** und entspricht damit demselben aktuellen Messpunkt wie Topbar `ACTIVE`.

`lifecycle.active_remaining` bleibt ein anderer Fakt: Stand von `tracking_enabled=true` beim letzten Lifecycle-Cycle. Dieser Wert bleibt im Detail sichtbar, aber nicht als konkurrierende große Population-Zahl.

Änderungen der kanonischen Population erzeugen einen kurzen +/- Reservoir-Pulse.

### Monitoring Loop

Der Rücklauf Tracking -> Search ist ein kontinuierlicher rate-codierter Monitoring-Current:

- Dichte/Breite aus aggregiertem aktuellem Search-RPM;
- Geschwindigkeit aus bounded medianer Search-Latenz;
- keine event-per-lane nervöse Rücklaufanimation;
- kein Punkt steht für einen konkreten Mint.

## 10. Backend Contract

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

### `/api/events`

```text
browser start / reconnect
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

Der Snapshot ist zugleich die Server-Baseline für nachfolgende Deltas.

### `/api/telemetry/events`

Der getrennte Telemetry-SSE beginnt mit `telemetry_snapshot` und liefert danach `telemetry_event`.

Event-Typen:

```text
discovery_tick
search_lane_tick
search_flush
lifecycle_tick
```

Harte Telemetry-Grenzen:

- maximal zehn Minuten flüchtiger RAM-Buffer;
- keine DB-/Disk-Persistenz;
- best effort;
- keine API Keys;
- keine Mint-Listen;
- kein Alerting, Broker oder Event Sourcing;
- keine operative Mutation.

## 11. Analyst Contract

### Model Policy

```text
current_data -> FAST   -> ministral-14b-latest
web          -> STRONG -> mistral-large-latest
temporal     -> STRONG -> mistral-large-latest
rugcheck     -> STRONG -> mistral-large-latest
```

Die UI kennt keine Modellnamen.

### Current Data

Freie Fragen werden in bounded `query_tokens`-Argumente übersetzt. Kein arbitrary SQL und kein vollständiger Dataset-Dump an das LLM.

### Web Research

Exact Mint ist die Identitätsgrenze. Web-Ergebnisse bleiben External Evidence.

### Temporal Summary

Deterministischer `<=24h` Summary -> genau ein STRONG-Modell-Request. Keine Raw-History und keine 1m/5m/15m-Time-Buckets an das LLM.

### RugCheck

Direct full-report fetch -> deterministische `rugcheck_analysis_v4`-Metadaten -> genau ein STRONG-Modell-Request. Keine Wallet-Adressen in der LLM-Projektion, keine Persistence und keine Lifecycle-Mutation.

## 12. Completed Visual Checkpoint

```text
WP1 Shell / Typography / Inspector      ✓
WP2 Analyst Focus                       ✓
WP3 Token Universe                      ✓
WP4 Operational Flow                    ✓
```

Universe und Flow verwenden dieselbe Main Stage, dieselbe kanonische Population und dieselbe Shell. Der Wechsel erzeugt keine zweite Seite und keinen zweiten Domain-State.

Es gibt derzeit kein weiteres beschlossenes Frontend-Design-WP. Neue UI-Arbeit muss aus einer konkreten Produktfrage oder einem beobachteten Usability-/Performance-Problem entstehen.

## 13. Non-Goals ohne neuen fachlichen Grund

- generische Visualization Engine;
- ViewSpec DSL;
- Event Bus / Event Sourcing Framework;
- vorsorglicher serverweiter Token-Stream-Broadcaster;
- automatischer AI Router;
- Discovery-Provenance-Persistenz;
- Multi-Mint-Vergleich;
- operative Mutation durch Frontend, Analyst oder Telemetry.

## Completion Principle

Der Functional Core ist richtig geschnitten, wenn neue read-only Views oder Evidence-Consumer hinzugefügt werden können, ohne Population, Search, Selection, SSE, Inspector oder Analyst grundlegend neu zu bauen. Der Telemetry-Pfad ist richtig geschnitten, wenn er reale operative Arbeit beobachtbar macht, ohne selbst Teil dieses operativen Flows zu werden. Presentation bleibt austauschbar und darf keine Domain-Wahrheit übernehmen.
