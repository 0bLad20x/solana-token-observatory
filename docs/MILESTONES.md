# Milestones

## Zweck

Dieses Dokument nennt den aktuellen Projektstand und die nächste offene Entwicklungsentscheidung. Detailverträge bleiben in Code, `docs/architecture.md`, `docs/LIFECYCLE_CONTRACT.md` und `docs/FRONTEND_OBSERVATORY.md`.

## Operative Foundation — abgeschlossen

Die operative Basis steht:

- Discovery aus mehreren Solana-Quellen;
- Jupiter Search Monitoring;
- PostgreSQL-Registry und immutable `mint_snapshots`;
- 24h Raw-Buffer-Retention für `mint_snapshots`;
- Operational Lifecycle v0.2;
- read-only Downstream-Grenze.

Lifecycle v0.2 übernimmt Rule 1–5 unverändert aus v0.1 und ergänzt Rule 6 `Early Holder Failure`: T0 ist `first_observed_at`, der Decision-Checkpoint liegt bei T+30 und `holderCount < 5` führt bei vorhandener Checkpoint-Evidence zur Deaktivierung. Der erste reale Apply auf der bestehenden Population deaktivierte 2.313 Mints, davon 2.125 über Rule 6, und reduzierte die aktive Population in diesem Lauf von 4.602 auf 2.348.

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

## Aktueller Checkpoint — Functional Core frozen

Der Observatory Functional Core wird jetzt als abgeschlossen betrachtet.

```text
Operational Core
      ↓
read-only backend
      ↓
Browser IO
      ↓
Population State + selected Mint
      ├── Search
      ├── Activity
      ├── Inspector
      ├── Analyst
      └── disposable Current View
```

Die Population synchronisiert sich über:

```text
initial / reconnect universe_snapshot
              ↓
subsequent universe_delta events
```

`GET /api/token/{mint}` bleibt ein Selected-Detail-Read und schreibt nicht als zweiter Pfad in die Population.

Der Functional Core enthält Domain-Fakten, Selection und Live-Event-Anwendung, aber keine Presentation Truth wie `x/y`, Radius, Farbe, Alpha, Clusterpositionen, Pixi/D3-State oder einen universellen ViewSpec.

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

## Jetzt offen — Evidence Readiness Review vor Design

Es gibt **noch keinen automatisch ausgewählten nächsten Feature-Slice**. Vor neuem Visual-/Spatial-Design wird entschieden, ob eine konkrete zukünftige Benutzerfrage noch eine fehlende Evidence- oder Relation-Grenze benötigt.

Kandidaten:

### 1. Discovery Provenance

Nur falls zukünftige Nutzung eine beweisbare Relation benötigt wie:

```text
Discovery Source
      ↓
Mint
      ↓
Jupiter Observation
```

muss geprüft werden, ob und wie diese Provenance persistiert oder als read-only Relation bereitgestellt wird.

Nicht vorab implementieren, nur weil eine spätere Flow-/Tunnel-Darstellung denkbar ist.

### 2. Bounded Multi-Mint Comparison / zusätzliche Evidence

Nur aus einer konkreten Benutzerfrage ableiten, ob mehrere Mints gemeinsam verglichen oder weitere deterministische Summaries/Source-Metadaten benötigt werden.

### 3. Unified AI Question Router

Die vier bewiesenen Analyst-Pfade könnten später hinter einem gemeinsamen Frageeingang liegen. Noch offen ist, ob Routing deterministisch, LLM-basiert, hybrid oder parallel erfolgt.

Kein generisches Agent-/Tool-Framework vorsorglich bauen.

## Danach — Issue #9 Visual / Spatial Research

Issue #9 bleibt der separate Design-/Research-Schritt.

Visual Design beginnt erst mit einer konkreten analytischen Frage und einem expliziten Mapping:

- welche Frage beantwortet die View;
- welche Datenfelder werden auf Position, Größe, Farbe, Opacity oder Text gemappt;
- Missing/Outlier-/Scale-Regeln;
- Density, Zoom und Aggregation;
- reale Populationen und Browser-Prototypen.

Keine frühere Bubble-, Farb-, Cluster- oder Panel-Semantik ist ein zukünftiger Designvertrag.

## Separater Repository-Cleanup

Große Dateien unter `analysis/` sind historische Research-Evidence und werden **nicht** in diesem Dokumentations-Checkpoint automatisch gelöscht. Ob einzelne Artefakte reproduzierbar, noch fachlich nützlich oder entbehrlich sind, ist ein separater Cleanup mit eigener Prüfung.

## Stop Condition dieses Checkpoints

Der Repository-Zustand ist für neue Arbeit bereit, wenn:

- die dauerhaften Authorities den aktuellen `main` widerspiegeln;
- abgeschlossene Issues nicht mehr als offene Roadmap erscheinen;
- kein Dokument einen bereits verworfenen Research-Pfad als Produktvertrag beschreibt;
- das nächste Feature erst nach einer expliziten Evidence-/Produktentscheidung begonnen wird.
