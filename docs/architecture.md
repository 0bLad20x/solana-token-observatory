# Architecture

## Zweck

`jupiter-data-transform` trennt operative Datensammlung, persistierte Beobachtung, operative Lifecycle-Entscheidungen und read-only Downstream-Nutzung.

Der operative Core entdeckt Solana-Mints, beobachtet deren Jupiter-Zustände, persistiert tatsächlich beobachtete Source-Versionen und reduziert die aktive Population anhand eines expliziten Lifecycle-Contracts. Observatory, Analyst, Telemetry und Research lesen bzw. projizieren diese Daten, besitzen aber keine operative Mutation-Authority.

## Systemübersicht

```text
DISCOVERY
PumpPortal / Jupiter Recent / Meteora
        ↓
PostgreSQL: mints
        ↓
JUPITER MONITORING
Search lanes -> WriteQueue -> Repository
        ↓
mints + mint_snapshots
        ↓                 ↓
OPERATIONAL LIFECYCLE   SNAPSHOT MAINTENANCE
R1-R7                   24h Raw Retention
        ↓
tracking_enabled=false
        ↓
READ-ONLY DOWNSTREAM
Observatory / Analyst / Telemetry / Research
```

## 1. Datenbank-Infrastruktur

`src/database.py` besitzt den process-wide PostgreSQL-ConnectionPool. Persistente Schemaänderungen erfolgen ausschließlich explizit in `src/schema.sql`.

Diese Schicht stellt Verbindungen bereit, enthält aber keine Discovery-, Collector-, Lifecycle- oder Downstream-Fachlogik.

## 2. Discovery

`src/discovery.py` entdeckt Mint-Adressen über externe Quellen wie:

- PumpPortal `subscribeNewToken`;
- Jupiter `/tokens/v2/recent`;
- Meteora DAMM v2;
- Meteora DLMM.

Discovery liefert Kandidaten-Mints. Sie bewertet keine wirtschaftliche Qualität und trifft keine Lifecycle-Entscheidungen. Neue Mints werden über `MintRepository` in die zentrale Registry aufgenommen.

**Discovery Provenance als dauerhafte Relation `Source -> konkrete Mint` ist kein abgeschlossener Architekturvertrag.** Telemetry darf Quellmengen visualisieren, aber keine per-Mint Provenance erfinden.

## 3. Operativer Jupiter-Refresh

`src/refresh.py` überwacht aktive Mints über parallele Jupiter-Search-Lanes. Ein Request umfasst maximal 100 Mint-Adressen.

Netzwerk-I/O und PostgreSQL-Writes sind getrennt. Erfolgreiche Search-Antworten werden über die `WriteQueue` an `MintRepository` übergeben.

Die Queue darf identische `(mint, updatedAt)`-Antworten innerhalb ihres Buffers zusammenfassen, aber keine unterschiedlichen tatsächlich beobachteten Jupiter-Source-Versionen eines Mints verwerfen.

## 4. Persistenz und Beobachtungssemantik

`src/repository.py` besitzt Collector-Persistenz und ausdrücklich erlaubte operative Datenbank-Mutationen.

### `mints`

Die Registry hält langlebige Mint-Fakten sowie Collector-/Lifecycle-Zustand:

- `first_observed_at`: erste persistierte Jupiter-Source-Version;
- `last_polled_at`: letzter erfolgreicher Search-Poll;
- `last_changed_at`: lokale Beobachtungszeit der jüngsten neuen Source-Version;
- `source_updated_at`: jüngster persistierter Jupiter-`updatedAt`-Wert;
- `tracking_enabled`;
- `disabled_at`;
- `disabled_reason`.

### `mint_snapshots`

`mint_snapshots` hält die hochaufgelöste Raw-Historie tatsächlich beobachteter Source-Versionen.

```text
Jupiter Search erfolgreich
        │
        ├─ updatedAt bereits bekannt
        │      -> last_polled_at fortschreiben
        │      -> kein redundanter Snapshot
        │
        └─ neue updatedAt-Version(en)
               -> jede beobachtete Version persistieren
               -> source_updated_at fortschreiben
               -> last_changed_at aktualisieren
               -> last_polled_at fortschreiben
```

**Poll und Snapshot sind verschiedene Ereignisse.** Fehlende Zwischen-Snapshots bedeuten nicht, dass der Collector nicht gepollt hat.

