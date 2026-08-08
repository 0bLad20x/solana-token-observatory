"""Bounded, self-describing export for external AI review.

The exporter consumes the derived diagnostic artifacts, never the PostgreSQL
database and never the complete per-mint state/event history.  Its output is a
single JSON whose denominators, timestamps and readiness gates travel together
with the metrics an analyst is expected to evaluate.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .constants import (
    AI_ANALYSIS_BUNDLE_PATH,
    COHORT_OUTCOMES_PATH,
    DATA_DIR,
    DECISION_EVENTS_PATH,
    OUTPUT_PATH,
    PHASE_GUIDE_PATH,
    POLICY_OUTCOMES_PATH,
    POLICY_RULES_PATH,
    POLICY_RUNS_PATH,
    POLICY_STATE_PATH,
    REGION_FLOW_PATH,
    REGION_POPULATION_RUNS_PATH,
    REGION_SNAPSHOT_PATH,
    REGION_TRANSITIONS_PATH,
)
from .storage import atomic_write_json


BUNDLE_SCHEMA_VERSION = 1
METHODOLOGY_VERSION = 1
JSONL_TAIL_LIMIT = 12
HASH_LIMIT_BYTES = 2_000_000


def _load_json(path: Path) -> dict | None:
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    return payload if isinstance(payload, dict) else None


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _pct(numerator: float | int, denominator: float | int) -> float | None:
    if not denominator:
        return None
    return round(float(numerator) / float(denominator) * 100.0, 4)


def _sha256(path: Path) -> str | None:
    try:
        if path.stat().st_size > HASH_LIMIT_BYTES:
            return None
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(131_072), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def _jsonl_tail(path: Path, limit: int = JSONL_TAIL_LIMIT) -> list[dict]:
    """Read a bounded JSONL tail without materialising a potentially huge log."""
    rows: deque[dict] = deque(maxlen=limit)
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(value, dict):
                    rows.append(value)
    except OSError:
        return []
    return list(rows)


def _artifact_manifest(
    path: Path,
    payload: dict | None = None,
    *,
    logical_path: str | None = None,
) -> dict:
    item: dict[str, Any] = {
        "path": logical_path or path.name,
        "exists": path.exists(),
        "size_bytes": None,
        "modified_at": None,
        "artifact_generated_at": None,
        "schema_version": None,
        "sha256": None,
    }
    try:
        stat = path.stat()
    except OSError:
        return item
    item["size_bytes"] = stat.st_size
    item["modified_at"] = datetime.fromtimestamp(
        stat.st_mtime, tz=timezone.utc
    ).isoformat()
    if payload:
        item["artifact_generated_at"] = payload.get("generated_at") or payload.get(
            "timestamp"
        )
        item["schema_version"] = payload.get("schema_version")
    item["sha256"] = _sha256(path)
    return item


def _wilson_interval(successes: int, total: int, z: float = 1.959963984540054) -> dict:
    if total <= 0:
        return {"low_pct": None, "high_pct": None}
    p = successes / total
    z2 = z * z
    denominator = 1.0 + z2 / total
    centre = (p + z2 / (2.0 * total)) / denominator
    margin = z * math.sqrt((p * (1.0 - p) + z2 / (4.0 * total)) / total) / denominator
    return {
        "low_pct": round(max(0.0, centre - margin) * 100.0, 4),
        "high_pct": round(min(1.0, centre + margin) * 100.0, 4),
    }


def _cells(snapshot: dict | None) -> tuple[list[str], list[list]]:
    if not snapshot:
        return [], []
    schema = snapshot.get("cells_schema") or []
    rows = snapshot.get("cells") or []
    return list(schema), [row for row in rows if isinstance(row, list)]


def _cell_dicts(snapshot: dict | None) -> list[dict]:
    schema, rows = _cells(snapshot)
    return [dict(zip(schema, row)) for row in rows if len(row) == len(schema)]


def _matrix(rows: list[dict], group_key: str, category_key: str) -> list[dict]:
    grouped: dict[str, Counter] = defaultdict(Counter)
    for row in rows:
        count = int(row.get("count") or 0)
        grouped[str(row.get(group_key, "unknown"))][
            str(row.get(category_key, "unknown"))
        ] += count
    result = []
    for group, counts in sorted(grouped.items(), key=lambda item: (-sum(item[1].values()), item[0])):
        total = sum(counts.values())
        result.append(
            {
                "group": group,
                "n": total,
                "counts": dict(counts),
                "shares_pct": {key: _pct(value, total) for key, value in counts.items()},
            }
        )
    return result


def _state_space(snapshot: dict | None) -> dict:
    if not snapshot:
        return {"available": False}
    tracked = int((snapshot.get("totals") or {}).get("tracked") or 0)
    rows = _cell_dicts(snapshot)
    economic: Counter = Counter()
    for row in rows:
        economic[f"{row.get('mcap_bucket')}~{row.get('liquidity_bucket')}"] += int(
            row.get("count") or 0
        )
    dominant_cells = sorted(rows, key=lambda row: int(row.get("count") or 0), reverse=True)[:50]
    for row in dominant_cells:
        row["population_share_pct"] = _pct(int(row.get("count") or 0), tracked)
    breakdowns = snapshot.get("breakdowns") or {}
    activity = breakdowns.get("activity") or {}
    unknown_activity = int(activity.get("unknown") or 0)
    holders = breakdowns.get("holders") or {}
    low_holders = int(holders.get("0_2") or 0)
    return {
        "available": True,
        "tracked": tracked,
        "coverage": {
            "known_mcap_and_liquidity": (snapshot.get("totals") or {}).get(
                "known_mcap_liquidity"
            ),
            "missing_mcap_or_liquidity": (snapshot.get("totals") or {}).get(
                "missing_mcap_or_liquidity"
            ),
            "known_activity": tracked - unknown_activity,
            "known_activity_pct": _pct(tracked - unknown_activity, tracked),
            "unknown_activity": unknown_activity,
        },
        "holders_0_2": low_holders,
        "holders_0_2_pct": _pct(low_holders, tracked),
        "economic_regions": [
            {"region": key, "count": count, "population_share_pct": _pct(count, tracked)}
            for key, count in economic.most_common()
        ],
        "dominant_cells": dominant_cells,
    }


def _flow_derived(flow: dict | None) -> dict:
    if not flow:
        return {"available": False}
    normalized = []
    for row in flow.get("regions") or []:
        baseline = int(row.get("baseline") or 0)
        moves_out = int(row.get("moves_out") or 0)
        transitions = row.get("transition_counts") or {}
        normalized.append(
            {
                "region": row.get("region"),
                "label": row.get("label"),
                "baseline": baseline,
                "current": row.get("current"),
                "moves_out": moves_out,
                "exit_population_share_pct": _pct(moves_out, baseline),
                "improved_among_exits_pct": _pct(
                    int(transitions.get("improved") or 0), moves_out
                ),
                "improved_population_share_pct": _pct(
                    int(transitions.get("improved") or 0), baseline
                ),
                "deteriorated_population_share_pct": _pct(
                    int(transitions.get("deteriorated") or 0), baseline
                ),
            }
        )
    return {
        "available": True,
        "sufficient_for_transitions": bool(
            (flow.get("coverage") or {}).get("sufficient_for_transitions")
        ),
        "population_normalized_regions": sorted(
            normalized, key=lambda row: -(row.get("baseline") or 0)
        ),
    }


def _cohort_derived(cohorts: dict | None) -> dict:
    if not cohorts:
        return {"available": False}
    rows = []
    for cohort in cohorts.get("cohorts") or []:
        outcomes = cohort.get("outcomes") or []
        rows.append(
            {
                "key": cohort.get("key"),
                "label": cohort.get("label"),
                "baseline_unique_mints": cohort.get("baseline_unique_mints"),
                "incident_unique_mints": cohort.get("unique_mints"),
                "matured_by_horizon": [
                    {
                        "horizon_minutes": row.get("horizon_minutes"),
                        "n": row.get("n"),
                        "outcome_pct": row.get("pct"),
                    }
                    for row in outcomes
                ],
                "has_any_matured_horizon": any(int(row.get("n") or 0) > 0 for row in outcomes),
            }
        )
    return {"available": True, "cohort_readiness": rows}


def _activity_derived(snapshot: dict | None) -> dict:
    if not snapshot:
        return {"available": False}
    tracked = int((snapshot.get("totals") or {}).get("tracked") or 0)
    counts = dict(((snapshot.get("breakdowns") or {}).get("activity") or {}))
    unknown = int(counts.get("unknown") or 0)
    rows = _cell_dicts(snapshot)
    return {
        "available": True,
        "coverage": {
            "tracked": tracked,
            "known": tracked - unknown,
            "unknown": unknown,
            "known_pct": _pct(tracked - unknown, tracked),
        },
        "counts": counts,
        "by_age": _matrix(rows, "age_bucket", "activity_bucket"),
        "by_market_cap": _matrix(rows, "mcap_bucket", "activity_bucket"),
        "by_liquidity": _matrix(rows, "liquidity_bucket", "activity_bucket"),
    }


def _launchpad_derived(snapshot: dict | None, flow: dict | None) -> dict:
    if not snapshot:
        return {"available": False}
    rows = _cell_dicts(snapshot)
    profiles: dict[str, dict] = {}
    for launchpad in sorted({str(row.get("launchpad", "unknown")) for row in rows}):
        selected = [row for row in rows if str(row.get("launchpad", "unknown")) == launchpad]
        total = sum(int(row.get("count") or 0) for row in selected)
        graduation = Counter()
        policy = Counter()
        activity = Counter()
        for row in selected:
            count = int(row.get("count") or 0)
            graduation[str(row.get("graduation"))] += count
            policy[str(row.get("policy_status"))] += count
            activity[str(row.get("activity_bucket"))] += count
        profiles[launchpad] = {
            "n": total,
            "graduation_counts": dict(graduation),
            "graduation_rates_pct": {key: _pct(value, total) for key, value in graduation.items()},
            "policy_counts": dict(policy),
            "policy_rates_pct": {key: _pct(value, total) for key, value in policy.items()},
            "activity_counts": dict(activity),
            "activity_rates_pct": {key: _pct(value, total) for key, value in activity.items()},
        }
    return {
        "available": True,
        "profiles": profiles,
        "flow_by_launchpad": (flow or {}).get("by_launchpad") or [],
    }


def _polling_projection(report: dict | None) -> dict:
    simulation = (report or {}).get("policy_simulation") or {}
    allocation = simulation.get("instantaneous_match_allocation") or {}
    cadences = simulation.get("priority_cadences_seconds") or {}
    total = sum(int(value or 0) for value in allocation.values())
    p1_seconds = float(cadences.get("p1") or 60)
    current = total / p1_seconds if p1_seconds > 0 else None
    proposed = 0.0
    for action in ("p1", "p2", "p3"):
        cadence = float(cadences.get(action) or 0)
        if cadence > 0:
            proposed += int(allocation.get(action) or 0) / cadence
    return {
        "population": total,
        "basis": "instantaneous_strongest_action_per_mint",
        "current_all_p1_poll_equivalent_per_second": round(current, 6) if current is not None else None,
        "proposed_poll_equivalent_per_second": round(proposed, 6),
        "load_reduction_pct": round((1.0 - proposed / current) * 100.0, 4)
        if current
        else None,
    }


def _filter_derived(report: dict | None) -> dict:
    if not report:
        return {"available": False}
    evidence = report.get("filter_evidence") or {}
    simulation = report.get("policy_simulation") or {}
    stateful = evidence.get("allocation") or {}
    instantaneous = simulation.get("instantaneous_match_allocation") or {}
    actions = sorted(set(stateful) | set(instantaneous))
    return {
        "available": True,
        "mode": evidence.get("mode"),
        "shadow_only": simulation.get("mode") == "shadow_only_no_database_mutation",
        "rule_set_hash": simulation.get("rule_set_hash"),
        "allocation_comparison": {
            "stateful_or_reported": stateful,
            "instantaneous": instantaneous,
            "instantaneous_minus_stateful": {
                action: int(instantaneous.get(action) or 0) - int(stateful.get(action) or 0)
                for action in actions
            },
        },
        "polling_load_projection": _polling_projection(report),
        "rules": evidence.get("rules") or simulation.get("rules") or [],
    }


def _policy_lab(report: dict | None, outcomes: dict | None) -> dict:
    simulation = (report or {}).get("policy_simulation") or {}
    active_rules = simulation.get("rules") or []
    active_keys = {row.get("rule_key") for row in active_rules if row.get("rule_key")}
    outcome_rows = (outcomes or {}).get("rules") or []
    selected = [row for row in outcome_rows if row.get("rule_key") in active_keys]
    enriched = []
    readiness = []
    filter_rules = {
        row.get("rule_key"): row
        for row in ((report or {}).get("filter_evidence") or {}).get("rules", [])
    }
    by_key = {row.get("rule_key"): row for row in selected}
    for active in active_rules:
        key = active.get("rule_key")
        outcome = by_key.get(key)
        applied = int(
            (filter_rules.get(key) or {}).get("applied_count")
            or (outcome or {}).get("applied_unique_mints")
            or 0
        )
        horizons = []
        for horizon in (outcome or {}).get("horizons", []):
            item = dict(horizon)
            item["recovery_rate_wilson_95_pct"] = _wilson_interval(
                int(horizon.get("recovered") or 0), int(horizon.get("matured") or 0)
            )
            horizons.append(item)
        if outcome:
            item = dict(outcome)
            item["horizons"] = horizons
            enriched.append(item)
        matured_total = sum(int(row.get("matured") or 0) for row in horizons)
        if not outcome or applied == 0:
            status = "not_applied_or_no_outcome_row"
        elif matured_total == 0:
            status = "awaiting_matured_horizon"
        else:
            status = "evidence_available"
        readiness.append(
            {
                "rule_key": key,
                "rule_id": active.get("rule_id"),
                "current_matches": active.get("current_match_count"),
                "applied": applied,
                "matured_observations_across_horizons": matured_total,
                "status": status,
            }
        )
    return {
        "available": bool(outcomes),
        "active_rule_set_hash": simulation.get("rule_set_hash"),
        "active_rule_outcomes": enriched,
        "rule_readiness": readiness,
        "excluded_legacy_rule_versions": len(outcome_rows) - len(selected),
        "historical_global_totals_not_valid_for_active_rule_set": (outcomes or {}).get("global"),
    }


def _quality_gates(
    report: dict | None,
    snapshot: dict | None,
    flow: dict | None,
    cohorts: dict | None,
    policy_lab: dict,
) -> dict:
    health = (report or {}).get("collector_health") or (snapshot or {}).get("collector_health") or {}
    validation = (report or {}).get("technical_validation") or {}
    validation_status = validation.get("status") if isinstance(validation, dict) else validation
    activity = _activity_derived(snapshot)
    active_evidence = any(
        row.get("status") == "evidence_available" for row in policy_lab.get("rule_readiness", [])
    )
    return {
        "collector_snapshot": {
            "status": "ready" if health.get("healthy") and validation_status == "ok" else "blocked",
            "collector_health": health.get("status"),
            "technical_validation": validation_status,
        },
        "phase_1_population": {"status": "ready" if snapshot else "missing"},
        "phase_2_transitions": {
            "status": "ready"
            if (flow or {}).get("coverage", {}).get("sufficient_for_transitions")
            else "insufficient_history"
        },
        "phase_3_cohorts": {
            "status": "ready"
            if (cohorts or {}).get("coverage", {}).get("has_matured_outcomes")
            else "insufficient_matured_outcomes"
        },
        "phase_4_activity": {
            "status": "partial" if activity.get("available") else "missing",
            "known_coverage_pct": (activity.get("coverage") or {}).get("known_pct"),
        },
        "phase_5_launchpads": {"status": "descriptive" if snapshot else "missing"},
        "phase_6_filters": {"status": "ready" if report else "missing"},
        "phase_7_active_policy_outcomes": {
            "status": "ready" if active_evidence else "awaiting_maturity"
        },
    }


def _warnings(
    report: dict | None,
    snapshot: dict | None,
    flow: dict | None,
    cohorts: dict | None,
    policy_lab: dict,
    manifests: dict,
) -> list[dict]:
    warnings: list[dict] = []
    for name, item in manifests.items():
        if name in {"methodology", "policy_state", "decision_events", "region_transitions"}:
            continue
        if not item.get("exists"):
            warnings.append({"code": "missing_artifact", "severity": "warning", "artifact": name})
    health = (report or {}).get("collector_health") or {}
    if report and not health.get("healthy"):
        warnings.append({"code": "collector_unhealthy", "severity": "blocker"})
    validation = (report or {}).get("technical_validation") or {}
    if report and isinstance(validation, dict) and validation.get("status") != "ok":
        warnings.append({"code": "technical_validation_failed", "severity": "blocker"})
    if flow and not (flow.get("coverage") or {}).get("sufficient_for_transitions"):
        warnings.append(
            {
                "code": "transition_history_insufficient",
                "severity": "warning",
                "coverage": flow.get("coverage"),
            }
        )
    activity = _activity_derived(snapshot)
    known_pct = (activity.get("coverage") or {}).get("known_pct")
    if known_pct is not None and known_pct < 80:
        warnings.append(
            {
                "code": "activity_coverage_low",
                "severity": "warning",
                "known_coverage_pct": known_pct,
                "rule": "unknown_must_not_be_treated_as_zero",
            }
        )
    if cohorts and not (cohorts.get("coverage") or {}).get("has_matured_outcomes"):
        warnings.append({"code": "cohort_outcomes_not_mature", "severity": "warning"})
    if policy_lab.get("available") and not any(
        row.get("status") == "evidence_available" for row in policy_lab.get("rule_readiness", [])
    ):
        warnings.append({"code": "active_rule_outcomes_not_mature", "severity": "warning"})
    legacy = int(policy_lab.get("excluded_legacy_rule_versions") or 0)
    if legacy:
        warnings.append(
            {
                "code": "legacy_policy_outcomes_excluded",
                "severity": "info",
                "excluded_rule_versions": legacy,
            }
        )
    report_n = int(
        ((report or {}).get("population_distribution") or {}).get(
            "total_active_with_snapshot"
        )
        or ((report or {}).get("policy_simulation") or {}).get("coverage", {}).get(
            "features"
        )
        or 0
    )
    snapshot_n = int(((snapshot or {}).get("totals") or {}).get("tracked") or 0)
    if report_n and snapshot_n and report_n != snapshot_n:
        warnings.append(
            {
                "code": "population_timestamp_mismatch",
                "severity": "warning",
                "report_tracked": report_n,
                "snapshot_tracked": snapshot_n,
            }
        )
    return warnings


def _phase_contract(number: int, key: str, question: str, denominator: str) -> dict:
    anchors = {
        1: "phase-1--state-space",
        2: "phase-2--region-flow",
        3: "phase-3--incident-cohorts",
        4: "phase-4--activity",
        5: "phase-5--launchpads",
        6: "phase-6--filter-evidence",
        7: "phase-7--policy-lab",
    }
    return {
        "number": number,
        "key": key,
        "question": question,
        "primary_denominator": denominator,
        "methodology": f"docs/DIAGNOSTIC_PHASES.md#{anchors[number]}",
    }


def build_ai_analysis_bundle(
    *,
    data_dir: Path = DATA_DIR,
    exported_at: datetime | None = None,
) -> dict:
    """Build one AI-ready payload from current derived artifacts.

    ``data_dir`` is injectable for tests and offline review.  The function does
    not open a database connection.
    """
    now = (exported_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    paths = {
        "investigation_report": data_dir / OUTPUT_PATH.name,
        "region_snapshot": data_dir / REGION_SNAPSHOT_PATH.name,
        "region_flow": data_dir / REGION_FLOW_PATH.name,
        "cohort_outcomes": data_dir / COHORT_OUTCOMES_PATH.name,
        "policy_outcomes": data_dir / POLICY_OUTCOMES_PATH.name,
        "policy_rules": data_dir / POLICY_RULES_PATH.name,
        "policy_runs": data_dir / POLICY_RUNS_PATH.name,
        "region_population_runs": data_dir / REGION_POPULATION_RUNS_PATH.name,
        "policy_state": data_dir / POLICY_STATE_PATH.name,
        "decision_events": data_dir / DECISION_EVENTS_PATH.name,
        "region_transitions": data_dir / REGION_TRANSITIONS_PATH.name,
        "methodology": PHASE_GUIDE_PATH,
    }
    report = _load_json(paths["investigation_report"])
    snapshot = _load_json(paths["region_snapshot"])
    flow = _load_json(paths["region_flow"])
    cohorts = _load_json(paths["cohort_outcomes"])
    policy_outcomes = _load_json(paths["policy_outcomes"])
    policy_rules = _load_json(paths["policy_rules"])
    payloads = {
        "investigation_report": report,
        "region_snapshot": snapshot,
        "region_flow": flow,
        "cohort_outcomes": cohorts,
        "policy_outcomes": policy_outcomes,
        "policy_rules": policy_rules,
    }
    logical_paths = {
        "investigation_report": f"data/{OUTPUT_PATH.name}",
        "region_snapshot": f"data/{REGION_SNAPSHOT_PATH.name}",
        "region_flow": f"data/{REGION_FLOW_PATH.name}",
        "cohort_outcomes": f"data/{COHORT_OUTCOMES_PATH.name}",
        "policy_outcomes": f"data/{POLICY_OUTCOMES_PATH.name}",
        "policy_rules": f"data/{POLICY_RULES_PATH.name}",
        "policy_runs": f"data/{POLICY_RUNS_PATH.name}",
        "region_population_runs": f"data/{REGION_POPULATION_RUNS_PATH.name}",
        "policy_state": f"data/{POLICY_STATE_PATH.name}",
        "decision_events": f"data/{DECISION_EVENTS_PATH.name}",
        "region_transitions": f"data/{REGION_TRANSITIONS_PATH.name}",
        "methodology": "docs/DIAGNOSTIC_PHASES.md",
    }
    manifests = {
        name: _artifact_manifest(
            path,
            payloads.get(name),
            logical_path=logical_paths[name],
        )
        for name, path in paths.items()
    }
    policy_lab = _policy_lab(report, policy_outcomes)
    state_space = _state_space(snapshot)
    filter_derived = _filter_derived(report)
    quality_gates = _quality_gates(report, snapshot, flow, cohorts, policy_lab)
    warnings = _warnings(report, snapshot, flow, cohorts, policy_lab, manifests)

    artifact_times = [
        _parse_time(item.get("artifact_generated_at"))
        for item in manifests.values()
        if item.get("artifact_generated_at")
    ]
    artifact_times = [item for item in artifact_times if item is not None]
    time_span_seconds = (
        round((max(artifact_times) - min(artifact_times)).total_seconds(), 3)
        if artifact_times
        else None
    )
    instantaneous = (
        ((report or {}).get("policy_simulation") or {}).get("instantaneous_match_allocation")
        or {}
    )
    tracked = int(state_space.get("tracked") or 0)

    return {
        "schema_version": BUNDLE_SCHEMA_VERSION,
        "methodology_version": METHODOLOGY_VERSION,
        "exported_at": now.isoformat(),
        "purpose": "bounded_ai_review_of_jupiter_token_diagnostics",
        "safety": {
            "mode": "analysis_and_shadow_policy_only",
            "database_mutation": False,
            "creates_lifecycle_table": False,
            "contains_full_per_mint_histories": False,
        },
        "methodology_document": "docs/DIAGNOSTIC_PHASES.md",
        "interpretation_contract": {
            "missing_is_zero": False,
            "unknown_is_inactive": False,
            "matching_is_applied": False,
            "applied_is_validated": False,
            "recovery_denominator": "unique candidates with a matured continuously observed horizon",
            "transition_exit_denominator": "moves_out from the source region",
            "population_transition_denominator": "baseline population of the source region",
            "active_policy_identity": "exact rule_key including id, version and config hash",
        },
        "source_manifest": manifests,
        "temporal_coherence": {
            "artifact_generated_time_span_seconds": time_span_seconds,
            "latest_artifact_generated_at": max(artifact_times).isoformat()
            if artifact_times
            else None,
            "oldest_artifact_generated_at": min(artifact_times).isoformat()
            if artifact_times
            else None,
            "latest_policy_runs": _jsonl_tail(paths["policy_runs"]),
            "latest_region_population_runs": _jsonl_tail(
                paths["region_population_runs"]
            ),
        },
        "quality_gates": quality_gates,
        "warnings": warnings,
        "executive_facts": {
            "tracked_tokens": tracked,
            "collector_health": ((report or {}).get("collector_health") or {}).get("status"),
            "technical_validation": ((report or {}).get("technical_validation") or {}).get("status"),
            "active_rule_set_hash": ((report or {}).get("policy_simulation") or {}).get("rule_set_hash"),
            "instantaneous_strongest_action_allocation": instantaneous,
            "instantaneous_retire_unique": int(instantaneous.get("retire") or 0),
            "instantaneous_retire_pct": _pct(int(instantaneous.get("retire") or 0), tracked),
            "polling_load_projection": filter_derived.get("polling_load_projection"),
            "largest_economic_region": (state_space.get("economic_regions") or [None])[0],
            "active_rules_with_matured_outcomes": sum(
                1
                for row in policy_lab.get("rule_readiness", [])
                if row.get("status") == "evidence_available"
            ),
        },
        "phases": {
            "phase_1_state_space": {
                "contract": _phase_contract(
                    1,
                    "state_space",
                    "Where is the current population concentrated?",
                    "all tracked tokens in the healthy snapshot",
                ),
                "readiness": quality_gates["phase_1_population"],
                "derived": state_space,
                "source_data": snapshot,
            },
            "phase_2_region_flow": {
                "contract": _phase_contract(
                    2,
                    "region_flow",
                    "Where do tokens move and how long do states persist?",
                    "moves_out for exit direction; baseline for population probability",
                ),
                "readiness": quality_gates["phase_2_transitions"],
                "derived": _flow_derived(flow),
                "source_data": flow,
            },
            "phase_3_incident_cohorts": {
                "contract": _phase_contract(
                    3,
                    "incident_cohorts",
                    "What follows the first observed entry into a state?",
                    "unique incident mints with a matured continuous horizon",
                ),
                "readiness": quality_gates["phase_3_cohorts"],
                "derived": _cohort_derived(cohorts),
                "source_data": cohorts,
            },
            "phase_4_activity": {
                "contract": _phase_contract(
                    4,
                    "activity",
                    "Is economic activity known, active, decaying or dormant?",
                    "tokens with known activity for activity rates",
                ),
                "readiness": quality_gates["phase_4_activity"],
                "derived": _activity_derived(snapshot),
                "source_data": {
                    "stats1h_validation": ((report or {}).get("cross_analysis") or {}).get(
                        "stats1h_activity_vs_unchanged_validation"
                    )
                },
            },
            "phase_5_launchpads": {
                "contract": _phase_contract(
                    5,
                    "launchpads",
                    "Does origin change distributions or outcomes?",
                    "tokens within each launchpad",
                ),
                "readiness": quality_gates["phase_5_launchpads"],
                "derived": _launchpad_derived(snapshot, flow),
            },
            "phase_6_filter_evidence": {
                "contract": _phase_contract(
                    6,
                    "filter_evidence",
                    "Which tokens match, mature into actions and reduce polling load?",
                    "unique tokens after strongest-action precedence",
                ),
                "readiness": quality_gates["phase_6_filters"],
                "derived": filter_derived,
                "source_data": {
                    "policy_simulation": (report or {}).get("policy_simulation"),
                    "filter_evidence": (report or {}).get("filter_evidence"),
                    "policy_rules": policy_rules,
                },
            },
            "phase_7_policy_lab": {
                "contract": _phase_contract(
                    7,
                    "policy_lab",
                    "Did an exact applied rule later miss a relevant recovery?",
                    "unique applied candidates with a matured continuous horizon",
                ),
                "readiness": quality_gates["phase_7_active_policy_outcomes"],
                **policy_lab,
            },
        },
        "supporting_diagnostics": {
            "context": (report or {}).get("context"),
            "collector_health": (report or {}).get("collector_health"),
            "technical_validation": (report or {}).get("technical_validation"),
            "decision_metrics": (report or {}).get("decision_metrics"),
            "population_distribution": (report or {}).get("population_distribution"),
            "categories": (report or {}).get("categories"),
            "cross_analysis": (report or {}).get("cross_analysis"),
            "performance": (report or {}).get("performance"),
            "monitor": (report or {}).get("monitor"),
        },
        "questions_for_ai": [
            "Which active rules are decision-ready, and which are only hypotheses?",
            "What is the unique retire/demote potential after strongest-action precedence?",
            "What is the Wilson 95% upper recovery bound per active rule and horizon?",
            "Which conclusions are blocked by gaps, missingness or small denominators?",
            "Which large population is not covered by an active rule?",
            "Which threshold should be tightened or relaxed, and what evidence supports it?",
            "What single additional measurement or rule would reduce the largest blind spot?",
        ],
        "required_ai_response_structure": [
            "facts",
            "decision_grade_conclusions",
            "blocked_or_immature_questions",
            "rule_changes_with_evidence",
            "next_measurement_or_test",
        ],
    }


def write_ai_analysis_bundle(
    *,
    data_dir: Path = DATA_DIR,
    output_path: Path = AI_ANALYSIS_BUNDLE_PATH,
) -> dict:
    bundle = build_ai_analysis_bundle(data_dir=data_dir)
    atomic_write_json(output_path, bundle)
    return bundle