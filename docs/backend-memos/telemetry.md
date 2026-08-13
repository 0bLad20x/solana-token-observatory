# `src/telemetry.py`

## Aufgabe

`telemetry.py` erzeugt kleine Runtime-Events über das Verhalten des operativen Backends. Diese Telemetrie ist bewusst **best effort**: Sie hilft bei Beobachtung und Visualisierung, darf aber niemals Discovery, Search, Persistenz oder Lifecycle blockieren.

[Quellcode](../../src/telemetry.py)

## Bird's-Eye-View

```text
Discovery / Refresh / Lifecycle
           │
           ▼
    TelemetryEmitter
           │
      localhost UDP
           │
           ▼
 src/observatory/telemetry.py
```

## `_has_forbidden_key(value)`

Durchsucht ein Event rekursiv nach verbotenen sensiblen Feldnamen. Damit werden versehentlich mitgegebene Zugangsdaten nicht als Telemetrie versendet.

**Genutzt von:** `validate_telemetry_event()`.

## `validate_telemetry_event(event)`

Prüft, ob Event-Typ, Zeitstempel und die jeweils benötigten Felder vorhanden sind. Nur die definierten Typen `discovery_tick`, `search_lane_tick`, `search_flush` und `lifecycle_tick` werden akzeptiert.

**Genutzt von:** `TelemetryEmitter.emit()` und vom read-only Telemetry-Receiver im Observatory.

## `TelemetryEmitter.__init__()`

Bereitet einen nicht blockierenden UDP-Socket zu einem lokalen Empfänger vor. Kann der Socket nicht geöffnet werden, bleibt der operative Core trotzdem funktionsfähig.

**Erzeugt von:** `TelemetryEmitter.from_env()`.

## `TelemetryEmitter.from_env()`

Liest Host und Port der Telemetrie aus der Umgebung und erzeugt den Emitter.

**Aufgerufen von:** `main.py` und `lifecycle_clean.py`.

## `TelemetryEmitter.emit(event_type, **fields)`

Baut ein Event mit UTC-Zeitstempel, validiert es und sendet ein kompaktes JSON-Datagramm. Fehler, ungültige Events oder zu große Payloads führen nur zu `False`, nicht zu einem Ausfall des Collectors.

**Genutzt von:** `discovery.py`, `refresh.py` und `lifecycle_clean.py`.

## `TelemetryEmitter.close()`

Schließt den UDP-Socket beim Beenden des jeweiligen Prozesses.

**Genutzt von:** `main.py` und `lifecycle_clean.py`.

## Präsentationssatz

> **`telemetry.py` macht Discovery, Search, Flushes und Lifecycle sichtbar, bleibt aber absichtlich ein verlustbehafteter Nebenkanal, damit Beobachtbarkeit niemals zur operativen Abhängigkeit wird.**
