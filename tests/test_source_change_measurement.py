from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from source_change_measurement import SourceChangeAccumulator


UTC = timezone.utc


def at(seconds: float) -> datetime:
    return datetime(2026, 9, 4, 8, tzinfo=UTC) + timedelta(seconds=seconds)


class SourceChangeAccumulatorTests(unittest.TestCase):
    def test_tracks_per_mint_intervals_and_actionable_sweep_thresholds(self) -> None:
        accumulator = SourceChangeAccumulator(started_at=at(0))

        rows = [
            ("A", at(0.1), at(0.0)),
            ("B", at(0.2), at(0.0)),
            ("A", at(0.5), at(0.4)),   # 0.4s
            ("A", at(1.5), at(1.4)),   # 1.0s
            ("B", at(6.2), at(6.0)),   # 6.0s
        ]
        for mint, observed_at, source_at in rows:
            accumulator.consume_row(
                mint=mint,
                observed_at=observed_at,
                source_updated_at=source_at,
            )
        accumulator.scanned_through = at(10)

        summary = accumulator.summary(ended_at=at(10))
        targets = {
            row["target_sweep_seconds"]: row
            for row in summary["interval_targets"]
        }

        self.assertEqual(summary["rows_scanned"], 5)
        self.assertEqual(summary["observed_source_intervals"], 3)
        self.assertEqual(summary["mints_with_persisted_source_versions"], 2)
        self.assertEqual(summary["mints_with_measured_intervals"], 2)
        self.assertEqual(targets[0.5]["observed_intervals_faster_than_target"], 1)
        self.assertAlmostEqual(
            targets[0.5]["observed_intervals_faster_share"],
            1 / 3,
        )
        self.assertEqual(targets[1.0]["observed_intervals_faster_than_target"], 1)
        self.assertEqual(targets[2.0]["observed_intervals_faster_than_target"], 2)
        self.assertEqual(targets[1.0]["mints_with_any_faster_interval"], 1)

        mint_a = accumulator.mints["A"]
        self.assertEqual(mint_a.source_versions, 3)
        self.assertEqual(mint_a.measured_intervals, 2)
        self.assertAlmostEqual(mint_a.min_interval_seconds or 0, 0.4)
        self.assertAlmostEqual(mint_a.mean_interval_seconds or 0, 0.7)
        self.assertAlmostEqual(mint_a.max_interval_seconds or 0, 1.0)

    def test_population_metadata_adds_zero_change_mints_and_active_normalization(self) -> None:
        accumulator = SourceChangeAccumulator(started_at=at(0))
        accumulator.consume_row(
            mint="A",
            observed_at=at(1),
            source_updated_at=at(1),
        )
        accumulator.consume_row(
            mint="A",
            observed_at=at(11),
            source_updated_at=at(11),
        )

        accumulator.apply_population_metadata(
            [
                ("A", "Alpha", "A", at(-100), None),
                ("B", "Beta", "B", at(5), at(15)),
            ],
            ended_at=at(20),
        )
        summary = accumulator.summary(ended_at=at(20))

        self.assertEqual(summary["source_observed_mints_overlapping_window"], 2)
        self.assertEqual(summary["mints_without_new_source_version"], 1)
        self.assertEqual(summary["source_versions_per_mint"]["count"], 2)
        self.assertEqual(accumulator.mints["B"].source_versions, 0)
        self.assertAlmostEqual(accumulator.mints["A"].active_seconds or 0, 20.0)
        self.assertAlmostEqual(accumulator.mints["B"].active_seconds or 0, 10.0)
        self.assertAlmostEqual(
            accumulator.mints["A"].changes_per_active_hour or 0,
            180.0,
        )

    def test_first_version_is_baseline_not_cross_window_interval(self) -> None:
        accumulator = SourceChangeAccumulator(started_at=at(0))
        accumulator.consume_row(
            mint="A",
            observed_at=at(1),
            source_updated_at=at(-500),
        )

        self.assertEqual(accumulator.mints["A"].source_versions, 1)
        self.assertEqual(accumulator.mints["A"].measured_intervals, 0)
        self.assertEqual(accumulator.global_histogram.total, 0)


if __name__ == "__main__":
    unittest.main()
