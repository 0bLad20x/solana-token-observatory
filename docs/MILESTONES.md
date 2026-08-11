# Milestones

## Zweck

Dieses Dokument beschreibt knapp den aktuellen Projektstand und die nächste Entwicklungsrichtung. Es ist keine Authority für bereits implementierte Architektur oder konkrete Thresholds. Implementierter Zustand gehört in `README.md`, `docs/architecture.md`, `docs/LIFECYCLE_CONTRACT.md`, `docs/FRONTEND_OBSERVATORY.md` und den Code.

## Foundation — abgeschlossen

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

Die fachliche und architektonische Authority ist [`docs/FRONTEND_OBSERVATORY.md`](FRONTEND_OBSERVATORY.md).

Das Frontend wird in kurzen vertikalen Slices entwickelt. Jeder Slice soll in einem real laufenden Browser/API-Pfad sichtbar funktionieren, bevor der nächste beginnt.

Aktueller Stand:

```text
V0  Observatory Contract                 DONE
 ↓
V1  Structural split + design system     DONE / VALIDATED
 ↓
V2  Stable Live Universe                 NEXT
 ↓
V3  Minimal ViewSpec                     LATER
 ↓
V4  Thin LLM analyst slice               LATER
```

V1 wurde mit dem real laufenden Frontend validiert: unabhängiger Serverstart, statische Module, `/api/health`, `/api/universe`, SSE-Pfad und eine Universe-Population von mehr als 1,500 Tokens funktionieren.

PR #5 ist damit der erste Merge-Checkpoint `V0 + V1`. V2 und spätere Slices werden nicht künstlich an diesen PR gekoppelt, sondern bauen vertikal auf der gemergten Baseline weiter.

## Nächster Slice — V2 Stable Live Universe

Das nächste konkrete Problem ist die visuelle Instabilität unter Live-Deltas.

Heute können einzelne Token-Änderungen die D3-Force-Simulation für eine größere Population erneut anstoßen. Bei großen Populationen wirkt dadurch eine lokale Änderung wie ein globaler Refresh.

V2 soll deshalb erreichen:

```text
new token      -> local enter
updated token  -> local visual change / one pulse
retired token  -> explicit retirement transition
unrelated      -> remain spatially stable
```

Der sichtbare Erfolg ist erreicht, wenn sich die räumliche Orientierung bei laufenden Deltas erhält und klar erkennbar bleibt, welcher Token tatsächlich geändert wurde.

## Danach — vertikale Observatory-Erweiterungen

Nach V2 werden neue Fähigkeiten nach realem Erkenntniswert ausgewählt und nicht vorsorglich als große horizontale Roadmap gebaut.

Mögliche nächste Grenzen:

```text
Minimal ViewSpec / alternate projection
Thin interactive LLM analyst
Token history / timeline
Graveyard
Cohorts / population trees
Discovery provenance + flow
Freeflow analyst
Lasso / pinning / command palette
additional visualizations
semantic zoom / density mode
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

Offene Fragen bleiben ausdrücklich offen, bis diese Arbeit wieder aktiviert wird:

- welches Jupiter-Preisfeld kanonischer Input wird;
- welche Zeitsemantik für Buckets gilt;
- welche Timeframes benötigt werden;
- wie leere Buckets behandelt werden;
- ob größere Timeframes aus 1m-Buckets oder Rohbeobachtungen entstehen;
- wie lange Roh-Snapshots behalten werden.

Es existiert deshalb derzeit **kein OHLC-Contract** und kein vorab festgeschriebenes Tabellenschema.

Wenn dieser Milestone wieder aufgenommen wird, soll die Semantik zunächst an einem kleinen realen Datensatz validiert und anschließend als eigener Vertrag dokumentiert werden.

## Aktuelle Reihenfolge

```text
Operational Foundation                  DONE
    ↓
Observatory V0 + V1                     DONE / MERGE CHECKPOINT PR #5
    ↓
V2 Stable Live Universe                 NEXT
    ↓
Next vertical slice chosen by value

OHLC / Time Buckets / Retention          DEFERRED
```

Die Reihenfolge ist keine Verpflichtung, künstliche Zwischenabstraktionen zu bauen. Neue Schichten werden erst eingeführt, wenn ein realer Consumer, eine sichtbare Interaktion oder ein Datenvertrag sie benötigt.
