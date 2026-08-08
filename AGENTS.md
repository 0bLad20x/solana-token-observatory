# AGENTS.md

## Zweck

Dieses Dokument definiert nur die verbindlichen Regeln für Änderungen an `jupiter-data-transform`. Projektbeschreibung, Bedienung und Architektur werden nicht hier dupliziert.

## Verbindlicher Einstieg

Vor jeder Änderung:

1. [`README.md`](README.md) lesen.
2. [`docs/architecture.md`](docs/architecture.md) lesen.
3. Die direkt betroffenen Dateien vollständig lesen.
4. Bei Diagnose-/Policy-Arbeit zusätzlich [`docs/DIAGNOSTIC_PHASES.md`](docs/DIAGNOSTIC_PHASES.md) lesen.
5. Bei GMGN-Arbeit zusätzlich [`docs/GMGN_FIELDS_REFERENCE.md`](docs/GMGN_FIELDS_REFERENCE.md) lesen.

Keine Annahmen über Verhalten treffen, das nicht im Code, in persistierten Datenverträgen oder in diesen Authorities belegt ist.

## First Principles

Änderungen lösen das zugrunde liegende Problem und nicht nur dessen Symptom.

Vermeiden:

- Quick Fixes und versteckte Fallbacks;
- zusätzliche Abstraktionen ohne konkrete Verantwortung;
- parallele Implementierungen derselben Verantwortung;
- Kopien bestehender Dokumentations-Authorities;
- unnötige Dependencies oder dauerhafte Zwischenartefakte;
- implizite Änderungen von Daten- oder Policy-Semantik.

Die bestehende Struktur wird erweitert, wenn eine neue fachliche Grenze existiert — nicht vorsorglich.

## Harte Systemgrenzen

Diese Invarianten gelten, solange sie nicht ausdrücklich als Architekturänderung beschlossen werden:

- Discovery entdeckt Mint-Adressen; sie bewertet keine Lifecycle-Entscheidungen.
- Jupiter Search ist die operative Quelle der gespeicherten Token-Snapshots.
- PostgreSQL-Zugriffe des Python-Collectors gehören in `repository.py`.
- Ein erfolgreicher Poll ist nicht dasselbe wie ein neuer Snapshot.
- `missing` oder `unknown` ist niemals automatisch numerische Null.
- GMGN ist zusätzliche Evidenz und darf fehlende Jupiter-Daten nicht stillschweigend ersetzen.
- Das Diagnose-Framework bleibt read-only gegenüber operativer Priority und `tracking_enabled`.
- `p2`, `p3` und `retire` bleiben Shadow-Actions, bis eine Produktionsänderung ausdrücklich beauftragt und durch Outcomes abgesichert ist.
- Diagnosephasen behalten ihre eigenen Populationen und Nenner; Cross-Phase-Vergleiche folgen `docs/DIAGNOSTIC_PHASES.md`.

## Daten und Persistenz

Persistente Schemaänderungen erfolgen explizit in `src/schema.sql`.

Keine versteckte Schema-Migration im normalen Lauf einführen.

Runtime- und Diagnose-Artefakte sind keine zweite Source of Truth für Code oder Methodik. Die fachliche Authority bleibt im Code beziehungsweise in den dafür benannten Dokumenten.

## Fehlerbehandlung

Fehler müssen sichtbar bleiben.

Keine stillen `except`-Blöcke und keine Fallbacks, die Datenverlust, fehlgeschlagene Polls oder unbekannte Zustände als valide Daten erscheinen lassen.

Lang laufende Loops dürfen einzelne externe Fehler überleben, müssen sie aber eindeutig loggen.

## Scope

Nur Änderungen durchführen, die für die angeforderte Aufgabe oder zur Vermeidung eines dadurch entstehenden inkonsistenten Zustands notwendig sind.

Keine beiläufigen Features oder Refactorings.

## Validierung

Mindestens die zur Änderung passenden Checks ausführen. Für allgemeine Python-Änderungen:

```powershell
python -m compileall -q src
python -m unittest discover -s tests -v
```

Für CLI- oder Entry-Point-Änderungen zusätzlich den betroffenen `--help`-Aufruf prüfen.

Externe Integrationen zusätzlich gegen den realen betroffenen Ablauf validieren.

## Dokumentation

Dauerhafte Dokumentation hat genau eine Authority pro Frage:

- `README.md`: Zweck, Einstieg und Bedienung.
- `docs/architecture.md`: Komponenten, Datenfluss und Systemgrenzen.
- `docs/DIAGNOSTIC_PHASES.md`: Diagnosemethodik und zulässige Schlussfolgerungen.
- `docs/GMGN_FIELDS_REFERENCE.md`: GMGN-Felder und deren Semantik.
- `AGENTS.md`: Änderungsregeln.

Änderungshistorie gehört in Git. Refactoring-Notizen werden nach Abschluss entfernt. Generierte Artefakte werden nicht als Dokumentationskopie verwendet.

Wenn sich Datenfluss, Bedienung, Persistenz oder Methodik ändern, muss im selben Arbeitsschritt die zuständige Authority angepasst werden.

## Git

Keine Secrets committen. Insbesondere niemals `.env`, virtuelle Environments oder lokale Runtime-Daten.

GitHub-Änderungen nur durchführen, wenn sie ausdrücklich angefordert wurden.

## Kommunikation

Erklärungen kurz und konkret halten. Technische Begriffe, Dateinamen, Commands und Code-Bezeichner bleiben in ihrer Originalsprache.