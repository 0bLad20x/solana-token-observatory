# `src/observatory/data.py`

## Aufgabe

`data.py` ist die read-only Datenzugriffsschicht des Observatory. Die Datei projiziert operative PostgreSQL-Daten in kleine Token-Objekte, die Frontend und Analyst verwenden können, ohne dem Observatory Schreibrechte auf den Collector-State zu geben.

## Bird's-Eye-View

```text
PostgreSQL -> FrontendReader -> Token-Projektion -> API / Analyst
```

### `_iso()`, `_float()`, `_int()`

Kleine Konverter, die Datenbankwerte in stabile API-Werte umwandeln.

### `FrontendReader.__init__()`

Erzeugt einen eigenen kleinen Connection Pool mit read-only PostgreSQL-Optionen und Statement-Timeout. Dadurch bleibt das Observatory technisch vom operativen Schreibpfad getrennt.

### `_rows()`

Lädt aktuelle Token-Zustände und zieht benötigte Werte direkt aus dem neuesten JSONB-Snapshot, zum Beispiel Market Cap, Liquidity, Holder oder `stats5m`.

Optional kann genau eine Mint gefiltert werden. Das ist die Grundlage dafür, einen ausgewählten Token technisch eindeutig wiederzufinden.

### `_token()`

Formt eine Datenbankzeile in das kompakte Token-Objekt um, das der restliche Observatory-Code versteht.

### `snapshot()`

Liefert die aktuelle Population. Current Data und Universe benutzen diese Funktion.

### `token(mint)`

Liefert genau den Token, dessen Mint angefragt wurde. Diese Funktion ist die zentrale Brücke zwischen UI-Auswahl und token-spezifischem LLM-Kontext.

### `temporal_summary(mint)`

Lädt die retained Historie für genau diese Mint und lässt daraus einen kompakten Temporal Summary berechnen.

**Nutzt:** `temporal_context.py`.

## Präsentationssatz

> **`data.py` ist die read-only Brücke zur Datenbank: Es liefert entweder die aktive Population oder genau den ausgewählten Mint und bereitet daraus die kompakte Evidence für API und Analyst vor.**
