# Architecture

## Zweck

`jupiter-data-transform` trennt operative Datensammlung, persistierte Beobachtung, operative Lifecycle-Entscheidungen und read-only Downstream-Nutzung.

Der operative Core entdeckt Solana-Mints, beobachtet deren Jupiter-Zustände, persistiert tatsächlich beobachtete Source-Versionen und reduziert die aktive Population anhand eines expliziten Lifecycle-Contracts. Observatory, Analyst und Research lesen diese Daten, besitzen aber keine operative Mutation-Authority.

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
lifecycle_clean.py      24h Raw Retention
lifecycle_queries.py
lifecycle_rules.py
        ↓
tracking_enabled=false
        ↓
READ-ONLY DOWNSTREAM
Observatory / Analyst / Research
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

**Discovery Provenance als dauerhaft nutzbare Relation ist derzeit kein abgeschlossener Architekturvertrag.** Eine spätere Darstellung von `Discovery Source -> Mint -> Observation` darf deshalb erst implementiert werden, wenn diese Relation tatsächlich persistiert oder anderweitig read-only beweisbar ist.

## 3. Operativer Jupiter-Refresh

`src/refresh.py` überwacht aktive Mints einer Priority. Mehrere API-Key-Lanes arbeiten mit Jupiter Search; ein Request umfasst maximal 100 Mint-Adressen.

Netzwerk-I/O und blockierende PostgreSQL-Writes sind getrennt. Erfolgreiche Search-Antworten werden über die `WriteQueue` an `MintRepository` übergeben.

Die Queue darf identische `(mint, updatedAt)`-Antworten innerhalb ihres Buffers zusammenfassen, aber keine unterschiedlichen tatsächlich beobachteten Jupiter-Source-Versionen eines Mints verwerfen.

## 4. Persistenz und Beobachtungssemantik

`src/repository.py` besitzt Collector-Persistenz und ausdrücklich erlaubte operative Datenbank-Mutationen.

### `mints`

Die operative Registry hält langlebige Mint-Fakten sowie Collector-/Lifecycle-Zustand:

- `first_observed_at`: erste vom Collector persistierte Jupiter-Source-Version;
- `last_polled_at`: letzter erfolgreicher Search-Poll;
- `last_changed_at`: lokale Beobachtungszeit der jüngsten neuen Source-Version;
- `source_updated_at`: jüngster persistierter Jupiter-`updatedAt`-Wert;
- `tracking_enabled`: ob der Mint weiter beobachtet wird;
- `disabled_at`: Zeitpunkt einer Lifecycle-Deaktivierung;
- `disabled_reason`: persistierter Disable-Reason.

### `mint_snapshots`

`mint_snapshots` hält die hochaufgelöste Raw-Historie tatsächlich beobachteter Jupiter-Source-Versionen.

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

**Snapshot-Abstände sind keine Poll-Abstände.** Fehlende Zwischen-Snapshots bedeuten nicht, dass der Collector nicht gepollt hat.

`mint_snapshots` ist ein 24-Stunden-Raw-Working-Buffer und kein unbegrenztes Langzeitarchiv. `src/maintenance.py` führt beim Collector-Start und danach stündlich gebatchte Cleanup-Läufe aus. Gelöscht werden ausschließlich Rows vor dem globalen `observed_at`-Cutoff; Retention besitzt keine per-Mint- oder Lifecycle-Sonderlogik.

## 5. Operational Lifecycle

Der operative Lifecycle ist ein eigenständiger Mutationspfad und darf `tracking_enabled=false` setzen.

Die fachliche Semantik von Rule 1–7 ist in [`LIFECYCLE_CONTRACT.md`](LIFECYCLE_CONTRACT.md) als Contract v0.3 eingefroren. Rule 1–5 sind unverändert aus v0.1 übernommen. Rule 6 ergänzt einen catch-up-fähigen T+30-Checkpoint auf frühe Holder-Distribution. Rule 7 ergänzt persistente Source-Inactivity: ein bereits beobachteter Mint wird deaktiviert, wenn `last_polled_at` frisch ist und `last_changed_at` seit mindestens 24 Stunden unverändert blieb. Rule 7 liest dafür ausschließlich langlebige Collector-Timestamps aus `mints` und benötigt keinen Raw-Snapshot. Änderungen an Thresholds, Zeitfenstern, T0, Evidence-Auswahl, Missing-Semantik, Reasons oder Regelreihenfolge sind Contract-Änderungen.

