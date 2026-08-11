from __future__ import annotations

import asyncio
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


if __name__ == "__main__":
    unittest.main()
