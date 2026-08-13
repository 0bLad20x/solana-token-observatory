# Milestones

## Zweck

Dieses Dokument nennt den aktuellen Projektstand und die nächste offene Entwicklungsentscheidung. Detailverträge bleiben in Code, `docs/architecture.md`, `docs/LIFECYCLE_CONTRACT.md` und `docs/FRONTEND_OBSERVATORY.md`.

## Operative Foundation — abgeschlossen

Die operative Basis steht:

- Discovery aus mehreren Solana-Quellen;
- Jupiter Search Monitoring mit parallelen Lanes;
- PostgreSQL-Registry und immutable `mint_snapshots`;
- 24h Raw-Buffer-Retention für `mint_snapshots`;
- Operational Lifecycle v0.3 mit Rule 1–7;
- read-only Downstream-Grenze.

Lifecycle v0.2 ergänzte Rule 6 `Early Holder Failure`; Lifecycle v0.3 ergänzte Rule 7 `Persistent Source Inactivity`. Retention bleibt Storage-Maintenance und ist keine Lifecycle-Evidence.

## Observatory Functional Foundation — abgeschlossen

Bewiesen und eingefroren sind:

- read-only Observatory mit kanonischer aktiver Population;
- `/api/events` mit `universe_snapshot` als Connect-/Reconnect-Baseline und anschließenden add/update/retire-Deltas;
- gemeinsame Selection über Search, View, Inspector und Analyst;
- Current Data, Web Research, Temporal Summary und RugCheck als vier read-only Analyst-Use-Cases;
- FAST/STRONG Model Policy;
- flüchtige Live Operational Telemetry über localhost UDP, 10m RAM-Buffer und separaten Telemetry-SSE;
- First-Principles Browser-Schnitt ohne parallele Population-State-Owner.

Der Functional Core bleibt eingefroren. Presentation darf ihn konsumieren, aber keine neue Domain- oder Mutation-Authority erzeugen.

## Observatory Visual Phase — abgeschlossen

Issue #36 definierte die Reihenfolge und Designprinzipien. Die vier Visual-Slices wurden nacheinander mit realen Browserdaten akzeptiert.

### WP1 — Visual Shell / Typography / Inspector (#33 / PR #37)

Akzeptiert:

- dominante One-Screen Main Stage;
- größere lesbare Typografie;
- Right Context auf Desktop resizebar und ein-/ausblendbar;
- vollständige Mint-Adresse mit Copy;
- Selection und Analyst-State bleiben bei Shell-Interaktionen erhalten.

### WP2 — Analyst Focus Workspace (#34 / PR #38)

Akzeptiert:

- Analyst bleibt idle im Right Context und kann als großer Focus-Workspace über der Main Stage geöffnet werden;
- Submit öffnet Focus automatisch; Close/Escape erhält denselben Zustand;
- Frage, Antwort und Evidence/Sources sind visuell getrennt;
- lange Antworten scrollen im Research-Bereich;
- sicherer Markdown-Subset-Renderer für Headings, Inline-Formatierung, Listen, Trennlinien und Tabellen;
- keine Conversation-History und keine neue Analyst-/Evidence-Semantik.

### WP3 — Launchpad Token Universe (#9 / PR #39)

Akzeptiert:

- Launchpad-zentrierte Bubble Map statt Token-Kachel-Proof;
- Launchpads einzeln ein-/ausblendbar;
- Zoom/Pan und bestehende Selection/Inspector/Analyst-Integration;
- Bubble-Größe = Market Cap;
- Liquidity = separater Halo;
- Holder Count beeinflusst die Membership-Verbindung nur im Fokus;
- stabile adaptive Cluster statt permanenter Force-Physics;
- semantische Add/Market-Cap-Update/Retire-Motion;
- User-Filter bleibt Authority über Launchpad-Sichtbarkeit.

### WP4 — Live Operational Flow (#35 / PR #40)

Akzeptiert:

```text
Discovery -> Admission -> Search -> Write -> Lifecycle -> Tracking
                                              └-> retired
                         ^                         |
                         └──── monitoring loop ────┘
```

