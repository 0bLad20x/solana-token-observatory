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
`tools/inspect_token_history.py` bleibt das Research-Werkzeug für zwei getrennte Produkte:

```text
maximal 24h mint_snapshots
        ↓
canonical observations
        ├──> summary_context.json
        │      token + deterministic summary
        │
        └──> llm_context.json
               token + summary + adaptive 1m/5m temporal_history
```

Der Summary verdichtet deterministisch Market Cap inklusive Peak und Drawdown, Liquidity
inklusive `liquidity / market_cap`, Holder-Entwicklung, Ownership-Konzentration,
rollierende `stats1h`-Aktivität und Organic Evidence. Missing bleibt Missing; es gibt kein
Zero-Fill und keine Interpolation.

Der Deep-Context verwendet für verfügbare History bis 6h 1m-Buckets und darüber 5m-Buckets.
Realtests mit annähernd 24h langen Historien lagen bei ungefähr 100k grob geschätzten
Context-Tokens. Der JupSOL-Sonderfall `mcap == liquidity` wurde direkt in den gespeicherten
Jupiter-Payloads bestätigt und ist keine Inspector-Berechnungsstörung.

Ein realer WP5-Browsertest zeigte anschließend die Produktgrenze des Deep-Contexts: Eine
24h-Analyse mit 160 5m-Buckets und 12.809 Raw-Observations benötigte rund 118 Sekunden,
während der zusätzliche Erkenntnisgewinn gegenüber dem deterministischen Summary gering
war. Der Deep-Context bleibt deshalb Research Evidence, ist aber **nicht** mehr der
standardmäßige Observatory-LLM-Payload.

## Aktiv — WP5 Temporal Summary Analysis

WP5 prüft jetzt die kleinste sinnvolle Analyseprojektion:

```text
selected Mint + free question
              ↓
Mistral Tool Call
              ↓
get_token_temporal_context
              ↓
exact selected Mint only
              ↓
token + deterministic summary
              ↓
expert diagnosis
```

Das Observatory sendet **keine 1m/5m-Buckets** und keine Raw-History an das LLM. Der
bestehende Tool-Name bleibt vorerst `get_token_temporal_context`; sein tatsächlicher
Vertrag ist im WP5-Slice `token + summary`.

### Eigenständiger Summary-Vertrag

`build_temporal_summary_bundle(mint, rows)` liefert ausschließlich:

```json
{
  "token": {},
  "summary": {}
}
```

Der Summary ist unabhängig von der adaptiven 1m/5m-Deep-History. Für zeitabhängige
Summary-Mediane und Ratios wird intern eine feste 5m-Zeitnormalisierung verwendet, damit
eine höhere Snapshot-Frequenz eines Tokens dessen Median nicht künstlich stärker gewichtet.
Diese internen 5m-Samples werden **nicht** als Zeitreihe an das LLM weitergegeben.

Start, Current, Min, Max, Peak und Drawdown werden aus der kanonischen Observation-Serie
abgeleitet. `stats1h` bleibt rollierende Source-Evidence und wird niemals über Samples
summiert.

### LLM Expert Contract

Der System-Prompt soll nicht mehr vortäuschen, eine vollständige zeitliche Trajektorie zu
sehen. Das Modell erhält nur den Summary und muss daraus eine versierte, aber begrenzte
Expertenanalyse erzeugen. Es soll insbesondere:

- Observation-Horizont und Evidence-Grenzen benennen;
- Valuation anhand Change, Range, Peak und Drawdown diagnostizieren;
- Liquidity relativ zur Valuation und `liquidity / market_cap` korrekt interpretieren;
- Holder-Entwicklung und Ownership-Konzentration einordnen;
- aktuelle `stats1h`-Aktivität gegen deren Median-Baseline vergleichen;
- Buy/Sell-, Net-Flow- und Organic-Evidence gemeinsam beurteilen;
- Cross-Metric-Bestätigung und Divergenzen suchen;
- konstruktive Signale, Risiken und Unknowns priorisieren;
- Facts und Interpretation auseinanderhalten;
- mit einer kalibrierten Einschätzung und Confidence enden.

Das Modell darf aus dem Summary **keine** Phasen, Wendepunkte, Event-Reihenfolge oder
historischen Werte erfinden, die nicht enthalten sind. `current + median` ist insbesondere
kein Ersatz für `start + min + max`.

### Tool- und Storage-Grenzen

`get_token_temporal_context` erhält ausschließlich den aktuell ausgewählten Mint. Der
Server validiert die Mint-Bindung. Keine freie SQL-Abfrage, kein eigener Zeitraum und keine
andere Mint-Auswahl sind erlaubt.

Die zugrunde liegende Snapshot-Abfrage ist zusätzlich zur operativen Retention explizit
auf die letzten 24 Stunden begrenzt. Das Observatory baut daraus nur den Standalone
Summary. `src/temporal_context.py` bleibt der gemeinsame Code-Owner; der Inspector darf
weiterhin zusätzlich den Deep-Context als Research-Artefakt erzeugen.

### Vorbereitung auf Multi-Token-Vergleich

Die Summary-Grenze ist zugleich die Vorbereitung auf einen späteren bounded Vergleich:

```text
Token A -> summary A
Token B -> summary B
Token C -> summary C
Token D -> summary D
              ↓
compact LLM comparison
```

WP5 implementiert **noch kein** Multi-Token-Tool. Es beweist zunächst, ob ein einzelner
Summary mit einem stärkeren Expertenprompt genug analytischen Wert liefert. Erst danach
wird entschieden, ob der Summary zusätzliche deterministische Informationen aus der
Time-Bucket-Research-Projektion aufnehmen soll.

### Visible proof / Stop condition

WP5 ist abgeschlossen, wenn der reale Browser mindestens bestätigt:

- Tool-Mint == aktuell ausgewählter Mint;
- genau ein `get_token_temporal_context` Tool Call;
- an Mistral geht `token + summary`, aber **kein** `temporal_history`;
- Zeitspanne, Observation-Anzahl und grobe Summary-Inputgröße sind sichtbar;
- die Antwort analysiert Beziehungen zwischen Metriken statt den Summary nur abzuschreiben;
- die Antwort behauptet keine nicht gelieferte Chronologie oder Bucket-Evidence;
- Missing bleibt Unknown;
- Laufzeit ist gegenüber dem ~100k-Deep-Context praktisch nutzbar;
- Current Data und Web Research funktionieren unverändert.

## Nicht Teil der funktionalen Foundation

- Bubble Map oder Designumbau;
- persistierte OHLC- oder Langzeit-History-Plattform;
- benutzerdefinierte Zeiträume oder Auflösungen;
- Raw-, Full- oder 15m-LLM-Payloads;
- 1m/5m-History als Standard-Payload in WP5;
- Multi-Token-Tool oder Cross-Token-History-Vergleich in WP5;
- Prognosen oder automatische Trading-Aktionen;
- Bubble-Größe, Pulsieren, Farbe, Layout oder Physics;
- Datenbank-, Collector- oder Lifecycle-Änderungen;
- automatischer Good/Bad-Score als operative Wahrheit.

Nach WP5 ist kein WP6 vorab definiert. Visual Redesign, zusätzliche interne Tools und
Discovery Provenance werden erst nach der Browservalidierung neu bewertet.
