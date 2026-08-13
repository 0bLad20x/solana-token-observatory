# `src/config.py`

## Aufgabe

`config.py` ist die zentrale Runtime-Konfiguration des Collector-Backends. Die Datei liest Umgebungsvariablen aus `.env`, validiert notwendige Werte und stellt sie anschließend als unveränderliches `Settings`-Objekt bereit.

[Quellcode](../../src/config.py)

## Bird's-Eye-View

```text
.env / Environment
       │
       ▼
    config.py
       │
       ▼
    Settings
       │
       ├─ main.py
       ├─ discovery.py
       ├─ refresh.py
       └─ lifecycle_clean.py
```

## `_required(name)`

Liest eine verpflichtende Umgebungsvariable und entfernt Leerzeichen. Ist der Wert leer oder fehlt vollständig, bricht die Konfiguration mit einem klaren Fehler ab, statt das System mit einer unvollständigen Einstellung zu starten.

**Genutzt von:** `Settings.from_env()`.

## `_positive_float(name, default)`

Liest numerische Runtime-Werte wie Request-Timeouts oder Polling-Intervalle. Zusätzlich wird geprüft, dass der Wert größer als null ist, damit ungültige Timings früh beim Start auffallen.

**Genutzt von:** `Settings.from_env()`.

## `Settings`

Die Dataclass bündelt alle Einstellungen, die der operative Collector benötigt: PostgreSQL-URL, Jupiter-Keys und Base URL, Rate Limit, PumpPortal-Key sowie Timeout- und Discovery-Intervalle. `frozen=True` macht das Objekt nach der Erstellung unveränderlich, sodass Runtime-Code die Konfiguration nicht versehentlich verändert.

**Genutzt von:** `main.py`, `discovery.py`, `refresh.py` und `lifecycle_clean.py`.

## `jupiter_seconds_per_key`

Diese Property rechnet das konfigurierte Jupiter-Limit von Calls pro Minute in den zeitlichen Abstand zwischen zwei Requests eines einzelnen API-Keys um. Bei 60 Calls pro Minute wären das beispielsweise ungefähr eine Sekunde pro Key.

**Genutzt von:** `discovery.py` für Jupiter Recent und `refresh.py` für die Search-Lanes.

## `Settings.from_env()`

Lädt `.env`, liest und validiert alle benötigten Einstellungen und baut daraus ein vollständiges `Settings`-Objekt. Mehrere Jupiter-Search-Keys werden dabei aus einer mehrzeiligen Variable in eine Liste umgewandelt.

**Aufgerufen von:** `main.py` und `lifecycle_clean.py`.

## Präsentationssatz

> **`config.py` übersetzt die externe Runtime-Konfiguration in ein validiertes, unveränderliches `Settings`-Objekt, das alle Collector-Komponenten gemeinsam verwenden.**
