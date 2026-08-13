# Architecture

## Zweck

`jupiter-data-transform` trennt operative Datensammlung, persistierte Beobachtung, Lifecycle-Entscheidungen und read-only Downstream-Nutzung.

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
R1-R7                   24h Raw Retention
        ↓
tracking_enabled=false
        ↓
READ-ONLY DOWNSTREAM
Observatory / Analyst / Telemetry
```

## 1. Datenbank-Infrastruktur

`src/database.py` besitzt den process-wide PostgreSQL-ConnectionPool. Persistente Schemaänderungen erfolgen ausschließlich explizit in `src/schema.sql`.

## 2. Discovery

`src/discovery.py` entdeckt Mint-Adressen über PumpPortal, Jupiter Recent und Meteora. Discovery liefert Kandidaten-Mints, bewertet keine wirtschaftliche Qualität und trifft keine Lifecycle-Entscheidungen.

Discovery-Provenance als dauerhafte Relation `Source -> konkrete Mint` ist kein aktueller Architekturvertrag.

## 3. Jupiter Monitoring

`src/refresh.py` überwacht aktive Mints über parallele Jupiter-Search-Lanes. Netzwerk-I/O und PostgreSQL-Writes sind getrennt; erfolgreiche Antworten werden über die `WriteQueue` an `MintRepository` übergeben.

Identische `(mint, updatedAt)`-Antworten dürfen innerhalb eines Buffers zusammengefasst werden. Unterschiedliche tatsächlich beobachtete Source-Versionen eines Mints dürfen nicht verloren gehen.

## 4. Persistenz

`src/repository.py` besitzt Collector-Persistenz und ausdrücklich erlaubte operative Mint-Mutationen.

### `mints`

Die Registry hält langlebige Mint-Fakten sowie Collector-/Lifecycle-Zustand:

- `first_observed_at`;
- `last_polled_at`;
- `last_changed_at`;
- `source_updated_at`;
- `tracking_enabled`;
- `disabled_at`;
- `disabled_reason`.

### `mint_snapshots`

`mint_snapshots` hält die immutable Raw-Historie tatsächlich beobachteter Jupiter-Source-Versionen innerhalb des 24h-Working-Buffers.

```text
Search erfolgreich
        │
        ├─ updatedAt bereits bekannt
        │      -> last_polled_at fortschreiben
        │      -> kein redundanter Snapshot
        │
        └─ neue updatedAt-Version
               -> Snapshot persistieren
               -> source_updated_at / last_changed_at / last_polled_at fortschreiben
```

Poll und Snapshot sind verschiedene Ereignisse. `src/maintenance.py` besitzt ausschließlich die gebatchte 24h-Retention und keine Lifecycle-Semantik.

## 5. Operational Lifecycle

Der Lifecycle ist der definierte Mutationspfad für `tracking_enabled=false`.

```text
LifecycleQueries
      ↓ evidence
Lifecycle Rules
      ↓ reason
lifecycle_clean.py
      ↓ ordering / dry-run / apply
MintRepository.disable_mints()
```

Die fachliche Semantik von Rule 1–7 steht ausschließlich in [`LIFECYCLE_CONTRACT.md`](LIFECYCLE_CONTRACT.md).

`tools/verify_lifecycle_contract_v01.py` schützt die unveränderte Semantik von Rule 1–5. Rule 6 und Rule 7 besitzen gezielte Unit-Tests.

## 6. Read-only Downstream Boundary

Observatory, Analyst und Telemetry dürfen operative Daten lesen und eigene Projektionen bzw. Interpretationen erzeugen. Sie dürfen weder Tracking noch Priority, Lifecycle-State, Thresholds oder Collector-owned Observation State verändern.

External Evidence und LLM-Interpretation werden nicht zu operativer Truth hochgestuft.

## 7. Observatory

Das Observatory läuft separat unter `src/observatory/` und konsumiert den operativen Zustand read-only.

```text
PostgreSQL
    ↓
FrontendReader
    ↓
Browser Population State + selected Mint
    ├── Search / Inspector
    ├── Token Universe
    ├── Analyst
    └── Runtime Telemetry -> Operational Flow
```

Der Browser besitzt genau eine kanonische aktive Population. `/api/events` liefert beim Connect/Reconnect einen `universe_snapshot` und danach `universe_delta`-Events (`token_added`, `token_updated`, `token_retired`).

Telemetry ist ein separater flüchtiger Beobachtungspfad über localhost UDP und einen begrenzten RAM-Buffer; keine DB-/Disk-Persistenz, kein Broker und keine Mutation.

Der Analyst besitzt die read-only Scopes `current_data`, `web`, `temporal` und `rugcheck`. Detailverträge, Truth Layers und Browser-Verantwortungen stehen ausschließlich in [`FRONTEND_OBSERVATORY.md`](FRONTEND_OBSERVATORY.md).

## Authority-Modell

| Frage | Authority |
|---|---|
| Was ist das Projekt und wie wird es benutzt? | `README.md` |
| Wie fließen Daten und wer besitzt welche Verantwortung? | `docs/architecture.md` |
| Welche Lifecycle-Regeln gelten exakt? | `docs/LIFECYCLE_CONTRACT.md` |
| Welche Observatory-/Analyst-/Telemetry-Grenzen gelten? | `docs/FRONTEND_OBSERVATORY.md` |
| Welche Regeln gelten für Änderungen? | `AGENTS.md` |

Offene Arbeit wird in GitHub Issues geführt; Änderungshistorie in Git.
