# Milestones

## Zweck

Dieses Dokument nennt den aktuellen Projektstand und die nächste offene Entwicklungsentscheidung. Detailverträge bleiben in Code, `docs/architecture.md`, `docs/LIFECYCLE_CONTRACT.md` und `docs/FRONTEND_OBSERVATORY.md`.

## Operative Foundation — abgeschlossen

Die operative Basis steht:

- Discovery aus mehreren Solana-Quellen;
- Jupiter Search Monitoring;
- PostgreSQL-Registry und immutable `mint_snapshots`;
- 24h Raw-Buffer-Retention für `mint_snapshots`;
- Operational Lifecycle v0.3;
- read-only Downstream-Grenze.

Lifecycle v0.2 ergänzte Rule 6 `Early Holder Failure`: T0 ist `first_observed_at`, der Decision-Checkpoint liegt bei T+30 und `holderCount < 5` führt bei vorhandener Checkpoint-Evidence zur Deaktivierung. Der erste reale Apply auf der bestehenden Population deaktivierte 2.313 Mints, davon 2.125 über Rule 6, und reduzierte die aktive Population in diesem Lauf von 4.602 auf 2.348.

Lifecycle v0.3 ergänzt Rule 7 `Persistent Source Inactivity`: ein bereits beobachteter Mint wird deaktiviert, wenn er weiterhin frisch erfolgreich gepollt wird, `last_changed_at` aber seit mindestens 24 Stunden unverändert ist. Diese Regel verwendet ausschließlich langlebige Collector-Timestamps aus `mints`; sie benötigt keinen Raw-Snapshot und vermischt die 24h-Retention nicht mit Lifecycle-Evidence.

Die Entscheidung wurde aus dem aktiven, frisch gepollten Bestand abgeleitet: 629 Mints lagen bei 24–48 Stunden ohne neue Jupiter-Source-Version und weitere 30 bei mehr als 48 Stunden. Rule 7 adressiert damit genau die persistente Monitoring-Inactivity, die zuvor als aktive Population ohne verbleibenden Raw-Snapshot sichtbar wurde.

## Observatory Functional Foundation — abgeschlossen

Die vertikalen Slices haben die funktionale Basis bewiesen:

| Slice | Ergebnis |
|---|---|
| V0–V2 | read-only Observatory, aktuelle Population, SSE add/update/retire |
| WP1 / PR #10 | exact-Mint Web Research mit externer Evidenz |
| WP2 / PR #11 | bounded `query_tokens` für aktuelle Population |
| WP3 / PR #12 | Mint/Symbol/Name Search + gemeinsame Selection |
| WP4 / PR #13 | kompakte 60s Volume-Activity-Projektion |
| Temporal Research / PR #16 | Deep-History-Proof; als Produktpfad verworfen |
| WP5 / PR #19 | kompakter Temporal Summary + genau ein Mistral-Request |
| Functional Core / Issue #20 / PR #21 | Browser-Verantwortungen getrennt, disposable View, gemeinsame Selection |
| Model Routing + RugCheck / Issue #22 / PR #23 | FAST/STRONG Policy + exact-Mint RugCheck Evidence + v4 Projection |
| Final Core Sync / PR #24 | verlustfreie Connect/Reconnect-Synchronisationsgrenze + ein Population-Updatepfad |
| Live Operational Telemetry / Issue #26 / PR #27 | Discovery, Search lanes, WriteQueue und Lifecycle als flüchtiger realer Runtime-Flow |

## Live Operational Telemetry — abgeschlossen

Der Telemetrie-Slice beobachtet den real laufenden operativen Pfad ohne neue Persistenz- oder Mutation-Authority:

```text
Discovery / Search / WriteQueue / Lifecycle
                ↓
       localhost UDP best effort
                ↓
      Observatory 10m RAM buffer
                ↓
      telemetry snapshot + SSE
                ↓
       deterministic <=1 Hz UI
```

Bewiesen und sichtbar sind:

- Discovery intake pro realem Pfad;
- Jupiter Search lanes mit RPM, latency, requested/received und Status;
- WriteQueue `polls -> source versions -> snapshots` plus Queue-/Write-Metriken;
- Lifecycle v0.3 mit R1–R7, affected count, duration und `TRACKING`;
- flüchtige 10-Minuten-History ohne DB-/Disk-Persistenz;
- eigener Telemetry-SSE, getrennt vom kanonischen Token-Stream.

Die Topbar-Zahl `ACTIVE` und Lifecycle `TRACKING` beantworten unterschiedliche Fragen. `ACTIVE` ist die aktuelle Observatory-Read-Model-Population; `TRACKING` ist `tracking_enabled=true` im operativen Lifecycle. Nach Rule 7 liegen beide im stabilen Betrieb eng zusammen, müssen aber aufgrund unabhängiger Read-Zeitpunkte und unterschiedlicher Projektionsgrenzen nicht exakt identisch sein.

