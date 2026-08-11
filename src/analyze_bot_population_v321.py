from __future__ import annotations

import argparse
import bisect
import csv
import json
import math
import os
import random
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any

from dotenv import load_dotenv

from bot_detection_v321 import (
    ANOMALY_LEVEL_RANK,
    BOT_LEVEL_RANK,
    CHECKPOINTS,
    DETECTOR_BY_NAME,
    detector_registry,
    evaluate_token,
    make_temporal_point,
    parse_timestamp,
)


ROOT = Path(__file__).resolve().parents[1]
ANALYSIS_DIR = ROOT / "analysis"

OUT_JSON = ANALYSIS_DIR / "bot_detection_v321.json"
OUT_REVIEW_CSV = ANALYSIS_DIR / "bot_detection_review_v321.csv"
OUT_CALIBRATION_CSV = ANALYSIS_DIR / "bot_rule_calibration_v321.csv"
OUT_MEMBERSHIP_CSV = ANALYSIS_DIR / "bot_archetype_membership_v321.csv"
OUT_FEATURE_VECTORS_CSV = ANALYSIS_DIR / "bot_feature_vectors_v321.csv"
OUT_PRESENCE_CSV = ANALYSIS_DIR / "bot_feature_presence_v321.csv"
OUT_AI_JSONL = ANALYSIS_DIR / "bot_ai_analysis_bundle_v321.jsonl"
OUT_BLIND_CSV = ANALYSIS_DIR / "bot_blind_stratified_control_v321.csv"
LABELS_CANONICAL_CSV = ANALYSIS_DIR / "bot_manual_labels.csv"
REPLAY_MODE = "CURRENT_SURVIVOR_RESEARCH"

MAX_HISTORY_MINUTES = max(CHECKPOINTS)
STATEMENT_TIMEOUT_MS = 180_000
TOP_PRINT = 50

COHORT_MIN_SIZE = 50
MATRIX_EXTREME_SINGLE = 0.999
MATRIX_EXTREME_MULTI = 0.990
BLIND_SAMPLE_TARGET = 120
BLIND_SAMPLE_SEED = 20260810

# High-percentile means "unusually large" for these diagnostics.
COHORT_FEATURES: dict[str, str] = {
    "trades_per_hour": "ACTIVITY",
    "turnover_liquidity_per_hour": "ACTIVITY",
    "trades_per_trader_per_hour": "MECHANICAL",
    "volume_symmetry": "MECHANICAL",
    "trade_count_symmetry": "MECHANICAL",
    "trade_size_symmetry": "MECHANICAL",
    "trades_per_holder": "PARTICIPATION",
    "net_buyer_absence": "PARTICIPATION",
    "price_impact_per_turnover": "ECONOMIC_RESPONSE",
    "churn_per_response": "ECONOMIC_RESPONSE",
}


# =============================================================================
# Canonical manual-label ledger
# =============================================================================

LABEL_FIELDS = [
    "mint",
    "bot_label",
    "retire_label",
    "label_source",
    "review_mode",
    "reviewed_at",
    "notes",
]


def _infer_review_mode(notes: str) -> str:
    n = notes.lower()
    if "blind_random" in n:
        return "blind_random"
    if "blind" in n:
        return "blind_stratified"
    if "manual_reference" in n or "organic_control" in n:
        return "known_reference"
    return "targeted"


def _read_label_rows(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    if not path.exists():
        return [], []
    with path.open("r", newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        return list(reader), list(reader.fieldnames or [])


def _normalize_label_row(row: dict[str, str], source: Path) -> dict[str, str] | None:
    mint = (row.get("mint") or "").strip()
    if not mint:
        return None

    if "bot_label" in row:
        bot_label = (row.get("bot_label") or "UNSURE").strip().upper()
        retire_label = (row.get("retire_label") or "UNSURE").strip().upper()
    else:
        old = (row.get("label") or "").strip().upper()
        bot_label = "BOT" if old == "BOT" else (
            "NON_BOT" if old == "ORGANIC" else "UNSURE"
        )
        retire_label = "RETIRE" if old == "BOT" else (
            "KEEP" if old == "ORGANIC" else "UNSURE"
        )

    if bot_label not in {"BOT", "NON_BOT", "UNSURE"}:
        bot_label = "UNSURE"
    if retire_label not in {"RETIRE", "KEEP", "UNSURE"}:
        retire_label = "UNSURE"

    notes = (row.get("notes") or "").strip()
    return {
        "mint": mint,
        "bot_label": bot_label,
        "retire_label": retire_label,
        "label_source": (row.get("label_source") or source.name).strip(),
        "review_mode": (
            row.get("review_mode") or _infer_review_mode(notes)
        ).strip(),
        "reviewed_at": (row.get("reviewed_at") or "").strip(),
        "notes": notes,
    }


def ensure_label_file() -> None:
    """
    Consolidate every historical manual-label file into one durable ledger.

    If bot_manual_labels.csv is already in the new schema it is authoritative;
    legacy/versioned files may only add missing mints. If it is an old V2
    label/notes file, it is migrated and then enriched by later version files.
    """
    ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)

    canonical_rows, canonical_fields = _read_label_rows(LABELS_CANONICAL_CSV)
    canonical_is_new = "bot_label" in canonical_fields

    versioned = sorted(
        p for p in ANALYSIS_DIR.glob("bot_manual_labels_v*.csv")
        if p != LABELS_CANONICAL_CSV
    )

    if canonical_is_new:
        sources = versioned + [LABELS_CANONICAL_CSV]
    else:
        sources = ([LABELS_CANONICAL_CSV] if LABELS_CANONICAL_CSV.exists() else []) + versioned

    merged: dict[str, dict[str, str]] = {}
    for source in sources:
        rows, _ = _read_label_rows(source)
        for row in rows:
            normalized = _normalize_label_row(row, source)
            if normalized is None:
                continue
            mint = normalized["mint"]
            old = merged.get(mint)
            if old is None:
                merged[mint] = normalized
                continue

            # Later evidence can strengthen UNKNOWN values, but never erase a
            # concrete manual label with UNSURE.
            for key in ("bot_label", "retire_label"):
                if normalized[key] != "UNSURE":
                    old[key] = normalized[key]
            for key in ("label_source", "review_mode", "reviewed_at", "notes"):
                if normalized.get(key):
                    old[key] = normalized[key]

    with LABELS_CANONICAL_CSV.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=LABEL_FIELDS)
        writer.writeheader()
        for mint in sorted(merged):
            writer.writerow(merged[mint])


def load_labels() -> dict[str, dict[str, str]]:
    ensure_label_file()
    result: dict[str, dict[str, str]] = {}

    rows, _ = _read_label_rows(LABELS_CANONICAL_CSV)
    for row in rows:
        normalized = _normalize_label_row(row, LABELS_CANONICAL_CSV)
        if normalized is None:
            continue
        result[normalized["mint"]] = {
            key: normalized[key]
            for key in LABEL_FIELDS
            if key != "mint"
        }
    return result


# =============================================================================
# Database replay
# =============================================================================

BASE_QUERY = """
SELECT
    m.mint,
    m.name,
    m.symbol,
    m.tracking_enabled,
    m.last_polled_at,
    m.first_observed_at AS tracking_started_at,
    m.last_changed_at AS latest_state_observed_at,
    m.source_updated_at AS latest_source_updated_at
FROM mints m
WHERE (m.tracking_enabled = true OR m.mint = ANY(%s))
  AND m.first_observed_at IS NOT NULL
ORDER BY m.mint
"""


def values_sql() -> str:
    return ", ".join(f"({checkpoint})" for checkpoint in CHECKPOINTS)


