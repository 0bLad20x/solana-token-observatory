# `src/database.py`

## Aufgabe

`database.py` kapselt die technische PostgreSQL-Infrastruktur. Die Datei verwaltet einen gemeinsamen Connection Pool, initialisiert bei Bedarf das Schema und behandelt einen speziellen PostgreSQL-Parallelitätsfehler gezielt — fachliche Token-Queries gehören bewusst nicht hierher.

[Quellcode](../../src/database.py)

## Bird's-Eye-View

```text
repository.py / lifecycle_queries.py
              │
              ▼
         database.py
              │
      Connection Pool
              │
              ▼
          PostgreSQL
```

## `retry_on_deadlock(fn)`

Decorator für Schreiboperationen, die bei parallelem Datenbankzugriff in einen PostgreSQL-Deadlock geraten können. Nur dieser konkrete Fehler wird maximal dreimal mit kurzer Wartezeit erneut versucht; andere Fehler bleiben sichtbar.

**Genutzt von:** mehreren Schreibmethoden in `repository.py`.

## `Database.__init__()`

Erzeugt den pro Prozess verwendeten PostgreSQL-Connection-Pool. Standardmäßig hält der Pool mindestens zwei und höchstens zwanzig Verbindungen bereit, sodass parallele Backend-Arbeit Connections wiederverwenden kann.

**Aufgerufen von:** `main.py` und `lifecycle_clean.py`.

## `connection()`

Gibt eine Connection aus dem Pool als Context Manager zurück. Die aufrufende Komponente kann damit SQL ausführen; nach dem `with`-Block wird die Verbindung sauber an den Pool zurückgegeben.

**Genutzt von:** `repository.py`, `lifecycle_queries.py` und `initialize_schema()`.

## `initialize_schema()`

Liest `src/schema.sql` und führt es auf PostgreSQL aus. Damit werden Tabellen und Indizes beim Kommando `python src/main.py init-schema` angelegt, ohne dass die Schema-Definition in Python dupliziert wird.

**Aufgerufen von:** `main.py` beim CLI-Kommando `init-schema`.

## `close()`

Schließt den Connection Pool und damit die vom Prozess gehaltene Datenbank-Infrastruktur. Das wird beim kontrollierten Beenden automatisch über den Context Manager ausgeführt.

**Genutzt von:** `Database.__exit__()`.

## `__enter__()` / `__exit__()`

Machen `Database` selbst zu einem Context Manager. Dadurch kann `main.py` mit `with Database(...) as database:` arbeiten und garantiert den Pool am Ende schließen — auch wenn innerhalb des Blocks ein Fehler auftritt.

**Genutzt von:** `main.py` und `lifecycle_clean.py`.

## Präsentationssatz

> **`database.py` stellt die robuste PostgreSQL-Grundverbindung bereit: einen begrenzten Connection Pool, Schema-Initialisierung und gezielte Retries bei einem klar erkannten Parallelitätskonflikt, aber keinerlei fachliche Token-Logik.**
