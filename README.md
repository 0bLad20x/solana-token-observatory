# jupiter-data-transform

Minimaler Python-Collector für Jupiter Tokens V2. Version 0 speichert ausschließlich
unterschiedliche, vollständige Jupiter-Zustände in PostgreSQL.

```text
Jupiter API -> kanonischer Payload-Hash -> jupiter_observations
```

Nicht enthalten sind Normalisierung, Timeframes, Indikatoren, Meteora, Signale,
TimescaleDB oder Rust.

## Voraussetzungen

- Python 3.11
- PostgreSQL
- ein Jupiter API Key

## Installation unter Windows

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
```

Trage den lokalen Datenbankzugang und einen API Key in `.env` ein. Die Datei wird
nicht committed.

## Datenbank und Schema

Die PostgreSQL-Datenbank muss bereits existieren. Der folgende Befehl erstellt nur
die Tabelle dieses Projekts:

```powershell
jupiter-data-transform init-schema
```

## Einen Token einmal abrufen

```powershell
jupiter-data-transform collect `
  --mint JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN `
  --once
```

## Mehrere Tokens regelmäßig abrufen

`mints.txt` enthält eine Mint-Adresse pro Zeile. Leerzeilen, Kommentare und doppelte
Einträge werden ignoriert.

```powershell
jupiter-data-transform collect --mints-file mints.txt --interval 60
```

Abbruch mit `Ctrl+C`.

## Persistenz

`jupiter_observations` enthält:

- `mint`: Token-Identität;
- `payload_hash`: SHA-256 über kanonisches JSON;
- `first_seen_at` und `last_seen_at`: lokaler Beobachtungszeitraum;
- `source_updated_at`: unverändertes optionales Jupiter-`updatedAt`;
- `seen_count`: Anzahl identischer empfangener Payloads;
- `payload`: vollständige Jupiter-Antwort als JSONB.

`PRIMARY KEY (mint, payload_hash)` verhindert doppelte Zustände. Ein wiederholter
identischer Payload aktualisiert nur `last_seen_at` und `seen_count`.

Die Begründung jeder persistierten Information steht in
[docs/architecture.md](docs/architecture.md).

## Tests

```powershell
pytest -q
ruff check .
```