REPLAY_QUERY = f"""
WITH base AS (
    SELECT *
    FROM unnest(
        %s::text[],
        %s::timestamptz[],
        %s::timestamptz[]
    ) AS t(
        mint,
        tracking_started_at,
        last_polled_at
    )
),
checkpoints(minutes) AS (
    VALUES {values_sql()}
)
SELECT
    b.mint,
    c.minutes AS checkpoint_minutes,
    b.tracking_started_at
        + make_interval(mins => c.minutes) AS decision_at,
    state.observed_at AS state_observed_at,
    EXTRACT(
        EPOCH FROM (
            b.tracking_started_at
                + make_interval(mins => c.minutes)
            - state.observed_at
        )
    ) AS state_age_seconds,
    state.payload
FROM base b
CROSS JOIN checkpoints c
JOIN LATERAL (
    SELECT
        s.observed_at,
        s.payload
    FROM mint_snapshots s
    WHERE s.mint = b.mint
      AND s.observed_at <= (
          b.tracking_started_at
              + make_interval(mins => c.minutes)
      )
    ORDER BY s.observed_at DESC
    LIMIT 1
) state ON true
WHERE b.last_polled_at IS NOT NULL
  AND b.last_polled_at >= (
      b.tracking_started_at
          + make_interval(mins => c.minutes)
  )
ORDER BY c.minutes, b.mint
"""


HISTORY_QUERY = """
WITH base AS (
    SELECT *
    FROM unnest(
        %s::text[],
        %s::timestamptz[]
    ) AS t(
        mint,
        tracking_started_at
    )
)
SELECT
    b.mint,
    s.observed_at,
    s.payload->>'mcap' AS mcap,
    s.payload->'stats5m'->>'buyVolume' AS buy_volume,
    s.payload->'stats5m'->>'sellVolume' AS sell_volume,
    s.payload->'stats5m'->>'numBuys' AS num_buys,
    s.payload->'stats5m'->>'numSells' AS num_sells,
    s.payload->'stats5m'->>'numTraders' AS num_traders
FROM base b
JOIN mint_snapshots s
  ON s.mint = b.mint
 AND s.observed_at >= b.tracking_started_at
 AND s.observed_at <= (
     b.tracking_started_at
       + make_interval(mins => %s)
 )
ORDER BY b.mint, s.observed_at
"""


# =============================================================================
# Cohorts / percentile warning matrix
# =============================================================================

def mcap_band(value: float | None) -> str:
    if value is None:
        return "mcap:null"
    if value < 10_000:
        return "mcap:<10k"
    if value < 30_000:
        return "mcap:10-30k"
    if value < 100_000:
        return "mcap:30-100k"
    if value < 300_000:
        return "mcap:100-300k"
    if value < 1_000_000:
        return "mcap:300k-1m"
    return "mcap:>=1m"


def liquidity_band(value: float | None) -> str:
    if value is None:
        return "liq:null"
    if value < 1_000:
        return "liq:<1k"
    if value < 5_000:
        return "liq:1-5k"
    if value < 20_000:
        return "liq:5-20k"
    if value < 100_000:
        return "liq:20-100k"
    return "liq:>=100k"


def market_age_band(value: float | None) -> str:
    if value is None:
        return "age:unknown"
    if value < 10:
        return "age:<10m"
    if value < 30:
        return "age:10-30m"
    if value < 60:
        return "age:30-60m"
    if value < 120:
        return "age:60-120m"
    if value < 360:
        return "age:2-6h"
    if value < 1440:
        return "age:6-24h"
    return "age:>=24h"


def cohort_feature_value(x: dict[str, Any], feature: str) -> float | None:
    if feature == "net_buyer_absence":
        share = x.get("net_buyer_share")
        if share is None:
            return None
        return 1.0 - share
    value = x.get(feature)
    try:
        if value is None:
            return None
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def empirical_percentile(sorted_values: list[float], value: float) -> float:
    if not sorted_values:
        return 0.0
    # True mid-rank for ties. If 20% of the cohort share the maximum value,
    # they receive the midpoint of that tied block instead of all becoming
    # artificial P99+ observations.
    left = bisect.bisect_left(sorted_values, value)
    right = bisect.bisect_right(sorted_values, value)
    p = (left + right) / (2.0 * len(sorted_values))
    return max(0.0, min(1.0, p))


def attach_cohort_anomalies(
    active_records: list[dict[str, Any]],
) -> None:
    """
    Warning matrix only. No detector classification is changed.

    Primary cohort:
      checkpoint + window + market-age band + MC band + liquidity band.

    Fallback hierarchy:
      checkpoint + window + market-age band
      then checkpoint + window across the active population.
    """
    groups: dict[tuple[Any, ...], dict[str, list[float]]] = defaultdict(
        lambda: defaultdict(list)
    )
    age_fallback: dict[tuple[int, str, str], dict[str, list[float]]] = defaultdict(
        lambda: defaultdict(list)
    )
    fallback: dict[tuple[int, str], dict[str, list[float]]] = defaultdict(
        lambda: defaultdict(list)
    )

    for rec in active_records:
        cp = rec["checkpoint_minutes"]
        age_band = market_age_band(
            (rec["evidence"].get("age") or {}).get("market_age_minutes")
        )
        for window, x in rec["evidence"]["windows"].items():
            key = (
                cp,
                window,
                age_band,
                mcap_band(x.get("mcap")),
                liquidity_band(x.get("liquidity")),
            )
            age_fb = (cp, window, age_band)
            fb = (cp, window)

            for feature in COHORT_FEATURES:
                value = cohort_feature_value(x, feature)
                if value is None:
                    continue
                groups[key][feature].append(value)
                age_fallback[age_fb][feature].append(value)
                fallback[fb][feature].append(value)

    for mapping in (groups, age_fallback, fallback):
        for feature_map in mapping.values():
            for values in feature_map.values():
                values.sort()

    for rec in active_records:
        cp = rec["checkpoint_minutes"]
        evidence = rec["evidence"]
        age_band = market_age_band(
            (evidence.get("age") or {}).get("market_age_minutes")
        )

        windows_out: dict[str, Any] = {}
        all_axis_max: dict[str, float] = defaultdict(float)

        for window, x in evidence["windows"].items():
            key = (
                cp,
                window,
                age_band,
                mcap_band(x.get("mcap")),
                liquidity_band(x.get("liquidity")),
            )
            age_fb = (cp, window, age_band)
            fb = (cp, window)

            percentiles: dict[str, float] = {}
            reference_sizes: dict[str, int] = {}
            reference_kind: dict[str, str] = {}
            axis_max: dict[str, float] = defaultdict(float)

            for feature, axis in COHORT_FEATURES.items():
                value = cohort_feature_value(x, feature)
                if value is None:
                    continue

                cohort_values = groups[key].get(feature, [])
                age_values = age_fallback[age_fb].get(feature, [])
                if len(cohort_values) >= COHORT_MIN_SIZE:
                    ref_values = cohort_values
                    kind = "age_mcap_liquidity_cohort"
                elif len(age_values) >= COHORT_MIN_SIZE:
                    ref_values = age_values
                    kind = "market_age_fallback"
                else:
                    ref_values = fallback[fb].get(feature, [])
                    kind = "checkpoint_window_fallback"

                if not ref_values:
                    continue

                p = empirical_percentile(ref_values, value)
                percentiles[feature] = p
                reference_sizes[feature] = len(ref_values)
                reference_kind[feature] = kind
                axis_max[axis] = max(axis_max[axis], p)
                all_axis_max[axis] = max(all_axis_max[axis], p)

            windows_out[window] = {
                "cohort": {
                    "market_age_band": key[2],
                    "mcap_band": key[3],
                    "liquidity_band": key[4],
                },
                "percentiles": percentiles,
                "reference_sizes": reference_sizes,
                "reference_kind": reference_kind,
                "axis_max_percentile": dict(axis_max),
            }

        single_extreme = any(
            p >= MATRIX_EXTREME_SINGLE
            for window in windows_out.values()
            for p in window["percentiles"].values()
        )
        strong_axes = sorted(
            axis
            for axis, p in all_axis_max.items()
            if p >= MATRIX_EXTREME_MULTI
        )
        review_trigger = single_extreme or len(strong_axes) >= 2

        evidence["cohort_anomaly"] = {
            "review_trigger": review_trigger,
            "trigger_semantics": (
                "warning_only_no_bot_or_retire_decision"
                if review_trigger else "none"
            ),
            "extreme_axes": strong_axes,
            "axis_max_percentile": dict(all_axis_max),
            "single_feature_ge_99_9pct": single_extreme,
            "windows": windows_out,
        }
        if review_trigger and evidence.get("analysis_tag") == "NORMAL_RANGE":
            evidence["analysis_tag"] = "SYSTEMATIC_WARNING"



