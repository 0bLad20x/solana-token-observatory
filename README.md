# jupiter-data-transform

`jupiter-data-transform` entdeckt Solana-Mints, beobachtet deren Jupiter-Zustände, hält eine begrenzte hochaufgelöste Raw-Historie, reduziert die operative Population über einen versionierten Lifecycle und projiziert den laufenden Zustand read-only in das Token Observatory.

## System in einem Satz

```text
Discovery -> Jupiter Monitoring -> Persistence -> Lifecycle -> Read-only Observatory / Research
```

Der operative Core besitzt vier Verantwortungen:

1. **Discovery:** neue Mint-Adressen aus externen Quellen aufnehmen.
2. **Monitoring:** aktive Mints über Jupiter Tokens V2 Search beobachten.
3. **Persistence:** tatsächlich beobachtete Jupiter-Source-Versionen persistieren und über eine begrenzte Retention pflegen.
4. **Operational Lifecycle:** Tokens anhand des eingefrorenen Lifecycle-Contracts deaktivieren.

Frontend, Analyst, Telemetry und Research sind read-only Downstream-Consumer und besitzen keine operative Mutation-Authority.

## Datenfluss

```text
Discovery sources
    ↓
PostgreSQL: mints
    ↓
Jupiter Search lanes
    ↓
WriteQueue -> MintRepository
    ↓
mints + mint_snapshots
    ↓              ↓
Lifecycle     Snapshot Maintenance
    ↓              ↓
tracking_enabled   24h Raw Retention
    ↓
Read-only Observatory / Research
```

Ein erfolgreicher Poll und ein neuer Snapshot sind verschiedene Ereignisse:

- `first_observed_at`: erste persistierte Jupiter-Source-Version;
- `last_polled_at`: letzter erfolgreicher Search-Poll;
- `last_changed_at`: lokale Beobachtungszeit der jüngsten neuen Source-Version;
- `source_updated_at`: jüngster persistierter Jupiter-`updatedAt`-Wert;
- `mint_snapshots`: immutable Historie tatsächlich beobachteter Source-Versionen innerhalb des 24h-Raw-Buffers.

Unveränderte Antworten aktualisieren `last_polled_at`, erzeugen aber keinen redundanten Snapshot.

## Voraussetzungen

- Python 3.14
- PostgreSQL
- Jupiter API Key(s)
- PumpPortal API Key für die entsprechende Discovery-Quelle
- Mistral API Key für die Analyst-Funktionen

## Installation

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -r requirements-frontend.txt
Copy-Item .env.example .env
```

Danach lokale Zugangsdaten in `.env` eintragen. `.env` wird nicht committed.

## Collector

Schema initialisieren:

```powershell
python src/main.py init-schema
```

Collector starten:

```powershell
python src/main.py run
```

Discovery, Jupiter-Refresh und Snapshot-Maintenance laufen parallel. Die Maintenance führt beim Start und danach stündlich einen gebatchten 24h-Retention-Lauf aus.

## Operational Lifecycle

```powershell
# Dry-Run
python src/lifecycle_clean.py --once

# einmalig anwenden
python src/lifecycle_clean.py --apply --once

# Dauerbetrieb
python src/lifecycle_clean.py --apply
```

Mit `--apply` setzt ausschließlich der definierte Lifecycle-Pfad `tracking_enabled=false` und persistiert `disabled_at` sowie `disabled_reason`.

Die fachliche Semantik von Rule 1–7 ist in [`docs/LIFECYCLE_CONTRACT.md`](docs/LIFECYCLE_CONTRACT.md) als Contract v0.3 eingefroren.

- Rule 6: T+30 Early Holder Failure, `holderCount < 5` bei vorhandener Checkpoint-Evidence.
- Rule 7: Persistent Source Inactivity bei weiterhin frischen Polls und mindestens 24h ohne neue Source-Version.

Rule 1–5 bleiben gegenüber v0.1 unverändert. Der bestehende Verifier prüft weiterhin genau diese geerbten Regeln:

```powershell
python tools/verify_lifecycle_contract_v01.py
```

## Token Observatory

Start:

```powershell
python src/frontend.py
```

Standardmäßig unter `http://127.0.0.1:8000`.

Der Browser besitzt genau eine kanonische aktive Population und einen `selected Mint`. Search, Universe, Inspector, Activity und Analyst konsumieren denselben State.

Die Live-Synchronisation besitzt eine explizite Grenze:

```text
connect / reconnect
      ↓
full universe_snapshot
      ↓
subsequent universe_delta events
```

`GET /api/token/{mint}` bleibt eine read-only Detail-Capability und schreibt nicht als zweiter Pfad in die Population.

### Akzeptierte Visual-Slices

Der definierte Observatory-Visual-Checkpoint ist abgeschlossen:

```text
WP1  Visual Shell / Typography / Inspector   ✓
WP2  Analyst Focus Workspace                 ✓
WP3  Launchpad Token Universe                ✓
WP4  Live Operational Flow                   ✓
```

#### Universe

Die Token-Population wird als launchpad-zentrierte Bubble Map dargestellt:

- Launchpads einzeln ein-/ausblendbar;
- Zoom/Pan;
- Bubble-Größe = Market Cap;
- Liquidity = separater Halo;
- Holder Count beeinflusst die Membership-Verbindung im Fokus;
- adaptive stabile Cluster ohne permanente Force-Physics;
- semantische Add/Market-Cap-Update/Retire-Motion;
- Click verwendet dieselbe Selection für Inspector und Analyst.

