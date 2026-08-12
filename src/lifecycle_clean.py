from __future__ import annotations

import argparse
import time
from datetime import datetime, timezone
from typing import Any

from config import Settings
from database import Database
from lifecycle_queries import LifecycleQueries
from lifecycle_rules import (
    COLLAPSE_GRACE_MINUTES,
    COLLAPSE_RULES,
    OBSERVATION_MINUTES,
    RULE2_CHECKPOINT_GRACE_SECONDS,
    RULE2_CHECKPOINT_MINUTES,
    RULE3_CHECKPOINT_GRACE_SECONDS,
    RULE3_CHECKPOINT_MINUTES,
    classify_rule1,
    classify_rule2,
    classify_rule3,
)
from repository import MintRepository
from telemetry import TelemetryEmitter


RULE1_MAX_POLL_LAG_SECONDS = 60.0
INTERVAL_SECONDS = 15.0

RULE_KEYS = ("rule1", "rule2", "rule3", "rule4", "rule5")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Lifecycle hard-retire engine. Rule 1-5 disable dead tokens "
            "by setting tracking_enabled=false."
        ),
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually set tracking_enabled=false. Without this flag: dry-run.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run one cycle and exit instead of looping.",
    )
    return parser.parse_args()


def _act(
    repository: MintRepository,
    candidates: list[dict[str, Any]],
    apply: bool,
) -> list[dict[str, Any]]:
    if not apply:
        return candidates

    retired = repository.disable_mints(candidates)
    return [
        candidate
        for candidate in candidates
        if candidate["mint"] in retired
    ]


def run_cycle(
    repository: MintRepository,
    queries: LifecycleQueries,
    apply: bool,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    already_flagged: set[str] = set()
    acted: dict[str, list[dict[str, Any]]] = {
        key: [] for key in RULE_KEYS
    }

    # Rule 1 — current state after T+10.
    # This is the only rule that needs current collector freshness.
    candidates = []
    for row in queries.fetch_mature_active_state(
        OBSERVATION_MINUTES * 60
    ):
        last_polled_at = row["last_polled_at"]
        if last_polled_at is None:
            continue
        if (
            now - last_polled_at
        ).total_seconds() > RULE1_MAX_POLL_LAG_SECONDS:
            continue

        reason = classify_rule1(row["payload"])
        if reason is not None:
            candidates.append({**row, "reason": reason})

    acted["rule1"] = _act(repository, candidates, apply)
    already_flagged.update(row["mint"] for row in acted["rule1"])

    # Rule 2 — T+10 -> T+30 evidence, evaluated in T+30 + grace.
    # A successful poll at/after T+30 is the complete checkpoint requirement.
    candidates = []
    for row in queries.fetch_continuation_checkpoint(
        checkpoint_minutes=RULE2_CHECKPOINT_MINUTES,
        signal_start_minutes=OBSERVATION_MINUTES,
        grace_seconds=RULE2_CHECKPOINT_GRACE_SECONDS,
    ):
        if row["mint"] in already_flagged:
            continue

        reason = classify_rule2(
            row["payload"],
            row["changes_in_window"],
        )
        if reason is not None:
            candidates.append({**row, "reason": reason})

    acted["rule2"] = _act(repository, candidates, apply)
    already_flagged.update(row["mint"] for row in acted["rule2"])

    # Rule 3 — T+5 economic-presence checkpoint.
    # A successful poll at/after T+5 is the complete checkpoint requirement.
    candidates = []
    for row in queries.fetch_economic_presence_checkpoint(
        checkpoint_minutes=RULE3_CHECKPOINT_MINUTES,
        grace_seconds=RULE3_CHECKPOINT_GRACE_SECONDS,
    ):
        if row["mint"] in already_flagged:
            continue

        reason = classify_rule3(row["has_economic_data"])
        if reason is not None:
            candidates.append({**row, "reason": reason})

    acted["rule3"] = _act(repository, candidates, apply)
    already_flagged.update(row["mint"] for row in acted["rule3"])

    # Rule 4 / Rule 5 — permanent historical floor crossings after T+30.
    # Immutable snapshot evidence does not depend on current poll freshness.
    for rule in COLLAPSE_RULES:
        rows = queries.fetch_threshold_scan(
            rule_key=rule.key,
            field=rule.field,
            threshold=rule.floor,
            min_age_minutes=COLLAPSE_GRACE_MINUTES,
        )

        candidates = [
            {**row, "reason": rule.reason}
            for row in rows
            if row["crossing_at"] is not None
            and row["mint"] not in already_flagged
        ]

        acted[rule.key] = _act(repository, candidates, apply)
        already_flagged.update(
            row["mint"] for row in acted[rule.key]
        )

        if apply:
            queries.advance_threshold_scan(
                rule.key,
                [
                    row
                    for row in rows
                    if row["crossing_at"] is None
                ],
            )

    breakdown = {
        key: len(acted[key])
        for key in RULE_KEYS
    }

    return {
        "apply": apply,
        "breakdown": breakdown,
        "candidate_or_deactivated_count": sum(breakdown.values()),
        "active_remaining": repository.count_active(),
    }


def print_result(result: dict[str, Any]) -> None:
    print(f"LIFECYCLE apply={result['apply']}")

    label = "deactivated" if result["apply"] else "candidates"
    print(
        f"  {label}: "
        f"{result['candidate_or_deactivated_count']}"
    )

    for rule, count in result["breakdown"].items():
        print(f"    {rule}: {count}")

    print(f"  active remaining: {result['active_remaining']}")


def main() -> None:
    args = parse_args()
    settings = Settings.from_env()
    telemetry = TelemetryEmitter.from_env()

    try:
        with Database(settings.database_url) as database:
            repository = MintRepository(database)
            queries = LifecycleQueries(database)

            while True:
                started = time.monotonic()
                result = run_cycle(
                    repository=repository,
                    queries=queries,
                    apply=args.apply,
                )
                duration_ms = (time.monotonic() - started) * 1000
                print_result(result)
                telemetry.emit(
                    "lifecycle_tick",
                    apply=result["apply"],
                    affected_count=result["candidate_or_deactivated_count"],
                    breakdown=result["breakdown"],
                    active_remaining=result["active_remaining"],
                    duration_ms=round(duration_ms),
                )

                if args.once:
                    break

                print(f"\nNext cycle in {INTERVAL_SECONDS:.1f}s...\n")
                time.sleep(INTERVAL_SECONDS)
    finally:
        telemetry.close()


if __name__ == "__main__":
    main()
