from __future__ import annotations

import asyncio
import traceback

import httpx

from ..config import Settings
from ..repository import MintRepository

METEORA_URL = "https://damm-v2.datapi.meteora.ag/pools"


async def meteora_damm_v2_loop(settings: Settings, repository: MintRepository) -> None:
    async with httpx.AsyncClient(timeout=20.0) as client:
        while True:
            try:
                response = await client.get(
                    METEORA_URL,
                    params={"page": 1, "page_size": 100, "sort_by": "pool_created_at:desc"},
                )
                status = "OK" if response.status_code == 200 else f"FEHLER {response.status_code}"
                pools = response.json().get("data", []) if response.status_code == 200 else []

                candidates: list[str] = []
                for pool in pools:
                    for token_key in ("token_x", "token_y"):
                        token = pool.get(token_key)
                        if isinstance(token, dict) and token.get("address"):
                            candidates.append(token["address"])

                inserted = 0
                if candidates:
                    inserted = await asyncio.to_thread(repository.insert_new_mints, candidates)

                print(f"[meteora_damm_v2] {status} pools={len(pools)} neue_mints={inserted}")
            except Exception:
                print("[meteora_damm_v2] AUSNAHME, Details folgen:")
                traceback.print_exc()

            await asyncio.sleep(settings.discovery_interval_seconds)