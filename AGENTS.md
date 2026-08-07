# AGENTS.md

## Zweck

Dieses Dokument definiert die verbindliche Arbeitsweise für Änderungen an `jupiter-data-transform`.

## Einstieg

Vor jeder Änderung:

1. `README.md` lesen.
2. `docs/architecture.md` lesen.
3. Die direkt betroffenen Dateien vollständig lesen.
4. Den aktuellen Datenfluss verstehen, bevor Code verändert wird.

Keine Annahmen über Verhalten treffen, das nicht im Code oder in der Dokumentation belegt ist.

## First Principles

Änderungen lösen das zugrunde liegende Problem und nicht nur dessen Symptom.

Vermeiden:

- Quick Fixes;
- zusätzliche Abstraktionen ohne konkrete Notwendigkeit;
- neue Unterordner für wenige kleine Dateien;
- parallele Implementierungen derselben Verantwortung;
- versteckte Fallbacks;
- unnötige Dependencies.

Bevor neue Struktur eingeführt wird, prüfen, ob die bestehende flache Struktur ausreicht.

## Aktuelle Architekturgrenzen

```text
main.py
    Prozessstart und Zusammenführung

config.py
    Environment-Konfiguration

discovery.py
    ausschließlich Mint-Adressen entdecken

refresh.py
    bekannte Mints über Jupiter Search aktualisieren

repository.py
    PostgreSQL lesen und schreiben

schema.sql
    persistentes Datenmodell
```

Diese Verantwortlichkeiten nicht ohne klaren architektonischen Grund vermischen.

- Discovery bewertet keine Tokens und speichert keine Marktlogik.
- Jupiter Search ist die Quelle für die gespeicherten Token-Snapshots.
- PostgreSQL-Zugriffe gehören in `repository.py`.
- Prozess-Orchestrierung gehört in `main.py`.
- Konfiguration gehört in `config.py`.

## Struktur

Die Anwendung ist bewusst kein verschachteltes Python-Package.

Neue Module nur dann anlegen, wenn dadurch eine echte Verantwortung getrennt wird. Neue Verzeichnisse nur dann anlegen, wenn mehrere zusammengehörige Module eine stabile eigene Domäne bilden.

## Dependencies

Es gibt genau eine Dependency-Datei:

```text
requirements.txt
```

Neue Pakete nur hinzufügen, wenn die Standardbibliothek oder bestehende Dependencies die Aufgabe nicht sinnvoll lösen.

`pyproject.toml` dient derzeit ausschließlich der Tool-Konfiguration.

## Datenbank

Schemaänderungen müssen explizit in `src/schema.sql` erfolgen.

Keine automatische oder versteckte Schema-Migration beim normalen Lauf einführen.

Persistierte Felder brauchen einen konkreten aktuellen Zweck.

## Fehlerbehandlung

Fehler dürfen sichtbar sein.

Keine stillen `except`-Blöcke und keine Fallbacks, die Datenverlust oder fehlerhafte Zustände verdecken.

Lang laufende Discovery- oder Refresh-Loops dürfen einzelne externe Fehler überleben, müssen diese aber eindeutig loggen.

## Scope

Nur die angeforderte Änderung durchführen.

Keine nebenläufigen Refactorings, neuen Features oder Architekturänderungen ohne Notwendigkeit.

## Validierung

Das Projekt verwendet derzeit keine Unit-Tests.

Nicht eigenständig eine Test-Infrastruktur einführen.

Mindestens:

```powershell
python -m compileall -q src
python src/main.py --help
```

Für Änderungen an externen Integrationen zusätzlich den betroffenen realen Ablauf manuell prüfen.

## Dokumentation

Wenn sich Datenfluss, Struktur, Startbefehl, Konfiguration oder Persistenz ändern, müssen `README.md` und gegebenenfalls `docs/architecture.md` im selben Arbeitsschritt angepasst werden.

Dokumentation beschreibt den tatsächlich implementierten Zustand, keine geplante Architektur.

## Git

Keine Secrets committen.

Insbesondere niemals:

```text
.env
.venv/
__pycache__/
```

GitHub-Änderungen nur durchführen, wenn sie ausdrücklich angefordert wurden.

## Kommunikation

Erklärungen kurz und konkret halten.

Technische Begriffe, Dateinamen, Commands und Code-Bezeichner bleiben in ihrer Originalsprache.
