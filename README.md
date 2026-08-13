# jupiter-data-transform

`jupiter-data-transform` entdeckt Solana-Mints, beobachtet deren Jupiter-Zustände, persistiert eine begrenzte Raw-Historie, reduziert die aktive Population über einen versionierten Lifecycle und projiziert den laufenden Zustand read-only in das Token Observatory.

## System

```text
Discovery -> Jupiter Monitoring -> Persistence -> Lifecycle
                              \-> Read-only Observatory / Analyst / Telemetry
```

Der operative Core besitzt vier Verantwortungen:

1. **Discovery** nimmt neue Mint-Adressen aus externen Quellen auf.
2. **Monitoring** beobachtet aktive Mints über Jupiter Tokens V2 Search.
3. **Persistence** speichert tatsächlich beobachtete Jupiter-Source-Versionen und hält `mint_snapshots` als 24h Raw-Working-Buffer.
4. **Lifecycle** deaktiviert Tokens ausschließlich nach dem versionierten Lifecycle-Contract.

Observatory, Analyst und Telemetry sind read-only Downstream-Consumer und besitzen keine operative Mutation-Authority.

## Voraussetzungen

- Python 3.14
- PostgreSQL
- Jupiter API Key(s)
- PumpPortal API Key für die entsprechende Discovery-Quelle
- Mistral API Key für Analyst-Funktionen

## Installation

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Danach lokale Zugangsdaten in `.env` eintragen. `.env` wird nicht committed.

## Betrieb

Schema initialisieren:

```powershell
python src/main.py init-schema
```

Collector starten:

```powershell
python src/main.py run
```

Lifecycle als Dry-Run:

```powershell
python src/lifecycle_clean.py --once
```

Lifecycle anwenden:

```powershell
python src/lifecycle_clean.py --apply
```

Observatory starten:

```powershell
python src/frontend.py
```

Standardmäßig läuft das Observatory unter `http://127.0.0.1:8000`.

## Zentrale Datenbegriffe

Ein erfolgreicher Poll und ein neuer Snapshot sind verschiedene Ereignisse:

- `first_observed_at`: erste persistierte Jupiter-Source-Version;
- `last_polled_at`: letzter erfolgreicher Search-Poll;
- `last_changed_at`: lokale Beobachtungszeit der jüngsten neuen Source-Version;
- `source_updated_at`: jüngster persistierter Jupiter-`updatedAt`-Wert;
- `mint_snapshots`: immutable Historie tatsächlich beobachteter Source-Versionen innerhalb des 24h-Raw-Buffers.

Unveränderte Antworten aktualisieren `last_polled_at`, erzeugen aber keinen redundanten Snapshot.

## Validierung

```powershell
python -m compileall -q src tools
python -m unittest discover -s tests -v
python tools/verify_lifecycle_contract_v01.py
python src/main.py --help
python src/lifecycle_clean.py --help
```

Frontend-Verträge werden zusätzlich über die vorhandenen Node-Tests unter `tests/*.mjs` geprüft.

## Dokumentations-Authorities

- [`docs/architecture.md`](docs/architecture.md): implementierte Komponenten, Datenfluss und Systemgrenzen.
- [`docs/LIFECYCLE_CONTRACT.md`](docs/LIFECYCLE_CONTRACT.md): fachliche Semantik des operativen Lifecycle.
- [`docs/FRONTEND_OBSERVATORY.md`](docs/FRONTEND_OBSERVATORY.md): funktionaler Observatory-/Analyst-/Telemetry-Vertrag.
- [`AGENTS.md`](AGENTS.md): verbindliche Regeln für Repository-Änderungen.

Offene Arbeit und Entwicklungsentscheidungen werden in GitHub Issues geführt; Änderungshistorie gehört in Git.
