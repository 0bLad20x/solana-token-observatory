from __future__ import annotations

from collections import Counter
import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Iterator

from .constants import REGION_DEGRADED_SNAPSHOT_PATH, REGION_SNAPSHOT_PATH
from .storage import atomic_write_json

# Phase 1 uses explicit semantic regions rather than statistical clustering.
# Boundaries are deliberately readable and can later be validated empirically.
MCAP_BUCKETS = [
    ("under_200", "< $200", 0.0, 200.0),
    ("200_2k", "$200–2k", 200.0, 2_000.0),
    ("2k_5k", "$2k–5k", 2_000.0, 5_000.0),
    ("5k_10k", "$5k–10k", 5_000.0, 10_000.0),
    ("10k_50k", "$10k–50k", 10_000.0, 50_000.0),
    ("50k_250k", "$50k–250k", 50_000.0, 250_000.0),
    ("250k_plus", ">= $250k", 250_000.0, None),
]

LIQUIDITY_BUCKETS = [
    ("under_1", "< $1", 0.0, 1.0),
    ("1_100", "$1–100", 1.0, 100.0),
    ("100_2k", "$100–2k", 100.0, 2_000.0),
    ("2k_10k", "$2k–10k", 2_000.0, 10_000.0),
    ("10k_50k", "$10k–50k", 10_000.0, 50_000.0),
    ("50k_plus", ">= $50k", 50_000.0, None),
]

HOLDER_BUCKETS = [
    ("0_2", "0–2", 0, 3),
    ("3_10", "3–10", 3, 11),
    ("11_30", "11–30", 11, 31),
    ("31_100", "31–100", 31, 101),
    ("101_500", "101–500", 101, 501),
    ("500_plus", ">500", 501, None),
]

AGE_BUCKETS = [
    ("under_30m", "<30m", 0.0, 30.0),
    ("30_60m", "30–60m", 30.0, 60.0),
    ("1_3h", "1–3h", 60.0, 180.0),
    ("3_8h", "3–8h", 180.0, 480.0),
    ("8_24h", "8–24h", 480.0, 1_440.0),
    ("24h_plus", ">=24h", 1_440.0, None),
]

# Phase 4 (activity) already works on data the collector delivers today:
# stats1h buys/sells plus the unchanged interval. This is a descriptive label,
# never a retirement decision.
ACTIVITY_BUCKETS = [
    ("dormant", "Dormant (0 trades, stale)"),
    ("idle", "Idle (0 trades/1h)"),
    ("low", "Low (1–9/1h)"),
    ("active", "Active (10–99/1h)"),
    ("hot", "Hot (>=100/1h)"),
    ("unknown", "Unknown"),
]

POLICY_STATUSES = [
    ("none", "No policy state"),
    ("probation", "Probation"),
    ("would_demote", "Would demote"),
    ("would_retire", "Would retire"),
]

DORMANT_UNCHANGED_MINUTES = 30

SEMANTIC_SCHEMA_VERSION = 1


def semantic_schema_payload() -> dict[str, Any]:
    """Stable, serialisable definition of what every semantic bucket means."""
    return {
        "version": SEMANTIC_SCHEMA_VERSION,
        "mcap_buckets": MCAP_BUCKETS,
        "liquidity_buckets": LIQUIDITY_BUCKETS,
        "holder_buckets": HOLDER_BUCKETS,
        "age_buckets": AGE_BUCKETS,
        "activity_buckets": ACTIVITY_BUCKETS,
        "dormant_unchanged_minutes": DORMANT_UNCHANGED_MINUTES,
    }


