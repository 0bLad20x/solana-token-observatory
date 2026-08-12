from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from temporal_context import build_temporal_summary, build_temporal_summary_bundle


def history_row(at: datetime, **values: object) -> dict[str, object]:
    return {"observed_at": at, **values}


def sample_row(at: datetime, **values: object) -> dict[str, object]:
    return {"observed_at": at, **values}


class TemporalContextTests(unittest.TestCase):
    def test_summary_bundle_contains_no_temporal_history(self) -> None:
        start = datetime(2026, 8, 12, tzinfo=timezone.utc)
        history = [
            history_row(start, market_cap="100", liquidity="20", holders="10"),
            history_row(
                start + timedelta(hours=8),
                market_cap="200",
                liquidity="30",
                holders="20",
            ),
        ]
        samples = [
            sample_row(
                start,
                market_cap="100",
                liquidity="20",
                stats_1h={"buyVolume": 50, "sellVolume": 25},
            ),
            sample_row(
                start + timedelta(hours=8),
                market_cap="200",
                liquidity="30",
                stats_1h={"buyVolume": 100, "sellVolume": 50},
            ),
        ]

        bundle = build_temporal_summary_bundle(
            "mint-a",
            history,
            samples,
            token={"name": "Token", "symbol": "TOK", "launchpad": "pump.fun"},
        )

        self.assertNotIn("temporal_history", bundle)
        self.assertEqual(bundle["token"]["mint"], "mint-a")
        self.assertEqual(bundle["token"]["symbol"], "TOK")
        self.assertEqual(bundle["summary"]["history"]["hours"], 8.0)
        self.assertEqual(bundle["summary"]["market_cap"]["change_pct"], 100.0)
        self.assertEqual(
            bundle["summary"]["activity_1h"]["fields"]["buy_volume"]["current"],
            100,
        )

    def test_exact_core_metrics_use_all_observations(self) -> None:
        start = datetime(2026, 8, 12, tzinfo=timezone.utc)
        history = [
            history_row(start, market_cap=100),
            history_row(start + timedelta(minutes=1), market_cap=250),
            history_row(start + timedelta(minutes=2), market_cap=125),
        ]
        samples = [sample_row(start + timedelta(minutes=2), market_cap=125)]

        summary = build_temporal_summary(history, samples)

        self.assertEqual(summary["market_cap"]["min"], 100)
        self.assertEqual(summary["market_cap"]["max"], 250)
        self.assertEqual(summary["market_cap"]["current"], 125)
        self.assertEqual(summary["market_cap"]["max_drawdown_pct"], -50.0)

    def test_missing_values_stay_missing(self) -> None:
        start = datetime(2026, 8, 12, tzinfo=timezone.utc)
        history = [
            history_row(start, market_cap=100),
            history_row(start + timedelta(minutes=5), market_cap=110),
        ]
        samples = [sample_row(start + timedelta(minutes=5), market_cap=110)]

        summary = build_temporal_summary(history, samples)

        self.assertNotIn("liquidity", summary)
        self.assertNotIn("holders", summary)
        self.assertNotIn("ownership", summary)

    def test_activity_medians_use_only_time_normalized_samples(self) -> None:
        start = datetime(2026, 8, 12, tzinfo=timezone.utc)
        history = [
            history_row(start, market_cap=100),
            history_row(start + timedelta(seconds=1), market_cap=101),
            history_row(start + timedelta(minutes=5), market_cap=102),
        ]
        samples = [
            sample_row(start, stats_1h={"buyVolume": 10, "sellVolume": 10}),
            sample_row(
                start + timedelta(minutes=5),
                stats_1h={"buyVolume": 30, "sellVolume": 10},
            ),
        ]

        summary = build_temporal_summary(history, samples)

        buy = summary["activity_1h"]["fields"]["buy_volume"]
        self.assertEqual(buy["current"], 30)
        self.assertEqual(buy["median"], 20.0)
        ratio = summary["activity_1h"]["derived"]["buy_sell_volume_ratio"]
        self.assertEqual(ratio["current"], 3.0)
        self.assertEqual(ratio["median"], 2.0)


if __name__ == "__main__":
    unittest.main()