## Analyst Evidence — aktueller Stand

Vier read-only Use Cases sind produktiv bewiesen:

```text
Current Data -> FAST   -> bounded query_tokens
Web          -> STRONG -> external web evidence
Temporal     -> STRONG -> deterministic <=24h summary
RugCheck     -> STRONG -> exact-mint external safety evidence
```

Aktuelle Model-Defaults:

```text
FAST   = ministral-14b-latest
STRONG = mistral-large-latest
```

RugCheck ist damit kein offener Readiness-Punkt mehr. Der ältere Issue #18 ist durch Issue #22 / PR #23 erfüllt.

## Nächster Slice — Operational Flow Visualization

Der nächste sinnvolle Schritt ist nicht mehr das Sammeln weiterer Runtime-Metriken, sondern die strukturelle Visualisierung des jetzt bewiesenen Datenflusses.

Die Ausgangsfrage lautet:

> Wie werden große Discovery-Massen durch Search, WriteQueue und Lifecycle zu einer kleinen weiter überwachten Survivor-Population reduziert?

Der erste Visual-Slice darf ausschließlich bereits bewiesene Telemetrie-Fakten verwenden:

```text
Discovery intake
      ↓
Search lanes
      ↓
WriteQueue
      ↓
Lifecycle R1-R7
      ↓
Tracking survivors ↺ Search
```

First-Principles-Grenzen:

- zuerst Data-to-Visual-Semantik, dann Gestaltung;
- Mengen, Durchsatz, Reduktion und Loop müssen verständlich sein;
- keine neue Discovery-Provenance erfinden;
- keine Mint-Identitäten aus Telemetrie ableiten;
- keine Bubble Physics als Ausgangspunkt;
- Motion nur, wenn sie reale Richtung, Durchsatz oder Zustandswechsel transportiert;
- Telemetry bleibt read-only und flüchtig.

Dieser Operational-Flow-Slice ist von Issue #9 Token Visual / Spatial Research getrennt. Er visualisiert das System selbst, nicht die räumliche Beziehung einzelner Tokens.

## Danach — Evidence / Token Visual Research

Nach dem Operational-Flow-Slice wird anhand einer konkreten Benutzerfrage entschieden, ob noch eine Evidence-/Relation-Grenze fehlt oder Issue #9 Visual / Spatial Research der nächste Schritt ist.

Mögliche spätere Kandidaten bleiben:

### Discovery Provenance

Nur falls zukünftige Nutzung eine beweisbare Relation benötigt wie:

```text
Discovery Source
      ↓
Mint
      ↓
Jupiter Observation
```

muss geprüft werden, ob und wie diese Provenance persistiert oder als read-only Relation bereitgestellt wird.

### Bounded Multi-Mint Comparison / zusätzliche Evidence

Nur aus einer konkreten Benutzerfrage ableiten, ob mehrere Mints gemeinsam verglichen oder weitere deterministische Summaries/Source-Metadaten benötigt werden.

### Unified AI Question Router

Die vier bewiesenen Analyst-Pfade könnten später hinter einem gemeinsamen Frageeingang liegen. Noch offen ist, ob Routing deterministisch, LLM-basiert, hybrid oder parallel erfolgt.

Kein generisches Agent-/Tool-Framework vorsorglich bauen.

## Issue #9 Visual / Spatial Research

Issue #9 bleibt der separate Design-/Research-Schritt für Token-Darstellungen.

Visual Design beginnt dort erst mit einer konkreten analytischen Frage und einem expliziten Mapping:

- welche Frage beantwortet die View;
- welche Datenfelder werden auf Position, Größe, Farbe, Opacity oder Text gemappt;
- Missing/Outlier-/Scale-Regeln;
- Density, Zoom und Aggregation;
- reale Populationen und Browser-Prototypen.

Keine frühere Bubble-, Farb-, Cluster- oder Panel-Semantik ist ein zukünftiger Designvertrag.

## Separater Repository-Cleanup

Große Dateien unter `analysis/` sind historische Research-Evidence und werden **nicht** in diesem Dokumentations-Checkpoint automatisch gelöscht. Ob einzelne Artefakte reproduzierbar, noch fachlich nützlich oder entbehrlich sind, ist ein separater Cleanup mit eigener Prüfung.

## Stop Condition dieses Checkpoints

Der Repository-Zustand ist für den nächsten Slice bereit, wenn:

- die dauerhaften Authorities den aktuellen `main` widerspiegeln;
- Lifecycle v0.3 und Live Telemetry semantisch zusammenpassen;
- `ACTIVE` versus `TRACKING` dokumentiert und im UI klar benannt ist;
- Lifecycle-Telemetrie R1–R7 vollständig zeigt;
- abgeschlossene Issues nicht mehr als offene Roadmap erscheinen;
- kein Dokument einen bereits verworfenen Research-Pfad als Produktvertrag beschreibt.
