from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from observatory.mistral import AnalystError, post_json


class FakeHTTPStatusError(Exception):
    def __init__(self, response: object) -> None:
        super().__init__("http status error")
        self.response = response


class FakeRequestError(Exception):
    pass


class FakeResponse:
    def __init__(self, status_code: int, payload: object) -> None:
        self.status_code = status_code
        self._payload = payload

    def raise_for_status(self) -> None:
        raise FakeHTTPStatusError(self)

    def json(self) -> object:
        if isinstance(self._payload, ValueError):
            raise self._payload
        return self._payload


class FakeClient:
    def __init__(self, response: FakeResponse) -> None:
        self._response = response

    async def post(self, *_: object, **__: object) -> FakeResponse:
        return self._response


FAKE_HTTPX = SimpleNamespace(
    HTTPStatusError=FakeHTTPStatusError,
    RequestError=FakeRequestError,
)


class MistralErrorTests(unittest.TestCase):
    def _error(self, payload: object, api_key: str = "secret-key") -> str:
        with self.assertRaises(AnalystError) as raised:
            asyncio.run(
                post_json(
                    client=FakeClient(FakeResponse(403, payload)),
                    httpx=FAKE_HTTPX,
                    url="https://api.mistral.ai/v1/chat/completions",
                    api_key=api_key,
                    request={"model": "example"},
                )
            )
        return str(raised.exception)

    def test_preserves_safe_provider_error_fields(self) -> None:
        message = self._error(
            {
                "code": "permission_denied",
                "type": "forbidden",
                "param": "tools",
                "message": "Web search is unavailable for this workspace.",
                "request_dump": {"prompt": "must not leak"},
            }
        )

        self.assertIn("status 403", message)
        self.assertIn("code=permission_denied", message)
        self.assertIn("type=forbidden", message)
        self.assertIn("param=tools", message)
        self.assertIn("message=Web search is unavailable", message)
        self.assertNotIn("request_dump", message)
        self.assertNotIn("must not leak", message)

    def test_supports_nested_detail_and_redacts_api_key(self) -> None:
        message = self._error(
            {
                "detail": {
                    "code": "guardrail_block",
                    "message": "blocked for secret-key",
                }
            }
        )

        self.assertIn("code=guardrail_block", message)
        self.assertIn("message=blocked for [redacted]", message)
        self.assertNotIn("secret-key", message)

    def test_scalar_detail_is_bounded_diagnostic_message(self) -> None:
        message = self._error({"detail": "Forbidden by workspace policy"})
        self.assertEqual(
            message,
            "Mistral request failed with status 403: "
            "message=Forbidden by workspace policy",
        )

    def test_unstructured_error_keeps_status_only(self) -> None:
        message = self._error(ValueError("not json"))
        self.assertEqual(message, "Mistral request failed with status 403")


if __name__ == "__main__":
    unittest.main()
