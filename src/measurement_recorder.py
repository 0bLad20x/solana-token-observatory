from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from telemetry import validate_telemetry_event


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8766
DEFAULT_HOURS = 1.0
DEFAULT_CHECKPOINT_SECONDS = 60.0
DEFAULT_OUTPUT = Path("measurements/runtime_measurement.json")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_nonnegative_int(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError("boolean is not a counter")
    result = int(value)
    if result < 0:
        raise ValueError("counter must be non-negative")
    return result


def _ratio(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return numerator / denominator


@dataclass
class MeasurementAccumulator:
    started_at: datetime = field(default_factory=_utc_now)
    events_received: int = 0
    invalid_events: int = 0
    search_lanes: set[str] = field(default_factory=set)
    new_mints_discovered: int = 0
    successful_search_requests: int = 0
    mint_positions_requested: int = 0
    mint_observations_received: int = 0
    source_version_candidates_flushed: int = 0
    new_snapshots_persisted: int = 0
    lifecycle_retirements: int = 0
    active_population_end: int | None = None
    last_event_at: str | None = None

    def consume(self, event: Any) -> bool:
        if not validate_telemetry_event(event):
            self.invalid_events += 1
            return False

        try:
            event_type = event["type"]

            if event_type == "discovery_tick":
                self.new_mints_discovered += _as_nonnegative_int(
                    event["new_mints"]
                )

            elif event_type == "search_lane_tick":
                lane = str(event["lane"]).strip()
                if lane:
                    self.search_lanes.add(lane)

                if _as_nonnegative_int(event["status"]) == 200:
                    self.successful_search_requests += 1
                    self.mint_positions_requested += _as_nonnegative_int(
                        event["requested"]
                    )
                    self.mint_observations_received += _as_nonnegative_int(
                        event["received"]
                    )

            elif event_type == "search_flush":
                self.source_version_candidates_flushed += _as_nonnegative_int(
                    event["source_versions"]
                )
                self.new_snapshots_persisted += _as_nonnegative_int(
                    event["new_snapshots"]
                )

            elif event_type == "lifecycle_tick":
                self.active_population_end = _as_nonnegative_int(
                    event["active_remaining"]
                )
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

    def snapshot(self, ended_at: datetime | None = None) -> dict[str, Any]:
        current_end = ended_at or _utc_now()
        duration_seconds = max(
            0.0,
            (current_end - self.started_at).total_seconds(),
        )

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

        return {
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
            "new_mints_discovered": self.new_mints_discovered,
            "successful_search_requests": self.successful_search_requests,
            "mint_positions_requested": self.mint_positions_requested,
            "mint_observations_received": self.mint_observations_received,
            "source_version_candidates_flushed": (
                self.source_version_candidates_flushed
            ),
            "new_snapshots_persisted": self.new_snapshots_persisted,
            "lifecycle_retirements": self.lifecycle_retirements,
            "active_population_end": self.active_population_end,
            "derived": {
                "response_coverage": response_coverage,
                "persistence_ratio": persistence_ratio,
                "unchanged_or_already_known_observations": unchanged_or_known,
                "unchanged_or_already_known_share": unchanged_or_known_share,
                "observations_per_persisted_snapshot": observations_per_snapshot,
            },
            "notes": {
                "source_version_candidates_flushed": (
                    "Sum of flush-level source-version candidates. The same "
                    "(mint, updatedAt) may appear in more than one flush, so "
                    "this is not a window-global distinct count."
                ),
                "transport": (
                    "Measurement consumes mirrored best-effort localhost UDP "
                    "telemetry. Packet loss can undercount events."
                ),
            },
            "warnings": warnings,
        }


def write_snapshot(
    accumulator: MeasurementAccumulator,
    output: Path,
    *,
    ended_at: datetime | None = None,
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f"{output.name}.tmp")
    temporary.write_text(
        json.dumps(
            accumulator.snapshot(ended_at=ended_at),
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
) -> MeasurementAccumulator:
    if not host:
        raise ValueError("host must not be empty")
    if not (0 < port <= 65_535):
        raise ValueError("port must be between 1 and 65535")
    if hours <= 0:
        raise ValueError("hours must be greater than zero")
    if checkpoint_seconds <= 0:
        raise ValueError("checkpoint_seconds must be greater than zero")

    accumulator = MeasurementAccumulator()
    loop = asyncio.get_running_loop()
    transport, _protocol = await loop.create_datagram_endpoint(
        lambda: _MeasurementProtocol(accumulator),
        local_addr=(host, port),
    )

    deadline = time.monotonic() + (hours * 3600.0)
    warned_no_events = False
    print(
        f"[measurement] listening={host}:{port} "
        f"hours={hours:g} output={output}"
    )

    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            await asyncio.sleep(min(checkpoint_seconds, remaining))
            write_snapshot(accumulator, output)

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
        write_snapshot(accumulator, output, ended_at=ended_at)
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
            "Aggregate mirrored runtime telemetry into one bounded measurement "
            "window without changing domain persistence."
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
            )
        )
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
