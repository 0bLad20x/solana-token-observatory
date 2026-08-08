# jupiter-data-transform

`jupiter-data-transform` sammelt und historisiert Zustände von Solana-Tokens und baut darauf ein read-only Diagnose- und Shadow-Policy-Framework auf.

Das Projekt hat drei getrennte Aufgaben:

1. **Discovery und Monitoring:** Solana-Mints entdecken und aktive Mints regelmäßig über Jupiter Tokens V2 Search abfragen.
2. **Diagnose:** Population, Regionen, Bewegung, Aktivität und Outcomes aus den gespeicherten Beobachtungen analysieren.
3. **Shadow-Policy:** mögliche Demote-/Retire-Regeln bewerten, ohne den operativen Collector zu verändern.

GMGN liefert optionale zusätzliche Beobachtungen. Es ersetzt weder Jupiter als Quelle der gespeicherten Token-Snapshots noch die PostgreSQL-Persistenz.

## Datenfluss

```text
Discovery sources
    │
    ▼
PostgreSQL mints
    │
    ▼
MintCache -> BatchCursor -> Jupiter Search lanes -> WriteQueue
    │                                      │
    │                                      ▼
    │                               mint_snapshots
    │
    └──────────────────────────────┐
                                   ▼
                         Diagnostic framework
                                   │
                ┌──────────────────┼──────────────────┐
                ▼                  ▼                  ▼
          state / flow         shadow policy      AI bundle
          / cohorts            / outcomes         / dashboard
```

Discovery-Quellen liefern Kandidaten-Mints. Der reguläre Refresh lädt aktive Mints nach Priority aus PostgreSQL, rotiert sie in Batches von maximal 100 Adressen durch die verfügbaren Jupiter-Search-Lanes und schreibt erfolgreiche Ergebnisse gebündelt.

Ein erfolgreicher Poll aktualisiert die Beobachtbarkeit eines Mints. Ein neuer historischer Snapshot wird nur gespeichert, wenn sich der fachliche Jupiter-Zustand gegenüber dem zuletzt bekannten Zustand geändert hat. Ein unveränderter Payload ist deshalb **kein fehlender Poll**.

## Sicherheitsgrenze der Diagnose

Das Diagnose-Framework ist gegenüber den operativen Mint-Daten read-only.

- Es setzt `tracking_enabled` nicht um.
- Es ändert keine operative Priority.
- `p2`, `p3` und `retire` sind Shadow-Actions.
- Diagnose-Tabellen in PostgreSQL sind temporäre Arbeitsstrukturen.
- Eine beobachtete Korrelation wird nicht automatisch zu einer Collector-Regel.

Die methodische Authority für Populationen, Nenner, Readiness und die sieben Diagnosephasen ist [`docs/DIAGNOSTIC_PHASES.md`](docs/DIAGNOSTIC_PHASES.md).

## Projektstruktur

```text
jupiter-data-transform/
├── src/
│   ├── main.py                    # Collector entrypoint
│   ├── config.py                  # Environment-Konfiguration
│   ├── discovery.py               # Mint-Discovery
│   ├── refresh.py                 # Jupiter Search refresh pipeline
│   ├── repository.py              # PostgreSQL-Zugriff
│   ├── schema.sql                 # Persistentes Datenmodell
│   ├── diagnose_inactivity.py     # Diagnose-/Monitor-CLI
│   ├── diagnostics_dashboard.py   # Dashboard entrypoint
│   ├── gmgn.mjs                   # separates GMGN-Tooling
│   └── diagnostics/               # Analyse, Regionen, Kohorten, Policy, Export
├── tests/
├── docs/
│   ├── architecture.md
│   ├── DIAGNOSTIC_PHASES.md
│   └── GMGN_FIELDS_REFERENCE.md
├── analysis/                      # erzeugte Analyse-Artefakte
├── data/                          # lokale Runtime-Artefakte, nicht versioniert
├── AGENTS.md
└── README.md
```

Die Struktur bleibt bewusst klein. Neue Module oder Verzeichnisse brauchen eine echte fachliche Verantwortung; parallele Implementierungen derselben Verantwortung sind nicht vorgesehen.

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

Für das Dashboard zusätzlich:

```powershell
python -m pip install -r requirements-dashboard.txt
```

## Collector

Schema initialisieren:

```powershell
python src/main.py init-schema
```

Collector starten:

```powershell
python src/main.py run
```

Der Collector führt Discovery und Jupiter-Refresh parallel aus.

## Diagnose

Aktuellen Zustand einmalig analysieren:

```powershell
python src/diagnose_inactivity.py
```

Dieser One-Shot erzeugt Report, aktuellen Region-Snapshot und AI-Bundle. Die longitudinale Region-History wird bewusst nicht automatisch fortgeschrieben, weil unregelmäßige manuelle Läufe keine belastbare Dwell-/Transition-Zeitreihe ergeben.

Kontinuierlichen Shadow-Monitor starten:

```powershell
python src/diagnose_inactivity.py --monitor --interval-seconds 60
```

Einen einzelnen Monitor-Zyklus ausführen:

```powershell
python src/diagnose_inactivity.py --monitor --max-runs 1
```

Bestehende Diagnose-Artefakte ohne Datenbankzugriff erneut als AI-Bundle exportieren:

```powershell
python src/diagnose_inactivity.py --ai-export-only
```

Dashboard starten:

```powershell
python src/diagnostics_dashboard.py
```

## GMGN

GMGN ist eine optionale zusätzliche Beobachtungsquelle und besitzt einen eigenen Collector-/Analysepfad. Seine Felder und deren Semantik sind bewusst ausführlich in [`docs/GMGN_FIELDS_REFERENCE.md`](docs/GMGN_FIELDS_REFERENCE.md) dokumentiert.

Diese Referenz ist ein Informationskatalog und keine Authority für Lifecycle- oder Diagnoseentscheidungen.

## Validierung

```powershell
python -m compileall -q src
python -m unittest discover -s tests -v
python src/main.py --help
python src/diagnose_inactivity.py --help
```

Externe Integrationen zusätzlich mit dem jeweils betroffenen realen Ablauf prüfen.

## Dokumentations-Authorities

Es gibt bewusst nur wenige dauerhafte Dokumentationsquellen:

- [`README.md`](README.md): Zweck, Einstieg und Bedienung.
- [`docs/architecture.md`](docs/architecture.md): Komponenten, Datenfluss und harte Systemgrenzen.
- [`docs/DIAGNOSTIC_PHASES.md`](docs/DIAGNOSTIC_PHASES.md): methodischer Diagnosevertrag.
- [`docs/GMGN_FIELDS_REFERENCE.md`](docs/GMGN_FIELDS_REFERENCE.md): vollständige GMGN-Feldreferenz.
- [`AGENTS.md`](AGENTS.md): verbindliche Regeln für Änderungen am Repository.

Änderungshistorie gehört in Git. Temporäre Refactoring-Notizen und Kopien bestehender Authorities gehören nicht in die dauerhafte Dokumentation.