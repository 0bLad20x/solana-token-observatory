# Architecture

## Zweck

`jupiter-data-transform` trennt operative Datensammlung, persistierte Beobachtung, operative Lifecycle-Entscheidungen und read-only Downstream-Nutzung.

Der Core soll Solana-Mints entdecken, deren Jupiter-Zustände effizient beobachten, tatsächlich beobachtete Source-Versionen nachvollziehbar persistieren und die aktive Population anhand eines expliziten Lifecycle-Contracts reduzieren.

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
mints + mint_snapshots
        ↓                 ↓
OPERATIONAL LIFECYCLE   SNAPSHOT MAINTENANCE
lifecycle_clean.py      24h Raw Retention
lifecycle_queries.py
lifecycle_rules.py
        ↓
tracking_enabled=false
```

Read-only Consumer wie Research, Frontend oder spätere LLM-Tools dürfen diese persistierten Daten lesen, gehören aber nicht zur operativen Mutationskette.

## 1. Datenbank-Infrastruktur

`src/database.py` besitzt den process-wide PostgreSQL-ConnectionPool.

Diese Schicht stellt Verbindungen bereit, enthält aber keine fachliche Discovery-, Collector-, Lifecycle- oder Downstream-Logik.

Persistente Schemaänderungen erfolgen ausschließlich explizit in `src/schema.sql`.

## 2. Discovery

`src/discovery.py` entdeckt Mint-Adressen über externe Quellen wie:

- PumpPortal `subscribeNewToken`;
- Jupiter `/tokens/v2/recent`;
- Meteora DAMM v2;
- Meteora DLMM.

Discovery liefert Kandidaten-Mints. Sie bewertet keine wirtschaftliche Qualität und trifft keine Lifecycle-Entscheidungen.

Neue Mints werden über `MintRepository` in die zentrale Registry aufgenommen.

## 3. Operativer Jupiter-Refresh

`src/refresh.py` überwacht aktive Mints einer Priority.

Mehrere API-Key-Lanes arbeiten unabhängig mit Jupiter Search. Ein Request kann maximal 100 Mint-Adressen enthalten. Die aktive Population wird über einen gemeinsamen Batch-Cursor verteilt.

Netzwerk-I/O und blockierende PostgreSQL-Writes sind getrennt. Erfolgreiche Search-Antworten werden über die `WriteQueue` an `MintRepository` übergeben.

Die Queue darf identische `(mint, updatedAt)`-Antworten innerhalb ihres Buffers zusammenfassen, aber keine unterschiedlichen Jupiter-Source-Versionen eines Mints verwerfen.

## 4. Persistenz und Beobachtungssemantik

`src/repository.py` besitzt Collector-Persistenz und die ausdrücklich erlaubten operativen Datenbank-Mutationen des Core.

### `mints`

`mints` ist die operative Registry. Sie hält langlebige Mint-Fakten sowie den aktuellen Collector- und Lifecycle-Zustand:

- `first_observed_at`: erste vom Collector persistierte Jupiter-Source-Version;
- `last_polled_at`: letzter erfolgreicher Search-Poll;
- `last_changed_at`: lokale Beobachtungszeit der jüngsten neuen Source-Version;
- `source_updated_at`: jüngster persistierter Jupiter-`updatedAt`-Wert;
- `tracking_enabled`: ob der Mint operativ weiter überwacht wird;
- `disabled_at`: Zeitpunkt der operativen Lifecycle-Deaktivierung;
- `disabled_reason`: Lifecycle-Reason der Deaktivierung.

### `mint_snapshots`

`mint_snapshots` hält die hochaufgelöste Raw-Historie tatsächlich beobachteter Jupiter-Source-Versionen.

```text
Jupiter Search erfolgreich
        │
        ├─ updatedAt bereits bekannt
        │      -> last_polled_at fortschreiben
        │      -> kein redundanter Snapshot
        │
        └─ neue updatedAt-Version(en)
               -> jede beobachtete neue Version persistieren
               -> source_updated_at fortschreiben
               -> last_changed_at aktualisieren
               -> last_polled_at fortschreiben
