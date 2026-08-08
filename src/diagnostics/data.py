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
            s.payload->>'updatedAt' AS updated_at_text,

            COALESCE(s.payload ? 'liquidity', false) AS has_liquidity,
            (s.payload->>'liquidity')::float8 AS liquidity,
            s.payload->>'liquidity' AS liquidity_text,

            COALESCE(s.payload ? 'mcap', false) AS has_mcap,
            (s.payload->>'mcap')::float8 AS mcap,
            s.payload->>'mcap' AS mcap_text,

            COALESCE(s.payload ? 'holderCount', false) AS has_holder_count,
            (s.payload->>'holderCount')::int AS holders,
            s.payload->>'holderCount' AS holders_text,

            (s.payload ? 'stats5m') AS has_stats5m,
            (s.payload->'stats5m'->>'numBuys')::int AS stats5m_num_buys,
            (s.payload->'stats5m'->>'numSells')::int AS stats5m_num_sells,
            (s.payload->'stats5m'->>'numTraders')::int AS stats5m_num_traders,
            (s.payload->'stats5m'->>'buyVolume')::float8 AS stats5m_buy_volume,
            (s.payload->'stats5m'->>'sellVolume')::float8 AS stats5m_sell_volume,

            (s.payload ? 'stats1h') AS has_stats1h,
            (s.payload->'stats1h'->>'numBuys')::int AS stats1h_num_buys,
            (s.payload->'stats1h'->>'numSells')::int AS stats1h_num_sells,
            (s.payload->'stats1h'->>'numTraders')::int AS stats1h_num_traders,
            (s.payload->'stats1h'->>'buyVolume')::float8 AS stats1h_buy_volume,
            (s.payload->'stats1h'->>'sellVolume')::float8 AS stats1h_sell_volume,

            (s.payload->'audit'->>'isSus')::boolean AS audit_is_sus,
            (s.payload->'audit'->>'devMints')::int AS audit_dev_mints,
            (s.payload->'audit'->>'devMigrations')::int AS audit_dev_migrations,
            (s.payload->'audit'->>'devBalancePercentage')::float8 AS audit_dev_balance_pct,
            (s.payload->'audit'->>'topHoldersPercentage')::float8 AS audit_top_holders_pct,

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
                ) AS latest_met_dbc_graduated_observed_at,

                COUNT(*) FILTER (
                    WHERE s.payload ? 'stats5m'
                ) AS stats5m_snapshot_count,
                COUNT(*) FILTER (
                    WHERE COALESCE((s.payload->'stats5m'->>'numBuys')::int, 0)
                        + COALESCE((s.payload->'stats5m'->>'numSells')::int, 0) > 0
                       OR COALESCE((s.payload->'stats5m'->>'buyVolume')::float8, 0) > 0
                       OR COALESCE((s.payload->'stats5m'->>'sellVolume')::float8, 0) > 0
                ) AS stats5m_active_snapshot_count,
                MAX(s.observed_at) FILTER (
                    WHERE COALESCE((s.payload->'stats5m'->>'numBuys')::int, 0)
                        + COALESCE((s.payload->'stats5m'->>'numSells')::int, 0) > 0
                       OR COALESCE((s.payload->'stats5m'->>'buyVolume')::float8, 0) > 0
                       OR COALESCE((s.payload->'stats5m'->>'sellVolume')::float8, 0) > 0
                ) AS last_stats5m_activity_at
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


