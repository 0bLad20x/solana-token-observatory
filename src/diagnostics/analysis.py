from __future__ import annotations

import bisect
import math
from datetime import datetime, timezone
from typing import Any

from .constants import (
    AGE_DISTRIBUTION_BUCKETS,
    CATEGORY_SPECS,
    JOINT_DENSITY_X_BINS,
    JOINT_DENSITY_Y_BINS,
    LIQUIDITY_DISTRIBUTION_THRESHOLDS,
    MCAP_DISTRIBUTION_THRESHOLDS,
    SAMPLE_LIMIT,
)

def _sample_row(mint, payload, observed_at, created_at, unchanged_since, last_polled_at, now) -> dict:
    first_pool = payload.get("firstPool") or {}
    stats24h = payload.get("stats24h") or {}
    stats1h = payload.get("stats1h") or {}
    unchanged_min = (
        (last_polled_at - unchanged_since).total_seconds() / 60 if unchanged_since else 0.0
    )

    mcap = payload.get("mcap")
    liquidity = payload.get("liquidity")
    holders = payload.get("holderCount")

    mcap_to_liquidity_ratio = mcap / liquidity if mcap is not None and liquidity else None
    mcap_per_holder = mcap / holders if mcap is not None and holders else None
    liquidity_per_holder = liquidity / holders if liquidity is not None and holders else None

    return {
        "mint": mint,
        "name": payload.get("name"),
        "symbol": payload.get("symbol"),
        "launchpad": payload.get("launchpad"),
        "token_created_at": created_at.isoformat() if created_at else None,
        "first_pool_created_at": first_pool.get("createdAt"),
        "graduated_at": payload.get("graduatedAt"),
        "latest_observed_at": observed_at.isoformat(),
        "minutes_since_latest_snapshot": round((now - observed_at).total_seconds() / 60, 1),
        "unchanged_min": round(unchanged_min, 1),
        "liquidity": liquidity,
        "holders": holders,
        "mcap": mcap,
        "mcap_to_liquidity_ratio": round(mcap_to_liquidity_ratio, 1) if mcap_to_liquidity_ratio is not None else None,
        "mcap_per_holder": round(mcap_per_holder, 2) if mcap_per_holder is not None else None,
        "liquidity_per_holder": round(liquidity_per_holder, 2) if liquidity_per_holder is not None else None,
        "stats1h_numBuys": stats1h.get("numBuys"),
        "stats1h_numSells": stats1h.get("numSells"),
        "stats24h_priceChange": stats24h.get("priceChange"),
        "stats24h_holderChange": stats24h.get("holderChange"),
        "stats24h_liquidityChange": stats24h.get("liquidityChange"),
        "stats24h_volumeChange": stats24h.get("volumeChange"),
    }


def run_categories(connection) -> list[dict]:
    """Alle 13 Counts in einem Scan; alle Samples in einem SQL-Roundtrip."""
    count_sql = "SELECT\n" + ",\n".join(
        f"COUNT(*) FILTER (WHERE {where_sql}) AS c{i}"
        for i, (_, where_sql, _) in enumerate(CATEGORY_SPECS)
    ) + "\nFROM diag_latest"

    counts = connection.execute(count_sql).fetchone()

    sample_queries = []
    for i, (name, where_sql, order_by_sql) in enumerate(CATEGORY_SPECS):
        safe_name = name.replace("'", "''")
        sample_queries.append(
            f"""
            (
                SELECT
                    {i} AS category_order,
                    '{safe_name}' AS category_name,
                    mint, payload, observed_at, created_at, unchanged_since, last_polled_at
                FROM diag_latest
                WHERE {where_sql}
                ORDER BY {order_by_sql}
                LIMIT {SAMPLE_LIMIT}
            )
            """
        )

    rows = connection.execute(
        "\nUNION ALL\n".join(sample_queries) + "\nORDER BY category_order"
    ).fetchall()

    now = datetime.now(timezone.utc)
    samples_by_name = {name: [] for name, _, _ in CATEGORY_SPECS}
    for _, name, mint, payload, observed_at, created_at, unchanged_since, last_polled_at in rows:
        samples_by_name[name].append(
            _sample_row(
                mint,
                payload,
                observed_at,
                created_at,
                unchanged_since,
                last_polled_at,
                now,
            )
        )

    return [
        {
            "category": name,
            "total_count": counts[i],
            "samples": samples_by_name[name],
        }
        for i, (name, _, _) in enumerate(CATEGORY_SPECS)
    ]


def overlap_analysis(connection) -> dict:
    liq_low, price_crashed, both_true = connection.execute(
        """
        SELECT
            COUNT(*) FILTER (WHERE has_liquidity AND liquidity < 0.01),
            COUNT(*) FILTER (WHERE has_stats24h_price_change AND stats24h_price_change <= -99),
            COUNT(*) FILTER (
                WHERE has_liquidity AND liquidity < 0.01
                  AND has_stats24h_price_change AND stats24h_price_change <= -99
            )
        FROM diag_latest
        """
    ).fetchone()
    return {
        "liquidity_below_0_01_count": liq_low,
        "price_crashed_count": price_crashed,
        "both_count": both_true,
        "only_liquidity_low": liq_low - both_true,
        "only_price_crashed": price_crashed - both_true,
    }


def liquidity_bucket_vs_price_change(connection) -> list[dict]:
    rows = connection.execute(
        """
        SELECT bucket_label, bucket_order, COUNT(*),
               ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY stats24h_price_change)::numeric, 2)
        FROM (
            SELECT stats24h_price_change,
                CASE
                    WHEN liquidity < 0.000001 THEN '<$0.000001'
                    WHEN liquidity < 0.0001 THEN '$0.000001-0.0001'
                    WHEN liquidity < 0.001 THEN '$0.0001-0.001'
                    WHEN liquidity < 0.01 THEN '$0.001-0.01'
                    WHEN liquidity < 0.1 THEN '$0.01-0.1'
                    WHEN liquidity < 1 THEN '$0.1-1'
                    WHEN liquidity < 10 THEN '$1-10'
                    WHEN liquidity < 100 THEN '$10-100'
                    WHEN liquidity < 1000 THEN '$100-1000'
                    WHEN liquidity < 10000 THEN '$1000-10000'
                    ELSE '>=$10000'
                END AS bucket_label,
                CASE
                    WHEN liquidity < 0.000001 THEN 0
                    WHEN liquidity < 0.0001 THEN 1
                    WHEN liquidity < 0.001 THEN 2
                    WHEN liquidity < 0.01 THEN 3
                    WHEN liquidity < 0.1 THEN 4
                    WHEN liquidity < 1 THEN 5
                    WHEN liquidity < 10 THEN 6
                    WHEN liquidity < 100 THEN 7
                    WHEN liquidity < 1000 THEN 8
                    WHEN liquidity < 10000 THEN 9
                    ELSE 10
                END AS bucket_order
            FROM diag_latest
            WHERE has_liquidity AND has_stats24h_price_change
        ) AS b
        GROUP BY bucket_label, bucket_order
        ORDER BY bucket_order
        """
    ).fetchall()
    return [
        {
            "liquidity_bucket": label,
            "count": count,
            "median_price_change_pct": float(median) if median is not None else None,
        }
        for label, _, count, median in rows
    ]


