from __future__ import annotations

import asyncio

from ..config import Settings
from ..repository import MintRepository
from .batch_cursor import BatchCursor
from .key_lane import key_lane
from .mint_cache import MintCache
from .write_queue import WriteQueue


async def refresh_system(settings: Settings, repository: MintRepository, priority: int = 1) -> None:
    cache = MintCache(repository, priority=priority)
    cursor = BatchCursor(cache)
    write_queue = WriteQueue(repository)

    lanes = [
        key_lane(
            api_key=key,
            label=f"lane{i}",
            cursor=cursor,
            settings=settings,
            write_queue=write_queue,
            seconds_per_key=settings.jupiter_seconds_per_key,
        )
        for i, key in enumerate(settings.jupiter_search_api_keys)
    ]

    await asyncio.gather(cache.run(), write_queue.run(), *lanes)