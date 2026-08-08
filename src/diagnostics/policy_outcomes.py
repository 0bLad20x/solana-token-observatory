"""Derived Phase-7 evidence from policy simulation events.

No rule is evaluated here. This module only asks what happened after an already
recorded WOULD_RETIRE event, with horizon-specific maturity and observation-gap
checks. Rates are first-event-per-mint by default; episode counts remain visible
for diagnosing repeated re-entry into the same rule.
"""

from __future__ import annotations

import json
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from .constants import (
    DECISION_EVENTS_PATH,
    MONITOR_CONTINUITY_FACTOR,
    POLICY_OUTCOMES_PATH,
    POLICY_RUNS_PATH,
)
from .storage import atomic_write_json

DEFAULT_HORIZONS = [30, 60, 360, 1440]


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _read_jsonl(path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def _healthy_runs() -> list[tuple[datetime, int]]:
    rows = []
    for row in _read_jsonl(POLICY_RUNS_PATH):
        health = row.get("collector_health") or {}
        if not health.get("healthy") or row.get("technical_validation") != "ok":
            continue
        at = _parse_iso(row.get("timestamp"))
        if at is None:
            continue
        rows.append((at, max(int(row.get("interval_seconds") or 300), 1)))
    rows.sort(key=lambda item: item[0])
    return rows


def _observed(start_at: datetime, end_at: datetime, runs: list[tuple[datetime, int]]) -> bool:
    if end_at <= start_at:
        return True
    if not runs:
        return False
    stamps = [row[0] for row in runs]
    start = bisect_right(stamps, start_at) - 1
    if start < 0:
        return False
    end = bisect_left(stamps, end_at)
    if end >= len(stamps):
        return False
    if (start_at - stamps[start]).total_seconds() > runs[start][1] * MONITOR_CONTINUITY_FACTOR:
        return False
    for idx in range(start + 1, end + 1):
        gap = (stamps[idx] - stamps[idx - 1]).total_seconds()
        allowed = max(runs[idx - 1][1], runs[idx][1]) * MONITOR_CONTINUITY_FACTOR
        if gap > allowed:
            return False
    return True


def _episodes(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], dict[str, Any]] = {}
    for event in sorted(events, key=lambda row: row.get("timestamp") or ""):
        if event.get("event") not in {"WOULD_RETIRE", "RECOVERED", "OUTCOME_CHECK", "STAYED_DEAD"}:
            continue
        rule_key = event.get("rule_key")
        mint = event.get("mint")
        would_at_raw = event.get("would_retire_at")
        if not rule_key or not mint or not would_at_raw:
            continue
        key = (rule_key, mint, would_at_raw)
        episode = grouped.setdefault(
            key,
            {
                "rule_key": rule_key,
                "rule_id": event.get("rule_id"),
                "rule_version": event.get("rule_version"),
                "rule_type": event.get("rule_type"),
                "mint": mint,
                "would_retire_at": would_at_raw,
                "recovered_at": None,
                "stayed_dead_at": None,
                "outcome_checks": [],
            },
        )
        name = event.get("event")
        at = event.get("timestamp")
        if name == "RECOVERED" and episode["recovered_at"] is None:
            episode["recovered_at"] = at
        elif name == "STAYED_DEAD" and episode["stayed_dead_at"] is None:
            episode["stayed_dead_at"] = at
        elif name == "OUTCOME_CHECK":
            episode["outcome_checks"].append(event.get("horizon_minutes"))
    return sorted(grouped.values(), key=lambda row: row["would_retire_at"])


def _horizon_row(episodes, horizon: int, now: datetime, runs):
    counts = Counter()
    for episode in episodes:
        start = _parse_iso(episode.get("would_retire_at"))
        if start is None:
            counts["invalid"] += 1
            continue
        target = start + timedelta(minutes=horizon)
        if target > now:
            counts["not_mature"] += 1
            continue
        recovered = _parse_iso(episode.get("recovered_at"))
        if recovered is not None and recovered <= target:
            if _observed(start, recovered, runs):
                counts["recovered"] += 1
            else:
                counts["observation_gap"] += 1
            continue
        if _observed(start, target, runs):
            counts["not_recovered"] += 1
        else:
            counts["observation_gap"] += 1

    matured = counts["recovered"] + counts["not_recovered"]
    return {
        "horizon_minutes": horizon,
        "matured": matured,
        "recovered": counts["recovered"],
        "not_recovered": counts["not_recovered"],
        "not_mature": counts["not_mature"],
        "skipped_observation_gap": counts["observation_gap"],
        "recovery_rate_pct": round(counts["recovered"] / matured * 100, 3) if matured else None,
        "not_recovered_rate_pct": round(counts["not_recovered"] / matured * 100, 3) if matured else None,
    }


def build_policy_outcomes(
    now: datetime | None = None,
    horizons: list[int] | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    horizons = sorted(set(horizons or DEFAULT_HORIZONS))
    events = _read_jsonl(DECISION_EVENTS_PATH)
    episodes = _episodes(events)
    runs = _healthy_runs()

    by_rule: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for episode in episodes:
        by_rule[episode["rule_key"]].append(episode)

    rule_rows = []
    mint_rules: dict[str, set[str]] = defaultdict(set)
    for rule_key, rows in sorted(by_rule.items()):
        rows.sort(key=lambda row: row["would_retire_at"])
        first_by_mint: dict[str, dict[str, Any]] = {}
        for row in rows:
            first_by_mint.setdefault(row["mint"], row)
            mint_rules[row["mint"]].add(rule_key)
        unique_rows = list(first_by_mint.values())
        confirmed_dead = {
            row["mint"] for row in rows if row.get("stayed_dead_at") is not None
        }
        recovered_ever = {
            row["mint"] for row in rows if row.get("recovered_at") is not None
        }
        rule_rows.append(
            {
                "rule_key": rule_key,
                "rule_id": rows[0].get("rule_id"),
                "rule_version": rows[0].get("rule_version"),
                "rule_type": rows[0].get("rule_type"),
                "would_retire_episodes": len(rows),
                "would_retire_unique_mints": len(unique_rows),
                "recovered_ever_unique_mints": len(recovered_ever),
                "stayed_dead_event_unique_mints": len(confirmed_dead),
                "horizons": [_horizon_row(unique_rows, horizon, now, runs) for horizon in horizons],
                "episode_horizons": [_horizon_row(rows, horizon, now, runs) for horizon in horizons],
            }
        )

    overlap_hist = Counter(len(rule_keys) for rule_keys in mint_rules.values())
    return {
        "schema_version": 1,
        "generated_at": now.isoformat(),
        "counting": "rule rates use first WOULD_RETIRE episode per mint; episode_horizons include re-entries",
        "maturity": "a horizon counts only when the concrete observation interval is continuous; early recovery only needs coverage until recovery",
        "coverage": {
            "decision_events": len(events),
            "healthy_monitor_runs": len(runs),
        },
        "global": {
            "would_retire_unique_union": len(mint_rules),
            "rule_membership_histogram": {str(k): v for k, v in sorted(overlap_hist.items())},
            "mints_matching_multiple_rules": sum(v for k, v in overlap_hist.items() if k > 1),
        },
        "rules": rule_rows,
    }


def write_policy_outcomes(outcomes: dict[str, Any]) -> None:
    atomic_write_json(POLICY_OUTCOMES_PATH, outcomes)
