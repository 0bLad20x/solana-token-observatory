from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from observatory.rugcheck_projection import project_rugcheck_evidence

MINT = "11111111111111111111111111111111"
HOLDER = "22222222222222222222222222222222"
MARKET = "33333333333333333333333333333333"
UNUSED = "44444444444444444444444444444444"


class RugCheckProjectionTests(unittest.TestCase):
    def test_projection_preserves_small_facts_and_compacts_market_account_state(self) -> None:
        evidence = {
            "source": "rugcheck",
            "mint": MINT,
            "fetched_at": "2026-08-12T12:00:00+00:00",
            "report_bytes": 9999,
            "rough_report_tokens": 2500,
            "report": {
                "mint": MINT,
                "score": 7,
                "risks": [{"name": "risk"}],
                "topHolders": [{"address": HOLDER, "pct": 12.5}],
                "markets": [
                    {
                        "pubkey": MARKET,
                        "marketType": "orca",
                        "mintA": MINT,
                        "mintB": HOLDER,
                        "liquidityA": "vault-a",
                        "liquidityB": "vault-b",
                        "mintAAccount": {"supply": 123},
                        "mintBAccount": {"supply": 456},
                        "mintLPAccount": {"supply": 789},
                        "liquidityAAccount": {"amount": 10},
                        "liquidityBAccount": {"amount": 20},
                        "lp": {
                            "baseUSD": 100.0,
                            "quoteUSD": 200.0,
                            "holders": None,
                            "lpLocked": 5,
                            "lpUnlocked": 95,
                            "lpLockedPct": 5.0,
                            "lpLockedUSD": 15.0,
                            "lpTotalSupply": 100,
                            "basePrice": 99.0,
                            "reserveSupply": 1000,
                        },
                    }
                ],
                "knownAccounts": {
                    HOLDER: {"name": "Known holder", "type": "wallet"},
                    MARKET: {"name": "AMM pool", "type": "AMM"},
                    UNUSED: {"name": "Unrelated", "type": "wallet"},
                },
            },
        }

        projected = project_rugcheck_evidence(evidence)
        report = projected["report"]

        self.assertEqual(report["score"], 7)
        self.assertEqual(report["risks"], [{"name": "risk"}])
        self.assertEqual(len(report["markets"]), 1)
        market = report["markets"][0]
        self.assertEqual(
            set(market),
            {"pubkey", "marketType", "mintA", "mintB", "lp"},
        )
        self.assertNotIn("mintAAccount", market)
        self.assertNotIn("liquidityAAccount", market)
        self.assertEqual(market["lp"]["baseUSD"], 100.0)
        self.assertEqual(market["lp"]["lpLockedPct"], 5.0)
        self.assertNotIn("basePrice", market["lp"])
        self.assertNotIn("reserveSupply", market["lp"])

        # HOLDER is referenced outside markets; MARKET and UNUSED are not retained merely
        # because they exist in the provider-wide registry or the market list.
        self.assertEqual(
            report["knownAccounts"],
            {HOLDER: {"name": "Known holder", "type": "wallet"}},
        )

        meta = projected["projection"]
        self.assertEqual(meta["type"], "rugcheck_analysis_v1")
        self.assertEqual(meta["raw_report_bytes"], 9999)
        self.assertEqual(meta["markets_total"], 1)
        self.assertEqual(meta["known_accounts_total"], 3)
        self.assertEqual(meta["known_accounts_retained"], 1)
        self.assertLess(meta["projected_report_bytes"], 9999)


if __name__ == "__main__":
    unittest.main()