`mint_snapshots` ist ein 24h Raw-Working-Buffer. `src/maintenance.py` löscht gebatcht Rows vor dem globalen `observed_at`-Cutoff. Retention besitzt keine per-Mint- oder Lifecycle-Sonderlogik.

## 5. Operational Lifecycle

Der Lifecycle ist der eigenständige Mutationspfad für `tracking_enabled=false`.

Die fachliche Semantik von Rule 1–7 ist in [`LIFECYCLE_CONTRACT.md`](LIFECYCLE_CONTRACT.md) als Contract v0.3 eingefroren.

- Rule 1–5 sind unverändert aus v0.1 übernommen.
- Rule 6 ergänzt einen catch-up-fähigen T+30-Checkpoint auf frühe Holder-Distribution.
- Rule 7 ergänzt persistente Source-Inactivity auf Basis langlebiger Collector-Timestamps.

```text
LifecycleQueries
      ↓ evidence
Lifecycle Rules
      ↓ reason
lifecycle_clean.py
      ↓ ordering / dry-run / apply
MintRepository.disable_mints()
      ↓
tracking_enabled=false
+ disabled_at
+ disabled_reason
```

`tools/verify_lifecycle_contract_v01.py` bleibt bewusst auf Rule 1–5 begrenzt. Rule 6 und Rule 7 werden über Contract v0.3 und gezielte Tests validiert.

Die 24h-Retention ist Storage-Maintenance und keine Lifecycle-Evidence.

## 6. Read-only Downstream Boundary

Observatory, Analyst, Telemetry und Research dürfen operative Daten lesen und eigene Projektionen bzw. Interpretationen erzeugen.

Sie dürfen nicht:

- `tracking_enabled` verändern;
- operative Priority verändern;
- Lifecycle-State oder Thresholds verändern;
- Collector-owned Observation State überschreiben;
- externe Evidence oder UI-Derivationen stillschweigend zu Lifecycle-Truth machen.

## 7. Observatory Functional Core

Das Observatory läuft separat unter `src/observatory/`. Der Functional Core ist abgeschlossen und bleibt unabhängig von konkreter Presentation.

```text
PostgreSQL
    ↓
FrontendReader
    ↓
Browser IO
    ↓
Population State + selected Mint
    ├── Search
    ├── Inspector
    ├── Derived Activity
    ├── Analyst
    └── Main-Stage Views
```

Browser-Verantwortungen:

```text
static/js/
├── app.js                         composition / wiring / shell
├── api.js                         HTTP + SSE
├── state.js                       population + selection + event application
├── search.js                      pure search/ranking
├── activity.js                    derived live signals
├── token-ui.js                    Search + Inspector DOM
├── activity-ui.js                 Live Deltas DOM
├── analyst-ui.js                  Analyst interaction + focus workspace
├── markdown.js                    safe Markdown-subset rendering
├── telemetry-ui.js                volatile telemetry projection
└── views/
    ├── token-universe-view.js      launchpad Token Universe
    └── operational-flow-view.js   live operational dataflow
```

`state.js` besitzt die Domain-Population und `selectedMint`. Search, Activity, Telemetry und Presentation State gehören nicht hinein.

### Selection

Die Selection ist ausschließlich der Mint. Search, Universe, Activity und Analyst dürfen Selection anfordern; keiner dieser Consumer besitzt sie.

Ein kürzlich retired Token kann als selected-token Context erhalten bleiben, ohne wieder Teil der aktiven Population zu werden.

### Presentation ist keine Domain Truth

Folgende Werte gehören ausdrücklich nicht in den Functional Core:

```text
x / y
radius
color / halo / opacity
cluster center
panel width
Canvas/D3/Pixi state
animation progress
```

Eine View darf dieselben Domain-/Telemetry-Fakten anders darstellen, ohne den Core umzudeuten.

## 8. Akzeptierte Observatory Presentation

Der definierte Visual-Checkpoint WP1–WP4 ist abgeschlossen.

### WP1 — Visual Shell

- dominante One-Screen Main Stage;
- Right Context auf Desktop resizebar und ein-/ausblendbar;
- Collapse/Resize verändert keinen Domain-, Selection- oder Analyst-State;
- vollständige Mint-Adresse mit Copy;
- größere lesbare Typografie.

### WP2 — Analyst Focus

