# Architecture

## Zweck

`jupiter-data-transform` trennt operative Datensammlung von analytischer Bewertung.

Der Collector soll Solana-Mints möglichst vollständig beobachten und deren Jupiter-Zustände historisieren. Das Diagnose-Framework wertet diese Beobachtungen anschließend aus, um belastbare Hypothesen für Polling-Priorisierung oder spätere Deaktivierung zu erzeugen.

Die Diagnose darf den Collector nicht stillschweigend in eine Lifecycle-Engine verwandeln.

## Systemgrenzen

```text
OPERATIVE DATA COLLECTION

Discovery sources
    │
    ▼
PostgreSQL: mints
    │
    ▼
MintCache -> BatchCursor -> Jupiter Search lanes -> WriteQueue
    │                                      │
    │                                      ▼
    │                              PostgreSQL:
    │                              mint_snapshots
    │
    └──────────────────────────────────────┐
                                           │
                                           ▼
READ-ONLY DIAGNOSTICS                     

current state -> regions -> flow -> cohorts -> shadow policy -> outcomes
                                           │
                              ┌────────────┴────────────┐
                              ▼                         ▼
                           dashboard                AI bundle

OPTIONAL SUPPLEMENTAL EVIDENCE

GMGN observations -----------------------> diagnostics / analysis
```

Die drei Bereiche haben unterschiedliche Authorities und dürfen nicht vermischt werden.

## 1. Discovery

`src/discovery.py` entdeckt Mint-Adressen über externe Quellen wie:

- PumpPortal `subscribeNewToken`;
- Jupiter `/tokens/v2/recent`;
- Meteora DAMM v2;
- Meteora DLMM.

Discovery liefert Kandidaten-Mints. Sie entscheidet nicht, ob ein Token wirtschaftlich gut, schlecht oder terminal ist.

Neue beziehungsweise erneut entdeckte Mints werden über `MintRepository` in die zentrale Registry überführt.

## 2. Operativer Jupiter-Refresh

`src/refresh.py` überwacht die aktiven Mints einer Priority.

### MintCache

`MintCache` lädt die aktuell aktiven Mints regelmäßig aus PostgreSQL und hält nur die für den Refresh benötigte Mint-Liste im Speicher.

### BatchCursor

`BatchCursor` rotiert deterministisch durch die sortierte Mint-Liste. Ein Batch enthält maximal 100 Mints. Änderungen der Population führen nicht zu einem vollständigen Neustart des Cursors.

### Search lanes

Für jeden konfigurierten Jupiter-Search-API-Key läuft eine eigene Lane. Alle Lanes teilen denselben Cursor und beziehen ihre Batches unabhängig voneinander.

Jede Lane fragt:

```text
GET /tokens/v2/search?query=<comma-separated mints>
```

ab.

### WriteQueue

Erfolgreiche Antworten landen zunächst in einer begrenzten asynchronen Queue. `WriteQueue` bündelt die Ergebnisse und führt blockierende PostgreSQL-Arbeit außerhalb des Event-Loops aus.

Damit sind Netzwerkabfragen und Datenbankwrites entkoppelt, ohne eine zweite persistente Queue einzuführen.

## 3. Persistenz und Beobachtungssemantik

`src/repository.py` ist die PostgreSQL-Grenze des Python-Collectors. Das dauerhafte Schema liegt explizit in `src/schema.sql`.

### `mints`

`mints` ist die operative Registry der bekannten Mint-Adressen und enthält unter anderem den aktuellen Tracking-/Priority-Zustand sowie Poll-Metadaten.

Ein erfolgreicher Jupiter-Poll ist selbst dann relevante Beobachtungsevidenz, wenn der Payload gegenüber dem vorherigen Poll unverändert bleibt.

### `mint_snapshots`

`mint_snapshots` historisiert fachlich veränderte Jupiter-Zustände.

```text
Jupiter-Poll erfolgreich
        │
        ├─ Zustand unverändert -> Poll-Freshness fortschreiben
        │
        └─ Zustand verändert   -> neuen Snapshot speichern
```

Deshalb dürfen Snapshot-Abstände nicht als direkte Poll-Abstände interpretiert werden.

## 4. Diagnose-Framework

Der Einstiegspunkt ist `src/diagnose_inactivity.py`. Die Module unter `src/diagnostics/` trennen die fachlichen Verantwortungen der Analyse.

Wesentliche Bereiche sind:

- Datenaufbereitung und Collector Health;
- aktuelle semantische Regionen;
- longitudinale Region-History und Transitionen;
- Incident-Kohorten und Outcomes;
- Activity- und Launchpad-Segmentierung;
- Shadow-Policy-Auswertung;
- Policy-Outcomes und Recovery;
- Reporting, Dashboard und AI-Export.

