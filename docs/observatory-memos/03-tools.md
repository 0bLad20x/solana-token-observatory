# `src/observatory/tools.py`

## Aufgabe

`tools.py` definiert den kleinen, kontrollierten Query-Vertrag für **Current Data**. Das LLM darf hier nicht frei SQL erzeugen, sondern nur eine begrenzte Menge erlaubter Felder, Sortierungen, Limits und Launchpads auswählen.

## Bird's-Eye-View

```text
Benutzerfrage -> LLM übersetzt -> query_tokens Argumente -> deterministischer Python-Code -> Ergebnis
```

### `QUERY_FIELDS` / `SORT_ORDERS`

Definieren den erlaubten Wortschatz. Aktuell gehören dazu unter anderem Market Cap, Liquidity, Holders, 5m Trades/Traders/Volume sowie Token Age und Last Change.

### `query_capabilities(tokens)`

Baut aus der aktuellen Population die Fähigkeiten zusammen, die dem Modell gezeigt werden. Dazu gehören erlaubte Felder, Sortierungen, aktuell vorhandene Launchpads und Ergebnisgrenzen.

**Genutzt von:** `analyst.py`.

### `query_tokens_tool(capabilities)`

Erzeugt die Tool-Spezifikation, die Mistral sieht. Damit weiß das Modell exakt, welche Argumente es erzeugen darf.

### `_arguments()`

Validiert die vom Modell erzeugten Argumente noch einmal in Python. Unbekannte Felder, falsche Sortierungen oder zu große Limits werden abgelehnt.

### `query_tokens()`

Führt Filterung, Sortierung und Limit deterministisch auf der read-only Population aus. Das LLM selbst sortiert also nicht die Daten und erhält keinen freien Datenbankzugriff.

## Präsentationssatz

> **`tools.py` macht Current Data kontrollierbar: Das LLM übersetzt Sprache in einen kleinen Query-Vertrag, aber die eigentliche Datenabfrage und Validierung bleiben deterministischer Python-Code.**
