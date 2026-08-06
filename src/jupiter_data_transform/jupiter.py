from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import httpx

from .models import FetchedToken

MAX_MINTS_PER_SEARCH = 100


class JupiterResponseError(RuntimeError):
    """Raised when Jupiter returns a successful HTTP response with an invalid body."""


class JupiterClient:
    def __init__(
        self,
        *,
        api_keys: Sequence[str],
        base_url: str = "https://api.jup.ag",
        timeout_seconds: float = 20.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        cleaned_keys = tuple(key.strip() for key in api_keys if key.strip())
        if not cleaned_keys:
            raise ValueError("at least one Jupiter API key is required")

        self._api_keys = cleaned_keys
        self._next_key_index = 0
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout_seconds,
        )

    async def __aenter__(self) -> JupiterClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    def _next_api_key(self) -> str:
        key = self._api_keys[self._next_key_index]
        self._next_key_index = (self._next_key_index + 1) % len(self._api_keys)
        return key

    async def fetch_tokens(self, mints: Sequence[str]) -> list[FetchedToken]:
        unique_mints = list(dict.fromkeys(mint.strip() for mint in mints if mint.strip()))
        fetched: list[FetchedToken] = []

        for start in range(0, len(unique_mints), MAX_MINTS_PER_SEARCH):
            batch = unique_mints[start : start + MAX_MINTS_PER_SEARCH]
            fetched.extend(await self._fetch_batch(batch))

        return fetched

    async def _fetch_batch(self, mints: Sequence[str]) -> list[FetchedToken]:
        response = await self._client.get(
            "/tokens/v2/search",
            params={"query": ",".join(mints)},
            headers={"x-api-key": self._next_api_key()},
        )
        response.raise_for_status()

        body: Any = response.json()
        if not isinstance(body, list):
            raise JupiterResponseError("Tokens V2 search response must be a JSON array")

        request_id = uuid4()
        received_at = datetime.now(timezone.utc)
        result: list[FetchedToken] = []
        for item in body:
            if not isinstance(item, dict) or not isinstance(item.get("id"), str):
                raise JupiterResponseError("each token response must be an object with string field 'id'")
            result.append(
                FetchedToken(
                    request_id=request_id,
                    received_at=received_at,
                    payload=item,
                )
            )
        return result