def null_launchpad_by_age(connection) -> list[dict]:
    rows = connection.execute(
        """
        SELECT
            CASE
                WHEN created_at IS NULL THEN 'unbekannt'
                WHEN created_at > now() - interval '1 hour' THEN 'age<1h'
                WHEN created_at > now() - interval '24 hours' THEN 'age<24h'
                WHEN created_at > now() - interval '30 days' THEN 'age<30d'
                ELSE 'age>=30d'
            END AS age_bucket,
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE has_liquidity AND liquidity < 0.01) AS crashed
        FROM diag_latest
        WHERE launchpad IS NULL
        GROUP BY 1
        ORDER BY 1
        """
    ).fetchall()
    return [
        {"age_bucket": bucket, "total": total, "crashed": crashed}
        for bucket, total, crashed in rows
    ]


def null_launchpad_pool_signature(connection) -> list[dict]:
    rows = connection.execute(
        """
        SELECT
            CASE
                WHEN created_at > now() - interval '24 hours' THEN 'young (<24h)'
                WHEN created_at <= now() - interval '30 days' THEN 'old (>=30d)'
                ELSE 'middle'
            END AS age_group,
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE mint = first_pool_id_text) AS self_referential_pool
        FROM diag_latest
        WHERE launchpad IS NULL
        GROUP BY 1
        ORDER BY 1
        """
    ).fetchall()
    return [
        {"age_group": ag, "total": total, "self_referential_pool_count": sig}
        for ag, total, sig in rows
    ]


def graduation_gap_vs_crash(connection) -> list[dict]:
    rows = connection.execute(
        """
        SELECT bucket, COUNT(*) AS total,
               COUNT(*) FILTER (WHERE liquidity IS NOT NULL AND liquidity < 0.01) AS crashed
        FROM (
            SELECT liquidity,
                CASE
                    WHEN gap_seconds < 5 THEN 'instant (<5s)'
                    WHEN gap_seconds < 3600 THEN 'short (<1h)'
                    WHEN gap_seconds < 86400 THEN 'medium (<24h)'
                    ELSE 'long (>=24h)'
                END AS bucket
            FROM (
                SELECT liquidity,
                       EXTRACT(EPOCH FROM (
                           graduated_at_text::timestamptz
                           - first_pool_created_at_text::timestamptz
                       )) AS gap_seconds
                FROM diag_latest
                WHERE launchpad = 'met-dbc'
                  AND graduated_at_text IS NOT NULL
                  AND first_pool_created_at_text IS NOT NULL
            ) AS g
        ) AS b
        GROUP BY bucket
        ORDER BY bucket
        """
    ).fetchall()
    return [
        {"bucket": bucket, "total": total, "crashed": crashed}
        for bucket, total, crashed in rows
    ]


def graduation_state_leading_indicator(connection) -> list[dict]:
    """Erhaelt die urspruengliche Semantik, vermeidet aber current_status-Scan.

    Der letzte historische met-dbc/graduated-Snapshot wurde bereits waehrend
    des einzigen History-Passes bestimmt. Fuer jeden relevanten Mint wird nur
    noch der erste Snapshot ab graduatedAt per Index-Lookup gesucht.
    """
    rows = connection.execute(
        """
        WITH grad_info AS (
            SELECT
                h.mint,
                (s.payload->>'graduatedAt')::timestamptz AS graduated_at,
                (s.payload->'firstPool'->>'createdAt')::timestamptz AS first_pool_at
            FROM diag_history_features AS h
            JOIN mint_snapshots AS s
              ON s.mint = h.mint
             AND s.observed_at = h.latest_met_dbc_graduated_observed_at
            WHERE h.latest_met_dbc_graduated_observed_at IS NOT NULL
        ),
        gap_bucketed AS (
            SELECT mint, graduated_at,
                CASE
                    WHEN EXTRACT(EPOCH FROM (graduated_at - first_pool_at)) < 5 THEN 'instant'
                    WHEN EXTRACT(EPOCH FROM (graduated_at - first_pool_at)) < 3600 THEN 'short'
                    ELSE 'other'
                END AS gap_bucket
            FROM grad_info
            WHERE first_pool_at IS NOT NULL
        ),
        first_post_grad AS (
            SELECT
                g.mint,
                g.gap_bucket,
                fp.initial_liquidity,
                fp.initial_holders
            FROM gap_bucketed AS g
            JOIN LATERAL (
                SELECT
                    (s.payload->>'liquidity')::float8 AS initial_liquidity,
                    (s.payload->>'holderCount')::float8 AS initial_holders
                FROM mint_snapshots AS s
                WHERE s.mint = g.mint
                  AND s.observed_at >= g.graduated_at
                ORDER BY s.observed_at ASC
                LIMIT 1
            ) AS fp ON true
        )
        SELECT
            f.gap_bucket,
            CASE WHEN c.liquidity < 0.01 THEN 'crashed' ELSE 'survived' END AS status,
            COUNT(*),
            ROUND(AVG(f.initial_liquidity)::numeric, 2),
            ROUND(AVG(f.initial_holders)::numeric, 1)
        FROM first_post_grad AS f
        JOIN diag_latest_all AS c ON c.mint = f.mint
        WHERE f.gap_bucket IN ('instant', 'short')
        GROUP BY f.gap_bucket, status
        ORDER BY f.gap_bucket, status
        """
    ).fetchall()
    return [
        {
            "gap_bucket": bucket,
            "status": status,
            "count": count,
            "avg_initial_liquidity": float(avg_liq) if avg_liq is not None else None,
            "avg_initial_holders": float(avg_holders) if avg_holders is not None else None,
        }
        for bucket, status, count, avg_liq, avg_holders in rows
    ]


