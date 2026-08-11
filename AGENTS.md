# AGENTS.md

## Zweck

Dieses Dokument definiert die verbindlichen Regeln für Änderungen an `jupiter-data-transform`. Projektbeschreibung, Bedienung, Architektur und Roadmap werden hier nicht dupliziert.

## Verbindlicher Einstieg

Vor jeder Änderung:

1. [`README.md`](README.md) lesen.
2. [`docs/architecture.md`](docs/architecture.md) lesen.
3. Die direkt betroffenen Dateien vollständig lesen.
4. Bei Lifecycle-Arbeit zusätzlich [`docs/LIFECYCLE_CONTRACT.md`](docs/LIFECYCLE_CONTRACT.md) lesen.
5. Bei Roadmap-/Scope-Fragen zusätzlich [`docs/MILESTONES.md`](docs/MILESTONES.md) lesen.

Keine Annahmen über Verhalten treffen, das nicht im Code, in persistierten Datenverträgen oder in diesen Authorities belegt ist.

## First Principles

Änderungen lösen das zugrunde liegende Problem und nicht nur dessen Symptom.

Vermeiden:

- Quick Fixes und versteckte Fallbacks;
- zusätzliche Abstraktionen ohne konkrete Verantwortung;
- parallele Implementierungen derselben Verantwortung;
- Kopien bestehender Dokumentations-Authorities;
- unnötige Dependencies oder dauerhafte Zwischenartefakte;
- implizite Änderungen von Daten- oder Lifecycle-Semantik.

Die bestehende Struktur wird erweitert, wenn eine neue fachliche Grenze existiert — nicht vorsorglich.

## Harte Systemgrenzen

Diese Invarianten gelten, solange sie nicht ausdrücklich als Architekturänderung beschlossen werden:

- Discovery entdeckt Mint-Adressen; sie bewertet keine Lifecycle-Entscheidungen.
- Jupiter Search ist die operative Quelle der gespeicherten Token-Zustände.
- Ein erfolgreicher Poll ist nicht dasselbe wie ein neuer Snapshot.
- Unterschiedliche tatsächlich beobachtete Jupiter-`updatedAt`-Versionen dürfen nicht durch Writer-Coalescing verloren gehen.
- `missing` oder `unknown` ist niemals automatisch numerische Null.
- Nur der ausdrücklich definierte Lifecycle-Pfad darf aufgrund von Lifecycle-Regeln `tracking_enabled=false` setzen.
- Die fachliche Lifecycle-Semantik folgt `docs/LIFECYCLE_CONTRACT.md`.
- Read-only Consumer dürfen operative Daten lesen, aber weder Tracking-, Priority-, Lifecycle- noch Collector-owned State verändern.

## Datenbank- und Mutation-Ownership

- `src/database.py` besitzt die process-wide PostgreSQL-Verbindungsinfrastruktur.
- `src/repository.py` besitzt Collector-Persistenz und ausdrücklich erlaubte operative Mint-Mutationen.
- `src/lifecycle_queries.py` liest Lifecycle-Evidence; es besitzt keine Mint-Mutation.
- `src/lifecycle_rules.py` enthält reine Regelentscheidungen; keine DB-Zugriffe und keine Writes.
- `src/lifecycle_clean.py` orchestriert den operativen Lifecycle und ruft Mutationen nur über `MintRepository` auf.
- Downstream-Code bleibt read-only gegenüber operativem State.

Persistente Schemaänderungen erfolgen explizit in `src/schema.sql`.

Keine versteckte Schema-Migration im normalen Lauf einführen.

## Beobachtungssemantik

Die folgenden Zustände dürfen nicht vermischt werden:

- `first_observed_at`: erste vom Collector persistierte Source-Version;
- `last_polled_at`: letzter erfolgreicher Poll;
- `last_changed_at`: lokale Beobachtungszeit der jüngsten neuen Source-Version;
- `source_updated_at`: jüngster persistierter Jupiter-`updatedAt`-Wert;
- `mint_snapshots`: immutable Historie beobachteter Source-Versionen.

Snapshot-Abstände sind deshalb keine Poll-Abstände. Fehlende Zwischen-Snapshots dürfen nicht künstlich interpoliert werden, sofern eine spätere Methodik dies nicht ausdrücklich und nachvollziehbar definiert.