- derselbe Analyst lebt idle im Right Context und kann als großer Focus-Workspace über der Main Stage erscheinen;
- Submit öffnet Focus automatisch; Close/Escape erhält denselben Zustand;
- Frage, LLM-Antwort und Evidence/Sources sind visuell getrennt;
- lange Antworten scrollen im Research-Bereich;
- `markdown.js` rendert einen kleinen sicheren Markdown-Subset über explizite DOM-Nodes;
- keine Conversation-History und keine neue Analyst-Semantik.

### WP3 — Token Universe

Die aktive Population wird launchpad-zentriert dargestellt.

Data-to-Visual-Vertrag:

- Cluster = Launchpad-Zugehörigkeit;
- Bubble-Größe = Market Cap;
- Liquidity = separater Halo;
- Holder Count beeinflusst die Membership-Verbindung im Fokus;
- Launchpads sind ein-/ausblendbar;
- Zoom/Pan;
- adaptive stabile Cluster statt permanenter Force-Physics;
- `token_added`, relevante Market-Cap-Updates und `token_retired` besitzen semantische Motion;
- User-Filter bleibt Authority über Sichtbarkeit.

### WP4 — Operational Flow

Die Runtime wird aus bestehenden Telemetry-Fakten dargestellt:

```text
Discovery -> Admission -> Search -> Write -> Lifecycle -> Tracking
                                              └-> retired
                         ^                         |
                         └──── monitoring loop ────┘
```

Data-to-Visual-Vertrag:

- Discovery: `raw intake -> dedupe -> new`;
- Discovery-Ticks: bounded mengenabhängige Bursts; Latenz begrenzt die Bewegungsdauer;
- Search: reale parallele Lanes; frische `search_lane_tick`s erzeugen Work-Pakete;
- Write: große Kondensationsregion `polls -> source versions -> snapshots`; `search_flush` erzeugt eine sichtbare Kompressionswelle;
- Lifecycle: R1–R7 als Gates; `lifecycle_tick` erzeugt Sweep, reale Rule-Breakdowns speisen Retirement/Candidate-Sink;
- Tracking: Survivor-Reservoir;
- große Tracking-Zahl = kanonische Browser-Population, damit sie mit Topbar `ACTIVE` synchron ist;
- `lifecycle.active_remaining` bleibt als Stand des letzten Lifecycle-Cycles im Detail erhalten;
- Tracking->Search = kontinuierlicher rate-codierter Monitoring-Current aus aggregiertem Search-RPM und beobachteter Latenz.

Count-Marks und Work-Pakete sind Mengen-/Arbeitskodierungen und niemals behauptete Mint-Identitäten.

## 9. Observatory Synchronisationsvertrag

`/api/events` besitzt die autoritative Browser-Synchronisationsgrenze:

```text
connect / reconnect
      ↓
universe_snapshot
      ↓
universe_delta*
```

Deltas verwenden:

```text
token_added
token_updated
token_retired
```

`src/observatory/delta.py` besitzt den kanonischen numerischen Change-Vertrag für:

```text
market_cap
liquidity
holders
trades_5m
traders_5m
volume_5m
```

`GET /api/token/{mint}` ist eine read-only Detail-Capability und kein zweiter Population-Updatepfad.

Der heutige SSE-Producer erzeugt Deltas weiterhin per Connection durch Snapshot/Diff-Polling. Ein gemeinsamer Broadcaster oder Event Replay wird erst eingeführt, wenn reale Messungen oder Anforderungen ihn rechtfertigen.

## 10. Live Operational Telemetry

Telemetry ist ein separater flüchtiger Beobachtungspfad:

