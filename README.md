# jupiter-data-transform

`jupiter-data-transform` entdeckt Solana-Mints, beobachtet deren Jupiter-Zustände, hält eine begrenzte hochaufgelöste Raw-Historie und reduziert die operative Population über einen transparenten, versionierten Lifecycle.

## System in einem Satz

```text
Discovery -> Jupiter Monitoring -> Persistent Observations -> Operational Lifecycle -> Read-only Observatory / Research
```

Der operative Core besitzt vier Verantwortungen:

1. **Discovery:** neue Mint-Adressen aus externen Quellen aufnehmen.
2. **Monitoring:** aktive Mints über Jupiter Tokens V2 Search beobachten.
3. **Persistence:** tatsächlich beobachtete Jupiter-Source-Versionen nachvollziehbar persistieren und über eine begrenzte Retention pflegen.
4. **Operational Lifecycle:** Tokens anhand des eingefrorenen Lifecycle-Contracts deaktivieren.

Frontend, Analyst und Research sind read-only Downstream-Consumer und besitzen keine operative Mutation-Authority.

## Datenfluss

```text
Discovery sources
    ↓
PostgreSQL: mints
    ↓
Jupiter Search refresh
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

- `first_observed_at`: erste vom Collector persistierte Jupiter-Source-Version;
- `last_polled_at`: letzter erfolgreicher Search-Poll;
- `last_changed_at`: lokale Beobachtungszeit der jüngsten neuen Source-Version;
- `source_updated_at`: jüngster persistierter Jupiter-`updatedAt`-Wert;
- `mint_snapshots`: immutable Historie tatsächlich beobachteter Source-Versionen innerhalb des Raw-Buffers.

Unveränderte Antworten aktualisieren `last_polled_at`, erzeugen aber keinen redundanten Snapshot. Rows in `mint_snapshots` mit `observed_at` älter als 24 Stunden werden unabhängig vom Lifecycle-Zustand entfernt.

## Voraussetzungen

- Python 3.14
- PostgreSQL
- Jupiter API Key(s)
- PumpPortal API Key für die entsprechende Discovery-Quelle
- Mistral API Key für die Analyst-Funktionen des Observatory

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

Dry-Run:

```powershell
python src/lifecycle_clean.py --once
```

Einmalig anwenden:

```powershell
python src/lifecycle_clean.py --apply --once
```

Dauerbetrieb:

```powershell
python src/lifecycle_clean.py --apply
```

Ohne `--apply` schreibt der Lifecycle keine Deaktivierungen. Mit `--apply` setzt ausschließlich der definierte Lifecycle-Pfad `tracking_enabled=false` und persistiert `disabled_at` sowie `disabled_reason`.

Die fachliche Semantik von Rule 1–7 ist in [`docs/LIFECYCLE_CONTRACT.md`](docs/LIFECYCLE_CONTRACT.md) als Contract v0.3 eingefroren.

- Rule 6 ergänzt einen T+30-Checkpoint auf frühe Holder-Distribution: `holderCount < 5` wird deaktiviert, sofern die definierte Checkpoint-Evidence vorhanden ist.
- Rule 7 deaktiviert Mints, die weiterhin frisch von Jupiter Search gepollt werden, deren `last_changed_at` aber seit mindestens 24 Stunden unverändert ist. Dafür ist kein Snapshot erforderlich; die Entscheidung verwendet die langlebigen Collector-Timestamps in `mints`.

Rule 1–5 bleiben gegenüber v0.1 unverändert. Der bestehende Verifier prüft weiterhin genau diese geerbten Regeln gegen die eingefrorene v0.1-Referenz:

```powershell
python tools/verify_lifecycle_contract_v01.py
```

## Read-only Observatory

Das Observatory läuft als separater FastAPI-/Browser-Prozess:

```powershell
python src/frontend.py
```

Standardmäßig unter `http://127.0.0.1:8000`.

Der Browser besitzt eine gemeinsame aktive Population und genau einen `selected Mint`. Search, Inspector, Activity, aktuelle View und selected-token Analyst-Funktionen konsumieren diese gemeinsame Selection. Die konkrete View ist ein austauschbarer Proof und keine Design-Authority.

Die Live-Synchronisation besitzt eine explizite Grenze:

```text
connect / reconnect
      ↓
full universe_snapshot
      ↓
subsequent universe_delta events
```

