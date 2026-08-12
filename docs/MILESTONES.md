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

PR #16 bewies zunächst, dass sich bis zu 24h `mint_snapshots` deterministisch zu einer
LLM-tauglichen History verdichten lassen. Die 1m/5m-Projektion war als Research-Proof
korrekt, aber ein realer 24h-Browsertest benötigte mit ungefähr 100k grob geschätzten
Input-Tokens rund 118 Sekunden und lieferte gegenüber dem kompakten Summary nur begrenzten
zusätzlichen Erkenntnisgewinn.

Diese Forschung ist abgeschlossen. Adaptive 1m/5m/15m-History ist **kein Bestandteil des
WP5-Produktpfads mehr** und wird auch vom Inspector nicht mehr erzeugt.

## Aktiv — WP5 Temporal Summary Analysis

WP5 reduziert den Analysepfad auf die kleinste bewiesene Projektion:

```text
maximal 24h mint_snapshots
        ↓
exact core metrics + fixed representative samples
        ↓
deterministic temporal summary
        ↓
token + summary
        ↓
ONE Mistral request
        ↓
expert diagnosis
```

Das LLM erhält keine Raw-History, keine 1m/5m/15m-Buckets und keine adaptive Resolution.
Der Summary ist die Produktgrenze und darf später gezielt um zusätzliche deterministische
Informationen erweitert werden, wenn ein konkreter analytischer Nutzen bewiesen ist.

Im Unterschied zu WP2 ist hier **kein LLM Tool Call nötig**. Der Scope und der ausgewählte
Mint bestimmen serverseitig bereits eindeutig, welche Summary geladen wird. Ein
vorgeschalteter Mistral-Request, der nur den feststehenden Mint zurückfordert, wäre reine
Latenz ohne zusätzliche Entscheidung.

### Summary-Berechnung

Start, Current, Min, Max, Change, Peak und Max Drawdown werden aus allen verfügbaren
Beobachtungen innerhalb des maximal 24h langen Fensters berechnet.

Für rollierende `stats1h`-Werte, deren Mediane und abgeleitete Ratios wird intern genau
eine feste 5m-Zeitnormalisierung verwendet. Sie ist **kein Time-Bucket-Produkt** und wird
nicht an das LLM ausgegeben. Ihr einziger Zweck ist, unterschiedliche Snapshot-Frequenzen
nicht unterschiedlich stark in Median- und Ratio-Statistiken zu gewichten.

```text
raw observations
      ├── exact core trajectory facts
      │
      └── one representative sample / 5m
                 ↓
        rolling-stat medians + ratios
                 ↓
             summary
```

### Query-Grenze

Die Datenbankabfrage ist ebenfalls auf den Summary-Vertrag reduziert:

- der exakte History-Scan lädt nur `observed_at` und die kleinen skalaren Felder für
  Market Cap, Liquidity, Holders, Organic Score und Ownership;
- das größere `stats1h`-JSON wird nur für einen repräsentativen Datensatz pro 5m-Sample
  aus PostgreSQL übertragen;
- statische Token-Metadaten werden nicht mehr in jedem Snapshot erneut projiziert;
- der vorhandene Primary Key `(mint, observed_at)` bleibt die Grundlage des per-Mint
  History-Scans;
- keine neue Tabelle, Materialized View oder persistierte Summary wird für WP5 eingeführt.

Damit bleibt die Summary erweiterbar, ohne wieder die vollständigen Snapshot-Payloads oder
Time-Bucket-Historien durch den Produktpfad zu transportieren.

### LLM Expert Contract

Das Modell soll Beziehungen zwischen den gelieferten Fakten analysieren, aber die Grenzen
des Summary strikt respektieren. Insbesondere gilt:

