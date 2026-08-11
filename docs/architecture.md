# Architecture

## Zweck

`jupiter-data-transform` trennt operative Datensammlung, operative Lifecycle-Entscheidungen und read-only Research.

Der Collector soll Solana-Mints entdecken und deren Jupiter-Zustände effizient beobachten. Der Lifecycle reduziert diese operative Population anhand expliziter wirtschaftlicher Regeln. Analytische Systeme untersuchen anschließend die verbleibenden Tokens, ohne selbst operative Mutationen auszuführen.

## Systemübersicht

```text
DISCOVERY
PumpPortal / Jupiter Recent / Meteora
        ↓
PostgreSQL: mints
        ↓
JUPITER MONITORING
Search lanes -> WriteQueue -> Repository
        ↓
Poll state + changed snapshots
        │
        ├──────────────────────────────┐
        ↓                              ↓
OPERATIONAL LIFECYCLE             READ-ONLY RESEARCH
lifecycle_clean.py                diagnostics/
lifecycle_queries.py              anomaly analysis
lifecycle_rules.py                GMGN comparison
        │                              │
        ↓                              ↓
tracking_enabled=false            reports / tags / AI data
for validated rule hits           no operational mutation
```

Die beiden unteren Pfade verwenden dieselbe Beobachtungsbasis, haben aber unterschiedliche Rechte und Verantwortungen.

## 1. Datenbank-Infrastruktur

`src/database.py` besitzt den process-wide PostgreSQL-ConnectionPool.

Diese Schicht stellt Verbindungen bereit, enthält aber keine fachliche Collector-, Lifecycle- oder Research-Logik.

Persistente Schemaänderungen erfolgen ausschließlich explizit in `src/schema.sql`.

## 2. Discovery

`src/discovery.py` entdeckt Mint-Adressen über externe Quellen wie:

- PumpPortal `subscribeNewToken`;
- Jupiter `/tokens/v2/recent`;
- Meteora DAMM v2;
- Meteora DLMM.

Discovery liefert Kandidaten-Mints. Sie entscheidet nicht, ob ein Token wirtschaftlich gut, schlecht oder terminal ist.

Neue Mints werden über `MintRepository` in die zentrale Registry aufgenommen.

## 3. Operativer Jupiter-Refresh

`src/refresh.py` überwacht die aktiven Mints einer Priority.

Die Refresh-Schicht trennt Netzwerk-I/O von blockierender Datenbankarbeit. Jupiter Search liefert die operative Tokenbeobachtung; Antworten werden gebündelt an `MintRepository` übergeben.

Ein Search-Request kann maximal 100 Mint-Adressen enthalten. Mehrere API-Key-Lanes teilen sich die aktive Population.

## 4. Persistenz und Beobachtungssemantik

`src/repository.py` besitzt Collector-Persistenz und ausdrücklich erlaubte operative Mint-Mutationen.

### `mints`

`mints` ist die operative Registry. Neben Identität und Tracking-Zustand hält sie die aktuelle Beobachtungssemantik:

- `first_observed_at`: erster Search-Poll, der einen neuen fachlichen Zustand erzeugt hat;
- `last_polled_at`: letzter erfolgreicher Search-Poll;
- `last_changed_at`: letzter lokaler Zeitpunkt, an dem sich Jupiters fachlicher Zustand geändert hat;
- `source_updated_at`: zuletzt beobachteter Jupiter-`updatedAt`-Wert;
- `tracking_enabled`: ob der Mint weiter operativ überwacht wird.

### `mint_snapshots`

`mint_snapshots` historisiert ausschließlich fachlich veränderte Jupiter-Zustände.

```text
Jupiter Search erfolgreich
        │
        ├─ source updatedAt unverändert
        │      -> last_polled_at fortschreiben
        │      -> kein redundanter Snapshot
        │
        └─ source updatedAt verändert
               -> last_polled_at fortschreiben
               -> last_changed_at aktualisieren
               -> source_updated_at aktualisieren
               -> Snapshot speichern
```

Daraus folgt eine harte Interpretationsgrenze:

**Snapshot-Abstände sind keine Poll-Abstände.**

Fehlende Snapshots zwischen zwei Zustandsänderungen bedeuten nicht automatisch, dass der Collector nicht gepollt hat.

## 5. Operational Lifecycle

Der operative Lifecycle ist ein eigenständiger Pfad und darf `tracking_enabled=false` setzen.

Die Verantwortung ist auf drei fachliche Module verteilt:

### `src/lifecycle_rules.py`

Enthält reine Regelentscheidungen und Thresholds. Keine DB-Zugriffe und keine Writes.

### `src/lifecycle_queries.py`

Liest die für Lifecycle-Regeln benötigte Evidence aus PostgreSQL. Diese Schicht führt keine Mint-Mutationen aus.

### `src/lifecycle_clean.py`

Orchestriert Regelreihenfolge, Freshness-Prüfung und Circuit Breaker. Ohne `--apply` ist der Lauf ein Dry-Run.

