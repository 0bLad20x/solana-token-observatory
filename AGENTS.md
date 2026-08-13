# AGENTS.md

## Zweck

Dieses Dokument definiert die verbindlichen Regeln für Änderungen an `solana-token-observatory`. Projektbeschreibung und Bedienung stehen in `README.md`; Architektur- und Fachverträge besitzen eigene Authorities.

## Verbindlicher Einstieg

Vor jeder Änderung:

1. `README.md` lesen.
2. `docs/architecture.md` lesen.
3. die direkt betroffenen Dateien vollständig lesen.
4. bei Lifecycle-Arbeit zusätzlich `docs/LIFECYCLE_CONTRACT.md` lesen.
5. bei Observatory-/Frontend-Arbeit zusätzlich `docs/FRONTEND_OBSERVATORY.md` lesen.

Keine Annahmen über Verhalten treffen, das nicht im Code, in Datenverträgen oder in den Authorities belegt ist.

## First Principles

Änderungen lösen das zugrunde liegende Problem und nicht nur dessen Symptom.

Vermeiden:

- Quick Fixes und versteckte Fallbacks;
- parallele Implementierungen derselben Verantwortung;
- zusätzliche Abstraktionen ohne konkrete Verantwortung;
- unnötige Dependencies oder dauerhafte Zwischenartefakte;
- Kopien bestehender Dokumentations-Authorities;
- implizite Änderungen von Daten-, Lifecycle- oder Evidence-Semantik.

## Harte Systemgrenzen

- Discovery entdeckt Mint-Adressen; sie trifft keine Lifecycle-Entscheidungen.
- Jupiter Search ist die operative Quelle der gespeicherten Token-Zustände.
- Ein erfolgreicher Poll ist nicht dasselbe wie ein neuer Snapshot.
- Unterschiedliche tatsächlich beobachtete Jupiter-`updatedAt`-Versionen dürfen nicht verloren gehen.
- `missing` oder `unknown` ist niemals automatisch numerische Null.
- Nur der definierte Lifecycle-Pfad darf aufgrund von Lifecycle-Regeln `tracking_enabled=false` setzen.
- Read-only Consumer dürfen Tracking-, Priority-, Lifecycle- oder Collector-owned State nicht verändern.
- External Evidence bleibt externe Evidence; LLM-Interpretation besitzt keine operative Authority.

## Ownership

- `src/database.py`: process-wide PostgreSQL-Verbindungsinfrastruktur.
- `src/repository.py`: Collector-Persistenz und erlaubte operative Mint-Mutationen.
- `src/lifecycle_queries.py`: read-only Lifecycle-Evidence.
- `src/lifecycle_rules.py`: reine Regelentscheidungen.
- `src/lifecycle_clean.py`: Lifecycle-Orchestrierung.
- `src/schema.sql`: explizite persistente Schema-Authority.
- `src/observatory/`: read-only Downstream-Consumer.

Keine versteckten Schema-Migrationen im normalen Lauf einführen.

## Lifecycle

`docs/LIFECYCLE_CONTRACT.md` ist die fachliche Authority für Rule 1–7.

Eine Simplification darf interne Struktur ändern, aber nicht stillschweigend T0, Zeitfenster, Thresholds, Evidence, Missing-Semantik, Disable-Reasons, Regelreihenfolge oder First-match-Verhalten verändern.

Für Änderungen an Rule 1–5 muss der Equivalence-Verifier ausgeführt werden:

```powershell
python tools/verify_lifecycle_contract_v01.py
```

Rule 6 und Rule 7 werden zusätzlich über ihre gezielten Unit-Tests validiert.

## Observatory / Frontend

`docs/FRONTEND_OBSERVATORY.md` ist die Authority für Read-only-Grenze, Truth Layers, Population/Selection, Browser-Synchronisation, Analyst und Telemetry.

- Population State besitzt keine Presentation Truth.
- `/api/events` bleibt die Browser-Synchronisationsgrenze für die aktive Population.
- konkrete Views sind Consumer und keine Domain-Authority.
- LLM-Keys und externe Analyst-Zugänge bleiben serverseitig.
- LLM-Tools bleiben bounded und read-only.
- External Evidence wird nicht zu operativer Truth umgedeutet.
- neue Frontend-, View-, Event- oder Agent-Abstraktionen benötigen eine konkrete Verantwortung.

## Fehlerbehandlung

Fehler müssen sichtbar bleiben. Keine stillen Fallbacks, die Datenverlust, fehlgeschlagene Polls oder unbekannte Zustände als valide Daten erscheinen lassen.

Lang laufende Loops dürfen einzelne externe Fehler überleben, müssen sie aber eindeutig loggen.

## Scope

Nur Änderungen durchführen, die für die angeforderte Aufgabe oder zur Vermeidung eines dadurch entstehenden inkonsistenten Zustands notwendig sind. Keine beiläufigen Features oder Refactorings.

Offene Roadmap-Arbeit wird in GitHub Issues geführt und ist keine implizite Implementierungsfreigabe.

## Validierung

Für allgemeine Python-Änderungen mindestens:

```powershell
python -m compileall -q src tools
python -m unittest discover -s tests -v
```

Für Lifecycle Rule 1–5 zusätzlich:

```powershell
python tools/verify_lifecycle_contract_v01.py
```

Für Rule 6 / Rule 7 zusätzlich:

```powershell
python -m unittest tests.test_lifecycle_rule6 tests.test_lifecycle_rule7 -v
```

Für Frontend-Synchronisations-/State-Änderungen die betroffenen Node-Tests und den realen Browserpfad prüfen.

## Dokumentation

Dauerhafte Dokumentation hat genau eine Authority pro Frage:

- `README.md`: Zweck, Einstieg und Bedienung.
- `docs/architecture.md`: Komponenten, Datenfluss und Systemgrenzen.
- `docs/LIFECYCLE_CONTRACT.md`: Lifecycle-Semantik.
- `docs/FRONTEND_OBSERVATORY.md`: Observatory-/Analyst-/Telemetry-Vertrag.
- `AGENTS.md`: Änderungsregeln.

Änderungshistorie gehört in Git; offene Arbeit in GitHub Issues.

## Git

Keine Secrets, `.env`, virtuelle Environments oder lokale Runtime-Daten committen. GitHub-Änderungen nur durchführen, wenn sie ausdrücklich angefordert wurden.
