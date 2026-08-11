# Milestones

## Zweck

Dieses Dokument beschreibt knapp den aktuellen Projektstand und die nächste Entwicklungsrichtung. Es ist keine Authority für bereits implementierte Architektur oder konkrete Thresholds. Implementierter Zustand gehört in `README.md`, `docs/architecture.md`, `docs/LIFECYCLE_CONTRACT.md` und den Code.

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

## Aktiv — Frontend Observatory

Draft PR #5 entwickelt den ersten read-only Vertical Slice des Frontends.

Die fachliche und architektonische Authority dafür ist [`docs/FRONTEND_OBSERVATORY.md`](FRONTEND_OBSERVATORY.md).

Das Ziel ist nicht, zuerst horizontal ein großes Frontend-Framework aufzubauen. Jeder Schritt soll in kurzer Folge ein sichtbar funktionierendes Ergebnis liefern.

Aktiver Ablauf:

```text
V0  Observatory Contract                 DONE / DOCUMENTED
 ↓
V1  Structural split + design system     NEXT
 ↓
V2  Stable Live Universe                 NEXT
 ↓
V3  Minimal ViewSpec                     NEXT
 ↓
V4  Thin LLM analyst slice               TARGET IF V1-V3 STABLE
```

Der erste Merge soll einen kohärenten Observatory-Unterbau liefern: read-only, visuell stabil unter Live-Deltas, semantisch konsistent gestaltet und ohne neuen Monolithen. Eine dünne LLM-Integration darf bereits Teil dieses Drafts werden, wenn sie denselben bounded read-only Datenvertrag nutzt und die vorherigen Slices stabil bleiben.

## Danach — vertikale Observatory-Erweiterungen

Nach dem ersten Merge werden neue Fähigkeiten als kleine vertikale Slices ergänzt. Die Reihenfolge wird nach realem Erkenntniswert entschieden und nicht vorsorglich festgeschrieben.

Mögliche nächste Grenzen:

```text
Token history / timeline
Graveyard
Cohorts / population trees
Discovery provenance + flow
Interactive analyst expansion
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
Frontend Observatory Draft #5           ACTIVE
    ├─ stable visual delta semantics
    ├─ minimal responsibility split
    ├─ semantic Solana/memecoin design language
    ├─ ViewSpec foundation
    └─ thin LLM vertical slice if stable
    ↓
Merge coherent Observatory foundation
    ↓
Next vertical slice chosen by value

OHLC / Time Buckets / Retention          DEFERRED
```

Die Reihenfolge ist keine Verpflichtung, künstliche Zwischenabstraktionen zu bauen. Neue Schichten werden erst eingeführt, wenn ein realer Consumer, eine sichtbare Interaktion oder ein Datenvertrag sie benötigt.