Operative Deaktivierungen laufen ausschließlich über `MintRepository.disable_mints()`.

Damit bleibt die Mutationskette explizit:

```text
LifecycleQueries
      ↓ evidence
Lifecycle Rules
      ↓ reason
lifecycle_clean.py
      ↓ only with --apply and safety gates
MintRepository.disable_mints()
      ↓
tracking_enabled=false
```

Research-Code darf diese Mutationskette nicht umgehen.

## 6. Read-only Research

Research beginnt auf gespeicherten Beobachtungen und verändert keine operative Mint-Population.

### Diagnose-/Shadow-Policy-Subsystem

`src/diagnose_inactivity.py` und `src/diagnostics/` bilden das separate siebenphasige Diagnose- und Shadow-Policy-System.

Dort verwendete Actions wie `p2`, `p3` oder `retire` bleiben innerhalb dieses Subsystems Shadow-Empfehlungen. Sie sind nicht identisch mit den separat implementierten operativen Lifecycle-Regeln.

Die methodische Authority dieses Subsystems ist [`DIAGNOSTIC_PHASES.md`](DIAGNOSTIC_PHASES.md).

### Anomaly-/Archetype-Research

Die versionierten Bot-/Anomaly-Skripte analysieren die aktuelle Survivor-Population auf transparente mathematische Strukturen, bekannte Archetypen und neue Anomalien.

Dieser Pfad darf:

- Features und Normalisierungen berechnen;
- Tokens taggen und Review-Populationen erzeugen;
- manuelle Labels und Kalibrierung auswerten;
- AI-/Research-Bundles erzeugen.

Er darf nicht:

- `tracking_enabled` ändern;
- operative Priority ändern;
- Research-Signale automatisch in Lifecycle-Regeln umwandeln.

Die konkreten Detector-Schwellen bleiben im versionierten Code statt in einer zweiten Markdown-Authority.

## 7. GMGN

`src/gmgn.mjs` bildet einen separaten optionalen Research-Pfad.

GMGN kann Jupiter-basierte Analysen ergänzen, ersetzt aber keine fehlenden Jupiter-Felder und besitzt keine operative Lifecycle-Authority.

Die ausführliche Trenches-Feldsemantik steht in [`GMGN_FIELDS_REFERENCE.md`](GMGN_FIELDS_REFERENCE.md).

## 8. Generierte Artefakte

`data/` und `analysis/` enthalten Laufzeit- und Research-Artefakte.

Diese Dateien sind Evidence und keine zweite Source of Truth für Architektur oder Methodik. Dauerhafte Regeln und Verträge gehören in Code oder die dafür benannte Dokumentations-Authority.

## 9. Nächste Architekturgrenze

Die geplante nächste Stufe beginnt **nach** dem operativen Lifecycle:

```text
Lifecycle survivors
      ↓
OHLC / Time Buckets
      ↓
Read-only Query Layer
      ├─ Frontend
      └─ LLM Tool Calling
```

Diese Komponenten sind noch nicht Teil der implementierten Architektur. Ihr aktueller Zielrahmen steht in [`MILESTONES.md`](MILESTONES.md).

## 10. Authority-Modell

| Frage | Authority |
|---|---|
| Was ist das Projekt und wie wird es benutzt? | `README.md` |
| Wie fließen Daten und wer besitzt welche Verantwortung? | `docs/architecture.md` |
| Was bedeutet jede Phase des siebenphasigen Diagnose-Subsystems? | `docs/DIAGNOSTIC_PHASES.md` |
| Was bedeuten die GMGN-Trenches-Felder? | `docs/GMGN_FIELDS_REFERENCE.md` |
| Wo steht das Projekt und wohin soll es als Nächstes? | `docs/MILESTONES.md` |
| Welche Regeln gelten für Repository-Änderungen? | `AGENTS.md` |

## 11. Architekturprinzipien

1. **Eine Verantwortung, ein Owner.** Keine parallelen Implementierungen derselben Mutation oder Datenverantwortung.
2. **Poll und Snapshot sind verschiedene Ereignisse.** Zeitabhängige Analysen dürfen diese Semantik nicht vermischen.
3. **Missing bleibt missing.** Unbekannte Werte werden nicht zu Null oder künstlich fortgeschrieben.
4. **Operational Lifecycle und Research bleiben getrennt.** Research erzeugt Evidence; operative Mutationen benötigen einen ausdrücklich implementierten Lifecycle-Pfad.
5. **Mutationen bleiben explizit.** DB-Writes auf operative Mint-Zustände laufen über definierte Ownership und Safety Gates.
6. **Generierte Daten sind Evidence, nicht Architektur.** Methodik bleibt nachvollziehbar im Code und in den benannten Authorities.
7. **Roadmap ist keine Implementation.** `MILESTONES.md` beschreibt Richtung, nicht bereits vorhandenes Verhalten.