from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

# Rule 1 -- Failed to Ignite.
# T0 = first observed by our collector; evaluate from T+10 onward.
OBSERVATION_MINUTES = 10
LIQUIDITY_FLOOR = 1_000.0
MCAP_FLOOR = 3_000.0
HOLDER_FLOOR = 300

# Rule 2 -- Early Continuation Failure.
# T0 = token created_at; evaluate only inside T+30 .. T+31 minute.
RULE2_CHECKPOINT_MINUTES = 30
RULE2_MAX_CHANGES = 10
RULE2_ESTABLISHED_MCAP = 50_000.0
RULE2_ESTABLISHED_LIQUIDITY = 5_000.0
RULE2_CHECKPOINT_GRACE_SECONDS = 60.0

# Rule 3 -- Persistent Economic Absence.
# T0 = token created_at; evaluate only inside T+5 .. T+6 minute.
RULE3_CHECKPOINT_MINUTES = 5
RULE3_CHECKPOINT_GRACE_SECONDS = 60.0

# Rule 4 / Rule 5 -- permanent post-early-phase collapse floors.
# T0 = token created_at; start at T+30 and never expire.
COLLAPSE_GRACE_MINUTES = 30

# Rule 6 -- Early Holder Failure.
# T0 = first observed by our collector; evaluate the T+30 checkpoint.
RULE6_CHECKPOINT_MINUTES = 30
RULE6_HOLDER_FLOOR = 5

# Rule 7 -- Persistent Source Inactivity.
# Freshly polled mints with no new Jupiter source version for 24h retire.
RULE7_INACTIVITY_HOURS = 24
RULE7_MAX_POLL_LAG_SECONDS = 60.0


@dataclass(frozen=True, slots=True)
class CollapseRule:
    key: str
    field: str
    floor: float
    reason: str


COLLAPSE_RULES = (
    CollapseRule(
        key="rule4",
        field="liquidity",
        floor=2_000.0,
        reason="liquidity_collapse_below_2000",
    ),
    CollapseRule(
        key="rule5",
        field="mcap",
        floor=2_000.0,
        reason="mcap_collapse_below_2000",
    ),
)


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


def classify_rule1(payload: dict[str, Any]) -> str | None:
    liquidity = _as_float(payload, "liquidity")
    mcap = _as_float(payload, "mcap")
    holders = _as_int(payload, "holderCount")

    low_liquidity = liquidity is not None and liquidity < LIQUIDITY_FLOOR
    low_mcap_and_holders = (
        mcap is not None
        and mcap < MCAP_FLOOR
        and holders is not None
        and holders < HOLDER_FLOOR
    )

    if low_liquidity and low_mcap_and_holders:
        return "liquidity_below_1000_and_mcap_below_3000_and_holders_below_300"
    if low_liquidity:
        return "liquidity_below_1000"
    if low_mcap_and_holders:
        return "mcap_below_3000_and_holders_below_300"
    return None


def classify_rule2(payload: dict[str, Any], changes_in_window: int) -> str | None:
    mcap = _as_float(payload, "mcap")
    liquidity = _as_float(payload, "liquidity")

    if mcap is None or liquidity is None:
        return None
    if mcap >= RULE2_ESTABLISHED_MCAP and liquidity >= RULE2_ESTABLISHED_LIQUIDITY:
        return None
    if changes_in_window <= RULE2_MAX_CHANGES:
        return "early_continuation_failure"
    return None


def classify_rule3(has_economic_data: bool) -> str | None:
    if has_economic_data:
        return None
    return "economic_data_missing_at_5m"


def classify_rule6(payload: dict[str, Any]) -> str | None:
    holders = _as_int(payload, "holderCount")
    if holders is not None and holders < RULE6_HOLDER_FLOOR:
        return "holder_count_below_5_at_30m"
    return None


def classify_rule7(
    first_observed_at: datetime | None,
    last_polled_at: datetime | None,
    last_changed_at: datetime | None,
    now: datetime,
) -> str | None:
    if (
        first_observed_at is None
        or last_polled_at is None
        or last_changed_at is None
    ):
        return None

    poll_age_seconds = (now - last_polled_at).total_seconds()
    if poll_age_seconds > RULE7_MAX_POLL_LAG_SECONDS:
        return None

    unchanged_seconds = (now - last_changed_at).total_seconds()
    if unchanged_seconds >= RULE7_INACTIVITY_HOURS * 60 * 60:
        return "source_unchanged_for_24h"
    return None
