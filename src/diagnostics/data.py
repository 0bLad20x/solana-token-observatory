from __future__ import annotations

import time
from contextlib import contextmanager
from datetime import datetime, timezone

@contextmanager
def measured(timings: dict[str, float], name: str):
    started = time.perf_counter()
    try:
        yield
    finally:
        timings[name] = round((time.perf_counter() - started) * 1000, 2)


def build_latest_cache(connection) -> None:
    """Baut den aktuellen Zustand genau einmal auf.

    Der vorhandene Index (mint, observed_at DESC) kann fuer jeden Mint direkt
    den neuesten Snapshot liefern. Die JSONB-Werte, die der Report mehrfach
    benoetigt, werden dabei genau einmal in typisierte Spalten extrahiert.
    """
    connection.execute(
        """
        CREATE TEMP TABLE diag_latest_all ON COMMIT DROP AS
        SELECT
            m.mint,
            m.tracking_enabled,
            m.created_at,
            m.unchanged_since,
            m.last_polled_at,
            s.observed_at,
            s.payload,

            s.payload->>'name' AS name,
            s.payload->>'symbol' AS symbol,
            s.payload->>'launchpad' AS launchpad,
            s.payload->>'dev' AS dev,
            s.payload->'firstPool'->>'id' AS first_pool_id_text,
            s.payload->'firstPool'->>'createdAt' AS first_pool_created_at_text,
            s.payload->>'graduatedAt' AS graduated_at_text,

            COALESCE(s.payload ? 'liquidity', false) AS has_liquidity,
            (s.payload->>'liquidity')::float8 AS liquidity,
            s.payload->>'liquidity' AS liquidity_text,

            COALESCE(s.payload ? 'mcap', false) AS has_mcap,
            (s.payload->>'mcap')::float8 AS mcap,
            s.payload->>'mcap' AS mcap_text,

            COALESCE(s.payload ? 'holderCount', false) AS has_holder_count,
            (s.payload->>'holderCount')::int AS holders,
            s.payload->>'holderCount' AS holders_text,

            (s.payload->'stats1h'->>'numBuys')::int AS stats1h_num_buys,
            (s.payload->'stats1h'->>'numSells')::int AS stats1h_num_sells,

            COALESCE(s.payload->'stats24h' ? 'priceChange', false) AS has_stats24h_price_change,
            (s.payload->'stats24h'->>'priceChange')::float8 AS stats24h_price_change,

            COALESCE(s.payload->'stats24h' ? 'holderChange', false) AS has_stats24h_holder_change,
            (s.payload->'stats24h'->>'holderChange')::float8 AS stats24h_holder_change,

            (s.payload->'stats24h'->>'liquidityChange')::float8 AS stats24h_liquidity_change,
            (s.payload->'stats24h'->>'volumeChange')::float8 AS stats24h_volume_change
        FROM mints AS m
        JOIN LATERAL (
            SELECT s.observed_at, s.payload
            FROM mint_snapshots AS s
            WHERE s.mint = m.mint
            ORDER BY s.observed_at DESC
            LIMIT 1
        ) AS s ON true
        """
    )

    connection.execute(
        """
        CREATE TEMP TABLE diag_latest ON COMMIT DROP AS
        SELECT *
        FROM diag_latest_all
        WHERE tracking_enabled = true
        """
    )

    # TEMP-TABLE-Statistiken helfen dem Planner, ohne das permanente Schema
    # oder die permanente Datenbankstruktur zu veraendern.
    connection.execute("ANALYZE diag_latest_all")
    connection.execute("ANALYZE diag_latest")