def young_token_change_artifact(connection) -> dict:
    young_with_change, young_extreme = connection.execute(
        """
        SELECT
            COUNT(*) FILTER (
                WHERE created_at > now() - interval '24 hours'
                  AND has_stats24h_holder_change
            ),
            COUNT(*) FILTER (
                WHERE created_at > now() - interval '24 hours'
                  AND has_stats24h_holder_change
                  AND abs(stats24h_holder_change) > 1000
            )
        FROM diag_latest
        """
    ).fetchone()
    return {
        "young_tokens_with_24h_change_field": young_with_change,
        "young_tokens_with_extreme_change_over_1000pct": young_extreme,
    }


def mcap_null_correlation(connection) -> dict:
    low_no_mcap, low_total, healthy_no_mcap, healthy_total = connection.execute(
        """
        SELECT
            COUNT(*) FILTER (WHERE has_liquidity AND liquidity < 0.01 AND mcap IS NULL),
            COUNT(*) FILTER (WHERE has_liquidity AND liquidity < 0.01),
            COUNT(*) FILTER (WHERE has_liquidity AND liquidity >= 1000 AND mcap IS NULL),
            COUNT(*) FILTER (WHERE has_liquidity AND liquidity >= 1000)
        FROM diag_latest
        """
    ).fetchone()
    return {
        "low_liquidity_tokens_missing_mcap": f"{low_no_mcap}/{low_total}",
        "healthy_liquidity_tokens_missing_mcap": f"{healthy_no_mcap}/{healthy_total}",
    }


def stale_bucket_breakdown(connection) -> list[dict]:
    rows = connection.execute(
        """
        SELECT bucket_label, bucket_order, COUNT(*)
        FROM (
            SELECT
                CASE
                    WHEN mins < 30 THEN '10-30min'
                    WHEN mins < 60 THEN '30-60min'
                    WHEN mins < 180 THEN '1-3h'
                    WHEN mins < 1440 THEN '3-24h'
                    ELSE '>=24h'
                END AS bucket_label,
                CASE
                    WHEN mins < 30 THEN 0
                    WHEN mins < 60 THEN 1
                    WHEN mins < 180 THEN 2
                    WHEN mins < 1440 THEN 3
                    ELSE 4
                END AS bucket_order
            FROM (
                SELECT EXTRACT(EPOCH FROM (last_polled_at - unchanged_since)) / 60 AS mins
                FROM diag_latest
                WHERE unchanged_since IS NOT NULL
                  AND (last_polled_at - unchanged_since) > interval '10 minutes'
            ) AS t
        ) AS b
        GROUP BY bucket_label, bucket_order
        ORDER BY bucket_order
        """
    ).fetchall()
    return [{"bucket": label, "count": count} for label, _, count in rows]


def newly_stale_3_24h_samples(connection) -> list[dict]:
    rows = connection.execute(
        """
        SELECT mint, name, symbol, created_at,
               unchanged_since, last_polled_at,
               liquidity_text, holders_text, launchpad
        FROM diag_latest
        WHERE unchanged_since IS NOT NULL
          AND EXTRACT(EPOCH FROM (last_polled_at - unchanged_since)) / 3600 >= 3
        ORDER BY unchanged_since ASC
        LIMIT %s
        """,
        (SAMPLE_LIMIT,),
    ).fetchall()
    return [
        {
            "mint": mint,
            "name": name,
            "symbol": symbol,
            "token_created_at": created_at.isoformat() if created_at else None,
            "unchanged_since": unchanged_since.isoformat() if unchanged_since else None,
            "last_polled_at": last_polled_at.isoformat() if last_polled_at else None,
            "hours_unchanged": round((last_polled_at - unchanged_since).total_seconds() / 3600, 2) if unchanged_since else None,
            "liquidity": liquidity,
            "holders": holders,
            "launchpad": launchpad,
        }
        for mint, name, symbol, created_at, unchanged_since, last_polled_at, liquidity, holders, launchpad in rows
    ]


def mcap_peak_crash(connection) -> dict:
    peak_threshold = 10_000
    drop_threshold = 0.95

    where_sql = """
        mcap_snapshot_count >= 3
        AND peak_mcap > %s
        AND (peak_mcap - current_nonnull_mcap) / peak_mcap > %s
    """

    total_count = connection.execute(
        f"SELECT COUNT(*) FROM diag_history_features WHERE {where_sql}",
        (peak_threshold, drop_threshold),
    ).fetchone()[0]

    rows = connection.execute(
        f"""
        SELECT
            mint, peak_mcap, current_nonnull_mcap,
            current_nonnull_mcap_observed_at,
            current_nonnull_mcap_name,
            current_nonnull_mcap_symbol,
            current_nonnull_mcap_holders,
            current_nonnull_mcap_liquidity,
            current_nonnull_mcap_graduated_at
        FROM diag_history_features
        WHERE {where_sql}
        ORDER BY (peak_mcap - current_nonnull_mcap) / peak_mcap DESC
        LIMIT %s
        """,
        (peak_threshold, drop_threshold, SAMPLE_LIMIT),
    ).fetchall()

    samples = []
    for mint, peak_mcap, current_mcap, observed_at, name, symbol, holders, liquidity, graduated_at in rows:
        pct_drop = (peak_mcap - current_mcap) / peak_mcap * 100
        samples.append({
            "mint": mint,
            "name": name,
            "symbol": symbol,
            "peak_mcap": peak_mcap,
            "current_mcap": current_mcap,
            "pct_drop_from_peak": round(pct_drop, 2),
            "latest_observed_at": observed_at.isoformat(),
            "holders": holders,
            "liquidity": liquidity,
            "graduated_at": graduated_at,
        })

    return {
        "category": "mcap_peak_crash_over_95pct",
        "total_count": total_count,
        "samples": samples,
    }


