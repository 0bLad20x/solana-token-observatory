from __future__ import annotations

import asyncio
import itertools

from .mint_cache import MintCache

BATCH_SIZE = 100


class BatchCursor:
    def __init__(self, cache: MintCache) -> None:
        self._cache = cache
        self._lock = asyncio.Lock()
        self._batches: list[list[str]] = []
        self._cycle = iter(())

    async def next_batch(self) -> list[str]:
        async with self._lock:
            current = self._cache.snapshot()
            if not current:
                return []
            expected_batches = [
                current[i : i + BATCH_SIZE] for i in range(0, len(current), BATCH_SIZE)
            ]
            if expected_batches != self._batches:
                self._batches = expected_batches
                self._cycle = itertools.cycle(self._batches)
            return next(self._cycle)