#### Flow

Die operative Runtime wird als Live-Datenfluss dargestellt:

```text
Discovery -> Admission -> Search -> Write -> Lifecycle -> Tracking
                                              └-> retired
                         ^                         |
                         └──── monitoring loop ────┘
```

Data-to-Visual-Semantik:

- Discovery: `raw intake -> dedupe -> new`;
- Discovery-Ticks: bounded mengenabhängige Bursts;
- Search: reale parallele Lanes und beobachtete Work-Pakete;
- WriteQueue: `polls -> source versions -> snapshots` als sichtbare Kondensation;
- Lifecycle: R1–R7 als Gates mit Retirement-/Candidate-Sink;
- Tracking: große sichtbare Zahl folgt derselben kanonischen Browser-Population wie Topbar `ACTIVE`;
- `lifecycle.active_remaining` bleibt als Stand des letzten Lifecycle-Cycles im Detail verfügbar;
- Tracking->Search: rate-codierter Monitoring-Current aus realem Search-RPM und beobachteter Latenz.

Count-Marks und Work-Pakete sind Mengen-/Arbeitskodierungen und **keine Mint-Identitäten**.

### Shell und Analyst

- Main Stage bleibt dominant.
- Right Context ist auf Desktop resizebar und ein-/ausblendbar.
- Inspector zeigt die vollständige Mint-Adresse mit Copy.
- Analyst bleibt idle im Right Context und kann als großer Focus-Workspace über der Main Stage geöffnet werden.
- Current Data, Web, Temporal und RugCheck bleiben dieselben vier read-only Scopes.
- LLM-Antworten werden über einen kleinen sicheren Markdown-Subset-Renderer dargestellt; kein Modell-HTML wird ungefiltert injiziert.

## Live Operational Telemetry

Collector und Lifecycle emittieren kleine best-effort Runtime-Events über localhost UDP. Das Observatory hält sie standardmäßig zehn Minuten ausschließlich im RAM:

```text
GET /api/telemetry
GET /api/telemetry/events
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
- kein Alerting;
- keine operative Mutation.

Konfiguration:

```text
TELEMETRY_HOST=127.0.0.1
TELEMETRY_PORT=8765
TELEMETRY_RETENTION_SECONDS=600
```

## Analyst

`POST /api/analyst` besitzt vier explizite read-only Use Cases:

| Scope | Evidence / Aufgabe | Modell-Tier |
|---|---|---|
| `current_data` | bounded `query_tokens` über die aktuelle aktive Population | FAST |
| `web` | exact-Mint Web Research | STRONG |
| `temporal` | deterministischer `<=24h` Summary + eine Interpretation | STRONG |
| `rugcheck` | exact-Mint RugCheck Evidence + kompakte Safety-Metadaten | STRONG |

Aktuelle Defaults:

```text
MISTRAL_MODEL_FAST=ministral-14b-latest
MISTRAL_MODEL_STRONG=mistral-large-latest
MISTRAL_WEB_SEARCH_MODE=web_search
```

Die Modellwahl ist serverseitige Use-Case-Policy. Die UI kennt keine Modellnamen.

## Funktionale Observatory-Grenze

Der Functional Core und der definierte Visual-Checkpoint sind abgeschlossen. Presentation, Telemetry und Analyst führen keine neue Domain- oder Mutation-Authority ein.

Es gibt derzeit **kein weiteres beschlossenes Frontend-Design-Arbeitspaket**. Weitere UI-Arbeit sollte aus einer konkreten neuen Benutzerfrage oder einem beobachteten Usability-/Performance-Problem entstehen.

Der aktuelle Projektcheckpoint steht in [`docs/MILESTONES.md`](docs/MILESTONES.md).

## Validierung

```powershell
python -m compileall -q src tools
python -m unittest discover -s tests -v
node --test tests/test_frontend_state.mjs tests/test_frontend_sync.mjs tests/test_telemetry_frontend.mjs
python -m unittest tests.test_telemetry -v
python src/main.py --help
python src/lifecycle_clean.py --help
python tools/verify_lifecycle_contract_v01.py
```

Für Lifecycle v0.3 zusätzlich:

```powershell
python -m unittest tests.test_lifecycle_rule6 tests.test_lifecycle_rule7 -v
```

Der repository-weite `unittest discover` besitzt aktuell zwei bereits bekannte veraltete `diagnostics`-Importfehler; Lifecycle, Telemetry und Observatory ändern diesen unabhängigen Baseline-Zustand nicht.

## Dokumentations-Authorities

- [`README.md`](README.md): Zweck, Einstieg und Bedienung.
- [`docs/architecture.md`](docs/architecture.md): implementierte Komponenten, Datenfluss und harte Systemgrenzen.
- [`docs/LIFECYCLE_CONTRACT.md`](docs/LIFECYCLE_CONTRACT.md): fachliche Semantik und Version des operativen Lifecycle.
- [`docs/FRONTEND_OBSERVATORY.md`](docs/FRONTEND_OBSERVATORY.md): funktionaler Observatory-/Analyst-/Telemetry-Vertrag und Truth-Grenzen.
- [`docs/MILESTONES.md`](docs/MILESTONES.md): aktueller Checkpoint und nächste Entwicklungsentscheidung.
- [`AGENTS.md`](AGENTS.md): verbindliche Regeln für Repository-Änderungen.
