from __future__ import annotations

import asyncio
import time
import traceback
from collections import deque
from collections.abc import Sequence
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
        self._ready = asyncio.Event()

    def snapshot(self) -> list[str]:
        return self._mints

    async def wait_ready(self) -> None:
        await self._ready.wait()

    async def run(self) -> None:
        while True:
            try:
                self._mints = await asyncio.to_thread(
                    self._repository.load_active_mints_by_priority,
                    self._priority,
                )
                self._ready.set()
            except Exception:
                traceback.print_exc()
            await asyncio.sleep(CACHE_REFRESH_SECONDS)


class BatchCursor:
    """Round-robin over one priority population.

    No in-flight suppression and no global cadence. Every API key owns its own
    rate limit. If fewer than BATCH_SIZE mints are active, every request gets
    the complete population exactly once.
    """

    def __init__(self, cache: MintCache) -> None:
        self._cache = cache
        self._lock = asyncio.Lock()
        self._offset = 0

    async def wait_ready(self) -> None:
        await self._cache.wait_ready()

    async def next_batch(self) -> list[str]:
        async with self._lock:
            current = self._cache.snapshot()
            n = len(current)

            if n == 0:
                return []

            if n <= BATCH_SIZE:
                return current.copy()

            start = self._offset % n
            end = start + BATCH_SIZE

            if end <= n:
                batch = current[start:end]
            else:
                batch = current[start:] + current[: end - n]

            self._offset = (self._offset + BATCH_SIZE) % n
            return batch


class WriteQueue:
    def __init__(self, repository: MintRepository) -> None:
        self._repository = repository
        self._queue: asyncio.Queue[tuple[list[dict], datetime]] = asyncio.Queue(
            maxsize=QUEUE_MAX_SIZE
        )

    async def submit(self, tokens: list[dict], observed_at: datetime) -> None:
        await self._queue.put((tokens, observed_at))

    async def run(self) -> None:
        buffer = []
        buffered_items = 0
        last_flush = time.monotonic()

        while True:
            timeout = max(
                0.0,
                FLUSH_INTERVAL_SECONDS - (time.monotonic() - last_flush),
            )
            try:
                tokens, observed_at = await asyncio.wait_for(
                    self._queue.get(),
                    timeout=timeout,
                )
                buffer.append((tokens, observed_at))
                buffered_items += len(tokens)
            except asyncio.TimeoutError:
                pass

            by_time = time.monotonic() - last_flush >= FLUSH_INTERVAL_SECONDS
            by_size = buffered_items >= FLUSH_SIZE_THRESHOLD

            if buffer and (by_time or by_size):
                all_tokens = []
                for tokens, observed_at in buffer:
                    for token in tokens:
                        token["_observed_at"] = observed_at
                        all_tokens.append(token)

                try:
                    write_started = time.monotonic()
                    summary = await asyncio.to_thread(
                        self._repository.store_tokens_grouped,
                        all_tokens,
                    )
                    write_seconds = time.monotonic() - write_started

                    print(
                        f"[write_queue] items={len(all_tokens)} "
                        f"new_mints={summary.new_mints} "
                        f"new_snapshots={summary.new_snapshots} "
                        f"write_ms={write_seconds * 1000:.0f} "
                        f"qsize={self._queue.qsize()}"
                    )
                except Exception:
                    traceback.print_exc()

                buffer = []
                buffered_items = 0
                last_flush = time.monotonic()


async def key_lane(
    api_key: str,
    label: str,
    cursor: BatchCursor,
    settings: Settings,
    writer: WriteQueue,
    startup_delay_seconds: float,
) -> None:
    request_times: deque[float] = deque()

    await cursor.wait_ready()
    if startup_delay_seconds > 0:
        await asyncio.sleep(startup_delay_seconds)

    async with httpx.AsyncClient(
        base_url=settings.jupiter_base_url,
        timeout=settings.request_timeout_seconds,
    ) as client:
        while True:
            started = time.monotonic()

            try:
                batch = await cursor.next_batch()

                if batch:
                    request_started = time.monotonic()

                    request_times.append(request_started)
                    cutoff = request_started - 60.0
                    while request_times and request_times[0] < cutoff:
                        request_times.popleft()

                    response = await client.get(
                        "/tokens/v2/search",
                        params={"query": ",".join(batch)},
                        headers={"x-api-key": api_key},
                    )

                    if response.status_code == 200:
                        tokens = response.json()
                        await writer.submit(
                            tokens,
                            datetime.now(timezone.utc),
                        )

                        latency_ms = (
                            time.monotonic() - request_started
                        ) * 1000

                        print(
                            f"[{label}] "
                            f"requested={len(batch)} "
                            f"received={len(tokens)} "
                            f"rpm60={len(request_times)} "
                            f"latency={latency_ms:.0f}ms"
                        )
                    else:
                        retry_after = response.headers.get("retry-after", "?")
                        print(
                            f"[{label}] FEHLER "
                            f"status={response.status_code} "
                            f"requested={len(batch)} "
                            f"retry_after={retry_after} "
                            f"body={response.text[:200]!r}"
                        )

            except Exception:
                traceback.print_exc()

            # Per-key rate only. There is intentionally no global sleep,
            # population-size floor, in-flight guard, or cycle delay.
            await asyncio.sleep(
                max(
                    0.0,
                    settings.jupiter_seconds_per_key
                    - (time.monotonic() - started),
                )
            )


async def refresh_system(
    settings: Settings,
    repository: MintRepository,
    priority: int = 1,
    api_keys: Sequence[str] | None = None,
) -> None:
    keys = list(
        settings.jupiter_search_api_keys
        if api_keys is None
        else api_keys
    )
    if not keys:
        raise ValueError("refresh_system requires at least one API key")

    cache = MintCache(repository, priority)
    cursor = BatchCursor(cache)
    writer = WriteQueue(repository)

    # Same throughput as starting all keys at once, but spread evenly over one
    # per-key interval. With K keys the aggregate request spacing approaches
    # jupiter_seconds_per_key / K instead of one K-request burst per interval.
    phase_step = settings.jupiter_seconds_per_key / len(keys)

    lanes = [
        key_lane(
            key,
            f"lane{i}",
            cursor,
            settings,
            writer,
            startup_delay_seconds=i * phase_step,
        )
        for i, key in enumerate(keys)
    ]

    await asyncio.gather(
        cache.run(),
        writer.run(),
        *lanes,
    )