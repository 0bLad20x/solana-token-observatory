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
- Trennung des operativen Core von Diagnose-/GMGN-Research-Tooling.

Diese Foundation wird nicht vorsorglich weiter refaktoriert. Änderungen benötigen ein konkretes Problem oder eine neue fachliche Grenze.

## Aktiv — Frontend MVP

Ein lokales read-only Frontend wird aktuell separat in Draft PR #5 entwickelt.

Ziel der ersten Version:

- aktuelle aktive Survivor-Population sichtbar machen;
- Market Cap, Liquidity, Holder und aktuelle Aktivität darstellen;
- neue, veränderte und deaktivierte Tokens live sichtbar machen;
- Lifecycle-Deaktivierungsgründe anzeigen;
- keine operative Mutation aus dem Frontend erlauben.

Der Draft ist bewusst additiv. Collector, Lifecycle, Repository und Schema werden durch die Frontend-Implementierung nicht verändert.

Vor einem späteren Merge wird der Draft auf den dann aktuellen `main` synchronisiert und gegen dessen Schema-/Read-only-Vertrag geprüft.

## Später — gemeinsame Read-only Query-Schicht

Eine eigene Query-Schicht wird nicht vorsorglich gebaut.

Sie wird erst sinnvoll, wenn mindestens zwei reale Consumer dieselben fachlichen Queries benötigen, zum Beispiel Frontend und LLM-Tools.

Dann soll sie:

- wenige klar definierte read-only Queries besitzen;
- reproduzierbare strukturierte Rückgabewerte liefern;
- keine freien operativen Writes ermöglichen;
- PostgreSQL-Details dort kapseln, wo tatsächlich eine gemeinsame Consumer-Grenze entstanden ist.

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

## Später — LLM Tool Calling

Ein Large Language Model soll später über wenige kontrollierte read-only Tools auf das System zugreifen können.

Zielbild:

```text
User question
    ↓
LLM
    ↓ tool call
Read-only query/tool contract
    ↓
Structured result
    ↓
LLM analysis
```

Das LLM erhält keine direkte Authority für operative SQL-Writes oder Lifecycle-Mutationen.

## Aktuelle Reihenfolge

```text
Foundation                         DONE
    ↓
Frontend MVP                      ACTIVE — Draft PR #5
    ↓
Shared Query Layer                WHEN NEEDED BY MULTIPLE CONSUMERS
    ↓
OHLC / Time Buckets / Retention   DEFERRED
    ↓
LLM Tool Calling                  LATER
```

Die Reihenfolge ist keine Verpflichtung, künstliche Zwischenabstraktionen zu bauen. Neue Schichten werden erst eingeführt, wenn ein realer Consumer oder Datenvertrag sie benötigt.