def build_history_cache(connection, timings: dict[str, float] | None = None) -> None:
    """Ein einziger voller History-Pass fuer alle historischen Merkmale.

    Peak-Mcap, Peak-Liquiditaet, Beobachtungsdauer, Mcap-Praesenz,
    Holder-Stagnation und die Zeitpunkte der jeweils letzten relevanten
    Snapshots entstehen in einem GROUP BY statt in vielen separaten Scans.
    """
    local_timings = timings if timings is not None else {}

    with measured(local_timings, "history_aggregate_ms"):
        connection.execute(
            """
            CREATE TEMP TABLE diag_history_agg ON COMMIT DROP AS
            SELECT
                s.mint,
                COUNT(*) AS snapshot_count,
                MIN(s.observed_at) AS first_snapshot_at,
                MAX(s.observed_at) AS last_snapshot_at,

                COUNT(*) FILTER (
                    WHERE s.payload->>'mcap' IS NOT NULL
                ) AS mcap_snapshot_count,
                MAX((s.payload->>'mcap')::float8) FILTER (
                    WHERE s.payload->>'mcap' IS NOT NULL
                ) AS peak_mcap,
                MAX(s.observed_at) FILTER (
                    WHERE s.payload->>'mcap' IS NOT NULL
                ) AS latest_nonnull_mcap_observed_at,

                COUNT(*) FILTER (
                    WHERE s.payload->>'liquidity' IS NOT NULL
                ) AS liquidity_snapshot_count,
                MAX((s.payload->>'liquidity')::float8) FILTER (
                    WHERE s.payload->>'liquidity' IS NOT NULL
                ) AS peak_liquidity,
                MAX(s.observed_at) FILTER (
                    WHERE s.payload->>'liquidity' IS NOT NULL
                ) AS latest_nonnull_liquidity_observed_at,

                COUNT(*) FILTER (
                    WHERE s.payload ? 'holderCount'
                ) AS holder_snapshot_count,
                MIN((s.payload->>'holderCount')::int) FILTER (
                    WHERE s.payload ? 'holderCount'
                ) AS min_holder_value,
                MAX((s.payload->>'holderCount')::int) FILTER (
                    WHERE s.payload ? 'holderCount'
                ) AS max_holder_value,
                MIN(s.observed_at) FILTER (
                    WHERE s.payload ? 'holderCount'
                ) AS holder_first_observed_at,
                MAX(s.observed_at) FILTER (
                    WHERE s.payload ? 'holderCount'
                ) AS holder_last_observed_at,

                MAX(s.observed_at) FILTER (
                    WHERE s.payload->>'launchpad' = 'met-dbc'
                      AND s.payload->>'graduatedAt' IS NOT NULL
                ) AS latest_met_dbc_graduated_observed_at
            FROM mint_snapshots AS s
            GROUP BY s.mint
            """
        )


    # CTAS erzeugt fuer TEMP TABLES noch keine brauchbaren Planner-Statistiken.
    # Das ANALYZE vor den beiden punktuellen PK-Lookups verhindert, dass
    # PostgreSQL die Groesse von diag_history_agg falsch schaetzt und einen
    # unnoetig teuren Join-Plan waehlt.
    with measured(local_timings, "history_agg_analyze_ms"):
        connection.execute("ANALYZE diag_history_agg")

    # Die zu den Aggregaten gehoerenden letzten NON-NULL-Snapshots werden ueber
    # den vorhandenen Primary Key (mint, observed_at) punktuell aufgeloest.
    # So muss die History nicht erneut sortiert oder gescannt werden.
    with measured(local_timings, "history_feature_join_ms"):
        connection.execute(
            """
            CREATE TEMP TABLE diag_history_features ON COMMIT DROP AS
            SELECT
                h.*,

                (sm.payload->>'mcap')::float8 AS current_nonnull_mcap,
                sm.observed_at AS current_nonnull_mcap_observed_at,
                sm.payload->>'name' AS current_nonnull_mcap_name,
                sm.payload->>'symbol' AS current_nonnull_mcap_symbol,
                sm.payload->>'holderCount' AS current_nonnull_mcap_holders,
                sm.payload->>'liquidity' AS current_nonnull_mcap_liquidity,
                sm.payload->>'graduatedAt' AS current_nonnull_mcap_graduated_at,

                (sl.payload->>'liquidity')::float8 AS current_nonnull_liquidity,
                sl.observed_at AS current_nonnull_liquidity_observed_at,
                sl.payload->>'name' AS current_nonnull_liquidity_name,
                sl.payload->>'symbol' AS current_nonnull_liquidity_symbol,
                sl.payload->>'holderCount' AS current_nonnull_liquidity_holders,
                sl.payload->>'mcap' AS current_nonnull_liquidity_mcap,
                sl.payload->>'graduatedAt' AS current_nonnull_liquidity_graduated_at
            FROM diag_history_agg AS h
            LEFT JOIN mint_snapshots AS sm
              ON sm.mint = h.mint
             AND sm.observed_at = h.latest_nonnull_mcap_observed_at
            LEFT JOIN mint_snapshots AS sl
              ON sl.mint = h.mint
             AND sl.observed_at = h.latest_nonnull_liquidity_observed_at
            """
        )


    with measured(local_timings, "history_finalize_ms"):
        connection.execute("ANALYZE diag_history_features")
        connection.execute("DROP TABLE diag_history_agg")


