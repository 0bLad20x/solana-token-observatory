from __future__ import annotations

import argparse
import asyncio
import logging

from config import Settings
from database import Database
from discovery import (
    jupiter_recent_loop,
    meteora_damm_v2_loop,
    meteora_dlmm_loop,
    pump_loop,
)
from maintenance import snapshot_retention_loop
from refresh import refresh_system
from repository import MintRepository
from telemetry import TelemetryEmitter


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="jupiter-data-transform")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("init-schema")
    sub.add_parser("run")
    return p


async def run(
    settings: Settings,
    repository: MintRepository,
    telemetry: TelemetryEmitter,
) -> None:
    await asyncio.gather(
        pump_loop(settings, repository, telemetry),
        jupiter_recent_loop(settings, repository, telemetry),
        meteora_damm_v2_loop(settings, repository, telemetry),
        meteora_dlmm_loop(settings, repository, telemetry),
        refresh_system(settings, repository, priority=1, telemetry=telemetry),
        snapshot_retention_loop(repository),
    )


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)

    args = parser().parse_args()
    settings = Settings.from_env()

    with Database(settings.database_url) as database:
        if args.command == "init-schema":
            database.initialize_schema()
            return

        repository = MintRepository(database)
        telemetry = TelemetryEmitter.from_env()
        try:
            asyncio.run(run(settings, repository, telemetry))
        except KeyboardInterrupt:
            pass
        finally:
            telemetry.close()


if __name__ == "__main__":
    main()
