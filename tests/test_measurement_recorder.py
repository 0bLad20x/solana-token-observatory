from __future__ import annotations

import json
import socket
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from measurement_recorder import (
    LaneMeasurement,
    MeasurementAccumulator,
    write_snapshot,
)
from telemetry import TelemetryEmitter


def telemetry_event(event_type: str, **fields: object) -> dict:
    return {
        "type": event_type,
        "at": "2026-09-03T08:00:00+00:00",
        **fields,
    }


class MeasurementAccumulatorTests(unittest.TestCase):
    def test_aggregates_runtime_window_without_inventing_distinct_versions(self) -> None:
        accumulator = MeasurementAccumulator(
            started_at=datetime(2026, 9, 3, 8, tzinfo=timezone.utc)
        )

        self.assertTrue(
            accumulator.consume(
                telemetry_event(
                    "discovery_tick",
                    source="pumpfun",
                    status=101,
                    response_items=4,
                    candidate_occurrences=4,
                    unique_candidates=3,
                    new_mints=2,
                    latency_ms=None,
                )
            )
        )
        self.assertTrue(
            accumulator.consume(
                telemetry_event(
                    "search_lane_tick",
                    lane="lane0",
                    status=200,
                    requested=100,
                    received=90,
                    rpm60=58,
                    latency_ms=200,
                )
            )
        )
        self.assertTrue(
            accumulator.consume(
                telemetry_event(
                    "search_flush",
                    polled_tokens=90,
                    source_versions=12,
                    new_snapshots=8,
                    write_ms=5,
                    queue_size=0,
                )
            )
        )
        self.assertTrue(
            accumulator.consume(
                telemetry_event(
                    "lifecycle_tick",
                    apply=True,
                    affected_count=3,
                    breakdown={"rule1": 3},
                    active_remaining=50,
                    duration_ms=4,
                )
            )
        )

        snapshot = accumulator.snapshot(
            ended_at=datetime(2026, 9, 3, 9, tzinfo=timezone.utc)
        )

        self.assertEqual(snapshot["duration_hours"], 1.0)
        self.assertEqual(snapshot["search_lane_count"], 1)
        self.assertEqual(snapshot["new_mints_discovered"], 2)
        self.assertEqual(snapshot["successful_search_requests"], 1)
        self.assertEqual(snapshot["mint_positions_requested"], 100)
        self.assertEqual(snapshot["mint_observations_received"], 90)
        self.assertEqual(snapshot["source_version_candidates_flushed"], 12)
        self.assertEqual(snapshot["new_snapshots_persisted"], 8)
        self.assertEqual(snapshot["lifecycle_retirements"], 3)
        self.assertEqual(snapshot["active_population_end"], 50)
        self.assertAlmostEqual(
            snapshot["derived"]["persistence_ratio"],
            8 / 90,
        )
        self.assertAlmostEqual(
            snapshot["derived"]["observations_per_persisted_snapshot"],
            90 / 8,
        )
        self.assertAlmostEqual(
            snapshot["lane_capacity"][
                "mean_successful_requests_per_minute_per_lane"
            ],
            1 / 60,
        )
        self.assertAlmostEqual(
            snapshot["lane_capacity"][
                "mean_token_observations_per_second_per_lane"
            ],
            90 / 3600,
        )

    def test_capacity_targets_use_measured_lane_rate_and_population(self) -> None:
        accumulator = MeasurementAccumulator(
            started_at=datetime(2026, 9, 3, 8, tzinfo=timezone.utc)
        )
        accumulator.search_lanes.add("lane0")
        accumulator.lane_measurements["lane0"] = LaneMeasurement(
            reported_attempts=3600,
            successful_requests=3600,
            mint_positions_requested=360_000,
            mint_observations_received=360_000,
        )
        accumulator.successful_search_requests = 3600
        accumulator.mint_positions_requested = 360_000
        accumulator.mint_observations_received = 360_000
        accumulator.active_population_end = 1_000

        snapshot = accumulator.snapshot(
            ended_at=datetime(2026, 9, 3, 9, tzinfo=timezone.utc),
            source_changes={
                "interval_targets": [
                    {
                        "target_sweep_seconds": 1.0,
                        "observed_intervals_faster_share": 0.03,
                        "mints_with_any_faster_interval_share": 0.11,
                    }
                ]
            },
        )
        targets = {
            row["target_full_population_sweep_seconds"]: row
            for row in snapshot["lane_capacity"]["capacity_targets"]
        }

        self.assertAlmostEqual(
            snapshot["lane_capacity"][
                "mean_token_observations_per_second_per_lane"
            ],
            100.0,
        )
        self.assertEqual(targets[1.0]["required_keys_at_population_end"], 10)
        self.assertEqual(
            targets[1.0]["observed_source_intervals_faster_than_target_share"],
            0.03,
        )
        self.assertEqual(targets[1.0]["mints_with_any_faster_interval_share"], 0.11)

    def test_snapshot_is_written_atomically(self) -> None:
        accumulator = MeasurementAccumulator()

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "nested" / "measurement.json"
            write_snapshot(accumulator, output)
            payload = json.loads(output.read_text(encoding="utf-8"))
            temporary = output.with_name(f"{output.name}.tmp")
            self.assertFalse(temporary.exists())

        self.assertEqual(
            payload["measurement_kind"],
            "best_effort_telemetry_aggregate",
        )


class TelemetryMirrorTests(unittest.TestCase):
    def test_emitter_can_mirror_one_event_to_second_local_target(self) -> None:
        with (
            socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as primary,
            socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as mirror,
        ):
            primary.bind(("127.0.0.1", 0))
            mirror.bind(("127.0.0.1", 0))
            primary.settimeout(1.0)
            mirror.settimeout(1.0)

            emitter = TelemetryEmitter(
                port=primary.getsockname()[1],
                mirror_port=mirror.getsockname()[1],
            )
            try:
                self.assertTrue(
                    emitter.emit(
                        "search_lane_tick",
                        lane="lane3",
                        status=200,
                        requested=100,
                        received=99,
                        rpm60=58,
                        latency_ms=190,
                    )
                )
                primary_payload = json.loads(primary.recvfrom(65_535)[0])
                mirror_payload = json.loads(mirror.recvfrom(65_535)[0])
            finally:
                emitter.close()

        self.assertEqual(primary_payload["lane"], "lane3")
        self.assertEqual(mirror_payload, primary_payload)


if __name__ == "__main__":
    unittest.main()
