# `src/lifecycle_queries.py`

## Aufgabe

`lifecycle_queries.py` liest genau die PostgreSQL-Evidence, die die Lifecycle-Regeln benötigen. Die Datei trifft keine fachliche Entscheidung und deaktiviert nichts; sie stellt nur gezielte, möglichst kleine Read-Modelle für die Regeln bereit.

[Quellcode](../../src/lifecycle_queries.py)

## Bird's-Eye-View

```text
PostgreSQL
    ↓
lifecycle_queries.py
    ↓
gezielte Evidence
    ↓
lifecycle_rules.py / lifecycle_clean.py
```

## `LifecycleQueries.__init__()`

Übernimmt die gemeinsame `Database`-Instanz. Alle Lifecycle-Reads benutzen damit dieselbe kontrollierte Datenbank-Infrastruktur.

**Aufgerufen von:** `lifecycle_clean.main()`.

## `_fetchall(query, params=None)`

Gemeinsame kleine Hilfsfunktion für read-only SQL-Abfragen. Sie öffnet eine Connection, verwendet Dictionary-Zeilen und gibt das vollständige Ergebnis als Liste zurück.

**Genutzt von:** fast allen `fetch_*`-Methoden dieser Klasse.

## `fetch_mature_active_state(observation_seconds)`

Lädt aktive Tokens, die mindestens die geforderte Beobachtungszeit erreicht haben, zusammen mit ihrem neuesten Snapshot. Diese Evidence ist die Grundlage für Rule 1.

**Genutzt von:** `lifecycle_clean.run_cycle()`.

## `fetch_continuation_checkpoint(checkpoint_minutes, signal_start_minutes, grace_seconds)`

Lädt die Evidence für den T+30-Continuation-Checkpoint und zählt zusätzlich die Snapshot-Änderungen im frühen Signal-Fenster. Die Query stellt sicher, dass nur Tokens mit ausreichender zeitlicher Coverage in den Check gelangen.

**Genutzt von:** Rule 2 in `lifecycle_clean.run_cycle()`.

## `fetch_economic_presence_checkpoint(checkpoint_minutes, grace_seconds)`

Prüft am frühen Checkpoint, ob in der bisherigen Snapshot-Historie überhaupt Market-Cap- oder Liquidity-Daten vorhanden waren. Zurückgegeben wird pro Mint vor allem die boolesche Evidence `has_economic_data`.

**Genutzt von:** Rule 3 in `lifecycle_clean.run_cycle()`.

## `fetch_holder_checkpoint(checkpoint_minutes)`

Lädt den letzten verfügbaren Snapshot bis zum T+30-Zeitpunkt relativ zur ersten Collector-Beobachtung. Dadurch kann Rule 6 die Holder-Zahl am vorgesehenen Checkpoint beurteilen.

**Genutzt von:** Rule 6 in `lifecycle_clean.run_cycle()`.

## `fetch_active_source_state()`

Lädt nur die leichten Collector-Zeitstempel aktiver Mints: erste Beobachtung, letzter Poll, letzte Änderung und Source-Version. Dafür muss keine Raw-Snapshot-Historie gelesen werden.

**Genutzt von:** Rule 7 in `lifecycle_clean.run_cycle()`.

## `fetch_threshold_scan(rule_key, field, threshold, min_age_minutes)`

Durchsucht für Rule 4 und Rule 5 nur noch die seit dem letzten sauberen Scan neu hinzugekommenen Snapshots. Die Query liefert sowohl den neuesten geprüften Zeitpunkt als auch den ersten gefundenen Floor-Crossing-Zeitpunkt.

**Genutzt von:** dem generischen Collapse-Loop in `lifecycle_clean.run_cycle()`.

## `advance_threshold_scan(rule_key, rows)`

Speichert für Tokens ohne Treffer, bis wohin Rule 4 oder Rule 5 bereits sauber geprüft haben. Dieser Cursor bewegt sich nur vorwärts und verhindert, dass dieselbe historische Evidence in jedem Lifecycle-Zyklus vollständig neu gelesen wird.

**Genutzt von:** `lifecycle_clean.run_cycle()` nach einem sauberen Threshold-Scan.

## Präsentationssatz

> **`lifecycle_queries.py` ist die Evidence-Schicht des Lifecycle-Systems: Für jede Regel liest sie nur den notwendigen Zeit- oder Snapshot-Ausschnitt und hält inkrementelle Scans effizient.**
