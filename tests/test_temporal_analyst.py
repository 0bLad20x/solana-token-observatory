from __future__ import annotations

import asyncio
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from observatory.analyst import (
    TEMPORAL_MAX_OUTPUT_TOKENS,
    TEMPORAL_REQUEST_TIMEOUT_SECONDS,
    analyze_temporal_token,
)

MINT = "11111111111111111111111111111111"


class TemporalAnalystTests(unittest.TestCase):
    def test_temporal_analysis_loads_selected_summary_and_uses_one_mistral_request(self) -> None:
        captured: list[dict[str, object]] = []
        client_options: list[dict[str, object]] = []
        summary = {
            "history": {
                "hours": 8.0,
                "observations": 123,
                "from": "2026-08-12T00:00:00+00:00",
                "to": "2026-08-12T08:00:00+00:00",
            },
            "market_cap": {
                "start": 10,
                "current": 20,
                "min": 8,
                "max": 22,
                "change_pct": 100,
            },
        }
        response_payload = {
            "choices": [
                {
                    "message": {
                        "content": (
                            "Valuation improved over the observed window, but the Summary "
                            "does not support claims about exact turning points."
                        )
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

        loaded: list[str] = []

        def load_summary(mint: str) -> dict[str, object]:
            loaded.append(mint)
            return summary

        with patch.dict(sys.modules, {"httpx": fake_httpx}):
            result = asyncio.run(
                analyze_temporal_token(
                    api_key="secret",
                    model="mistral-small-latest",
                    token={
                        "mint": MINT,
                        "name": "Example",
                        "symbol": "EX",
                        "launchpad": "pump.fun",
                    },
                    question="How does this token look?",
                    summary_loader=load_summary,
                )
            )

        self.assertEqual(loaded, [MINT])
        self.assertEqual(len(captured), 1)
        self.assertEqual(client_options[0]["timeout"], TEMPORAL_REQUEST_TIMEOUT_SECONDS)

        request = captured[0]["json"]
        self.assertNotIn("tools", request)
        self.assertEqual(request["max_tokens"], TEMPORAL_MAX_OUTPUT_TOKENS)
        system_prompt = request["messages"][0]["content"]
        self.assertIn("no raw history or time buckets", system_prompt)
        self.assertIn("does not prove continuous coverage", system_prompt)
        self.assertIn("never an ATH", system_prompt)
        self.assertIn("Do NOT claim linear, parabolic", system_prompt)

        user_message = request["messages"][1]["content"]
        self.assertIn("How does this token look?", user_message)
        context_text = user_message.split("Deterministic temporal evidence JSON:\n", 1)[1]
        delivered = json.loads(context_text)
        self.assertEqual(delivered["summary"], summary)
        self.assertEqual(delivered["token"]["mint"], MINT)
        self.assertEqual(delivered["token"]["symbol"], "EX")
        self.assertNotIn("temporal_history", delivered)

        self.assertEqual(result["scope"], "temporal")
        self.assertEqual(result["evidence"]["type"], "temporal_summary")
        self.assertEqual(result["evidence"]["mint"], MINT)
        self.assertGreater(result["evidence"]["rough_summary_tokens"], 0)


if __name__ == "__main__":
    unittest.main()
