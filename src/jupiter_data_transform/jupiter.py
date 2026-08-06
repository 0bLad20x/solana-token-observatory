from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx

MAX_MINTS_PER_SEARCH = 100


class JupiterResponseError(RuntimeError):
    """Raised when Jupiter returns HTTP success with an invalid response body."""


@dataclass(frozen=True, slots=True)
class FetchedToken:
    received_at: datetime
    payload: dict[str, Any]

    def __post_init__(self) -> None:
        if self.received_at.tzinfo is None:
            raise ValueError("received_at must be timezone-aware")


class JupiterClient:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.jup.ag",
        timeout_seconds: float = 20.0,
        client: httpx.Client | None = None,
    ) -> None:
        if not api_key.strip():
            raise ValueError("api_key must not be empty")

        self._api_key = api_key.strip()
        self._owns_client = client is None
        self._client = client or httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=timeout_seconds,
        )

    def __enter__(self) -> JupiterClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def fetch_tokens(self, mints: Sequence[str]) -> list[FetchedToken]:
        unique_mints = list(dict.fromkeys(mint.strip() for mint in mints if mint.strip()))
        fetched: list[FetchedToken] = []

        for start in range(0, len(unique_mints), MAX_MINTS_PER_SEARCH):
            batch = unique_mints[start : start + MAX_MINTS_PER_SEARCH]
            fetched.extend(self._fetch_batch(batch))

        return fetched

    def _fetch_batch(self, mints: Sequence[str]) -> list[FetchedToken]:
        response = self._client.get(
            "/tokens/v2/search",
            params={"query": ",".join(mints)},
            headers={"x-api-key": self._api_key},
        )
        received_at = datetime.now(timezone.utc)
        response.raise_for_status()

        body: Any = response.json()
        if not isinstance(body, list):
            raise JupiterResponseError("Tokens V2 search response must be a JSON array")

        result: list[FetchedToken] = []
        for item in body:
            mint = item.get("id") if isinstance(item, dict) else None
            if not isinstance(mint, str) or not mint.strip():
                raise JupiterResponseError("each token must be an object with a non-empty string id")
            result.append(FetchedToken(received_at=received_at, payload=item))
        return result
