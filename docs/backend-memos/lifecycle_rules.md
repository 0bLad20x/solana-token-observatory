# `src/lifecycle_rules.py`

## Aufgabe

`lifecycle_rules.py` enthält die fachlichen Schwellenwerte und Klassifikationsfunktionen für die sieben Hard-Retire-Regeln. Die Datei liest keine Datenbank und deaktiviert keine Tokens selbst; sie beantwortet nur: **Erfüllt diese Evidence die Regel oder nicht?**

[Quellcode](../../src/lifecycle_rules.py)

## Bird's-Eye-View

```text
Lifecycle Evidence
      ↓
lifecycle_rules.py
      ↓
Reason oder None
      ↓
lifecycle_clean.py
```

## Konstanten

Die Konstanten definieren Zeitpunkte und Schwellenwerte wie T+10, T+30, Liquidity-/Market-Cap-Floors oder die 24h-Inaktivität. Dadurch stehen fachliche Parameter zentral und nicht verstreut in Queries oder Orchestrierungscode.

**Genutzt von:** `lifecycle_clean.py` und den Klassifikationsfunktionen dieser Datei.

## `CollapseRule`

Kleine unveränderliche Dataclass für Rule 4 und Rule 5. Sie bündelt Rule-Key, JSON-Feld, Floor und gespeicherten Retirement-Grund, sodass beide Collapse-Regeln denselben generischen Scan-Pfad verwenden können.

**Genutzt von:** `COLLAPSE_RULES` und `lifecycle_clean.py`.

## `_as_float(payload, key)`

Liest einen numerischen Wert robust aus einem Jupiter-Payload. Fehlende oder nicht interpretierbare Werte werden als `None` behandelt statt als null oder automatisch schlecht.

**Genutzt von:** mehreren `classify_*`-Funktionen.

## `_as_int(payload, key)`

Verwendet `_as_float()` und wandelt den Wert anschließend in Integer um. Das wird vor allem für Holder-Zahlen gebraucht.

**Genutzt von:** `classify_rule1()` und `classify_rule6()`.

## `classify_rule1(payload)`

Prüft nach der ersten Beobachtungsphase, ob ein Token wirtschaftlich nicht gezündet hat: zu wenig Liquidität und/oder gleichzeitig sehr niedrige Market Cap und Holder-Zahl. Bei Treffer wird ein konkreter Reason-String zurückgegeben.

**Aufgerufen von:** `lifecycle_clean.run_cycle()`.

## `classify_rule2(payload, changes_in_window)`

Prüft den T+30-Continuation-Checkpoint. Ein bereits etablierter Token wird geschützt; ansonsten kann eine sehr geringe Zahl an Source-Änderungen im frühen Fenster als Continuation Failure klassifiziert werden.

**Aufgerufen von:** `lifecycle_clean.run_cycle()`.

## `classify_rule3(has_economic_data)`

Prüft den T+5-Checkpoint auf wirtschaftliche Daten. Fehlen sowohl Market-Cap- als auch Liquidity-Evidence, liefert die Funktion den Retirement-Grund für Rule 3.

**Aufgerufen von:** `lifecycle_clean.run_cycle()`.

## Rule 4 und Rule 5

Dafür existiert keine eigene `classify_rule4/5()`-Funktion. Beide Regeln sind als `COLLAPSE_RULES` definiert und werden generisch über historische Threshold-Scans in `lifecycle_queries.py` geprüft.

**Genutzt von:** `lifecycle_clean.run_cycle()`.

## `classify_rule6(payload)`

Prüft am T+30-Checkpoint die Holder-Zahl. Liegt sie unter fünf, wird der entsprechende Retirement-Grund zurückgegeben.

**Aufgerufen von:** `lifecycle_clean.run_cycle()`.

## `classify_rule7(first_observed_at, last_polled_at, last_changed_at, now)`

Unterscheidet Collector-Ausfall von echter Source-Inaktivität. Nur wenn der Token frisch gepollt wird, aber seit mindestens 24 Stunden keine neue Jupiter-Version mehr beobachtet wurde, greift Rule 7.

**Aufgerufen von:** `lifecycle_clean.run_cycle()`.

## Präsentationssatz

> **`lifecycle_rules.py` enthält reine Entscheidungslogik: Es definiert die fachlichen Schwellenwerte und übersetzt bereits geladene Evidence in einen Retirement-Grund oder in „keine Regel erfüllt“.**
