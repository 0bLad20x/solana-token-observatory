from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from observatory.evidence.rugcheck import (
    RUGCHECK_TIMEOUT_SECONDS,
    RugCheckError,
    get_token_report,
)

MINT = "11111111111111111111111111111111"


class RugCheckEvidenceTests(unittest.TestCase):
    def test_fetch_wraps_exact_provider_report_with_provenance(self) -> None:
        captured: list[dict[str, object]] = []
        client_options: list[dict[str, object]] = []

        class FakeResponse:
            status_code = 200

            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict[str, object]:
                return {"mint": MINT, "score": 7, "risks": []}

        class FakeClient:
            async def __aenter__(self) -> "FakeClient":
                return self

            async def __aexit__(self, *_: object) -> None:
                return None

            async def get(self, url: str, **kwargs: object) -> FakeResponse:
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
            evidence = asyncio.run(get_token_report(MINT))

        self.assertEqual(client_options[0]["timeout"], RUGCHECK_TIMEOUT_SECONDS)
        self.assertTrue(captured[0]["url"].endswith(f"/{MINT}/report"))
        self.assertEqual(evidence["source"], "rugcheck")
        self.assertEqual(evidence["mint"], MINT)
        self.assertEqual(evidence["report"]["score"], 7)
        self.assertIn("fetched_at", evidence)

    def test_invalid_mint_fails_before_provider_request(self) -> None:
        with self.assertRaises(RugCheckError) as raised:
            asyncio.run(get_token_report("not-a-mint"))
        self.assertEqual(raised.exception.status_code, 422)


if __name__ == "__main__":
    unittest.main()
