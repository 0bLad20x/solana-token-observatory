from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from .collector import Collector
from .config import Settings
from .jupiter import JupiterClient
from .repository import JupiterRepository


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jupiter-data-transform")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init-db", help="Create the PostgreSQL tables")

    collect = subparsers.add_parser("collect", help="Collect Jupiter token snapshots")
    collect.add_argument("--mint", action="append", default=[], help="Mint address; repeatable")
    collect.add_argument("--mints-file", type=Path, help="Text file with one mint per line")
    collect.add_argument("--once", action="store_true", help="Run one collection cycle and exit")
    collect.add_argument("--interval", type=float, help="Seconds between collection cycles")

    return parser


def load_mints(cli_mints: list[str], mints_file: Path | None) -> list[str]:
    mints = list(cli_mints)
    if mints_file:
        mints.extend(
            line.strip()
            for line in mints_file.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        )
    return list(dict.fromkeys(mints))


async def run_command(args: argparse.Namespace) -> None:
    settings = Settings()

    async with JupiterRepository(settings.database_url) as repository:
        await repository.initialize_schema()

        if args.command == "init-db":
            return

        mints = load_mints(args.mint, args.mints_file)
        if not mints:
            raise SystemExit("collect requires --mint or --mints-file")

        async with JupiterClient(
            api_keys=settings.jupiter_api_keys,
            base_url=settings.jupiter_base_url,
            timeout_seconds=settings.jupiter_request_timeout_seconds,
        ) as client:
            collector = Collector(client, repository)
            if args.once:
                await collector.collect_once(mints)
            else:
                interval = args.interval or settings.collect_interval_seconds
                await collector.run(mints, interval)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    args = build_parser().parse_args()
    try:
        asyncio.run(run_command(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
