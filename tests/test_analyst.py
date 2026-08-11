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
    AnalystError,
    _parse_response,
    _prompt,
    query_current_tokens,
    research_token,
    validate_search_mode,
)


class AnalystTests(unittest.TestCase):
    def test_search_modes_are_explicit(self) -> None:
        self.assertEqual(validate_search_mode("web_search"), "web_search")
        self.assertEqual(validate_search_mode(" WEB_SEARCH_PREMIUM "), "web_search_premium")
        with self.assertRaises(ValueError):
            validate_search_mode("auto")

    def test_prompt_grounds_research_in_exact_mint(self) -> None:
        prompt = _prompt(
            {
                "mint": "ExactMint1111111111111111111111111111111",
                "name": "Example",
                "symbol": "EX",
                "launchpad": "pump.fun",
            },
            "Who is behind it?",
        )
        self.assertIn("ExactMint1111111111111111111111111111111", prompt)
        self.assertIn("primary identity", prompt)
        self.assertIn("Who is behind it?", prompt)

    def test_response_requires_real_web_search_execution(self) -> None:
        with self.assertRaisesRegex(AnalystError, "did not execute"):
            _parse_response(
                {"outputs": [{"type": "message.output", "content": "unsupported answer"}]},
                "web_search",
            )

    def test_response_returns_answer_and_safe_unique_sources(self) -> None:
        result = _parse_response(
            {
                "outputs": [
                    {"type": "tool.execution", "name": "web_search"},
                    {
                        "type": "message.output",
                        "content": [
                            {"type": "text", "text": "Evidence found."},
                            {
                                "type": "tool_reference",
                                "title": "Project page",
                                "url": "https://example.com/token",
                            },
                            {
                                "type": "tool_reference",
                                "title": "Duplicate",
                                "url": "https://example.com/token",
                            },
                            {
                                "type": "tool_reference",
                                "title": "Unsafe",
                                "url": "javascript:alert(1)",
                            },
                        ],
                    },
                ]
            },
            "web_search",
        )
        self.assertEqual(result["answer"], "Evidence found.")
        self.assertEqual(
            result["sources"],
            [{"title": "Project page", "url": "https://example.com/token"}],
        )
        self.assertEqual(result["search_mode"], "web_search")

    def test_research_uses_configured_premium_tool(self) -> None:
        captured: dict[str, object] = {}

        class FakeResponse:
            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict[str, object]:
                return {
                    "outputs": [
                        {"type": "tool.execution", "name": "web_search_premium"},
                        {"type": "message.output", "content": "No reliable evidence found."},
                    ]
                }

        class FakeClient:
            async def __aenter__(self) -> "FakeClient":
                return self

            async def __aexit__(self, *_: object) -> None:
                return None

            async def post(self, url: str, **kwargs: object) -> FakeResponse:
                captured.update({"url": url, **kwargs})
                return FakeResponse()

        fake_httpx = SimpleNamespace(
            AsyncClient=lambda **_: FakeClient(),
            HTTPStatusError=type("HTTPStatusError", (Exception,), {}),
            RequestError=type("RequestError", (Exception,), {}),
        )
        with patch.dict(sys.modules, {"httpx": fake_httpx}):
            result = asyncio.run(
                research_token(
                    api_key="secret",
                    model="mistral-small-latest",
                    search_mode="web_search_premium",
                    token={
                        "mint": "ExactMint1111111111111111111111111111111",
                        "name": "Example",
                        "symbol": "EX",
                        "launchpad": "pump.fun",
                    },
                    question="What is known?",
                )
            )

        request = captured["json"]
        self.assertIsInstance(request, dict)
        self.assertEqual(request["tools"], [{"type": "web_search_premium"}])
        self.assertIn("ExactMint1111111111111111111111111111111", request["inputs"][0]["content"])
        self.assertEqual(result["search_mode"], "web_search_premium")

    def test_current_data_executes_one_bounded_query_tokens_call(self) -> None:
        captured: list[dict[str, object]] = []
        responses = [
            {
                "choices": [
                    {
                        "message": {
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "call-1",
                                    "type": "function",
                                    "function": {
                                        "name": "query_tokens",
                                        "arguments": json.dumps(
                                            {
                                                "sort_by": "market_cap",
                                                "sort_order": "desc",
                                                "limit": 5,
                                            }
                                        ),
                                    },
                                }
                            ],
                        }
                    }
                ]
            },
            {
                "choices": [
                    {"message": {"content": "AAA has the highest current market cap."}}
                ]
            },
        ]

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
        tokens = [
            {
                "mint": "mint-a",
                "name": "AAA",
                "symbol": "AAA",
                "launchpad": "pump.fun",
                "tracking_enabled": True,
                "market_cap": 100,
                "liquidity": None,
                "holders": None,
                "trades_5m": None,
                "traders_5m": None,
                "volume_5m": None,
                "age_seconds": None,
                "change_age_seconds": None,
            },
            {
                "mint": "mint-b",
                "name": "BBB",
                "symbol": "BBB",
                "launchpad": "met-dbc",
                "tracking_enabled": True,
                "market_cap": 90,
                "liquidity": None,
                "holders": None,
                "trades_5m": None,
                "traders_5m": None,
                "volume_5m": None,
                "age_seconds": None,
                "change_age_seconds": None,
            },
            {
                "mint": "mint-c",
                "name": "CCC",
                "symbol": "CCC",
                "launchpad": "letsbonk.fun",
                "tracking_enabled": True,
                "market_cap": 80,
                "liquidity": None,
                "holders": None,
                "trades_5m": None,
                "traders_5m": None,
                "volume_5m": None,
                "age_seconds": None,
                "change_age_seconds": None,
            },
        ]
        with patch.dict(sys.modules, {"httpx": fake_httpx}):
            result = asyncio.run(
                query_current_tokens(
                    api_key="secret",
                    model="mistral-small-latest",
                    tokens=tokens,
                    question="Which five tokens have the highest market cap?",
                )
            )

        first_request = captured[0]["json"]
        self.assertEqual(first_request["tools"][0]["function"]["name"], "query_tokens")
        system_prompt = first_request["messages"][0]["content"]
        self.assertIn("met-dbc", system_prompt)
        self.assertIn("letsbonk.fun", system_prompt)
        self.assertIn("Liquidität", system_prompt)
        launchpad_schema = first_request["tools"][0]["function"]["parameters"][
            "properties"
        ]["launchpad"]
        self.assertEqual(
            launchpad_schema["enum"],
            ["letsbonk.fun", "met-dbc", "pump.fun"],
        )
        self.assertNotIn(
            "price_change_5m",
            first_request["tools"][0]["function"]["parameters"]["properties"][
                "sort_by"
            ]["enum"],
        )
        tool_message = captured[1]["json"]["messages"][-1]
        self.assertEqual(tool_message["role"], "tool")
        self.assertEqual(json.loads(tool_message["content"])["returned_count"], 3)
        self.assertEqual(result["tool"]["returned_count"], 3)
        self.assertEqual(result["scope"], "current_data")

    def test_current_data_does_not_trust_an_answer_without_tool_use(self) -> None:
        class FakeResponse:
            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict[str, object]:
                return {
                    "choices": [
                        {"message": {"content": "I invented a five-minute price change."}}
                    ]
                }

        class FakeClient:
            async def __aenter__(self) -> "FakeClient":
                return self

            async def __aexit__(self, *_: object) -> None:
                return None

            async def post(self, *_: object, **__: object) -> FakeResponse:
                return FakeResponse()

        fake_httpx = SimpleNamespace(
            AsyncClient=lambda **_: FakeClient(),
            HTTPStatusError=type("HTTPStatusError", (Exception,), {}),
            RequestError=type("RequestError", (Exception,), {}),
        )
        with patch.dict(sys.modules, {"httpx": fake_httpx}):
            result = asyncio.run(
                query_current_tokens(
                    api_key="secret",
                    model="mistral-small-latest",
                    tokens=[
                        {
                            "mint": "mint-a",
                            "launchpad": "pump.fun",
                            "tracking_enabled": True,
                        }
                    ],
                    question="Which tokens had the largest price increase in five minutes?",
                )
            )

        self.assertIsNone(result["tool"])
        self.assertNotIn("invented", result["answer"])
        self.assertIn("cannot be mapped", result["answer"])
        self.assertIn(
            "liquidity",
            [field["key"] for field in result["capabilities"]["fields"]],
        )
        self.assertEqual(
            result["capabilities"]["launchpads"],
            [{"value": "pump.fun", "active_tokens": 1}],
        )


if __name__ == "__main__":
    unittest.main()