## Lifecycle-Änderungen

`docs/LIFECYCLE_CONTRACT.md` ist die fachliche Authority für Rule 1–5.

Eine reine Simplification darf SQL, Python-Struktur, Datenzugriff oder Orchestrierung ändern, aber nicht:

- T0;
- Zeitfenster;
- Thresholds;
- Evidence-Auswahl;
- Missing-Value-Semantik;
- Disable-Reasons;
- Regelreihenfolge;
- First-match-Verhalten.

Vor einer reinen Lifecycle-Simplification muss der Equivalence-Verifier ausgeführt werden:

```powershell
python tools/verify_lifecycle_contract_v01.py
```

Nur wenn pro Regel exakt dieselben `(mint, reason)`-Sets entstehen, ist die Änderung gegenüber Contract v0.1 semantisch äquivalent.

## Downstream-Consumer

Frontend, Research und spätere LLM-Tools sind Consumer operativer Daten und besitzen keine Mutation-Authority.

Eine gemeinsame Abstraktion oder Query-Schicht wird erst eingeführt, wenn mehrere reale Consumer dieselbe Verantwortung teilen. Kein vorsorgliches Framework zwischen PostgreSQL und einem einzelnen Consumer bauen.

## Fehlerbehandlung

Fehler müssen sichtbar bleiben.

Keine stillen `except`-Blöcke und keine Fallbacks, die Datenverlust, fehlgeschlagene Polls oder unbekannte Zustände als valide Daten erscheinen lassen.

Lang laufende Loops dürfen einzelne externe Fehler überleben, müssen sie aber eindeutig loggen.

Operative Lifecycle-Writes müssen die im Lifecycle-Contract definierte Evidence erfüllen. Zusätzliche Safety-Layer dürfen diese Semantik nicht stillschweigend verändern oder einen zweiten fachlichen Vertrag erzeugen.

## Scope

Nur Änderungen durchführen, die für die angeforderte Aufgabe oder zur Vermeidung eines dadurch entstehenden inkonsistenten Zustands notwendig sind.

Keine beiläufigen Features oder Refactorings.

Roadmap-Ziele aus `docs/MILESTONES.md` sind keine implizite Implementierungsfreigabe. Nur ausdrücklich beauftragte Milestones oder Teilaufgaben umsetzen.

## Validierung

Mindestens die zur Änderung passenden Checks ausführen. Für allgemeine Python-Änderungen:

```powershell
python -m compileall -q src tools
python -m unittest discover -s tests -v
```

Für Lifecycle-Simplifications zusätzlich:

```powershell
python tools/verify_lifecycle_contract_v01.py
```

Für CLI- oder Entry-Point-Änderungen zusätzlich den betroffenen `--help`-Aufruf prüfen.

Externe Integrationen zusätzlich gegen den realen betroffenen Ablauf validieren.

## Dokumentation

Dauerhafte Dokumentation hat genau eine Authority pro Frage:

- `README.md`: Zweck, Einstieg und Bedienung.
- `docs/architecture.md`: implementierte Komponenten, Datenfluss und Systemgrenzen.
- `docs/LIFECYCLE_CONTRACT.md`: fachliche Semantik und Version des operativen Lifecycle.
- `docs/MILESTONES.md`: aktueller Stand und nächste Entwicklungsrichtung; keine Authority für implementierten Zustand.
- `AGENTS.md`: Änderungsregeln.

Änderungshistorie gehört in Git. Refactoring-, Research- und Optimization-Notizen werden nicht als dauerhafte Architektur-Authority verwendet.

Wenn sich Datenfluss, Bedienung, Persistenz oder Methodik ändern, muss im selben Arbeitsschritt die zuständige Authority angepasst werden.

## Git

Keine Secrets committen. Insbesondere niemals `.env`, virtuelle Environments oder lokale Runtime-Daten.

GitHub-Änderungen nur durchführen, wenn sie ausdrücklich angefordert wurden.

## Kommunikation

Erklärungen kurz und konkret halten. Technische Begriffe, Dateinamen, Commands und Code-Bezeichner bleiben in ihrer Originalsprache.