def liquidity_peak_crash(connection) -> dict:
    peak_threshold = 100
    drop_threshold = 0.95

    where_sql = """
        liquidity_snapshot_count >= 3
        AND peak_liquidity > %s
        AND (peak_liquidity - current_nonnull_liquidity) / peak_liquidity > %s
    """

    total_count = connection.execute(
        f"SELECT COUNT(*) FROM diag_history_features WHERE {where_sql}",
        (peak_threshold, drop_threshold),
    ).fetchone()[0]

    rows = connection.execute(
        f"""
        SELECT
            mint, peak_liquidity, current_nonnull_liquidity,
            current_nonnull_liquidity_observed_at,
            current_nonnull_liquidity_name,
            current_nonnull_liquidity_symbol,
            current_nonnull_liquidity_holders,
            current_nonnull_liquidity_mcap,
            current_nonnull_liquidity_graduated_at
        FROM diag_history_features
        WHERE {where_sql}
        ORDER BY (peak_liquidity - current_nonnull_liquidity) / peak_liquidity DESC
        LIMIT %s
        """,
        (peak_threshold, drop_threshold, SAMPLE_LIMIT),
    ).fetchall()

    samples = []
    for mint, peak_liq, current_liq, observed_at, name, symbol, holders, mcap, graduated_at in rows:
        pct_drop = (peak_liq - current_liq) / peak_liq * 100
        samples.append({
            "mint": mint,
            "name": name,
            "symbol": symbol,
            "peak_liquidity": peak_liq,
            "current_liquidity": current_liq,
            "pct_drop_from_peak": round(pct_drop, 2),
            "latest_observed_at": observed_at.isoformat(),
            "holders": holders,
            "mcap": mcap,
            "graduated_at": graduated_at,
        })

    return {
        "category": "liquidity_peak_crash_over_95pct",
        "total_count": total_count,
        "samples": samples,
    }


def holder_stagnation(connection) -> dict:
    min_snapshots = 5
    min_span_min = 60

    where_sql = """
        h.holder_snapshot_count >= %s
        AND h.min_holder_value IS NOT DISTINCT FROM h.max_holder_value
        AND h.min_holder_value IS NOT NULL
        AND EXTRACT(EPOCH FROM (h.holder_last_observed_at - h.holder_first_observed_at)) / 60 >= %s
    """

    total_count = connection.execute(
        f"SELECT COUNT(*) FROM diag_history_features AS h WHERE {where_sql}",
        (min_snapshots, min_span_min),
    ).fetchone()[0]

    rows = connection.execute(
        f"""
        SELECT
            h.mint,
            l.name,
            l.symbol,
            h.holder_snapshot_count,
            h.min_holder_value,
            EXTRACT(EPOCH FROM (h.holder_last_observed_at - h.holder_first_observed_at)) / 60 AS span_min,
            l.liquidity_text,
            l.mcap_text,
            l.launchpad
        FROM diag_history_features AS h
        JOIN diag_latest_all AS l ON l.mint = h.mint
        WHERE {where_sql}
        ORDER BY span_min DESC
        LIMIT %s
        """,
        (min_snapshots, min_span_min, SAMPLE_LIMIT),
    ).fetchall()

    samples = []
    for mint, name, symbol, n, stuck_holders, span_min, liquidity, mcap, launchpad in rows:
        samples.append({
            "mint": mint,
            "name": name,
            "symbol": symbol,
            "snapshot_count": n,
            "stuck_holder_value": stuck_holders,
            "span_min": round(float(span_min), 1) if span_min is not None else None,
            "liquidity": liquidity,
            "mcap": mcap,
            "launchpad": launchpad,
        })

    return {
        "category": "holder_count_stagnant_60min_plus",
        "total_count": total_count,
        "samples": samples,
    }


def bot_ratio_clusters(connection) -> list[dict]:
    rows = connection.execute(
        """
        WITH ratios AS (
            SELECT
                mint,
                name,
                symbol,
                mcap_text::numeric AS mcap_val,
                liquidity_text::numeric AS liq_val,
                ROUND((mcap_text::numeric / NULLIF(liquidity_text::numeric, 0)), 3) AS ratio
            FROM diag_latest
            WHERE launchpad IS NULL
              AND has_mcap AND mcap IS NOT NULL
              AND has_liquidity AND liquidity > 0
        )
        SELECT
            ratio,
            COUNT(*) AS n,
            MIN(mcap_val / NULLIF(liq_val, 0)) AS actual_min,
            MAX(mcap_val / NULLIF(liq_val, 0)) AS actual_max,
            array_agg(mint ORDER BY mint) AS mints,
            array_agg(name ORDER BY mint) AS names
        FROM ratios
        WHERE ratio IS NOT NULL
        GROUP BY ratio
        HAVING COUNT(*) >= 3
        ORDER BY n DESC
        LIMIT 10
        """
    ).fetchall()
    return [
        {
            "mcap_to_liquidity_ratio_rounded": float(ratio),
            "actual_min": float(actual_min) if actual_min is not None else None,
            "actual_max": float(actual_max) if actual_max is not None else None,
            "count": n,
            "mints": mints[:8],
            "names": names[:8],
        }
        for ratio, n, actual_min, actual_max, mints, names in rows
    ]


def stats1h_activity_vs_unchanged_validation(connection) -> list[dict]:
    rows = connection.execute(
        """
        SELECT activity_group, unchanged_bucket, unchanged_order, COUNT(*)
        FROM (
            SELECT
                CASE
                    WHEN COALESCE(stats1h_num_buys, 0) + COALESCE(stats1h_num_sells, 0) = 0
                    THEN 'zero_stats1h_activity'
                    ELSE 'has_stats1h_activity'
                END AS activity_group,
                CASE
                    WHEN mins < 5 THEN '<5min'
                    WHEN mins < 15 THEN '5-15min'
                    WHEN mins < 60 THEN '15-60min'
                    WHEN mins < 180 THEN '1-3h'
                    ELSE '>=3h'
                END AS unchanged_bucket,
                CASE
                    WHEN mins < 5 THEN 0
                    WHEN mins < 15 THEN 1
                    WHEN mins < 60 THEN 2
                    WHEN mins < 180 THEN 3
                    ELSE 4
                END AS unchanged_order
            FROM (
                SELECT
                    stats1h_num_buys,
                    stats1h_num_sells,
                    EXTRACT(EPOCH FROM (last_polled_at - unchanged_since)) / 60 AS mins
                FROM diag_latest
                WHERE created_at < now() - interval '1 hour'
                  AND unchanged_since IS NOT NULL
            ) AS t
        ) AS b
        GROUP BY activity_group, unchanged_bucket, unchanged_order
        ORDER BY activity_group, unchanged_order
        """
    ).fetchall()
    return [
        {"activity_group": ag, "unchanged_bucket": bucket, "count": count}
        for ag, bucket, _, count in rows
    ]


