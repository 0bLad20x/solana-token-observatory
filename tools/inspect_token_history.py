from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from temporal_context import (
    TEMPORAL_SOURCE_FIELDS,
    build_temporal_context,
    iso,
    rounded,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build one LLM-ready token history context: standalone deterministic "
            "summary plus 1m buckets for up to 6h, otherwise 5m buckets."
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


def projected_payload_sql() -> str:
    parts = ",\n                ".join(
        f"'{field}', payload->'{field}'" for field in TEMPORAL_SOURCE_FIELDS
    )
    return f"""
        jsonb_strip_nulls(
            jsonb_build_object(
                {parts}
            )
        )
    """


def load_rows(database_url: str, mint: str) -> list[dict[str, Any]]:
    projection = projected_payload_sql()
    with psycopg.connect(
        database_url,
        row_factory=dict_row,
        autocommit=True,
        options="-c default_transaction_read_only=on -c statement_timeout=60000",
    ) as connection:
        return list(
            connection.execute(
                f"""
                SELECT observed_at, {projection} AS payload
                FROM mint_snapshots
                WHERE mint = %s
                  AND observed_at >= CURRENT_TIMESTAMP - INTERVAL '24 hours'
                ORDER BY observed_at ASC
                """,
                (mint,),
            ).fetchall()
        )


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


def main() -> None:
    args = parse_args()
    load_dotenv(ROOT / ".env")
    database_url = args.database_url or os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        raise SystemExit("DATABASE_URL is not configured.")

    rows = load_rows(database_url, args.mint)
    if not rows:
        raise SystemExit(f"No mint_snapshots found for: {args.mint}")

    llm_context = build_temporal_context(args.mint, rows)
    summary_context = {
        "token": llm_context["token"],
        "summary": llm_context["summary"],
    }
    temporal_history = llm_context["temporal_history"]
    resolution_minutes = temporal_history["resolution_minutes"]
    buckets = temporal_history["buckets"]
    summary = llm_context["summary"]
    header = llm_context["token"]
    size = context_size(llm_context)
    summary_size = context_size(summary_context)

    times = [row["observed_at"] for row in rows]
    payloads = [row["payload"] for row in rows]
    duration_seconds = (times[-1] - times[0]).total_seconds()
    unique_updated_at = len(
        {
            payload.get("updatedAt")
            for payload in payloads
            if payload.get("updatedAt") is not None
        }
    )

    report = {
        "mint": args.mint,
        "snapshots": len(rows),
        "unique_updated_at": unique_updated_at,
        "duplicate_updated_at_rows": len(rows) - unique_updated_at,
        "from": iso(times[0]),
        "to": iso(times[-1]),
        "duration_seconds": duration_seconds,
        "gaps": gap_summary(times),
        "summary_projection": {
            "standalone": True,
            "context_size": summary_size,
            "resolution_independent": True,
            "role": (
                "deterministic per-token analysis projection suitable for later "
                "multi-token bundling without temporal_history"
            ),
        },
        "temporal_projection": {
            "rule": "1m for available history <= 6h; otherwise 5m",
            "resolution_minutes": resolution_minutes,
            "buckets": len(buckets),
            "context_size": size,
        },
        "summary": summary,
        "future_system_prompt_requirement": {
            "summary_role": (
                "summary is deterministic derived context, not a diagnosis"
            ),
            "temporal_evidence_rule": (
                "for deep single-token analysis the model must inspect "
                "temporal_history and use it to confirm, qualify, or challenge "
                "summary; judgment from summary alone is forbidden"
            ),
        },
        "notes": {
            "missing": "missing stays missing; no zero fill or interpolation",
            "rolling_stats": (
                "stats_1h is rolling source data; summary medians and ratios use "
                "fixed 5m time-normalized samples and rolling values are never summed"
            ),
            "token_estimate": "characters / 4 is only a rough comparison metric",
        },
    }

    output_dir = Path(
        args.out or f"history_inspection_{args.mint[:12]}"
    ).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "summary_context.json", summary_context)
    write_json(output_dir / "llm_context.json", llm_context)
    write_json(output_dir / "report.json", report)

    print()
    print("# TOKEN HISTORY INSPECTOR")
    print()
    print(f"Mint:       {args.mint}")
    print(f"Name:       {header.get('name') or '-'}")
    print(f"Symbol:     {header.get('symbol') or '-'}")
    print(f"Snapshots:  {len(rows):,}")
    print(f"updatedAt:  {unique_updated_at:,} unique")
    print(f"Duplicates: {len(rows) - unique_updated_at:,} rows")
    print(f"From:       {iso(times[0])}")
    print(f"To:         {iso(times[-1])}")
    print(f"Duration:   {duration_seconds / 3600:.2f}h")
    print()
    print("STANDALONE SUMMARY")
    print(
        f"Context:    {human_bytes(summary_size['utf8_bytes'])} / "
        f"~{summary_size['estimated_tokens_chars_div_4']:,} rough tokens"
    )
    print("Role:       resolution-independent per-token comparison building block")
    print()
    print("TEMPORAL PROJECTION")
    print("Rule:       1m <= 6h, otherwise 5m")
    print(f"Resolution: {resolution_minutes}m")
    print(f"Buckets:    {len(buckets):,}")
    print(
        f"Context:    {human_bytes(size['utf8_bytes'])} / "
        f"~{size['estimated_tokens_chars_div_4']:,} rough tokens"
    )
    print()
    print("DERIVED SUMMARY")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print()
    print("LLM EVIDENCE RULE")
    print(
        "Summary is derived context only. Deep temporal analysis must inspect "
        "temporal_history and forbid judgment from summary alone."
    )
    print()
    print(f"Output: {output_dir}")
    print("Files: summary_context.json, llm_context.json, report.json")


if __name__ == "__main__":
    main()
