# Architecture

## Aktueller Zweck

Das System entdeckt automatisch Solana-Mint-Adressen und aktualisiert diese anschließend über Jupiter Tokens V2 Search.

## Komponenten

```text
Discovery -> mints -> MintCache -> 100er-Batches -> Jupiter Search lanes -> WriteQueue -> PostgreSQL
```

Discovery besteht aus PumpPortal `subscribeNewToken`, Jupiter `/tokens/v2/recent`, Meteora DAMM v2 und Meteora DLMM. Diese Quellen liefern nur Kandidaten-Mints.

Neue Mints starten derzeit mit `priority = 1` und `tracking_enabled = true`. Eine automatische Lifecycle-Logik existiert noch nicht.

Für jeden Jupiter-Search-API-Key läuft eine eigene Lane. `BatchCursor` rotiert durch Batches mit maximal 100 aktiven Mints. Erfolgreiche Antworten werden über `WriteQueue` gebündelt geschrieben.

## Snapshot-Semantik

Pro Mint wird das zuletzt gespeicherte Jupiter-`updatedAt` im Arbeitsspeicher gehalten und beim Start aus PostgreSQL geladen.

```text
updatedAt gleich     -> kein neuer Snapshot
updatedAt verändert  -> Snapshot schreiben
```

Ein Snapshot enthält `mint`, lokales `observed_at` und den vollständigen Jupiter-Payload als JSONB. `updatedAt` bleibt Bestandteil dieses Payloads.

## Datenmodell

`mints` ist die aktuelle Mint-Registry. Primärschlüssel ist `mint`.

`mint_snapshots` ist die Historie geänderter Jupiter-Zustände. Primärschlüssel ist `(mint, observed_at)`.

TimescaleDB, Lifecycle und Timeframe-Aggregation sind noch nicht implementiert.
