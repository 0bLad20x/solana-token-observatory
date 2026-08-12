from __future__ import annotations

import asyncio
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from observatory.analyst import TEMPORAL_MAX_OUTPUT_TOKENS, analyze_temporal_token
from observatory.tools import (
    TemporalToolError,
    temporal_context_tool,
    validate_temporal_context_arguments,
)


MINT = "11111111111111111111111111111111"


class TemporalAnalystTests(unittest.TestCase):
    def test_tool_schema_and_validation_are_bound_to_selected_mint(self) -> None:
        tool = temporal_context_tool(MINT)
        mint_schema = tool["function"]["parameters"]["properties"]["mint"]
        self.assertEqual(mint_schema["enum"], [MINT])
        self.assertEqual(
            validate_temporal_context_arguments({"mint": MINT}, MINT),
            MINT,
        )
        with self.assertRaises(TemporalToolError):
            validate_temporal_context_arguments({"mint": "other"}, MINT)
        with self.assertRaises(TemporalToolError):
            validate_temporal_context_arguments(
                {"mint": MINT, "hours": 24},
                MINT,
            )

    def test_temporal_analysis_sends_summary_only_and_returns_evidence_meta(self) -> None:
        captured: list[dict[str, object]] = []
        responses = [
            {
                "choices": [
                    {
                        "message": {
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "call-temporal",
                                    "type": "function",
                                    "function": {
                                        "name": "get_token_temporal_context",
                                        "arguments": json.dumps({"mint": MINT}),
                                    },
                                }
                            ],
                        }
                    }
                ]
            },
            {
                "choices": [
                    {
                        "message": {
                            "content": (
                                "Valuation improved across the observed window, while the "
                                "available summary is insufficient for exact turning points."
                            )
                        }
                    }
                ]
            },
        ]
        context = {
            "token": {"mint": MINT, "name": "Example", "symbol": "EX"},
            "summary": {
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
            },
        }

        class FakeResponse:
            def __init__(self, payload: dict[str, object]) -> None:
                self.payload = payload

            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict[str, object]:
                return self.payload

        class FakeClient:
            async def __aenter__(self) -> "FakeClient":
                return self

            async def __aexit__(self, *_: object) -> None:
                return None

            async def post(self, url: str, **kwargs: object) -> FakeResponse:
                captured.append({"url": url, **kwargs})
                return FakeResponse(responses.pop(0))

        fake_httpx = SimpleNamespace(
            AsyncClient=lambda **_: FakeClient(),
            HTTPStatusError=type("HTTPStatusError", (Exception,), {}),
            RequestError=type("RequestError", (Exception,), {}),
        )

        loaded: list[str] = []

        def load_context(mint: str) -> dict[str, object]:
            loaded.append(mint)
            return context

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
                    context_loader=load_context,
                )
            )

        self.assertEqual(loaded, [MINT])
        first_request = captured[0]["json"]
        self.assertEqual(
            first_request["tools"][0]["function"]["name"],
            "get_token_temporal_context",
        )
        self.assertEqual(first_request["tool_choice"], "required")
        system_prompt = first_request["messages"][0]["content"]
        self.assertIn("It does NOT return time buckets", system_prompt)
        self.assertIn("cross-metric confirmation or divergence", system_prompt)
        self.assertIn("Do NOT claim phases", system_prompt)

        final_request = captured[1]["json"]
        self.assertEqual(final_request["max_tokens"], TEMPORAL_MAX_OUTPUT_TOKENS)
        tool_message = final_request["messages"][-1]
        delivered = json.loads(tool_message["content"])
        self.assertEqual(delivered, context)
        self.assertNotIn("temporal_history", delivered)
        self.assertEqual(result["scope"], "temporal")
        self.assertEqual(result["tool"]["mint"], MINT)
        self.assertEqual(result["tool"]["evidence"], "summary_only")
        self.assertGreater(result["tool"]["rough_input_tokens"], 0)


if __name__ == "__main__":
    unittest.main()
