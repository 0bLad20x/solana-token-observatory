# `src/observatory/analyst.py`

## Aufgabe

`analyst.py` enthält die eigentlichen LLM-Workflows des Observatory. Die Datei baut je nach Analyseart unterschiedliche Systemanweisungen, verbindet die Benutzerfrage mit der erlaubten Evidence und verarbeitet anschließend die Mistral-Antwort.

## Wichtige Teile

### `_prompt()`

Baut den Web-Research-Prompt. Die ausgewählte Mint wird als primäre Identität in den Prompt geschrieben; Name, Symbol und Launchpad sind nur zusätzliche Hinweise.

### `_internal_instructions()`

Baut die Systemanweisung für Current Data. Das Modell darf natürliche Sprache in den kleinen `query_tokens`-Vertrag übersetzen, aber keine nicht unterstützten Metriken erfinden.

### `_temporal_instructions()`

Baut die ausführlichere Analyst-Anweisung für Temporal. Das Modell bekommt Regeln, wie der deterministische Summary zu interpretieren ist und welche Kausalbehauptungen ausdrücklich nicht aus aggregierten Daten abgeleitet werden dürfen.

### `query_current_tokens()`

Führt den zweistufigen Tool-Calling-Ablauf aus: zuerst interpretiert Mistral die Frage und fordert höchstens einen `query_tokens`-Call an; anschließend wird das deterministische Tool-Ergebnis zurück an das Modell gegeben, damit es daraus eine kurze Antwort formuliert.

### `research_token()`

Startet Web Research für genau den ausgewählten Token. Die Websuche muss tatsächlich ausgeführt worden sein, sonst wird die Antwort verworfen.

### `analyze_temporal_token()`

Lädt den Summary für die ausgewählte Mint, kombiniert ihn mit der Benutzerfrage und schickt beides in einem Strong-Model-Request an Mistral.

## Präsentationssatz

> **`analyst.py` ist die Prompt- und LLM-Schicht: Jeder Scope bekommt eigene Regeln und eigene Evidence, während die ausgewählte Mint bei token-spezifischen Analysen als feste Identität im gesamten Request erhalten bleibt.**