```

Daraus folgt eine harte Interpretationsgrenze:

**Snapshot-Abstände sind keine Poll-Abstände.**

Fehlende Zwischen-Snapshots bedeuten nicht automatisch, dass der Collector nicht gepollt hat.

`mint_snapshots` ist kein unbegrenztes Langzeitarchiv. Die Tabelle ist ein 24-Stunden-Raw-Working-Buffer. `src/maintenance.py` führt beim Start des normalen Collectors und danach stündlich gebatchte Cleanup-Läufe aus; `MintRepository.delete_expired_snapshots()` löscht ausschließlich Rows mit `observed_at` vor dem globalen 24h-Cutoff. Es gibt keine per-Mint- oder Lifecycle-Sonderlogik in der Retention.

Für den globalen Retention-Cutoff existiert zusätzlich zum Primärschlüssel `(mint, observed_at)` ein Index mit `observed_at` als führendem Key.

## 5. Operational Lifecycle

Der operative Lifecycle ist ein eigenständiger Pfad und darf `tracking_enabled=false` setzen.

Die fachliche Semantik von Rule 1–5 ist in [`LIFECYCLE_CONTRACT.md`](LIFECYCLE_CONTRACT.md) als Contract v0.1 eingefroren. Änderungen an Thresholds, Zeitfenstern, T0, Evidence-Auswahl, Missing-Semantik, Reasons oder Regelreihenfolge sind Contract-Änderungen und keine bloßen Refactorings.

Die Verantwortung ist auf drei Module verteilt:

### `src/lifecycle_rules.py`

Enthält reine Regelentscheidungen und Thresholds. Keine DB-Zugriffe und keine Writes.

### `src/lifecycle_queries.py`

Liest die für Lifecycle-Regeln benötigte Evidence aus PostgreSQL. Diese Schicht führt keine Mint-Mutationen aus.

### `src/lifecycle_clean.py`

Orchestriert Regelreihenfolge, Rule-1-Current-State-Freshness und Betriebsmodus. Ohne `--apply` ist der Lauf ein Dry-Run.

Operative Deaktivierungen laufen ausschließlich über `MintRepository.disable_mints()`.

```text
LifecycleQueries
      ↓ evidence
Lifecycle Rules
      ↓ reason
lifecycle_clean.py
      ↓ contract-defined ordering / mode
MintRepository.disable_mints()
      ↓
tracking_enabled=false
+ disabled_at
+ disabled_reason
```

Vor einer reinen Lifecycle-Simplification wird die aktuelle Implementierung mit `tools/verify_lifecycle_contract_v01.py` gegen die eingefrorene v0.1-Referenz auf demselben PostgreSQL-Snapshot verglichen.

## 6. Read-only Downstream

Downstream-Code darf operative Daten lesen und daraus eigene Projektionen, Visualisierungen oder Analysen erzeugen.

Er darf nicht:

- `tracking_enabled` verändern;
- operative Priority verändern;
- `lifecycle_rule_state` verändern;
- Collector-owned Observation State überschreiben;
- Research- oder UI-Signale stillschweigend zu Lifecycle-Regeln machen.

Diese Grenze gilt unabhängig davon, ob der Consumer ein Research-Skript, ein Frontend oder ein späteres LLM-Tool ist.

`tools/inspect_token_history.py` ist der aktuelle read-only Research-Consumer für WP5. Er projiziert aus dem maximal 24h großen Raw-Buffer nur den vereinbarten LLM-Grundvertrag und erzeugt genau einen zeitlichen Kontext: bei höchstens sechs Stunden verfügbarer History 1-Minuten-Buckets, sonst 5-Minuten-Buckets. Jede Bucket-Metrik enthält die tatsächlich beobachteten Werte innerhalb des Fensters; es gibt kein Zero-Fill und keine Interpolation.

Der Inspector ergänzt diese Serie um einen deterministischen `summary`-Block. Er beschreibt unter anderem Market-Cap-Verlauf und Drawdown, Liquidity einschließlich `liquidity / market_cap`, Holder-Entwicklung, Ownership-Konzentration, rollierende `stats1h`-Aktivität und Organic Evidence. Rollierende `stats1h`-Werte werden nicht über Buckets summiert; Median- und Ratio-Metriken verwenden zeitlich gleichmäßig verteilte Bucket-Werte. `summary` ist Derived Analysis und kein Ersatz für die historische Evidence.

Eine spätere LLM-Integration muss deshalb im System Prompt ausdrücklich verlangen, dass das Modell `temporal_history` selbst prüft und den Summary nur zur Orientierung verwendet. Ein Urteil ausschließlich aus dem Summary ist nicht Teil des Contracts. `llm_context.json` und `report.json` sind weiterhin Research-Evidence und noch kein produktiver Observatory-Endpunkt.

Das Observatory ist als separater read-only FastAPI-/Browser-Prozess unter `src/observatory/` implementiert. Es liest aktuelle Projektionen und SSE-Deltas, verändert aber keine Core-Dateien oder operativen Zustände.

`POST /api/analyst` besitzt zwei explizite read-only Scopes:

- `web` lädt die bekannte Tokenidentität und ruft Mistrals Conversations API mit genau
  einem Built-in Web-Search-Tool auf;
- `current_data` lässt Mistral eine freie Frage in genau einen strukturierten
  `query_tokens`-Aufruf übersetzen.

`src/observatory/tools.py` besitzt den realen internen Tool-Vertrag. `query_tokens`
filtert und sortiert ausschließlich die aktuelle aktive `FrontendReader`-Projektion. Die
zentrale Feldbeschreibung erzeugt Tool-Schema, LLM-Vokabular und den sichtbaren
Capabilities-Hinweis. Die kanonischen Launchpad-Werte werden pro Anfrage aus der aktiven
Population ergänzt. Der Default sind fünf und das harte Maximum zwanzig Ergebnisse. Das
Modell erhält weder SQL noch Datenbankzugriff und darf kein fehlendes Feld durch eine
andere Metrik ersetzen. Tool Calls und Webrecherche bleiben read-only, werden nicht
persistiert und besitzen keine Lifecycle-Authority.

Token Search läuft ausschließlich über die bereits geladene aktuelle
`/api/universe`-Projektion. Mint, Symbol und Name werden im bestehenden Frontend-State
durchsucht. Direkte Suchtreffer und `query_tokens`-Treffer verwenden dieselbe Selection;
diese aktualisiert Inspector und Web-Research-Kontext, ohne operativen State zu ändern.

Der SSE-Vertrag enthält für `token_updated` neben den bestehenden Felddeltas auch die
Änderung von `volume_5m`. `state.js` rekonstruiert daraus die beobachteten Vorher-/Nachher-
Werte und hält ausschließlich die letzten 60 Sekunden im Browser. Pro Mint werden diese
Beobachtungen aggregiert und nach der positiven Zunahme von
`volume_5m / market_cap` gerankt. Das Ergebnis ist eine flüchtige read-only Projektion;
es ist weder persistierte Historie noch eine operative Metrik.

## 7. Generierte Artefakte

Lokale Runtime- oder Research-Artefakte sind Evidence, aber keine zweite Source of Truth für Architektur oder Methodik.

Dauerhafte Regeln und Verträge gehören in Code oder die dafür benannte Dokumentations-Authority.

## 8. Nächste Architekturgrenze

Die aktuelle Foundation ist:

```text
Discovery
   ↓
