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

## Temporal Context Research — abgeschlossen

PR #16 hat den LLM-tauglichen Temporal Context gegen reale Token-Historien validiert.
`tools/inspect_token_history.py` ist die Referenz für die bewiesene Semantik:

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

Der normale Proof erzeugt weder Raw-Payload noch unaggregierte Full- oder 15m-Varianten.
Der Summary verdichtet deterministisch Market Cap inklusive Peak und Drawdown, Liquidity
inklusive `liquidity / market_cap`, Holder-Entwicklung, Ownership-Konzentration,
rollierende `stats1h`-Aktivität und Organic Evidence. Rolling `stats1h` wird nicht über
Buckets summiert. Missing bleibt Missing; es gibt kein Zero-Fill und keine Interpolation.

Realtests mit einer annähernd 24h langen JupSOL-Historie und ZEC-Historie bestätigten die
5m-Projektion bei ungefähr 100k grob geschätzten Context-Tokens. Der JupSOL-Sonderfall
`mcap == liquidity` wurde direkt in den gespeicherten Jupiter-Payloads bestätigt und ist
keine Inspector-Berechnungsstörung.

## Aktiv — WP5 Temporal Token Analysis

WP5 integriert genau den bewiesenen Temporal Context in den bestehenden read-only
Observatory-Analysten. Die Produktfrage lautet:

```text
Wie ist der ausgewählte Token innerhalb der verfügbaren Beobachtungshistorie
zu seinem aktuellen Zustand gekommen, und welche konstruktiven, schwachen,
instabilen oder unklaren Muster sind in den Daten sichtbar?
```

Der vertikale Pfad ist:

```text
selected Mint + free temporal question
              ↓
Mistral Tool Call
              ↓
get_token_temporal_context
              ↓
exact selected Mint only
              ↓
summary + 1m/5m temporal_history
              ↓
grounded temporal diagnosis
```

### Zwei eigenständige Temporal-Projektionen

WP5 behandelt den deterministischen Summary und die hochauflösende History als zwei
getrennte Produkte derselben kanonischen Observation-Serie:

```text
mint_snapshots
      ↓
canonical observations
      ├────────────→ temporal summary
      │                klein / dicht / resolution-independent
      │
      └────────────→ temporal history
                       <= 6h: 1m
                       >  6h: 5m
```

`build_temporal_summary_bundle(mint, rows)` liefert ausschließlich:

```json
{
  "token": {},
  "summary": {}
}
```

Diese Projektion ist bewusst unabhängig von der 1m/5m-LLM-Auflösung und ist damit ein
später wiederverwendbarer Baustein, um mehrere Token kompakt gegeneinander zu vergleichen,
ohne deren vollständige Temporal History an das Modell zu senden. Ein zukünftiger
Multi-Token-Vergleich bündelt einzelne Token-Summaries; er berechnet keinen gemeinsamen
Cross-Token-Summary.

Für zeitabhängige Summary-Mediane und Ratios wird intern eine feste 5m-Zeitnormalisierung
verwendet. Damit beeinflusst eine höhere Snapshot-Frequenz eines Tokens den Summary nicht
stärker als eine niedrigere Frequenz eines anderen Tokens. Start, Current, Min, Max, Peak
und Drawdown bleiben aus der kanonischen Observation-Serie abgeleitet.

Der Deep-Context `build_temporal_context(mint, rows)` komponiert:

```json
{
  "token": {},
  "summary": {},
  "temporal_history": {
    "resolution_minutes": 5,
    "buckets": []
  }
}
```

Der Inspector schreibt deshalb zusätzlich `summary_context.json`, damit beide Produkte
separat sichtbar und testbar bleiben.

### Tool-Vertrag

Genau ein neues internes read-only Tool wird ergänzt:

```text
get_token_temporal_context
```

Es erhält nur den Mint und darf ausschließlich den aktuell ausgewählten Mint lesen. Der
Server validiert diese Bindung. Das Modell darf weder freie SQL-Abfragen noch eigene
Zeiträume, Auflösungen oder andere Mints anfordern.

Die History-Abfrage ist zusätzlich zur operativen Retention explizit auf die letzten
24 Stunden begrenzt. Die Auflösung ist keine Modellentscheidung:

```text
verfügbare History <= 6h -> 1m
verfügbare History >  6h -> 5m
```

### Eine Semantik, zwei Consumer

