from __future__ import annotations

import asyncio
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from observatory.rugcheck_analysis import (
    RUGCHECK_MAX_OUTPUT_TOKENS,
    RUGCHECK_REQUEST_TIMEOUT_SECONDS,
    analyze_rugcheck_report,
)

MINT = "11111111111111111111111111111111"
HOLDER = "22222222222222222222222222222222"


class RugCheckAnalystTests(unittest.TestCase):
    def test_rugcheck_analysis_uses_one_strong_request_with_projected_evidence(self) -> None:
        captured: list[dict[str, object]] = []
        client_options: list[dict[str, object]] = []
        evidence = {
            "source": "rugcheck",
            "mint": MINT,
            "fetched_at": "2026-08-12T12:00:00+00:00",
            "report_bytes": 5000,
            "rough_report_tokens": 1250,
            "report": {
                "score": 123,
                "score_normalised": 42,
                "rugged": False,
                "risks": [{"name": "Mutable metadata", "level": "warn"}],
                "topHolders": [{"address": HOLDER, "pct": 10}],
                "knownAccounts": {
                    HOLDER: {"name": "Known holder", "type": "wallet"},
                    "33333333333333333333333333333333": {
                        "name": "Unrelated",
                        "type": "wallet",
                    },
                },
                "markets": [
                    {
                        "pubkey": "44444444444444444444444444444444",
                        "marketType": "orca",
                        "mintA": MINT,
                        "mintB": HOLDER,
                        "mintAAccount": {"supply": 123},
                        "liquidityAAccount": {"amount": 10},
                        "lp": {
                            "baseUSD": 100.0,
                            "quoteUSD": 200.0,
                            "lpLockedPct": 0,
                            "lpLockedUSD": 0,
                            "lpTotalSupply": 100,
                            "basePrice": 1.23,
                        },
                    }
                ],
            },
        }
        response_payload = {
            "choices": [
                {
                    "message": {
                        "content": "RugCheck reports mutable metadata; that is evidence, not a safety guarantee."
                    }
                }
            ]
        }

        class FakeResponse:
            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict[str, object]:
                return response_payload

        class FakeClient:
            async def __aenter__(self) -> "FakeClient":
                return self

            async def __aexit__(self, *_: object) -> None:
                return None

            async def post(self, url: str, **kwargs: object) -> FakeResponse:
                captured.append({"url": url, **kwargs})
                return FakeResponse()

        def fake_client(**kwargs: object) -> FakeClient:
            client_options.append(kwargs)
            return FakeClient()

        fake_httpx = SimpleNamespace(
            AsyncClient=fake_client,
            HTTPStatusError=type("HTTPStatusError", (Exception,), {}),
            RequestError=type("RequestError", (Exception,), {}),
        )

        with patch.dict(sys.modules, {"httpx": fake_httpx}):
            result = asyncio.run(
                analyze_rugcheck_report(
                    api_key="secret",
                    model="mistral-large-latest",
                    token={
                        "mint": MINT,
                        "name": "Example",
                        "symbol": "EX",
                        "launchpad": "pump.fun",
                    },
                    question="What are the main safety risks?",
                    evidence=evidence,
                )
            )

        self.assertEqual(len(captured), 1)
        self.assertEqual(client_options[0]["timeout"], RUGCHECK_REQUEST_TIMEOUT_SECONDS)
        request = captured[0]["json"]
        self.assertEqual(request["model"], "mistral-large-latest")
        self.assertEqual(request["max_tokens"], RUGCHECK_MAX_OUTPUT_TOKENS)
        self.assertNotIn("tools", request)
        system = request["messages"][0]["content"]
        self.assertIn("external provider", system)
        self.assertIn("transport projection", system)
        self.assertIn("omitted account-level fields", system)

        user_message = request["messages"][1]["content"]
        context_text = user_message.split("RugCheck external evidence JSON:\n", 1)[1]
        delivered = json.loads(context_text)
        self.assertEqual(delivered["projection"]["type"], "rugcheck_analysis_v1")
        self.assertEqual(delivered["projection"]["raw_report_bytes"], 5000)
        self.assertNotIn("mintAAccount", delivered["report"]["markets"][0])
        self.assertNotIn("liquidityAAccount", delivered["report"]["markets"][0])
        self.assertEqual(
            list(delivered["report"]["knownAccounts"]),
            [HOLDER],
        )

        self.assertEqual(result["scope"], "rugcheck")
        self.assertEqual(result["evidence"]["source"], "rugcheck")
        self.assertEqual(result["evidence"]["mint"], MINT)
        self.assertEqual(result["evidence"]["raw_report_bytes"], 5000)
        self.assertGreater(result["evidence"]["analysis_rough_tokens"], 0)
        self.assertEqual(result["evidence"]["markets_total"], 1)
        self.assertEqual(result["evidence"]["known_accounts_total"], 2)
        self.assertEqual(result["evidence"]["known_accounts_retained"], 1)


if __name__ == "__main__":
    unittest.main()
