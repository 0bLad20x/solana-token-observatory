from __future__ import annotations

import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lifecycle_rules import classify_rule6


class Rule6Tests(unittest.TestCase):
    def test_below_five_holders_retires(self):
        self.assertEqual(
            classify_rule6({"holderCount": 4}),
            "holder_count_below_5_at_30m",
        )
        self.assertEqual(
            classify_rule6({"holderCount": "1"}),
            "holder_count_below_5_at_30m",
        )

    def test_five_holders_survives(self):
        self.assertIsNone(classify_rule6({"holderCount": 5}))

    def test_missing_holders_is_unknown(self):
        self.assertIsNone(classify_rule6({}))
        self.assertIsNone(classify_rule6({"holderCount": None}))
        self.assertIsNone(classify_rule6({"holderCount": ""}))


if __name__ == "__main__":
    unittest.main()
