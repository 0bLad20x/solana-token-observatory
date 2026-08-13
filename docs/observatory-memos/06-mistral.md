# `src/observatory/mistral.py`

## Aufgabe

`mistral.py` ist die gemeinsame Transportgrenze zur Mistral API. Die Datei enthält keine fachliche Token-Analyse, sondern kümmert sich darum, Requests zu senden, Fehler zu vereinheitlichen und Antworten sicher auszulesen.

## Bird's-Eye-View

```text
analyst.py / rugcheck_analysis.py -> mistral.py -> Mistral API
```

### `AnalystError`

Gemeinsamer, nach außen verständlicher Fehlertyp für Probleme an der LLM-Grenze.

### `post_json()`

Sendet einen JSON-Request mit API-Key an den gewünschten Mistral-Endpoint. HTTP-, Netzwerk-, Timeout- und JSON-Fehler werden in kontrollierte `AnalystError`-Meldungen übersetzt.

### `chat_message()`

Holt aus einer Chat-Completions-Antwort die eigentliche Assistant-Message heraus und prüft, dass sie vorhanden ist.

### `message_text()`

Extrahiert den Text aus unterschiedlichen möglichen Content-Formaten der Mistral-Antwort.

**Genutzt von:** `analyst.py` und `rugcheck_analysis.py`.

## Präsentationssatz

> **`mistral.py` ist die technische LLM-Schnittstelle: Die fachlichen Prompts liegen in den Analysemodulen, während diese Datei nur Transport, Fehlerbehandlung und Response-Parsing vereinheitlicht.**
