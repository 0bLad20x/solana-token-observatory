# Milestones

## Zweck

Dieses Dokument beschreibt knapp den aktuellen Projektstand und die nächste Entwicklungsrichtung. Es ist keine Authority für bereits implementierte Architektur oder konkrete Thresholds. Implementierter Zustand gehört in `README.md`, `docs/architecture.md` und den Code.

## Aktueller Stand

Das Framework besitzt bereits vier getrennte Ebenen:

1. **Discovery:** neue Solana-Mints aus mehreren Quellen aufnehmen.
2. **Jupiter Monitoring:** aktive Mints regelmäßig über Jupiter Search beobachten und fachlich veränderte Zustände historisieren.
3. **Operational Lifecycle:** wirtschaftlich offensichtlich schlechte Tokens anhand transparenter Regeln deaktivieren.
4. **Read-only Research:** Survivor-Tokens mit Diagnose- und Anomaly-Analysen untersuchen, ohne daraus automatisch operative Mutationen abzuleiten.

Die nächste Entwicklungsstufe beginnt bewusst **nach** dem Lifecycle: Aus den verbleibenden Survivor-Tokens soll eine strukturierte Zeitreihen- und Query-Schicht entstehen.

## Milestone 1 — Survivor OHLC / Time Buckets

Aus den gespeicherten Jupiter-Beobachtungen der relevanten Survivor-Tokens sollen OHLC-Zeitreihen aufgebaut werden.

### Ziel

- kanonische Time Buckets erzeugen;
- zunächst ein 1-Minuten-Schema definieren und validieren;
- spätere Timeframes wie 5m, 15m, 1h oder weitere Intervalle daraus ableiten können;
- unregelmäßige Jupiter-Beobachtungen korrekt behandeln.

### 1-Minuten-Vertrag

Für einen Bucket `[t, t + 1m)`:

```text
open  = erster beobachteter Preis im Bucket
high  = höchster beobachteter Preis im Bucket
low   = niedrigster beobachteter Preis im Bucket
close = letzter beobachteter Preis im Bucket
observation_count = Anzahl realer Preisbeobachtungen im Bucket
```

Leere Buckets werden **nicht** automatisch per Fill-Forward zu künstlichen Candles. Fehlende Beobachtung bleibt zunächst fehlend.

Konzeptionelles Schema:

```sql
CREATE TABLE token_ohlc_1m (
    mint              TEXT        NOT NULL,
    bucket_start      TIMESTAMPTZ NOT NULL,
    open              DOUBLE PRECISION NOT NULL,
    high              DOUBLE PRECISION NOT NULL,
    low               DOUBLE PRECISION NOT NULL,
    close             DOUBLE PRECISION NOT NULL,
    observation_count INTEGER     NOT NULL,
    first_observed_at TIMESTAMPTZ NOT NULL,
    last_observed_at  TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (mint, bucket_start)
);
```

Noch offen bleiben bewusst:

- welches konkrete Jupiter-Preisfeld der kanonische Input wird;
- ob größere Timeframes ausschließlich aus 1m-Buckets oder teilweise direkt aus Rohbeobachtungen aggregiert werden;
- Retention und mögliche Verdichtung alter Rohdaten.

Diese Entscheidungen werden erst nach einem kleinen realen 1m-Testdatensatz festgelegt.

## Milestone 2 — Read-only Query Layer

Über den persistierten Token-, Lifecycle-, Anomaly- und später OHLC-Daten soll eine kontrollierte Query-Schicht entstehen.

Ziel:

- klar definierte read-only Queries statt freiem Datenbankzugriff;
- reproduzierbare Antworten auf Fragen zu einzelnen Tokens, Populationen und Zeiträumen;
- strukturierte Rückgabewerte, die sowohl Frontend als auch LLM verwenden können.

Die Query-Schicht ist die fachliche Grenze zwischen PostgreSQL und späteren Verbrauchern.

## Milestone 3 — Frontend

Ein lokales Frontend soll den aktuellen Zustand des Systems sichtbar machen.

Mögliche Inhalte:

- aktive Survivor-Population;
- Lifecycle-Status und Deaktivierungsgründe;
- Anomaly-/Archetype-Tags;
- Token-Verläufe und optional OHLC-Charts;
- Query-Ergebnisse aus der gemeinsamen read-only Query-Schicht.

Der konkrete Frontend-Stack und die endgültige Visualisierung sind noch nicht festgelegt.

## Milestone 4 — LLM Tool Calling

Aus einem lokalen Browser-Frontend soll ein Large Language Model über eine API auf kontrollierte Tools zugreifen können.

Zielablauf:

```text
User question
    ↓
LLM
    ↓ tool call
Read-only query tool
    ↓
Structured database result
    ↓
LLM analysis
    ↓
Answer in browser
```

Das LLM soll nicht direkt beliebige SQL-Schreibzugriffe erzeugen. Die erste Version soll wenige klar definierte read-only Tools verwenden und deren Ergebnisse analysieren.

Welche Daten und Queries das LLM konkret verwenden darf, wird erst anhand realer Analysefragen festgelegt.

## Reihenfolge

```text
Operational Lifecycle
        ↓
Survivor population
        ↓
1m OHLC / Time-Bucket contract
        ↓
Read-only Query Layer
        ├──────────────→ Frontend
        └──────────────→ LLM Tool Calling
```

Anomaly Research läuft parallel weiter und kann später zusätzliche Tags oder Query-Dimensionen liefern. Es bleibt von operativen Lifecycle-Mutationen getrennt, bis einzelne Regeln ausdrücklich validiert und übernommen werden.