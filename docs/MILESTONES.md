# Milestones

## Zweck

Dieses Dokument nennt den aktuellen Projektstand und genau den aktiven nächsten Slice.
Detailverträge bleiben in Code, `docs/architecture.md`, `docs/LIFECYCLE_CONTRACT.md` und
`docs/FRONTEND_OBSERVATORY.md`.

## Operative Foundation — abgeschlossen

Die operative Basis steht:

- Discovery aus mehreren Solana-Quellen;
- Jupiter Search Monitoring;
- PostgreSQL-Registry und immutable `mint_snapshots`;
- 24h Raw-Buffer-Retention für `mint_snapshots`;
- Operational Lifecycle v0.1;
- read-only Observatory als Downstream-Consumer.

## Observatory Functional Proofs — abgeschlossen

Die bisherigen vertikalen Slices haben die funktionale Basis bewiesen:

| Slice | Ergebnis |
|---|---|
| V0–V2 | read-only Observatory, aktuelle Population, SSE add/update/retire |
| WP1 / PR #10 | exact-Mint Web Research mit externer Evidenz |
| WP2 / PR #11 | bounded `query_tokens` für aktuelle Population |
| WP3 / PR #12 | Mint/Symbol/Name Search + gemeinsame Selection |
| WP4 / PR #13 | kompakte 60s Volume-Activity-Projektion |
| Temporal Research / PR #16 | Deep-History-Proof; als Produktpfad verworfen |
| WP5 / PR #19 | kompakter Temporal Summary + genau ein Mistral-Request |

WP5 ist abgeschlossen und auf `main` gemergt. Der normale Temporal-Pfad sendet keine
Raw-History und keine 1m/5m/15m-Time-Buckets an das LLM.

## Aktiv — Issue #20 Observatory Functional Core Consolidation

Issue #20 trennt den bereits funktionierenden Observatory-Kern von allen aktuellen
Darstellungsentscheidungen.

```text
Operational Core
      ↓
read-only backend
      ↓
Browser Data IO
      ↓
Functional Core
population + selected Mint + live event apply
      ↓
Search / Activity / Analyst / Current View
```

Der aktuelle Bubble-/Physics-Stand ist **kein** Kompatibilitätsvertrag. Für den Refactor
wird er durch einen kleinen deterministischen Proof-View ersetzt, wenn das die
Verantwortungsgrenzen sauberer macht.

### Harte Grenze

Der funktionale Kern darf Domain-Fakten enthalten, aber keine Presentation Truth:

```text
allowed:
mint, market_cap, liquidity, holders, launchpad, timestamps,
trading activity, tracking state, selected Mint, live events

not core truth:
x/y, radius, color, alpha, stroke, cluster position,
Pixi objects, D3 forces, panel position, Bubble semantics
```

Search bleibt vollständiger Zugriff auf die aktive Population und ist unabhängig von der
konkreten View. Selection gehört der Anwendung und nicht einem Bubble Node, einer Zeile
oder einem Analyst-Ergebnis.

### Verantwortlichkeiten nach dem Slice

```text
app.js          composition / wiring
api.js          browser HTTP + SSE
state.js        population + selection + event application
search.js       pure token search/ranking
activity.js     WP4 derived live signal
token-ui.js     Search + Inspector DOM
activity-ui.js  Activity Feed DOM
analyst-ui.js   current Analyst workspace DOM
views/*         konkrete, austauschbare Darstellung
```

Backendseitig besitzt `src/observatory/delta.py` den kanonischen SSE-Delta-Vertrag.
Fingerprint und numerische Changes teilen dieselbe Feldliste, einschließlich
`trades_5m`.

### Stop Condition

Issue #20 ist erst abgeschlossen, wenn lokal im realen Browser bewiesen ist:

- Bootstrap aus `/api/universe`;
- beliebiger aktiver Mint/Symbol/Name über Search erreichbar;
- gemeinsame Selection funktioniert aus Search, Current View, Activity und Analyst;
- Inspector folgt Selection und Live Updates;
- SSE `token_added`, `token_updated`, `token_retired` bleibt korrekt;
- WP4 Activity bleibt korrekt;
- Current Data bleibt funktionsfähig;
- Web Research bleibt funktionsfähig;
- Temporal Summary bleibt funktionsfähig;
- keine operative Mutation;
- der konkrete View kann ausgetauscht werden, ohne Search/Selection/Inspector/Analyst zu ändern.

## Nach Issue #20 — Evidence Readiness vor Design

Nach dem Functional-Core-Refactor wird **nicht direkt** mit dem visuellen Redesign
begonnen.

Zuerst wird geprüft, welche Evidenz und Relationen der zukünftige Observatory-Kern
wahrheitsgemäß anbieten soll.

Mindestens zu klären:

1. **RugCheck / Safety Evidence — Issue #18**  
   Exact-Mint Token Report als getrennte externe Evidenz, ohne ihn zu Jupiter System Truth
   oder Lifecycle Evidence umzudeuten.

2. **Discovery Provenance**  
   Persistenter/read-only Vertrag für Discovery Source → Mint → Jupiter Observation, falls
   zukünftige Flow-/Tunnel-Views diese Beziehungen darstellen sollen.

3. **Bounded Comparison / zusätzliche Evidence**  
   Nur aus konkreten Benutzerfragen ableiten, ob Multi-Mint-Vergleich, zusätzliche
   deterministische Summaries oder weitere Source-Metadaten benötigt werden.

## Danach — Issue #9 Visual / Spatial Research

Erst wenn der funktionale Kern und die benötigten Evidence-Grenzen klar sind, wird Issue
#9 aktiviert.

Dann werden Designfragen aus analytischen Fragen abgeleitet:

- welche Frage beantwortet eine View;
- welche Datenfelder werden auf Position, Größe, Farbe, Opacity oder Text gemappt;
- Missing/Outlier-/Scale-Regeln;
- Density, Zoom und Aggregation;
- reale Populationen und Browser-Prototypen.

Keine heutige Bubble-, Farb-, Cluster- oder Panel-Semantik wird vorab als zukünftiger
Designvertrag behandelt.
