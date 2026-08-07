# jupiter-data-transform

Kleine Python-Anwendung zum automatischen Entdecken von Solana-Mints und zum regelmäßigen Abrufen ihrer Jupiter-Tokens-V2-Daten.

## Datenfluss

```text
PumpPortal subscribeNewToken ─┐
Jupiter /tokens/v2/recent ────┤
Meteora DAMM v2 ──────────────┼─> mints
Meteora DLMM ─────────────────┘
                                  ↓
                         aktive Priority-1-Mints
                                  ↓
                       Batches mit maximal 100 Mints
                                  ↓
                        Jupiter /tokens/v2/search
                                  ↓
                         updatedAt verändert?
                           │             │
                          nein           ja
                           │             │
                     kein Snapshot   mint_snapshots
```

Discovery liefert ausschließlich Mint-Adressen. Tokeninformationen kommen anschließend von Jupiter Search.

## Struktur

```text
src/
├── main.py
├── config.py
├── discovery.py
├── refresh.py
├── repository.py
├── sampling_rate.py
└── schema.sql
```

Keine weiteren Python-Unterordner und kein doppeltes `src/jupiter_data_transform`-Package.

## Installation

Python 3.14 verwenden.

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

## Start

```powershell
python src/main.py init-schema
python src/main.py run
```

## Persistenz

`mints` enthält bekannte Mint-Adressen, Basisdaten sowie `priority` und `tracking_enabled`.

`mint_snapshots` erhält nur dann einen neuen vollständigen Jupiter-Payload, wenn sich `updatedAt` gegenüber dem zuletzt gespeicherten Zustand des Mints geändert hat. `observed_at` ist der lokale Empfangszeitpunkt.

## Noch nicht implementiert

Lifecycle-Regeln, Timeframes/OHLC, TimescaleDB, automatische Verdichtung und Unit-Tests.

Siehe `docs/architecture.md`.