def get_context(connection) -> dict:
    total = connection.execute(
        "SELECT COUNT(*) FROM mints WHERE tracking_enabled = true"
    ).fetchone()[0]
    by_launchpad = connection.execute(
        """
        SELECT COALESCE(launchpad, '(null)') AS launchpad, COUNT(*)
        FROM diag_latest
        GROUP BY 1
        ORDER BY 2 DESC
        """
    ).fetchall()
    return {
        "total_tracked_mints": total,
        "by_launchpad": {lp: cnt for lp, cnt in by_launchpad},
    }


def collect_collector_health(connection, config: dict) -> dict:
    """Globaler Fail-closed-Guard vor jeder simulierten Policy-Entscheidung."""
    health_cfg = config["collector_health"]
    recent_window_seconds = int(health_cfg.get("recent_poll_window_seconds", 300))
    min_recent_fraction = float(health_cfg.get("min_recent_poll_fraction", 0.95))
    max_p95_poll_age = float(health_cfg.get("max_p95_poll_age_seconds", 300))
    min_snapshot_coverage = float(
        health_cfg.get("min_snapshot_coverage_fraction", 0.95)
    )

    row = connection.execute(
        """
        SELECT
            COUNT(*) AS total_active,
            COUNT(*) FILTER (WHERE last_polled_at IS NOT NULL) AS ever_polled,
            COUNT(*) FILTER (
                WHERE last_polled_at IS NOT NULL
                  AND EXTRACT(EPOCH FROM (now() - last_polled_at)) <= %s
            ) AS recently_polled,
            PERCENTILE_CONT(0.5) WITHIN GROUP (
                ORDER BY EXTRACT(EPOCH FROM (now() - last_polled_at))
            ) FILTER (WHERE last_polled_at IS NOT NULL) AS median_poll_age_seconds,
            PERCENTILE_CONT(0.95) WITHIN GROUP (
                ORDER BY EXTRACT(EPOCH FROM (now() - last_polled_at))
            ) FILTER (WHERE last_polled_at IS NOT NULL) AS p95_poll_age_seconds,
            MAX(EXTRACT(EPOCH FROM (now() - last_polled_at))) FILTER (
                WHERE last_polled_at IS NOT NULL
            ) AS max_poll_age_seconds
        FROM mints
        WHERE tracking_enabled = true
        """,
        (recent_window_seconds,),
    ).fetchone()

    total_active, ever_polled, recently_polled, median_age, p95_age, max_age = row
    latest_cache_rows = connection.execute(
        "SELECT COUNT(*) FROM diag_latest"
    ).fetchone()[0]

    recent_fraction = recently_polled / total_active if total_active else 0.0
    polled_fraction = ever_polled / total_active if total_active else 0.0
    snapshot_coverage = latest_cache_rows / total_active if total_active else 0.0

    checks = {
        "has_active_mints": total_active > 0,
        "recent_poll_fraction_ok": recent_fraction >= min_recent_fraction,
        "p95_poll_age_ok": (
            p95_age is not None and float(p95_age) <= max_p95_poll_age
        ),
        "snapshot_coverage_ok": snapshot_coverage >= min_snapshot_coverage,
    }
    healthy = all(checks.values())

    return {
        "status": "healthy" if healthy else "unhealthy",
        "healthy": healthy,
        "checks": checks,
        "thresholds": {
            "recent_poll_window_seconds": recent_window_seconds,
            "min_recent_poll_fraction": min_recent_fraction,
            "max_p95_poll_age_seconds": max_p95_poll_age,
            "min_snapshot_coverage_fraction": min_snapshot_coverage,
        },
        "observed": {
            "active_mints": total_active,
            "ever_polled": ever_polled,
            "recently_polled": recently_polled,
            "polled_fraction": round(polled_fraction, 6),
            "recent_poll_fraction": round(recent_fraction, 6),
            "latest_snapshot_cache_rows": latest_cache_rows,
            "snapshot_coverage_fraction": round(snapshot_coverage, 6),
            "median_poll_age_seconds": (
                round(float(median_age), 2) if median_age is not None else None
            ),
            "p95_poll_age_seconds": (
                round(float(p95_age), 2) if p95_age is not None else None
            ),
            "max_poll_age_seconds": (
                round(float(max_age), 2) if max_age is not None else None
            ),
        },
    }


