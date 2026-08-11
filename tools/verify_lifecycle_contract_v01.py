from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from psycopg.rows import dict_row

from config import Settings
from database import Database
from lifecycle_queries import LifecycleQueries
from lifecycle_rules import (
    COLLAPSE_GRACE_MINUTES,
    COLLAPSE_RULES,
    OBSERVATION_MINUTES,
    RULE2_CHECKPOINT_GRACE_SECONDS,
    RULE2_CHECKPOINT_MINUTES,
    RULE3_CHECKPOINT_GRACE_SECONDS,
    RULE3_CHECKPOINT_MINUTES,
    classify_rule1,
    classify_rule2,
    classify_rule3,
)


REFERENCE_RULE1_MAX_POLL_LAG_SECONDS = 60.0
REFERENCE_RULE2_MAX_CHANGES = 10
REFERENCE_RULE2_ESTABLISHED_MCAP = 50_000.0
REFERENCE_RULE2_ESTABLISHED_LIQUIDITY = 5_000.0

REFERENCE_COLLAPSE_RULES = (
    ("rule4", "liquidity", 2_000.0, "liquidity_collapse_below_2000"),
    ("rule5", "mcap", 2_000.0, "mcap_collapse_below_2000"),
)

RULE_KEYS = ("rule1", "rule2", "rule3", "rule4", "rule5")


