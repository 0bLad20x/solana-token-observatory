from __future__ import annotations

from pathlib import Path
from typing import Any

SAMPLE_LIMIT = 5

# diagnose_inactivity.py liegt unter <project>/src/.
# Persistente Diagnose-Artefakte leben gesammelt unter <project>/data/.
# Damit bleibt das Projektroot sauber und alle Pfade bleiben unabhaengig vom
# aktuellen PowerShell-Arbeitsverzeichnis.
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[1]
DATA_DIR = PROJECT_ROOT / "data"
ANALYSIS_DIR = PROJECT_ROOT / "analysis"

OUTPUT_PATH = DATA_DIR / "investigation_report.json"
POLICY_RULES_PATH = DATA_DIR / "policy_rules.json"
POLICY_RUNS_PATH = DATA_DIR / "policy_runs.jsonl"
DECISION_EVENTS_PATH = DATA_DIR / "decision_events.jsonl"
POLICY_STATE_PATH = DATA_DIR / "policy_state.json"
POPULATION_DISTRIBUTION_SVG_PATH = DATA_DIR / "population_distribution.svg"
REGION_SNAPSHOT_PATH = DATA_DIR / "region_snapshot.json"
REGION_DEGRADED_SNAPSHOT_PATH = DATA_DIR / "region_snapshot_degraded.json"
POLICY_OUTCOMES_PATH = DATA_DIR / "policy_outcomes.json"

# Phase 2/3 artifacts. region_state.json is the compact per-mint current state,
# the jsonl files only grow on real state changes, and the two derived *.json
# files are what the dashboard reads (rendering stays downstream of analysis).
REGION_STATE_PATH = DATA_DIR / "region_state.json"
REGION_TRANSITIONS_PATH = DATA_DIR / "region_transition_events.jsonl"
REGION_POPULATION_RUNS_PATH = DATA_DIR / "region_population_runs.jsonl"
REGION_FLOW_PATH = DATA_DIR / "region_flow.json"
COHORT_OUTCOMES_PATH = DATA_DIR / "cohort_outcomes.json"

# Human-readable methodology and one bounded, machine-readable export.  The
# export is intentionally overwritten instead of archived on every monitor
# cycle so Git repositories do not grow with redundant snapshots.
PHASE_GUIDE_PATH = ANALYSIS_DIR / "DIAGNOSTIC_PHASES.md"
AI_ANALYSIS_BUNDLE_PATH = ANALYSIS_DIR / "diagnostics_ai_bundle.json"

# How much history the derived artifacts look back on.
REGION_FLOW_WINDOW_HOURS = 24
REGION_POPULATION_RUN_LIMIT = 2_016  # ~7 days at a 5-minute cadence

# A first monitor run emits one ENTER event per tracked mint, so event count
# alone is a useless readiness signal. Phase 2 only counts as usable once real
# movement has been observed across enough distinct mints.
REGION_FLOW_MIN_MOVES = 500
REGION_FLOW_MIN_MOVING_MINTS = 200
COHORT_HORIZONS_MINUTES = [30, 60, 180, 360, 1_440]

MCAP_DISTRIBUTION_THRESHOLDS = [
    100, 200, 500, 1_000, 2_000, 5_000, 10_000, 25_000, 50_000,
    100_000, 250_000, 500_000, 1_000_000, 5_000_000, 10_000_000,
]
LIQUIDITY_DISTRIBUTION_THRESHOLDS = [
    0.01, 0.1, 1, 10, 100, 500, 1_000, 2_000, 5_000, 10_000,
    25_000, 50_000, 100_000, 500_000, 1_000_000,
]

AGE_DISTRIBUTION_BUCKETS = [
    ("under_30m", "<30m", 0.0, 30.0),
    ("30_60m", "30-60m", 30.0, 60.0),
    ("1_3h", "1-3h", 60.0, 180.0),
    ("3_8h", "3-8h", 180.0, 480.0),
    ("8h_plus", ">=8h", 480.0, None),
]

JOINT_DENSITY_X_BINS = 24
JOINT_DENSITY_Y_BINS = 20

DEFAULT_MONITOR_INTERVAL_SECONDS = 60
MONITOR_CONTINUITY_FACTOR = 2.5


