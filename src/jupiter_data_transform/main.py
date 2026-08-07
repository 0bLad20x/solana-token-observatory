from __future__ import annotations

import argparse
import asyncio
import logging

from .config import Settings
from .orchestrator import run as run_orchestrator
from .repository import MintRepository


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jupiter-data-transform")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init-schema", help="Create the PostgreSQL tables")
    subparsers.add_parser("run", help="Run discovery and search together")

    return parser


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    args = build_parser().parse_args()

    if args.command == "init-schema":
        settings = Settings.from_env()
        MintRepository(settings.database_url).initialize_schema()
        return

    if args.command == "run":
        try:
            asyncio.run(run_orchestrator())
        except KeyboardInterrupt:
            pass
        return


if __name__ == "__main__":
    main()