class SnapshotQueries(LifecycleQueries):
    """Run current LifecycleQueries against one repeatable-read snapshot."""

    def __init__(self, connection: Any) -> None:
        self._connection = connection

    def _fetchall(
        self,
        query: str,
        params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        with self._connection.cursor(row_factory=dict_row) as cursor:
            return cursor.execute(query, params).fetchall()


def _as_float(payload: dict[str, Any], key: str) -> float | None:
    raw = payload.get(key)
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    text = str(raw).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _as_int(payload: dict[str, Any], key: str) -> int | None:
    value = _as_float(payload, key)
    return int(value) if value is not None else None


def _reference_classify_rule1(payload: dict[str, Any]) -> str | None:
    liquidity = _as_float(payload, "liquidity")
    mcap = _as_float(payload, "mcap")
    holders = _as_int(payload, "holderCount")

    low_liquidity = liquidity is not None and liquidity < 1_000.0
    low_mcap_and_holders = (
        mcap is not None
        and mcap < 3_000.0
        and holders is not None
        and holders < 300
    )

    if low_liquidity and low_mcap_and_holders:
        return (
            "liquidity_below_1000_and_"
            "mcap_below_3000_and_holders_below_300"
        )
    if low_liquidity:
        return "liquidity_below_1000"
    if low_mcap_and_holders:
        return "mcap_below_3000_and_holders_below_300"
    return None


def _reference_classify_rule2(
    payload: dict[str, Any],
    changes_in_window: int,
) -> str | None:
    mcap = _as_float(payload, "mcap")
    liquidity = _as_float(payload, "liquidity")

    if mcap is None or liquidity is None:
        return None
    if (
        mcap >= REFERENCE_RULE2_ESTABLISHED_MCAP
        and liquidity >= REFERENCE_RULE2_ESTABLISHED_LIQUIDITY
    ):
        return None
    if changes_in_window <= REFERENCE_RULE2_MAX_CHANGES:
        return "early_continuation_failure"
    return None


def _reference_classify_rule3(has_economic_data: bool) -> str | None:
    if has_economic_data:
        return None
    return "economic_data_missing_at_5m"


def _fetchall(
    connection: Any,
    query: str,
    params: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    with connection.cursor(row_factory=dict_row) as cursor:
        return cursor.execute(query, params).fetchall()


def _current_candidates(
    queries: SnapshotQueries,
    now: datetime,
) -> dict[str, set[tuple[str, str]]]:
    result: dict[str, set[tuple[str, str]]] = {
        key: set() for key in RULE_KEYS
    }
    already_flagged: set[str] = set()

    for row in queries.fetch_mature_active_state(OBSERVATION_MINUTES * 60):
        last_polled_at = row["last_polled_at"]
        if last_polled_at is None:
            continue
        if (
            now - last_polled_at
        ).total_seconds() > REFERENCE_RULE1_MAX_POLL_LAG_SECONDS:
            continue

        reason = classify_rule1(row["payload"])
        if reason is not None:
            result["rule1"].add((row["mint"], reason))

    already_flagged.update(mint for mint, _reason in result["rule1"])

    for row in queries.fetch_continuation_checkpoint(
        checkpoint_minutes=RULE2_CHECKPOINT_MINUTES,
        signal_start_minutes=OBSERVATION_MINUTES,
        grace_seconds=RULE2_CHECKPOINT_GRACE_SECONDS,
    ):
        if row["mint"] in already_flagged:
            continue

        reason = classify_rule2(
            row["payload"],
            row["changes_in_window"],
        )
        if reason is not None:
            result["rule2"].add((row["mint"], reason))

    already_flagged.update(mint for mint, _reason in result["rule2"])

    for row in queries.fetch_economic_presence_checkpoint(
        checkpoint_minutes=RULE3_CHECKPOINT_MINUTES,
        grace_seconds=RULE3_CHECKPOINT_GRACE_SECONDS,
    ):
        if row["mint"] in already_flagged:
            continue

        reason = classify_rule3(row["has_economic_data"])
        if reason is not None:
            result["rule3"].add((row["mint"], reason))

    already_flagged.update(mint for mint, _reason in result["rule3"])

    for rule in COLLAPSE_RULES:
        for row in queries.fetch_threshold_scan(
            rule_key=rule.key,
            field=rule.field,
            threshold=rule.floor,
            min_age_minutes=COLLAPSE_GRACE_MINUTES,
        ):
            if (
                row["crossing_at"] is not None
                and row["mint"] not in already_flagged
            ):
                result[rule.key].add((row["mint"], rule.reason))

        already_flagged.update(
            mint for mint, _reason in result[rule.key]
        )

    return result


def _reference_rule1(
    connection: Any,
    now: datetime,
) -> list[dict[str, Any]]:
    rows = _fetchall(
        connection,
        """
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
          AND m.first_observed_at <= CURRENT_TIMESTAMP - INTERVAL '10 minutes'
        """,
    )

    result = []
    for row in rows:
        last_polled_at = row["last_polled_at"]
        if last_polled_at is None:
            continue
        if (
            now - last_polled_at
        ).total_seconds() > REFERENCE_RULE1_MAX_POLL_LAG_SECONDS:
            continue
        result.append(row)
    return result


def _reference_rule2(connection: Any) -> list[dict[str, Any]]:
    return _fetchall(
        connection,
        """
        SELECT
            m.mint,
            decision.payload,
            (
                SELECT COUNT(*)
                FROM mint_snapshots x
                WHERE x.mint = m.mint
                  AND x.observed_at > m.created_at + INTERVAL '10 minutes'
                  AND x.observed_at <= m.created_at + INTERVAL '30 minutes'
            ) AS changes_in_window
        FROM mints m
        JOIN LATERAL (
            SELECT s.payload
            FROM mint_snapshots s
            WHERE s.mint = m.mint
              AND s.observed_at <= m.created_at + INTERVAL '30 minutes'
            ORDER BY s.observed_at DESC
            LIMIT 1
        ) decision ON true
        WHERE m.tracking_enabled = true
          AND m.created_at IS NOT NULL
          AND m.first_observed_at IS NOT NULL
          AND m.first_observed_at <= m.created_at + INTERVAL '10 minutes'
          AND m.created_at > CURRENT_TIMESTAMP - INTERVAL '31 minutes'
          AND m.created_at <= CURRENT_TIMESTAMP - INTERVAL '30 minutes'
          AND m.last_polled_at IS NOT NULL
          AND m.last_polled_at >= m.created_at + INTERVAL '30 minutes'
        ORDER BY m.mint
        """,
    )


def _reference_rule3(connection: Any) -> list[dict[str, Any]]:
    return _fetchall(
        connection,
        """
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
          AND m.first_observed_at <= m.created_at + INTERVAL '5 minutes'
          AND m.created_at > CURRENT_TIMESTAMP - INTERVAL '6 minutes'
          AND m.created_at <= CURRENT_TIMESTAMP - INTERVAL '5 minutes'
          AND m.last_polled_at IS NOT NULL
          AND m.last_polled_at >= m.created_at + INTERVAL '5 minutes'
        ORDER BY m.mint
        """,
    )


def _reference_threshold_scan(
    connection: Any,
    rule_key: str,
    field: str,
    threshold: float,
) -> list[dict[str, Any]]:
    return _fetchall(
        connection,
        """
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
                    WHERE NULLIF(
                        BTRIM(s.payload ->> %(field)s),
                        ''
                    ) IS NOT NULL
                      AND NULLIF(
                          BTRIM(s.payload ->> %(field)s),
                          ''
                      )::float8 < %(threshold)s
                ) AS crossing_at
            FROM mint_snapshots s
            WHERE s.mint = m.mint
              AND s.observed_at > COALESCE(
                  state.scanned_through,
                  m.created_at
                      + INTERVAL '30 minutes'
                      - INTERVAL '1 microsecond'
              )
        ) scan ON true
        WHERE m.tracking_enabled = true
          AND m.created_at IS NOT NULL
          AND m.created_at <= CURRENT_TIMESTAMP - INTERVAL '30 minutes'
          AND scan.scanned_through IS NOT NULL
        ORDER BY m.mint
        """,
        {
            "rule_key": rule_key,
            "field": field,
            "threshold": threshold,
        },
    )


def _reference_candidates(
    connection: Any,
    now: datetime,
) -> dict[str, set[tuple[str, str]]]:
    result: dict[str, set[tuple[str, str]]] = {
        key: set() for key in RULE_KEYS
    }
    already_flagged: set[str] = set()

    for row in _reference_rule1(connection, now):
        reason = _reference_classify_rule1(row["payload"])
        if reason is not None:
            result["rule1"].add((row["mint"], reason))

    already_flagged.update(mint for mint, _reason in result["rule1"])

    for row in _reference_rule2(connection):
        if row["mint"] in already_flagged:
            continue

        reason = _reference_classify_rule2(
            row["payload"],
            row["changes_in_window"],
        )
        if reason is not None:
            result["rule2"].add((row["mint"], reason))

    already_flagged.update(mint for mint, _reason in result["rule2"])

    for row in _reference_rule3(connection):
        if row["mint"] in already_flagged:
            continue

        reason = _reference_classify_rule3(row["has_economic_data"])
        if reason is not None:
            result["rule3"].add((row["mint"], reason))

    already_flagged.update(mint for mint, _reason in result["rule3"])

    for rule_key, field, threshold, reason in REFERENCE_COLLAPSE_RULES:
        for row in _reference_threshold_scan(
            connection,
            rule_key=rule_key,
            field=field,
            threshold=threshold,
        ):
            if (
                row["crossing_at"] is not None
                and row["mint"] not in already_flagged
            ):
                result[rule_key].add((row["mint"], reason))

        already_flagged.update(
            mint for mint, _reason in result[rule_key]
        )

    return result


def _print_diff(
    rule_key: str,
    current: set[tuple[str, str]],
    reference: set[tuple[str, str]],
) -> bool:
    if current == reference:
        print(f"PASS {rule_key}: {len(current)} candidates")
        return True

    only_current = sorted(current - reference)
    only_reference = sorted(reference - current)

    print(
        f"FAIL {rule_key}: "
        f"current={len(current)} reference={len(reference)}"
    )

    if only_current:
        print("  only current:")
        for mint, reason in only_current[:20]:
            print(f"    {mint} | {reason}")
        if len(only_current) > 20:
            print(f"    ... +{len(only_current) - 20}")

    if only_reference:
        print("  only v0.1 reference:")
        for mint, reason in only_reference[:20]:
            print(f"    {mint} | {reason}")
        if len(only_reference) > 20:
            print(f"    ... +{len(only_reference) - 20}")

    return False


def main() -> int:
    settings = Settings.from_env()

    with Database(settings.database_url) as database:
        with database.connection() as connection:
            connection.execute(
                "BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
            )
            try:
                transaction_now = connection.execute(
                    "SELECT CURRENT_TIMESTAMP"
                ).fetchone()[0]

                queries = SnapshotQueries(connection)
                current = _current_candidates(
                    queries,
                    now=transaction_now,
                )
                reference = _reference_candidates(
                    connection,
                    now=transaction_now,
                )

                checks = [
                    _print_diff(
                        rule_key,
                        current[rule_key],
                        reference[rule_key],
                    )
                    for rule_key in RULE_KEYS
                ]
                passed = all(checks)
            finally:
                connection.rollback()

    if passed:
        print("LIFECYCLE CONTRACT v0.1: EQUIVALENT")
        return 0

    print("LIFECYCLE CONTRACT v0.1: SEMANTIC DRIFT")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
