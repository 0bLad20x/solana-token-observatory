from __future__ import annotations

import asyncio
import time
import traceback
from datetime import datetime

from ..repository import MintRepository

FLUSH_INTERVAL_SECONDS = 2.0
FLUSH_SIZE_THRESHOLD = 500
QUEUE_MAX_SIZE = 10_000


class WriteQueue:
    def __init__(self, repository: MintRepository) -> None:
        self._repository = repository
        self._queue: asyncio.Queue[tuple[list[dict], datetime]] = asyncio.Queue(maxsize=QUEUE_MAX_SIZE)

    def submit(self, tokens: list[dict], observed_at: datetime) -> None:
        try:
            self._queue.put_nowait((tokens, observed_at))
        except asyncio.QueueFull:
            print(f"[write_queue] VOLL — Batch verworfen, Writer haengt hinterher (qsize={self._queue.qsize()})")

    async def run(self) -> None:
        buffer: list[tuple[list[dict], datetime]] = []
        last_flush = time.monotonic()

        while True:
            timeout = max(0.0, FLUSH_INTERVAL_SECONDS - (time.monotonic() - last_flush))
            try:
                item = await asyncio.wait_for(self._queue.get(), timeout=timeout)
                buffer.append(item)
            except asyncio.TimeoutError:
                pass

            due_by_time = time.monotonic() - last_flush >= FLUSH_INTERVAL_SECONDS
            due_by_size = sum(len(tokens) for tokens, _ in buffer) >= FLUSH_SIZE_THRESHOLD

            if buffer and (due_by_time or due_by_size):
                all_tokens: list[dict] = []
                for tokens, observed_at in buffer:
                    for token in tokens:
                        token["_observed_at"] = observed_at
                        all_tokens.append(token)

                try:
                    summary = await asyncio.to_thread(self._repository.store_tokens_grouped, all_tokens)
                    print(
                        f"[write_queue] flush items={len(all_tokens)} "
                        f"neue_mints={summary.new_mints} neue_snapshots={summary.new_snapshots} "
                        f"qsize={self._queue.qsize()}"
                    )
                except Exception:
                    print(
                        f"[write_queue] FEHLER beim Schreiben — Batch verworfen "
                        f"(items={len(all_tokens)}), Details folgen:"
                    )
                    traceback.print_exc()

                buffer = []
                last_flush = time.monotonic()