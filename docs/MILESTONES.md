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

## Aktiv — WP4 Volume Activity Deltas

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

## Nicht Teil von WP4

- Bubble Map oder Designumbau;
- historische Analyse;
- Bubble-Größe, Pulsieren, Farbe, Layout oder Physics;
- Price-Change-Proxies;
- Datenbank-, Collector- oder Lifecycle-Änderungen.

Der nächste Slice wird erst nach der Browservalidierung von WP4 festgelegt.
