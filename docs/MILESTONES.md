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

## Aktiv — WP1 Token Web Research

WP1 beweist den kleinsten LLM-Durchstich:

```text
selected token
      ↓
free question
      ↓
server-side Mistral Conversations API
      ↓
web_search | web_search_premium
      ↓
answer + source references
```

Der Slice enthält ausschließlich:

- `POST /api/analyst`;
- serverseitige Mistral-Konfiguration;
- die bestehende Tokenidentität als Kontext;
- genau ein Built-in Web-Search-Tool;
- ein kleines Prompt-Feld;
- Antwort und Quellen als `EXTERNAL EVIDENCE`;
- `MISTRAL_WEB_SEARCH_MODE` als Backend-Switch.

WP1 ist abgeschlossen, wenn der reale Browserpfad mit beiden Search-Modi geprüft wurde,
der Tool Call nachweisbar ist und fehlende Evidenz nicht durch erfundene Zuordnungen
ersetzt wird.

## Nicht Teil von WP1

- Bubble Map oder Designumbau;
- interne Datenbank-Tools;
- historische Analyse;
- Conversation Memory;
- Streaming;
- persistierte Rechercheergebnisse;
- Provider- oder Tool-Framework;
- SQL-, Python- oder Mutation-Tools;
- Planung des nächsten Slices.

Der nächste Slice wird erst nach der Browservalidierung von WP1 festgelegt.