- Observation Count beweist keine lückenlose Coverage;
- Observation Window ist nicht Token Age;
- `max` und `peak_at` gelten nur innerhalb des gelieferten Fensters und sind kein ATH;
- Drawdown beweist keine individuelle Stundenrichtung;
- keine erfundenen Phasen, Wendepunkte, linearen/parabolischen Verläufe oder Eventfolgen;
- keine Behauptung von Bots, Fake Volume, Wash Trading, Whales, Manipulation,
  Akkumulation oder Distribution aus aggregierten Metriken allein;
- positive `num_net_buyers` bleiben positive Net Buyers, auch wenn sie unter Median liegen;
- Veränderungen von `top_holders_pct` beschreiben Konzentration, nicht die Identität des
  Käufers oder Verkäufers;
- `dev_balance_pct` beschreibt eine Balance-Veränderung, nicht deren Mechanismus;
- Missing bleibt Unknown;
- rollierende `stats1h`-Werte werden niemals über Samples summiert;
- Percentage Change und x-fold Growth werden mathematisch getrennt behandelt.

Die gewünschte Ausgabe priorisiert Evidence-Grenze, strukturelle Diagnose,
Current-vs-Median, Cross-Metric-Divergenzen, stärkste Risiken/konstruktive Signale,
Unknowns sowie eine kalibrierte Einschätzung mit Confidence.

### Inspector

`tools/inspect_token_history.py` ist jetzt ein Summary-Proof und erzeugt nur noch:

```text
summary_context.json
report.json
```

Er zeigt zusätzlich die DB-Laufzeit und die Anzahl der internen repräsentativen Samples.
`llm_context.json` sowie adaptive 1m/5m-History wurden entfernt.

### Vorbereitung auf Multi-Token-Vergleich

Der Standalone Summary bleibt bewusst pro Token eigenständig:

```text
Token A -> summary A
Token B -> summary B
Token C -> summary C
Token D -> summary D
              ↓
compact LLM comparison
```

WP5 implementiert noch keinen Multi-Token-Vergleich. Die Modulgrenze erlaubt es später
jedoch, mehrere kleine Summaries zu bündeln, ohne Historien mitzuschicken.

### Visible proof / Stop condition

WP5 ist abgeschlossen, wenn der reale lokale Test bestätigt:

- Summary-Unit-Tests und bestehende Analyst-/Tool-Tests bleiben grün;
- Inspector erzeugt nur `summary_context.json` und `report.json`;
- die DB-Laufzeit ist gegenüber der früheren Full-Payload-Projektion praktisch verbessert;
- der Summary wird ausschließlich für den aktuell ausgewählten Mint geladen;
- an Mistral geht `token + summary`, aber keine History und kein vorgeschalteter Tool-Request;
- der Temporal-Pfad erzeugt genau **einen** Mistral-Request;
- Zeitspanne, Observation-Anzahl und grobe Summary-Größe sind sichtbar;
- die Antwort analysiert Beziehungen, ohne nicht gelieferte Chronologie zu erfinden;
- spätestens nach 45s folgt für diesen einen Mistral-Request eine Antwort oder ein sichtbarer Fehler/Timeout;
- Current Data und Web Research funktionieren unverändert.

## Nicht Teil der funktionalen Foundation

- Bubble Map oder Designumbau;
- persistierte OHLC- oder Langzeit-History-Plattform;
- benutzerdefinierte Zeiträume oder Auflösungen;
- Raw-, Full-, 1m-, 5m- oder 15m-LLM-History-Payloads;
- Multi-Token- oder Cross-Token-History-Vergleich in WP5;
- Prognosen oder automatische Trading-Aktionen;
- Bubble-Größe, Pulsieren, Farbe, Layout oder Physics;
- Datenbank-, Collector- oder Lifecycle-Änderungen;
- automatischer Good/Bad-Score als operative Wahrheit.

Nach WP5 ist kein WP6 vorab definiert. Visual Redesign, zusätzliche interne Analysen und
Discovery Provenance werden erst nach der Browservalidierung neu bewertet.
