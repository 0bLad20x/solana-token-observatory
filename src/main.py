from __future__ import annotations

import argparse
import asyncio
import logging

from config import Settings
from discovery import jupiter_recent_loop, meteora_damm_v2_loop, meteora_dlmm_loop, pump_loop
from refresh import refresh_system
from repository import MintRepository


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="jupiter-data-transform")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("init-schema")
    sub.add_parser("run")
    return p


async def run() -> None:
    settings = Settings.from_env()
    repository = MintRepository(settings.database_url)
    repository.load_last_updated_at()
    await asyncio.gather(
        pump_loop(settings, repository),
        jupiter_recent_loop(settings, repository),
        meteora_damm_v2_loop(settings, repository),
        meteora_dlmm_loop(settings, repository),
        refresh_system(settings, repository, priority=1),
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    args = parser().parse_args()
    if args.command == "init-schema":
        settings = Settings.from_env()
        MintRepository(settings.database_url).initialize_schema()
        return
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
