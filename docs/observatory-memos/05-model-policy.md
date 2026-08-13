# `src/observatory/model_policy.py`

## Aufgabe

`model_policy.py` entscheidet zentral, welche Modellklasse für welchen Analyst-Use-Case verwendet wird.

### `USE_CASE_TIERS`

Ordnet `current_data` dem Fast-Tier zu. Web, Temporal und RugCheck verwenden das Strong-Tier.

### `ModelPolicy.__post_init__()`

Prüft, dass beide konfigurierten Modellnamen vorhanden sind.

### `tier_for(use_case)`

Liefert für einen Use Case `fast` oder `strong`.

### `model_for(use_case)`

Übersetzt den Tier in den konkreten Modellnamen aus der Konfiguration.

**Genutzt von:** `app.py` vor jedem Analyst-Aufruf.

## Präsentationssatz

> **`model_policy.py` hält die Modellwahl an einer Stelle: Current Data nutzt den Fast-Pfad, die interpretativeren Scopes Web, Temporal und RugCheck den Strong-Pfad.**
