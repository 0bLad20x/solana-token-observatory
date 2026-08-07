from __future__ import annotations

import asyncio
import traceback

import httpx

from ..config import Settings
from ..repository import MintRepository

DLMM_URL = "https://dlmm.datapi.meteora.ag/pools"
SORT_ORDERS = ["tvl:desc", "fee_24h:desc", "volume_24h:desc"]


async def meteora_dlmm_loop(settings: Settings, repository: MintRepository) -> None:
    async with httpx.AsyncClient(timeout=20.0) as client:
        while True:
            for sort_by in SORT_ORDERS:
                try:
                    response = await client.get(
                        DLMM_URL,
                        params={"page": 1, "page_size": 100, "sort_by": sort_by},
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

                    print(f"[meteora_dlmm:{sort_by}] {status} pools={len(pools)} neue_mints={inserted}")
                except Exception:
                    print(f"[meteora_dlmm:{sort_by}] AUSNAHME, Details folgen:")
                    traceback.print_exc()

            await asyncio.sleep(settings.discovery_interval_seconds)