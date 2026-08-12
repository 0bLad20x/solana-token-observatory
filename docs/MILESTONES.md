# Milestones

## Zweck

Dieses Dokument nennt nur den aktuellen Stand und den genau einen aktiven nächsten Slice.
Implementiertes Verhalten und harte Grenzen bleiben in Code, `docs/architecture.md`,
`docs/LIFECYCLE_CONTRACT.md` und `docs/FRONTEND_OBSERVATORY.md`.

## Foundation — abgeschlossen

Die operative Basis steht:

- Discovery aus mehreren Solana-Quellen;
- Jupiter Search Monitoring;
- PostgreSQL-Registry und immutable `mint_snapshots`;
- Operational Lifecycle v0.1;
- read-only Observatory mit aktueller Population, Token Inspector, SSE-Deltas und
  Retirements.

Die beiden V3-Spatial-Experimente wurden nach negativem Browserergebnis geschlossen.
Bubble-Physik und ViewSpec-Arbeit sind kein aktiver Milestone.

## WP1 Token Web Research — abgeschlossen

WP1 liefert ausgewählten Token, freie Frage, serverseitige Mistral Web Search sowie
Antwort und Quellen als externe Evidenz. Der Slice wurde als PR #10 gemergt.

## WP2 Current Population Query — abgeschlossen

WP2 beweist genau einen internen Tool Call:

```text
free question
      ↓
Mistral function arguments
      ↓
bounded read-only query_tokens
      ↓
top 5 current rows
      ↓
grounded answer
```

Der Slice enthält ausschließlich:

- die bestehende aktuelle aktive `FrontendReader`-Projektion;
- genau ein internes `query_tokens`-Tool;
- ein zentrales beschriebenes Feldvokabular für aktuelle Werte;
- die pro Anfrage real verfügbaren kanonischen Launchpads;
- Sortierung sowie Default-Limit fünf und Hard-Limit zwanzig;
- eine kleine Scope-Umschaltung im bestehenden Analyst-Panel;
- sichtbare aktuelle Abfragemöglichkeiten, wenn keine eindeutige Zuordnung gelingt.

WP2 ist abgeschlossen, wenn eine frei formulierte unterstützte Frage nachweisbar
`query_tokens` ausführt und eine Frage nach einer nicht vorhandenen Metrik keine
Ersatzmetrik oder erfundene Antwort erzeugt, sondern die verfügbaren Möglichkeiten zeigt.

Der Slice wurde nach realer Browservalidierung als PR #11 gemergt.

## WP3 Token Search & Selection — abgeschlossen

WP3 stellt vollständigen funktionalen Zugriff auf die aktive Population her:

```text
Mint / Symbol / Name search ─┐
                             ├─> shared selection -> Inspector -> Web Research
query_tokens result ─────────┘
```

Der Slice enthält ausschließlich:

- clientseitige Suche in der bereits geladenen `/api/universe`-Population;
- Mint, Symbol und Name als Suchfelder;
- Market-Cap-Sortierung sowie Market Cap, Liquidity und Holders pro Treffer;
- eine gemeinsame Selection für Visualisierung, Suche und `query_tokens`-Treffer;
- Inspector- und Web-Research-Kontext für den ausgewählten Token;
- höchstens acht sichtbare Suchtreffer.

WP3 ist abgeschlossen, wenn jeder aktive Token unabhängig von der Visualisierung
auffindbar und auswählbar ist und ein `query_tokens`-Treffer dieselbe Selection auslöst.

Der Slice wurde nach realer Browservalidierung als PR #12 gemergt.

## WP4 Volume Activity Deltas — abgeschlossen

WP4 ersetzt die lange Liste beliebiger State Events durch genau eine kleine aktuelle
Projektion:

```text
positive Änderung des rollierenden volume_5m
                     ↓
        volume_5m / market_cap
                     ↓
   pro Mint über 60 Sekunden aggregieren
                     ↓
          fünf stärkste Tokens
```

Jede Zeile zeigt Zeitpunkt, Token, Volumen vorher/nachher, aktuelle Market Cap sowie
Ratio vorher/nachher und deren Differenz. Nur Beobachtungen mit steigendem Volumen und
steigender Ratio sind gültig. Missing bleibt missing. `volume_5m` ist das rollierende
Jupiter-Fünf-Minuten-Fenster und kein exaktes Event-Volumen.

WP4 ist abgeschlossen, wenn im realen Browser höchstens fünf unterschiedliche Tokens
korrekt gerankt werden, Mehrfachupdates pro Mint zu einer Zeile führen und Einträge nach
60 Sekunden verschwinden.

Der Feed verwendet dieselbe Selection wie Suche und Bubble. Der Slice wurde nach realer
Browservalidierung als PR #13 gemergt.

## Aktiv — WP5 Temporal Token Context

WP5 untersucht zuerst den kleinsten belastbaren LLM-Kontext für die Frage:

```text
Wie ist dieser Token in seinem verfügbaren Beobachtungsfenster
zu seinem aktuellen Zustand gekommen?
```

Der aktuelle Research-Proof ist `tools/inspect_token_history.py`:

```text
maximal 24h mint_snapshots
        ↓
LLM-Grundvertrag
        ↓
History <= 6h -> 1m Buckets
History >  6h -> 5m Buckets
        ↓
deterministic summary + temporal_history
        ↓
llm_context.json
```

Der Summary verdichtet deterministisch Market Cap inklusive Peak und Drawdown,
Liquidity inklusive `liquidity / market_cap`, Holder-Entwicklung,
Ownership-Konzentration, rollierende `stats1h`-Aktivität und Organic Evidence. Rolling
`stats1h` wird nicht über Buckets summiert. Missing bleibt Missing; es gibt kein
Zero-Fill und keine Interpolation.

Raw-Payload-, unaggregierte Full- und 15m-Repräsentationen gehören nicht mehr zum
aktiven Proof. Der Inspector erzeugt genau einen LLM-Kontext plus `report.json`.

Wichtige LLM-Grenze für die spätere Integration: Der System Prompt muss das Modell
zwingen, `temporal_history` selbst zu untersuchen und den Summary nur als deterministische
Orientierung zu verwenden. Ein Urteil ausschließlich aus dem Summary ist nicht zulässig;
die Zeitreihe muss die Zusammenfassung bestätigen, qualifizieren oder in Frage stellen.

Der aktuelle Stop ist noch bewusst vor der Observatory-Integration: Zuerst muss der reale
Inspector-Lauf für lange und kurze Token-Historien zeigen, dass Projektion, Summary und
Context-Größe sinnvoll sind. Erst danach wird daraus der konkrete read-only WP5-Tool- und
Browser-Vertrag abgeleitet.

## Nicht Teil der funktionalen Foundation

- Bubble Map oder Designumbau;
- persistierte OHLC- oder Langzeit-History-Plattform;
- Bubble-Größe, Pulsieren, Farbe, Layout oder Physics;
- Price-Change-Proxies;
- Datenbank-, Collector- oder Lifecycle-Änderungen;
- automatischer Good/Bad-Score als operative Wahrheit.

Nach WP5 ist kein WP6 vorab definiert. Visual Redesign, zusätzliche interne Tools und
Discovery Provenance werden erst nach der Browservalidierung neu bewertet.
