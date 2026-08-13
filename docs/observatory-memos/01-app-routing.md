# `src/observatory/app.py`

## Aufgabe

`app.py` ist der API-Router des Observatory. Die Datei nimmt Benutzeranfragen entgegen, lädt den benötigten read-only Kontext und entscheidet anhand des Scopes, welcher Analysepfad verwendet wird.

## Bird's-Eye-View

```text
Request -> app.py -> Scope -> Evidence -> Analyse -> Response
```

### `AnalystRequest`

Definiert Scope, Frage und optional eine Mint. Für Web, Temporal und RugCheck ist diese Mint die feste technische Identität des ausgewählten Tokens.

### `lifespan()`

Öffnet beim Start den Datenbank-Reader und den Telemetry-Receiver und schließt beide beim Beenden.

### `universe()` und `token_detail()`

`universe()` liefert die aktive Population. `token_detail()` lädt genau einen Token anhand seiner Mint.

**Nutzt:** `data.py`.

### `analyst()`

Zentrale Routing-Funktion für das LLM. Current Data erhält die aktive Population; Web, Temporal und RugCheck laden zuerst den ausgewählten Token und geben ihn danach an den jeweiligen Analysepfad weiter.

**Nutzt:** `analyst.py`, `rugcheck_analysis.py`, `model_policy.py` und `evidence/rugcheck.py`.

### `telemetry_snapshot()` und `telemetry_events()`

Stellen die kurzfristige Runtime-Telemetrie bereit.

### `events()`

Liefert zuerst einen vollständigen Universe-Snapshot und danach nur noch Änderungen.

**Nutzt:** `delta.py`.

## Präsentationssatz

> **`app.py` ist der Router: Es entscheidet zuerst, welche Evidence eine Frage benutzen darf, und hält bei token-spezifischen Scopes die ausgewählte Mint als feste Identität durch den gesamten Analysepfad.**
