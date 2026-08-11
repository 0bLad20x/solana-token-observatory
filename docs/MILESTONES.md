# Milestones

## Zweck

Dieses Dokument beschreibt knapp den aktuellen Projektstand und die nächste Entwicklungsrichtung. Es ist keine Authority für bereits implementierte Architektur oder konkrete Thresholds.

Aktive Authorities:

- `README.md` für den aktuellen Projektüberblick;
- `docs/architecture.md` für die Core-Architektur;
- `docs/LIFECYCLE_CONTRACT.md` für Lifecycle v0.1;
- `docs/FRONTEND_OBSERVATORY.md` für Produkt-, Design- und Interaktionsprinzipien des Observatory;
- `docs/FRONTEND_SPATIAL_MODEL.md` für den aktiven V3-Vertrag zu Bubble-Physik und ViewSpec.

## Operational Foundation — abgeschlossen

Die operative Basis steht:

- Discovery aus mehreren Solana-Quellen;
- Jupiter Search Monitoring mit mehreren API-Key-Lanes;
- version-safe Writer-Pfad ohne Verlust unterschiedlicher beobachteter `updatedAt`-Versionen;
- PostgreSQL-Registry in `mints` und immutable Source-Versionen in `mint_snapshots`;
- Operational Lifecycle Rule 1–5;
- eingefrorener Lifecycle Contract v0.1;
- ausführbarer Equivalence Gate gegen die v0.1-Referenz;
- Trennung des operativen Core von Research-Tooling.

Diese Foundation wird nicht vorsorglich weiter refaktoriert. Änderungen benötigen ein konkretes Problem oder eine neue fachliche Grenze.

## Frontend Observatory

Das Frontend wird in kurzen vertikalen Slices entwickelt. Jeder Slice muss in einem real laufenden Browser/API-Pfad einen sichtbaren Erfolg liefern.

Aktueller Stand:

```text
V0  Observatory Contract                         DONE
 ↓
V1  Structural split + design system             DONE / MERGED
 ↓
V2  Stable Live Deltas                           DONE / MERGED
 ↓
V3  Generic Bubble Physics + ViewSpec             ACTIVE
 ↓
V4  Thin LLM analyst slice                        LATER
```

### V1 — abgeschlossen

V1 wurde mit dem real laufenden Frontend validiert:

- unabhängiger Serverstart;
- statische ES-Module;
- `/api/health`;
- `/api/universe`;
- SSE-Pfad;
- Universe mit mehr als 1.500 Tokens;
- minimale Trennung von Backend, Datenzugriff, State, Renderer, Theme und ViewSpec.

PR #5 war der Merge-Checkpoint für V0 + V1.

### V2 — abgeschlossen

V2 löst bewusst nur die Live-Delta-Instabilität.

Validierter Vertrag:

```text
bootstrap      -> initial layout once
new token      -> local enter
updated token  -> local visual update / pulse
retired token  -> local retirement
unrelated      -> keep spatial position
resize         -> explicit full refit allowed
```

Der große Cluster kontrahiert und expandiert bei normalen SSE-Updates nicht mehr global.

PR #6 ist der Merge-Checkpoint für **Stable Live Deltas**.

V2 definiert ausdrücklich noch nicht die endgültige Bubble-Map-Physik.

## Aktiver Slice — V3 Generic Bubble Physics + ViewSpec

Technische Authority: [`docs/FRONTEND_SPATIAL_MODEL.md`](FRONTEND_SPATIAL_MODEL.md).

V3 löst die nächste reale Grenze:

> Die Universe-Ansicht soll global stabil bleiben, sich aber lokal wie eine zusammenhängende physikalische Population verhalten.

First Principle:

```text
Cluster != renderer hard-code
Cluster = result of active ViewSpec
```

Die gleiche Engine soll später unter anderem darstellen können:

```text
group by launchpad
group by market-cap tier
group by age tier
group by lifecycle state
group by deterministic cohort
group by temporary LLM cohort
```

Die Physik selbst bleibt generisch.

### V3-R — Physics Research Gate — revidiert durch Browser-Evidence

Vor der ersten V3-A-Implementierung wurde gezielt geprüft, ob etablierte Mechanismen unser gewünschtes Verhalten bereits einfacher abbilden.

Research-Fragen:

```text
D3 local / bounded force simulation?
fixed or partially fixed nodes?
quadtree / spatial grid for local neighborhoods?
circle packing / overlap removal?
drag + collision + weak attraction?
Pixi + D3 sufficient without another dependency?
```

