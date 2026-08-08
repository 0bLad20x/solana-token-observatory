from __future__ import annotations

from datetime import datetime, timezone

from config import Settings

from .analysis import compact_population_run_summary
from .cohorts import build_cohort_outcomes, write_cohort_outcomes
from .constants import (
    COHORT_OUTCOMES_PATH,
    DECISION_EVENTS_PATH,
    OUTPUT_PATH,
    POLICY_RULES_PATH,
    POLICY_RUNS_PATH,
    POLICY_STATE_PATH,
    POLICY_OUTCOMES_PATH,
    POPULATION_DISTRIBUTION_SVG_PATH,
    REGION_DEGRADED_SNAPSHOT_PATH,
    REGION_FLOW_PATH,
    REGION_SNAPSHOT_PATH,
    REGION_STATE_PATH,
    REGION_TRANSITIONS_PATH,
)
from .policy_outcomes import build_policy_outcomes, write_policy_outcomes
from .policy import (
    advance_policy_state,
    annotate_policy_status,
    current_policy_population_overlay,
    load_policy_config,
    prospective_monitor_metrics,
    update_monitor_token_metrics,
)
from .region_history import (
    build_region_flow,
    update_region_history,
    write_region_flow,
)
from .reporting import build_report, write_report
from .regions import build_region_snapshot, write_region_snapshot
from .storage import append_jsonl, atomic_write_json

def run_monitor_cycle(
    settings: Settings,
    state: dict,
    interval_seconds: int,
) -> dict:
    # Rules werden absichtlich pro Lauf neu geladen, damit Schwellenwerte ohne
    # Monitor-Neustart experimentell angepasst werden koennen.
    config = load_policy_config()
    output, features = build_report(settings, config)

    now = datetime.now(timezone.utc)
    run_id = now.strftime("%Y%m%dT%H%M%S.%fZ")
    health_ok = bool(output["collector_health"]["healthy"])
    validation_ok = output["technical_validation"]["status"] == "ok"

    events: list[dict] = []
    summaries: list[dict] = []
    continuity = False
    region_summary: dict = {"skipped": True, "reason": "unhealthy_run"}

    if health_ok and validation_ok:
        continuity = update_monitor_token_metrics(
            state,
            features,
            now,
            interval_seconds,
        )
        events, summaries = advance_policy_state(
            state,
            config,
            features,
            now,
            interval_seconds,
            continuity,
        )
        for event in events:
            event["run_id"] = run_id

        output["decision_metrics"]["prospective_monitor"] = (
            prospective_monitor_metrics(features)
        )
        annotate_policy_status(state, config, features)

        # Events enthalten bereits run_id; der State wird atomar geschrieben.
        append_jsonl(DECISION_EVENTS_PATH, events)
        atomic_write_json(POLICY_STATE_PATH, state)

        # Longitudinale Artefakte nur bei gesundem Lauf: eine unvollstaendige
        # Population ist im Append-only-Log nicht mehr von echtem Verschwinden
        # zu unterscheiden.
        region_summary = update_region_history(
            features,
            now,
            run_id,
            interval_seconds,
            healthy=True,
            continuity=continuity,
            infer_gone=continuity,
        )
        write_region_flow(build_region_flow(now=now))
        write_cohort_outcomes(build_cohort_outcomes(now=now))
    else:
        summaries = [
            {
                "rule_key": row["rule_key"],
                "rule_id": row["rule_id"],
                "version": row["version"],
                "current_match_count": row["current_match_count"],
                "probation_count": None,
                "would_retire_count": None,
            }
            for row in output["policy_simulation"]["rules"]
        ]

    output["population_distribution"]["policy_overlay"] = (
        current_policy_population_overlay(
            state,
            features,
            config,
            output["population_distribution"],
        )
    )

    # Der letzte gesunde Snapshot bleibt kanonisch. Ein degradierter Lauf wird
    # separat abgelegt, damit das Dashboard weder partielle Daten als Gegenwart
    # noch einen alten Healthy-Snapshot kommentarlos als frisch ausgibt.
    snapshot = build_region_snapshot(
        features,
        output["generated_at"],
        collector_health=output.get("collector_health"),
        technical_validation=output.get("technical_validation", {}).get("status"),
        expected_interval_seconds=interval_seconds,
    )
    write_region_snapshot(snapshot, healthy=health_ok and validation_ok)

    event_counts: dict[str, int] = {}
    for event in events:
        name = event["event"]
        event_counts[name] = event_counts.get(name, 0) + 1

    run_record = {
        "schema_version": 1,
        "run_id": run_id,
        "timestamp": now.isoformat(),
        "interval_seconds": interval_seconds,
        "collector_health": output["collector_health"],
        "technical_validation": output["technical_validation"]["status"],
        "policy_state_advanced": health_ok and validation_ok,
        "monitor_continuity": continuity,
        "tracked_mints": output["context"]["total_tracked_mints"],
        "population": compact_population_run_summary(output["population_distribution"]),
        "regions": region_summary,
        "rule_set_hash": output["policy_simulation"]["rule_set_hash"],
        "rules": summaries,
        "event_counts": event_counts,
        "performance_ms": output["performance"]["total_ms"],
    }
    append_jsonl(POLICY_RUNS_PATH, [run_record])
    if health_ok and validation_ok:
        write_policy_outcomes(
            build_policy_outcomes(
                now=now,
                horizons=config.get("outcome_horizons_minutes"),
            )
        )

    output["monitor"] = {
        "mode": "monitor",
        "run_id": run_id,
        "interval_seconds": interval_seconds,
        "state_advanced": health_ok and validation_ok,
        "continuity": continuity,
        "event_counts": event_counts,
        "regions": region_summary,
        "rule_states": summaries,
        "artifacts": {
            "latest_report": str(OUTPUT_PATH),
            "policy_rules": str(POLICY_RULES_PATH),
            "policy_runs": str(POLICY_RUNS_PATH),
            "decision_events": str(DECISION_EVENTS_PATH),
            "policy_state": str(POLICY_STATE_PATH),
            "population_distribution_svg": str(POPULATION_DISTRIBUTION_SVG_PATH),
            "region_snapshot": str(REGION_SNAPSHOT_PATH),
            "region_snapshot_degraded": str(REGION_DEGRADED_SNAPSHOT_PATH),
            "region_state": str(REGION_STATE_PATH),
            "region_transitions": str(REGION_TRANSITIONS_PATH),
            "region_flow": str(REGION_FLOW_PATH),
            "cohort_outcomes": str(COHORT_OUTCOMES_PATH),
            "policy_outcomes": str(POLICY_OUTCOMES_PATH),
        },
    }

    # Erst jetzt schreiben: investigation_report.json enthaelt damit auch
    # collector_health, decision_metrics, policy_simulation und monitor.
    write_report(output)
    return output


