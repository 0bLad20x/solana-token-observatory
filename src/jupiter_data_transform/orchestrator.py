from __future__ import annotations

import asyncio
import traceback

from .config import Settings
from .discovery.jupiter_recent import jupiter_recent_loop
from .discovery.meteora_damm_v2 import meteora_damm_v2_loop
from .discovery.meteora_dlmm import meteora_dlmm_loop
from .discovery.pumpfun import pump_loop
from .refresh.refresh_loop import refresh_system
from .repository import MintRepository


async def run() -> None:
    settings = Settings.from_env()
    repository = MintRepository(settings.database_url)
    repository.load_last_updated_at()

    tasks = [
        pump_loop(settings, repository),
        jupiter_recent_loop(settings, repository),
        meteora_damm_v2_loop(settings, repository),
        meteora_dlmm_loop(settings, repository),
        refresh_system(settings, repository, priority=1),
    ]

    try:
        await asyncio.gather(*tasks)
    except Exception:
        print("ORCHESTRATOR ABSTURZ:")
        traceback.print_exc()
        raise