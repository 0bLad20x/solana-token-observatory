# `src/repository.py`

## Aufgabe

`repository.py` ist die zentrale Persistenzschicht des operativen Backends. Discovery, Refresh, Maintenance und Lifecycle benutzen diese Datei, damit Regeln für Mint-Insert, Snapshot-Persistenz, Retention und Deaktivierung nicht über mehrere Komponenten verteilt werden.

[Quellcode](../../src/repository.py)

## Bird's-Eye-View

```text
Discovery ───┐
Refresh ─────┼──► MintRepository ───► PostgreSQL
Maintenance ─┤
Lifecycle ───┘
```

## `_parse_datetime(value)`

Wandelt ISO-Zeitstempel aus Jupiter in Python-`datetime` um. Diese normalisierten Zeiten werden später benutzt, um Source-Versionen korrekt chronologisch zu vergleichen.

**Genutzt von:** `store_tokens_grouped()`.

## `_payload(token)`

Bereitet den Jupiter-Datensatz für `JSONB` vor. Interne Collector-Felder wie `_observed_at` und `_last_polled_at` werden entfernt, damit im Snapshot nur die eigentlichen Quelldaten landen.

**Genutzt von:** `store_tokens_grouped()`.

## `StoreSummary`

Kleines Ergebnisobjekt mit der Anzahl neu angereicherter Mints und neu persistierter Snapshots. Dadurch kann die WriteQueue nach einem Flush strukturiert protokollieren und Telemetrie erzeugen.

**Genutzt von:** `refresh.py` / `WriteQueue`.

## `MintRepository.__init__()`

Übernimmt die gemeinsame `Database`-Instanz. Das Repository baut keinen eigenen Connection Pool auf, sondern benutzt die zentrale Datenbank-Infrastruktur.

**Aufgerufen von:** `main.py` und `lifecycle_clean.py`.

## `load_active_mints_by_priority(priority)`

Lädt alle Mints, die aktuell `tracking_enabled=true` besitzen und zur gewünschten Priorität gehören. Diese Liste definiert die Population, die der Refresh-Loop bei Jupiter weiter beobachtet.

**Genutzt von:** `refresh.py` / `MintCache`.

## `insert_new_mints(candidates)`

Nimmt neue Mint-Kandidaten aus Discovery entgegen, dedupliziert sie und fügt nur bislang unbekannte Adressen ein. `ON CONFLICT` sorgt dafür, dass dieselbe Mint auch bei mehreren Discovery-Quellen nur einmal in der Tabelle existiert.

**Genutzt von:** allen Discovery-Loops in `discovery.py`.

## `store_tokens_grouped(tokens)`

Das ist die zentrale Schreibfunktion für Jupiter Search. Sie gruppiert Beobachtungen nach Mint, sortiert sie nach Jupiter-`updatedAt`, reichert neue Mints mit beschreibenden Metadaten an und speichert nur Source-Versionen, die neuer als der bereits persistierte Stand sind.

Zusätzlich hält sie `last_polled_at` und `last_changed_at` getrennt: Ein erfolgreicher Poll kann aktuell sein, obwohl Jupiter seit längerer Zeit keine neue Source-Version geliefert hat. Genau diese Trennung ist später wichtige Lifecycle-Evidence.

**Genutzt von:** `refresh.py` / `WriteQueue.run()`.

## `delete_expired_snapshots(cutoff, batch_size)`

Löscht einen begrenzten Batch Raw-Snapshots vor einem Cutoff-Zeitpunkt. Die Begrenzung verhindert eine einzelne sehr große Löschtransaktion und unterstützt die 24h-Retention.

**Genutzt von:** `maintenance.py`.

## `disable_mints(candidates)`

Setzt Lifecycle-Kandidaten auf `tracking_enabled=false` und speichert Zeitpunkt und Grund. Die Mint wird bewusst nicht gelöscht, sondern nur aus der aktiven Monitoring-Population entfernt.

**Genutzt von:** `lifecycle_clean.py` über `_act()`.

## `count_active()`

Zählt die aktuell aktiven Mints. Die Zahl wird nach Lifecycle-Zyklen für Ausgabe und Telemetrie verwendet.

**Genutzt von:** `lifecycle_clean.py`.

## Präsentationssatz

> **`repository.py` ist die zentrale Persistenzgrenze: Hier werden neue Mints aufgenommen, Jupiter-Versionen sauber und monoton als Snapshots gespeichert, alte History entfernt und Lifecycle-Entscheidungen als operativer Tracking-State umgesetzt.**
