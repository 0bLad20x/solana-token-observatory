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

## Visual Phase — aktiv

Für die Visual-Phase gibt es keinen offenen Core-, Backend- oder Datenvertrags-Blocker. Der Produktmodus ist ein One-Screen `Read + Inspect + Ask` Workspace:

```text
ansehen -> suchen -> selektieren -> fragen -> analysieren
```

Search und Analyst sind die wesentlichen aktiven Interaktionen. Bubble Map und Operational Flow sind primär visuelle Informationsflächen; Click/Selection öffnet Detailkontext.

Der Reihenfolge-/Entscheidungsanker ist Issue #36.

### Visual WP1 — Shell / Typography / Inspector (#33 / PR #37) — abgeschlossen

Der erste Visual-Slice wurde lokal im realen Browser akzeptiert. Bewiesen ist jetzt eine belastbare One-Screen-Shell, ohne Domain-, Population-, Selection-, SSE-, Analyst- oder Evidence-Semantik zu verändern.

Akzeptierter Stand:

- bestehende dunkle Solana-/Crypto-Farbwelt und System-Font-Stack bleiben erhalten;
- Typografie und visuelle Hierarchie von Topbar, Search, Inspector, Analyst, Live Deltas und Telemetry sind angehoben;
- Main Stage bleibt die dominante Visualisierungsfläche;
- Right Context startet breiter und ist auf Desktop zwischen 360px und 640px resizebar;
- Right Context kann ein-/ausgeblendet werden, ohne Selection oder Analyst-State zu verlieren;
- Search bleibt vollständiger aktiver Population-Zugriff;
- Inspector zeigt die bestehenden Token-Fakten in größerer, klarerer Hierarchie;
- vollständige Mint-Adresse ist sichtbar und kopierbar;
- ein redundanter `ACTIVE`-Badge wird bei normalen aktiven Selected Tokens nicht mehr benötigt; `RETIRED` bleibt für erhaltenen Retired-Context sichtbar;
- der aktuelle Token-Kachel-Proof und die Telemetry-Karten bleiben bewusst Platzhalter für WP3/WP4.

WP1 legt weder Bubble-Größen-/Cluster-Semantik noch Operational-Flow-Geometrie fest.

### Visual WP2 — Analyst Focus Workspace (#34) — nächster Slice

Als nächstes wird der Analyst als wichtigste aktive Interaktion aufgewertet:

- klarer Focus-State innerhalb derselben Seite;
- deutlich größere Lesefläche für Antworten;
- LLM-Text, Tool-/Evidence-Metadaten und Quellen visuell getrennt;
- lange Antworten zerstören nicht mehr die Sidebar-Geometrie;
- keine neue Analyst-/Evidence-Semantik.

Die konkrete Focus-Mechanik wird im Browser-Prototyp entschieden. WP1 liefert dafür bereits die resize-/collapse-fähige Right-Context-Geometrie.

### Visual WP3 — Launchpad Token Universe Bubble Map (#9)

Die konkrete V1-Frage ist definiert:

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

## Offene Designentscheidungen — keine Core-Blocker

Folgende Fragen werden bewusst erst im zuständigen Browser-Prototyp entschieden:

- Analyst Focus als Expand/Overlay/anderer minimaler Focus-State -> #34;
- konkrete Main-Stage-Umschaltung zwischen Token Universe und Operational Flow -> bei Integration der ersten echten Main-Stage-View;
- Bubble-Größenfunktion, Missing- und Outlier-Scale -> #9;
- genaue Flow-Geometrie zwischen Layer- und Fan-in/Fan-out-Muster -> #35.

Keine dieser Fragen rechtfertigt eine weitere Core-/Backend-Phase.

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

WP1 ist abgeschlossen, weil:

- die neue Shell im realen Browser lokal akzeptiert wurde;
- Typografie, Search, Inspector und Right Context sichtbar verbessert sind;
- Resize/Collapse funktionieren;
- vollständige Mint-Adresse sichtbar und kopierbar ist;
- Search, Selection, Analyst, Live Deltas und Telemetry funktional unverändert bleiben;
- keine neue Domain-, Mutation-, Evidence- oder Presentation-Authority in den Functional Core eingeführt wurde.

Der nächste offene Visual-Slice ist WP2 / Issue #34.
