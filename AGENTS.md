# AGENTS.md

## Zweck

Dieses Dokument definiert nur die verbindlichen Regeln für Änderungen an `jupiter-data-transform`. Projektbeschreibung, Bedienung, Architektur und Roadmap werden hier nicht dupliziert.

## Verbindlicher Einstieg

Vor jeder Änderung:

1. [`README.md`](README.md) lesen.
2. [`docs/architecture.md`](docs/architecture.md) lesen.
3. Die direkt betroffenen Dateien vollständig lesen.
4. Bei Diagnose-/Shadow-Policy-Arbeit zusätzlich [`docs/DIAGNOSTIC_PHASES.md`](docs/DIAGNOSTIC_PHASES.md) lesen.
5. Bei GMGN-Arbeit zusätzlich [`docs/GMGN_FIELDS_REFERENCE.md`](docs/GMGN_FIELDS_REFERENCE.md) lesen.
6. Bei Roadmap-/Scope-Fragen zusätzlich [`docs/MILESTONES.md`](docs/MILESTONES.md) lesen.

Keine Annahmen über Verhalten treffen, das nicht im Code, in persistierten Datenverträgen oder in diesen Authorities belegt ist.

## First Principles

Änderungen lösen das zugrunde liegende Problem und nicht nur dessen Symptom.

Vermeiden:

- Quick Fixes und versteckte Fallbacks;
- zusätzliche Abstraktionen ohne konkrete Verantwortung;
- parallele Implementierungen derselben Verantwortung;
- Kopien bestehender Dokumentations-Authorities;
- unnötige Dependencies oder dauerhafte Zwischenartefakte;
- implizite Änderungen von Daten-, Lifecycle- oder Policy-Semantik.

Die bestehende Struktur wird erweitert, wenn eine neue fachliche Grenze existiert — nicht vorsorglich.

## Harte Systemgrenzen

Diese Invarianten gelten, solange sie nicht ausdrücklich als Architekturänderung beschlossen werden:

- Discovery entdeckt Mint-Adressen; sie bewertet keine Lifecycle-Entscheidungen.
- Jupiter Search ist die operative Quelle der gespeicherten Token-Zustände.
- Ein erfolgreicher Poll ist nicht dasselbe wie ein neuer Snapshot.
- `missing` oder `unknown` ist niemals automatisch numerische Null.
- GMGN ist zusätzliche Research-Evidenz und darf fehlende Jupiter-Daten nicht stillschweigend ersetzen.
- Das operative Lifecycle-System und read-only Research sind getrennte Verantwortungen.
- Nur der ausdrücklich definierte Lifecycle-Pfad darf aufgrund von Lifecycle-Regeln `tracking_enabled=false` setzen.
- Diagnose-, Anomaly- und AI-Research dürfen keine operative Priority oder `tracking_enabled` verändern.
- `p2`, `p3` und `retire` im siebenphasigen Diagnose-Subsystem bleiben Shadow-Actions; sie sind nicht identisch mit den separat implementierten operativen Lifecycle-Regeln.
- Diagnosephasen behalten ihre eigenen Populationen und Nenner; Cross-Phase-Vergleiche folgen `docs/DIAGNOSTIC_PHASES.md`.

## Datenbank- und Mutation-Ownership

- `src/database.py` besitzt die process-wide PostgreSQL-Verbindungsinfrastruktur.
- `src/repository.py` besitzt Collector-Persistenz und ausdrücklich erlaubte operative Mint-Mutationen.
- `src/lifecycle_queries.py` liest Lifecycle-Evidence; es besitzt keine Mint-Mutation.
- `src/lifecycle_rules.py` enthält reine Regelentscheidungen; keine DB-Zugriffe und keine Writes.
- `src/lifecycle_clean.py` orchestriert den operativen Lifecycle und ruft Mutationen nur über `MintRepository` auf.
- Research-Skripte bleiben read-only gegenüber operativen Mint-Zuständen.

Persistente Schemaänderungen erfolgen explizit in `src/schema.sql`.

Keine versteckte Schema-Migration im normalen Lauf einführen.

## Beobachtungssemantik

Die folgenden Zustände dürfen nicht vermischt werden:

- `last_polled_at`: letzter erfolgreicher Poll;
- `last_changed_at`: letzter lokal beobachteter fachlicher Zustandswechsel;
- `source_updated_at`: zuletzt beobachteter Jupiter-`updatedAt`-Wert;
- `mint_snapshots`: ausschließlich fachlich veränderte gespeicherte Zustände.

Snapshot-Abstände sind deshalb keine Poll-Abstände. Fehlende Zwischen-Snapshots dürfen nicht künstlich interpoliert werden, sofern die jeweilige Methodik dies nicht ausdrücklich und nachvollziehbar definiert.

## Fehlerbehandlung

Fehler müssen sichtbar bleiben.

Keine stillen `except`-Blöcke und keine Fallbacks, die Datenverlust, fehlgeschlagene Polls oder unbekannte Zustände als valide Daten erscheinen lassen.

Lang laufende Loops dürfen einzelne externe Fehler überleben, müssen sie aber eindeutig loggen.

Operative Lifecycle-Writes benötigen belastbare aktuelle Collector-Evidence und dürfen bestehende Freshness-/Circuit-Breaker-Sicherheiten nicht stillschweigend umgehen.

## Scope

Nur Änderungen durchführen, die für die angeforderte Aufgabe oder zur Vermeidung eines dadurch entstehenden inkonsistenten Zustands notwendig sind.

Keine beiläufigen Features oder Refactorings.

Roadmap-Ziele aus `docs/MILESTONES.md` sind keine implizite Implementierungsfreigabe. Nur ausdrücklich beauftragte Milestones oder Teilaufgaben umsetzen.

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
- `docs/architecture.md`: implementierte Komponenten, Datenfluss und Systemgrenzen.
- `docs/DIAGNOSTIC_PHASES.md`: Methodik des siebenphasigen Diagnose-/Shadow-Policy-Subsystems.
- `docs/GMGN_FIELDS_REFERENCE.md`: GMGN-Trenches-Felder und deren Semantik.
- `docs/MILESTONES.md`: aktueller Stand und nächste Entwicklungsrichtung; keine Authority für implementierten Zustand.
- `AGENTS.md`: Änderungsregeln.

Änderungshistorie gehört in Git. Refactoring- und Optimization-Notizen werden nach Abschluss entfernt. Generierte Artefakte werden nicht als Dokumentationskopie verwendet.

Wenn sich Datenfluss, Bedienung, Persistenz oder Methodik ändern, muss im selben Arbeitsschritt die zuständige Authority angepasst werden.

## Git

Keine Secrets committen. Insbesondere niemals `.env`, virtuelle Environments oder lokale Runtime-Daten.

GitHub-Änderungen nur durchführen, wenn sie ausdrücklich angefordert wurden.

## Kommunikation

Erklärungen kurz und konkret halten. Technische Begriffe, Dateinamen, Commands und Code-Bezeichner bleiben in ihrer Originalsprache.