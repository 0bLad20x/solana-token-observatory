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
from observatory.rugcheck_projection import project_rugcheck_evidence


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


def _object_key_profile(items: list[Any]) -> list[tuple[tuple[str, ...], int]]:
    counts: dict[tuple[str, ...], int] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        keys = tuple(sorted(item))
        counts[keys] = counts.get(keys, 0) + 1
    return sorted(counts.items(), key=lambda row: (-row[1], row[0]))


def _print_section_sample(section: str, value: Any, sample_size: int) -> None:
    print()
    print(f"SECTION DETAIL · {section}")
    print(f"Shape: {_shape(value)}")
    print(f"Bytes: {_json_bytes(value):,}")

    if isinstance(value, list):
        profiles = _object_key_profile(value)
        if profiles:
            print("Object key shapes:")
            for keys, count in profiles[:5]:
                print(f"  {count:>4} × {', '.join(keys)}")
        for index, item in enumerate(value[:sample_size]):
            print()
            print(f"Sample [{index}]")
            print(json.dumps(item, ensure_ascii=False, indent=2))
        return

    if isinstance(value, dict):
        print("Value shapes:")
        shape_counts: dict[str, int] = {}
        for item in value.values():
            shape = _shape(item)
            shape_counts[shape] = shape_counts.get(shape, 0) + 1
        for shape, count in sorted(shape_counts.items(), key=lambda row: (-row[1], row[0])):
            print(f"  {count:>4} × {shape}")

        for index, (key, item) in enumerate(value.items()):
            if index >= sample_size:
                break
            print()
            print(f"Sample key: {key}")
            print(json.dumps(item, ensure_ascii=False, indent=2))
        return

    print(json.dumps(value, ensure_ascii=False, indent=2))


async def inspect(
    mint: str,
    show_json: bool,
    show_analysis: bool,
    sections: list[str],
    sample_size: int,
) -> int:
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

    projected = project_rugcheck_evidence(evidence)
    projection = projected.get("projection", {})
    projected_bytes = projection.get("projected_report_bytes")
    raw_bytes = projection.get("raw_report_bytes")
    reduction = None
    if isinstance(raw_bytes, int) and raw_bytes > 0 and isinstance(projected_bytes, int):
        reduction = 100.0 * (1.0 - projected_bytes / raw_bytes)

    print()
    print("ANALYSIS METADATA")
    print(f"Mode:                     {projection.get('type')}")
    print(
        f"Raw report bytes:         {raw_bytes:,}"
        if isinstance(raw_bytes, int)
        else "Raw report bytes:         -"
    )
    print(
        f"Metadata bytes:           {projected_bytes:,}"
        if isinstance(projected_bytes, int)
        else "Metadata bytes:           -"
    )
    projected_tokens = projection.get("projected_rough_report_tokens")
    print(
        f"Metadata rough tokens:    {projected_tokens:,}"
        if isinstance(projected_tokens, int)
        else "Metadata rough tokens:    -"
    )
    print(
        f"Reduction:                {reduction:.1f}%"
        if reduction is not None
        else "Reduction:                -"
    )
    print(f"Markets observed:         {projection.get('markets_observed')}")
    print(f"Top holders observed:     {projection.get('top_holders_observed')}")
    print(f"Known accounts observed:  {projection.get('known_accounts_observed')}")
    print(
        "Wallet addresses to LLM: "
        f"{projection.get('wallet_addresses_sent_to_llm')}"
    )

    if show_analysis:
        print()
        print("LLM SAFETY METADATA JSON")
        print(json.dumps(projected.get("summary"), ensure_ascii=False, indent=2))

    for section in sections:
        if section not in report:
            print()
            print(f"SECTION DETAIL · {section}")
            print("Section not present")
            continue
        _print_section_sample(section, report[section], sample_size)

    if show_json:
        print()
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect one exact-mint RugCheck report.")
    parser.add_argument("mint")
    parser.add_argument("--show-json", action="store_true")
    parser.add_argument(
        "--show-analysis",
        action="store_true",
        help="Print exactly the compact safety metadata delivered to the LLM.",
    )
    parser.add_argument(
        "--section",
        action="append",
        default=[],
        help="Print structure and bounded samples for one top-level section; repeatable.",
    )
    parser.add_argument(
        "--sample-size",
        type=int,
        default=2,
        choices=range(1, 6),
        metavar="1-5",
        help="Number of bounded section samples to print (default: 2).",
    )
    args = parser.parse_args()
    raise SystemExit(
        asyncio.run(
            inspect(
                args.mint,
                args.show_json,
                args.show_analysis,
                args.section,
                args.sample_size,
            )
        )
    )


if __name__ == "__main__":
    main()
