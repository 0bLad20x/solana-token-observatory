from __future__ import annotations

import unittest

from src.observatory.delta import DELTA_NUMERIC_FIELDS, changes, fingerprint


class ObservatoryDeltaContractTests(unittest.TestCase):
    def test_numeric_delta_fields_include_trade_and_volume_split(self) -> None:
        self.assertEqual(
            DELTA_NUMERIC_FIELDS,
            (
                "market_cap",
                "liquidity",
                "holders",
                "trades_5m",
                "traders_5m",
                "buy_volume_5m",
                "sell_volume_5m",
                "volume_5m",
            ),
        )

    def test_fingerprint_and_changes_share_numeric_fields(self) -> None:
        before = {
            "tracking_enabled": True,
            "source_updated_at": "a",
            "last_changed_at": "a",
            **{field: 1 for field in DELTA_NUMERIC_FIELDS},
        }
        after = {**before, "trades_5m": 3}

        self.assertNotEqual(fingerprint(before), fingerprint(after))
        result = changes(before, after)
        self.assertEqual(set(result), set(DELTA_NUMERIC_FIELDS))
        self.assertEqual(result["trades_5m"]["absolute"], 2.0)
        self.assertEqual(result["trades_5m"]["percent"], 200.0)

    def test_missing_numeric_value_stays_unknown(self) -> None:
        result = changes(
            {field: None for field in DELTA_NUMERIC_FIELDS},
            {field: 1 for field in DELTA_NUMERIC_FIELDS},
        )
        for value in result.values():
            self.assertEqual(value, {"absolute": None, "percent": None})


if __name__ == "__main__":
    unittest.main()