def semantic_schema_hash() -> str:
    raw = json.dumps(semantic_schema_payload(), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


SEMANTIC_SCHEMA_HASH = semantic_schema_hash()

# Cell rows are stored positionally: the snapshot carries one row per distinct
# combination, and consumers read it back through CELL_SCHEMA.
CELL_SCHEMA = [
    "mcap_bucket",
    "liquidity_bucket",
    "holder_bucket",
    "age_bucket",
    "activity_bucket",
    "launchpad",
    "graduation",
    "policy_status",
    "count",
]

MCAP_INDEX = {key: i for i, (key, *_rest) in enumerate(MCAP_BUCKETS)}
LIQUIDITY_INDEX = {key: i for i, (key, *_rest) in enumerate(LIQUIDITY_BUCKETS)}


def region_id(mcap_bucket: str, liquidity_bucket: str) -> str:
    """Core semantic region used for transitions (Phase 2) and cohorts (Phase 3).

    Age is deliberately not part of the identity: it only ever increases and
    would produce transitions that carry no economic meaning.
    """
    return f"{mcap_bucket}~{liquidity_bucket}"


def split_region_id(value: str) -> tuple[str, str]:
    mcap, _, liquidity = value.partition("~")
    return mcap, liquidity


def region_coords(value: str | None) -> tuple[int, int] | None:
    """(mcap index, liquidity index) or None when a coordinate is unknown."""
    if not value:
        return None
    mcap, liquidity = split_region_id(value)
    if mcap not in MCAP_INDEX or liquidity not in LIQUIDITY_INDEX:
        return None
    return MCAP_INDEX[mcap], LIQUIDITY_INDEX[liquidity]


def region_rank(value: str) -> int | None:
    """Display ordering only — NOT a health score.

    Market cap and liquidity are not interchangeable, so their sum says nothing
    about whether a token got better or worse. Use `compare_regions` for that.
    This function exists purely to put axes and lists in a stable, readable
    order; it is deliberately never used to classify an outcome.
    """
    coords = region_coords(value)
    return None if coords is None else coords[0] * 100 + coords[1]


def compare_regions(before: str | None, after: str | None) -> str:
    """Partial order over regions: no scalar, no invented weighting.

    improved      — neither dimension worse, at least one better
    deteriorated  — neither dimension better, at least one worse
    mixed         — one better, one worse (market cap up, liquidity down, ...)
    same          — identical region
    unknown       — at least one coordinate missing, so not comparable
    """
    start, end = region_coords(before), region_coords(after)
    if start is None or end is None:
        return "unknown"
    mcap_delta = end[0] - start[0]
    liquidity_delta = end[1] - start[1]
    if mcap_delta == 0 and liquidity_delta == 0:
        return "same"
    if mcap_delta >= 0 and liquidity_delta >= 0:
        return "improved"
    if mcap_delta <= 0 and liquidity_delta <= 0:
        return "deteriorated"
    return "mixed"


TRANSITION_CLASSES = ["improved", "mixed", "same", "deteriorated", "unknown"]


def region_directions(before: str | None, after: str | None) -> dict[str, str]:
    """Per-dimension direction, so that `mixed` stays inspectable."""
    start, end = region_coords(before), region_coords(after)
    if start is None or end is None:
        return {"mcap": "unknown", "liquidity": "unknown"}

    def direction(delta: int) -> str:
        return "up" if delta > 0 else ("down" if delta < 0 else "same")

    return {
        "mcap": direction(end[0] - start[0]),
        "liquidity": direction(end[1] - start[1]),
    }


MCAP_LABELS = {key: label for key, label, *_ in MCAP_BUCKETS}
LIQUIDITY_LABELS = {key: label for key, label, *_ in LIQUIDITY_BUCKETS}
ACTIVITY_LABELS = dict(ACTIVITY_BUCKETS)


def region_label(value: str) -> str:
    mcap_key, liq_key = split_region_id(value)
    return (
        f"{MCAP_LABELS.get(mcap_key, 'Unknown')} × "
        f"{LIQUIDITY_LABELS.get(liq_key, 'Unknown')}"
    )


def _bucket(value: float | int | None, buckets, missing_key: str = "missing") -> tuple[str, str]:
    if value is None:
        return missing_key, "Unknown"
    for key, label, low, high in buckets:
        if value >= low and (high is None or value < high):
            return key, label
    return missing_key, "Unknown"


def classify_activity(feature: dict[str, Any]) -> tuple[str, str]:
    if not feature.get("has_stats1h"):
        return "unknown", ACTIVITY_LABELS["unknown"]
    activity = feature.get("stats1h_activity")
    if activity is None:
        return "unknown", ACTIVITY_LABELS["unknown"]
    unchanged = feature.get("unchanged_minutes")
    if activity == 0:
        if unchanged is not None and unchanged >= DORMANT_UNCHANGED_MINUTES:
            return "dormant", ACTIVITY_LABELS["dormant"]
        return "idle", ACTIVITY_LABELS["idle"]
    if activity < 10:
        return "low", ACTIVITY_LABELS["low"]
    if activity < 100:
        return "active", ACTIVITY_LABELS["active"]
    return "hot", ACTIVITY_LABELS["hot"]


def classify_feature(feature: dict[str, Any]) -> dict[str, str]:
    mcap_key, mcap_label = _bucket(feature.get("mcap"), MCAP_BUCKETS)
    liq_key, liq_label = _bucket(feature.get("liquidity"), LIQUIDITY_BUCKETS)
    holder_key, holder_label = _bucket(feature.get("holders"), HOLDER_BUCKETS)
    age_key, age_label = _bucket(feature.get("age_minutes"), AGE_BUCKETS)
    activity_key, activity_label = classify_activity(feature)
    launchpad = feature.get("launchpad") or "unknown"
    graduation = "graduated" if feature.get("is_graduated") else "not_graduated"
    status = (feature.get("policy_status") or "none").lower()
    if status not in {key for key, _label in POLICY_STATUSES}:
        status = "none"
    return {
        "region": region_id(mcap_key, liq_key),
        "mcap_bucket": mcap_key,
        "mcap_label": mcap_label,
        "liquidity_bucket": liq_key,
        "liquidity_label": liq_label,
        "holder_bucket": holder_key,
        "holder_label": holder_label,
        "age_bucket": age_key,
        "age_label": age_label,
        "activity_bucket": activity_key,
        "activity_label": activity_label,
        "launchpad": launchpad,
        "graduation": graduation,
        "policy_status": status,
    }


def _ordered_meta(buckets: list[tuple]) -> list[dict[str, str]]:
    return [{"key": row[0], "label": row[1]} for row in buckets]


def iter_cells(snapshot: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Yield snapshot cells as dicts for schema v1 and v2 alike."""
    schema = snapshot.get("cells_schema")
    for row in snapshot.get("cells", []):
        yield row if schema is None else dict(zip(schema, row))


def build_region_snapshot(
    features: list[dict[str, Any]],
    generated_at: str | None = None,
    *,
    collector_health: dict[str, Any] | None = None,
    technical_validation: str | None = None,
    expected_interval_seconds: int | None = None,
) -> dict[str, Any]:
    generated_at = generated_at or datetime.now(timezone.utc).isoformat()
    cell_counts: Counter[tuple[str, ...]] = Counter()
    launchpad_counts: Counter[str] = Counter()
    graduation_counts: Counter[str] = Counter()
    age_counts: Counter[str] = Counter()
    holder_counts: Counter[str] = Counter()
    activity_counts: Counter[str] = Counter()
    policy_counts: Counter[str] = Counter()
    known_pair_count = 0

    for feature in features:
        region = classify_feature(feature)
        launchpad_counts[region["launchpad"]] += 1
        graduation_counts[region["graduation"]] += 1
        age_counts[region["age_bucket"]] += 1
        holder_counts[region["holder_bucket"]] += 1
        activity_counts[region["activity_bucket"]] += 1
        policy_counts[region["policy_status"]] += 1
        if region["mcap_bucket"] != "missing" and region["liquidity_bucket"] != "missing":
            known_pair_count += 1

        cell_counts[tuple(region[column] for column in CELL_SCHEMA[:-1])] += 1

    cells = [list(key) + [count] for key, count in sorted(cell_counts.items())]

    return {
        "schema_version": 2,
        "generated_at": generated_at,
        "phase": "semantic_regions_v2",
        "semantic_schema_version": SEMANTIC_SCHEMA_VERSION,
        "semantic_schema_hash": SEMANTIC_SCHEMA_HASH,
        "collector_health": collector_health,
        "technical_validation": technical_validation,
        "expected_interval_seconds": expected_interval_seconds,
        "totals": {
            "tracked": len(features),
            "known_mcap_liquidity": known_pair_count,
            "missing_mcap_or_liquidity": len(features) - known_pair_count,
        },
        "dimensions": {
            "mcap": _ordered_meta(MCAP_BUCKETS) + [{"key": "missing", "label": "Unknown"}],
            "liquidity": _ordered_meta(LIQUIDITY_BUCKETS) + [{"key": "missing", "label": "Unknown"}],
            "holders": _ordered_meta(HOLDER_BUCKETS) + [{"key": "missing", "label": "Unknown"}],
            "age": _ordered_meta(AGE_BUCKETS) + [{"key": "missing", "label": "Unknown"}],
            "activity": [{"key": key, "label": label} for key, label in ACTIVITY_BUCKETS],
            "policy": [{"key": key, "label": label} for key, label in POLICY_STATUSES],
            "graduation": [
                {"key": "not_graduated", "label": "Not graduated"},
                {"key": "graduated", "label": "Graduated"},
            ],
        },
        "breakdowns": {
            "launchpad": dict(launchpad_counts.most_common()),
            "graduation": dict(graduation_counts),
            "age": dict(age_counts),
            "holders": dict(holder_counts),
            "activity": dict(activity_counts),
            "policy": dict(policy_counts),
        },
        "cells_schema": CELL_SCHEMA,
        "cells": cells,
    }


def write_region_snapshot(snapshot: dict[str, Any], *, healthy: bool = True) -> None:
    """Keep the last healthy snapshot canonical; degraded runs live beside it."""
    target = REGION_SNAPSHOT_PATH if healthy else REGION_DEGRADED_SNAPSHOT_PATH
    atomic_write_json(target, snapshot)
