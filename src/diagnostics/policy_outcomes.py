"""Outcome evidence for shadow demotion/retirement decisions.

This module never evaluates a rule and never changes tracking. It only scores
what happened after WOULD_DEMOTE / WOULD_RETIRE events.
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

DEFAULT_HORIZONS = [5, 15, 30, 60, 360, 1440]
MILESTONES = ("reached_10k", "reached_50k", "reached_200k", "graduated_after_action")


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
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def _healthy_runs() -> list[tuple[datetime, int]]:
    rows = []
    for row in _read_jsonl(POLICY_RUNS_PATH):
        if not (row.get("collector_health") or {}).get("healthy"):
            continue
        if row.get("technical_validation") != "ok":
            continue
        at = _parse_iso(row.get("timestamp"))
        if at:
            rows.append((at, max(int(row.get("interval_seconds") or 60), 1)))
    return sorted(rows)


def _observed(start_at: datetime, end_at: datetime, runs: list[tuple[datetime, int]]) -> bool:
    if end_at <= start_at:
        return True
    if not runs:
        return False
    stamps = [row[0] for row in runs]
    start = bisect_right(stamps, start_at) - 1
    end = bisect_left(stamps, end_at)
    if start < 0 or end >= len(stamps):
        return False
    if (start_at - stamps[start]).total_seconds() > runs[start][1] * MONITOR_CONTINUITY_FACTOR:
        return False
    for idx in range(start + 1, end + 1):
        allowed = max(runs[idx - 1][1], runs[idx][1]) * MONITOR_CONTINUITY_FACTOR
        if (stamps[idx] - stamps[idx - 1]).total_seconds() > allowed:
            return False
    return True


def _episodes(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], dict[str, Any]] = {}
    relevant = {
        "WOULD_DEMOTE", "WOULD_RETIRE", "RECOVERED", "OUTCOME_CHECK",
        "OUTCOME_MILESTONE", "STAYED_DEAD",
    }
    for event in sorted(events, key=lambda row: row.get("timestamp") or ""):
        if event.get("event") not in relevant:
            continue
        rule_key = event.get("rule_key")
        mint = event.get("mint")
        applied_raw = event.get("applied_at") or event.get("would_retire_at")
        if not rule_key or not mint or not applied_raw:
            continue
        key = (rule_key, mint, applied_raw)
        episode = grouped.setdefault(key, {
            "rule_key": rule_key,
            "rule_id": event.get("rule_id"),
            "rule_version": event.get("rule_version"),
            "rule_type": event.get("rule_type"),
            "action": event.get("action") or "retire",
            "mint": mint,
            "applied_at": applied_raw,
            "recovered_at": None,
            "stayed_dead_at": None,
            "milestones": {},
        })
        name = event.get("event")
        at = event.get("timestamp")
        if name == "RECOVERED" and not episode["recovered_at"]:
            episode["recovered_at"] = at
        elif name == "STAYED_DEAD" and not episode["stayed_dead_at"]:
            episode["stayed_dead_at"] = at
        elif name == "OUTCOME_MILESTONE" and event.get("milestone"):
            episode["milestones"].setdefault(event["milestone"], at)
        elif name == "OUTCOME_CHECK":
            for milestone in MILESTONES:
                if event.get(milestone):
                    episode["milestones"].setdefault(milestone, at)
    return sorted(grouped.values(), key=lambda row: row["applied_at"])


def _horizon_row(episodes, horizon: int, now: datetime, runs):
    counts = Counter()
    for episode in episodes:
        start = _parse_iso(episode.get("applied_at"))
        if start is None:
            counts["invalid"] += 1
            continue
        target = start + timedelta(minutes=horizon)
        if target > now:
            counts["not_mature"] += 1
            continue
        if not _observed(start, target, runs):
            counts["observation_gap"] += 1
            continue
        counts["matured"] += 1
        recovered = _parse_iso(episode.get("recovered_at"))
        counts["recovered"] += int(recovered is not None and recovered <= target)
        for milestone in MILESTONES:
            reached = _parse_iso((episode.get("milestones") or {}).get(milestone))
            counts[milestone] += int(reached is not None and reached <= target)

    matured = counts["matured"]
    row = {
        "horizon_minutes": horizon,
        "matured": matured,
        "recovered": counts["recovered"],
        "not_recovered": matured - counts["recovered"],
        "not_mature": counts["not_mature"],
        "skipped_observation_gap": counts["observation_gap"],
        "recovery_rate_pct": round(counts["recovered"] / matured * 100, 3) if matured else None,
    }
    for milestone in MILESTONES:
        row[milestone] = counts[milestone]
        row[f"{milestone}_rate_pct"] = round(counts[milestone] / matured * 100, 3) if matured else None
    return row


def build_policy_outcomes(now: datetime | None = None, horizons: list[int] | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    horizons = sorted(set(horizons or DEFAULT_HORIZONS))
    events = _read_jsonl(DECISION_EVENTS_PATH)
    episodes = _episodes(events)
    runs = _healthy_runs()
    by_rule: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for episode in episodes:
        by_rule[episode["rule_key"]].append(episode)

    rule_rows = []
    mint_actions: dict[str, set[str]] = defaultdict(set)
    for key, rows in sorted(by_rule.items()):
        first_by_mint: dict[str, dict[str, Any]] = {}
        for row in rows:
            first_by_mint.setdefault(row["mint"], row)
            mint_actions[row["mint"]].add(row["action"])
        unique = list(first_by_mint.values())
        rule_rows.append({
            "rule_key": key,
            "rule_id": rows[0].get("rule_id"),
            "rule_version": rows[0].get("rule_version"),
            "rule_type": rows[0].get("rule_type"),
            "action": rows[0].get("action"),
            "applied_episodes": len(rows),
            "applied_unique_mints": len(unique),
            # Backwards-compatible aliases for the old dashboard/export.
            "would_retire_episodes": len(rows) if rows[0].get("action") == "retire" else 0,
            "would_retire_unique_mints": len(unique) if rows[0].get("action") == "retire" else 0,
            "recovered_ever_unique_mints": len({row["mint"] for row in rows if row.get("recovered_at")}),
            "stayed_dead_event_unique_mints": len({row["mint"] for row in rows if row.get("stayed_dead_at")}),
            "horizons": [_horizon_row(unique, horizon, now, runs) for horizon in horizons],
            "episode_horizons": [_horizon_row(rows, horizon, now, runs) for horizon in horizons],
        })

    by_action = Counter()
    for actions in mint_actions.values():
        for action in actions:
            by_action[action] += 1
    return {
        "schema_version": 2,
        "generated_at": now.isoformat(),
        "counting": "rule rates use the first applied episode per mint; episode_horizons include re-entry",
        "maturity": "each horizon needs continuous healthy monitor coverage",
        "coverage": {"decision_events": len(events), "healthy_monitor_runs": len(runs)},
        "global": {
            "applied_unique_union": len(mint_actions),
            "would_retire_unique_union": by_action.get("retire", 0),
            "unique_mints_by_action": dict(by_action),
        },
        "rules": rule_rows,
    }


def write_policy_outcomes(outcomes: dict[str, Any]) -> None:
    atomic_write_json(POLICY_OUTCOMES_PATH, outcomes)
