from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from temporal_context import build_temporal_summary, load_temporal_summary_rows


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    return str(value)


def _float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class FrontendReader:
    """Read-only projection of operational token state for the Observatory."""

    def __init__(self, database_url: str, recent_disabled_minutes: int) -> None:
        self._database_url = database_url
        self._recent_disabled_minutes = recent_disabled_minutes
        self._pool = ConnectionPool(
            database_url,
            min_size=1,
            max_size=4,
            open=False,
            kwargs={
                "autocommit": True,
                "options": "-c default_transaction_read_only=on -c statement_timeout=5000",
            },
        )

    def open(self) -> None:
        self._pool.open(wait=True)

    def close(self) -> None:
        self._pool.close()

    def _rows(
        self,
        include_recent_disabled: bool,
        mint: str | None = None,
    ) -> list[dict[str, Any]]:
        params: list[Any] = []
        if include_recent_disabled:
            visibility = """
                (
                    m.tracking_enabled = true
                    OR COALESCE(
                        m.disabled_at,
                        '-infinity'::timestamptz
                    ) >= NOW() - (%s * INTERVAL '1 minute')
                )
            """
            params.append(self._recent_disabled_minutes)
        else:
            visibility = "m.tracking_enabled = true"

        if mint is not None:
            visibility += " AND m.mint = %s"
            params.append(mint)

        query = f"""
            SELECT
                m.mint,
                COALESCE(s.payload->>'name', m.name, '') AS name,
                COALESCE(s.payload->>'symbol', m.symbol, '') AS symbol,
                m.tracking_enabled,
                m.created_at,
                m.first_pool_created_at,
                m.first_observed_at,
                m.last_polled_at,
                m.last_changed_at,
                m.source_updated_at,
                m.disabled_at,
                m.disabled_reason,
                s.observed_at AS snapshot_observed_at,
                COALESCE(NULLIF(s.payload->>'launchpad', ''), 'unknown') AS launchpad,
                NULLIF(s.payload->>'mcap', '')::double precision AS market_cap,
                NULLIF(s.payload->>'liquidity', '')::double precision AS liquidity,
                NULLIF(s.payload->>'holderCount', '')::integer AS holders,
                CASE
                    WHEN NULLIF(s.payload->'stats5m'->>'numBuys', '') IS NULL
                     AND NULLIF(s.payload->'stats5m'->>'numSells', '') IS NULL
                    THEN NULL
                    ELSE COALESCE(NULLIF(s.payload->'stats5m'->>'numBuys', '')::integer, 0)
                       + COALESCE(NULLIF(s.payload->'stats5m'->>'numSells', '')::integer, 0)
                END AS trades_5m,
                NULLIF(s.payload->'stats5m'->>'numTraders', '')::integer AS traders_5m,
                CASE
                    WHEN NULLIF(s.payload->'stats5m'->>'buyVolume', '') IS NULL
                     AND NULLIF(s.payload->'stats5m'->>'sellVolume', '') IS NULL
                    THEN NULL
                    ELSE COALESCE(
                        NULLIF(s.payload->'stats5m'->>'buyVolume', '')::double precision,
                        0
                    ) + COALESCE(
                        NULLIF(s.payload->'stats5m'->>'sellVolume', '')::double precision,
                        0
                    )
                END AS volume_5m,
                EXTRACT(EPOCH FROM (
                    NOW() - COALESCE(
                        m.first_pool_created_at,
                        m.created_at,
                        m.first_observed_at,
                        s.observed_at
                    )
                )) AS age_seconds,
                EXTRACT(EPOCH FROM (NOW() - m.last_polled_at)) AS poll_age_seconds,
                EXTRACT(EPOCH FROM (NOW() - m.last_changed_at)) AS change_age_seconds
            FROM mints AS m
            JOIN LATERAL (
                SELECT observed_at, payload
                FROM mint_snapshots
                WHERE mint = m.mint
                ORDER BY observed_at DESC
                LIMIT 1
            ) AS s ON true
            WHERE {visibility}
            ORDER BY m.mint
        """

        with self._pool.connection() as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(query, tuple(params))
                return list(cursor.fetchall())

    @staticmethod
    def _token(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "mint": row["mint"],
            "name": row["name"] or "",
            "symbol": row["symbol"] or "",
            "launchpad": row["launchpad"] or "unknown",
            "tracking_enabled": bool(row["tracking_enabled"]),
            "market_cap": _float(row["market_cap"]),
            "liquidity": _float(row["liquidity"]),
            "holders": _int(row["holders"]),
            "trades_5m": _int(row["trades_5m"]),
            "traders_5m": _int(row["traders_5m"]),
            "volume_5m": _float(row["volume_5m"]),
            "age_seconds": _float(row["age_seconds"]),
            "poll_age_seconds": _float(row["poll_age_seconds"]),
            "change_age_seconds": _float(row["change_age_seconds"]),
            "last_polled_at": _iso(row["last_polled_at"]),
            "last_changed_at": _iso(row["last_changed_at"]),
            "source_updated_at": row["source_updated_at"],
            "snapshot_observed_at": _iso(row["snapshot_observed_at"]),
            "disabled_at": _iso(row["disabled_at"]),
            "disabled_reason": row["disabled_reason"],
        }

    def snapshot(self, include_recent_disabled: bool = False) -> list[dict[str, Any]]:
        return [self._token(row) for row in self._rows(include_recent_disabled)]

    def token(self, mint: str) -> dict[str, Any] | None:
        rows = self._rows(include_recent_disabled=True, mint=mint)
        return self._token(rows[0]) if rows else None

    def temporal_summary(self, mint: str) -> dict[str, Any] | None:
        """Build the compact 24h summary without loading repeated full snapshot JSON."""

        with psycopg.connect(
            self._database_url,
            row_factory=dict_row,
            autocommit=True,
            options="-c default_transaction_read_only=on -c statement_timeout=60000",
        ) as connection:
            history_rows, sample_rows = load_temporal_summary_rows(connection, mint)
        if not history_rows:
            return None
        return build_temporal_summary(history_rows, sample_rows)
