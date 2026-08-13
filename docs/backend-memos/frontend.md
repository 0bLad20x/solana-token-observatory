# `src/frontend.py`

## Aufgabe

`frontend.py` startet die bereits definierte Observatory-Anwendung. Die eigentliche Frontend-Backend-Logik liegt im Ordner `src/observatory/`.

[Quellcode](../../src/frontend.py)

## Bird's-Eye-View

```text
frontend.py → observatory.app → Observatory
```

## Import der Anwendung

Die Datei importiert `app` aus `src/observatory/app.py`. Sie definiert deshalb selbst keine API-Routen oder Analyst-Logik.

**Genutzt von:** dem direkten Start des Observatory.

## Programmstart

Beim direkten Ausführen startet die Datei den Webserver mit der importierten Anwendung. Host und Port können über die Umgebung gesetzt werden; ansonsten gelten die lokalen Standardwerte.

**Aufgerufen durch:** `python src/frontend.py`.

## Präsentationssatz

> **`frontend.py` ist nur der dünne Einstiegspunkt zum Observatory; die eigentliche API-, Daten- und Analyst-Logik bleibt im separaten `src/observatory/`-Paket.**
