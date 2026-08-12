from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lifecycle_rules import classify_rule7


class Rule7Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 8, 12, 20, 0, tzinfo=timezone.utc)
        self.first_observed_at = self.now - timedelta(days=3)

    def test_fresh_poll_and_24h_source_inactivity_retires(self):
        reason = classify_rule7(
            first_observed_at=self.first_observed_at,
            last_polled_at=self.now - timedelta(seconds=10),
            last_changed_at=self.now - timedelta(hours=24),
            now=self.now,
        )
        self.assertEqual(reason, "source_unchanged_for_24h")

    def test_less_than_24h_survives(self):
        reason = classify_rule7(
            first_observed_at=self.first_observed_at,
            last_polled_at=self.now - timedelta(seconds=10),
            last_changed_at=self.now - timedelta(hours=23, minutes=59),
            now=self.now,
        )
        self.assertIsNone(reason)

    def test_stale_poll_does_not_retire(self):
        reason = classify_rule7(
            first_observed_at=self.first_observed_at,
            last_polled_at=self.now - timedelta(seconds=61),
            last_changed_at=self.now - timedelta(days=2),
            now=self.now,
        )
        self.assertIsNone(reason)

    def test_missing_source_timestamp_does_not_retire(self):
        reason = classify_rule7(
            first_observed_at=self.first_observed_at,
            last_polled_at=self.now - timedelta(seconds=10),
            last_changed_at=None,
            now=self.now,
        )
        self.assertIsNone(reason)

    def test_never_observed_does_not_retire(self):
        reason = classify_rule7(
            first_observed_at=None,
            last_polled_at=self.now - timedelta(seconds=10),
            last_changed_at=self.now - timedelta(days=2),
            now=self.now,
        )
        self.assertIsNone(reason)


if __name__ == "__main__":
    unittest.main()