```text
LifecycleQueries
      ↓ evidence
Lifecycle Rules
      ↓ reason
lifecycle_clean.py
      ↓ contract-defined ordering / mode
MintRepository.disable_mints()
      ↓
tracking_enabled=false
+ disabled_at
+ disabled_reason
```

- `src/lifecycle_queries.py`: read-only Lifecycle-Evidence;
- `src/lifecycle_rules.py`: reine Regelentscheidungen;
- `src/lifecycle_clean.py`: Orchestrierung und Dry-Run/Apply-Modus;
- `MintRepository.disable_mints()`: operative Deaktivierung.

`tools/verify_lifecycle_contract_v01.py` bleibt bewusst auf Rule 1–5 begrenzt und beweist deren Äquivalenz zur eingefrorenen v0.1-Referenz. Rule 6 und Rule 7 werden separat über Contract v0.3 und gezielte Unit-Tests validiert.

Rule 7 trennt Poll-Fortschritt und Source-Fortschritt explizit: ein frischer `last_polled_at` beweist eine weiterhin erfolgreiche Jupiter-Search-Antwort, während ein alter `last_changed_at` beweist, dass seitdem keine neuere Jupiter-`updatedAt`-Version persistiert wurde. Die 24h-Retention ist weiterhin ausschließlich Storage-Maintenance und keine Lifecycle-Evidence.

## 6. Read-only Downstream Boundary

Downstream-Code darf operative Daten lesen und eigene Projektionen, Visualisierungen oder Analysen erzeugen.

Er darf nicht:

- `tracking_enabled` verändern;
- operative Priority verändern;
- Lifecycle-State oder Thresholds verändern;
- Collector-owned Observation State überschreiben;
- Research-, UI- oder externe Evidence stillschweigend zu Lifecycle-Regeln machen.

Diese Grenze gilt für Research-Skripte, Browser, Analyst und externe Evidence-Adapter gleichermaßen.

## 7. Observatory Functional Core

Das Observatory läuft als separater read-only FastAPI-/Browser-Prozess unter `src/observatory/`.

Der Functional Core ist nach der Konsolidierung in Issue #20 / PR #21, der finalen Synchronisationskorrektur in PR #24 und dem First-Principles-Simplification-Slice PR #32 abgeschlossen.

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
    └── concrete View
```

### Browser-Verantwortungen

```text
static/js/
├── app.js                 composition / wiring + shell presentation
├── api.js                 HTTP + SSE
├── state.js               population + selection + event application
├── search.js              pure search/ranking
├── activity.js            derived live signals
├── token-ui.js            Search + Inspector DOM
├── activity-ui.js         Activity DOM
├── analyst-ui.js          Analyst interaction + focus presentation
├── markdown.js            safe Analyst Markdown-subset rendering
├── telemetry-ui.js        volatile operational telemetry projection
└── views/
    └── simple-token-view.js
```

`state.js` besitzt die Domain-Population und `selectedMint`. Search, Activity, Telemetry und Presentation State gehören nicht hinein.

Die aktuelle `SimpleTokenView` ist ein austauschbarer funktionaler Proof und kein Designvertrag. Presentation-Werte wie `x/y`, Radius, Farbe, Opacity, D3/Pixi-State oder Clusterpositionen sind keine Functional-Core-Truth.

### Selection

Die Selection ist ausschließlich der Mint. Search, View, Activity und Analyst dürfen Selection anfordern; keiner dieser Consumer besitzt sie.

Ein kürzlich retired Token kann als selected-token Context erhalten bleiben, ohne wieder Teil der aktiven Population zu werden.

### Visual Shell WP1

Visual WP1 ergänzt ausschließlich Presentation und wurde lokal im realen Browser akzeptiert.

```text
TOPBAR

MAIN STAGE                         RIGHT CONTEXT
current/future visualization      selected token + analyst + live deltas
                                  resize / collapse

