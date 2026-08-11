# First-Principles DB Optimization

Changed:
- `database.py` (new): single process-wide ConnectionPool owner; deadlock retry lives with DB infrastructure.
- `repository.py`: receives `Database`; persists `first_observed_at` once; collector write/sampling semantics unchanged.
- `lifecycle_queries.py`: uses `first_observed_at`; Rule 2/3 use index-friendly `created_at` windows; no rule semantics changed.
- `lifecycle_clean.py`: Repository and LifecycleQueries share one Database/pool.
- `main.py`: one Database/pool for the whole runtime process.
- `sampling_rate.py`: uses the same central Database abstraction.
- `schema.sql`: adds durable collector fact `first_observed_at`; removes redundant snapshot DESC index; adds low-write partial index for first observation.

Explicitly unchanged:
- `refresh.py`
- `discovery.py`
- `lifecycle_rules.py`
- `config.py`

Important invariants:
1. Search sampling cadence and Round-Robin behaviour are untouched.
2. Rule 1–5 thresholds, time anchors, grace windows, missing-data behaviour and ordering are untouched.
3. `first_observed_at` represents the first snapshot-producing Search observation, matching the old `MIN(mint_snapshots.observed_at)` meaning.
4. No index was added on `last_polled_at`, because that column is updated on every poll and would increase the hot write path.
5. The deadlock retry remains, but is centralized in `database.py`.