Entscheidungsregel:

> Bevorzuge den kleinsten etablierten Mechanismus, der den beobachtbaren V3-Vertrag erfüllt. Eigene Physik oder neue Dependencies erst bei einem nachgewiesenen Gap.

Der Research-Pass und seine Revision sind im Spatial Contract festgehalten:

```text
selected mechanism
main alternatives considered
why rejected
new dependency required? yes/no + reason
```

Die velocity-basierte `d3-force`-Simulation und der nachfolgende positionale Constraint-Resolver scheiterten im realen Browser. Beide Ansätze sind verworfen. Der aktive Reset entfernt Live-Physik vollständig.

### V3-A — Static Overview/Focus Reset — Browserretest ausstehend

Ziel:

```text
overview
→ one aggregate per canonical launchpad

focus
→ bounded top-market-cap population of one launchpad

radius changes
→ change inside one immutable slot
→ no neighbor movement

retirement
→ red collapse
→ stable empty slot until explicit refit
```

Keine Sonderfall-Architektur wie `findFreeCoordinate()`, `fillHole()` oder ein neuer Collision Solver.

Aktiver Mechanismus:

```text
d3 hierarchy pack → equal non-overlapping slots
viewport budget   → bounded visible detail
area mapping      → market-cap size inside a slot
no drag/physics   → structural stability
```

### V3-B — ViewSpec Proof

Erst nach bestandenem Browser-Test des statischen Reset werden mindestens zwei echte Gruppierungs-Views geprüft:

```text
Launchpad
+
Market Cap Tier oder Age Tier
```

Ein Projection-Preset wie `Age × Market Cap` kann im selben PR folgen, wenn V3-A/B bereits stabil sind. Es ist kein Pflichtteil für den ersten Physik-Beweis.

## Danach — vertikale Observatory-Erweiterungen

Nach V3 werden neue Fähigkeiten nach realem Erkenntniswert ausgewählt und nicht als große horizontale Roadmap vorgebaut.

Naheliegende nächste Grenzen:

```text
Thin interactive LLM analyst
Token history / timeline
Graveyard
Cohorts / population trees
Discovery provenance + flow
Freeflow analyst
Lasso / pinning / command palette
additional visualizations
deeper semantic zoom / density modes
```

Die konkrete Reihenfolge bleibt bewusst offen.

## Read-only Query-Schicht — nur bei realem gemeinsamen Bedarf

Eine eigene Query-Schicht wird nicht vorsorglich gebaut.

Sobald Frontend und LLM tatsächlich dieselben Datenprojektionen benötigen, darf `observatory/data.py` beziehungsweise eine daraus entstehende kleine read-only Query-Grenze diese gemeinsame Verantwortung übernehmen.

Sie soll:

- wenige klar definierte read-only Queries besitzen;
- reproduzierbare strukturierte Rückgabewerte liefern;
- keine freien operativen Writes ermöglichen;
- PostgreSQL-Details nur dort kapseln, wo tatsächlich eine gemeinsame Consumer-Grenze entstanden ist.

## Zurückgestellt — OHLC / Time Buckets

OHLC, Time-Buckets und Snapshot-Retention sind bewusst zurückgestellt.

Offene Fragen bleiben offen, bis diese Arbeit wieder aktiviert wird:

- welches Jupiter-Preisfeld kanonischer Input wird;
- welche Zeitsemantik für Buckets gilt;
- welche Timeframes benötigt werden;
- wie leere Buckets behandelt werden;
- ob größere Timeframes aus 1m-Buckets oder Rohbeobachtungen entstehen;
- wie lange Roh-Snapshots behalten werden.

Es existiert derzeit kein OHLC-Contract und kein vorab festgeschriebenes Tabellenschema.

## Aktuelle Reihenfolge

```text
Operational Foundation                  DONE
    ↓
Observatory V0 + V1                     DONE / PR #5
    ↓
V2 Stable Live Deltas                   DONE / PR #6
    ↓
V3-R Physics Research Gate              REVISED BY BROWSER EVIDENCE
    ↓
V3-A Static Overview/Focus Reset        BROWSER RETEST PENDING
    ↓
V3-B ViewSpec Proof
    ↓
Next vertical slice chosen by value

OHLC / Time Buckets / Retention         DEFERRED
```

Neue Schichten werden erst eingeführt, wenn ein realer Consumer, eine sichtbare Interaktion oder ein Datenvertrag sie benötigt.