Die vollständige methodische Definition der sieben Phasen steht ausschließlich in [`DIAGNOSTIC_PHASES.md`](DIAGNOSTIC_PHASES.md).

## 5. One-Shot gegen Monitor

Ein manueller One-Shot:

```powershell
python src/diagnose_inactivity.py
```

analysiert den aktuellen Zustand und erzeugt die aktuellen abgeleiteten Artefakte.

Er schreibt die longitudinale Region-History standardmäßig **nicht** fort. Zwischen manuellen Läufen können beliebig große Lücken liegen; würden diese wie reguläre Monitorintervalle behandelt, entstünden falsche Dwell-Zeiten und GONE-Events.

Kontinuierliche Transition-, Cohort- und Policy-Evidenz entsteht im Monitorbetrieb:

```powershell
python src/diagnose_inactivity.py --monitor --interval-seconds 60
```

Nur kontinuierlich beobachtbare Zeiträume dürfen als entsprechende longitudinale Evidence interpretiert werden.

## 6. Shadow-Policy

Phase 6 bewertet Regeln über aktuelle und historische Features. Sie kann Actions wie `p2`, `p3` oder `retire` empfehlen.

Diese Actions sind ausschließlich Shadow-Zustände.

Das Framework:

- führt keine operative Retire-Entscheidung aus;
- ändert `tracking_enabled` nicht;
- schreibt keine neue Collector-Priority als Folge einer Diagnose;
- hält Regelversionen und Outcomes getrennt, damit alte und neue Regelstände nicht statistisch vermischt werden.

Phase 7 prüft nachgelagerte Recovery. Erst solche Outcomes können zeigen, ob eine Shadow-Entscheidung wahrscheinlich sicher oder zu aggressiv war.

## 7. Diagnose-Artefakte

Lokale Laufzeit- und Diagnoseartefakte liegen unter `data/`. Dazu gehören je nach Lauf unter anderem:

- aktueller Investigation Report;
- Region Snapshot und Region Flow;
- Population-/Transition-History;
- Cohort Outcomes;
- Policy Runs, Decision Events und Policy State;
- Policy Outcomes.

Diese Dateien sind erzeugte Evidenz und keine zweite methodische Source of Truth.

Das AI-Bundle unter `analysis/diagnostics_ai_bundle.json` verdichtet die bereits erzeugten Diagnoseartefakte für externe KI-Analyse. Der Exporter liest nicht direkt aus PostgreSQL.

## 8. GMGN

`src/gmgn.mjs` bildet einen separaten, optionalen Datenpfad für zusätzliche GMGN-Beobachtungen.

GMGN-Daten können Diagnose und Analyse ergänzen, aber ihre Abwesenheit darf eine Jupiter-basierte Beobachtung nicht automatisch invalidieren und ihre Felder dürfen nicht stillschweigend Jupiter-Felder ersetzen.

Die vollständige Feldsemantik ist absichtlich separat und ausführlich in [`GMGN_FIELDS_REFERENCE.md`](GMGN_FIELDS_REFERENCE.md) dokumentiert.

## 9. Authority-Modell

Für jede dauerhaft dokumentierte Frage existiert genau eine Authority:

| Frage | Authority |
|---|---|
| Was ist das Projekt und wie wird es benutzt? | `README.md` |
| Wie fließen Daten und wo liegen Systemgrenzen? | `docs/architecture.md` |
| Was bedeutet jede Diagnosephase statistisch? | `docs/DIAGNOSTIC_PHASES.md` |
| Was bedeuten die GMGN-Felder? | `docs/GMGN_FIELDS_REFERENCE.md` |
| Welche Regeln gelten für Repository-Änderungen? | `AGENTS.md` |

Git hält die Änderungshistorie. Generierte Artefakte halten Laufzeitevidenz. Keines von beiden wird durch zusätzliche Markdown-Kopien dupliziert.

## 10. Architekturprinzipien

1. **Eine Verantwortung, eine Authority.** Keine parallelen Implementierungen oder Dokumentationskopien.
2. **Observation vor Policy.** Erst messen, dann bewerten, erst nach validierten Outcomes operativ handeln.
3. **Missing bleibt missing.** Unbekannte Werte werden nicht zu Null umgedeutet.
4. **Poll und Snapshot sind verschiedene Ereignisse.** Zeitabhängige Regeln dürfen diese Semantik nicht vermischen.
5. **Read-only Diagnose bleibt read-only.** Produktionsmutationen brauchen eine ausdrückliche eigene Änderung.
6. **Generierte Daten sind Evidenz, nicht Architektur.** Methodik bleibt nachvollziehbar im Code und in den benannten Authorities.