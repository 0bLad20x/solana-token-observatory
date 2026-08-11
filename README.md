# jupiter-data-transform

`jupiter-data-transform` sammelt und historisiert Zustände von Solana-Tokens, reduziert die operative Beobachtung über einen transparenten Lifecycle und stellt die verbleibenden Tokens für read-only Research und spätere Zeitreihenanalyse bereit.

## System in einem Satz

```text
Discovery -> Jupiter Monitoring -> Operational Lifecycle -> Survivor Research -> Time Series / Query Layer
```

Das Projekt trennt bewusst vier Verantwortungen:

1. **Discovery:** neue Mint-Adressen aus externen Quellen aufnehmen.
2. **Monitoring:** aktive Mints regelmäßig über Jupiter Tokens V2 Search beobachten.
3. **Operational Lifecycle:** wirtschaftlich offensichtlich schlechte Tokens anhand expliziter Regeln deaktivieren.
4. **Read-only Research:** Survivor-Tokens diagnostisch und auf Anomalien untersuchen, ohne daraus automatisch operative Mutationen abzuleiten.

GMGN ist eine optionale zusätzliche Research-Quelle. Es ersetzt Jupiter nicht als operative Quelle der gespeicherten Token-Zustände.

## Datenfluss

```text
Discovery sources
    ↓
PostgreSQL: mints
    ↓
Jupiter Search refresh
    ↓
Poll state + changed snapshots
    │
    ├──────────────→ Operational Lifecycle ──→ tracking_enabled=false
    │
    └──────────────→ Read-only Research
                         ├─ diagnostic framework
                         └─ anomaly / archetype analysis
```

Ein erfolgreicher Poll und ein neuer Snapshot sind verschiedene Ereignisse:

- `last_polled_at` zeigt, wann ein Mint zuletzt erfolgreich abgefragt wurde;
- `last_changed_at` zeigt, wann Jupiter zuletzt einen fachlich geänderten Zustand geliefert hat;
- `source_updated_at` hält den zuletzt beobachteten Jupiter-`updatedAt`-Wert;
- `mint_snapshots` speichert nur fachlich veränderte Zustände.

Unveränderte Antworten werden deshalb nicht als redundante Snapshots gespeichert.

## Projektstruktur

```text
jupiter-data-transform/
├── src/
│   ├── main.py                     # Collector entrypoint
│   ├── config.py                   # Environment-Konfiguration
│   ├── database.py                 # process-wide PostgreSQL pool
│   ├── discovery.py                # Mint-Discovery
│   ├── refresh.py                  # Jupiter Search refresh
│   ├── repository.py               # Persistenz + operative Mint-Mutationen
│   ├── schema.sql                  # persistentes Datenmodell
│   │
│   ├── lifecycle_clean.py          # operative Lifecycle-Orchestrierung
│   ├── lifecycle_queries.py        # Lifecycle-Evidence aus PostgreSQL
│   ├── lifecycle_rules.py          # reine Lifecycle-Regeln
│   │
│   ├── bot_detection_v321.py       # pure Anomaly-/Archetype-Evaluation
│   ├── analyze_bot_population_v321.py # read-only Population Research
│   │
│   ├── diagnose_inactivity.py      # separates Diagnose-/Shadow-Policy-System
│   ├── diagnostics/                # Diagnosemethodik und AI-Export
│   └── gmgn.mjs                    # separates GMGN-Research-Tooling
├── tools/
│   └── verify_lifecycle_contract_v01.py # live Equivalence Gate
├── docs/
│   ├── architecture.md
│   ├── LIFECYCLE_CONTRACT.md
│   ├── DIAGNOSTIC_PHASES.md
│   ├── GMGN_FIELDS_REFERENCE.md
│   └── MILESTONES.md
├── analysis/                       # erzeugte Research-Artefakte
├── data/                           # lokale Runtime-Artefakte
├── AGENTS.md
└── README.md
```

Versionierte Research-Skripte sind keine dauerhafte Architektur-Authority. Ihre konkrete Methodik bleibt im Code und in den erzeugten Analyseartefakten nachvollziehbar.

## Voraussetzungen

- Python 3.14
- PostgreSQL
- Jupiter API Key(s)
- PumpPortal API Key für die entsprechende Discovery-Quelle
- Node.js nur für das separate GMGN-Tooling

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