Der initiale Stream-Snapshot ist zugleich die Server-Baseline für nachfolgende Deltas. `GET /api/token/{mint}` bleibt ein Selected-Detail-Read und schreibt nicht als zweiter Pfad in die Population.

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

### Current Data

Freie Fragen zur aktuellen Population werden in genau den bounded `query_tokens`-Vertrag übersetzt. Das Tool akzeptiert ausschließlich beschriebene Felder, Limits und Filter; kein SQL und keine operative Mutation. Unsupported oder mehrdeutige Fragen dürfen keine Proxy-Metrik erfinden.

### Web Research

Web Research verwendet den exakt selektierten Mint als Identitätsgrenze. Externe Ergebnisse bleiben externe Evidenz und werden nicht persistiert oder zu Jupiter System Truth umgedeutet.

### Temporal Summary

Der produktive Temporal-Pfad lädt einen deterministischen Summary aus maximal 24 Stunden verfügbarer Raw-Historie und sendet **keine Raw-History und keine 1m/5m/15m-Buckets** an das LLM. Danach erfolgt genau eine STRONG-Modell-Interpretation.

`tools/inspect_token_history.py` bleibt als read-only Research-/Diagnosewerkzeug im Repository, ist aber nicht der produktive Observatory-Vertrag.

### RugCheck

Der direkte Evidence-Endpunkt ist:

```text
GET /api/evidence/rugcheck/{mint}
```

Der vollständige RugCheck Token Report bleibt als Provider-Evidence verfügbar. Für die Analyst-Interpretation wird daraus deterministisch eine kompakte Safety-Metadaten-Projektion (`rugcheck_analysis_v4`) erzeugt; einzelne Wallet-/Holder-/Market-Rohzeilen werden nicht an das LLM geschickt. RugCheck-Evidence wird weder persistiert noch zu Jupiter- oder Lifecycle-Truth.

## Funktionale Observatory-Grenze

Der Functional Core ist nach Issue #20 / PR #21 und dem finalen Synchronisations-Slice PR #24 abgeschlossen. Er enthält Domain-Fakten, Population, Selection und Live-Event-Anwendung, aber keine Presentation Truth wie `x/y`, Radius, Farbe, Opacity, D3/Pixi-State oder Clusterpositionen.

Der nächste Schritt ist deshalb **nicht automatisch ein neues Visual Design**. Der aktuelle Projektcheckpoint und die noch zu entscheidenden Evidence-/Relation-Fragen stehen in [`docs/MILESTONES.md`](docs/MILESTONES.md).

## Validierung

```powershell
python -m compileall -q src tools
node --test tests/test_frontend_state.mjs tests/test_frontend_sync.mjs
python src/main.py --help
python src/lifecycle_clean.py --help
python tools/verify_lifecycle_contract_v01.py
```

Für Lifecycle v0.3 zusätzlich gezielt:

```powershell
python -m unittest tests.test_lifecycle_rule6 tests.test_lifecycle_rule7 -v
```

Hinweis: Der repository-weite `unittest discover` besitzt aktuell zwei bereits auf `main` vorhandene Importfehler in veralteten `diagnostics`-Tests. Lifecycle-v0.3 verändert diesen unabhängigen Baseline-Zustand nicht.

Externe Integrationen zusätzlich gegen den realen betroffenen Ablauf prüfen.

## Dokumentations-Authorities

- [`README.md`](README.md): Zweck, Einstieg und Bedienung.
- [`docs/architecture.md`](docs/architecture.md): implementierte Komponenten, Datenfluss und harte Systemgrenzen.
- [`docs/LIFECYCLE_CONTRACT.md`](docs/LIFECYCLE_CONTRACT.md): fachliche Semantik und Version des operativen Lifecycle.
- [`docs/FRONTEND_OBSERVATORY.md`](docs/FRONTEND_OBSERVATORY.md): funktionaler Observatory-/Analyst-Vertrag und Truth-Grenzen.
- [`docs/MILESTONES.md`](docs/MILESTONES.md): aktueller Checkpoint und nächste Entwicklungsentscheidung.
- [`AGENTS.md`](AGENTS.md): verbindliche Regeln für Repository-Änderungen.

Änderungshistorie gehört in Git. Temporäre Refactoring-, Research- oder Optimization-Notizen sind keine dauerhaften Architektur-Authorities.
