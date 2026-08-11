from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from observatory.tools import MAX_LIMIT, QueryToolError, query_tokens


def token(
    mint: str,
    market_cap: float | None,
    *,
    launchpad: str = "pump.fun",
    liquidity: float | None = None,
    tracking_enabled: bool = True,
) -> dict[str, object]:
    return {
        "mint": mint,
        "name": mint,
        "symbol": mint,
        "launchpad": launchpad,
        "tracking_enabled": tracking_enabled,
        "market_cap": market_cap,
        "liquidity": liquidity,
        "holders": None,
        "trades_5m": None,
        "traders_5m": None,
        "volume_5m": None,
        "age_seconds": None,
        "change_age_seconds": None,
    }


class QueryTokensTests(unittest.TestCase):
    def test_defaults_to_top_five_and_excludes_missing_rank_values(self) -> None:
        tokens = [token(f"mint-{index}", float(index)) for index in range(1, 7)]
        tokens.append(token("missing", None))

        result = query_tokens(tokens, {})

        self.assertEqual(result["matched_count"], 6)
        self.assertEqual(result["returned_count"], 5)
        self.assertEqual(
            [row["market_cap"] for row in result["tokens"]],
            [6.0, 5.0, 4.0, 3.0, 2.0],
        )
        self.assertEqual(query_tokens([tokens[-1]], {})["tokens"], [])

    def test_filters_launchpad_before_ranking(self) -> None:
        tokens = [
            token("a", 10),
            token("b", 20),
            token("c", 30, launchpad="meteora"),
            token("d", 40, tracking_enabled=False),
        ]

        result = query_tokens(
            tokens,
            {
                "launchpad": "PUMP.FUN",
                "sort_by": "market_cap",
                "sort_order": "asc",
                "limit": 10,
            },
        )

        self.assertEqual(result["matched_count"], 2)
        self.assertEqual([row["mint"] for row in result["tokens"]], ["a", "b"])

    def test_rejects_unbounded_or_unknown_arguments(self) -> None:
        with self.assertRaises(QueryToolError):
            query_tokens([], {"limit": MAX_LIMIT + 1})
        with self.assertRaises(QueryToolError):
            query_tokens([], {"sort_by": "price_change_5m"})
        with self.assertRaises(QueryToolError):
            query_tokens([], {"sql": "SELECT * FROM mints"})


if __name__ == "__main__":
    unittest.main()
