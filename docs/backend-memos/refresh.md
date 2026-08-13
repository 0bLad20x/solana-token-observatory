# `src/refresh.py`

## Aufgabe

`refresh.py` überwacht die aktive Mint-Population kontinuierlich über Jupiter Search. Die Datei hält Mints im Speicher, verteilt sie auf Batches und parallele Lanes und puffert Ergebnisse vor dem Datenbank-Write.

[Quellcode](../../src/refresh.py)

## Bird's-Eye-View

```text
PostgreSQL → MintCache → BatchCursor → Search Lanes → WriteQueue → Repository
```

## `MintCache.__init__()`

Bereitet den Speicher für eine Priority-Population vor. Der Cache besitzt zusätzlich ein Signal dafür, wann die erste Population geladen wurde.

**Erzeugt von:** `refresh_system()`.

## `MintCache.snapshot()`

Liefert die aktuelle Liste aktiver Mints aus dem Speicher. Search muss dadurch nicht vor jedem Request erneut PostgreSQL lesen.

**Genutzt von:** `BatchCursor.next_batch()`.

## `MintCache.wait_ready()`

Wartet auf das erste erfolgreiche Laden der Population. So beginnt Search erst, wenn ein definierter Cache-Zustand vorhanden ist.

**Genutzt von:** `BatchCursor` und `key_lane()`.

## `MintCache.run()`

Aktualisiert die aktive Population alle fünf Sekunden aus dem Repository. Neue Discovery-Mints kommen dadurch automatisch hinein; deaktivierte Mints verschwinden wieder.

**Gestartet von:** `refresh_system()`.

## `BatchCursor.__init__()`

Hält Cache, gemeinsamen Offset und einen Async-Lock. Damit können mehrere Lanes kontrolliert denselben Round-Robin-Cursor benutzen.

**Erzeugt von:** `refresh_system()`.

## `BatchCursor.wait_ready()`

Reicht die Readiness des MintCache an die Search-Lanes weiter.

**Genutzt von:** `key_lane()`.

## `BatchCursor.next_batch()`

Liefert bis zu 100 Mints pro Aufruf und wandert dabei zyklisch durch die Population. So werden auch große Populationen kontinuierlich abgearbeitet.

**Genutzt von:** `key_lane()`.

## `WriteQueue.__init__()`

Erzeugt den begrenzten Puffer zwischen Search und Datenbank. Dadurch sind Netzwerk-I/O und Persistenz voneinander entkoppelt.

**Erzeugt von:** `refresh_system()`.

## `WriteQueue.submit()`

Legt eine erfolgreiche Search-Antwort mit Beobachtungszeitpunkt in die Queue.

**Genutzt von:** `key_lane()`.

## `WriteQueue.run()`

Fasst wiederholte Beobachtungen derselben `(mint, updatedAt)`-Version zusammen und erhält unterschiedliche Source-Versionen. Zeit- oder größenbasiert werden die verdichteten Daten gesammelt an `repository.store_tokens_grouped()` geschrieben.

**Gestartet von:** `refresh_system()`.

## `key_lane()`

Eine Lane holt fortlaufend den nächsten Batch, fragt Jupiter Search ab und übergibt erfolgreiche Antworten an die WriteQueue. Jede Lane besitzt ihre eigene Request-Kadenz.

**Erzeugt von:** `refresh_system()`.

## `refresh_system()`

Setzt Cache, Cursor, WriteQueue und alle parallelen Search-Lanes zusammen und startet sie gemeinsam. Zusätzliche konfigurierte Lanes erhöhen dadurch den Gesamtdurchsatz, während ihre Starts zeitlich verteilt werden.

**Gestartet von:** `main.py`.

## Präsentationssatz

> **`refresh.py` ist der skalierbare Search-Motor: aktive Mints bleiben im Cache, werden zyklisch auf parallele Search-Lanes verteilt und vor der Persistenz auf echte Jupiter-Versionen verdichtet.**