SECONDARY RUNTIME CONTEXT
operational telemetry proof
```

- Main Stage bleibt dominant.
- Right Context ist auf Desktop zwischen 360px und 640px resizebar und kann collapsed/restored werden.
- Collapse/Resize verändern keinen Population-, Selection- oder Analyst-State.
- Search bleibt vollständiger Zugriff auf die aktive Population.
- Inspector zeigt die vollständige Mint-Adresse und bietet Copy.
- bestehende Token-Fakten bleiben erhalten.
- Panelbreite, Collapse-State und andere Layoutwerte sind Presentation State, keine Domain Truth.
- aktuelle Token-Kacheln und Telemetry-Karten bleiben Visual-Proofs; Bubble Map und Operational Flow werden in eigenen Slices definiert.

### Analyst Focus WP2

Visual WP2 ergänzt ebenfalls ausschließlich Presentation und wurde lokal im realen Browser akzeptiert.

- derselbe Analyst bleibt idle im Right Context und wird im Focus-State als großer Research-Workspace über der Main Stage dargestellt;
- es gibt keinen zweiten Analyst-State, keine zweite Route und keine Conversation-Persistenz;
- Submit öffnet Focus automatisch; Close/Escape stellt denselben UI-Zustand wieder im Right Context dar;
- User-Frage, LLM-Antwort und Evidence/Sources besitzen getrennte visuelle Bereiche;
- lange Antworten scrollen innerhalb des Research-Bereichs;
- Antwort ist kopierbar;
- ein kleiner `markdown.js`-Renderer stellt nur einen sicheren Markdown-Subset über explizite DOM-Nodes dar und injiziert kein Modell-HTML;
- Current Data, Web, Temporal und RugCheck behalten ihre bestehenden Backend-/Evidence-Verträge;
- Mermaid oder andere Diagramm-Renderer sind kein Bestandteil dieses Presentation-Slices.

## 8. Observatory Synchronisationsvertrag

`/api/events` besitzt eine explizite Synchronisationsgrenze:

```text
connect / reconnect
      ↓
universe_snapshot
      ↓
universe_delta*
```

Jede SSE-Verbindung sendet zuerst einen vollständigen `universe_snapshot`. **Genau derselbe Snapshot ist die Server-Baseline für nachfolgende Deltas.** Damit gibt es keine undefinierte Lücke zwischen Browserzustand und Stream-Baseline.

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

Fingerprint und numerische Changes werden aus demselben Contract abgeleitet. Missing bleibt unknown.

`GET /api/token/{mint}` ist ein Selected-Detail-Read. Seine Antwort wird **nicht** als zweiter beliebiger Update-Pfad in die Population geschrieben.

Der heutige SSE-Producer erzeugt Deltas weiterhin durch per-Connection Snapshot/Diff-Polling. Das ist bewusst akzeptierte Skalierungsschuld, kein dauerhafter Event-Infrastrukturvertrag. Ein gemeinsamer Broadcaster oder Event Replay wird erst eingeführt, wenn reale Messungen oder neue Anforderungen ihn rechtfertigen.

## 9. Live Operational Telemetry

Die Live-Telemetrie ist ein separater flüchtiger Beobachtungspfad für den realen operativen Datenfluss. Sie besitzt keine Mutation- oder Persistenz-Authority.

```text
Discovery / Search / WriteQueue / Lifecycle
                ↓
       localhost UDP best effort
                ↓
      Observatory bounded RAM buffer
                ↓
      telemetry snapshot + SSE
                ↓
       deterministic <=1 Hz UI
