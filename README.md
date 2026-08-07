# jupiter-data-transform

Minimaler Python-Collector für Jupiter Tokens V2. Version 0 dokumentiert jede
erfolgreich zurückgegebene Token-Beobachtung und speichert jeden vollständigen
Jupiter-Payload nur einmal in PostgreSQL.

```text
Jupiter API
    -> vollständiger raw_hash
    -> fachlicher content_hash ohne updatedAt
    -> deduplizierter Payload + geordnete Beobachtung
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
die Tabellen dieses Projekts:

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

### `jupiter_payloads`

Enthält jeden unterschiedlichen vollständigen Jupiter-Payload genau einmal:

- `mint`: Token-Identität;
- `raw_hash`: SHA-256 über den vollständigen Payload einschließlich `updatedAt`;
- `content_hash`: SHA-256 über den vollständigen Payload ohne das Top-Level-Feld
  `updatedAt`;
- `source_updated_at`: geparstes optionales Jupiter-`updatedAt`;
- `payload`: vollständige Jupiter-Antwort als JSONB.

### `jupiter_observations`

Enthält für jedes erfolgreich zurückgegebene Token-Objekt eine eigene Zeile:

- `id`: lokale Reihenfolge der gespeicherten Beobachtungen;
- `mint`: beobachteter Token;
- `observed_at`: lokaler Empfangszeitpunkt;
- `raw_hash`: Verweis auf den vollständigen Payload.

Identische Antworten erzeugen deshalb mehrere Beobachtungen, aber keinen mehrfach
gespeicherten JSONB-Payload. Auch eine Folge `A -> B -> A` bleibt vollständig
rekonstruierbar.

`content_hash` ist ein Messinstrument. Erst reale Beobachtungen können zeigen, ob
Jupiters `updatedAt` immer gemeinsam mit den übrigen Payload-Daten wechselt.

Der aktuelle Vertrag persistiert erfolgreiche zurückgegebene Token-Objekte. Fehlende
Tokens in einer erfolgreichen Antwort und fehlgeschlagene HTTP-Anfragen werden derzeit
nur durch Logs sichtbar, nicht als Datenbankereignis gespeichert.

Die Begründung jeder persistierten Information steht in
[docs/architecture.md](docs/architecture.md).

## Tests

```powershell
pytest -q
ruff check .
```
