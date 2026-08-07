from __future__ import annotations

import asyncio
import itertools
import time
import traceback
from datetime import datetime, timezone

import httpx

from config import Settings
from repository import MintRepository

BATCH_SIZE = 100
CACHE_REFRESH_SECONDS = 5.0
FLUSH_INTERVAL_SECONDS = 2.0
FLUSH_SIZE_THRESHOLD = 500
QUEUE_MAX_SIZE = 10_000


class MintCache:
    def __init__(self, repository: MintRepository, priority: int) -> None:
        self._repository = repository
        self._priority = priority
        self._mints: list[str] = []

    def snapshot(self) -> list[str]:
        return self._mints

    async def run(self) -> None:
        while True:
            try:
                self._mints = await asyncio.to_thread(
                    self._repository.load_active_mints_by_priority, self._priority
                )
            except Exception:
                traceback.print_exc()
            await asyncio.sleep(CACHE_REFRESH_SECONDS)


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
            batches = [current[i:i + BATCH_SIZE] for i in range(0, len(current), BATCH_SIZE)]
            if batches != self._batches:
                self._batches = batches
                self._cycle = itertools.cycle(self._batches)
            return next(self._cycle)


class WriteQueue:
    def __init__(self, repository: MintRepository) -> None:
        self._repository = repository
        self._queue: asyncio.Queue[tuple[list[dict], datetime]] = asyncio.Queue(maxsize=QUEUE_MAX_SIZE)

    def submit(self, tokens: list[dict], observed_at: datetime) -> None:
        try:
            self._queue.put_nowait((tokens, observed_at))
        except asyncio.QueueFull:
            print(f"[write_queue] full qsize={self._queue.qsize()}")

    async def run(self) -> None:
        buffer: list[tuple[list[dict], datetime]] = []
        last_flush = time.monotonic()
        while True:
            timeout = max(0.0, FLUSH_INTERVAL_SECONDS - (time.monotonic() - last_flush))
            try:
                buffer.append(await asyncio.wait_for(self._queue.get(), timeout=timeout))
            except asyncio.TimeoutError:
                pass

            by_time = time.monotonic() - last_flush >= FLUSH_INTERVAL_SECONDS
            by_size = sum(len(tokens) for tokens, _ in buffer) >= FLUSH_SIZE_THRESHOLD

            if buffer and (by_time or by_size):
                all_tokens: list[dict] = []
                for tokens, observed_at in buffer:
                    for token in tokens:
                        token["_observed_at"] = observed_at
                        all_tokens.append(token)
                try:
                    summary = await asyncio.to_thread(self._repository.store_tokens_grouped, all_tokens)
                    print(
                        f"[write_queue] items={len(all_tokens)} "
                        f"new_mints={summary.new_mints} new_snapshots={summary.new_snapshots}"
                    )
                except Exception:
                    traceback.print_exc()
                buffer = []
                last_flush = time.monotonic()


async def key_lane(
    api_key: str,
    label: str,
    cursor: BatchCursor,
    settings: Settings,
    writer: WriteQueue,
) -> None:
    async with httpx.AsyncClient(
        base_url=settings.jupiter_base_url, timeout=settings.request_timeout_seconds
    ) as client:
        while True:
            started = time.monotonic()
            try:
                batch = await cursor.next_batch()
                if batch:
                    response = await client.get(
                        "/tokens/v2/search",
                        params={"query": ",".join(batch)},
                        headers={"x-api-key": api_key},
                    )
                    if response.status_code == 200:
                        tokens = response.json()
                        writer.submit(tokens, datetime.now(timezone.utc))
                        print(f"[{label}] requested={len(batch)} received={len(tokens)}")
                    else:
                        retry_after = response.headers.get("retry-after", "?")
                        print(
                            f"[{label}] FEHLER status={response.status_code} "
                            f"requested={len(batch)} retry_after={retry_after} "
                            f"body={response.text[:200]!r}"
                        )
            except Exception:
                traceback.print_exc()
            await asyncio.sleep(max(0.0, settings.jupiter_seconds_per_key - (time.monotonic() - started)))


async def refresh_system(settings: Settings, repository: MintRepository, priority: int = 1) -> None:
    cache = MintCache(repository, priority)
    cursor = BatchCursor(cache)
    writer = WriteQueue(repository)
    lanes = [
        key_lane(key, f"lane{i}", cursor, settings, writer)
        for i, key in enumerate(settings.jupiter_search_api_keys)
    ]
    await asyncio.gather(cache.run(), writer.run(), *lanes)