from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from observatory.rugcheck_projection import project_rugcheck_evidence

MINT = "11111111111111111111111111111111"
HOLDER = "22222222222222222222222222222222"
MARKET = "33333333333333333333333333333333"
UNUSED = "44444444444444444444444444444444"
CREATOR = "55555555555555555555555555555555"


class RugCheckProjectionTests(unittest.TestCase):
    def test_projection_sends_metadata_not_wallet_or_market_rows(self) -> None:
        evidence = {
            "source": "rugcheck",
            "mint": MINT,
            "fetched_at": "2026-08-12T12:00:00+00:00",
            "report_bytes": 9999,
            "rough_report_tokens": 2500,
            "report": {
                "mint": MINT,
                "score": 7,
                "score_normalised": 14,
                "rugged": False,
                "risks": [
                    {
                        "name": "Mutable metadata",
                        "level": "warn",
                        "value": "true",
                        "score": 100,
                        "description": "Metadata can change",
                    }
                ],
                "creator": CREATOR,
                "creatorTokens": [{"mint": UNUSED}],
                "totalHolders": 100,
                "graphInsidersDetected": 1,
                "tokenMeta": {
                    "mutable": True,
                    "updateAuthority": CREATOR,
                    "uri": "https://example.invalid/metadata.json",
                },
                "token": {
                    "mintAuthority": CREATOR,
                    "freezeAuthority": None,
                    "supply": 1_000_000,
                },
                "topHolders": [
                    {
                        "address": HOLDER,
                        "owner": CREATOR,
                        "pct": 12.5,
                        "insider": True,
                        "amount": 125_000,
                    },
                    {
                        "address": UNUSED,
                        "owner": UNUSED,
                        "pct": 5.0,
                        "insider": False,
                    },
                ],
                "markets": [
                    {
                        "pubkey": MARKET,
                        "marketType": "orca",
                        "mintA": MINT,
                        "mintB": HOLDER,
                        "liquidityAAccount": {"amount": 10},
                        "liquidityBAccount": {"amount": 20},
                        "lp": {
                            "baseUSD": 100.0,
                            "quoteUSD": 300.0,
                            "lpLockedPct": 5.0,
                        },
                    },
                    {
                        "pubkey": UNUSED,
                        "marketType": "orca",
                        "mintA": MINT,
                        "mintB": HOLDER,
                        "lp": {
                            "baseUSD": 25.0,
                            "quoteUSD": 75.0,
                            "lpLockedPct": 0.0,
                        },
                    },
                ],
                "knownAccounts": {
                    HOLDER: {"name": "Known AMM pool", "type": "AMM"},
                    MARKET: {"name": "Another AMM pool", "type": "AMM"},
                    UNUSED: {"name": "Unrelated", "type": "wallet"},
                },
                "totalMarketLiquidity": 500.0,
                "totalStableLiquidity": 300.0,
                "totalLPProviders": 2,
                "lockers": {"a": {}, "b": {}},
                "lockerScanStatus": "done",
            },
        }

        projected = project_rugcheck_evidence(evidence)
        summary = projected["summary"]

        self.assertEqual(summary["provider_risk"]["score"], 7)
        self.assertEqual(summary["provider_risk"]["score_normalised"], 14)
        self.assertEqual(summary["provider_risk"]["risks"][0]["name"], "Mutable metadata")

        control = summary["token_control"]
        self.assertTrue(control["mint_authority_present"])
        self.assertFalse(control["freeze_authority_present"])
        self.assertTrue(control["metadata_mutable"])
        self.assertTrue(control["metadata_update_authority_present"])

        ownership = summary["ownership"]
        self.assertEqual(ownership["total_holders"], 100)
        self.assertEqual(ownership["top1_pct"], 12.5)
        self.assertEqual(ownership["top5_pct"], 17.5)
        self.assertEqual(ownership["insiders_in_top_holders"], 1)
        self.assertEqual(ownership["insider_pct_in_top_holders"], 12.5)
        self.assertEqual(ownership["creator_in_top_holders_pct"], 12.5)
        self.assertEqual(ownership["creator_tokens_count"], 1)
        self.assertEqual(ownership["known_top_holder_types"], {"AMM": 1, "wallet": 1})

        liquidity = summary["liquidity"]
        self.assertEqual(liquidity["market_count"], 2)
        self.assertEqual(liquidity["market_types"], {"orca": 2})
        self.assertEqual(liquidity["largest_market_liquidity_usd"], 400.0)
        self.assertEqual(liquidity["largest_market_share_pct"], 80.0)
        self.assertEqual(liquidity["markets_with_positive_lp_lock"], 1)
        self.assertEqual(liquidity["markets_with_zero_lp_lock"], 1)
        self.assertEqual(liquidity["locker_count"], 2)

        serialized = json.dumps(projected, ensure_ascii=False)
        self.assertNotIn(HOLDER, serialized)
        self.assertNotIn(MARKET, serialized)
        self.assertNotIn(UNUSED, serialized)
        self.assertNotIn(CREATOR, serialized)
        self.assertNotIn("liquidityAAccount", serialized)
        self.assertNotIn("topHolders", serialized)
        self.assertNotIn("knownAccounts", serialized)

        meta = projected["projection"]
        self.assertEqual(meta["type"], "rugcheck_analysis_v2")
        self.assertEqual(meta["raw_report_bytes"], 9999)
        self.assertEqual(meta["markets_observed"], 2)
        self.assertEqual(meta["top_holders_observed"], 2)
        self.assertEqual(meta["known_accounts_observed"], 3)
        self.assertEqual(meta["wallet_addresses_sent_to_llm"], 0)
        self.assertLess(meta["projected_report_bytes"], 9999)

    def test_missing_provider_sections_remain_unknown(self) -> None:
        projected = project_rugcheck_evidence(
            {
                "source": "rugcheck",
                "mint": MINT,
                "fetched_at": "2026-08-12T12:00:00+00:00",
                "report": {"score": 5},
            }
        )
        summary = projected["summary"]

        self.assertIsNone(summary["token_control"]["mint_authority_present"])
        self.assertIsNone(summary["token_control"]["freeze_authority_present"])
        self.assertIsNone(summary["token_control"]["metadata_update_authority_present"])
        self.assertIsNone(summary["ownership"]["top_holders_reported"])
        self.assertIsNone(summary["ownership"]["insiders_in_top_holders"])
        self.assertIsNone(summary["liquidity"]["market_count"])
        self.assertIsNone(summary["liquidity"]["markets_with_zero_lp_lock"])
        self.assertIsNone(summary["provider_risk"]["risks"])


if __name__ == "__main__":
    unittest.main()
