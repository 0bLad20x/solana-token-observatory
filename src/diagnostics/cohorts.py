"""Phase 3 — incident cohorts, horizon coverage and prospective outcomes.

The default evidence base is incident-only: first observation of a mint is a
prevalent BASELINE, not an entry into the state in which we happened to find it.
Baseline membership is reported separately and never mixed into escape/outcome
rates. Re-entries after observation gaps are censored for the same reason.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from .constants import (
    COHORT_HORIZONS_MINUTES,
    COHORT_OUTCOMES_PATH,
    MONITOR_CONTINUITY_FACTOR,
)
from .region_history import (
    EVENT_BASELINE,
    EVENT_ENTER,
    EVENT_GONE,
    EVENT_GRADUATION,
    EVENT_MOVE,
    EVENT_RETURN,
    _parse_iso,
    load_region_state,
    read_population_runs,
    read_transition_events,
)
from .regions import SEMANTIC_SCHEMA_HASH, compare_regions, region_label
from .storage import atomic_write_json

TIMELINE_KINDS = {EVENT_BASELINE, EVENT_ENTER, EVENT_MOVE, EVENT_RETURN}
INCIDENT_ENTRY_KINDS = {EVENT_ENTER, EVENT_MOVE}

COHORT_PRESETS: list[dict[str, Any]] = [
    {
        "key": "mass_point",
        "label": "Mass point $2k–5k × $2k–10k",
        "description": "Incident entries into the largest current cluster. Baseline/prevalent members are reported separately.",
        "mcap": {"2k_5k"},
        "liquidity": {"2k_10k"},
    },
    {
        "key": "fresh_launch",
        "label": "Fresh launches <30m",
        "description": "Incident state entries observed while the token is younger than 30 minutes; first-seen fresh tokens remain baseline evidence only.",
        "age": {"under_30m"},
    },
    {
        "key": "dust",
        "label": "Dust: < $2k mcap, < $100 liquidity",
        "description": "Incident entries into the bottom-left corner. Expected to be terminal, but measured prospectively.",
        "mcap": {"under_200", "200_2k"},
        "liquidity": {"under_1", "1_100"},
    },
    {
        "key": "stalled_micro",
        "label": "Dormant micro tokens",
        "description": "Incident entries with no trades in the last hour, stale 30 minutes, and market cap below $5k.",
        "mcap": {"under_200", "200_2k", "2k_5k"},
        "activity": {"dormant"},
    },
    {
        "key": "orphan_liquidity",
        "label": "Deep liquidity, almost no holders",
        "description": "$10k+ liquidity with at most 10 holders at incident entry.",
        "liquidity": {"10k_50k", "50k_plus"},
        "holders": {"0_2", "3_10"},
    },
    {
        "key": "pre_graduation",
        "label": "Approaching graduation ($50k–250k)",
        "description": "Incident entries while not graduated in the market-cap band where graduation may occur.",
        "mcap": {"50k_250k"},
        "graduation": {"not_graduated"},
    },
    {
        "key": "post_crash",
        "label": "Crashed into < $1 liquidity",
        "description": "Incident MOVE into the lowest liquidity region. Does anything recover?",
        "liquidity": {"under_1"},
        "kinds": {EVENT_MOVE},
    },
]

OUTCOME_KEYS = [
    "improved",
    "mixed",
    "same",
    "deteriorated",
    "graduated",
    "graduation_uncertain",
    "left_population",
    "unknown",
]


def _matches_state(preset: dict[str, Any], event: dict[str, Any]) -> bool:
    target = event.get("to") or {}
    region = target.get("region")
    if not region:
        return False
    mcap_key, _, liquidity_key = region.partition("~")
    if "mcap" in preset and mcap_key not in preset["mcap"]:
        return False
    if "liquidity" in preset and liquidity_key not in preset["liquidity"]:
        return False
    for field in ("holders", "activity", "graduation", "launchpad"):
        allowed = preset.get(field)
        if allowed and target.get(field) not in allowed:
            return False
    if preset.get("age") and event.get("age") not in preset["age"]:
        return False
    return True


def _is_incident_entry(preset: dict[str, Any], event: dict[str, Any]) -> bool:
    kinds = preset.get("kinds") or INCIDENT_ENTRY_KINDS
    if event.get("kind") not in kinds:
        return False
    if event.get("entry_censored"):
        return False
    if event.get("kind") == EVENT_MOVE and not event.get("continuity", False):
        return False
    return _matches_state(preset, event)


def _timelines(events: list[dict[str, Any]]):
    timeline: dict[str, list[tuple[datetime, str | None]]] = defaultdict(list)
    graduations: dict[str, list[tuple[datetime, datetime, bool]]] = defaultdict(list)

    for event in events:
        at = _parse_iso(event.get("at"))
        mint = event.get("mint")
        if at is None or not mint:
            continue
        kind = event.get("kind")
        if kind in TIMELINE_KINDS:
            timeline[mint].append((at, (event.get("to") or {}).get("region")))
        elif kind == EVENT_GONE:
            timeline[mint].append((at, None))
        elif kind == EVENT_GRADUATION:
            lower = _parse_iso(event.get("graduation_lower_at")) or at
            upper = _parse_iso(event.get("graduation_upper_at")) or at
            graduations[mint].append((lower, upper, bool(event.get("graduation_censored"))))

    for rows in timeline.values():
        rows.sort(key=lambda row: row[0])
    for rows in graduations.values():
        rows.sort(key=lambda row: row[1])
    return timeline, graduations


def _region_at(rows: list[tuple[datetime, str | None]], moment: datetime) -> str | None:
    index = bisect_right([row[0] for row in rows], moment) - 1
    return None if index < 0 else rows[index][1]


def _exit_time(rows: list[tuple[datetime, str | None]], entry_at: datetime, region: str):
    start = bisect_right([row[0] for row in rows], entry_at)
    for at, value in rows[start:]:
        if value != region:
            return at
    return None


def _graduation_status(
    intervals: list[tuple[datetime, datetime, bool]],
    after: datetime,
    until: datetime,
) -> str | None:
    """Return definite/uncertain graduation inside a cohort horizon."""
    uncertain = False
    for lower, upper, censored in intervals:
        if upper <= after or lower > until:
            continue
        if lower > after and upper <= until:
            return "graduated"
        # The interval crosses the entry or horizon boundary. We know a
        # graduation was observed, but cannot assign it to this horizon exactly.
        if censored or lower <= after < upper or lower <= until < upper:
            uncertain = True
    return "graduation_uncertain" if uncertain else None


def _prepare_observation_runs(population_runs: list[dict[str, Any]]):
    rows = []
    for row in population_runs:
        at = _parse_iso(row.get("timestamp"))
        if at is None:
            continue
        interval = max(int(row.get("expected_interval_seconds") or 300), 1)
        rows.append((at, interval))
    rows.sort(key=lambda item: item[0])
    return rows


def _horizon_observed(
    entry_at: datetime,
    target_at: datetime,
    observation_runs: list[tuple[datetime, int]],
) -> bool:
    """True only when the concrete [entry, target] interval is continuously observed."""
    if not observation_runs:
        return False
    stamps = [row[0] for row in observation_runs]
    start = bisect_right(stamps, entry_at) - 1
    if start < 0:
        return False
    end = bisect_left(stamps, target_at)
    if end >= len(stamps):
        return False

    start_gap = max((entry_at - stamps[start]).total_seconds(), 0.0)
    if start_gap > observation_runs[start][1] * MONITOR_CONTINUITY_FACTOR:
        return False

    for idx in range(start + 1, end + 1):
        gap = (stamps[idx] - stamps[idx - 1]).total_seconds()
        allowed = max(observation_runs[idx - 1][1], observation_runs[idx][1]) * MONITOR_CONTINUITY_FACTOR
        if gap > allowed:
            return False
    return True


def _score(spells, timeline, graduations, horizons, now, observation_runs):
    outcomes = []
    survival = []
    for horizon in horizons:
        counts: Counter[str] = Counter()
        inside = left = 0
        skipped_not_mature = skipped_gap = 0
        for mint, entry_at, region, exit_at in spells:
            target_moment = entry_at + timedelta(minutes=horizon)
            if target_moment > now:
                skipped_not_mature += 1
                continue
            if not _horizon_observed(entry_at, target_moment, observation_runs):
                skipped_gap += 1
                continue

            rows = timeline.get(mint, [])
            graduation = _graduation_status(graduations.get(mint, []), entry_at, target_moment)
            if graduation:
                counts[graduation] += 1
            else:
                position = _region_at(rows, target_moment)
                if position is None:
                    counts["left_population"] += 1
                else:
                    counts[compare_regions(region, position)] += 1

            if exit_at is not None and exit_at <= target_moment:
                left += 1
            else:
                inside += 1

        matured = sum(counts.values())
        outcomes.append(
            {
                "horizon_minutes": horizon,
                "n": matured,
                "skipped_not_mature": skipped_not_mature,
                "skipped_observation_gap": skipped_gap,
                **{key: counts.get(key, 0) for key in OUTCOME_KEYS},
                "pct": {
                    key: round(counts.get(key, 0) / matured * 100, 2) if matured else None
                    for key in OUTCOME_KEYS
                },
            }
        )
        observed = inside + left
        survival.append(
            {
                "horizon_minutes": horizon,
                "n": observed,
                "skipped_observation_gap": skipped_gap,
                "still_inside": inside,
                "still_inside_pct": round(inside / observed * 100, 2) if observed else None,
            }
        )
    return outcomes, survival


def build_cohort_outcomes(
    state: dict[str, Any] | None = None,
    events: list[dict[str, Any]] | None = None,
    now: datetime | None = None,
    horizons: list[int] | None = None,
    presets: list[dict[str, Any]] | None = None,
    max_entries_per_cohort: int = 30_000,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    horizons = horizons or COHORT_HORIZONS_MINUTES
    presets = presets or COHORT_PRESETS
    state = state if state is not None else load_region_state()
    legacy_rows = semantic_rows = 0
    if events is None:
        events, legacy_rows, semantic_rows = read_transition_events()

    population_runs = read_population_runs()
    observation_runs = _prepare_observation_runs(population_runs)
    timeline, graduations = _timelines(events)

    current_members: dict[str, int] = {preset["key"]: 0 for preset in presets}
    for record in state.get("mints", {}).values():
        if record.get("gone_at"):
            continue
        for preset in presets:
            if preset.get("age"):
                continue
            probe = {
                "to": {
                    "region": record.get("region"),
                    "holders": record.get("holders"),
                    "activity": record.get("activity"),
                    "graduation": record.get("graduation"),
                    "launchpad": record.get("launchpad"),
                }
            }
            if _matches_state(preset, probe):
                current_members[preset["key"]] += 1

    cohorts = []
    for preset in presets:
        incident_events = [event for event in events if _is_incident_entry(preset, event)]
        incident_events.sort(key=lambda event: _parse_iso(event.get("at")) or datetime.min.replace(tzinfo=timezone.utc))
        incident_events = incident_events[-max_entries_per_cohort:]

        baseline_events = [
            event for event in events
            if event.get("kind") == EVENT_BASELINE and _matches_state(preset, event)
        ]
        baseline_mints = {event.get("mint") for event in baseline_events if event.get("mint")}

        entries = [
            (event["mint"], _parse_iso(event["at"]), (event.get("to") or {})["region"])
            for event in incident_events
            if _parse_iso(event.get("at")) is not None
        ]

        spells = []
        destinations: Counter[str] = Counter()
        for mint, entry_at, region in entries:
            rows = timeline.get(mint, [])
            exit_at = _exit_time(rows, entry_at, region)
            if exit_at is not None:
                destinations[_region_at(rows, exit_at) or "left_population"] += 1
            spells.append((mint, entry_at, region, exit_at))

        first_spells: list[tuple] = []
        seen_mints: set[str] = set()
        for spell in spells:
            if spell[0] in seen_mints:
                continue
            seen_mints.add(spell[0])
            first_spells.append(spell)

        episode_outcomes, episode_survival = _score(
            spells, timeline, graduations, horizons, now, observation_runs
        )
        outcomes, survival = _score(
            first_spells, timeline, graduations, horizons, now, observation_runs
        )

        total_destinations = sum(destinations.values())
        cohorts.append(
            {
                "key": preset["key"],
                "label": preset["label"],
                "description": preset["description"],
                "definition": {
                    field: sorted(preset[field])
                    for field in ("mcap", "liquidity", "holders", "activity", "graduation", "age", "launchpad")
                    if preset.get(field)
                },
                "current_members": current_members.get(preset["key"], 0),
                "baseline_observed": len(baseline_events),
                "baseline_unique_mints": len(baseline_mints),
                "episodes_total": len(spells),
                "unique_mints": len(seen_mints),
                "first_entry_at": min((row[1] for row in entries), default=None),
                "outcomes": outcomes,
                "survival": survival,
                "episode_outcomes": episode_outcomes,
                "episode_survival": episode_survival,
                "top_destinations": [
                    {
                        "region": region,
                        "label": "left population" if region == "left_population" else region_label(region),
                        "count": count,
                        "pct": round(count / total_destinations * 100, 2) if total_destinations else None,
                    }
                    for region, count in destinations.most_common(10)
                ],
            }
        )

    matured_any = any(row["n"] > 0 for cohort in cohorts for row in cohort["outcomes"])
    return {
        "schema_version": 2,
        "semantic_schema_hash": SEMANTIC_SCHEMA_HASH,
        "generated_at": now.isoformat(),
        "horizons_minutes": horizons,
        "coverage": {
            "events": len(events),
            "legacy_events_ignored": legacy_rows,
            "semantic_events_ignored": semantic_rows,
            "healthy_observation_runs": len(observation_runs),
            "mints_with_timeline": len(timeline),
            "has_matured_outcomes": matured_any,
        },
        "outcome_keys": OUTCOME_KEYS,
        "counting": "outcomes = first incident entry per mint; episode_outcomes = every incident entry; baseline is separate",
        "cohorts": cohorts,
    }


def write_cohort_outcomes(outcomes: dict[str, Any]) -> None:
    atomic_write_json(COHORT_OUTCOMES_PATH, outcomes)