```

Produzenten emittieren kleine strukturierte Events unmittelbar nach realer Arbeit:

```text
discovery_tick
search_lane_tick
search_flush
lifecycle_tick
```

Der Observatory-Prozess bindet standardmäßig nur localhost, hält maximal zehn Minuten Telemetrie im RAM und verwirft sie bei Neustart. Es gibt keine Telemetrie-Tabelle, keine Disk-Persistenz, keinen Broker, kein Alerting und kein Event Sourcing. API Keys und Mint-Listen gehören nicht in Telemetrie-Payloads.

Die Telemetrie besitzt einen eigenen Transportvertrag:

```text
GET /api/telemetry
GET /api/telemetry/events
```

`/api/telemetry/events` startet mit `telemetry_snapshot` und liefert danach `telemetry_event`. Dieser Stream ist bewusst getrennt vom kanonischen Token-Stream `/api/events`.

### Population semantics

Zwei sichtbare Zahlen beantworten unterschiedliche Fragen:

- Observatory `ACTIVE`: Größe der aktuell vom `FrontendReader` projizierten Token-Population. Der heutige Read-Model-Pfad benötigt `tracking_enabled=true` und einen verfügbaren jüngsten Raw-Snapshot.
- Lifecycle Telemetry `TRACKING`: `active_remaining` aus dem operativen Lifecycle, also die Anzahl aller Rows in `mints` mit `tracking_enabled=true`.

Beide Zahlen sollten im stabilen Betrieb eng zusammenliegen, sind aber **nicht als identische Messung definiert**. Kleine Abweichungen sind zulässig, weil Lifecycle und Observatory unabhängig lesen und weil ihre Projektionsgrenzen verschieden sind. Lifecycle v0.3 / Rule 7 entfernt langfristig frisch gepollte Mints ohne Source-Fortschritt und hat dadurch die zuvor große Differenz praktisch beseitigt; die Semantik der beiden Zähler bleibt trotzdem getrennt.

`lifecycle_tick.breakdown` zeigt Rule 1–7. Telemetrie interpretiert diese Regeln nicht neu, sondern projiziert ausschließlich das Ergebnis des realen Lifecycle-Cycles.

## 10. Observatory Backend-Endpunkte

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

`FrontendReader` verwendet read-only PostgreSQL-Verbindungen. Observatory-Endpunkte besitzen keine operative Mutation.

## 11. Analyst und Model Policy

Der Analyst besitzt vier explizite Use Cases. Modellwahl ist serverseitige Use-Case-Policy und keine UI-Verantwortung.

Aktuelle Defaults:

```text
current_data -> FAST   -> ministral-14b-latest
web          -> STRONG -> mistral-large-latest
temporal     -> STRONG -> mistral-large-latest
rugcheck     -> STRONG -> mistral-large-latest
```

Konfiguration:

```text
MISTRAL_MODEL_FAST
MISTRAL_MODEL_STRONG
MISTRAL_WEB_SEARCH_MODE
```

### Current Data

```text
free population question
      ↓
FAST model
      ↓
bounded query_tokens arguments
      ↓
current active rows
      ↓
grounded answer
```

`src/observatory/tools.py` besitzt den internen Tool-Vertrag. Das Modell erhält weder SQL noch Datenbankzugriff. Unsupported oder mehrdeutige Fragen dürfen keine nicht vorhandene Metrik durch einen Proxy ersetzen.

Der aktuelle FAST-Default `ministral-14b-latest` wurde gegen den realen `query_tokens`-Regressionsvertrag ausgewählt; der Tool-Vertrag wurde dafür nicht abgeschwächt.

### Web Research

```text
selected exact Mint + question
      ↓
Mistral Web Search
      ↓
answer + external references
```

Exact Mint ist die Identitätsgrenze. Web-Ergebnisse bleiben externe Evidence.

### Temporal Summary

```text
selected exact Mint
      ↓
deterministic <=24h summary
      ↓
STRONG model
      ↓
interpretation
```

Der produktive Temporal-Pfad sendet keine Raw-History und keine Zeit-Buckets an das Modell. Die Zusammenfassung ist read-only und bounded.

### RugCheck

```text
selected exact Mint
      ↓
direct RugCheck report
      ↓
deterministic compact metadata projection
      ↓
STRONG model
      ↓
safety-evidence interpretation
```

RugCheck bleibt externe Evidence. Die Projektion und Interpretation treffen keine operative Lifecycle-Entscheidung.

## 12. Visualisierung — nächste Grenze

WP1 und WP2 haben Shell und Analyst-Presentation akzeptiert. Der nächste Visual-Slice ist die Token-Universe-Bubble-Map. Sie darf Domain-Fakten auf Position, Größe, Verbindung und Motion abbilden, aber diese Presentation-Werte bleiben derived und dürfen nicht in den Functional Core zurückgeschrieben werden.

Der Operational Flow folgt danach als separater Telemetry-Visual-Slice. Eine per-Mint Discovery-Provenance darf dabei nicht erfunden werden.