def fetch_policy_features(connection) -> list[dict]:
    rows = connection.execute(
        """
        SELECT
            l.mint,
            l.name,
            l.symbol,
            l.launchpad,
            l.graduated_at_text,
            l.created_at,
            l.observed_at,
            l.unchanged_since,
            l.last_polled_at,
            l.has_mcap,
            l.mcap,
            l.has_liquidity,
            l.liquidity,
            l.has_holder_count,
            l.holders,
            l.stats1h_num_buys,
            l.stats1h_num_sells,
            (l.payload ? 'stats1h') AS has_stats1h,
            h.snapshot_count,
            h.first_snapshot_at,
            h.last_snapshot_at,
            h.peak_mcap,
            h.peak_liquidity,
            h.max_holder_value
        FROM diag_latest AS l
        JOIN diag_history_features AS h ON h.mint = l.mint
        """
    ).fetchall()

    now = datetime.now(timezone.utc)
    features: list[dict] = []

    for row in rows:
        (
            mint,
            name,
            symbol,
            launchpad,
            graduated_at_text,
            created_at,
            observed_at,
            unchanged_since,
            last_polled_at,
            has_mcap,
            mcap,
            has_liquidity,
            liquidity,
            has_holder_count,
            holders,
            buys,
            sells,
            has_stats1h,
            snapshot_count,
            first_snapshot_at,
            last_snapshot_at,
            peak_mcap,
            peak_liquidity,
            peak_holders,
        ) = row

        age_anchor = created_at or first_snapshot_at
        age_minutes = (
            max((now - age_anchor).total_seconds() / 60, 0.0)
            if age_anchor is not None
            else None
        )
        unchanged_minutes = (
            max((last_polled_at - unchanged_since).total_seconds() / 60, 0.0)
            if last_polled_at is not None and unchanged_since is not None
            else None
        )
        poll_age_seconds = (
            max((now - last_polled_at).total_seconds(), 0.0)
            if last_polled_at is not None
            else None
        )

        mcap_drop_pct = None
        if peak_mcap is not None and peak_mcap > 0 and mcap is not None:
            mcap_drop_pct = max((peak_mcap - mcap) / peak_mcap * 100, 0.0)

        liquidity_drop_pct = None
        if (
            peak_liquidity is not None
            and peak_liquidity > 0
            and liquidity is not None
        ):
            liquidity_drop_pct = max(
                (peak_liquidity - liquidity) / peak_liquidity * 100,
                0.0,
            )

        holder_retention_pct = None
        if peak_holders is not None and peak_holders > 0 and holders is not None:
            holder_retention_pct = holders / peak_holders * 100

        graduated_at = None
        if graduated_at_text:
            try:
                graduated_at = datetime.fromisoformat(
                    graduated_at_text.replace("Z", "+00:00")
                )
                if graduated_at.tzinfo is None:
                    graduated_at = graduated_at.replace(tzinfo=timezone.utc)
            except ValueError:
                graduated_at = None

        graduation_age_minutes = (
            max((now - graduated_at).total_seconds() / 60, 0.0)
            if graduated_at is not None
            else None
        )

        features.append(
            {
                "mint": mint,
                "name": name,
                "symbol": symbol,
                "launchpad": launchpad,
                "graduated_at": graduated_at,
                "is_graduated": graduated_at is not None,
                "graduation_age_minutes": graduation_age_minutes,
                "created_at": created_at,
                "latest_observed_at": observed_at,
                "last_polled_at": last_polled_at,
                "age_minutes": age_minutes,
                "unchanged_minutes": unchanged_minutes,
                "poll_age_seconds": poll_age_seconds,
                "has_mcap": bool(has_mcap),
                "mcap": mcap,
                "has_liquidity": bool(has_liquidity),
                "liquidity": liquidity,
                "has_holder_count": bool(has_holder_count),
                "holders": holders,
                "has_stats1h": bool(has_stats1h),
                "stats1h_num_buys": buys,
                "stats1h_num_sells": sells,
                "stats1h_activity": (buys or 0) + (sells or 0),
                "snapshot_count": snapshot_count,
                "first_snapshot_at": first_snapshot_at,
                "last_snapshot_at": last_snapshot_at,
                "peak_mcap": peak_mcap,
                "peak_liquidity": peak_liquidity,
                "peak_holders": peak_holders,
                "mcap_drop_pct": mcap_drop_pct,
                "liquidity_drop_pct": liquidity_drop_pct,
                "holder_retention_pct": holder_retention_pct,
            }
        )

    return features
