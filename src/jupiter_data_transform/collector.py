from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from typing import Protocol

from .models import FetchedToken

LOGGER = logging.getLogger(__name__)


class TokenClient(Protocol):
    async def fetch_tokens(self, mints: Sequence[str]) -> list[FetchedToken]: ...


class TokenRepository(Protocol):
    async def store(self, fetched: FetchedToken) -> int: ...


class Collector:
    def __init__(self, client: TokenClient, repository: TokenRepository) -> None:
        self._client = client
        self._repository = repository

    async def collect_once(self, mints: Sequence[str]) -> int:
        fetched_tokens = await self._client.fetch_tokens(mints)
        for fetched in fetched_tokens:
            await self._repository.store(fetched)

        LOGGER.info(
            "collection_completed requested=%d received=%d",
            len(set(mints)),
            len(fetched_tokens),
        )
        return len(fetched_tokens)

    async def run(self, mints: Sequence[str], interval_seconds: float) -> None:
        while True:
            started = asyncio.get_running_loop().time()
            try:
                await self.collect_once(mints)
            except Exception:
                LOGGER.exception("collection_failed")

            elapsed = asyncio.get_running_loop().time() - started
            await asyncio.sleep(max(0.0, interval_seconds - elapsed))
