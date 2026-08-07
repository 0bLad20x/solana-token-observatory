from __future__ import annotations

import asyncio
import time
import traceback
from datetime import datetime, timezone

import httpx

from ..config import Settings
from .batch_cursor import BatchCursor
from .write_queue import WriteQueue


async def key_lane(
    api_key: str,
    label: str,
    cursor: BatchCursor,
    settings: Settings,
    write_queue: WriteQueue,
    seconds_per_key: float,
) -> None:
    async with httpx.AsyncClient(
        base_url=settings.jupiter_base_url,
        timeout=settings.request_timeout_seconds,
    ) as client:
        while True:
            tick_started = time.monotonic()

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
                        write_queue.submit(tokens, datetime.now(timezone.utc))
                        print(f"[{label}] OK requested={len(batch)} received={len(tokens)}")
                    else:
                        retry_after = response.headers.get("retry-after", "?")
                        print(
                            f"[{label}] FEHLER {response.status_code} "
                            f"requested={len(batch)} retry_after={retry_after} "
                            f"body={response.text[:200]!r}"
                        )
            except Exception:
                print(f"[{label}] AUSNAHME (Lane läuft trotzdem weiter):")
                traceback.print_exc()

            elapsed = time.monotonic() - tick_started
            await asyncio.sleep(max(0.0, seconds_per_key - elapsed))