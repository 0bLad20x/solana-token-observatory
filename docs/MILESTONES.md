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
1m <= 6h, otherwise 5m
              ↓
token + deterministic summary + temporal_history
              ↓
grounded temporal diagnosis
```

### Tool-Vertrag

Genau ein neues internes read-only Tool wird ergänzt:

```text
get_token_temporal_context
```

Es erhält nur den Mint und darf ausschließlich den aktuell ausgewählten Mint lesen. Der
Server validiert diese Bindung. Das Modell darf weder freie SQL-Abfragen noch eigene
Zeiträume, Auflösungen oder andere Mints anfordern.

Die Tool-Antwort entspricht semantisch dem validierten `llm_context.json`:

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

Die Auflösung ist keine Modellentscheidung:

```text
verfügbare History <= 6h -> 1m
verfügbare History >  6h -> 5m
```

Die verfügbare History ist durch die operative Raw-Retention auf maximal ungefähr 24h
begrenzt.

### Eine Semantik, zwei Consumer

Der Inspector bleibt das Research-/CLI-Testwerkzeug, das Observatory wird der zweite reale
Consumer derselben Temporal-Projection-Semantik. WP5 darf deshalb die Berechnung nicht
kopieren und den CLI-Prozess nicht als Subprocess starten. Die pure Projection-/Summary-
Logik bekommt genau einen gemeinsamen Code-Owner; der Inspector wird ein dünner Consumer
davon und das Observatory ruft dieselbe Logik read-only auf.

### LLM Evidence Contract

Der deterministische Summary ist Orientierung, nicht Diagnose und nicht höherwertig als
die historische Evidence. Der Temporal-System-Prompt muss das Modell verpflichten:

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

### Minimaler Implementierungsschnitt

WP5 verändert nur den read-only Analyst-Pfad:

1. gemeinsame pure Temporal-Projection aus dem validierten Inspector-Verhalten ableiten;
2. read-only History für exakt den ausgewählten Mint laden;
3. `get_token_temporal_context` in den bestehenden bounded Tool-Vertrag aufnehmen;
4. einen expliziten `temporal` Analyst-Scope ergänzen;
5. den Evidence Contract in dessen System Prompt verankern;
6. im Browser Resolution, abgedeckte Zeitspanne und die grounded Antwort sichtbar machen.

Kein neuer allgemeiner Tool-Registry-, Agenten- oder History-Framework-Layer wird dafür
eingeführt.

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
- keine operative Mutation;
- keine erfundenen Werte oder Zeiträume.

## Nicht Teil der funktionalen Foundation

- Bubble Map oder Designumbau;
- persistierte OHLC- oder Langzeit-History-Plattform;
- benutzerdefinierte Zeiträume oder Auflösungen;
- Raw-, Full- oder 15m-LLM-Payloads;
- Cross-Token-History-Vergleich;
- Prognosen oder automatische Trading-Aktionen;
- Bubble-Größe, Pulsieren, Farbe, Layout oder Physics;
- Datenbank-, Collector- oder Lifecycle-Änderungen;
- automatischer Good/Bad-Score als operative Wahrheit.

Nach WP5 ist kein WP6 vorab definiert. Visual Redesign, zusätzliche interne Tools und
Discovery Provenance werden erst nach der Browservalidierung neu bewertet.
