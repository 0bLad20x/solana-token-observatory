from __future__ import annotations

import argparse
import logging
from pathlib import Path

from .collector import collect_once, run
from .config import Settings
from .jupiter import JupiterClient
from .repository import JupiterRepository


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jupiter-data-transform")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init-schema", help="Create the PostgreSQL tables")

    collect = subparsers.add_parser("collect", help="Collect Jupiter token observations")
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
    return list(dict.fromkeys(mint for mint in mints if mint))


def run_command(args: argparse.Namespace) -> None:
    settings = Settings.from_env()
    repository = JupiterRepository(settings.database_url)

    if args.command == "init-schema":
        repository.initialize_schema()
        return

    mints = load_mints(args.mint, args.mints_file)
    if not mints:
        raise SystemExit("collect requires --mint or --mints-file")

    with JupiterClient(
        api_key=settings.jupiter_api_key,
        base_url=settings.jupiter_base_url,
        timeout_seconds=settings.request_timeout_seconds,
    ) as client:
        if args.once:
            collect_once(client, repository, mints)
        else:
            interval = (
                args.interval
                if args.interval is not None
                else settings.collect_interval_seconds
            )
            run(client, repository, mints, interval)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    args = build_parser().parse_args()
    try:
        run_command(args)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