def build_gmgn_cache(connection) -> None:
    """Optionaler, rein lesender GMGN-Latest-Join.

    GMGN ist Referenz-Evidence und nie Voraussetzung fuer eine Entscheidung.
    Es wird weder eine Lifecycle- noch eine abgeleitete permanente Tabelle
    erzeugt. Fehlt die Quelltabelle, hat die TEMP TABLE einfach null Zeilen.
    """
    exists = connection.execute(
        "SELECT to_regclass('gmgn_mint_observations') IS NOT NULL"
    ).fetchone()[0]
    if not exists:
        connection.execute(
            """
            CREATE TEMP TABLE diag_gmgn_latest (
                mint text, run_id timestamptz, source text,
                market_cap float8, liquidity float8, volume_24h float8,
                holder_count int, buys_24h int, sells_24h int, swaps_24h int,
                net_buy_24h float8, rug_ratio float8, entrapment_ratio float8,
                dev_team_hold_rate float8, creator_token_status text,
                creator_created_count int, creator_created_open_ratio float8,
                bot_degen_count int, bot_degen_rate float8,
                smart_degen_count int, bundler_mhr float8,
                bundler_trader_amount_rate float8, sniper_count int,
                top70_sniper_hold_rate float8, fresh_wallet_rate float8,
                suspected_insider_hold_rate float8, burn_status text,
                is_honeypot boolean, is_wash_trading boolean,
                progress float8, complete_timestamp float8,
                launchpad_platform text, has_social boolean
            ) ON COMMIT DROP
            """
        )
        return

    connection.execute(
        """
        CREATE TEMP TABLE diag_gmgn_latest ON COMMIT DROP AS
        SELECT DISTINCT ON (g.mint)
            g.mint,
            g.run_id,
            g.source,
            g.market_cap,
            g.liquidity,
            g.volume_24h,
            g.holder_count,
            (g.raw_data->>'buys_24h')::int AS buys_24h,
            (g.raw_data->>'sells_24h')::int AS sells_24h,
            (g.raw_data->>'swaps_24h')::int AS swaps_24h,
            (g.raw_data->>'net_buy_24h')::float8 AS net_buy_24h,
            g.rug_ratio,
            g.entrapment_ratio,
            g.dev_team_hold_rate,
            g.creator_token_status,
            g.creator_created_count,
            g.creator_created_open_ratio,
            g.bot_degen_count,
            g.bot_degen_rate,
            g.smart_degen_count,
            g.bundler_mhr,
            g.bundler_trader_amount_rate,
            g.sniper_count,
            g.top70_sniper_hold_rate,
            g.fresh_wallet_rate,
            g.suspected_insider_hold_rate,
            g.burn_status,
            g.is_honeypot,
            g.is_wash_trading,
            (g.raw_data->>'progress')::float8 AS progress,
            (g.raw_data->>'complete_timestamp')::float8 AS complete_timestamp,
            g.raw_data->>'launchpad_platform' AS launchpad_platform,
            COALESCE((g.raw_data->>'has_at_least_one_social')::boolean, false)
                AS has_social
        FROM gmgn_mint_observations AS g
        ORDER BY g.mint, g.run_id DESC
        """
    )
    connection.execute("ANALYZE diag_gmgn_latest")


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
            l.updated_at_text,
            l.has_mcap,
            l.mcap,
            l.has_liquidity,
            l.liquidity,
            l.has_holder_count,
            l.holders,
            l.has_stats5m,
            l.stats5m_num_buys,
            l.stats5m_num_sells,
            l.stats5m_num_traders,
            l.stats5m_buy_volume,
            l.stats5m_sell_volume,
            l.has_stats1h,
            l.stats1h_num_buys,
            l.stats1h_num_sells,
            l.stats1h_num_traders,
            l.stats1h_buy_volume,
            l.stats1h_sell_volume,
            l.audit_is_sus,
            l.audit_dev_mints,
            l.audit_dev_migrations,
            l.audit_dev_balance_pct,
            l.audit_top_holders_pct,
            h.snapshot_count,
            h.first_snapshot_at,
            h.last_snapshot_at,
            h.peak_mcap,
            h.peak_liquidity,
            h.max_holder_value,
            h.stats5m_snapshot_count,
            h.stats5m_active_snapshot_count,
            h.last_stats5m_activity_at,
            g.run_id AS gmgn_observed_at,
            g.source AS gmgn_source,
            g.market_cap AS gmgn_market_cap,
            g.liquidity AS gmgn_liquidity,
            g.volume_24h AS gmgn_volume_24h,
            g.holder_count AS gmgn_holder_count,
            g.buys_24h AS gmgn_buys_24h,
            g.sells_24h AS gmgn_sells_24h,
            g.swaps_24h AS gmgn_swaps_24h,
            g.net_buy_24h AS gmgn_net_buy_24h,
            g.rug_ratio AS gmgn_rug_ratio,
            g.entrapment_ratio AS gmgn_entrapment_ratio,
            g.dev_team_hold_rate AS gmgn_dev_team_hold_rate,
            g.creator_token_status AS gmgn_creator_token_status,
            g.creator_created_count AS gmgn_creator_created_count,
            g.creator_created_open_ratio AS gmgn_creator_created_open_ratio,
            g.bot_degen_count AS gmgn_bot_degen_count,
            g.bot_degen_rate AS gmgn_bot_degen_rate,
            g.smart_degen_count AS gmgn_smart_degen_count,
            g.bundler_mhr AS gmgn_bundler_mhr,
            g.bundler_trader_amount_rate AS gmgn_bundler_trader_amount_rate,
            g.sniper_count AS gmgn_sniper_count,
            g.top70_sniper_hold_rate AS gmgn_top70_sniper_hold_rate,
            g.fresh_wallet_rate AS gmgn_fresh_wallet_rate,
            g.suspected_insider_hold_rate AS gmgn_suspected_insider_hold_rate,
            g.burn_status AS gmgn_burn_status,
            g.is_honeypot AS gmgn_is_honeypot,
            g.is_wash_trading AS gmgn_is_wash_trading,
            g.progress AS gmgn_progress,
            g.complete_timestamp AS gmgn_complete_timestamp,
            g.launchpad_platform AS gmgn_launchpad_platform,
            g.has_social AS gmgn_has_social
        FROM diag_latest AS l
        JOIN diag_history_features AS h ON h.mint = l.mint
        LEFT JOIN diag_gmgn_latest AS g ON g.mint = l.mint
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
            updated_at_text,
            has_mcap,
            mcap,
            has_liquidity,
            liquidity,
            has_holder_count,
            holders,
            has_stats5m,
            stats5m_buys,
            stats5m_sells,
            stats5m_traders,
            stats5m_buy_volume,
            stats5m_sell_volume,
            has_stats1h,
            buys,
            sells,
            stats1h_traders,
            stats1h_buy_volume,
            stats1h_sell_volume,
            audit_is_sus,
            audit_dev_mints,
            audit_dev_migrations,
            audit_dev_balance_pct,
            audit_top_holders_pct,
            snapshot_count,
            first_snapshot_at,
            last_snapshot_at,
            peak_mcap,
            peak_liquidity,
            peak_holders,
            stats5m_snapshot_count,
            stats5m_active_snapshot_count,
            last_stats5m_activity_at,
            gmgn_observed_at,
            gmgn_source,
            gmgn_market_cap,
            gmgn_liquidity,
            gmgn_volume_24h,
            gmgn_holder_count,
            gmgn_buys_24h,
            gmgn_sells_24h,
            gmgn_swaps_24h,
            gmgn_net_buy_24h,
            gmgn_rug_ratio,
            gmgn_entrapment_ratio,
            gmgn_dev_team_hold_rate,
            gmgn_creator_token_status,
            gmgn_creator_created_count,
            gmgn_creator_created_open_ratio,
            gmgn_bot_degen_count,
            gmgn_bot_degen_rate,
            gmgn_smart_degen_count,
            gmgn_bundler_mhr,
            gmgn_bundler_trader_amount_rate,
            gmgn_sniper_count,
            gmgn_top70_sniper_hold_rate,
            gmgn_fresh_wallet_rate,
            gmgn_suspected_insider_hold_rate,
            gmgn_burn_status,
            gmgn_is_honeypot,
            gmgn_is_wash_trading,
            gmgn_progress,
            gmgn_complete_timestamp,
            gmgn_launchpad_platform,
            gmgn_has_social,
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

        stats5m_activity = None
        if has_stats5m:
            stats5m_activity = (stats5m_buys or 0) + (stats5m_sells or 0)
        stats1h_activity = None
        if has_stats1h:
            stats1h_activity = (buys or 0) + (sells or 0)

        minutes_since_stats5m_activity = (
            max((now - last_stats5m_activity_at).total_seconds() / 60, 0.0)
            if last_stats5m_activity_at is not None
            else None
        )
        gmgn_age_minutes = (
            max((now - gmgn_observed_at).total_seconds() / 60, 0.0)
            if gmgn_observed_at is not None
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
                "updated_at_text": updated_at_text,
                "age_minutes": age_minutes,
                "unchanged_minutes": unchanged_minutes,
                "poll_age_seconds": poll_age_seconds,
                "has_mcap": bool(has_mcap),
                "mcap": mcap,
                "has_liquidity": bool(has_liquidity),
                "liquidity": liquidity,
                "has_holder_count": bool(has_holder_count),
                "holders": holders,
                "has_stats5m": bool(has_stats5m),
                "stats5m_num_buys": stats5m_buys,
                "stats5m_num_sells": stats5m_sells,
                "stats5m_num_traders": stats5m_traders,
                "stats5m_buy_volume": stats5m_buy_volume,
                "stats5m_sell_volume": stats5m_sell_volume,
                "stats5m_activity": stats5m_activity,
                "has_stats1h": bool(has_stats1h),
                "stats1h_num_buys": buys,
                "stats1h_num_sells": sells,
                "stats1h_num_traders": stats1h_traders,
                "stats1h_buy_volume": stats1h_buy_volume,
                "stats1h_sell_volume": stats1h_sell_volume,
                "stats1h_activity": stats1h_activity,
                "audit_is_sus": audit_is_sus,
                "audit_dev_mints": audit_dev_mints,
                "audit_dev_migrations": audit_dev_migrations,
                "audit_dev_balance_pct": audit_dev_balance_pct,
                "audit_top_holders_pct": audit_top_holders_pct,
                "snapshot_count": snapshot_count,
                "first_snapshot_at": first_snapshot_at,
                "last_snapshot_at": last_snapshot_at,
                "peak_mcap": peak_mcap,
                "peak_liquidity": peak_liquidity,
                "peak_holders": peak_holders,
                "stats5m_snapshot_count": stats5m_snapshot_count,
                "stats5m_active_snapshot_count": stats5m_active_snapshot_count,
                "ever_had_stats5m_activity": bool(stats5m_active_snapshot_count),
                "last_stats5m_activity_at": last_stats5m_activity_at,
                "minutes_since_stats5m_activity": minutes_since_stats5m_activity,
                "activity_extinguished": bool(stats5m_active_snapshot_count)
                and stats5m_activity in (None, 0),
                "mcap_drop_pct": mcap_drop_pct,
                "liquidity_drop_pct": liquidity_drop_pct,
                "holder_retention_pct": holder_retention_pct,
                "gmgn_available": gmgn_observed_at is not None,
                "gmgn_observed_at": gmgn_observed_at,
                "gmgn_age_minutes": gmgn_age_minutes,
                "gmgn_source": gmgn_source,
                "gmgn_market_cap": gmgn_market_cap,
                "gmgn_liquidity": gmgn_liquidity,
                "gmgn_volume_24h": gmgn_volume_24h,
                "gmgn_holder_count": gmgn_holder_count,
                "gmgn_buys_24h": gmgn_buys_24h,
                "gmgn_sells_24h": gmgn_sells_24h,
                "gmgn_swaps_24h": gmgn_swaps_24h,
                "gmgn_net_buy_24h": gmgn_net_buy_24h,
                "gmgn_rug_ratio": gmgn_rug_ratio,
                "gmgn_entrapment_ratio": gmgn_entrapment_ratio,
                "gmgn_dev_team_hold_rate": gmgn_dev_team_hold_rate,
                "gmgn_creator_token_status": gmgn_creator_token_status,
                "gmgn_creator_created_count": gmgn_creator_created_count,
                "gmgn_creator_created_open_ratio": gmgn_creator_created_open_ratio,
                "gmgn_bot_degen_count": gmgn_bot_degen_count,
                "gmgn_bot_degen_rate": gmgn_bot_degen_rate,
                "gmgn_smart_degen_count": gmgn_smart_degen_count,
                "gmgn_bundler_mhr": gmgn_bundler_mhr,
                "gmgn_bundler_trader_amount_rate": gmgn_bundler_trader_amount_rate,
                "gmgn_sniper_count": gmgn_sniper_count,
                "gmgn_top70_sniper_hold_rate": gmgn_top70_sniper_hold_rate,
                "gmgn_fresh_wallet_rate": gmgn_fresh_wallet_rate,
                "gmgn_suspected_insider_hold_rate": gmgn_suspected_insider_hold_rate,
                "gmgn_burn_status": gmgn_burn_status,
                "gmgn_is_honeypot": gmgn_is_honeypot,
                "gmgn_is_wash_trading": gmgn_is_wash_trading,
                "gmgn_progress": gmgn_progress,
                "gmgn_complete_timestamp": gmgn_complete_timestamp,
                "gmgn_launchpad_platform": gmgn_launchpad_platform,
                "gmgn_has_social": gmgn_has_social,
            }
        )

    return features
