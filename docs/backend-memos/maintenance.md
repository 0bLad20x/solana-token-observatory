# `src/maintenance.py`

## Aufgabe

`maintenance.py` hält die Raw-Snapshot-Historie auf dem vorgesehenen 24-Stunden-Arbeitsfenster. Ältere Snapshot-Zeilen werden regelmäßig in begrenzten Batches bereinigt.

[Quellcode](../../src/maintenance.py)

## Bird's-Eye-View

```text
mint_snapshots → maintenance.py → repository.delete_expired_snapshots()
```

## `run_snapshot_retention_once(repository, now=None)`

Berechnet den Cutoff `jetzt - 24 Stunden` und verarbeitet ältere Snapshots in Batches von bis zu 10.000 Zeilen. Solange ein vollständiger Batch verarbeitet wurde, läuft der Pass weiter.

**Genutzt von:** `snapshot_retention_loop()`.

## `snapshot_retention_loop(repository)`

Führt beim Start einen Retention-Pass aus und wiederholt ihn anschließend einmal pro Stunde. Ein einzelner Fehler beendet den dauerhaften Loop nicht.

**Gestartet von:** `main.py` / `run()`.

## Wichtige Kreuzverbindung

Die konkrete SQL-Operation liegt in `repository.delete_expired_snapshots()`. `maintenance.py` definiert lediglich die Retention-Policy: 24 Stunden, stündlicher Lauf und Batch-Größe.

## Präsentationssatz

> **`maintenance.py` hält die Raw-History bounded: Es sorgt dafür, dass nur das 24-Stunden-Arbeitsfenster bestehen bleibt und die Snapshot-Tabelle nicht unbegrenzt wächst.**
