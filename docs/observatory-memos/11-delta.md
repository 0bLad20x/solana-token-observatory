# `src/observatory/delta.py`

## Aufgabe

`delta.py` vergleicht zwei Universe-Zustände und beschreibt nur die relevanten Änderungen.

### `fingerprint(token)`

Erzeugt aus wichtigen Zustandsfeldern einen Vergleichswert. Bleibt er gleich, muss kein Update gesendet werden.

### `numeric_change(before, after)`

Berechnet absolute und prozentuale Veränderung eines Zahlenwertes. Fehlende Werte bleiben unbekannt.

### `changes(before, after)`

Berechnet diese Unterschiede für die wichtigsten Markt- und Aktivitätsfelder.

**Genutzt von:** `app.py` im Live-Universe-Stream.

## Präsentationssatz

> **`delta.py` reduziert den Live-Stream auf echte Änderungen, nachdem der Client einmal einen vollständigen Ausgangszustand erhalten hat.**
