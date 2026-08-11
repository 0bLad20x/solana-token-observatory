from __future__ import annotations

from typing import Any

from psycopg.rows import dict_row

from database import Database


class LifecycleQueries:
    """Read only the evidence needed by lifecycle rules."""

    def __init__(self, database: Database) -> None:
        self._db = database

    def _fetchall(
        self,
        query: str,
        params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        with self._db.connection() as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                return cursor.execute(query, params).fetchall()

    def _fetchone(
        self,
        query: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self._db.connection() as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                return cursor.execute(query, params).fetchone()

    def fetch_mature_active_state(
        self,
        observation_seconds: float,
    ) -> list[dict[str, Any]]:
        query = """
            SELECT
                m.mint,
                m.last_polled_at,
                latest.payload
            FROM mints m
            JOIN LATERAL (
                SELECT s.payload
                FROM mint_snapshots s
                WHERE s.mint = m.mint
                ORDER BY s.observed_at DESC
                LIMIT 1
            ) latest ON true
            WHERE m.tracking_enabled = true
              AND m.first_observed_at IS NOT NULL
              AND m.first_observed_at <= CURRENT_TIMESTAMP
                    - (%(observation_seconds)s * INTERVAL '1 second')
        """
        return self._fetchall(
            query,
            {"observation_seconds": observation_seconds},
        )

    def fetch_startup_health(self) -> dict[str, Any]:
        """Visibility only; does not participate in lifecycle decisions."""
        query = """
            SELECT
                COUNT(*) AS active_total,
                COUNT(first_observed_at) AS active_with_snapshot,
                MIN(first_observed_at) AS oldest_snapshot_at
            FROM mints
            WHERE tracking_enabled = true
        """
        return self._fetchone(query)

    def fetch_continuation_checkpoint(
        self,
        checkpoint_minutes: int,
        signal_start_minutes: int,
        grace_seconds: float,
        max_poll_lag_seconds: float,
    ) -> list[dict[str, Any]]:
        query = """
            SELECT
                m.mint,
                decision.payload,
                (
                    SELECT COUNT(*)
                    FROM mint_snapshots x
                    WHERE x.mint = m.mint
                      AND x.observed_at >
                          m.created_at
                          + (%(signal_start_minutes)s * INTERVAL '1 minute')
                      AND x.observed_at <=
                          m.created_at
                          + (%(checkpoint_minutes)s * INTERVAL '1 minute')
                ) AS changes_in_window
            FROM mints m
            JOIN LATERAL (
                SELECT s.payload
                FROM mint_snapshots s
                WHERE s.mint = m.mint
                  AND s.observed_at <=
                      m.created_at
                      + (%(checkpoint_minutes)s * INTERVAL '1 minute')
                ORDER BY s.observed_at DESC
                LIMIT 1
            ) decision ON true
            WHERE m.tracking_enabled = true
              AND m.created_at IS NOT NULL
              AND m.first_observed_at IS NOT NULL
              AND m.first_observed_at <=
                  m.created_at
                  + (%(signal_start_minutes)s * INTERVAL '1 minute')
              AND m.created_at >
                  CURRENT_TIMESTAMP
                  - (%(checkpoint_minutes)s * INTERVAL '1 minute')
                  - (%(grace_seconds)s * INTERVAL '1 second')
              AND m.created_at <=
                  CURRENT_TIMESTAMP
                  - (%(checkpoint_minutes)s * INTERVAL '1 minute')
              AND m.last_polled_at IS NOT NULL
              AND m.last_polled_at >=
                  m.created_at
                  + (%(checkpoint_minutes)s * INTERVAL '1 minute')
              AND m.last_polled_at >=
                  CURRENT_TIMESTAMP
                  - (%(max_poll_lag_seconds)s * INTERVAL '1 second')
            ORDER BY m.mint
        """
        return self._fetchall(
            query,
            {
                "checkpoint_minutes": checkpoint_minutes,
                "signal_start_minutes": signal_start_minutes,
                "grace_seconds": grace_seconds,
                "max_poll_lag_seconds": max_poll_lag_seconds,
            },
        )

    def fetch_economic_presence_checkpoint(
        self,
        checkpoint_minutes: int,
        grace_seconds: float,
        max_poll_lag_seconds: float,
    ) -> list[dict[str, Any]]:
        query = """
            SELECT
                m.mint,
                EXISTS (
                    SELECT 1
                    FROM mint_snapshots x
                    WHERE x.mint = m.mint
                      AND x.observed_at <= CURRENT_TIMESTAMP
                      AND (
                          NULLIF(BTRIM(x.payload->>'mcap'), '') IS NOT NULL
                          OR NULLIF(BTRIM(x.payload->>'liquidity'), '') IS NOT NULL
                      )
                ) AS has_economic_data
            FROM mints m
            WHERE m.tracking_enabled = true
              AND m.created_at IS NOT NULL
              AND m.first_observed_at IS NOT NULL
              AND m.first_observed_at <=
                  m.created_at
                  + (%(checkpoint_minutes)s * INTERVAL '1 minute')
              AND m.created_at >
                  CURRENT_TIMESTAMP
                  - (%(checkpoint_minutes)s * INTERVAL '1 minute')
                  - (%(grace_seconds)s * INTERVAL '1 second')
              AND m.created_at <=
                  CURRENT_TIMESTAMP
                  - (%(checkpoint_minutes)s * INTERVAL '1 minute')
              AND m.last_polled_at IS NOT NULL
              AND m.last_polled_at >=
                  m.created_at
                  + (%(checkpoint_minutes)s * INTERVAL '1 minute')
              AND m.last_polled_at >=
                  CURRENT_TIMESTAMP
                  - (%(max_poll_lag_seconds)s * INTERVAL '1 second')
              AND m.last_polled_at > m.first_observed_at
            ORDER BY m.mint
        """
        return self._fetchall(
            query,
            {
                "checkpoint_minutes": checkpoint_minutes,
                "grace_seconds": grace_seconds,
                "max_poll_lag_seconds": max_poll_lag_seconds,
            },
        )

    def fetch_threshold_scan(
        self,
        rule_key: str,
        field: str,
        threshold: float,
        min_age_minutes: int,
        max_poll_lag_seconds: float,
    ) -> list[dict[str, Any]]:
        """Scan only snapshots newer than the rule's clean checkpoint."""
        query = """
            SELECT
                m.mint,
                scan.scanned_through,
                scan.crossing_at
            FROM mints m
            LEFT JOIN lifecycle_rule_state state
              ON state.mint = m.mint
             AND state.rule_key = %(rule_key)s
            JOIN LATERAL (
                SELECT
                    MAX(s.observed_at) AS scanned_through,
                    MIN(s.observed_at) FILTER (
                        WHERE NULLIF(BTRIM(s.payload ->> %(field)s), '') IS NOT NULL
                          AND NULLIF(BTRIM(s.payload ->> %(field)s), '')::float8
                              < %(threshold)s
                    ) AS crossing_at
                FROM mint_snapshots s
                WHERE s.mint = m.mint
                  AND s.observed_at > COALESCE(
                      state.scanned_through,
                      m.created_at
                          + (%(min_age_minutes)s * INTERVAL '1 minute')
                          - INTERVAL '1 microsecond'
                  )
            ) scan ON true
            WHERE m.tracking_enabled = true
              AND m.created_at IS NOT NULL
              AND m.created_at <=
                  CURRENT_TIMESTAMP
                  - (%(min_age_minutes)s * INTERVAL '1 minute')
              AND m.last_polled_at IS NOT NULL
              AND m.last_polled_at >=
                  CURRENT_TIMESTAMP
                  - (%(max_poll_lag_seconds)s * INTERVAL '1 second')
              AND scan.scanned_through IS NOT NULL
            ORDER BY m.mint
        """
        return self._fetchall(
            query,
            {
                "rule_key": rule_key,
                "field": field,
                "threshold": threshold,
                "min_age_minutes": min_age_minutes,
                "max_poll_lag_seconds": max_poll_lag_seconds,
            },
        )

    def advance_threshold_scan(
        self,
        rule_key: str,
        rows: list[dict[str, Any]],
    ) -> None:
        """Advance clean scan cursors monotonically over immutable snapshots."""
        if not rows:
            return

        query = """
            WITH progress AS (
                SELECT * FROM unnest(
                    %(mints)s::text[],
                    %(scanned_through)s::timestamptz[]
                ) AS p(mint, scanned_through)
            )
            INSERT INTO lifecycle_rule_state (mint, rule_key, scanned_through)
            SELECT p.mint, %(rule_key)s, p.scanned_through
            FROM progress p
            JOIN mints m ON m.mint = p.mint
            WHERE m.tracking_enabled = true
            ON CONFLICT (mint, rule_key) DO UPDATE SET
                scanned_through = GREATEST(
                    lifecycle_rule_state.scanned_through,
                    EXCLUDED.scanned_through
                )
        """

        with self._db.connection() as connection:
            connection.execute(
                query,
                {
                    "rule_key": rule_key,
                    "mints": [row["mint"] for row in rows],
                    "scanned_through": [row["scanned_through"] for row in rows],
                },
            )
            connection.commit()