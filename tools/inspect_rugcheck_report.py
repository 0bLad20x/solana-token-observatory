from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from observatory.evidence.rugcheck import RugCheckError, get_token_report


def _json_bytes(value: Any) -> int:
    payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return len(payload.encode("utf-8"))


def _shape(value: Any) -> str:
    if isinstance(value, list):
        return f"list[{len(value)}]"
    if isinstance(value, dict):
        return f"object[{len(value)}]"
    if value is None:
        return "null"
    return type(value).__name__


def _section_profile(report: dict[str, Any]) -> list[tuple[str, str, int, int]]:
    rows = []
    for key, value in report.items():
        size = _json_bytes(value)
        rows.append((key, _shape(value), size, (size + 3) // 4))
    rows.sort(key=lambda row: (-row[2], row[0]))
    return rows


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
    print()
    print("SECTION PROFILE")
    print(f"{'section':<28} {'shape':<14} {'bytes':>10} {'~tokens':>10}")
    for key, shape, size, rough_tokens in _section_profile(report):
        print(f"{key:<28} {shape:<14} {size:>10,} {rough_tokens:>10,}")

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
