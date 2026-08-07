from __future__ import annotations

import asyncio
import traceback

from ..repository import MintRepository


class MintCache:
    def __init__(self, repository: MintRepository, priority: int, refresh_interval: float = 5.0) -> None:
        self._repository = repository
        self._priority = priority
        self._refresh_interval = refresh_interval
        self._mints: list[str] = []

    def snapshot(self) -> list[str]:
        return self._mints

    async def run(self) -> None:
        while True:
            try:
                mints = await asyncio.to_thread(
                    self._repository.load_active_mints_by_priority, self._priority
                )
                self._mints = mints
            except Exception:
                print(
                    f"[mint_cache prio={self._priority}] FEHLER beim Laden — "
                    f"behalte vorherigen Stand ({len(self._mints)} Mints), Details folgen:"
                )
                traceback.print_exc()

            await asyncio.sleep(self._refresh_interval)