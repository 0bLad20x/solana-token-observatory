# Architecture

## Current boundary

Version 0 performs one operation:

```text
Jupiter Tokens V2 response
    -> canonical JSON hash
    -> deduplicated raw observation
    -> PostgreSQL
```

There is no typed snapshot, timeframe, indicator or source combination yet.

## Observation identity

A stored state is identified by:

```text
(mint, payload_hash)
```

The hash is SHA-256 over JSON serialized with sorted object keys and fixed separators.
Object key order therefore does not create a new state, while every value change does.

Jupiter's official Tokens V2 OpenAPI schema describes `updatedAt` only as
"Last data update timestamp". It does not specify that the value is unique, monotonic,
or changed for every field mutation. Therefore:

- `payload_hash` decides content equality;
- `source_updated_at` preserves Jupiter's timestamp as source metadata;
- `first_seen_at` and `last_seen_at` describe local observation time.

Official source:
[Tokens V2 OpenAPI schema](https://github.com/jup-ag/docs/blob/main/openapi-spec/tokens/v2/tokens.yaml)

## Persisted fields and present value

| Field | Why it exists |
|---|---|
| `mint` | Identifies the token whose state was returned. |
| `payload_hash` | Detects exact semantic payload repetition independently of `updatedAt`. |
| `first_seen_at` | Records when this exact state was first received. |
| `last_seen_at` | Records how long Jupiter continued returning this exact state. |
| `source_updated_at` | Preserves Jupiter's optional source timestamp without treating it as identity. |
| `seen_count` | Measures repeated delivery without duplicating the JSONB payload. |
| `payload` | Retains the complete source response for later, evidence-based normalization. |

## Deliberately absent

- `request_id`: no request entity or current query requires it;
- typed snapshot columns: the normalization contract has not been established;
- a second 1:1 table: it would duplicate identity and time fields;
- asynchronous execution: current work is one HTTP request followed by one transaction;
- automatic schema creation during collection: schema changes are an explicit command;
- TimescaleDB: no measured volume or timeframe workload currently requires it;
- deduplication by `updatedAt`: Jupiter documents no sufficient identity guarantee.

## Next decision boundary

Normalization starts only after collected payloads establish which fields are stable,
which fields are states, and which fields are rolling windows. TimescaleDB is evaluated
only after data volume and real query patterns have been measured.
