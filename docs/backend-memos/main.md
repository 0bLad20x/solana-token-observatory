# `src/main.py`

## Aufgabe

`main.py` ist der Einstiegspunkt des operativen Collectors. Die Datei lädt Konfiguration und Datenbank, baut Repository und Telemetrie auf und startet anschließend die Discovery-, Refresh- und Maintenance-Loops gemeinsam.

[Quellcode](../../src/main.py)

## Bird's-Eye-View

```text
main.py
 ├─ pump_loop
 ├─ jupiter_recent_loop
 ├─ meteora_damm_v2_loop
 ├─ meteora_dlmm_loop
 ├─ refresh_system
 └─ snapshot_retention_loop
```

## `parser()`

Definiert die beiden CLI-Kommandos `init-schema` und `run`. Dadurch bleibt Datenbank-Bootstrap vom normalen Collector-Start getrennt.

**Genutzt von:** `main()`.

## `run(settings, repository, telemetry)`

Startet mit `asyncio.gather()` alle dauerhaft laufenden Collector-Komponenten parallel. Discovery, Search und Retention sind eigenständige Tasks im selben Event Loop.

**Aufgerufen von:** `main()` über `asyncio.run()`.

## `main()`

Konfiguriert Logging, lädt `Settings`, öffnet die Datenbank und entscheidet anhand des CLI-Kommandos zwischen Schema-Initialisierung und normalem Betrieb. Beim `run`-Pfad werden `MintRepository` und `TelemetryEmitter` aufgebaut und beim Beenden sauber geschlossen.

**Aufgerufen von:** direkt beim Start mit `python src/main.py ...`.

## Wichtige Kreuzverbindung

Die Lifecycle-Engine läuft bewusst nicht in `main.py`. `lifecycle_clean.py` ist ein separater Prozess und greift über dieselbe PostgreSQL-Datenbasis auf den operativen Zustand zu.

## Präsentationssatz

> **`main.py` ist der Orchestrator des Collector-Prozesses: Es startet Discovery, Jupiter Search und Snapshot-Retention parallel und verbindet sie mit gemeinsamer Konfiguration, Persistenz und Telemetrie.**
