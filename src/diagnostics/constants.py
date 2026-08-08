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

DEFAULT_MONITOR_INTERVAL_SECONDS = 300
MONITOR_CONTINUITY_FACTOR = 2.5


DEFAULT_POLICY_CONFIG: dict[str, Any] = {'schema_version': 1, 'collector_health': {'recent_poll_window_seconds': 300, 'min_recent_poll_fraction': 0.95, 'max_p95_poll_age_seconds': 300, 'min_snapshot_coverage_fraction': 0.95}, 'outcome_horizons_minutes': [30, 60, 360, 1440], 'rules': [{'id': 'terminal_liquidity_collapse_strict', 'version': 1, 'enabled': True, 'type': 'terminal_liquidity_collapse', 'persistence_minutes': 15, 'min_consecutive_matches': 3, 'thresholds': {'min_age_minutes': 30, 'min_peak_liquidity': 10000, 'max_current_liquidity': 1.0, 'min_liquidity_drop_pct': 99.9, 'max_current_mcap_or_null': 1000, 'min_unchanged_minutes': 10}}, {'id': 'terminal_liquidity_collapse_mcap_missing', 'version': 1, 'enabled': True, 'type': 'terminal_liquidity_collapse_mcap_missing', 'persistence_minutes': 15, 'min_consecutive_matches': 3, 'thresholds': {'min_age_minutes': 30, 'min_peak_liquidity': 1000, 'max_current_liquidity': 1.0, 'min_liquidity_drop_pct': 99.9, 'min_unchanged_minutes': 15}}, {'id': 'terminal_market_collapse_strict', 'version': 1, 'enabled': True, 'type': 'terminal_market_collapse', 'persistence_minutes': 15, 'min_consecutive_matches': 3, 'thresholds': {'min_age_minutes': 30, 'min_peak_mcap': 40000, 'max_current_mcap': 100, 'min_mcap_drop_pct': 99.5, 'max_current_liquidity': 1000, 'min_unchanged_minutes': 10}}, {'id': 'abandoned_micro_holders_2', 'version': 1, 'enabled': True, 'type': 'abandoned_micro_token', 'persistence_minutes': 30, 'min_consecutive_matches': 4, 'thresholds': {'min_age_minutes': 60, 'max_holders': 2, 'max_current_liquidity': 100, 'max_current_mcap_or_null': 5000, 'min_unchanged_minutes': 30, 'require_zero_stats1h_activity': True}}, {'id': 'abandoned_micro_holders_5', 'version': 1, 'enabled': True, 'type': 'abandoned_micro_token', 'persistence_minutes': 30, 'min_consecutive_matches': 4, 'thresholds': {'min_age_minutes': 60, 'max_holders': 5, 'max_current_liquidity': 100, 'max_current_mcap_or_null': 5000, 'min_unchanged_minutes': 30, 'require_zero_stats1h_activity': True}}, {'id': 'legacy_rust_v6_low_liq_exact', 'version': 1, 'enabled': True, 'type': 'legacy_low_liquidity', 'source_rule': 'LOW_LIQ', 'decision_mode': 'immediate', 'persistence_minutes': 0, 'min_consecutive_matches': 1, 'thresholds': {'min_age_minutes': 60, 'max_current_liquidity': 2000, 'strict_min_age': True}}, {'id': 'legacy_rust_v6_pre_migration_stale_exact', 'version': 1, 'enabled': True, 'type': 'legacy_pre_migration_stale', 'source_rule': 'PRE_MIGRATION_STALE', 'decision_mode': 'immediate', 'persistence_minutes': 0, 'min_consecutive_matches': 1, 'thresholds': {'min_age_minutes': 1440, 'max_peak_mcap': 5000, 'strict_min_age': True}}], 'protected_mints': ['So11111111111111111111111111111111111111112', 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v', 'Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB', 'USD1ttGY1N17NEEHLmELoaybftRBUSErhqYiQzvEmuB'], 'legacy_rust_v6': {'directly_translated': ['LOW_LIQ', 'PRE_MIGRATION_STALE'], 'not_translated': {'ZOMBIE_SHIELD': 'requires fees and fee_signal_age', 'ZOMBIE': 'requires fees and fee_signal_age', 'FAILED': 'requires fees and old mint_to_pool has_pool semantics', 'DUST': 'requires old mint_to_pool has_pool semantics', 'BOT': 'requires fees', 'EARLY_INACTIVE': 'requires fees and old mint_to_pool has_pool semantics', 'NO_POOL_STALE': 'requires old mint_to_pool has_pool semantics', 'PRE_MIGRATION_INACTIVE': 'requires fees and old mint_to_pool has_pool semantics', 'GRADUATED_STALE': 'requires fees'}}}

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