DEFAULT_POLICY_CONFIG: dict[str, Any] = {
    "schema_version": 2,
    "collector_health": {
        "recent_poll_window_seconds": 300,
        "min_recent_poll_fraction": 0.95,
        "max_p95_poll_age_seconds": 300,
        "min_snapshot_coverage_fraction": 0.95,
    },
    "priority_cadences_seconds": {"p1": 60, "p2": 300, "p3": 3600},
    "outcome_horizons_minutes": [5, 15, 30, 60, 360, 1440],
    "outcome_thresholds": {
        "weak_escape_mcap": 10_000,
        "relevant_escape_mcap": 50_000,
        "success_mcap": 200_000,
        "min_recovery_liquidity": 1_000,
    },
    "rules": [
        {
            "id": "liquidity_removed_hard",
            "version": 1,
            "enabled": True,
            "type": "terminal_liquidity_collapse",
            "action": "retire",
            "confirmation": "immediate",
            "persistence_minutes": 0,
            "min_poll_confirmations": 1,
            "thresholds": {
                "min_age_minutes": 0,
                "min_peak_liquidity": 5_000,
                "max_current_liquidity": 1.0,
                "min_liquidity_drop_pct": 99.99,
                "max_current_mcap_or_null": 1_000,
                "max_poll_age_seconds": 300,
            },
        },
        {
            "id": "failed_at_birth_floor",
            "version": 1,
            "enabled": True,
            "type": "failed_at_birth",
            "action": "retire",
            "confirmation": "poll_confirmed",
            "persistence_minutes": 0,
            "min_poll_confirmations": 1,
            "thresholds": {
                "min_age_minutes": 0.5,
                "max_age_minutes": 10,
                "max_current_mcap": 2_500,
                "max_current_liquidity": 5_000,
                "max_peak_mcap": 5_000,
                "max_holders": 3,
                "max_poll_age_seconds": 180,
            },
        },
        {
            "id": "early_floor_uncertain_p2",
            "version": 1,
            "enabled": True,
            "type": "floor_low_signal",
            "action": "p2",
            "confirmation": "immediate",
            "persistence_minutes": 0,
            "min_poll_confirmations": 1,
            "thresholds": {
                "min_age_minutes": 1,
                "max_age_minutes": 30,
                "min_current_mcap": 1_500,
                "max_current_mcap": 5_000,
                "max_current_liquidity": 10_000,
                "max_holders": 20,
                "max_stats5m_buys": 2,
                "max_stats5m_buy_volume": 100,
                "max_poll_age_seconds": 300,
            },
        },
        {
            "id": "pre_migration_return_to_floor",
            "version": 1,
            "enabled": True,
            "type": "pre_migration_floor_return",
            "action": "retire",
            "confirmation": "poll_confirmed",
            "persistence_minutes": 1,
            "min_poll_confirmations": 2,
            "thresholds": {
                "min_age_minutes": 5,
                "min_peak_mcap": 10_000,
                "max_current_mcap": 3_000,
                "max_current_liquidity": 5_000,
                "min_mcap_drop_pct": 75,
                "max_holder_retention_pct": 30,
                "max_holders_without_retention": 5,
                "max_stats5m_buys": 2,
                "max_stats5m_buy_volume": 100,
                "max_poll_age_seconds": 300,
            },
        },
        {
            "id": "micro_pool_exhausted",
            "version": 1,
            "enabled": True,
            "type": "micro_pool_exhausted",
            "action": "retire",
            "confirmation": "poll_confirmed",
            "persistence_minutes": 2,
            "min_poll_confirmations": 2,
            "thresholds": {
                "min_age_minutes": 5,
                "max_current_mcap": 5_000,
                "max_current_liquidity": 100,
                "max_holders": 5,
                "max_stats5m_buys": 0,
                "max_stats5m_buy_volume": 0,
                "max_poll_age_seconds": 300,
            },
        },
        {
            "id": "graveyard_low_signal_p3",
            "version": 1,
            "enabled": True,
            "type": "graveyard_stalled",
            "action": "p3",
            "confirmation": "poll_confirmed",
            "persistence_minutes": 2,
            "min_poll_confirmations": 2,
            "thresholds": {
                "min_age_minutes": 15,
                "min_current_mcap": 2_000,
                "max_current_mcap": 5_000,
                "min_current_liquidity": 2_000,
                "max_current_liquidity": 10_000,
                "max_holders": 10,
                "max_stats5m_buys": 0,
                "max_stats5m_buy_volume": 0,
                "min_unchanged_minutes": 5,
                "max_poll_age_seconds": 300,
            },
        },
        {
            "id": "graveyard_confirmed_retire",
            "version": 1,
            "enabled": True,
            "type": "graveyard_stalled",
            "action": "retire",
            "confirmation": "poll_confirmed",
            "persistence_minutes": 2,
            "min_poll_confirmations": 2,
            "thresholds": {
                "min_age_minutes": 25,
                "min_current_mcap": 2_000,
                "max_current_mcap": 5_000,
                "min_current_liquidity": 2_000,
                "max_current_liquidity": 10_000,
                "max_holders": 10,
                "max_stats5m_buys": 0,
                "max_stats5m_buy_volume": 0,
                "min_unchanged_minutes": 10,
                "max_poll_age_seconds": 300,
            },
        },
    ],
    "protected_mints": [
        "So11111111111111111111111111111111111111112",
        "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
        "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
        "USD1ttGY1N17NEEHLmELoaybftRBUSErhqYiQzvEmuB",
    ],
}

