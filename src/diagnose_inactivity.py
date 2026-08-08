from __future__ import annotations

import argparse
import time
from datetime import datetime, timezone

from config import Settings

from diagnostics.ai_export import write_ai_analysis_bundle
from diagnostics.cohorts import build_cohort_outcomes, write_cohort_outcomes
from diagnostics.constants import (
    AI_ANALYSIS_BUNDLE_PATH,
    DEFAULT_MONITOR_INTERVAL_SECONDS,
    POLICY_RULES_PATH,
    PROJECT_ROOT,
)
from diagnostics.region_history import (
    build_region_flow,
    update_region_history,
    write_region_flow,
)
from diagnostics.monitor import print_monitor_summary, run_monitor_cycle
from diagnostics.policy import load_monitor_state, load_policy_config
from diagnostics.reporting import build_report, print_full_report, write_report
from diagnostics.regions import build_region_snapshot, write_region_snapshot

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Jupiter token diagnosis and longitudinal policy simulator"
    )
    parser.add_argument(
        "--ai-export-only",
        action="store_true",
        help=(
            "vorhandene Diagnose-Artefakte ohne Datenbankzugriff in eine "
            "einzige KI-lesbare JSON exportieren"
        ),
    )
    parser.add_argument(
        "--monitor",
        action="store_true",
        help=(
            "run continuously and evaluate policy candidates without "
            "changing tracking_enabled"
        ),
    )
    parser.add_argument(
        "--interval-seconds",
        type=int,
        default=DEFAULT_MONITOR_INTERVAL_SECONDS,
        help="monitor cadence in seconds (default: 60)",
    )
    parser.add_argument(
        "--update-history",
        action="store_true",
        help=(
            "in einem One-Shot-Lauf zusaetzlich die Region-History fortschreiben; "
            "standardmaessig aus, weil unregelmaessige Laeufe Dwell-Zeiten und "
            "GONE-Events verfaelschen"
        ),
    )
    parser.add_argument(
        "--max-runs",
        type=int,
        default=0,
        help="stop monitor after N runs; 0 means unlimited",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.interval_seconds <= 0:
        raise SystemExit("--interval-seconds muss > 0 sein")
    if args.max_runs < 0:
        raise SystemExit("--max-runs muss >= 0 sein")

    if args.ai_export_only:
        if args.monitor or args.update_history:
            raise SystemExit(
                "--ai-export-only kann nicht mit --monitor oder --update-history kombiniert werden"
            )
        bundle = write_ai_analysis_bundle()
        print(f"KI-Analyseexport geschrieben: {AI_ANALYSIS_BUNDLE_PATH}")
        print(
            f"Phasen: {len(bundle['phases'])} | "
            f"Warnungen: {len(bundle['warnings'])} | "
            f"Tracked: {bundle['executive_facts']['tracked_tokens']}"
        )
        return

    settings = Settings.from_env()

    if not args.monitor:
        config = load_policy_config()
        output, features = build_report(settings, config)
        healthy = bool(output["collector_health"]["healthy"]) and output["technical_validation"]["status"] == "ok"
        write_region_snapshot(
            build_region_snapshot(
                features,
                output["generated_at"],
                collector_health=output.get("collector_health"),
                technical_validation=output.get("technical_validation", {}).get("status"),
                expected_interval_seconds=args.interval_seconds,
            ),
            healthy=healthy,
        )

        # Die Region-History wird bewusst NICHT automatisch fortgeschrieben:
        # zwischen zwei manuellen Laeufen liegen beliebige Luecken, und daraus
        # entstehen falsche GONE-Events und unbrauchbare Verweildauern.
        if args.update_history:
            now = datetime.now(timezone.utc)
            update_region_history(
                features,
                now,
                now.strftime("%Y%m%dT%H%M%S.%fZ"),
                args.interval_seconds,
                healthy=healthy,
                continuity=False,
                infer_gone=False,
            )
            write_region_flow(build_region_flow(now=now))
            write_cohort_outcomes(build_cohort_outcomes(now=now))
            print(
                "Hinweis: Region-History aus einem One-Shot fortgeschrieben. "
                "Neue/veraenderte Spells sind censored; GONE wird aus einem manuellen Lauf nie abgeleitet."
            )

        write_report(output)
        write_ai_analysis_bundle()
        print_full_report(output)
        print(f"KI-Analyseexport: {AI_ANALYSIS_BUNDLE_PATH}")
        return

    state = load_monitor_state()
    run_count = 0

    print(
        f"Monitor gestartet: cadence={args.interval_seconds}s, "
        f"rules={POLICY_RULES_PATH}"
    )
    print(f"Projektroot: {PROJECT_ROOT}")

    try:
        while True:
            cycle_started = time.monotonic()

            output = run_monitor_cycle(
                settings,
                state,
                args.interval_seconds,
            )
            print_monitor_summary(output)

            run_count += 1
            if args.max_runs and run_count >= args.max_runs:
                break

            elapsed = time.monotonic() - cycle_started
            sleep_seconds = max(0.0, args.interval_seconds - elapsed)
            time.sleep(sleep_seconds)
    except KeyboardInterrupt:
        print("\nMonitor beendet (Ctrl+C).")


if __name__ == "__main__":
    main()
