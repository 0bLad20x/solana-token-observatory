from __future__ import annotations

import asyncio
import time
import traceback

import httpx

from ..config import Settings
from ..repository import MintRepository


async def jupiter_recent_loop(settings: Settings, repository: MintRepository) -> None:
    async with httpx.AsyncClient(timeout=20.0) as client:
        while True:
            tick_started = time.monotonic()
            try:
                response = await client.get(
                    f"{settings.jupiter_base_url}/tokens/v2/recent",
                    headers={"x-api-key": settings.jupiter_recent_api_key},
                )
                status = "OK" if response.status_code == 200 else f"FEHLER {response.status_code}"
                items = response.json() if response.status_code == 200 else []
                candidates = [
                    item["id"] for item in items if isinstance(item, dict) and item.get("id")
                ]

                inserted = 0
                if candidates:
                    inserted = await asyncio.to_thread(repository.insert_new_mints, candidates)

                print(f"[jupiter_recent] {status} erhalten={len(items)} neue_mints={inserted}")
            except Exception:
                print("[jupiter_recent] AUSNAHME, Details folgen:")
                traceback.print_exc()

            elapsed = time.monotonic() - tick_started
            await asyncio.sleep(max(0.0, settings.jupiter_seconds_per_key - elapsed))