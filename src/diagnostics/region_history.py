"""Phase 2 — region transitions, dwell time and population flow.

Event log format v2. Every event carries the full observed state on both sides
of the transition (`from` / `to`), the observation gap that produced it, and an
interval-censored dwell time. That is what makes it possible to ask later
"what happened to tokens that had 3-10 holders and no activity when they left"
without re-deriving anything from the current state.

This module is only ever called for a healthy monitor run. A broken collector
cycle produces a partial population, and writing that into an append-only log
would manufacture MOVE and GONE events that never happened.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Any, Iterable

from .constants import (
    MONITOR_CONTINUITY_FACTOR,
    REGION_FLOW_MIN_MOVES,
    REGION_FLOW_MIN_MOVING_MINTS,
    REGION_FLOW_PATH,
    REGION_FLOW_WINDOW_HOURS,
    REGION_POPULATION_RUN_LIMIT,
    REGION_POPULATION_RUNS_PATH,
    REGION_STATE_PATH,
    REGION_TRANSITIONS_PATH,
)
from .regions import (
    SEMANTIC_SCHEMA_HASH,
    classify_feature,
    compare_regions,
    region_directions,
    region_label,
)
from .storage import append_jsonl, atomic_write_json

EVENT_SCHEMA_VERSION = 2

DWELL_BINS = [
    ("0_5", "<5m", 0.0, 5.0),
    ("5_15", "5–15m", 5.0, 15.0),
    ("15_30", "15–30m", 15.0, 30.0),
    ("30_60", "30–60m", 30.0, 60.0),
    ("1_3h", "1–3h", 60.0, 180.0),
    ("3_6h", "3–6h", 180.0, 360.0),
    ("6_24h", "6–24h", 360.0, 1_440.0),
    ("24h_plus", ">=24h", 1_440.0, None),
]

EVENT_BASELINE = "baseline"
EVENT_ENTER = "enter"  # reserved for future explicit incident-entry sources
EVENT_MOVE = "move"
EVENT_GRADUATION = "graduation"
EVENT_GONE = "gone"
EVENT_RETURN = "return"

ATTRIBUTE_FIELDS = ("region", "holders", "activity", "graduation", "launchpad")


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def load_region_state() -> dict[str, Any]:
    if not REGION_STATE_PATH.exists():
        return {
            "schema_version": 2,
            "semantic_schema_hash": SEMANTIC_SCHEMA_HASH,
            "updated_at": None,
            "mints": {},
        }
    try:
        state = json.loads(REGION_STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Region-State unlesbar: {REGION_STATE_PATH}: {exc}") from exc
    if state.get("schema_version") not in (1, 2):
        raise RuntimeError("region_state.json: unbekannte schema_version")
    existing_hash = state.get("semantic_schema_hash")
    if state.get("mints") and existing_hash != SEMANTIC_SCHEMA_HASH:
        raise RuntimeError(
            "region_state.json gehoert zu einer anderen semantischen Bucket-Definition. "
            "Vor dem neuen Langzeitlauf die Region-Artefakte einmalig loeschen."
        )
    state["schema_version"] = 2
    state["semantic_schema_hash"] = SEMANTIC_SCHEMA_HASH
    state.setdefault("mints", {})
    return state


def dwell_bin(minutes: float | None) -> str | None:
    if minutes is None:
        return None
    for key, _label, low, high in DWELL_BINS:
        if minutes >= low and (high is None or minutes < high):
            return key
    return None


def _attributes(region: dict[str, str]) -> dict[str, str]:
    return {
        "region": region["region"],
        "holders": region["holder_bucket"],
        "activity": region["activity_bucket"],
        "graduation": region["graduation"],
        "launchpad": region["launchpad"],
    }


def _record_attributes(record: dict[str, Any]) -> dict[str, Any]:
    return {field: record.get(field) for field in ATTRIBUTE_FIELDS}


def _event(
    mint: str,
    kind: str,
    now: datetime,
    source: dict[str, Any] | None,
    target: dict[str, Any] | None,
    *,
    expected_interval_seconds: int,
    continuity: bool,
    entry_censored: bool | None = None,
    gap_seconds: float | None = None,
    dwell_lower: float | None = None,
    dwell_upper: float | None = None,
    dwell_censored: bool | None = None,
    age_bucket: str | None = None,
    age_minutes: float | None = None,
    graduation_lower_at: datetime | None = None,
    graduation_upper_at: datetime | None = None,
    graduation_censored: bool | None = None,
) -> dict[str, Any]:
    from_region = (source or {}).get("region")
    to_region = (target or {}).get("region")
    return {
        "schema": EVENT_SCHEMA_VERSION,
        "semantic_schema_hash": SEMANTIC_SCHEMA_HASH,
        "mint": mint,
        "at": now.isoformat(),
        "kind": kind,
        "from": source,
        "to": target,
        "transition": compare_regions(from_region, to_region) if source and target else None,
        "direction": region_directions(from_region, to_region) if source and target else None,
        "entry_censored": entry_censored,
        "dwell_lower_minutes": round(dwell_lower, 2) if dwell_lower is not None else None,
        "dwell_upper_minutes": round(dwell_upper, 2) if dwell_upper is not None else None,
        "dwell_censored": dwell_censored,
        "expected_interval_seconds": int(expected_interval_seconds),
        "gap_seconds": round(gap_seconds, 1) if gap_seconds is not None else None,
        "continuity": bool(continuity),
        "age": age_bucket,
        "age_minutes": round(age_minutes, 1) if age_minutes is not None else None,
        "graduation_lower_at": graduation_lower_at.isoformat() if graduation_lower_at else None,
        "graduation_upper_at": graduation_upper_at.isoformat() if graduation_upper_at else None,
        "graduation_censored": graduation_censored,
    }


def update_region_history(
    features: list[dict[str, Any]],
    now: datetime,
    run_id: str,
    interval_seconds: int,
    healthy: bool = True,
    continuity: bool = False,
    infer_gone: bool | None = None,
) -> dict[str, Any]:
    """Advance per-mint semantic state from a healthy observation.

    Initial observations are BASELINE/PREVALENT, not incident entries. A MOVE
    is incident only when it is observed across a continuous cadence. GONE is
    inferred only when the previous healthy observation is still inside the
    continuity window; after downtime, absence means UNKNOWN rather than gone.
    """
    if not healthy:
        return {"skipped": True, "reason": "unhealthy_run"}

    if infer_gone is None:
        infer_gone = continuity

    state = load_region_state()
    mints: dict[str, Any] = state["mints"]
    events: list[dict[str, Any]] = []
    seen: set[str] = set()

    continuity_limit_seconds = interval_seconds * MONITOR_CONTINUITY_FACTOR
    interval_minutes = interval_seconds / 60

    region_counts: Counter[str] = Counter()
    activity_counts: Counter[str] = Counter()
    policy_counts: Counter[str] = Counter()
    transition_counts: Counter[str] = Counter()
    moved = 0

    for feature in features:
        mint = feature["mint"]
        seen.add(mint)
        region = classify_feature(feature)
        current = _attributes(region)
        region_counts[current["region"]] += 1
        activity_counts[current["activity"]] += 1
        policy_counts[region["policy_status"]] += 1
        age_minutes = feature.get("age_minutes")

        record = mints.get(mint)
        if record is None:
            # First observation is prevalent by definition: we do not know when
            # this mint entered the region in which we first found it.
            mints[mint] = {
                **current,
                "entered_at": now.isoformat(),
                "entry_censored": True,
                "first_seen_at": now.isoformat(),
                "last_seen_at": now.isoformat(),
                "prior_region": None,
                "transitions": 0,
                "policy_status": region["policy_status"],
            }
            events.append(
                _event(
                    mint,
                    EVENT_BASELINE,
                    now,
                    None,
                    current,
                    expected_interval_seconds=interval_seconds,
                    continuity=continuity,
                    entry_censored=True,
                    age_bucket=region["age_bucket"],
                    age_minutes=age_minutes,
                )
            )
            continue

        previous = _record_attributes(record)
        last_seen = _parse_iso(record.get("last_seen_at"))
        gap_seconds = (now - last_seen).total_seconds() if last_seen else None
        stale_gap = (
            gap_seconds is None
            or gap_seconds > continuity_limit_seconds
            or not continuity
        )
        was_gone = bool(record.get("gone_at"))
        record.pop("absence_started_at", None)
        record.pop("absence_censored", None)

        record["last_seen_at"] = now.isoformat()
        record["policy_status"] = region["policy_status"]

        graduation_changed = (
            previous.get("graduation") != current.get("graduation")
            and current.get("graduation") == "graduated"
        )

        if was_gone:
            # RETURN starts a new censored spell. It is not also a MOVE. If the
            # token graduated while unobserved, preserve that as interval-censored
            # graduation evidence in a separate attribute event.
            record.pop("gone_at", None)
            events.append(
                _event(
                    mint,
                    EVENT_RETURN,
                    now,
                    previous,
                    current,
                    expected_interval_seconds=interval_seconds,
                    continuity=False,
                    entry_censored=True,
                    gap_seconds=gap_seconds,
                    age_bucket=region["age_bucket"],
                    age_minutes=age_minutes,
                )
            )
            if graduation_changed:
                events.append(
                    _event(
                        mint,
                        EVENT_GRADUATION,
                        now,
                        previous,
                        current,
                        expected_interval_seconds=interval_seconds,
                        continuity=False,
                        gap_seconds=gap_seconds,
                        age_bucket=region["age_bucket"],
                        age_minutes=age_minutes,
                        graduation_lower_at=last_seen,
                        graduation_upper_at=now,
                        graduation_censored=True,
                    )
                )
            record.update(current)
            record["prior_region"] = previous["region"]
            record["entered_at"] = now.isoformat()
            record["entry_censored"] = True
            continue

        if graduation_changed:
            events.append(
                _event(
                    mint,
                    EVENT_GRADUATION,
                    now,
                    previous,
                    current,
                    expected_interval_seconds=interval_seconds,
                    continuity=continuity and not stale_gap,
                    gap_seconds=gap_seconds,
                    age_bucket=region["age_bucket"],
                    age_minutes=age_minutes,
                    graduation_lower_at=last_seen,
                    graduation_upper_at=now,
                    graduation_censored=stale_gap,
                )
            )

        if previous["region"] != current["region"]:
            entered_at = _parse_iso(record.get("entered_at")) or now
            dwell_upper = max((now - entered_at).total_seconds() / 60, 0.0)
            dwell_lower = (
                max((last_seen - entered_at).total_seconds() / 60, 0.0)
                if last_seen
                else 0.0
            )
            censored = bool(record.get("entry_censored")) or stale_gap
            transition = compare_regions(previous["region"], current["region"])
            transition_counts[transition] += 1
            moved += 1
            events.append(
                _event(
                    mint,
                    EVENT_MOVE,
                    now,
                    previous,
                    current,
                    expected_interval_seconds=interval_seconds,
                    continuity=continuity and not stale_gap,
                    entry_censored=stale_gap,
                    gap_seconds=gap_seconds,
                    dwell_lower=dwell_lower,
                    dwell_upper=dwell_upper,
                    dwell_censored=censored,
                    age_bucket=region["age_bucket"],
                    age_minutes=age_minutes,
                )
            )
            record["prior_region"] = previous["region"]
            record["entered_at"] = now.isoformat()
            record["entry_censored"] = stale_gap
            record["transitions"] = int(record.get("transitions", 0)) + 1
        elif stale_gap:
            record["entry_censored"] = True

        record.update(current)

    gone_after = timedelta(seconds=max(interval_seconds * 3, 900))
    gone = 0
    for mint, record in mints.items():
        if mint in seen or record.get("gone_at"):
            continue

        # Absence itself needs a continuously observed clock. After downtime we
        # start that clock on the first healthy resumed run rather than pretending
        # we watched the token throughout the gap.
        absence_started = _parse_iso(record.get("absence_started_at"))
        if absence_started is None:
            record["absence_started_at"] = now.isoformat()
            record["absence_censored"] = not continuity
            continue
        if not infer_gone:
            record["absence_censored"] = True
            continue
        if record.get("absence_censored"):
            # First continuous run after a censored gap establishes a new clean
            # absence interval; only subsequent healthy runs can mature it.
            record["absence_started_at"] = now.isoformat()
            record["absence_censored"] = False
            continue
        if now - absence_started < gone_after:
            continue

        last_seen = _parse_iso(record.get("last_seen_at"))
        record["gone_at"] = now.isoformat()
        record.pop("absence_started_at", None)
        record.pop("absence_censored", None)
        gone += 1
        entered_at = _parse_iso(record.get("entered_at")) or now
        events.append(
            _event(
                mint,
                EVENT_GONE,
                now,
                _record_attributes(record),
                None,
                expected_interval_seconds=interval_seconds,
                continuity=True,
                gap_seconds=(now - last_seen).total_seconds() if last_seen else None,
                dwell_lower=max((last_seen - entered_at).total_seconds() / 60, 0.0) if last_seen else None,
                dwell_upper=max((now - entered_at).total_seconds() / 60, 0.0),
                dwell_censored=True,
            )
        )


    for event in events:
        event["run_id"] = run_id

    state["schema_version"] = 2
    state["semantic_schema_hash"] = SEMANTIC_SCHEMA_HASH
    state["updated_at"] = now.isoformat()
    append_jsonl(REGION_TRANSITIONS_PATH, events)
    atomic_write_json(REGION_STATE_PATH, state)

    population_record = {
        "schema_version": 2,
        "semantic_schema_hash": SEMANTIC_SCHEMA_HASH,
        "run_id": run_id,
        "timestamp": now.isoformat(),
        "expected_interval_seconds": interval_seconds,
        "continuity": bool(continuity),
        "tracked": len(features),
        "moved": moved,
        "gone": gone,
        "gone_inference_enabled": bool(infer_gone),
        "transitions": dict(transition_counts),
        "regions": dict(region_counts.most_common()),
        "activity": dict(activity_counts),
        "policy": dict(policy_counts),
    }
    append_jsonl(REGION_POPULATION_RUNS_PATH, [population_record])

    return {
        "events": len(events),
        "moved": moved,
        "gone": gone,
        "improved": transition_counts.get("improved", 0),
        "deteriorated": transition_counts.get("deteriorated", 0),
        "mixed": transition_counts.get("mixed", 0),
        "known_mints": len(mints),
        "continuity": bool(continuity),
        "gone_inference_enabled": bool(infer_gone),
    }


def read_transition_events(
    since: datetime | None = None,
) -> tuple[list[dict[str, Any]], int, int]:
    """Return (events, ignored_legacy_rows, ignored_semantic_rows)."""
    if not REGION_TRANSITIONS_PATH.exists():
        return [], 0, 0
    events: list[dict[str, Any]] = []
    legacy = 0
    semantic_mismatch = 0
    with REGION_TRANSITIONS_PATH.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("schema") != EVENT_SCHEMA_VERSION:
                legacy += 1
                continue
            if event.get("semantic_schema_hash") != SEMANTIC_SCHEMA_HASH:
                semantic_mismatch += 1
                continue
            if since is not None:
                at = _parse_iso(event.get("at"))
                if at is None or at < since:
                    continue
            events.append(event)
    return events, legacy, semantic_mismatch


def read_population_runs(limit: int = REGION_POPULATION_RUN_LIMIT) -> list[dict[str, Any]]:
    if not REGION_POPULATION_RUNS_PATH.exists():
        return []
    rows: list[dict[str, Any]] = []
    with REGION_POPULATION_RUNS_PATH.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("schema_version") != 2:
                continue
            if row.get("semantic_schema_hash") != SEMANTIC_SCHEMA_HASH:
                continue
            rows.append(row)
    return rows[-limit:]


def _quantile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round(fraction * (len(ordered) - 1)))))
    return round(ordered[index], 1)


def _coverage_summary(population_runs: list[dict[str, Any]], now: datetime) -> dict[str, Any]:
    ordered = sorted(
        (row for row in population_runs if _parse_iso(row.get("timestamp")) is not None),
        key=lambda row: _parse_iso(row["timestamp"]),
    )
    if not ordered:
        return {
            "observation_hours": None,
            "largest_gap_seconds": None,
            "coverage_fraction": None,
            "latest_continuous_minutes": 0.0,
        }

    stamps = [_parse_iso(row["timestamp"]) for row in ordered]
    intervals = [max(int(row.get("expected_interval_seconds") or 300), 1) for row in ordered]
    gaps = [max((b - a).total_seconds(), 0.0) for a, b in zip(stamps, stamps[1:])]
    largest_gap = max(gaps, default=0.0)
    span_seconds = max((stamps[-1] - stamps[0]).total_seconds(), 0.0)
    median_interval = median(intervals) if intervals else 300
    expected_runs = max(int(span_seconds / median_interval) + 1, 1)
    coverage_fraction = min(len(ordered) / expected_runs, 1.0)

    segment_start = stamps[0]
    for index, gap in enumerate(gaps, start=1):
        allowed = max(intervals[index - 1], intervals[index]) * MONITOR_CONTINUITY_FACTOR
        if gap > allowed:
            segment_start = stamps[index]
    latest_continuous_minutes = max((stamps[-1] - segment_start).total_seconds() / 60, 0.0)

    return {
        "observation_hours": round((now - stamps[0]).total_seconds() / 3600, 2),
        "largest_gap_seconds": round(largest_gap, 1),
        "coverage_fraction": round(coverage_fraction, 4),
        "latest_continuous_minutes": round(latest_continuous_minutes, 1),
    }


def build_region_flow(
    state: dict[str, Any] | None = None,
    events: Iterable[dict[str, Any]] | None = None,
    population_runs: list[dict[str, Any]] | None = None,
    now: datetime | None = None,
    window_hours: int = REGION_FLOW_WINDOW_HOURS,
) -> dict[str, Any]:
    """Aggregate the raw Phase-2 log into the artifact the dashboard renders."""
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(hours=window_hours)
    state = state if state is not None else load_region_state()
    legacy_rows = 0
    semantic_rows = 0
    if events is None:
        events, legacy_rows, semantic_rows = read_transition_events(since)
    else:
        events = list(events)
    population_runs = population_runs if population_runs is not None else read_population_runs()

    transitions: Counter[tuple[str, str]] = Counter()
    transition_dwell: dict[tuple[str, str], list[float]] = defaultdict(list)
    exits: Counter[str] = Counter()
    entries: Counter[str] = Counter()
    baselines: Counter[str] = Counter()
    returns: Counter[str] = Counter()
    dwell_by_region: dict[str, list[float]] = defaultdict(list)
    dwell_bounds: dict[str, list[float]] = defaultdict(list)
    censored_by_region: Counter[str] = Counter()
    dwell_hist: dict[str, Counter[str]] = defaultdict(Counter)
    class_by_region: dict[str, Counter[str]] = defaultdict(Counter)
    graduation_source: Counter[str] = Counter()
    gone_source: Counter[str] = Counter()
    launchpad_flow: dict[str, Counter[str]] = defaultdict(Counter)
    moving_mints: set[str] = set()
    exit_activity: dict[str, Counter[str]] = defaultdict(Counter)
    censored_moves = 0

    for event in events:
        kind = event.get("kind")
        source = event.get("from") or {}
        target = event.get("to") or {}
        source_region = source.get("region")
        target_region = target.get("region")
        launchpad = (source or target).get("launchpad") or "unknown"

        if kind == EVENT_MOVE and source_region and target_region:
            transitions[(source_region, target_region)] += 1
            exits[source_region] += 1
            entries[target_region] += 1
            if event.get("entry_censored"):
                censored_moves += 1
            else:
                moving_mints.add(event.get("mint"))
            class_by_region[source_region][event.get("transition") or "unknown"] += 1
            exit_activity[source_region][source.get("activity") or "unknown"] += 1
            launchpad_flow[launchpad]["moves"] += 1
            launchpad_flow[launchpad][event.get("transition") or "unknown"] += 1
            if not event.get("dwell_censored"):
                upper = event.get("dwell_upper_minutes")
                lower = event.get("dwell_lower_minutes")
                if upper is not None:
                    transition_dwell[(source_region, target_region)].append(float(upper))
                    dwell_by_region[source_region].append(float(upper))
                    if lower is not None:
                        dwell_bounds[source_region].append(float(lower))
                    bucket = dwell_bin(float(upper))
                    if bucket:
                        dwell_hist[source_region][bucket] += 1
            else:
                censored_by_region[source_region] += 1
        elif kind == EVENT_BASELINE and target_region:
            baselines[target_region] += 1
            launchpad_flow[launchpad]["baseline"] += 1
        elif kind == EVENT_ENTER and target_region:
            entries[target_region] += 1
            launchpad_flow[launchpad]["entered"] += 1
        elif kind == EVENT_RETURN and target_region:
            returns[target_region] += 1
            launchpad_flow[launchpad]["returned"] += 1
        elif kind == EVENT_GRADUATION and target_region:
            graduation_source[target_region] += 1
            launchpad_flow[launchpad]["graduated"] += 1
        elif kind == EVENT_GONE and source_region:
            gone_source[source_region] += 1
            exits[source_region] += 1
            transitions[(source_region, "left_population")] += 1
            exit_activity[source_region][source.get("activity") or "unknown"] += 1
            launchpad_flow[launchpad]["gone"] += 1

    current: Counter[str] = Counter()
    open_spells: dict[str, list[float]] = defaultdict(list)
    for record in state.get("mints", {}).values():
        if record.get("gone_at"):
            continue
        region = record.get("region")
        if not region:
            continue
        current[region] += 1
        entered_at = _parse_iso(record.get("entered_at"))
        if entered_at is not None and not record.get("entry_censored"):
            open_spells[region].append(max((now - entered_at).total_seconds() / 60, 0.0))

    region_keys = sorted(
        set(current) | set(entries) | set(exits) | set(graduation_source) | set(baselines) | set(returns),
        key=lambda key: (-(current.get(key, 0)), key),
    )

    region_rows = []
    for key in region_keys:
        completed = dwell_by_region.get(key, [])
        lower_bounds = dwell_bounds.get(key, [])
        classes = class_by_region.get(key, Counter())
        total_moves = sum(classes.values())
        total_exits = exits.get(key, 0)
        region_rows.append(
            {
                "region": key,
                "label": region_label(key),
                "current": current.get(key, 0),
                "baseline": baselines.get(key, 0),
                "entered": entries.get(key, 0),
                "returned": returns.get(key, 0),
                "left": total_exits,
                "graduated": graduation_source.get(key, 0),
                "gone": gone_source.get(key, 0),
                "moves_out": total_moves,
                "transition_counts": dict(classes),
                "transition_pct": {
                    name: round(classes.get(name, 0) / total_moves * 100, 2) if total_moves else None
                    for name in ("improved", "mixed", "same", "deteriorated", "unknown")
                },
                "exit_activity": dict(exit_activity.get(key, {})),
                "dwell_samples": len(completed),
                "dwell_censored_samples": censored_by_region.get(key, 0),
                "median_dwell_upper_minutes": round(median(completed), 1) if completed else None,
                "median_dwell_lower_minutes": round(median(lower_bounds), 1) if lower_bounds else None,
                "p90_dwell_upper_minutes": _quantile(completed, 0.9),
                "median_open_minutes": round(median(open_spells[key]), 1) if open_spells.get(key) else None,
                "dwell_histogram": dict(dwell_hist.get(key, {})),
            }
        )

    transition_rows = []
    for (source, target), count in transitions.most_common():
        samples = transition_dwell.get((source, target), [])
        total_out = exits.get(source, 0)
        transition_rows.append(
            {
                "from_region": source,
                "to_region": target,
                "count": count,
                "share_of_source_pct": round(count / total_out * 100, 2) if total_out else None,
                "transition": "left_population" if target == "left_population" else compare_regions(source, target),
                "median_dwell_upper_minutes": round(median(samples), 1) if samples else None,
            }
        )

    timeline_regions = [row["region"] for row in region_rows[:24]]
    timeline = {
        "timestamps": [row["timestamp"] for row in population_runs],
        "tracked": [int(row.get("tracked", 0)) for row in population_runs],
        "regions": timeline_regions,
        "series": {
            region: [int(row.get("regions", {}).get(region, 0)) for row in population_runs]
            for region in timeline_regions
        },
        "activity": {
            key: [int(row.get("activity", {}).get(key, 0)) for row in population_runs]
            for key in sorted({key for row in population_runs for key in row.get("activity", {})})
        },
        "moved": [int(row.get("moved", 0)) for row in population_runs],
        "gone": [int(row.get("gone", 0)) for row in population_runs],
    }

    uncensored = [value for values in dwell_by_region.values() for value in values]
    censored_total = sum(censored_by_region.values())
    coverage_summary = _coverage_summary(population_runs, now)

    totals_by_class: Counter[str] = Counter()
    for classes in class_by_region.values():
        totals_by_class.update(classes)
    moves_total = sum(
        count for (source, target), count in transitions.items() if target != "left_population"
    )

    return {
        "schema_version": 2,
        "semantic_schema_hash": SEMANTIC_SCHEMA_HASH,
        "generated_at": now.isoformat(),
        "window_hours": window_hours,
        "coverage": {
            "monitor_runs": len(population_runs),
            **coverage_summary,
            "events_in_window": len(events),
            "legacy_events_ignored": legacy_rows,
            "semantic_events_ignored": semantic_rows,
            "moves_in_window": moves_total,
            "censored_moves_in_window": censored_moves,
            "mints_with_incident_moves": len(moving_mints),
            "known_mints": len(state.get("mints", {})),
            "sufficient_for_transitions": (
                (moves_total - censored_moves) >= REGION_FLOW_MIN_MOVES
                and len(moving_mints) >= REGION_FLOW_MIN_MOVING_MINTS
                and (coverage_summary.get("latest_continuous_minutes") or 0) >= 60
            ),
        },
        "totals": {
            "moves": moves_total,
            "baseline": sum(baselines.values()),
            "entries": sum(entries.values()),
            "returns": sum(returns.values()),
            "graduations": sum(graduation_source.values()),
            "gone": sum(gone_source.values()),
            "median_dwell_upper_minutes": round(median(uncensored), 1) if uncensored else None,
            "dwell_samples": len(uncensored),
            "dwell_censored_samples": censored_total,
            "transitions": dict(totals_by_class),
        },
        "dwell_bins": [{"key": key, "label": label} for key, label, *_ in DWELL_BINS],
        "regions": region_rows,
        "transitions": transition_rows,
        "by_launchpad": [
            {"launchpad": launchpad, **dict(counter)}
            for launchpad, counter in sorted(
                launchpad_flow.items(), key=lambda item: -item[1].get("moves", 0)
            )
        ],
        "timeline": timeline,
    }


def write_region_flow(flow: dict[str, Any]) -> None:
    atomic_write_json(REGION_FLOW_PATH, flow)