`src/temporal_context.py` ist der gemeinsame Code-Owner für Normalisierung, Summary und
History-Projektion. Der Inspector bleibt ein dünner Research-/CLI-Consumer; das
Observatory verwendet dieselben Funktionen. Der CLI-Prozess wird nicht als Subprocess
gestartet und die Berechnung wird nicht im Frontend dupliziert.

### LLM Evidence Contract

Der deterministische Summary ist Orientierung, nicht Diagnose und nicht höherwertig als
die historische Evidence. Der Temporal-System-Prompt verpflichtet das Modell:

- `summary` **und** `temporal_history` zu prüfen;
- relevante zeitliche Verläufe selbst aus den Buckets zu untersuchen;
- den Summary mit der Zeitreihe zu bestätigen, zu qualifizieren oder ihm zu widersprechen;
- bei Widerspruch die direkte zeitliche Evidence ausdrücklich zu benennen;
- beobachtete Fakten, deterministisch abgeleitete Werte und LLM-Interpretation sprachlich
  auseinanderzuhalten;
- Missing nicht als Null zu interpretieren oder durch Proxy-Werte zu ersetzen;
- `stats1h` als rollierende Ein-Stunden-Werte zu behandeln und niemals über Buckets zu
  summieren;
- keine Entwicklung außerhalb des tatsächlich gelieferten Zeitfensters zu behaupten.

Ein Urteil ausschließlich aus dem Summary ist unzulässig.

### Aktueller Implementierungsschnitt

Der Draft implementiert:

1. `src/temporal_context.py` als gemeinsamen pure Code-Owner;
2. `summary_context.json` als separat prüfbare Summary-Projektion;
3. bounded read-only History für exakt den ausgewählten Mint und maximal 24h;
4. `get_token_temporal_context` mit harter Selected-Mint-Bindung;
5. `temporal` als dritten expliziten Analyst-Scope;
6. den Evidence Contract im Temporal-System-Prompt;
7. sichtbare Resolution, Zeitspanne, Observation- und Bucket-Anzahl im Browser;
8. deterministische Tests für 6h-Grenze, Missing, Summary-Unabhängigkeit und Tool-Bindung.

Kein allgemeiner Tool-Registry-, Agenten- oder History-Framework-Layer wird eingeführt.

### Vorbereitung auf Multi-Token-Vergleich

WP5 implementiert **noch kein** Multi-Token-Tool. Die Modulgrenze ist aber bewusst so
gesetzt, dass ein späterer bounded Vergleich nur mehrere bereits vorhandene
`token + summary`-Pakete bündeln muss:

```text
Token A -> summary A
Token B -> summary B
Token C -> summary C
Token D -> summary D
              ↓
compact LLM comparison
```

Die 1m/5m-History bleibt der Deep-Analyse eines einzelnen Tokens vorbehalten, solange kein
konkreter Cross-Token-History-Use-Case eine andere Grenze beweist.

### Visible proof / Stop condition

WP5 ist abgeschlossen, wenn der reale Browser mindestens diese drei Fälle beweist:

- Token mit `<= 6h` verfügbarer History -> realer Tool Call -> `1m` Context;
- Token mit `> 6h` verfügbarer History -> realer Tool Call -> `5m` Context;
- Token mit fehlenden Teilfeldern -> Missing bleibt Missing und die Antwort benennt die
  begrenzte Evidence.

Für jeden Fall muss gelten:

- Tool-Mint == aktuell ausgewählter Mint;
- genau ein `get_token_temporal_context` Tool Call für die Analyse;
- Antwort verwendet die zeitliche History und nicht nur den Summary;
- Resolution und tatsächlich gelieferter Zeitraum sind sichtbar;
- keine operative Mutation;
- keine erfundenen Werte oder Zeiträume.

## Nicht Teil der funktionalen Foundation

- Bubble Map oder Designumbau;
- persistierte OHLC- oder Langzeit-History-Plattform;
- benutzerdefinierte Zeiträume oder Auflösungen;
- Raw-, Full- oder 15m-LLM-Payloads;
- Multi-Token-Tool oder Cross-Token-History-Vergleich in WP5;
- Prognosen oder automatische Trading-Aktionen;
- Bubble-Größe, Pulsieren, Farbe, Layout oder Physics;
- Datenbank-, Collector- oder Lifecycle-Änderungen;
- automatischer Good/Bad-Score als operative Wahrheit.

Nach WP5 ist kein WP6 vorab definiert. Visual Redesign, zusätzliche interne Tools und
Discovery Provenance werden erst nach der Browservalidierung neu bewertet.