def mcap_null_pattern_analysis(connection) -> list[dict]:
    rows = connection.execute(
        """
        WITH classified AS (
            SELECT
                h.mint,
                EXTRACT(EPOCH FROM (h.last_snapshot_at - h.first_snapshot_at)) / 60 AS observed_span_min,
                CASE
                    WHEN h.mcap_snapshot_count = 0 THEN 'never_had_mcap'
                    ELSE 'had_mcap_then_lost_it'
                END AS pattern
            FROM diag_history_features AS h
            JOIN diag_latest_all AS l ON l.mint = h.mint
            WHERE l.mcap IS NULL
        )
        SELECT pattern, span_bucket, span_order, COUNT(*)
        FROM (
            SELECT pattern,
                CASE
                    WHEN pattern = 'had_mcap_then_lost_it' THEN 'n/a'
                    WHEN observed_span_min < 2 THEN '<2min'
                    WHEN observed_span_min < 5 THEN '2-5min'
                    WHEN observed_span_min < 15 THEN '5-15min'
                    WHEN observed_span_min < 60 THEN '15-60min'
                    ELSE '>=60min'
                END AS span_bucket,
                CASE
                    WHEN pattern = 'had_mcap_then_lost_it' THEN -1
                    WHEN observed_span_min < 2 THEN 0
                    WHEN observed_span_min < 5 THEN 1
                    WHEN observed_span_min < 15 THEN 2
                    WHEN observed_span_min < 60 THEN 3
                    ELSE 4
                END AS span_order
            FROM classified
        ) AS c
        GROUP BY pattern, span_bucket, span_order
        ORDER BY pattern, span_order
        """
    ).fetchall()
    return [
        {"pattern": pattern, "observed_span_bucket": bucket, "count": count}
        for pattern, bucket, _, count in rows
    ]


def mcap_null_never_had_stuck_samples(connection) -> list[dict]:
    rows = connection.execute(
        """
        SELECT
            h.mint,
            l.name,
            l.symbol,
            h.snapshot_count,
            l.created_at,
            EXTRACT(EPOCH FROM (h.last_snapshot_at - h.first_snapshot_at)) / 60 AS observed_span_min,
            l.holders_text,
            l.liquidity_text,
            l.launchpad
        FROM diag_history_features AS h
        JOIN diag_latest_all AS l ON l.mint = h.mint
        WHERE h.mcap_snapshot_count = 0
          AND l.mcap IS NULL
          AND EXTRACT(EPOCH FROM (h.last_snapshot_at - h.first_snapshot_at)) / 60 >= 60
        ORDER BY h.snapshot_count DESC
        LIMIT %s
        """,
        (SAMPLE_LIMIT,),
    ).fetchall()
    return [
        {
            "mint": mint,
            "name": name,
            "symbol": symbol,
            "snapshot_count": snap_count,
            "token_created_at": created_at.isoformat() if created_at else None,
            "observed_span_min": round(float(span), 1) if span is not None else None,
            "holders": holders,
            "liquidity": liquidity,
            "launchpad": launchpad,
        }
        for mint, name, symbol, snap_count, created_at, span, holders, liquidity, launchpad in rows
    ]


def validate_internal_consistency(
    connection,
    context: dict,
    results: list[dict],
    overlap: dict,
    stale_breakdown: list[dict],
    stats1h_validation: list[dict],
) -> dict:
    """Technische Guardrails fuer die materialisierten Diagnose-Caches.

    Diese Checks fuehren keine alte Analyse erneut aus. Sie vergleichen nur
    bereits unabhaengig berechnete Summen und die Groesse der TEMP TABLES.
    Bei einer Abweichung bricht der Report sichtbar ab, statt stillschweigend
    inkonsistente Zahlen zu schreiben.
    """
    active_cache_rows = connection.execute(
        "SELECT COUNT(*) FROM diag_latest"
    ).fetchone()[0]
    all_cache_rows = connection.execute(
        "SELECT COUNT(*) FROM diag_latest_all"
    ).fetchone()[0]
    history_cache_rows = connection.execute(
        "SELECT COUNT(*) FROM diag_history_features"
    ).fetchone()[0]

    category_counts = {row["category"]: row["total_count"] for row in results}
    stale_total = sum(row["count"] for row in stale_breakdown)
    zero_activity_stale_total = sum(
        row["count"]
        for row in stats1h_validation
        if row["activity_group"] == "zero_stats1h_activity"
        and row["unchanged_bucket"] in {"15-60min", "1-3h", ">=3h"}
    )
    launchpad_total = sum(context["by_launchpad"].values())

    checks = {
        "latest_cache_matches_launchpad_total": active_cache_rows == launchpad_total,
        "history_cache_matches_all_latest_cache": history_cache_rows == all_cache_rows,
        "liquidity_category_matches_overlap": (
            category_counts["liquidity_below_0_01_but_field_present"]
            == overlap["liquidity_below_0_01_count"]
        ),
        "price_crash_category_matches_overlap": (
            category_counts["price_change_24h_below_minus_99"]
            == overlap["price_crashed_count"]
        ),
        "stale_category_matches_bucket_sum": (
            category_counts["no_update_for_more_than_10min"] == stale_total
        ),
        "zero_activity_stale_category_matches_validation_buckets": (
            category_counts["zero_activity_and_stale_15min_plus"]
            == zero_activity_stale_total
        ),
    }

    failed = [name for name, ok in checks.items() if not ok]
    if failed:
        raise RuntimeError(
            "Diagnose cache consistency check failed: " + ", ".join(failed)
        )

    return {
        "status": "ok",
        "checks": checks,
        "cache_rows": {
            "active_latest": active_cache_rows,
            "all_latest": all_cache_rows,
            "history_features": history_cache_rows,
            "active_without_snapshot": max(
                context["total_tracked_mints"] - active_cache_rows,
                0,
            ),
        },
    }


