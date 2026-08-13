# `src/schema.sql`

## Aufgabe

`schema.sql` definiert die dauerhafte PostgreSQL-Struktur des Systems. Es trennt **aktuellen operativen Token-Zustand** von **zeitlicher Snapshot-Evidence** und hält zusätzlich minimalen Fortschritt für inkrementelle Lifecycle-Regeln.

[Quellcode](../../src/schema.sql)

## Bird's-Eye-View

```text
Discovery / Search / Lifecycle
            │
            ▼
        repository.py
            │
            ▼
      PostgreSQL Schema
       ├─ mints
       ├─ mint_snapshots
       └─ lifecycle_rule_state
```

## `mints`

Eine Mint-Adresse existiert hier genau einmal. Die Tabelle enthält relativ stabile Token-Fakten wie Name, Symbol oder `created_at`, aber auch den **operativen Zustand** des Observatory: `tracking_enabled`, `priority`, Collector-Zeitstempel und den Lifecycle-Retirement-Grund.

Besonders wichtig sind `first_observed_at`, `last_polled_at`, `last_changed_at` und `source_updated_at`. Dadurch kann das System unterscheiden, wann es einen Token erstmals gesehen hat, wann es zuletzt erfolgreich gefragt hat und wann Jupiter tatsächlich neue Information geliefert hat.

**Genutzt von:** `repository.py`, `refresh.py` indirekt über das Repository, `lifecycle_queries.py`, `lifecycle_clean.py` und das read-only Observatory.

## `mint_snapshots`

Jede Zeile enthält `mint`, `observed_at` und den vollständigen Jupiter-Payload als `JSONB`. Dadurch bleibt die flexible externe Datenstruktur erhalten, während PostgreSQL bei Bedarf einzelne Felder wie `mcap`, `liquidity`, `holderCount` oder verschachtelte `stats5m`-Werte direkt aus dem JSON lesen kann.

Die Tabelle ist die zeitliche Evidence des Systems. Nicht jeder HTTP-Poll wird ein Snapshot; `refresh.py` und `repository.py` sorgen davor dafür, dass nur neue Source-Versionen persistiert werden.

**Genutzt von:** `repository.py`, `lifecycle_queries.py`, `maintenance.py` indirekt über das Repository und `temporal_context.py`.

## `lifecycle_rule_state`

Diese Tabelle enthält keine Marktdaten. Sie speichert für inkrementelle Lifecycle-Regeln lediglich, bis zu welchem Snapshot-Zeitpunkt eine Mint bereits geprüft wurde.

Damit müssen Rule 4 und Rule 5 nicht bei jedem Zyklus die komplette Historie erneut durchsuchen, sondern können dort weiterlesen, wo der vorherige Scan aufgehört hat.

**Genutzt von:** `lifecycle_queries.py`.

## Indizes

Die Indizes beschleunigen die häufigsten Zugriffspfade: aktive Mints nach Priority, zeitbasierte Lifecycle-Auswahl und Retention über `observed_at`. Sie ändern keine Fachlogik, sondern sorgen dafür, dass diese Abfragen mit wachsender Datenmenge effizient bleiben.

## Präsentationssatz

> **`schema.sql` trennt die aktuelle operative Token-Population von ihrer zeitlichen Evidence: `mints` hält den aktuellen Systemzustand, `mint_snapshots` die Jupiter-Historie als JSONB und `lifecycle_rule_state` den minimalen Fortschritt inkrementeller Regeln.**