Die Main Stage visualisiert ausschließlich bereits vorhandene Runtime-Fakten:

- Discovery als `raw intake -> dedupe -> new`;
- reale Discovery-Ticks als bounded mengenabhängige Bursts;
- Jupiter Search als stabiles paralleles Lane-Feld mit realen Work-Paketen;
- WriteQueue als große sichtbare Kondensation `polls -> source versions -> snapshots`;
- Lifecycle R1–R7 als Gates mit regelgebundenem Retirement-/Candidate-Sink;
- Tracking als Survivor-Reservoir;
- die große sichtbare Tracking-Zahl folgt derselben kanonischen Browser-Population wie Topbar `ACTIVE`; `lifecycle.active_remaining` bleibt als Stand des letzten Lifecycle-Cycles im Detail verfügbar;
- der Tracking->Search-Rücklauf ist ein rate-codierter Monitoring-Current aus realem Search-RPM und beobachteter Latenz;
- Count-Marks und Work-Pakete sind Mengen-/Arbeitskodierungen und niemals behauptete Mint-Identitäten.

Keine neue Backend-Telemetrie, Persistenz, Mint-Provenance oder operative Authority wurde für die Visualisierung eingeführt.

## Aktueller Produktcheckpoint

Das Observatory besitzt jetzt zwei akzeptierte Main-Stage-Ansichten:

```text
UNIVERSE  -> aktive Token-Population als Launchpad Bubble Map
FLOW      -> laufende operative Datenverarbeitung als Live Operational Flow
```

Dazu kommen:

- Search;
- Selected Token Inspector;
- Analyst im Right Context + Focus Workspace;
- Live Deltas;
- Topbar Runtime-Kontext.

**Es gibt derzeit kein weiteres beschlossenes Frontend-Design-Arbeitspaket.** WP1–WP4 erfüllen den definierten Visual-Checkpoint. Weitere UI-Arbeit sollte nur aus einer neuen konkreten Benutzerfrage oder einem beobachteten Usability-/Performance-Problem entstehen, nicht aus vorsorglichem Redesign.

## Mögliche spätere Produkt-/Evidence-Erweiterungen — nicht Teil des abgeschlossenen Visual-Checkpoints

### Discovery Provenance

Nur falls eine zukünftige Frage eine beweisbare Relation benötigt wie:

```text
Discovery Source -> Mint -> Jupiter Observation
```

muss dafür eine echte read-only Evidence-Grenze geschaffen werden. Die heutige Telemetrie darf diese Relation nicht erfinden.

### Bounded Multi-Mint Comparison / zusätzliche Evidence

Nur aus einer konkreten Benutzerfrage ableiten, ob mehrere Mints gemeinsam verglichen oder weitere deterministische Summaries bzw. externe Evidence benötigt werden.

### Unified AI Question Router

Die vier bewiesenen Analyst-Pfade könnten später hinter einem gemeinsamen Frageeingang liegen. Routing ist heute bewusst nicht Teil des Produktvertrags.

### Repository-Cleanup

Historische Research-Artefakte unter `analysis/` bleiben ein separater Cleanup und sind kein Frontend-Design-Thema.

## Stop Condition dieses Checkpoints

Der Observatory Visual Checkpoint ist abgeschlossen, weil:

- Functional Core und Datenverträge unverändert tragfähig geblieben sind;
- Shell, Analyst, Token Universe und Operational Flow lokal mit realen Daten akzeptiert wurden;
- die Visualisierungen klare Data-to-Visual-Semantik besitzen;
- Motion reale Zustandsänderungen oder beobachtete Arbeit ausdrückt;
- Universe und Flow dieselbe Selection-/Shell-/Analyst-Foundation verwenden;
- keine zweite Population, keine neue Mutation-Authority und keine erfundene Mint-Provenance entstanden ist.

Die nächste Entwicklungsentscheidung ist daher **nicht automatisch ein weiteres Frontend-WP**, sondern muss aus dem nächsten konkreten Produkt- oder Datenproblem abgeleitet werden.
