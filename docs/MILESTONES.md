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
| First-Principles Simplification / Issue #31 / PR #32 | redundante Browser-Reads/State-Duplikation entfernt; Visual-Freiheit erhalten |

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

## Visual Phase — jetzt offen

Für den Start der Visual-Phase gibt es keinen offenen Core-, Backend- oder Datenvertrags-Blocker. Der aktuelle Produktmodus ist ein One-Screen `Read + Inspect + Ask` Workspace:

```text
ansehen -> suchen -> selektieren -> fragen -> analysieren
```

Search und Analyst sind die wesentlichen aktiven Interaktionen. Bubble Map und Operational Flow sind primär visuelle Informationsflächen; Click/Selection öffnet Detailkontext.

Der Reihenfolge-/Entscheidungsanker ist Issue #36.

### Visual WP1 — Shell / Typography / Inspector (#33)

Zuerst wird die visuelle Grundfläche stabilisiert:

- größere und klar hierarchisierte Typografie;
- Main Stage als dominante Visualisierungsfläche;
- Search klarer sichtbar;
- Right Context breiter sowie resize-/collapse-fähig;
- vollständige Mint-Adresse sichtbar und kopierbar;
- bestehende Selected-Token-Fakten bleiben erhalten;
- keine Bubble- oder Flow-Semantik in diesem Slice.

### Visual WP2 — Analyst Focus Workspace (#34)

Danach wird der Analyst als wichtigste aktive Interaktion aufgewertet:

- klarer Focus-State innerhalb derselben Seite;
- deutlich größere Lesefläche für Antworten;
- LLM-Text, Tool-/Evidence-Metadaten und Quellen visuell getrennt;
- lange Antworten zerstören nicht mehr die Sidebar-Geometrie;
- keine neue Analyst-/Evidence-Semantik.

### Visual WP3 — Launchpad Token Universe Bubble Map (#9)

Issue #9 ist nicht mehr deferred. Die konkrete V1-Frage ist jetzt definiert:

> Wie verteilt sich die aktive Token-Population auf Launchpads, und welche Tokens sind relativ groß, liquide und holder-stark?

V1 verwendet:

- Launchpad-Hubs + Token-Nodes;
- ein-/ausblendbare Launchpad-Cluster;
- Zoom/Pan;
- kompakte Bubble-Labels;
- Click -> bestehender Inspector/Analyst Context;
- Holder Count als zusätzliche visuelle Dimension der Membership-Verbindung;
- semantische Add/Update/Retire-Motion.

Die Bubble-Größenfunktion wird innerhalb des WP mit realer Population entschieden. Market Cap, Liquidity und ein explizit dokumentierter normalisierter Composite-Kandidat werden verglichen; keine willkürliche Formel wird vorab zum Vertrag.

### Visual WP4 — Live Operational Flow (#35)

Die heutige Telemetry-Karten-/Tabellenwahrnehmung wird durch eine Systemvisualisierung ersetzt:

```text
Discovery -> Search -> WriteQueue -> Lifecycle -> Tracking -> Search
                                      └-> retired exit
```

Als Designmuster dienen layered neural/data networks sowie fan-in/fan-out flows. Die Visualisierung verwendet ausschließlich bestehende Telemetrie-Fakten; keine per-Mint Discovery-Provenance und keine neue Runtime-Semantik werden erfunden.

## Referenzmuster

Aus der Design-Diskussion sind drei Muster als Inspiration festgehalten:

1. Hub-and-spoke / radial network für Launchpad -> Tokens;
2. layered neural/data network für parallele Verarbeitungslanes;
3. fan-in / fan-out stream für Bündelung, Verteilung und Kondensation.

Die verwendeten Stock-/Referenzbilder sind keine Produktassets und kein 1:1-Ziel. Entscheidend sind die zugrunde liegenden Muster und ihre überprüfbare Data-to-Visual-Semantik.

## Offene Designentscheidungen — keine Vorab-Blocker

Folgende Fragen werden bewusst erst im zuständigen Browser-Prototyp entschieden:

- Main-Stage-Wechselmechanik zwischen Universe und Flow -> #33;
- Analyst Focus als Expand/Overlay/anderer minimaler Focus-State -> #34;
- Bubble-Größenfunktion, Missing- und Outlier-Scale -> #9;
- genaue Flow-Geometrie zwischen Layer- und Fan-in/Fan-out-Muster -> #35.

Keine dieser Fragen rechtfertigt eine weitere Core-/Backend-Phase vor Beginn der Visual-Arbeit.

## Mögliche spätere Evidence-Erweiterungen

Nur aus einer konkreten Benutzerfrage ableiten, ob weitere Verträge nötig werden.

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

## Separater Repository-Cleanup

Große Dateien unter `analysis/` sind historische Research-Evidence und werden **nicht** in diesem Dokumentations-Checkpoint automatisch gelöscht. Ob einzelne Artefakte reproduzierbar, noch fachlich nützlich oder entbehrlich sind, ist ein separater Cleanup mit eigener Prüfung.

## Stop Condition dieses Checkpoints

Der Repository-Zustand ist für die Visual-Phase bereit, weil:

- Functional Core und First-Principles Simplification auf `main` abgeschlossen sind;
- Lifecycle v0.3 und Live Telemetry semantisch zusammenpassen;
- `ACTIVE` versus `TRACKING` dokumentiert und im UI klar benannt ist;
- Lifecycle-Telemetrie R1–R7 vollständig zeigt;
- Search/Selection/Analyst als stabile Interaktionsgrenzen bewiesen sind;
- die vier Visual Work Packages eine klare Reihenfolge und eigene Acceptance-Gates besitzen;
- offene Designentscheidungen nicht mehr mit fehlenden Core-Daten verwechselt werden.
