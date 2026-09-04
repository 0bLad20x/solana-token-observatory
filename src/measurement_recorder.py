from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from source_change_measurement import (
    CAPACITY_TARGET_SWEEPS_SECONDS,
    DEFAULT_QUERY_BATCH_SIZE,
    SourceChangeSampler,
)
from telemetry import validate_telemetry_event


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8766
DEFAULT_HOURS = 1.0
DEFAULT_CHECKPOINT_SECONDS = 60.0
DEFAULT_OUTPUT = Path("measurements/runtime_measurement.json")
DEFAULT_SOURCE_SCAN_SECONDS = 300.0
DEFAULT_SOURCE_SETTLE_SECONDS = 15.0


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_nonnegative_int(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError("boolean is not a counter")
    result = int(value)
    if result < 0:
        raise ValueError("counter must be non-negative")
    return result


def _as_nonnegative_float(value: Any) -> float:
    if isinstance(value, bool):
        raise ValueError("boolean is not a number")
    result = float(value)
    if result < 0:
        raise ValueError("number must be non-negative")
    return result


def _ratio(numerator: int | float, denominator: int | float) -> float | None:
    if denominator <= 0:
        return None
    return numerator / denominator


@dataclass
class LaneMeasurement:
    reported_attempts: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    mint_positions_requested: int = 0
    mint_observations_received: int = 0
    latency_samples: int = 0
    latency_ms_sum: float = 0.0
    latency_ms_min: float | None = None
    latency_ms_max: float | None = None
    rpm60_last: int | None = None
    rpm60_max: int | None = None

    def consume(
        self,
        *,
        status: int,
        requested: int,
        received: int,
        rpm60: int,
        latency_ms: float,
    ) -> None:
        self.reported_attempts += 1
        self.mint_positions_requested += requested
        self.mint_observations_received += received
        if status == 200:
            self.successful_requests += 1
        else:
            self.failed_requests += 1

        self.latency_samples += 1
        self.latency_ms_sum += latency_ms
        self.latency_ms_min = (
            latency_ms
            if self.latency_ms_min is None
            else min(self.latency_ms_min, latency_ms)
        )
        self.latency_ms_max = (
            latency_ms
            if self.latency_ms_max is None
            else max(self.latency_ms_max, latency_ms)
        )
        self.rpm60_last = rpm60
        self.rpm60_max = rpm60 if self.rpm60_max is None else max(self.rpm60_max, rpm60)

    def snapshot(self, duration_seconds: float) -> dict[str, Any]:
        duration_minutes = duration_seconds / 60.0
        return {
            "reported_attempts": self.reported_attempts,
            "successful_requests": self.successful_requests,
            "failed_requests": self.failed_requests,
            "success_ratio": _ratio(self.successful_requests, self.reported_attempts),
            "mint_positions_requested": self.mint_positions_requested,
            "mint_observations_received": self.mint_observations_received,
            "response_coverage": _ratio(
                self.mint_observations_received,
                self.mint_positions_requested,
            ),
            "successful_requests_per_minute": _ratio(
                self.successful_requests,
                duration_minutes,
            ),
            "token_observations_per_second": _ratio(
                self.mint_observations_received,
                duration_seconds,
            ),
            "latency_ms_mean": _ratio(self.latency_ms_sum, self.latency_samples),
            "latency_ms_min": self.latency_ms_min,
            "latency_ms_max": self.latency_ms_max,
            "rpm60_last": self.rpm60_last,
            "rpm60_max": self.rpm60_max,
        }


@dataclass
class MeasurementAccumulator:
    started_at: datetime = field(default_factory=_utc_now)
    events_received: int = 0
    invalid_events: int = 0
    search_lanes: set[str] = field(default_factory=set)
    lane_measurements: dict[str, LaneMeasurement] = field(default_factory=dict)
    new_mints_discovered: int = 0
    successful_search_requests: int = 0
    mint_positions_requested: int = 0
    mint_observations_received: int = 0
    source_version_candidates_flushed: int = 0
    new_snapshots_persisted: int = 0
    lifecycle_retirements: int = 0
    active_population_end: int | None = None
    active_population_first_observed: int | None = None
    active_population_min: int | None = None
    active_population_max: int | None = None
    active_population_sum: int = 0
    active_population_samples: int = 0
    max_search_flush_write_ms: float = 0.0
    last_event_at: str | None = None

    def consume(self, event: Any) -> bool:
        if not validate_telemetry_event(event):
            self.invalid_events += 1
            return False

        try:
            event_type = event["type"]

            if event_type == "discovery_tick":
                self.new_mints_discovered += _as_nonnegative_int(event["new_mints"])

            elif event_type == "search_lane_tick":
                lane = str(event["lane"]).strip()
                status = _as_nonnegative_int(event["status"])
                requested = _as_nonnegative_int(event["requested"])
                received = _as_nonnegative_int(event["received"])
                rpm60 = _as_nonnegative_int(event["rpm60"])
                latency_ms = _as_nonnegative_float(event["latency_ms"])

                if lane:
                    self.search_lanes.add(lane)
                    self.lane_measurements.setdefault(lane, LaneMeasurement()).consume(
                        status=status,
                        requested=requested,
                        received=received,
                        rpm60=rpm60,
                        latency_ms=latency_ms,
                    )

                if status == 200:
                    self.successful_search_requests += 1
                    self.mint_positions_requested += requested
                    self.mint_observations_received += received

            elif event_type == "search_flush":
                self.source_version_candidates_flushed += _as_nonnegative_int(
                    event["source_versions"]
                )
                self.new_snapshots_persisted += _as_nonnegative_int(
                    event["new_snapshots"]
                )
                self.max_search_flush_write_ms = max(
                    self.max_search_flush_write_ms,
                    _as_nonnegative_float(event["write_ms"]),
                )

            elif event_type == "lifecycle_tick":
                active = _as_nonnegative_int(event["active_remaining"])
                self.active_population_end = active
                if self.active_population_first_observed is None:
                    self.active_population_first_observed = active
                self.active_population_min = (
                    active
                    if self.active_population_min is None
                    else min(self.active_population_min, active)
                )
                self.active_population_max = (
                    active
                    if self.active_population_max is None
                    else max(self.active_population_max, active)
                )
                self.active_population_sum += active
                self.active_population_samples += 1
                if bool(event["apply"]):
                    self.lifecycle_retirements += _as_nonnegative_int(
                        event["affected_count"]
                    )

        except (KeyError, TypeError, ValueError):
            self.invalid_events += 1
            return False

        self.events_received += 1
        self.last_event_at = str(event["at"])
        return True

    def _lane_capacity(
        self,
        *,
        duration_seconds: float,
        source_changes: dict[str, Any] | None,
    ) -> dict[str, Any]:
        lane_rows = {
            lane: measurement.snapshot(duration_seconds)
            for lane, measurement in sorted(self.lane_measurements.items())
        }
        request_rates = [
            row["successful_requests_per_minute"]
            for row in lane_rows.values()
            if row["successful_requests_per_minute"] is not None
        ]
        observation_rates = [
            row["token_observations_per_second"]
            for row in lane_rows.values()
            if row["token_observations_per_second"] is not None
        ]
        mean_request_rate = (
            sum(request_rates) / len(request_rates) if request_rates else None
        )
        mean_observation_rate = (
            sum(observation_rates) / len(observation_rates)
            if observation_rates
            else None
        )
        total_observation_rate = _ratio(
            self.mint_observations_received,
            duration_seconds,
        )

        interval_targets = {
            float(row["target_sweep_seconds"]): row
            for row in (source_changes or {}).get("interval_targets", [])
        }
        target_rows = []
        for target in CAPACITY_TARGET_SWEEPS_SECONDS:
            required_keys = None
            if (
                self.active_population_end is not None
                and mean_observation_rate is not None
                and mean_observation_rate > 0
            ):
                required_keys = math.ceil(
                    self.active_population_end / (mean_observation_rate * target)
                )
            interval_row = interval_targets.get(target, {})
            target_rows.append(
                {
                    "target_full_population_sweep_seconds": target,
                    "required_keys_at_population_end": required_keys,
                    "observed_source_intervals_faster_than_target_share": (
                        interval_row.get("observed_intervals_faster_share")
                    ),
                    "mints_with_any_faster_interval_share": (
                        interval_row.get("mints_with_any_faster_interval_share")
                    ),
                }
            )

        reference_sweep = None
        if (
            self.active_population_end is not None
            and total_observation_rate is not None
            and total_observation_rate > 0
        ):
            reference_sweep = self.active_population_end / total_observation_rate

        return {
            "lane_semantics": (
                "One search lane corresponds to one configured Jupiter Search "
                "API key; API keys themselves are never recorded."
            ),
            "per_lane": lane_rows,
            "mean_successful_requests_per_minute_per_lane": mean_request_rate,
            "mean_token_observations_per_second_per_lane": mean_observation_rate,
            "average_successful_batch_size": _ratio(
                self.mint_observations_received,
                self.successful_search_requests,
            ),
            "reference_full_population_sweep_seconds_at_window_end": reference_sweep,
            "capacity_targets": target_rows,
            "capacity_formula": (
                "required_keys = ceil(active_tokens / "
                "(measured_token_observations_per_second_per_lane * "
                "target_sweep_seconds))"
            ),
        }

    def snapshot(
        self,
        ended_at: datetime | None = None,
        *,
        source_changes: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        current_end = ended_at or _utc_now()
        duration_seconds = max(0.0, (current_end - self.started_at).total_seconds())

        persistence_ratio = _ratio(
            self.new_snapshots_persisted,
            self.mint_observations_received,
        )
        response_coverage = _ratio(
            self.mint_observations_received,
            self.mint_positions_requested,
        )
        observations_per_snapshot = _ratio(
            self.mint_observations_received,
            self.new_snapshots_persisted,
        )

        unchanged_or_known = max(
            0,
            self.mint_observations_received - self.new_snapshots_persisted,
        )
        unchanged_or_known_share = _ratio(
            unchanged_or_known,
            self.mint_observations_received,
        )

        warnings: list[str] = []
        if self.new_snapshots_persisted > self.mint_observations_received:
            warnings.append(
                "Persisted snapshot telemetry exceeds received observation "
                "telemetry; best-effort UDP loss likely affected the window."
            )

        lane_attempts = sum(
            measurement.reported_attempts
            for measurement in self.lane_measurements.values()
        )
        lane_failures = sum(
            measurement.failed_requests
            for measurement in self.lane_measurements.values()
        )

        payload: dict[str, Any] = {
            "measurement_kind": "best_effort_telemetry_aggregate",
            "started_at": self.started_at.isoformat(),
            "ended_at": current_end.isoformat(),
            "duration_seconds": round(duration_seconds, 3),
            "duration_hours": round(duration_seconds / 3600.0, 6),
            "events_received": self.events_received,
            "invalid_events": self.invalid_events,
            "last_event_at": self.last_event_at,
            "search_lanes_observed": sorted(self.search_lanes),
            "search_lane_count": len(self.search_lanes),
            "reported_search_attempts": lane_attempts,
            "reported_search_failures": lane_failures,
            "reported_search_success_ratio": _ratio(
                self.successful_search_requests,
                lane_attempts,
            ),
            "new_mints_discovered": self.new_mints_discovered,
            "successful_search_requests": self.successful_search_requests,
            "mint_positions_requested": self.mint_positions_requested,
            "mint_observations_received": self.mint_observations_received,
            "source_version_candidates_flushed": self.source_version_candidates_flushed,
            "new_snapshots_persisted": self.new_snapshots_persisted,
            "lifecycle_retirements": self.lifecycle_retirements,
            "active_population_end": self.active_population_end,
            "active_population": {
                "first_lifecycle_sample": self.active_population_first_observed,
                "min_lifecycle_sample": self.active_population_min,
                "max_lifecycle_sample": self.active_population_max,
                "mean_lifecycle_sample": _ratio(
                    self.active_population_sum,
                    self.active_population_samples,
                ),
                "sample_count": self.active_population_samples,
            },
            "max_search_flush_write_ms": self.max_search_flush_write_ms,
            "derived": {
                "response_coverage": response_coverage,
                "persistence_ratio": persistence_ratio,
                "unchanged_or_already_known_observations": unchanged_or_known,
                "unchanged_or_already_known_share": unchanged_or_known_share,
                "observations_per_persisted_snapshot": observations_per_snapshot,
            },
            "lane_capacity": self._lane_capacity(
                duration_seconds=duration_seconds,
                source_changes=source_changes,
            ),
            "notes": {
                "source_version_candidates_flushed": (
                    "Sum of flush-level source-version candidates. The same "
                    "(mint, updatedAt) may appear in more than one flush, so "
                    "this is not a window-global distinct count."
                ),
                "transport": (
                    "Aggregate runtime telemetry consumes mirrored best-effort "
                    "localhost UDP and can undercount events. Persisted source "
                    "change cadence, when enabled, is read independently from "
                    "PostgreSQL snapshots."
                ),
            },
            "warnings": warnings,
        }
        if source_changes is not None:
            payload["source_changes"] = source_changes
        return payload


def write_snapshot(
    accumulator: MeasurementAccumulator,
    output: Path,
    *,
    ended_at: datetime | None = None,
    source_changes: dict[str, Any] | None = None,
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f"{output.name}.tmp")
    temporary.write_text(
        json.dumps(
            accumulator.snapshot(
                ended_at=ended_at,
                source_changes=source_changes,
            ),
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(output)


class _MeasurementProtocol(asyncio.DatagramProtocol):
    def __init__(self, accumulator: MeasurementAccumulator) -> None:
        self._accumulator = accumulator

    def datagram_received(self, data: bytes, _addr: tuple[str, int]) -> None:
        try:
            event = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._accumulator.invalid_events += 1
            return
        self._accumulator.consume(event)


async def record(
    *,
    host: str,
    port: int,
    hours: float,
    checkpoint_seconds: float,
    output: Path,
    source_changes: bool = False,
    database_url: str | None = None,
    source_scan_seconds: float = DEFAULT_SOURCE_SCAN_SECONDS,
    source_settle_seconds: float = DEFAULT_SOURCE_SETTLE_SECONDS,
    source_query_batch_size: int = DEFAULT_QUERY_BATCH_SIZE,
    per_mint_output: Path | None = None,
) -> MeasurementAccumulator:
    if not host:
        raise ValueError("host must not be empty")
    if not (0 < port <= 65_535):
        raise ValueError("port must be between 1 and 65535")
    if hours <= 0:
        raise ValueError("hours must be greater than zero")
    if checkpoint_seconds <= 0:
        raise ValueError("checkpoint_seconds must be greater than zero")
    if source_changes and not (database_url or "").strip():
        raise ValueError(
            "DATABASE_URL must not be empty when --source-changes is enabled"
        )
    if source_scan_seconds <= 0:
        raise ValueError("source_scan_seconds must be greater than zero")
    if source_settle_seconds < 0:
        raise ValueError("source_settle_seconds must be non-negative")

    accumulator = MeasurementAccumulator()
    source_sampler = (
        SourceChangeSampler(
            database_url=database_url or "",
            started_at=accumulator.started_at,
            query_batch_size=source_query_batch_size,
        )
        if source_changes
        else None
    )

    loop = asyncio.get_running_loop()
    transport, _protocol = await loop.create_datagram_endpoint(
        lambda: _MeasurementProtocol(accumulator),
        local_addr=(host, port),
    )

    deadline = time.monotonic() + (hours * 3600.0)
    next_source_scan = time.monotonic() + source_scan_seconds
    warned_no_events = False
    print(
        f"[measurement] listening={host}:{port} "
        f"hours={hours:g} output={output} "
        f"source_changes={'on' if source_sampler else 'off'}"
    )

    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            await asyncio.sleep(min(checkpoint_seconds, remaining))

            if source_sampler is not None and time.monotonic() >= next_source_scan:
                cutoff = _utc_now() - timedelta(seconds=source_settle_seconds)
                scanned = await asyncio.to_thread(source_sampler.scan_until, cutoff)
                print(
                    f"[measurement] source_scan rows={scanned} "
                    f"through={cutoff.isoformat()}"
                )
                next_source_scan = time.monotonic() + source_scan_seconds

            source_summary = (
                source_sampler.summary() if source_sampler is not None else None
            )
            write_snapshot(
                accumulator,
                output,
                source_changes=source_summary,
            )

            if accumulator.events_received == 0 and not warned_no_events:
                print(
                    "[measurement] WARNING no telemetry received yet; "
                    "ensure Collector/Lifecycle were restarted after setting "
                    "TELEMETRY_MIRROR_PORT to this recorder port"
                )
                warned_no_events = True
    finally:
        transport.close()
        ended_at = _utc_now()
        source_summary = None

        if source_sampler is not None:
            if source_settle_seconds > 0:
                print(
                    "[measurement] waiting "
                    f"{source_settle_seconds:g}s for final persisted writes"
                )
                await asyncio.sleep(source_settle_seconds)

            scanned = await asyncio.to_thread(source_sampler.scan_until, ended_at)
            population_rows = await asyncio.to_thread(
                source_sampler.load_population_metadata,
                ended_at,
            )
            source_summary = source_sampler.summary(ended_at=ended_at)
            print(
                f"[measurement] final_source_scan rows={scanned} "
                f"population_overlap={population_rows}"
            )

            if per_mint_output is not None:
                await asyncio.to_thread(
                    source_sampler.write_per_mint_csv,
                    per_mint_output,
                )
                print(f"[measurement] per_mint_output={per_mint_output}")

            if accumulator.max_search_flush_write_ms > source_settle_seconds * 1000:
                source_summary.setdefault("warnings", []).append(
                    "Observed search flush write latency exceeded the final "
                    "settle window; a very late commit could make the final "
                    "source scan incomplete."
                )

        write_snapshot(
            accumulator,
            output,
            ended_at=ended_at,
            source_changes=source_summary,
        )
        print(
            f"[measurement] complete events={accumulator.events_received} "
            f"output={output}"
        )

    return accumulator


def _default_port() -> int:
    value = os.getenv("TELEMETRY_MIRROR_PORT", "").strip()
    return int(value) if value else DEFAULT_PORT


def parse_args() -> argparse.Namespace:
    load_dotenv(dotenv_path=Path.cwd() / ".env")
    parser = argparse.ArgumentParser(
        description=(
            "Measure runtime throughput and, optionally, incrementally analyze "
            "persisted Jupiter source-version cadence without changing domain "
            "persistence."
        ),
    )
    parser.add_argument(
        "--host",
        default=(
            os.getenv("TELEMETRY_MIRROR_HOST", DEFAULT_HOST).strip()
            or DEFAULT_HOST
        ),
        help="UDP host for mirrored telemetry (default: 127.0.0.1).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=_default_port(),
        help="UDP port for mirrored telemetry (default: 8766).",
    )
    parser.add_argument(
        "--hours",
        type=float,
        default=DEFAULT_HOURS,
        help="Measurement window in hours (default: 1).",
    )
    parser.add_argument(
        "--checkpoint-seconds",
        type=float,
        default=DEFAULT_CHECKPOINT_SECONDS,
        help="Rewrite the JSON checkpoint at this cadence (default: 60).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=(
            "JSON output path "
            "(default: measurements/runtime_measurement.json)."
        ),
    )
    parser.add_argument(
        "--source-changes",
        action="store_true",
        help=(
            "Incrementally analyze persisted per-mint Jupiter updatedAt cadence "
            "during the measurement window. Requires DATABASE_URL."
        ),
    )
    parser.add_argument(
        "--source-scan-seconds",
        type=float,
        default=DEFAULT_SOURCE_SCAN_SECONDS,
        help="Cadence for incremental snapshot scans (default: 300).",
    )
    parser.add_argument(
        "--source-settle-seconds",
        type=float,
        default=DEFAULT_SOURCE_SETTLE_SECONDS,
        help=(
            "Lag behind live writes and final wait before the last source scan "
            "(default: 15)."
        ),
    )
    parser.add_argument(
        "--source-query-batch-size",
        type=int,
        default=DEFAULT_QUERY_BATCH_SIZE,
        help="Maximum rows fetched per source-history query page (default: 50000).",
    )
    parser.add_argument(
        "--per-mint-output",
        type=Path,
        default=None,
        help=(
            "Optional local CSV with one compact source-cadence row per mint. "
            "The normal JSON already contains population distributions and "
            "the most informative extremes."
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        asyncio.run(
            record(
                host=args.host,
                port=args.port,
                hours=args.hours,
                checkpoint_seconds=args.checkpoint_seconds,
                output=args.output,
                source_changes=args.source_changes,
                database_url=os.getenv("DATABASE_URL", "").strip(),
                source_scan_seconds=args.source_scan_seconds,
                source_settle_seconds=args.source_settle_seconds,
                source_query_batch_size=args.source_query_batch_size,
                per_mint_output=args.per_mint_output,
            )
        )
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
