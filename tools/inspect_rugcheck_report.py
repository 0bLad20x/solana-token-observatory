from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from observatory.evidence.rugcheck import RugCheckError, get_token_report


async def inspect(mint: str, show_json: bool) -> int:
    try:
        evidence = await get_token_report(mint)
    except RugCheckError as error:
        print(f"RugCheck error ({error.status_code}): {error}")
        return 1

    report = evidence["report"]
    print("RUGCHECK TOKEN REPORT")
    print(f"Mint:         {evidence['mint']}")
    print(f"Fetched at:   {evidence['fetched_at']}")
    print(f"Report bytes: {evidence['report_bytes']:,}")
    print(f"Rough tokens: {evidence['rough_report_tokens']:,}")
    print(f"Top-level:    {', '.join(sorted(report))}")
    if show_json:
        print()
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect one exact-mint RugCheck report.")
    parser.add_argument("mint")
    parser.add_argument("--show-json", action="store_true")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(inspect(args.mint, args.show_json)))


if __name__ == "__main__":
    main()
