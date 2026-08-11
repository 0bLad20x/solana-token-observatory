# jupiter-data-transform

`jupiter-data-transform` sammelt und historisiert Zustände von Solana-Tokens und reduziert die operative Beobachtung über einen transparenten, versionierten Lifecycle.

## System in einem Satz

```text
Discovery -> Jupiter Monitoring -> Persistent Observations -> Operational Lifecycle -> Read-only Downstream
```

Der operative Core besitzt vier Verantwortungen:

1. **Discovery:** neue Mint-Adressen aus externen Quellen aufnehmen.
2. **Monitoring:** aktive Mints regelmäßig über Jupiter Tokens V2 Search beobachten.
3. **Persistence:** beobachtete Jupiter-Source-Versionen verlustfrei und nachvollziehbar speichern.
4. **Operational Lifecycle:** wirtschaftlich offensichtlich schlechte Tokens anhand des eingefrorenen Lifecycle-Contracts deaktivieren.

Read-only Consumer wie Research, Frontend oder spätere LLM-Tools liegen außerhalb dieser operativen Mutationskette.

## Datenfluss

```text
Discovery sources
    ↓
PostgreSQL: mints
    ↓
Jupiter Search refresh
    ↓
WriteQueue
    ↓
MintRepository
    ↓
mints + mint_snapshots
    ↓
Operational Lifecycle
    ↓
tracking_enabled=false
```

Ein erfolgreicher Poll und ein neuer Snapshot sind verschiedene Ereignisse:

- `first_observed_at`: erste vom Collector persistierte Jupiter-Source-Version;
- `last_polled_at`: letzter erfolgreicher Search-Poll;
- `last_changed_at`: lokale Beobachtungszeit der jüngsten neuen Source-Version;
- `source_updated_at`: jüngster persistierter Jupiter-`updatedAt`-Wert;
- `mint_snapshots`: immutable Historie tatsächlich beobachteter Source-Versionen.

Unveränderte Antworten aktualisieren `last_polled_at`, erzeugen aber keinen redundanten Snapshot.

## Operativer Core

```text
src/
├── main.py
├── config.py
├── database.py
├── discovery.py
├── refresh.py
├── repository.py
├── schema.sql
├── lifecycle_clean.py
├── lifecycle_queries.py
└── lifecycle_rules.py
```

Zusätzliche read-only Research-Skripte können im Repository existieren, besitzen aber keine operative Authority über Tracking- oder Lifecycle-Zustand.

## Voraussetzungen

- Python 3.14
- PostgreSQL
- Jupiter API Key(s)
- PumpPortal API Key für die entsprechende Discovery-Quelle

## Installation

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Danach die lokalen Zugangsdaten in `.env` eintragen. `.env` wird nicht committed.

## Collector

Schema initialisieren:

```powershell
python src/main.py init-schema
```

Collector starten:

```powershell
python src/main.py run
```

Discovery und Jupiter-Refresh laufen parallel. Neue Mints werden zunächst als aktiv registriert; Search-Beobachtungen vervollständigen anschließend Mint-Fakten und Snapshot-Historie.

## Operational Lifecycle

Einmalig als Dry-Run:

```powershell
python src/lifecycle_clean.py --once
```

Einmalig mit operativer Deaktivierung:

```powershell
python src/lifecycle_clean.py --apply --once
```

Dauerbetrieb:

```powershell
python src/lifecycle_clean.py --apply
```

Ohne `--apply` schreibt der Lifecycle keine Deaktivierungen. Mit `--apply` setzt ausschließlich der definierte Lifecycle-Pfad `tracking_enabled=false` und persistiert `disabled_at` sowie `disabled_reason`.

Die fachliche Semantik von Rule 1–5 ist in [`docs/LIFECYCLE_CONTRACT.md`](docs/LIFECYCLE_CONTRACT.md) als Contract v0.1 eingefroren.

Vor einer reinen Lifecycle-Simplification:

```powershell
python tools/verify_lifecycle_contract_v01.py
```

Der Verifier vergleicht die aktuelle Implementierung gegen die eingefrorene v0.1-Referenz auf demselben PostgreSQL-Snapshot und verlangt pro Regel identische `(mint, reason)`-Sets.

## Read-only Downstream

Read-only Consumer dürfen operative Daten lesen und eigene Projektionen erzeugen. Sie dürfen jedoch weder `tracking_enabled`, Priority noch Lifecycle-State verändern.

Das lokale Observatory läuft als separater read-only Prozess:

```powershell
python src/frontend.py
```

Für die tokenbezogene Webrecherche werden serverseitig konfiguriert:

```text
MISTRAL_API_KEY=...
MISTRAL_MODEL=mistral-small-latest
MISTRAL_WEB_SEARCH_MODE=web_search
```

`MISTRAL_WEB_SEARCH_MODE` akzeptiert ausschließlich `web_search` oder
`web_search_premium`. Externe Rechercheergebnisse werden nicht persistiert und besitzen
keine operative Mutation-Authority.

Der Analyst kann außerdem Fragen zur aktuellen aktiven Token-Population in einen
serverseitigen `query_tokens`-Aufruf übersetzen. Das Tool kennt nur eine feste Liste
beschriebener aktueller Felder. Die real verfügbaren Launchpads werden pro Anfrage aus
der aktiven Population ergänzt. Das Tool liefert standardmäßig fünf und maximal zwanzig
Treffer und akzeptiert weder SQL noch operative Mutationen. Dafür ist keine zusätzliche
Konfiguration nötig.

OHLC/Time-Buckets und Snapshot-Retention sind derzeit bewusst zurückgestellt. Der aktuelle Entwicklungsstand und die Reihenfolge stehen in [`docs/MILESTONES.md`](docs/MILESTONES.md).

## Validierung

```powershell
python -m compileall -q src tools
python -m unittest discover -s tests -v
python src/main.py --help
python src/lifecycle_clean.py --help
python tools/verify_lifecycle_contract_v01.py
```

Externe Integrationen zusätzlich gegen den realen betroffenen Ablauf prüfen.

## Dokumentations-Authorities

- [`README.md`](README.md): Zweck, Einstieg und Bedienung.
- [`docs/architecture.md`](docs/architecture.md): implementierte Komponenten, Datenfluss und harte Systemgrenzen.
- [`docs/LIFECYCLE_CONTRACT.md`](docs/LIFECYCLE_CONTRACT.md): fachliche Semantik und Version des operativen Lifecycle.
- [`docs/MILESTONES.md`](docs/MILESTONES.md): aktueller Stand und nächste Entwicklungsrichtung; keine Authority für bereits implementiertes Verhalten.
- [`AGENTS.md`](AGENTS.md): verbindliche Regeln für Änderungen am Repository.

Änderungshistorie gehört in Git. Temporäre Refactoring-, Research- oder Optimization-Notizen sind keine dauerhaften Architektur-Authorities.
