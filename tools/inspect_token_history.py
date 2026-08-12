from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import Any

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from temporal_context import (
    SUMMARY_SAMPLE_MINUTES,
    build_temporal_summary_bundle,
    iso,
    load_temporal_summary_rows,
    rounded,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build the compact deterministic 24h temporal summary used by WP5."
        )
    )
    parser.add_argument("mint", help="Solana mint address")
    parser.add_argument(
        "--database-url",
        default=None,
        help="PostgreSQL URL. Defaults to DATABASE_URL from .env/environment.",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Output directory. Default: history_inspection_<mint-prefix>",
    )
    return parser.parse_args()


def context_size(value: Any) -> dict[str, int]:
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return {
        "utf8_bytes": len(text.encode("utf-8")),
        "estimated_tokens_chars_div_4": math.ceil(len(text) / 4),
    }


def human_bytes(value: int) -> str:
    size = float(value)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.2f} {unit}"
        size /= 1024
    return f"{size:.2f} GB"


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    if len(values) == 1:
        return values[0]
    position = (len(values) - 1) * q
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return values[lower]
    weight = position - lower
    return values[lower] * (1 - weight) + values[upper] * weight


def gap_summary(times: list[datetime]) -> dict[str, Any]:
    gaps = [
        (after - before).total_seconds()
        for before, after in zip(times, times[1:])
    ]
    if not gaps:
        return {}
    return {
        "median_seconds": rounded(percentile(gaps, 0.5)),
        "p95_seconds": rounded(percentile(gaps, 0.95)),
        "max_seconds": rounded(max(gaps)),
    }


def load_summary_data(
    database_url: str,
    mint: str,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    with psycopg.connect(
        database_url,
        row_factory=dict_row,
        autocommit=True,
        options="-c default_transaction_read_only=on -c statement_timeout=60000",
    ) as connection:
        token = connection.execute(
            "SELECT mint, name, symbol FROM mints WHERE mint = %s",
            (mint,),
        ).fetchone()
        history_rows, sample_rows = load_temporal_summary_rows(connection, mint)
    return dict(token or {"mint": mint}), history_rows, sample_rows


def main() -> None:
    args = parse_args()
    load_dotenv(ROOT / ".env")
    database_url = args.database_url or os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        raise SystemExit("DATABASE_URL is not configured.")

    query_started = perf_counter()
    token, history_rows, sample_rows = load_summary_data(database_url, args.mint)
    query_seconds = perf_counter() - query_started
    if not history_rows:
        raise SystemExit(f"No mint_snapshots found for: {args.mint}")

    summary_context = build_temporal_summary_bundle(
        args.mint,
        history_rows,
        sample_rows,
        token=token,
    )
    summary = summary_context["summary"]
    size = context_size(summary_context)

    times = [row["observed_at"] for row in history_rows]
    duration_seconds = (times[-1] - times[0]).total_seconds()
    report = {
        "mint": args.mint,
        "snapshots": len(history_rows),
        "from": iso(times[0]),
        "to": iso(times[-1]),
        "duration_seconds": duration_seconds,
        "query_seconds": rounded(query_seconds),
        "gaps": gap_summary(times),
        "summary_projection": {
            "context_size": size,
            "role": "deterministic per-token LLM evidence",
            "adaptive_time_buckets": False,
        },
        "internal_sampling": {
            "minutes": SUMMARY_SAMPLE_MINUTES,
            "samples": len(sample_rows),
            "purpose": (
                "time-normalize rolling stats and ratios so snapshot frequency does not "
                "bias summary medians; samples are not sent as temporal history"
            ),
        },
        "summary": summary,
        "notes": {
            "missing": "missing stays missing; no zero fill or interpolation",
            "rolling_stats": (
                "stats_1h is rolling source data and is never summed across samples"
            ),
            "token_estimate": "characters / 4 is only a rough comparison metric",
        },
    }

    output_dir = Path(
        args.out or f"history_inspection_{args.mint[:12]}"
    ).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "summary_context.json", summary_context)
    write_json(output_dir / "report.json", report)

    print()
    print("# TOKEN SUMMARY INSPECTOR")
    print()
    print(f"Mint:       {args.mint}")
    print(f"Name:       {token.get('name') or '-'}")
    print(f"Symbol:     {token.get('symbol') or '-'}")
    print(f"Snapshots:  {len(history_rows):,}")
    print(f"From:       {iso(times[0])}")
    print(f"To:         {iso(times[-1])}")
    print(f"Duration:   {duration_seconds / 3600:.2f}h")
    print(f"DB query:   {query_seconds:.2f}s")
    print()
    print("SUMMARY CONTEXT")
    print(
        f"Context:    {human_bytes(size['utf8_bytes'])} / "
        f"~{size['estimated_tokens_chars_div_4']:,} rough tokens"
    )
    print("Adaptive time buckets: none")
    print(
        f"Internal sampling: {SUMMARY_SAMPLE_MINUTES}m / {len(sample_rows):,} representative samples"
    )
    print()
    print("DERIVED SUMMARY")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print()
    print(f"Output: {output_dir}")
    print("Files: summary_context.json, report.json")


if __name__ == "__main__":
    main()
