# `src/observatory/telemetry.py`

## Aufgabe

Diese Datei empfängt die lossy UDP-Telemetrie des Collectors und hält sie kurzfristig im RAM für das Observatory. Sie besitzt keine operative Authority und schreibt nichts zurück in den Collector.

### `TelemetryStore`

Speichert valide Events in einem zeitlich begrenzten `deque`. Zusätzlich verwaltet der Store Subscriber-Queues für Live-Streams.

### `_prune()`

Entfernt Events, die außerhalb des konfigurierten Retention-Fensters liegen.

### `push()`

Validiert ein Event über den zentralen Telemetry-Vertrag und verteilt es anschließend an Store und Subscriber.

### `snapshot()`

Liefert die aktuell retained Events als read-only Snapshot.

### `subscribe_with_snapshot()` / `unsubscribe()`

Registrieren beziehungsweise entfernen Live-Subscriber. Ein neuer Subscriber bekommt zuerst den aktuellen Snapshot und danach neue Events.

### `_TelemetryDatagramProtocol`

Dekodiert eingehende UDP-Pakete und übergibt gültiges JSON an den Store.

### `TelemetryReceiver`

Öffnet und schließt den lokalen UDP-Listener.

**Genutzt von:** `app.py` für `/api/telemetry` und den Telemetry-Live-Stream.

## Präsentationssatz

> **`observatory/telemetry.py` macht die Runtime sichtbar, ohne Teil ihrer Steuerung zu werden: Collector-Events werden lokal empfangen, kurz im RAM gehalten und read-only an das Observatory weitergegeben.**
