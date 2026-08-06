# jupiter-data-transform

Minimaler Python-Collector für Jupiter Tokens V2. Das erste Release speichert jeden empfangenen
API-Zustand unverändert und erzeugt daraus einen typisierten Snapshot in PostgreSQL.

## Grenze der ersten Version

```text
Jupiter API -> Raw JSONB -> typisierter Snapshot -> PostgreSQL
```

Noch nicht enthalten: Timeframes, Indikatoren, Meteora, Signale, automatische Trades oder Rust.

## Voraussetzungen

- Python 3.11
- PostgreSQL
- Jupiter API Key

## Installation unter Windows

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
```

Trage anschließend in `.env` den lokalen Datenbankzugang und mindestens einen Jupiter API Key ein.
Mehrere Keys werden kommasepariert angegeben. `.env` wird nicht committed.

## Datenbank anlegen

```sql
CREATE DATABASE jupiter_data_transform;
```

Danach:

```powershell
jupiter-data-transform init-db
```

## Einen Token einmal abrufen

```powershell
jupiter-data-transform collect `
  --mint JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN `
  --once
```

## Mehrere Tokens regelmäßig abrufen

`mints.txt`:

```text
JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN
So11111111111111111111111111111111111111112
```

```powershell
jupiter-data-transform collect --mints-file mints.txt --interval 60
```

Abbruch mit `Ctrl+C`.

## Tabellen

- `jupiter_raw_updates`: kompletter Payload, Request- und Empfangszeitpunkt;
- `jupiter_snapshots`: typisierte Zustandswerte und der zuletzt gemeldete `stats5m`-Stand.

Die Zeitsemantik und Projektgrenze sind in [docs/architecture.md](docs/architecture.md) dokumentiert.

## Tests

```powershell
pytest -q
ruff check .
```