# Alle Bedingungen arbeiten nach dem einmaligen Aufbau von diag_latest nur noch
# auf typisierten Spalten einer kleinen TEMP TABLE. Keine dieser Definitionen
# greift direkt auf mint_snapshots zu.
CATEGORY_SPECS = [
    (
        "liquidity_below_0_01_but_field_present",
        "has_liquidity AND liquidity < 0.01",
        "liquidity ASC",
    ),
    (
        "price_change_24h_below_minus_99",
        "has_stats24h_price_change AND stats24h_price_change <= -99",
        "stats24h_price_change ASC",
    ),
    (
        "no_update_for_more_than_10min",
        "unchanged_since IS NOT NULL AND (last_polled_at - unchanged_since) > interval '10 minutes'",
        "unchanged_since ASC",
    ),
    (
        "high_holders_but_near_zero_liquidity",
        "has_liquidity AND liquidity < 0.01 AND has_holder_count AND holders >= 10",
        "holders DESC",
    ),
    (
        "very_young_already_crashed",
        "created_at > now() - interval '30 minutes' AND has_liquidity AND liquidity < 0.01",
        "created_at DESC",
    ),
    (
        "graduated_long_ago_still_near_peak",
        "graduated_at_text IS NOT NULL AND has_liquidity AND liquidity > 1000",
        "graduated_at_text ASC",
    ),
    (
        "launchpad_is_null",
        "launchpad IS NULL",
        "created_at DESC",
    ),
    (
        "null_launchpad_and_crashed",
        "launchpad IS NULL AND has_liquidity AND liquidity < 0.01",
        "created_at DESC",
    ),
    (
        "mcap_liquidity_ratio_over_1000",
        "has_mcap AND mcap IS NOT NULL AND has_liquidity AND liquidity > 0 "
        "AND mcap / liquidity > 1000",
        "mcap / liquidity DESC",
    ),
    (
        "high_mcap_tiny_holder_count",
        "has_mcap AND mcap IS NOT NULL AND mcap > 100000 "
        "AND has_holder_count AND holders < 20",
        "mcap DESC",
    ),
    (
        "deep_liquidity_tiny_holder_count",
        "has_liquidity AND liquidity > 10000 "
        "AND has_holder_count AND holders < 10 "
        "AND COALESCE(stats1h_num_buys, 0) + COALESCE(stats1h_num_sells, 0) = 0",
        "liquidity DESC",
    ),
    (
        "zero_trading_activity_stats1h",
        "created_at < now() - interval '1 hour' AND "
        "COALESCE(stats1h_num_buys, 0) + COALESCE(stats1h_num_sells, 0) = 0",
        "created_at ASC",
    ),
    (
        "zero_activity_and_stale_15min_plus",
        "created_at < now() - interval '1 hour' AND "
        "COALESCE(stats1h_num_buys, 0) + COALESCE(stats1h_num_sells, 0) = 0 AND "
        "unchanged_since IS NOT NULL AND "
        "EXTRACT(EPOCH FROM (last_polled_at - unchanged_since)) / 60 >= 15",
        "unchanged_since ASC",
    ),
]