```text
Discovery / Search / WriteQueue / Lifecycle
                ↓
       localhost UDP best effort
                ↓
      Observatory bounded RAM buffer
                ↓
      telemetry snapshot + SSE
                ↓
       Browser Flow View
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

Der RAM-Buffer ist standardmäßig auf zehn Minuten begrenzt und wird bei Neustart verworfen. Es gibt keine Telemetrie-Tabelle, keine Disk-Persistenz, keinen Broker, kein Alerting und kein Event Sourcing. API Keys und Mint-Listen gehören nicht in Telemetry-Payloads.

### Population semantics

Der Operational Flow zeigt als große Tracking-Zahl bewusst **die kanonische aktuelle Browser-Population**, also denselben Messpunkt wie Topbar `ACTIVE`.

`lifecycle_tick.active_remaining` bleibt ein anderer Fakt: `tracking_enabled=true` zum Zeitpunkt des letzten Lifecycle-Cycles. Dieser Wert wird nur als Lifecycle-Cycle-Kontext dargestellt und darf wegen unterschiedlicher Takte von der aktuellen Browser-Population abweichen.

Damit werden zwei verschiedene Messpunkte nicht mehr als konkurrierende große UI-Zahlen präsentiert.

## 11. Observatory Backend-Endpunkte

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

Observatory-Endpunkte besitzen keine operative Mutation.

## 12. Analyst und Model Policy

Der Analyst besitzt vier explizite Use Cases:

```text
current_data -> FAST   -> ministral-14b-latest
web          -> STRONG -> mistral-large-latest
temporal     -> STRONG -> mistral-large-latest
rugcheck     -> STRONG -> mistral-large-latest
```

### Current Data

Freie Fragen werden in bounded `query_tokens`-Argumente übersetzt. Das Modell erhält weder SQL noch beliebigen Datenbankzugriff.

### Web Research

Exact Mint ist die Identitätsgrenze. Ergebnisse bleiben External Evidence.

### Temporal Summary

Ein deterministischer `<=24h` Summary wird in genau einem STRONG-Modell-Request interpretiert. Raw-History und 1m/5m/15m-Buckets werden nicht an das LLM gesendet.

### RugCheck

Der direkte Provider-Report bleibt Evidence. Die LLM-Interpretation verwendet die deterministische kompakte `rugcheck_analysis_v4`-Projektion ohne einzelne Wallet-Adressen. Keine Persistence und keine Lifecycle-Mutation.

## 13. Truth Layers

Das Observatory unterscheidet:

1. **System Truth:** persistierte oder direkt gelesene operative Fakten.
2. **Deterministic Analysis:** reproduzierbare Derived Values.
3. **Runtime Telemetry:** flüchtige Beobachtung realer Arbeit.
4. **External Evidence:** Web und RugCheck.
5. **LLM Interpretation:** probabilistische Interpretation ohne operative Authority.

Keine Ebene darf stillschweigend in eine stärkere Truth-Klasse hochgestuft werden.

## 14. Aktuelle Architekturgrenze

Die operative, funktionale und definierte visuelle Foundation steht:

```text
Discovery
   ↓
Monitoring
   ↓
24h Raw Observations
   ↓
Lifecycle v0.3
   ↓
Survivor Population
   ↓
Read-only Observatory
   ├── Token Universe
   ├── Live Operational Flow
   ├── Inspector + Live Deltas
   └── Analyst
       ├── Current Data
       ├── Web Evidence
       ├── Temporal Summary
       └── RugCheck Evidence
```

Es gibt derzeit kein weiteres beschlossenes Frontend-Design-Arbeitspaket. Neue Presentation- oder Evidence-Arbeit wird nur aus einer konkreten Produktfrage, einem realen Usability-/Performance-Problem oder einem neuen beweisbaren Datenvertrag abgeleitet.

Der aktuelle Checkpoint steht in [`MILESTONES.md`](MILESTONES.md).

## 15. Authority-Modell

| Frage | Authority |
|---|---|
| Was ist das Projekt und wie wird es benutzt? | `README.md` |
| Wie fließen Daten und wer besitzt welche Verantwortung? | `docs/architecture.md` |
| Wie funktioniert der operative Lifecycle fachlich exakt? | `docs/LIFECYCLE_CONTRACT.md` |
| Welche funktionalen Produkt-/Truth-Grenzen gelten für das Observatory? | `docs/FRONTEND_OBSERVATORY.md` |
| Wo steht das Projekt und welche Entscheidung ist als Nächstes offen? | `docs/MILESTONES.md` |
| Welche Regeln gelten für Repository-Änderungen? | `AGENTS.md` |

## 16. Architekturprinzipien

1. **Eine Verantwortung, ein Owner.**
2. **Poll und Snapshot sind verschiedene Ereignisse.**
3. **Source-Versionen gehen nicht durch Writer-Coalescing verloren.**
4. **Raw-Auflösung ist temporär.**
5. **Missing bleibt missing.**
6. **Lifecycle-Semantik ist versioniert.**
7. **Downstream ist read-only gegenüber operativem State.**
8. **Presentation ist keine Functional-Core-Truth.**
9. **Operational Telemetry ist flüchtige Beobachtung, keine operative Authority.**
10. **External Evidence ist keine Jupiter- oder Lifecycle-Truth.**
11. **LLM-Interpretation besitzt keine operative Authority.**
12. **Generierte Daten sind Evidence, nicht Architektur.**
13. **Roadmap ist keine Implementation.**