Monitoring
   ↓
24h Raw Observations
   ↓
Lifecycle v0.1
   ↓
Survivor Population
```

Die aktive nächste Arbeit ist weiterhin WP5. Der History Inspector ist dafür ausschließlich ein empirisches Research-Werkzeug und legt noch keinen produktiven Temporal-Projection- oder LLM-Tool-Vertrag fest. Spatial-Arbeit, persistierte OHLC/Time-Buckets, Prognosen und operative Mutationen bleiben davon getrennt.

Der aktuelle Zielrahmen steht in [`MILESTONES.md`](MILESTONES.md).

## 9. Authority-Modell

| Frage | Authority |
|---|---|
| Was ist das Projekt und wie wird es benutzt? | `README.md` |
| Wie fließen Daten und wer besitzt welche Verantwortung? | `docs/architecture.md` |
| Wie funktioniert der operative Lifecycle fachlich exakt? | `docs/LIFECYCLE_CONTRACT.md` |
| Welche Produktgrenzen gelten für das Observatory? | `docs/FRONTEND_OBSERVATORY.md` |
| Wie funktioniert der aktive V3-Spatial-Vertrag? | `docs/FRONTEND_SPATIAL_MODEL.md` |
| Wo steht das Projekt und was ist als Nächstes aktiv? | `docs/MILESTONES.md` |
| Welche Regeln gelten für Repository-Änderungen? | `AGENTS.md` |

## 10. Architekturprinzipien

1. **Eine Verantwortung, ein Owner.** Keine parallelen Implementierungen derselben Mutation oder Datenverantwortung.
2. **Poll und Snapshot sind verschiedene Ereignisse.** Zeitabhängige Analysen dürfen diese Semantik nicht vermischen.
3. **Source-Versionen gehen nicht durch Writer-Coalescing verloren.** Unterschiedliche beobachtete `updatedAt`-Versionen bleiben erhalten.
4. **Raw-Auflösung ist temporär.** `mint_snapshots` ist auf die letzten 24 Stunden begrenzt.
5. **Missing bleibt missing.** Unbekannte Werte werden nicht zu Null oder künstlich fortgeschrieben.
6. **Lifecycle-Semantik ist versioniert.** Retention ist Storage-Maintenance und keine Lifecycle-Regel.
7. **Downstream ist read-only gegenüber operativem State.** Frontend, Research und spätere Tools lesen; Lifecycle mutiert.
8. **Generierte Daten sind Evidence, nicht Architektur.**
9. **Roadmap ist keine Implementation.** `MILESTONES.md` beschreibt Richtung, nicht bereits vorhandenes Verhalten.
