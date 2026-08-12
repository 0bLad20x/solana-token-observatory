from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from temporal_context import (
    build_temporal_context,
    build_temporal_summary_bundle,
)


def row(at: datetime, **payload: object) -> dict[str, object]:
    return {"observed_at": at, "payload": payload}


class TemporalContextTests(unittest.TestCase):
    def test_resolution_uses_one_minute_through_six_hours(self) -> None:
        start = datetime(2026, 8, 12, tzinfo=timezone.utc)
        rows = [
            row(start, name="Token", mcap=100, holderCount=10),
            row(start + timedelta(hours=6), name="Token", mcap=150, holderCount=20),
        ]

        context = build_temporal_context("mint-a", rows)

        self.assertEqual(context["temporal_history"]["resolution_minutes"], 1)
        self.assertEqual(context["summary"]["market_cap"]["change_pct"], 50.0)

    def test_resolution_switches_to_five_minutes_after_six_hours(self) -> None:
        start = datetime(2026, 8, 12, tzinfo=timezone.utc)
        rows = [
            row(start, name="Token", mcap=100),
            row(start + timedelta(hours=6, seconds=1), name="Token", mcap=90),
        ]

        context = build_temporal_context("mint-a", rows)

        self.assertEqual(context["temporal_history"]["resolution_minutes"], 5)

    def test_summary_is_standalone_and_identical_to_context_summary(self) -> None:
        start = datetime(2026, 8, 12, tzinfo=timezone.utc)
        rows = [
            row(
                start,
                name="Token",
                symbol="TOK",
                mcap=100,
                liquidity=20,
                holderCount=10,
                stats1h={"buyVolume": 50, "sellVolume": 25},
            ),
            row(
                start + timedelta(hours=8),
                name="Token",
                symbol="TOK",
                mcap=200,
                liquidity=30,
                holderCount=20,
                stats1h={"buyVolume": 100, "sellVolume": 50},
            ),
        ]

        summary_bundle = build_temporal_summary_bundle("mint-a", rows)
        context = build_temporal_context("mint-a", rows)

        self.assertEqual(summary_bundle["summary"], context["summary"])
        self.assertEqual(summary_bundle["token"], context["token"])
        self.assertNotIn("resolution_minutes", summary_bundle["summary"]["history"])
        self.assertNotIn("temporal_history", summary_bundle)

    def test_missing_values_stay_missing(self) -> None:
        start = datetime(2026, 8, 12, tzinfo=timezone.utc)
        rows = [
            row(start, name="Token", mcap=100),
            row(start + timedelta(minutes=5), name="Token", mcap=110),
        ]

        context = build_temporal_context("mint-a", rows)

        self.assertNotIn("liquidity", context["summary"])
        self.assertNotIn("holders", context["summary"])
        for bucket in context["temporal_history"]["buckets"]:
            self.assertNotIn("liquidity", bucket)
            self.assertNotIn("holders", bucket)


if __name__ == "__main__":
    unittest.main()