def cohort_reference_distribution(
    active_records: list[dict[str, Any]],
) -> dict[str, Any]:
    counter: Counter[str] = Counter()
    total = 0
    for rec in active_records:
        matrix = rec["evidence"].get("cohort_anomaly") or {}
        for window in (matrix.get("windows") or {}).values():
            for kind in (window.get("reference_kind") or {}).values():
                counter[kind] += 1
                total += 1
    return {
        "total_feature_references": total,
        "counts": dict(counter),
        "shares": {
            key: value / total if total else None
            for key, value in counter.items()
        },
    }


# =============================================================================
# Calibration and earliness
# =============================================================================

def percentile_value(values: list[float], q: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    if len(values) == 1:
        return values[0]
    pos = (len(values) - 1) * q
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return values[lo]
    weight = pos - lo
    return values[lo] * (1 - weight) + values[hi] * weight


def rule_names(evidence: dict[str, Any]) -> set[str]:
    return set(evidence.get("archetype_tags") or [])


def build_rule_calibration(
    labeled: dict[str, dict[str, Any]],
    active_mints_by_rule: dict[str, set[str]],
    first_cp_by_rule_mint: dict[str, dict[str, int]],
) -> list[dict[str, Any]]:
    registry = detector_registry()
    registered_names = {d["name"] for d in registry}
    all_rules = registered_names | set(active_mints_by_rule)

    bots = [x for x in labeled.values() if x["found"] and x["bot_label"] == "BOT"]
    nonbots = [x for x in labeled.values() if x["found"] and x["bot_label"] == "NON_BOT"]
    retires = [x for x in labeled.values() if x["found"] and x["retire_label"] == "RETIRE"]
    keeps = [x for x in labeled.values() if x["found"] and x["retire_label"] == "KEEP"]

    established = {
        d["name"]
        for d in registry
        if d["status"] in {"FROZEN", "CANDIDATE"}
    }

    def first_rule_cp(item: dict[str, Any], rule: str) -> int | None:
        cps = [
            int(e["checkpoint_minutes"])
            for e in item.get("evidence", [])
            if rule in rule_names(e)
        ]
        return min(cps) if cps else None

    rows: list[dict[str, Any]] = []

    for rule in sorted(all_rules):
        contract = DETECTOR_BY_NAME.get(rule)

        bot_cps = [cp for x in bots if (cp := first_rule_cp(x, rule)) is not None]
        nonbot_cps = [cp for x in nonbots if (cp := first_rule_cp(x, rule)) is not None]
        retire_cps = [cp for x in retires if (cp := first_rule_cp(x, rule)) is not None]
        keep_cps = [cp for x in keeps if (cp := first_rule_cp(x, rule)) is not None]

        own_active = set(active_mints_by_rule.get(rule, set()))
        comparison_rules = (
            established - {rule}
            if rule in established
            else established
        )

        covered_elsewhere: set[str] = set()
        for other in comparison_rules:
            covered_elsewhere |= active_mints_by_rule.get(other, set())

        marginal = own_active - covered_elsewhere

        first_map = first_cp_by_rule_mint.get(rule, {})
        early_first_count = 0
        gains: list[float] = []

        for mint, own_cp in first_map.items():
            other_cps = [
                first_cp_by_rule_mint.get(other, {}).get(mint)
                for other in comparison_rules
            ]
            other_cps = [cp for cp in other_cps if cp is not None]
            if not other_cps:
                continue
            other_cp = min(other_cps)
            if own_cp < other_cp:
                early_first_count += 1
                gains.append(float(other_cp - own_cp))

        row = {
            "rule": rule,
            "family": contract.family if contract else "",
            "axis": contract.axis if contract else "",
            "classification": contract.classification if contract else "",
            "status": contract.status if contract else "",
            "scope": contract.scope if contract else "",
            "min_age_minutes": contract.min_age_minutes if contract else "",
            "needs_history": contract.needs_history if contract else "",

            "active_unique_mints": len(own_active),
            "marginal_unique_mints": len(marginal),
            "marginal_share_pct": (
                round(100.0 * len(marginal) / len(own_active), 4)
                if own_active else 0.0
            ),
            "early_first_mints": early_first_count,
            "median_minutes_gained": median(gains) if gains else None,
            "p90_minutes_gained": percentile_value(gains, 0.90),

            "labeled_bots_total": len(bots),
            "labeled_bots_hit": len(bot_cps),
            "labeled_nonbots_total": len(nonbots),
            "labeled_nonbots_hit": len(nonbot_cps),
            "labeled_retire_total": len(retires),
            "labeled_retire_hit": len(retire_cps),
            "labeled_keep_total": len(keeps),
            "labeled_keep_hit": len(keep_cps),
        }

        for cp in CHECKPOINTS:
            row[f"bot_hit_by_{cp}m"] = sum(x <= cp for x in bot_cps)
            row[f"retire_hit_by_{cp}m"] = sum(x <= cp for x in retire_cps)

        rows.append(row)

    rows.sort(
        key=lambda r: (
            {"FROZEN": 0, "CANDIDATE": 1, "DISCOVERY": 2}.get(r["status"], 9),
            r["labeled_nonbots_hit"],
            r["labeled_keep_hit"],
            -r["labeled_bots_hit"],
            -r["early_first_mints"],
            -r["marginal_unique_mints"],
            r["rule"],
        )
    )
    return rows


def build_family_summary(
    labeled: dict[str, dict[str, Any]],
    active_mints_by_rule: dict[str, set[str]],
) -> list[dict[str, Any]]:
    registry = detector_registry()
    rules_by_family: dict[str, list[str]] = defaultdict(list)
    for d in registry:
        rules_by_family[d["family"]].append(d["name"])

    bots = [x for x in labeled.values() if x["found"] and x["bot_label"] == "BOT"]
    nonbots = [x for x in labeled.values() if x["found"] and x["bot_label"] == "NON_BOT"]

    def item_family_hit(item: dict[str, Any], rules: set[str]) -> bool:
        return any(
            bool(rule_names(e) & rules)
            for e in item.get("evidence", [])
        )

    rows = []
    for family, rules in sorted(rules_by_family.items()):
        rule_set = set(rules)
        active: set[str] = set()
        for rule in rules:
            active |= active_mints_by_rule.get(rule, set())

        rows.append({
            "family": family,
            "rules": sorted(rules),
            "active_unique_mints": len(active),
            "labeled_bots_hit": sum(
                item_family_hit(item, rule_set) for item in bots
            ),
            "labeled_bots_total": len(bots),
            "labeled_nonbots_hit": sum(
                item_family_hit(item, rule_set) for item in nonbots
            ),
            "labeled_nonbots_total": len(nonbots),
        })

    return rows


def current_observation_structure(meta: dict[str, Any]) -> dict[str, Any]:
    """
    Verified CURRENT unchanged-age evidence.

    The repository updates last_polled_at on successful unchanged responses, so
    last_polled_at minus the latest stored changed state is meaningful now. It
    is deliberately NOT projected backwards into historical checkpoints.
    """
    last_poll = meta.get("last_polled_at")
    latest_local = meta.get("latest_state_observed_at")
    latest_source = parse_timestamp(meta.get("latest_source_updated_at"))

    local_age = None
    source_age = None
    if last_poll is not None and latest_local is not None:
        local_age = max(0.0, (last_poll - latest_local).total_seconds())
    if last_poll is not None and latest_source is not None:
        if last_poll.tzinfo is None:
            last_poll = last_poll.replace(tzinfo=timezone.utc)
        source_age = max(0.0, (last_poll - latest_source).total_seconds())

    return {
        "last_polled_at": last_poll,
        "latest_state_observed_at": latest_local,
        "latest_source_updated_at": latest_source,
        "current_local_unchanged_age_seconds": local_age,
        "current_source_unchanged_age_seconds": source_age,
        "semantics": "current_successful_poll_vs_latest_changed_state",
    }


# =============================================================================
# Candidate summaries
# =============================================================================

def best_bot_level(evidence: list[dict[str, Any]]) -> str:
    if not evidence:
        return "NONE"
    return max(
        (e["bot_level"] for e in evidence),
        key=lambda x: BOT_LEVEL_RANK[x],
    )


def best_anomaly_level(evidence: list[dict[str, Any]]) -> str:
    if not evidence:
        return "NONE"
    return max(
        (e["anomaly_level"] for e in evidence),
        key=lambda x: ANOMALY_LEVEL_RANK[x],
    )


def first_checkpoint(
    evidence: list[dict[str, Any]],
    *,
    axis: str,
    minimum: str,
) -> int | None:
    if axis == "bot":
        rank = BOT_LEVEL_RANK
        key = "bot_level"
    else:
        rank = ANOMALY_LEVEL_RANK
        key = "anomaly_level"

    threshold = rank[minimum]
    cps = [
        int(e["checkpoint_minutes"])
        for e in evidence
        if rank[e[key]] >= threshold
    ]
    return min(cps) if cps else None


def first_matrix_checkpoint(evidence: list[dict[str, Any]]) -> int | None:
    cps = [
        int(e["checkpoint_minutes"])
        for e in evidence
        if (e.get("cohort_anomaly") or {}).get("review_trigger")
    ]
    return min(cps) if cps else None


def best_evidence(evidence: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not evidence:
        return None

    return max(
        evidence,
        key=lambda e: (
            BOT_LEVEL_RANK[e["bot_level"]],
            ANOMALY_LEVEL_RANK[e["anomaly_level"]],
            int(bool((e.get("cohort_anomaly") or {}).get("review_trigger"))),
            -int(e["checkpoint_minutes"]),
        ),
    )


def summarize_candidates(
    base: dict[str, dict[str, Any]],
    labels: dict[str, dict[str, str]],
    active_evidence_by_mint: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    candidates = []

    for mint, evidence in active_evidence_by_mint.items():
        detector_flag = any(e["anomaly_level"] != "NONE" for e in evidence)
        matrix_flag = any(
            (e.get("cohort_anomaly") or {}).get("review_trigger")
            for e in evidence
        )
        if not detector_flag and not matrix_flag:
            continue

        tags = sorted({
            tag for e in evidence for tag in e.get("archetype_tags", [])
        })
        families = sorted({
            family for e in evidence for family in e.get("archetype_families", [])
        })
        axes = sorted({
            axis for e in evidence for axis in e.get("evidence_axes", [])
        })
        matrix_axes = sorted({
            axis
            for e in evidence
            for axis in (e.get("cohort_anomaly") or {}).get("extreme_axes", [])
        })

        first_seen: dict[str, int] = {}
        checkpoints_by_tag: dict[str, list[int]] = defaultdict(list)
        for e in evidence:
            cp = int(e["checkpoint_minutes"])
            for tag in e.get("archetype_tags", []):
                first_seen[tag] = min(first_seen.get(tag, cp), cp)
                checkpoints_by_tag[tag].append(cp)

        label = labels.get(mint)
        best = best_evidence(evidence)

        candidates.append({
            **base[mint],
            "current_observation_structure": current_observation_structure(base[mint]),
            "best_bot_level": best_bot_level(evidence),
            "best_anomaly_level": best_anomaly_level(evidence),
            "first_hard_bot_checkpoint": first_checkpoint(
                evidence, axis="bot", minimum="HARD_BOT"
            ),
            "first_candidate_checkpoint": first_checkpoint(
                evidence, axis="bot", minimum="CANDIDATE"
            ),
            "first_anomaly_high_checkpoint": first_checkpoint(
                evidence, axis="anomaly", minimum="HIGH"
            ),
            "first_matrix_review_checkpoint": first_matrix_checkpoint(evidence),
            "matrix_review_trigger": matrix_flag,
            "matrix_extreme_axes": matrix_axes,
            "archetype_tags": tags,
            "archetype_families": families,
            "evidence_axes": axes,
            "archetype_first_seen": dict(sorted(first_seen.items())),
            "archetype_checkpoints": {
                tag: sorted(set(cps))
                for tag, cps in sorted(checkpoints_by_tag.items())
            },
            "bot_label": label["bot_label"] if label else None,
            "retire_label": label["retire_label"] if label else None,
            "manual_notes": label["notes"] if label else None,
            "checkpoint_evidence": evidence,
            "best_evidence": best,
        })

    candidates.sort(
        key=lambda x: (
            -BOT_LEVEL_RANK[x["best_bot_level"]],
            -ANOMALY_LEVEL_RANK[x["best_anomaly_level"]],
            -int(x["matrix_review_trigger"]),
            x["first_hard_bot_checkpoint"]
            if x["first_hard_bot_checkpoint"] is not None else 10**9,
            x["first_candidate_checkpoint"]
            if x["first_candidate_checkpoint"] is not None else 10**9,
            x["mint"],
        )
    )
    return candidates


# =============================================================================
# Feature presence + semantic diagnostics
# =============================================================================

def build_presence_rows(
    active_records: list[dict[str, Any]],
    eligible_active: Counter[int],
) -> list[dict[str, Any]]:
    """
    Presence != readiness.

    Reports checkpoint presence, non-zero rate, conditional presence inside an
    available stats5m state, and how often observed checkpoint values actually
    change. These are descriptive diagnostics only.
    """
    fields: set[str] = set()
    by_field_cp: dict[str, dict[int, list[dict[str, Any]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    by_field_mint: dict[str, dict[str, list[tuple[int, dict[str, Any]]]]] = defaultdict(
        lambda: defaultdict(list)
    )

    for rec in active_records:
        cp = rec["checkpoint_minutes"]
        mint = rec["mint"]
        presence = rec["evidence"].get("feature_presence") or {}
        for field, metric in presence.items():
            fields.add(field)
            by_field_cp[field][cp].append(metric)
            by_field_mint[field][mint].append((cp, metric))

    rows: list[dict[str, Any]] = []
    for field in sorted(fields):
        row: dict[str, Any] = {"feature": field}
        first_50 = None
        first_90 = None

        for cp in CHECKPOINTS:
            eligible = eligible_active.get(cp, 0)
            metrics = by_field_cp[field].get(cp, [])
            present = sum(bool(m.get("present")) for m in metrics)
            nonzero = sum(bool(m.get("nonzero")) for m in metrics)

            presence_rate = present / eligible if eligible else None
            nonzero_rate = nonzero / present if present else None

            # For rolling stats fields, distinguish field absence from the
            # absence of the entire stats5m activity state.
            conditional_rate = None
            if field.startswith("stats5m_") and field != "stats5m_volume":
                denominator = 0
                numerator = 0
                for rec in active_records:
                    if rec["checkpoint_minutes"] != cp:
                        continue
                    p = rec["evidence"].get("feature_presence") or {}
                    base = p.get("stats5m_volume") or {}
                    if not base.get("present"):
                        continue
                    denominator += 1
                    metric = p.get(field) or {}
                    numerator += int(bool(metric.get("present")))
                conditional_rate = numerator / denominator if denominator else None

            row[f"present_{cp}m"] = present
            row[f"presence_rate_{cp}m"] = presence_rate
            row[f"nonzero_rate_given_present_{cp}m"] = nonzero_rate
            row[f"conditional_on_stats5m_presence_{cp}m"] = conditional_rate

            if presence_rate is not None and presence_rate >= 0.50 and first_50 is None:
                first_50 = cp
            if presence_rate is not None and presence_rate >= 0.90 and first_90 is None:
                first_90 = cp

        comparable_pairs = 0
        changed_pairs = 0
        first_nonzero_checkpoints: list[int] = []
        for mint, observations in by_field_mint[field].items():
            observations = sorted(observations, key=lambda x: x[0])
            first_nonzero = next(
                (cp for cp, metric in observations if metric.get("nonzero")),
                None,
            )
            if first_nonzero is not None:
                first_nonzero_checkpoints.append(first_nonzero)

            for (_, prev), (_, curr) in zip(observations, observations[1:]):
                if not prev.get("present") or not curr.get("present"):
                    continue
                comparable_pairs += 1
                if prev.get("value") != curr.get("value"):
                    changed_pairs += 1

        row["first_checkpoint_ge_50pct_presence"] = first_50
        row["first_checkpoint_ge_90pct_presence"] = first_90
        row["checkpoint_change_rate"] = (
            changed_pairs / comparable_pairs if comparable_pairs else None
        )
        row["median_first_nonzero_checkpoint"] = (
            median(first_nonzero_checkpoints)
            if first_nonzero_checkpoints else None
        )
        rows.append(row)

    return rows


# =============================================================================
# Blind control cohort
# =============================================================================

def make_blind_sample(
    active_records: list[dict[str, Any]],
    labels: dict[str, dict[str, str]],
) -> list[dict[str, Any]]:
    """
    Deterministic, unlabeled, stratified control sample.
    No detector or matrix result is written to the output.
    """
    target_cp = 30 if 30 in CHECKPOINTS else CHECKPOINTS[0]
    rows = [
        rec
        for rec in active_records
        if rec["checkpoint_minutes"] == target_cp
        and rec["mint"] not in labels
    ]

    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for rec in rows:
        windows = rec["evidence"].get("windows") or {}
        x = windows.get("stats5m") or next(iter(windows.values()), {})
        groups[
            (
                market_age_band(
                    (rec["evidence"].get("age") or {}).get("market_age_minutes")
                ),
                mcap_band(x.get("mcap")),
                liquidity_band(x.get("liquidity")),
            )
        ].append(rec)

    rng = random.Random(BLIND_SAMPLE_SEED)
    chosen: list[dict[str, Any]] = []

    # Round-robin across cohorts to avoid one giant low-MC bucket dominating.
    buckets = []
    for key, values in sorted(groups.items()):
        values = list(values)
        rng.shuffle(values)
        buckets.append((key, values))

    while len(chosen) < BLIND_SAMPLE_TARGET:
        progressed = False
        for key, values in buckets:
            if not values or len(chosen) >= BLIND_SAMPLE_TARGET:
                continue
            rec = values.pop()
            chosen.append(rec)
            progressed = True
        if not progressed:
            break

    result = []
    for i, rec in enumerate(chosen, 1):
        meta = rec["meta"]
        result.append({
            "review_id": f"B{str(i).zfill(3)}",
            "mint": rec["mint"],
            "name": meta.get("name"),
            "symbol": meta.get("symbol"),
            "checkpoint_minutes": rec["checkpoint_minutes"],
            "manual_bot_label": "",
            "manual_retire_label": "",
            "manual_notes": "",
        })

    return result


# =============================================================================
# AI bundle / feature-vector exports
# =============================================================================

COMPACT_WINDOW_KEYS = (
    "mcap", "liquidity", "holders",
    "buy_volume", "sell_volume", "total_volume",
    "num_buys", "num_sells", "total_trades",
    "num_traders", "num_net_buyers",
    "avg_buy_size", "avg_sell_size", "avg_trade_size",
    "volume_symmetry", "trade_count_symmetry", "trade_size_symmetry",
    "trades_per_trader", "trades_per_trader_per_hour",
    "trades_per_hour", "volume_per_hour",
    "turnover_liquidity", "turnover_liquidity_per_hour",
    "turnover_mcap", "turnover_mcap_per_hour",
    "price_change", "holder_change", "liquidity_change",
    "net_buyer_share", "price_impact_per_turnover",
    "churn_per_response",
)


def compact_evidence(e: dict[str, Any]) -> dict[str, Any]:
    return {
        "checkpoint_minutes": e["checkpoint_minutes"],
        "decision_at": str(e["decision_at"]),
        "age": e["age"],
        "bot_level": e["bot_level"],
        "anomaly_level": e["anomaly_level"],
        "archetype_tags": e["archetype_tags"],
        "evidence_axes": e["evidence_axes"],
        "feature_presence": e["feature_presence"],
        "windows": {
            name: {key: x.get(key) for key in COMPACT_WINDOW_KEYS}
            for name, x in e["windows"].items()
        },
        "temporal_features": e["temporal_features"],
        "cohort_anomaly": e.get("cohort_anomaly"),
    }


def ai_bundle_row(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": "anomaly-ai-analysis-bundle-v321",
        "identity": {
            "mint": candidate["mint"],
            "name": candidate.get("name"),
            "symbol": candidate.get("symbol"),
        },
        "current_observation_structure": candidate.get("current_observation_structure"),
        "human_labels": {
            "bot_label": candidate.get("bot_label"),
            "retire_label": candidate.get("retire_label"),
            "notes": candidate.get("manual_notes"),
        },
        "engine_summary": {
            "best_bot_level": candidate["best_bot_level"],
            "best_anomaly_level": candidate["best_anomaly_level"],
            "archetype_tags": candidate["archetype_tags"],
            "archetype_families": candidate["archetype_families"],
            "matrix_review_trigger": candidate["matrix_review_trigger"],
            "matrix_extreme_axes": candidate["matrix_extreme_axes"],
        },
        "instruction_hint": {
            "purpose": "research_review_only",
            "do_not_treat_as_ground_truth": True,
            "suggested_labels": [
                "NORMAL",
                "SUSPICIOUS",
                "STRONGLY_SYSTEMATIC",
                "INSUFFICIENT_DATA",
            ],
            "request": (
                "Assess whether the observed behavior appears systematic rather "
                "than naturally variable. Cite exact metrics, counter-evidence, "
                "and any possible novel archetype. Do not infer bot identity "
                "from Jupiter organic/black-box fields."
            ),
        },
        "checkpoints": [
            compact_evidence(e)
            for e in candidate["checkpoint_evidence"]
        ],
    }


# =============================================================================
# Main replay
# =============================================================================

# =============================================================================
# Outputs
# =============================================================================

def write_outputs(
    result: dict[str, Any],
    *,
    active_records: list[dict[str, Any]] | None = None,
) -> None:
    ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)

    OUT_JSON.write_text(
        json.dumps(result, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )

    candidates = result["candidates"]

    with OUT_REVIEW_CSV.open("w", newline="", encoding="utf-8-sig") as fh:
        fields = [
            "mint", "name", "symbol",
            "best_bot_level", "best_anomaly_level", "best_analysis_tag",
            "best_observation_quality",
            "first_hard_bot_checkpoint", "first_candidate_checkpoint",
            "first_anomaly_high_checkpoint", "first_matrix_review_checkpoint",
            "matrix_review_trigger", "matrix_extreme_axes",
            "archetype_tags", "archetype_families", "evidence_axes",
            "bot_label", "retire_label", "manual_notes",
            "best_monitoring_age", "best_market_age", "best_age_basis",
            "best_checkpoint",
            "current_local_unchanged_age_seconds",
            "current_source_unchanged_age_seconds",
        ]
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for c in candidates:
            best = c.get("best_evidence") or {}
            age = best.get("age") or {}
            writer.writerow({
                "mint": c["mint"],
                "name": c.get("name"),
                "symbol": c.get("symbol"),
                "best_bot_level": c["best_bot_level"],
                "best_anomaly_level": c["best_anomaly_level"],
                "best_analysis_tag": best.get("analysis_tag"),
                "best_observation_quality": best.get("observation_quality"),
                "first_hard_bot_checkpoint": c["first_hard_bot_checkpoint"],
                "first_candidate_checkpoint": c["first_candidate_checkpoint"],
                "first_anomaly_high_checkpoint": c["first_anomaly_high_checkpoint"],
                "first_matrix_review_checkpoint": c["first_matrix_review_checkpoint"],
                "matrix_review_trigger": c["matrix_review_trigger"],
                "matrix_extreme_axes": "|".join(c["matrix_extreme_axes"]),
                "archetype_tags": "|".join(c["archetype_tags"]),
                "archetype_families": "|".join(c["archetype_families"]),
                "evidence_axes": "|".join(c["evidence_axes"]),
                "bot_label": c["bot_label"],
                "retire_label": c["retire_label"],
                "manual_notes": c["manual_notes"],
                "best_monitoring_age": age.get("monitoring_age_minutes"),
                "best_market_age": age.get("market_age_minutes"),
                "best_age_basis": age.get("age_basis"),
                "best_checkpoint": best.get("checkpoint_minutes"),
                "current_local_unchanged_age_seconds": (
                    (c.get("current_observation_structure") or {}).get(
                        "current_local_unchanged_age_seconds"
                    )
                ),
                "current_source_unchanged_age_seconds": (
                    (c.get("current_observation_structure") or {}).get(
                        "current_source_unchanged_age_seconds"
                    )
                ),
            })

    calibration = result["rule_calibration"]
    with OUT_CALIBRATION_CSV.open("w", newline="", encoding="utf-8-sig") as fh:
        if calibration:
            writer = csv.DictWriter(fh, fieldnames=list(calibration[0]))
            writer.writeheader()
            writer.writerows(calibration)

    with OUT_MEMBERSHIP_CSV.open("w", newline="", encoding="utf-8-sig") as fh:
        fields = [
            "mint", "name", "symbol", "archetype", "family", "axis",
            "classification", "status", "scope",
            "first_seen_checkpoint", "checkpoints",
            "best_bot_level", "best_anomaly_level",
            "bot_label", "retire_label", "manual_notes",
        ]
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()

        for c in candidates:
            for tag in c["archetype_tags"]:
                d = DETECTOR_BY_NAME[tag]
                writer.writerow({
                    "mint": c["mint"],
                    "name": c.get("name"),
                    "symbol": c.get("symbol"),
                    "archetype": tag,
                    "family": d.family,
                    "axis": d.axis,
                    "classification": d.classification,
                    "status": d.status,
                    "scope": d.scope,
                    "first_seen_checkpoint": c["archetype_first_seen"].get(tag),
                    "checkpoints": "|".join(
                        str(x)
                        for x in c["archetype_checkpoints"].get(tag, [])
                    ),
                    "best_bot_level": c["best_bot_level"],
                    "best_anomaly_level": c["best_anomaly_level"],
                    "bot_label": c["bot_label"],
                    "retire_label": c["retire_label"],
                    "manual_notes": c["manual_notes"],
                })

    presence = result["feature_presence"]
    with OUT_PRESENCE_CSV.open("w", newline="", encoding="utf-8-sig") as fh:
        if presence:
            writer = csv.DictWriter(fh, fieldnames=list(presence[0]))
            writer.writeheader()
            writer.writerows(presence)

    with OUT_AI_JSONL.open("w", encoding="utf-8") as fh:
        for candidate in candidates:
            # Matrix warning, detector signal, or human label -> useful bundle.
            fh.write(
                json.dumps(
                    ai_bundle_row(candidate),
                    ensure_ascii=False,
                    default=str,
                )
                + "\n"
            )


def write_feature_vectors(
    active_records: list[dict[str, Any]],
    labels: dict[str, dict[str, str]],
) -> None:
    fields = [
        "mint", "name", "symbol", "checkpoint_minutes",
        "monitoring_age_minutes", "market_age_minutes", "age_basis",
        "window", "window_minutes", "mcap", "liquidity", "holders",
        "total_trades", "trades_per_hour", "num_traders",
        "trades_per_trader", "trades_per_trader_per_hour",
        "total_volume", "volume_per_hour", "avg_trade_size",
        "volume_symmetry", "trade_count_symmetry", "trade_size_symmetry",
        "turnover_liquidity", "turnover_liquidity_per_hour",
        "turnover_mcap", "turnover_mcap_per_hour",
        "price_change", "holder_change", "liquidity_change",
        "num_net_buyers", "net_buyer_share",
        "price_impact_per_turnover", "churn_per_response",
        "cohort_market_age_band", "cohort_mcap_band", "cohort_liquidity_band",
        "p_trades_per_hour", "p_turnover_liquidity_per_hour",
        "p_trades_per_trader_per_hour", "p_volume_symmetry",
        "p_trade_count_symmetry", "p_trade_size_symmetry",
        "p_price_impact_per_turnover", "p_churn_per_response",
        "matrix_review_trigger", "matrix_extreme_axes",
        "archetype_tags", "bot_label", "retire_label",
    ]

    with OUT_FEATURE_VECTORS_CSV.open(
        "w", newline="", encoding="utf-8-sig"
    ) as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()

        for rec in active_records:
            e = rec["evidence"]
            age = e["age"]
            label = labels.get(rec["mint"])
            matrix = e.get("cohort_anomaly") or {}

            for window, x in e["windows"].items():
                cw = (matrix.get("windows") or {}).get(window, {})
                cohort = cw.get("cohort") or {}
                p = cw.get("percentiles") or {}

                writer.writerow({
                    "mint": rec["mint"],
                    "name": rec["meta"].get("name"),
                    "symbol": rec["meta"].get("symbol"),
                    "checkpoint_minutes": rec["checkpoint_minutes"],
                    "monitoring_age_minutes": age.get("monitoring_age_minutes"),
                    "market_age_minutes": age.get("market_age_minutes"),
                    "age_basis": age.get("age_basis"),
                    "window": window,
                    "window_minutes": x.get("window_minutes"),
                    "mcap": x.get("mcap"),
                    "liquidity": x.get("liquidity"),
                    "holders": x.get("holders"),
                    "total_trades": x.get("total_trades"),
                    "trades_per_hour": x.get("trades_per_hour"),
                    "num_traders": x.get("num_traders"),
                    "trades_per_trader": x.get("trades_per_trader"),
                    "trades_per_trader_per_hour": x.get("trades_per_trader_per_hour"),
                    "total_volume": x.get("total_volume"),
                    "volume_per_hour": x.get("volume_per_hour"),
                    "avg_trade_size": x.get("avg_trade_size"),
                    "volume_symmetry": x.get("volume_symmetry"),
                    "trade_count_symmetry": x.get("trade_count_symmetry"),
                    "trade_size_symmetry": x.get("trade_size_symmetry"),
                    "turnover_liquidity": x.get("turnover_liquidity"),
                    "turnover_liquidity_per_hour": x.get("turnover_liquidity_per_hour"),
                    "turnover_mcap": x.get("turnover_mcap"),
                    "turnover_mcap_per_hour": x.get("turnover_mcap_per_hour"),
                    "price_change": x.get("price_change"),
                    "holder_change": x.get("holder_change"),
                    "liquidity_change": x.get("liquidity_change"),
                    "num_net_buyers": x.get("num_net_buyers"),
                    "net_buyer_share": x.get("net_buyer_share"),
                    "price_impact_per_turnover": x.get("price_impact_per_turnover"),
                    "churn_per_response": x.get("churn_per_response"),
                    "cohort_market_age_band": cohort.get("market_age_band"),
                    "cohort_mcap_band": cohort.get("mcap_band"),
                    "cohort_liquidity_band": cohort.get("liquidity_band"),
                    "p_trades_per_hour": p.get("trades_per_hour"),
                    "p_turnover_liquidity_per_hour": p.get("turnover_liquidity_per_hour"),
                    "p_trades_per_trader_per_hour": p.get("trades_per_trader_per_hour"),
                    "p_volume_symmetry": p.get("volume_symmetry"),
                    "p_trade_count_symmetry": p.get("trade_count_symmetry"),
                    "p_trade_size_symmetry": p.get("trade_size_symmetry"),
                    "p_price_impact_per_turnover": p.get("price_impact_per_turnover"),
                    "p_churn_per_response": p.get("churn_per_response"),
                    "matrix_review_trigger": matrix.get("review_trigger"),
                    "matrix_extreme_axes": "|".join(matrix.get("extreme_axes") or []),
                    "archetype_tags": "|".join(e.get("archetype_tags") or []),
                    "bot_label": label["bot_label"] if label else None,
                    "retire_label": label["retire_label"] if label else None,
                })


def write_blind_sample(sample: list[dict[str, Any]]) -> None:
    with OUT_BLIND_CSV.open("w", newline="", encoding="utf-8-sig") as fh:
        fields = [
            "review_id", "mint", "name", "symbol", "checkpoint_minutes",
            "manual_bot_label", "manual_retire_label", "manual_notes",
        ]
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(sample)


def print_summary(result: dict[str, Any]) -> None:
    pop = result["active_population"]
    bench = result["manual_benchmark_summary"]

    print("")
    print("SUMMARY")
    print("=" * 104)
    for cp in CHECKPOINTS:
        print(
            f"T+{cp:<3} eligible={pop['eligible_by_checkpoint'].get(cp, 0):>6,}"
        )

    print(
        f"Unique review population={pop['unique_candidates_or_matrix_review']:,} | "
        f"HARD_BOT={pop['unique_hard_bots']:,} | "
        f"CANDIDATE={pop['unique_bot_candidates']:,} | "
        f"MATRIX_REVIEW={pop['unique_matrix_review']:,}"
    )

    print("")
    print("MANUAL BENCHMARK")
    print("=" * 104)
    print(
        f"BOT={bench['bot_labels_found']} | "
        f"HARD_BOT={bench['bots_hard_detected']} | "
        f"CANDIDATE+={bench['bots_candidate_or_higher']}"
    )
    print(
        f"NON_BOT={bench['non_bot_labels_found']} | "
        f"HARD FP={bench['nonbots_hard_false_positive']} | "
        f"CANDIDATE+ FP={bench['nonbots_candidate_or_higher']}"
    )

    print("")
    print("ARCHETYPE CALIBRATION / EARLINESS / MARGINAL VALUE")
    print("=" * 104)
    for row in result["rule_calibration"]:
        print(
            f"{row['rule']:<35} "
            f"{row['status']:<9} {row['classification']:<14} | "
            f"pop={row['active_unique_mints']:>4} "
            f"marg={row['marginal_unique_mints']:>4} "
            f"early={row['early_first_mints']:>4} "
            f"gain50={str(row['median_minutes_gained']):>5} | "
            f"BOT={row['labeled_bots_hit']:>2}/{row['labeled_bots_total']:<2} "
            f"NONBOT={row['labeled_nonbots_hit']:>2}/{row['labeled_nonbots_total']:<2}"
        )

    print("")
    print("FEATURE PRESENCE / SEMANTIC DIAGNOSTICS")
    print("=" * 104)
    for row in result["feature_presence"]:
        print(
            f"{row['feature']:<42} "
            + " ".join(
                f"T+{cp}={row.get(f'presence_rate_{cp}m'):.1%}"
                if row.get(f"presence_rate_{cp}m") is not None
                else f"T+{cp}=n/a"
                for cp in CHECKPOINTS
            )
        )

    print("")
    print("TOP UNLABELED REVIEW CASES")
    print("=" * 104)
    printed = 0
    for c in result["candidates"]:
        if c["bot_label"] is not None:
            continue
        print(
            f"{c['best_bot_level']:<9} | {c['mint']} | {c.get('name') or ''} | "
            f"tags={','.join(c['archetype_tags']) or '-'} | "
            f"matrix={','.join(c['matrix_extreme_axes']) or '-'}"
        )
        printed += 1
        if printed >= TOP_PRINT:
            break

    print("")
    print("FILES")
    print("=" * 104)
    for path in (
        OUT_JSON, OUT_REVIEW_CSV, OUT_CALIBRATION_CSV,
        OUT_MEMBERSHIP_CSV, OUT_FEATURE_VECTORS_CSV,
        OUT_PRESENCE_CSV, OUT_AI_JSONL, OUT_BLIND_CSV,
        LABELS_CANONICAL_CSV,
    ):
        print(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        choices=["replay"],
        default="replay",
        help="Historical read-only calibration replay.",
    )
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        raise SystemExit("DATABASE_URL fehlt in .env")

    labels = load_labels()

    # Run once and retain active-record exports by reconstructing them through
    # a lightweight internal wrapper. We keep run_replay as the single public
    # research entrypoint; output generation below reuses the returned data.
    #
    # To avoid a second DB replay, run_replay stores only summarized JSON.
    # Feature-vector / blind exports are generated inside _run_and_export.
    result, active_records, blind_sample = _run_and_export(database_url, labels)

    write_outputs(result)
    write_feature_vectors(active_records, labels)
    write_blind_sample(blind_sample)
    print_summary(result)


def _run_and_export(
    database_url: str,
    labels: dict[str, dict[str, str]],
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    import psycopg
    from psycopg.rows import dict_row

    """
    Single DB pass variant of run_replay. Kept separate only so feature-vector
    and blind-sample exports can reuse active records without serializing the
    entire active population into the main JSON.
    """
    label_mints = sorted(labels)

    print("ANOMALY ENGINE V3.2.1 - CURRENT SURVIVOR RESEARCH")
    print("=" * 104)
    print("Raw metrics + transparent ratios. No Organic fields in decisions.")
    print(f"Monitoring checkpoints: {' / '.join(str(x) for x in CHECKPOINTS)} minutes")
    print("Loading active population + labeled references...")

    with psycopg.connect(
        database_url,
        row_factory=dict_row,
        options=(
            "-c default_transaction_read_only=on "
            f"-c statement_timeout={STATEMENT_TIMEOUT_MS}"
        ),
    ) as con:
        base_rows = con.execute(BASE_QUERY, (label_mints,)).fetchall()
        base = {
            row["mint"]: {
                "mint": row["mint"],
                "name": row["name"],
                "symbol": row["symbol"],
                "active": bool(row["tracking_enabled"]),
                "tracking_started_at": row["tracking_started_at"],
                "last_polled_at": row["last_polled_at"],
                "latest_state_observed_at": row["latest_state_observed_at"],
                "latest_source_updated_at": row["latest_source_updated_at"],
            }
            for row in base_rows
        }

        mints = list(base)
        starts = [base[m]["tracking_started_at"] for m in mints]
        last_polls = [base[m]["last_polled_at"] for m in mints]

        replay_rows = con.execute(
            REPLAY_QUERY,
            (mints, starts, last_polls),
        ).fetchall()

        print("Loading distinct history once in one batched query...")
        history_rows = con.execute(
            HISTORY_QUERY,
            (mints, starts, MAX_HISTORY_MINUTES),
        ).fetchall()

    history_by_mint: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in history_rows:
        history_by_mint[row["mint"]].append(
            make_temporal_point(
                observed_at=row["observed_at"],
                mcap=row["mcap"],
                buy_volume=row["buy_volume"],
                sell_volume=row["sell_volume"],
                num_buys=row["num_buys"],
                num_sells=row["num_sells"],
                num_traders=row["num_traders"],
            )
        )

    eligible_active: Counter[int] = Counter()
    active_mints_by_rule: dict[str, set[str]] = defaultdict(set)
    first_cp_by_rule_mint: dict[str, dict[str, int]] = defaultdict(dict)
    active_records: list[dict[str, Any]] = []
    active_evidence_by_mint: dict[str, list[dict[str, Any]]] = defaultdict(list)

    labeled_results: dict[str, dict[str, Any]] = {
        mint: {
            "mint": mint,
            **meta,
            **labels[mint],
            "found": True,
            "evidence": [],
        }
        for mint, meta in base.items()
        if mint in labels
    }
    for mint in labels:
        if mint not in labeled_results:
            labeled_results[mint] = {
                "mint": mint,
                "name": None,
                "symbol": None,
                "active": False,
                "tracking_started_at": None,
                "last_polled_at": None,
                **labels[mint],
                "found": False,
                "evidence": [],
            }

    for row in replay_rows:
        mint = row["mint"]
        meta = base[mint]
        cp = int(row["checkpoint_minutes"])

        evaluation = evaluate_token(
            row["payload"],
            monitoring_age_minutes=cp,
            history_points=history_by_mint.get(mint, []),
            tracking_started_at=meta["tracking_started_at"],
            decision_at=row["decision_at"],
        )
        evidence = {
            "checkpoint_minutes": cp,
            "decision_at": row["decision_at"],
            "state_observed_at": row["state_observed_at"],
            "state_age_seconds": float(row["state_age_seconds"]),
            "historical_state_age_is_not_poll_freshness": True,
            **evaluation,
        }

        if mint in labeled_results:
            labeled_results[mint]["evidence"].append(evidence)

        if not meta["active"]:
            continue

        eligible_active[cp] += 1
        for rule in evaluation["archetype_tags"]:
            active_mints_by_rule[rule].add(mint)
            old = first_cp_by_rule_mint[rule].get(mint)
            if old is None or cp < old:
                first_cp_by_rule_mint[rule][mint] = cp

        active_evidence_by_mint[mint].append(evidence)
        active_records.append({
            "mint": mint,
            "checkpoint_minutes": cp,
            "meta": meta,
            "evidence": evidence,
        })

    print("Building cohort percentile warning matrix...")
    attach_cohort_anomalies(active_records)

    candidates = summarize_candidates(
        base, labels, active_evidence_by_mint
    )

    # Active label evidence shares the same evidence dicts only for active
    # mints added above; refresh benchmark levels after matrix attachment.
    for item in labeled_results.values():
        ev = item["evidence"]
        item["best_bot_level"] = best_bot_level(ev)
        item["best_anomaly_level"] = best_anomaly_level(ev)
        item["first_candidate_checkpoint"] = first_checkpoint(
            ev, axis="bot", minimum="CANDIDATE"
        )
        item["first_hard_bot_checkpoint"] = first_checkpoint(
            ev, axis="bot", minimum="HARD_BOT"
        )
        item["first_anomaly_high_checkpoint"] = first_checkpoint(
            ev, axis="anomaly", minimum="HIGH"
        )

    calibration = build_rule_calibration(
        labeled_results,
        active_mints_by_rule,
        first_cp_by_rule_mint,
    )
    family_summary = build_family_summary(
        labeled_results,
        active_mints_by_rule,
    )
    presence_rows = build_presence_rows(
        active_records, eligible_active
    )

    bots = [x for x in labeled_results.values() if x["found"] and x["bot_label"] == "BOT"]
    nonbots = [x for x in labeled_results.values() if x["found"] and x["bot_label"] == "NON_BOT"]
    retires = [x for x in labeled_results.values() if x["found"] and x["retire_label"] == "RETIRE"]
    keeps = [x for x in labeled_results.values() if x["found"] and x["retire_label"] == "KEEP"]

    benchmark_summary = {
        "bot_labels_found": len(bots),
        "non_bot_labels_found": len(nonbots),
        "retire_labels_found": len(retires),
        "keep_labels_found": len(keeps),
        "bots_hard_detected": sum(x["best_bot_level"] == "HARD_BOT" for x in bots),
        "bots_candidate_or_higher": sum(
            BOT_LEVEL_RANK[x["best_bot_level"]] >= BOT_LEVEL_RANK["CANDIDATE"]
            for x in bots
        ),
        "nonbots_hard_false_positive": sum(
            x["best_bot_level"] == "HARD_BOT" for x in nonbots
        ),
        "nonbots_candidate_or_higher": sum(
            BOT_LEVEL_RANK[x["best_bot_level"]] >= BOT_LEVEL_RANK["CANDIDATE"]
            for x in nonbots
        ),
        "retire_refs_anomaly_high": sum(
            x["best_anomaly_level"] == "HIGH" for x in retires
        ),
        "keep_refs_anomaly_high_false_positive": sum(
            x["best_anomaly_level"] == "HIGH" for x in keeps
        ),
        "uncovered_bot_mints": [
            x["mint"] for x in bots if x["best_bot_level"] == "NONE"
        ],
    }

    blind_sample = make_blind_sample(active_records, labels)

    result = {
        "probe_version": "bot-detection-v3.2.1-methodology",
        "generated_at": datetime.now(timezone.utc),
        "read_only": True,
        "important": {
            "automatic_retire_enabled": False,
            "organic_metrics_used_in_decision": False,
            "organic_presence_measured_diagnostic_only": True,
            "jupiter_blackbox_classification_used_in_decision": False,
            "future_market_outcome_used": False,
            "fill_forward_temporal_features_used": False,
            "fixed_grid_temporal_sampling_used": True,
            "bot_identity_separate_from_retire_value": True,
            "no_universal_bot_score": True,
            "cohort_percentiles_are_warning_only": True,
            "ai_bundle_is_research_only": True,
        },
        "replay_mode": REPLAY_MODE,
        "replay_mode_semantics": (
            "historical checkpoints evaluated only for tokens that are current lifecycle survivors"
        ),
        "production_shape": {
            "stage_1": "cheap economic lifecycle rules first",
            "stage_2": "snapshot archetypes + feature matrix on active survivors",
            "stage_3": "history only for detectors whose contract needs_history=true",
            "stage_4": "optional cohort/AI research analysis outside hard decisions",
            "production_history_should_be_batched_and_gated": True,
            "no_per_mint_n_plus_one_history_queries": True,
            "monitoring_checkpoints_minutes": list(CHECKPOINTS),
            "window_maturity_prefers_market_age": True,
            "market_age_source": "firstPool.createdAt when available",
            "monitoring_age_kept_separately": True,
        },
        "detector_contract": {
            "registry": detector_registry(),
        },
        "feature_matrix": {
            "cohort_min_size": COHORT_MIN_SIZE,
            "single_feature_warning_percentile": MATRIX_EXTREME_SINGLE,
            "multi_axis_warning_percentile": MATRIX_EXTREME_MULTI,
            "features": COHORT_FEATURES,
            "semantics": "warning_only_no_bot_probability",
            "reference_distribution": cohort_reference_distribution(active_records),
            "midrank_ties": True,
        },
        "active_population": {
            "eligible_by_checkpoint": dict(eligible_active),
            "active_records": len(active_records),
            "unique_candidates_or_matrix_review": len(candidates),
            "unique_hard_bots": sum(
                c["best_bot_level"] == "HARD_BOT" for c in candidates
            ),
            "unique_bot_candidates": sum(
                c["best_bot_level"] == "CANDIDATE" for c in candidates
            ),
            "unique_discovery": sum(
                c["best_bot_level"] == "DISCOVERY" for c in candidates
            ),
            "unique_matrix_review": sum(
                c["matrix_review_trigger"] for c in candidates
            ),
        },
        "manual_benchmark_summary": benchmark_summary,
        "feature_presence": presence_rows,
        "rule_calibration": calibration,
        "family_summary": family_summary,
        "manual_benchmark": labeled_results,
        "candidates": candidates,
        "blind_stratified_control_sample_size": len(blind_sample),
    }

    return result, active_records, blind_sample


if __name__ == "__main__":
    main()