Discovery und Jupiter-Refresh laufen parallel. Neue Discovery-Ergebnisse werden zunächst als aktive Mints aufgenommen; der Refresh erzeugt anschließend die Jupiter-Beobachtungen.

## Operational Lifecycle

Einmalig als Dry-Run prüfen:

```powershell
python src/lifecycle_clean.py --once
```

Operative Deaktivierung ausdrücklich anwenden:

```powershell
python src/lifecycle_clean.py --apply --once
```

Ohne `--apply` schreibt die Lifecycle-Engine keine Deaktivierungen. Mit `--apply` kann ausschließlich der definierte Lifecycle-Pfad `tracking_enabled=false` setzen.

Die fachliche Semantik von Rule 1–5 ist in [`docs/LIFECYCLE_CONTRACT.md`](docs/LIFECYCLE_CONTRACT.md) als Contract v0.1 eingefroren. Rule 1 besitzt eine feste Current-State-Freshness; Rule 2 und Rule 3 verwenden ihre jeweiligen Checkpoint-Bedingungen; Rule 4 und Rule 5 arbeiten auf immutable Snapshot-Evidence.

Vor einer reinen Lifecycle-Simplification:

```powershell
python tools/verify_lifecycle_contract_v01.py
```

Der Verifier vergleicht die aktuelle Implementierung gegen die eingefrorene v0.1-Referenz auf demselben PostgreSQL-Snapshot.

## Read-only Research

Aktuelle Survivor-Population mit der Anomaly Engine analysieren:

```powershell
python src/analyze_bot_population_v321.py
```

Das Skript bewertet bekannte Archetypen und allgemeine Anomaliestrukturen, verändert aber keine operative Priority und deaktiviert keine Mints.

Das separate siebenphasige Diagnose-/Shadow-Policy-System bleibt ebenfalls verfügbar:

```powershell
python src/diagnose_inactivity.py
python src/diagnose_inactivity.py --monitor --interval-seconds 60
```

Seine Methodik ist ausschließlich in [`docs/DIAGNOSTIC_PHASES.md`](docs/DIAGNOSTIC_PHASES.md) definiert.

## GMGN

`src/gmgn.mjs` ist ein separates Research-Tool für zusätzliche GMGN-Beobachtungen. Die Trenches-Feldsemantik steht in [`docs/GMGN_FIELDS_REFERENCE.md`](docs/GMGN_FIELDS_REFERENCE.md).

GMGN-Daten sind zusätzliche Evidenz und keine Authority für operative Lifecycle-Entscheidungen.

## Nächste Richtung

Die nächste Entwicklungsstufe beginnt bei den Tokens, die den operativen Lifecycle überleben: daraus sollen OHLC-/Time-Bucket-Daten, eine gemeinsame read-only Query-Schicht, ein lokales Frontend und später LLM Tool Calling entstehen.

Die bewusst knappe Roadmap steht in [`docs/MILESTONES.md`](docs/MILESTONES.md).

## Validierung

```powershell
python -m compileall -q src tools
python -m unittest discover -s tests -v
python src/main.py --help
python src/lifecycle_clean.py --help
python tools/verify_lifecycle_contract_v01.py
```

Externe Integrationen zusätzlich mit dem jeweils betroffenen realen Ablauf prüfen.

## Dokumentations-Authorities

- [`README.md`](README.md): Zweck, Einstieg und Bedienung.
- [`docs/architecture.md`](docs/architecture.md): implementierte Komponenten, Datenfluss und harte Systemgrenzen.
- [`docs/LIFECYCLE_CONTRACT.md`](docs/LIFECYCLE_CONTRACT.md): fachliche Semantik und Version des operativen Lifecycle.
- [`docs/DIAGNOSTIC_PHASES.md`](docs/DIAGNOSTIC_PHASES.md): Methodik des separaten siebenphasigen Diagnose-/Shadow-Policy-Subsystems.
- [`docs/GMGN_FIELDS_REFERENCE.md`](docs/GMGN_FIELDS_REFERENCE.md): GMGN-Trenches-Feldreferenz.
- [`docs/MILESTONES.md`](docs/MILESTONES.md): aktueller Stand und nächste Entwicklungsrichtung; keine Authority für bereits implementierten Zustand.
- [`AGENTS.md`](AGENTS.md): verbindliche Regeln für Änderungen am Repository.

Änderungshistorie gehört in Git. Temporäre Refactoring- oder Optimization-Notizen gehören nicht in die dauerhafte Dokumentation.