def print_monitor_summary(output: dict) -> None:
    monitor = output["monitor"]
    health = output["collector_health"]["status"].upper()
    print(
        f"[{output['generated_at']}] "
        f"tracked={output['context']['total_tracked_mints']} "
        f"health={health} "
        f"validation={output['technical_validation']['status']} "
        f"runtime={output['performance']['total_ms'] / 1000:.2f}s "
        f"state_advanced={monitor['state_advanced']} "
        f"continuity={monitor['continuity']}"
    )
    for row in monitor["rule_states"]:
        print(
            f"  {row['rule_id']:<45} "
            f"matches={row['current_match_count']:>5} "
            f"probation={str(row['probation_count']):>5} "
            f"would_retire={str(row['would_retire_count']):>5}"
        )
    regions = monitor.get("regions") or {}
    if regions.get("skipped"):
        print(f"  regions: uebersprungen ({regions.get('reason')})")
    elif regions:
        print(
            f"  regions: moved={regions.get('moved', 0)} "
            f"improved={regions.get('improved', 0)} "
            f"mixed={regions.get('mixed', 0)} "
            f"deteriorated={regions.get('deteriorated', 0)} "
            f"gone={regions.get('gone', 0)}"
        )
    if monitor["event_counts"]:
        print(
            "  events: "
            + ", ".join(
                f"{key}={value}"
                for key, value in sorted(monitor["event_counts"].items())
            )
        )
    else:
        print("  events: none")
