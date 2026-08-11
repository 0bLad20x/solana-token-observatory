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


DEFAULT_MAX_POLL_LAG_SECONDS = 60.0
DEFAULT_MIN_FRESH_COVERAGE = 0.95
DEFAULT_INTERVAL_SECONDS = 15.0

RULE_KEYS = ("rule1", "rule2", "rule3", "rule4", "rule5")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Lifecycle hard-retire engine. Rule 1-5 disable dead tokens by setting tracking_enabled=false.",
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
    parser.add_argument(
        "--interval-seconds",
        type=float,
        default=DEFAULT_INTERVAL_SECONDS,
        help="Loop interval.",
    )
    parser.add_argument(
        "--max-poll-lag-seconds",
        type=float,
        default=DEFAULT_MAX_POLL_LAG_SECONDS,
        help="A token's last_polled_at must be this fresh before any rule may retire it.",
    )
    parser.add_argument(
        "--min-fresh-coverage",
        type=float,
        default=DEFAULT_MIN_FRESH_COVERAGE,
        help="Circuit breaker: minimum fraction of mature active tokens with a fresh last_polled_at required before any write.",
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
    return [candidate for candidate in candidates if candidate["mint"] in retired]


def run_cycle(
    repository: MintRepository,
    queries: LifecycleQueries,
    apply: bool,
    max_poll_lag_seconds: float,
    min_fresh_coverage: float,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    already_flagged: set[str] = set()
    acted: dict[str, list[dict[str, Any]]] = {key: [] for key in RULE_KEYS}

    # Preserve the current safety semantics exactly: the circuit-breaker
    # population is the same mature T+10 population used by Rule 1.
    state_rows = queries.fetch_mature_active_state(OBSERVATION_MINUTES * 60)
    mature_active = len(state_rows)
    fresh_active = sum(
        1
        for row in state_rows
        if row["last_polled_at"] is not None
        and (now - row["last_polled_at"]).total_seconds() <= max_poll_lag_seconds
    )
    fresh_coverage = fresh_active / mature_active if mature_active else 0.0
    circuit_open = mature_active == 0 or fresh_coverage < min_fresh_coverage

    startup_health = None
    if mature_active == 0:
        startup_health = queries.fetch_startup_health()

    if not circuit_open:
        # Rule 1 -- current latest state after T+10 from first observation.
        candidates = []
        for row in state_rows:
            if row["last_polled_at"] is None:
                continue
            if (now - row["last_polled_at"]).total_seconds() > max_poll_lag_seconds:
                continue
            reason = classify_rule1(row["payload"])
            if reason is not None:
                candidates.append({**row, "reason": reason})

        acted["rule1"] = _act(repository, candidates, apply)
        already_flagged.update(row["mint"] for row in acted["rule1"])

        # Rule 2 -- same T+10 -> T+30 evidence and same T+30 + 60s trigger window.
        rows = queries.fetch_continuation_checkpoint(
            checkpoint_minutes=RULE2_CHECKPOINT_MINUTES,
            signal_start_minutes=OBSERVATION_MINUTES,
            grace_seconds=RULE2_CHECKPOINT_GRACE_SECONDS,
            max_poll_lag_seconds=max_poll_lag_seconds,
        )
        candidates = []
        for row in rows:
            if row["mint"] in already_flagged:
                continue
            reason = classify_rule2(row["payload"], row["changes_in_window"])
            if reason is not None:
                candidates.append({**row, "reason": reason})

        acted["rule2"] = _act(repository, candidates, apply)
        already_flagged.update(row["mint"] for row in acted["rule2"])

        # Rule 3 -- same T+5 + 60s window and same economic-absence evidence.
        rows = queries.fetch_economic_presence_checkpoint(
            checkpoint_minutes=RULE3_CHECKPOINT_MINUTES,
            grace_seconds=RULE3_CHECKPOINT_GRACE_SECONDS,
            max_poll_lag_seconds=max_poll_lag_seconds,
        )
        candidates = []
        for row in rows:
            if row["mint"] in already_flagged:
                continue
            reason = classify_rule3(row["has_economic_data"])
            if reason is not None:
                candidates.append({**row, "reason": reason})

        acted["rule3"] = _act(repository, candidates, apply)
        already_flagged.update(row["mint"] for row in acted["rule3"])

        # Rule 4 / Rule 5 -- same permanent floor crossing after T+30.
        # No rule-specific DB checkpoint is needed: the query reconstructs the
        # first crossing from immutable snapshots and the generic index.
        for rule in COLLAPSE_RULES:
            rows = queries.fetch_threshold_scan(
                rule_key=rule.key,
                field=rule.field,
                threshold=rule.floor,
                min_age_minutes=COLLAPSE_GRACE_MINUTES,
                max_poll_lag_seconds=max_poll_lag_seconds,
            )
            candidates = [
                {**row, "reason": rule.reason}
                for row in rows
                if row["crossing_at"] is not None
                and row["mint"] not in already_flagged
            ]
            acted[rule.key] = _act(repository, candidates, apply)
            already_flagged.update(row["mint"] for row in acted[rule.key])

            if apply:
                queries.advance_threshold_scan(
                    rule.key,
                    [row for row in rows if row["crossing_at"] is None],
                )

    active_remaining = repository.count_active()

    breakdown = {key: len(acted[key]) for key in RULE_KEYS}
    return {
        "apply": apply,
        "max_poll_lag_seconds": max_poll_lag_seconds,
        "min_fresh_coverage": min_fresh_coverage,
        "mature_active": mature_active,
        "fresh_active": fresh_active,
        "fresh_coverage": fresh_coverage,
        "circuit_open": circuit_open,
        "breakdown": breakdown,
        "candidate_or_deactivated_count": sum(breakdown.values()),
        "active_remaining": active_remaining,
        "startup_health": startup_health,
    }


def print_result(result: dict[str, Any]) -> None:
    print(f"LIFECYCLE apply={result['apply']}")
    print(
        f"  health: mature_active={result['mature_active']} "
        f"fresh_active={result['fresh_active']} "
        f"coverage={result['fresh_coverage']:.4%} "
        f"circuit_open={result['circuit_open']}"
    )

    if result["circuit_open"]:
        startup = result.get("startup_health")
        if startup is not None:
            oldest = startup.get("oldest_snapshot_at")
            if oldest is None:
                age_text = "none"
            else:
                age_seconds = (
                    datetime.now(timezone.utc) - oldest
                ).total_seconds()
                age_text = f"{age_seconds:.0f}s"
            print(
                f"  startup: active={startup['active_total']} "
                f"with_snapshot={startup['active_with_snapshot']} "
                f"oldest_snapshot_age={age_text} "
                f"matures_at={OBSERVATION_MINUTES * 60}s"
            )
        print("  NO RETIRE: freshness gate failed.")
        return

    label = "deactivated" if result["apply"] else "candidates"
    print(f"  {label}: {result['candidate_or_deactivated_count']}")
    for rule, count in result["breakdown"].items():
        print(f"    {rule}: {count}")
    print(f"  active remaining: {result['active_remaining']}")


def main() -> None:
    args = parse_args()

    if not 0.0 < args.min_fresh_coverage <= 1.0:
        raise SystemExit("--min-fresh-coverage muss in (0, 1] liegen")
    if args.max_poll_lag_seconds <= 0:
        raise SystemExit("--max-poll-lag-seconds muss > 0 sein")

    settings = Settings.from_env()

    with Database(settings.database_url) as database:
        repository = MintRepository(database)
        queries = LifecycleQueries(database)

        while True:
            result = run_cycle(
                repository=repository,
                queries=queries,
                apply=args.apply,
                max_poll_lag_seconds=args.max_poll_lag_seconds,
                min_fresh_coverage=args.min_fresh_coverage,
            )
            print_result(result)

            if args.once:
                break

            print(f"\nNext cycle in {args.interval_seconds:.1f}s...\n")
            time.sleep(args.interval_seconds)


if __name__ == "__main__":
    main()