def data_quality_metrics(connection) -> dict:
    row = connection.execute(
        """
        SELECT
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE has_mcap AND mcap IS NOT NULL) AS mcap_present,
            COUNT(*) FILTER (
                WHERE has_liquidity AND liquidity IS NOT NULL
            ) AS liquidity_present,
            COUNT(*) FILTER (
                WHERE has_holder_count AND holders IS NOT NULL
            ) AS holder_count_present,
            COUNT(*) FILTER (WHERE payload ? 'stats1h') AS stats1h_present,
            COUNT(*) FILTER (WHERE payload ? 'stats24h') AS stats24h_present,
            COUNT(*) FILTER (WHERE payload ? 'firstPool') AS first_pool_present,
            COUNT(*) FILTER (
                WHERE graduated_at_text IS NOT NULL
            ) AS graduated_at_present,
            COUNT(*) FILTER (WHERE payload ? 'updatedAt') AS updated_at_present
        FROM diag_latest
        """
    ).fetchone()

    names = [
        "total",
        "mcap",
        "liquidity",
        "holder_count",
        "stats1h",
        "stats24h",
        "first_pool",
        "graduated_at",
        "updated_at",
    ]
    values = dict(zip(names, row))
    total = values.pop("total")
    fields: dict[str, dict] = {}
    for name, count in values.items():
        fields[name] = {
            "present": count,
            "missing": total - count,
            "present_pct": round(count / total * 100, 2) if total else 0.0,
        }
    return {"total_active_with_snapshot": total, "fields": fields}


def trajectory_metrics(connection) -> dict:
    row = connection.execute(
        """
        SELECT
            COUNT(*) FILTER (
                WHERE h.peak_mcap > 0
                  AND l.mcap IS NOT NULL
                  AND (h.peak_mcap - l.mcap) / h.peak_mcap >= 0.95
            ) AS mcap_drop_95,
            COUNT(*) FILTER (
                WHERE h.peak_mcap > 0
                  AND l.mcap IS NOT NULL
                  AND (h.peak_mcap - l.mcap) / h.peak_mcap >= 0.99
            ) AS mcap_drop_99,
            COUNT(*) FILTER (
                WHERE h.peak_mcap >= 40000
                  AND l.mcap IS NOT NULL
                  AND l.mcap <= 100
            ) AS mcap_peak_40k_current_100,
            COUNT(*) FILTER (
                WHERE h.peak_liquidity > 0
                  AND l.liquidity IS NOT NULL
                  AND (h.peak_liquidity - l.liquidity)
                      / h.peak_liquidity >= 0.95
            ) AS liq_drop_95,
            COUNT(*) FILTER (
                WHERE h.peak_liquidity > 0
                  AND l.liquidity IS NOT NULL
                  AND (h.peak_liquidity - l.liquidity)
                      / h.peak_liquidity >= 0.99
            ) AS liq_drop_99,
            COUNT(*) FILTER (
                WHERE h.peak_liquidity >= 10000
                  AND l.liquidity IS NOT NULL
                  AND l.liquidity <= 1
            ) AS liq_peak_10k_current_1,
            COUNT(*) FILTER (
                WHERE h.max_holder_value > 0
                  AND l.holders IS NOT NULL
                  AND l.holders::float8 / h.max_holder_value <= 0.25
            ) AS holders_below_25pct_peak,
            COUNT(*) FILTER (
                WHERE h.max_holder_value > 0
                  AND l.holders IS NOT NULL
                  AND l.holders::float8 / h.max_holder_value <= 0.50
            ) AS holders_below_50pct_peak
        FROM diag_latest AS l
        JOIN diag_history_features AS h ON h.mint = l.mint
        """
    ).fetchone()

    return {
        "mcap_drop_from_peak": {
            ">=95pct": row[0],
            ">=99pct": row[1],
            "peak>=40000_current<=100": row[2],
        },
        "liquidity_drop_from_peak": {
            ">=95pct": row[3],
            ">=99pct": row[4],
            "peak>=10000_current<=1": row[5],
        },
        "holder_retention": {
            "current<=25pct_of_peak": row[6],
            "current<=50pct_of_peak": row[7],
        },
    }


def peak_timing_metrics(connection) -> dict:
    """Zeit seit historischem Peak fuer aktuell stark kollabierte Tokens.

    Peak-Zeitpunkte werden nur fuer die kleine Kandidatenmenge gesucht, nicht
    fuer alle Mints. Das permanente Schema bleibt unveraendert.
    """
    rows = connection.execute(
        """
        WITH candidates AS (
            SELECT
                l.mint,
                h.peak_mcap,
                h.peak_liquidity,
                l.mcap,
                l.liquidity,
                (
                    h.peak_mcap > 0
                    AND l.mcap IS NOT NULL
                    AND (h.peak_mcap - l.mcap) / h.peak_mcap >= 0.95
                ) AS mcap_collapsed,
                (
                    h.peak_liquidity > 0
                    AND l.liquidity IS NOT NULL
                    AND (h.peak_liquidity - l.liquidity)
                        / h.peak_liquidity >= 0.95
                ) AS liquidity_collapsed
            FROM diag_latest AS l
            JOIN diag_history_features AS h ON h.mint = l.mint
        )
        SELECT
            c.mint,
            c.mcap_collapsed,
            c.liquidity_collapsed,
            pm.peak_at AS mcap_peak_at,
            pl.peak_at AS liquidity_peak_at
        FROM candidates AS c
        LEFT JOIN LATERAL (
            SELECT s.observed_at AS peak_at
            FROM mint_snapshots AS s
            WHERE c.mcap_collapsed
              AND s.mint = c.mint
              AND s.payload->>'mcap' IS NOT NULL
            ORDER BY (s.payload->>'mcap')::float8 DESC, s.observed_at ASC
            LIMIT 1
        ) AS pm ON true
        LEFT JOIN LATERAL (
            SELECT s.observed_at AS peak_at
            FROM mint_snapshots AS s
            WHERE c.liquidity_collapsed
              AND s.mint = c.mint
              AND s.payload->>'liquidity' IS NOT NULL
            ORDER BY (s.payload->>'liquidity')::float8 DESC, s.observed_at ASC
            LIMIT 1
        ) AS pl ON true
        WHERE c.mcap_collapsed OR c.liquidity_collapsed
        """
    ).fetchall()

    now = datetime.now(timezone.utc)
    buckets = ["<30min", "30-60min", "1-3h", "3-24h", ">=24h"]

    def bucket(minutes: float) -> str:
        if minutes < 30:
            return "<30min"
        if minutes < 60:
            return "30-60min"
        if minutes < 180:
            return "1-3h"
        if minutes < 1440:
            return "3-24h"
        return ">=24h"

    result = {
        "mcap_collapsed_since_peak": {name: 0 for name in buckets},
        "liquidity_collapsed_since_peak": {name: 0 for name in buckets},
    }

    for _, mcap_collapsed, liq_collapsed, mcap_peak_at, liq_peak_at in rows:
        if mcap_collapsed and mcap_peak_at is not None:
            minutes = max((now - mcap_peak_at).total_seconds() / 60, 0.0)
            result["mcap_collapsed_since_peak"][bucket(minutes)] += 1
        if liq_collapsed and liq_peak_at is not None:
            minutes = max((now - liq_peak_at).total_seconds() / 60, 0.0)
            result["liquidity_collapsed_since_peak"][bucket(minutes)] += 1

    result["candidate_count"] = len(rows)
    return result


