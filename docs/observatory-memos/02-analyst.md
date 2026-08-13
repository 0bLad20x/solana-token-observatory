# `src/observatory/analyst.py`

## Aufgabe

`analyst.py` enthält die eigentlichen LLM-Workflows des Observatory. Die Datei baut je nach Analyseart unterschiedliche Systemanweisungen, verbindet die Benutzerfrage mit der erlaubten Evidence und verarbeitet anschließend die Mistral-Antwort.

## Wie der Prompt ins System kommt

```text
Benutzerfrage
   |
   v
app.py wählt Scope und Token/Evidence
   |
   v
analyst.py baut Systemanweisung + User Content
   |
   v
mistral.py sendet Request
   |
   v
Mistral
```

Die Prompts liegen also nicht im Browser und werden auch nicht vom Modell selbst gewählt. Python baut sie serverseitig passend zum Scope zusammen.

## Wie die Mint erhalten bleibt

Bei Web und Temporal bekommt `analyst.py` bereits das Token-Objekt, das `app.py` zuvor über die angefragte Mint geladen hat. `_prompt()` und `_temporal_instructions()` schreiben genau diese Mint in die Systemanweisung; der Temporal Summary wird zusätzlich erneut mit derselben Mint geladen.

Name, Symbol und Launchpad verbessern nur die Lesbarkeit. Die Mint bleibt die technische Primäridentität.

## Wichtige Teile

### `_prompt()`

Baut den Web-Research-Prompt. Die Mint wird als primäre Identität gesetzt und der Prompt verlangt, externe Aussagen nur dann diesem Token zuzuordnen, wenn die Web-Evidence die Verbindung zur Mint stützt.

### `_parse_response()`

Prüft, ob Mistral die Websuche tatsächlich ausgeführt hat, extrahiert die Antwort und sammelt valide Quellen-URLs.

### `_internal_instructions()`

Baut die Systemanweisung für Current Data. Das Modell darf natürliche Sprache in den kleinen `query_tokens`-Vertrag übersetzen, aber keine nicht unterstützten Metriken erfinden.

### `_tool_call()`

Akzeptiert höchstens genau einen erwarteten Tool Call und validiert Name sowie Argumentstruktur, bevor Python das Tool ausführt.

### `_temporal_instructions()`

Baut die ausführlichere Analyst-Anweisung für Temporal. Sie erklärt die Semantik des deterministischen Summary und begrenzt unbelegte Chronologie-, Kausalitäts- und Marktverhaltensbehauptungen.

### `query_current_tokens()`

Führt den zweistufigen Tool-Calling-Ablauf aus. Zuerst übersetzt Mistral die Frage in einen `query_tokens`-Call; Python validiert und führt ihn deterministisch aus. Danach erhält Mistral nur dieses Ergebnis, um daraus die sprachliche Antwort zu formulieren.

### `research_token()`

Startet Web Research für genau den ausgewählten Token und gibt den Web-Search-Tooltyp ausdrücklich an. Eine Antwort ohne tatsächlich ausgeführte Websuche wird nicht akzeptiert.

### `analyze_temporal_token()`

Lädt den Summary für die ausgewählte Mint, baut daraus ein kompaktes Evidence-JSON und kombiniert es mit Systemanweisung und Benutzerfrage. Dieser gesamte Kontext geht anschließend in genau einen Strong-Model-Request.

**Aufgerufen von:** `app.py`.

**Nutzt:** `tools.py` für Current Data und `mistral.py` für den gemeinsamen API-Transport.

## Präsentationssatz

> **`analyst.py` ist die Prompt- und LLM-Schicht: Python bestimmt je Scope die Regeln und Evidence, hält die Mint bei token-spezifischen Analysen als feste Identität fest und lässt das Modell nur innerhalb dieser vorbereiteten Grenze interpretieren.**
