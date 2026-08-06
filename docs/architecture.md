# Architecture

## Current boundary

Version 0 performs one operation:

```text
Jupiter Tokens V2 response
    -> complete raw payload identity
    -> content identity without updatedAt
    -> deduplicated payload storage
    -> ordered local observation log
```

There is no typed snapshot, timeframe, indicator or source combination yet.

## Two different facts

The collector must preserve two independent facts:

1. which complete payload Jupiter returned;
2. when that payload was observed locally.

A payload and an observation therefore have different identities.

### Payload identity

A stored payload is identified by:

```text
(mint, raw_hash)
```

`raw_hash` is SHA-256 over the complete JSON object, serialized with sorted object
keys and fixed separators. JSON object key order therefore does not create a new
payload, while every returned value change does.

### Observation identity

Every successfully returned token object creates one row in
`jupiter_observations`. Its generated `id` preserves insertion order and its
`observed_at` records the local response time.

Identical payloads are not collapsed into `first_seen_at`, `last_seen_at` and a total
counter. This preserves sequences such as:

```text
A -> A -> B -> A
```

while the JSONB representation of A is stored only once.

## Testing Jupiter updatedAt

Jupiter's official Tokens V2 OpenAPI schema describes `updatedAt` only as
"Last data update timestamp". It does not specify that the value is unique, monotonic,
or changed for every mutation.

The collector therefore records three separate signals:

| Signal | Meaning |
|---|---|
| `observed_at` | When this collector received the token object. |
| `source_updated_at` | Jupiter's optional top-level `updatedAt` value. |
| `raw_hash` | Identity of the complete returned payload, including `updatedAt`. |
| `content_hash` | Identity of the complete returned payload after removing only top-level `updatedAt`. |

The comparison matrix is:

| `source_updated_at` | `content_hash` | Interpretation |
|---|---|---|
| same | same | Jupiter returned the same non-timestamp content. |
| changed | changed | Jupiter timestamp and content changed together. |
| same | changed | `updatedAt` is insufficient as the sole state-change signal. |
| changed | same | `updatedAt` changed without another returned field changing. |

This is an empirical test contract, not an assumption that either outcome is already
proven.

Official source:
[Tokens V2 OpenAPI schema](https://github.com/jup-ag/docs/blob/main/openapi-spec/tokens/v2/tokens.yaml)

## Persisted fields and present value

### `jupiter_payloads`

| Field | Why it exists |
|---|---|
| `mint` | Identifies the token whose payload was returned. |
| `raw_hash` | Deduplicates the complete source payload without trusting `updatedAt`. |
| `content_hash` | Measures content changes independently of `updatedAt`. |
| `source_updated_at` | Preserves Jupiter's timestamp as source metadata. |
| `payload` | Retains the complete source response for later evidence-based normalization. |

### `jupiter_observations`

| Field | Why it exists |
|---|---|
| `id` | Preserves the local order of successful returned observations. |
| `mint` | Supports token-local chronological queries and the payload foreign key. |
| `observed_at` | Records when the collector received this exact response. |
| `raw_hash` | Links the observation to the complete deduplicated payload. |

## Scope of an observation

An observation currently means one valid token object returned by a successful Tokens
V2 response. The current baseline does not persist:

- failed HTTP attempts;
- a requested mint omitted from a successful response;
- HTTP response headers or original JSON bytes.

These are explicit boundaries. A separate request-attempt entity is introduced only if
missing-response or transport-history requirements justify it.

## Deliberately absent

- `request_id`: no persisted request-attempt entity currently requires it;
- typed snapshot columns: the normalization contract has not been established;
- asynchronous execution: current work is one HTTP request followed by one transaction;
- automatic schema creation during collection: schema changes are an explicit command;
- TimescaleDB: no measured volume or timeframe workload currently requires it;
- deduplication by `updatedAt`: Jupiter documents no sufficient identity guarantee.

## Next decision boundary

Collect enough ordered observations to compare `source_updated_at` with `content_hash`.
Only that evidence can determine whether `updatedAt` is a sufficient long-term change
signal or whether content hashing must remain part of the production contract.
Normalization and TimescaleDB remain later, independent decisions.