def _round_num(value: float | None, digits: int = 6) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def _quantiles(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {key: None for key in ("p01", "p05", "p10", "p25", "p50", "p75", "p90", "p95", "p99")}
    ordered = sorted(values)

    def percentile(p: float) -> float:
        if len(ordered) == 1:
            return ordered[0]
        pos = (len(ordered) - 1) * p
        lo = math.floor(pos)
        hi = math.ceil(pos)
        if lo == hi:
            return ordered[lo]
        weight = pos - lo
        return ordered[lo] * (1.0 - weight) + ordered[hi] * weight

    return {
        "p01": _round_num(percentile(0.01)),
        "p05": _round_num(percentile(0.05)),
        "p10": _round_num(percentile(0.10)),
        "p25": _round_num(percentile(0.25)),
        "p50": _round_num(percentile(0.50)),
        "p75": _round_num(percentile(0.75)),
        "p90": _round_num(percentile(0.90)),
        "p95": _round_num(percentile(0.95)),
        "p99": _round_num(percentile(0.99)),
    }


def _threshold_distribution(values: list[float], total_active: int, thresholds: list[float]) -> list[dict]:
    ordered = sorted(values)
    result = []
    for threshold in thresholds:
        count = bisect.bisect_left(ordered, threshold)
        result.append({
            "threshold": threshold,
            "count_below": count,
            "pct_of_present": round(count / len(ordered) * 100, 3) if ordered else 0.0,
            "pct_of_all_active": round(count / total_active * 100, 3) if total_active else 0.0,
        })
    return result


def _ecdf_curve(values: list[float], total_active: int, points: int = 120) -> list[dict]:
    positive = sorted(value for value in values if value > 0)
    if not positive:
        return []
    low, high = positive[0], positive[-1]
    if low == high:
        xs = [low]
    else:
        lo_log, hi_log = math.log10(low), math.log10(high)
        xs = [10 ** (lo_log + (hi_log - lo_log) * i / (points - 1)) for i in range(points)]
    ordered_all = sorted(values)
    return [
        {
            "value": _round_num(x),
            "count_at_or_below": bisect.bisect_right(ordered_all, x),
            "pct_of_present": round(bisect.bisect_right(ordered_all, x) / len(ordered_all) * 100, 4),
            "pct_of_all_active": round(bisect.bisect_right(ordered_all, x) / total_active * 100, 4) if total_active else 0.0,
        }
        for x in xs
    ]


def _age_bucket_for_minutes(age_minutes: float | None) -> str:
    if age_minutes is None or age_minutes < 0:
        return "unknown"
    for key, _, lower, upper in AGE_DISTRIBUTION_BUCKETS:
        if age_minutes >= lower and (upper is None or age_minutes < upper):
            return key
    return "unknown"


def _distribution_metric(values: list[float], total: int, thresholds: list[float]) -> dict:
    missing = max(total - len(values), 0)
    return {
        "present": len(values),
        "missing": missing,
        "coverage_pct": round(len(values) / total * 100, 3) if total else 0.0,
        "zero_or_negative": sum(1 for value in values if value <= 0),
        "quantiles": _quantiles(values),
        "thresholds": _threshold_distribution(values, total, thresholds),
        "ecdf": _ecdf_curve(values, total),
    }


def _joint_density(paired: list[tuple[float | None, float | None]]) -> dict:
    positive = [
        (mcap, liquidity)
        for mcap, liquidity in paired
        if mcap is not None and liquidity is not None and mcap > 0 and liquidity > 0
    ]
    if not positive:
        return {
            "paired_positive": 0,
            "x_bins": JOINT_DENSITY_X_BINS,
            "y_bins": JOINT_DENSITY_Y_BINS,
            "x_log_min": None,
            "x_log_max": None,
            "y_log_min": None,
            "y_log_max": None,
            "max_cell_count": 0,
            "cells": [],
        }

    x_logs = [math.log10(mcap) for mcap, _ in positive]
    y_logs = [math.log10(liquidity) for _, liquidity in positive]
    x_lo = math.floor(min(x_logs))
    x_hi = math.ceil(max(x_logs))
    y_lo = math.floor(min(y_logs))
    y_hi = math.ceil(max(y_logs))
    if x_hi <= x_lo:
        x_hi = x_lo + 1
    if y_hi <= y_lo:
        y_hi = y_lo + 1

    counts: dict[tuple[int, int], int] = {}
    for x_log, y_log in zip(x_logs, y_logs):
        ix = min(
            JOINT_DENSITY_X_BINS - 1,
            max(0, int((x_log - x_lo) / (x_hi - x_lo) * JOINT_DENSITY_X_BINS)),
        )
        iy = min(
            JOINT_DENSITY_Y_BINS - 1,
            max(0, int((y_log - y_lo) / (y_hi - y_lo) * JOINT_DENSITY_Y_BINS)),
        )
        counts[(ix, iy)] = counts.get((ix, iy), 0) + 1

    return {
        "paired_positive": len(positive),
        "x_bins": JOINT_DENSITY_X_BINS,
        "y_bins": JOINT_DENSITY_Y_BINS,
        "x_log_min": float(x_lo),
        "x_log_max": float(x_hi),
        "y_log_min": float(y_lo),
        "y_log_max": float(y_hi),
        "max_cell_count": max(counts.values(), default=0),
        "cells": [
            {"ix": ix, "iy": iy, "count": count}
            for (ix, iy), count in sorted(counts.items())
        ],
    }


def population_distribution_metrics(connection) -> dict:
    rows = connection.execute(
        """
        SELECT
            mint,
            dev,
            EXTRACT(EPOCH FROM (now() - created_at)) / 60.0 AS age_minutes,
            has_mcap,
            mcap,
            has_liquidity,
            liquidity
        FROM diag_latest
        """
    ).fetchall()
    total = len(rows)
    mcap_values: list[float] = []
    liquidity_values: list[float] = []
    dev_counts: dict[str, int] = {}
    paired: list[tuple[float | None, float | None]] = []

    age_state: dict[str, dict[str, Any]] = {
        key: {
            "label": label,
            "total": 0,
            "mcap_values": [],
            "liquidity_values": [],
        }
        for key, label, _, _ in AGE_DISTRIBUTION_BUCKETS
    }
    age_state["unknown"] = {
        "label": "unknown",
        "total": 0,
        "mcap_values": [],
        "liquidity_values": [],
    }

    for _, dev, age_minutes, has_mcap, mcap, has_liquidity, liquidity in rows:
        current_mcap = float(mcap) if has_mcap and mcap is not None else None
        current_liquidity = float(liquidity) if has_liquidity and liquidity is not None else None
        if current_mcap is not None:
            mcap_values.append(current_mcap)
        if current_liquidity is not None:
            liquidity_values.append(current_liquidity)
        paired.append((current_mcap, current_liquidity))

        bucket_key = _age_bucket_for_minutes(
            float(age_minutes) if age_minutes is not None else None
        )
        bucket = age_state[bucket_key]
        bucket["total"] += 1
        if current_mcap is not None:
            bucket["mcap_values"].append(current_mcap)
        if current_liquidity is not None:
            bucket["liquidity_values"].append(current_liquidity)

        if dev:
            dev_counts[dev] = dev_counts.get(dev, 0) + 1

    repeated_devs = {dev: count for dev, count in dev_counts.items() if count >= 2}
    top_devs = sorted(dev_counts.items(), key=lambda item: (-item[1], item[0]))[:20]

    joint = []
    for mcap_threshold in [200, 1_000, 2_000, 5_000, 10_000]:
        for liq_threshold in [1, 100, 1_000, 2_000]:
            mcap_low = liq_low = both_low = union_low = 0
            for current_mcap, current_liquidity in paired:
                low_mcap = current_mcap is not None and current_mcap < mcap_threshold
                low_liq = current_liquidity is not None and current_liquidity < liq_threshold
                mcap_low += int(low_mcap)
                liq_low += int(low_liq)
                both_low += int(low_mcap and low_liq)
                union_low += int(low_mcap or low_liq)
            joint.append({
                "mcap_below": mcap_threshold,
                "liquidity_below": liq_threshold,
                "mcap_low_count": mcap_low,
                "liquidity_low_count": liq_low,
                "both_low_count": both_low,
                "union_low_count": union_low,
                "union_pct_of_all_active": round(union_low / total * 100, 3) if total else 0.0,
            })

    age_segments: list[dict] = []
    ordered_age_keys = [key for key, _, _, _ in AGE_DISTRIBUTION_BUCKETS] + ["unknown"]
    for key in ordered_age_keys:
        bucket = age_state[key]
        bucket_total = int(bucket["total"])
        age_segments.append({
            "key": key,
            "label": bucket["label"],
            "total": bucket_total,
            "pct_of_all_active": round(bucket_total / total * 100, 3) if total else 0.0,
            "mcap": _distribution_metric(
                bucket["mcap_values"], bucket_total, MCAP_DISTRIBUTION_THRESHOLDS
            ),
            "liquidity": _distribution_metric(
                bucket["liquidity_values"], bucket_total, LIQUIDITY_DISTRIBUTION_THRESHOLDS
            ),
        })

    return {
        "total_active_with_snapshot": total,
        "mcap": _distribution_metric(mcap_values, total, MCAP_DISTRIBUTION_THRESHOLDS),
        "liquidity": _distribution_metric(
            liquidity_values, total, LIQUIDITY_DISTRIBUTION_THRESHOLDS
        ),
        "age_segments": age_segments,
        "joint_hard_filter_grid": joint,
        "joint_density": _joint_density(paired),
        "developers": {
            "dev_present_tokens": sum(dev_counts.values()),
            "dev_missing_tokens": total - sum(dev_counts.values()),
            "distinct_devs": len(dev_counts),
            "repeated_devs": len(repeated_devs),
            "tokens_from_repeated_devs": sum(repeated_devs.values()),
            "max_tokens_single_dev": max(dev_counts.values(), default=0),
            "top_by_token_count": [{"dev": dev, "token_count": count} for dev, count in top_devs],
        },
    }


def _joint_row(distribution: dict, mcap_threshold: float, liq_threshold: float) -> dict | None:
    for row in distribution.get("joint_hard_filter_grid", []):
        if (
            float(row["mcap_below"]) == float(mcap_threshold)
            and float(row["liquidity_below"]) == float(liq_threshold)
        ):
            return row
    return None


def compact_population_run_summary(distribution: dict) -> dict:
    def pick(metric: str, wanted: set[float]) -> dict[str, int]:
        return {
            str(row["threshold"]): row["count_below"]
            for row in distribution[metric]["thresholds"]
            if float(row["threshold"]) in wanted
        }

    age_counts = {
        row["key"]: row["total"]
        for row in distribution.get("age_segments", [])
    }
    joint_unions: dict[str, int] = {}
    for mcap_threshold, liq_threshold in [(2_000, 1), (5_000, 100), (10_000, 2_000)]:
        row = _joint_row(distribution, mcap_threshold, liq_threshold)
        if row:
            joint_unions[f"mcap<{mcap_threshold}|liq<{liq_threshold}"] = row["union_low_count"]

    overlay = distribution.get("policy_overlay", {})
    return {
        "mcap_present": distribution["mcap"]["present"],
        "mcap_missing": distribution["mcap"]["missing"],
        "mcap_below": pick("mcap", {200, 1_000, 2_000, 5_000, 10_000}),
        "liquidity_present": distribution["liquidity"]["present"],
        "liquidity_missing": distribution["liquidity"]["missing"],
        "liquidity_below": pick("liquidity", {1, 100, 1_000, 2_000, 10_000}),
        "age_counts": age_counts,
        "joint_unions": joint_unions,
        "would_retire_unique": overlay.get("would_retire_unique"),
        "probation_unique": overlay.get("probation_unique"),
        "distinct_devs": distribution["developers"]["distinct_devs"],
        "repeated_devs": distribution["developers"]["repeated_devs"],
    }
