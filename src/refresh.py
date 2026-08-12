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
from telemetry import TelemetryEmitter

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
    """Buffer observed Jupiter source versions, not redundant polls.

    `(mint, updatedAt)` is the in-memory version key:
    - repeated polls of the same source version collapse to one payload;
    - every distinct source version survives the flush;
    - `_observed_at` is when that version was first seen in this buffer;
    - `_last_polled_at` is the newest successful poll of that version.
    """

    def __init__(
        self,
        repository: MintRepository,
        telemetry: TelemetryEmitter | None = None,
    ) -> None:
        self._repository = repository
        self._telemetry = telemetry
        self._queue: asyncio.Queue[tuple[list[dict], datetime]] = asyncio.Queue(
            maxsize=QUEUE_MAX_SIZE
        )

    async def submit(self, tokens: list[dict], observed_at: datetime) -> None:
        await self._queue.put((tokens, observed_at))

    async def run(self) -> None:
        versions: dict[tuple[str, str], dict] = {}
        buffered_polls = 0
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
                buffered_polls += len(tokens)

                for token in tokens:
                    key = (token["id"], token["updatedAt"])
                    existing = versions.get(key)

                    if existing is None:
                        version = token.copy()
                        version["_observed_at"] = observed_at
                        version["_last_polled_at"] = observed_at
                        versions[key] = version
                    elif observed_at > existing["_last_polled_at"]:
                        existing["_last_polled_at"] = observed_at

            except asyncio.TimeoutError:
                pass

            by_time = time.monotonic() - last_flush >= FLUSH_INTERVAL_SECONDS
            by_size = buffered_polls >= FLUSH_SIZE_THRESHOLD

            if versions and (by_time or by_size):
                version_rows = list(versions.values())

                try:
                    write_started = time.monotonic()
                    summary = await asyncio.to_thread(
                        self._repository.store_tokens_grouped,
                        version_rows,
                    )
                    write_seconds = time.monotonic() - write_started
                    queue_size = self._queue.qsize()

                    print(
                        f"[write_queue] polls={buffered_polls} "
                        f"versions={len(version_rows)} "
                        f"new_mints={summary.new_mints} "
                        f"new_snapshots={summary.new_snapshots} "
                        f"write_ms={write_seconds * 1000:.0f} "
                        f"qsize={queue_size}"
                    )
                    if self._telemetry is not None:
                        self._telemetry.emit(
                            "search_flush",
                            polled_tokens=buffered_polls,
                            source_versions=len(version_rows),
                            new_snapshots=summary.new_snapshots,
                            write_ms=round(write_seconds * 1000),
                            queue_size=queue_size,
                        )
                except Exception:
                    traceback.print_exc()

                versions = {}
                buffered_polls = 0
                last_flush = time.monotonic()


async def key_lane(
    api_key: str,
    label: str,
    cursor: BatchCursor,
    settings: Settings,
    writer: WriteQueue,
    startup_delay_seconds: float,
    telemetry: TelemetryEmitter | None = None,
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
                    latency_ms = (time.monotonic() - request_started) * 1000

                    if response.status_code == 200:
                        tokens = response.json()
                        await writer.submit(
                            tokens,
                            datetime.now(timezone.utc),
                        )

                        print(
                            f"[{label}] "
                            f"requested={len(batch)} "
                            f"received={len(tokens)} "
                            f"rpm60={len(request_times)} "
                            f"latency={latency_ms:.0f}ms"
                        )
                        if telemetry is not None:
                            telemetry.emit(
                                "search_lane_tick",
                                lane=label,
                                status=response.status_code,
                                requested=len(batch),
                                received=len(tokens),
                                rpm60=len(request_times),
                                latency_ms=round(latency_ms),
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
                        if telemetry is not None:
                            telemetry.emit(
                                "search_lane_tick",
                                lane=label,
                                status=response.status_code,
                                requested=len(batch),
                                received=0,
                                rpm60=len(request_times),
                                latency_ms=round(latency_ms),
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
    telemetry: TelemetryEmitter | None = None,
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
    writer = WriteQueue(repository, telemetry=telemetry)

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
            telemetry=telemetry,
        )
        for i, key in enumerate(keys)
    ]

    await asyncio.gather(
        cache.run(),
        writer.run(),
        *lanes,
    )
