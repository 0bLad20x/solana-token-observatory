from __future__ import annotations

import argparse
import json
import math
import os
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row

ONE_MINUTE_MAX_HISTORY_HOURS = 6.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build one LLM-ready token history context: 1m buckets for up to 6h, "
            "otherwise 5m buckets, plus a deterministic derived summary."
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


def iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def numeric(value: Any) -> float | int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def rounded(value: float | int | None, digits: int = 6) -> float | int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    return round(float(value), digits)


def snake_case(value: str) -> str:
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value)
    value = re.sub(r"[^a-zA-Z0-9]+", "_", value)
    return value.strip("_").lower()


def numeric_object(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, Any] = {}
    for key, child in value.items():
        key = snake_case(str(key))
        if isinstance(child, dict):
            nested = numeric_object(child)
            if nested:
                result[key] = nested
        else:
            number = numeric(child)
            if number is not None:
                result[key] = number
    return result


def get_path(value: dict[str, Any], *path: str) -> Any:
    current: Any = value
    for part in path:
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def last_present(payloads: list[dict[str, Any]], *path: str) -> Any:
    for payload in reversed(payloads):
        value = get_path(payload, *path)
        if value is not None:
            return value
    return None


def distinct_present(payloads: list[dict[str, Any]], *path: str) -> list[Any]:
    values: list[Any] = []
    seen: set[str] = set()
    for payload in payloads:
        value = get_path(payload, *path)
        if value is None:
            continue
        fingerprint = json.dumps(value, sort_keys=True, ensure_ascii=False)
        if fingerprint not in seen:
            seen.add(fingerprint)
            values.append(value)
    return values


def build_header(
    mint: str,
    payloads: list[dict[str, Any]],
) -> tuple[dict[str, Any], set[str]]:
    header: dict[str, Any] = {"mint": mint}
    simple_fields = {
        "name": ("name",),
        "symbol": ("symbol",),
        "dev": ("dev",),
        "icon": ("icon",),
        "website": ("website",),
        "twitter": ("twitter",),
        "decimals": ("decimals",),
        "token_program": ("tokenProgram",),
        "launchpad": ("launchpad",),
        "created_at": ("createdAt",),
    }
    for output, path in simple_fields.items():
        value = last_present(payloads, *path)
        if value is not None:
            header[output] = value

    first_pool = {
        "id": last_present(payloads, "firstPool", "id"),
        "created_at": last_present(payloads, "firstPool", "createdAt"),
    }
    first_pool = {key: value for key, value in first_pool.items() if value is not None}
    if first_pool:
        header["first_pool"] = first_pool

    verified = last_present(payloads, "isVerified")
    if verified is not None:
        header["verification"] = {"is_verified": verified}

    authorities = {
        "mint_authority": last_present(payloads, "mintAuthority"),
        "freeze_authority": last_present(payloads, "freezeAuthority"),
        "mint_authority_disabled": last_present(
            payloads, "audit", "mintAuthorityDisabled"
        ),
        "freeze_authority_disabled": last_present(
            payloads, "audit", "freezeAuthorityDisabled"
        ),
    }
    authorities = {
        key: value for key, value in authorities.items() if value is not None
    }
    if authorities:
        header["authorities"] = authorities

    dynamic_supply: set[str] = set()
    constant_supply: dict[str, Any] = {}
    for output, path in {
        "circulating": ("circSupply",),
        "total": ("totalSupply",),
    }.items():
        values = distinct_present(payloads, *path)
        if len(values) == 1:
            constant_supply[output] = values[0]
        elif len(values) > 1:
            dynamic_supply.add(output)
    if constant_supply:
        header["supply"] = constant_supply

    return header, dynamic_supply


def history_row(
    observed_at: datetime,
    payload: dict[str, Any],
    dynamic_supply: set[str],
) -> dict[str, Any]:
    row: dict[str, Any] = {"t": iso(observed_at)}
    for source, target in (
        ("mcap", "market_cap"),
        ("liquidity", "liquidity"),
        ("holderCount", "holders"),
        ("organicScore", "organic_score"),
    ):
        value = numeric(payload.get(source))
        if value is not None:
            row[target] = value

    audit = payload.get("audit")
    if isinstance(audit, dict):
        values = {
            "dev_mints": numeric(audit.get("devMints")),
            "dev_balance_pct": numeric(audit.get("devBalancePercentage")),
            "top_holders_pct": numeric(audit.get("topHoldersPercentage")),
        }
        values = {key: value for key, value in values.items() if value is not None}
        if values:
            row["audit"] = values

    stats = numeric_object(payload.get("stats1h"))
    if stats:
        row["stats_1h"] = stats

    apy = numeric_object(payload.get("apy"))
    if apy:
        row["apy"] = apy

    if dynamic_supply:
        supply: dict[str, Any] = {}
        if "circulating" in dynamic_supply:
            value = numeric(payload.get("circSupply"))
            if value is not None:
                supply["circulating"] = value
        if "total" in dynamic_supply:
            value = numeric(payload.get("totalSupply"))
            if value is not None:
                supply["total"] = value
        if supply:
            row["supply"] = supply

    return row


def flatten_numeric(value: Any, prefix: str = "") -> dict[str, float | int]:
    result: dict[str, float | int] = {}
    if not isinstance(value, dict):
        return result
    for key, child in value.items():
        if key == "t":
            continue
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(child, dict):
            result.update(flatten_numeric(child, path))
        else:
            number = numeric(child)
            if number is not None:
                result[path] = number
    return result


def set_path(target: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    current = target
    for part in parts[:-1]:
        current = current.setdefault(part, {})
    current[parts[-1]] = value


def make_buckets(history: list[dict[str, Any]], minutes: int) -> list[dict[str, Any]]:
    seconds = minutes * 60
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in history:
        timestamp = datetime.fromisoformat(row["t"]).timestamp()
        grouped[math.floor(timestamp / seconds) * seconds].append(row)

    buckets: list[dict[str, Any]] = []
    for start_ts in sorted(grouped):
        rows = grouped[start_ts]
        values_by_path: dict[str, list[float | int]] = defaultdict(list)
        for row in rows:
            for path, value in flatten_numeric(row).items():
                values_by_path[path].append(value)

        bucket: dict[str, Any] = {
            "bucket_start": iso(datetime.fromtimestamp(start_ts, tz=timezone.utc)),
            "bucket_end": iso(
                datetime.fromtimestamp(start_ts + seconds, tz=timezone.utc)
            ),
            "observations": len(rows),
        }
        for path, values in sorted(values_by_path.items()):
            set_path(
                bucket,
                path,
                {
                    "first": values[0],
                    "last": values[-1],
                    "min": min(values),
                    "max": max(values),
                    "samples": len(values),
                },
            )
        buckets.append(bucket)
    return buckets


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


def metric_points(
    history: list[dict[str, Any]],
    *path: str,
) -> list[tuple[str, float]]:
    points: list[tuple[str, float]] = []
    for row in history:
        value = numeric(get_path(row, *path))
        if value is not None:
            points.append((row["t"], float(value)))
    return points


def change_pct(start: float, current: float) -> float | None:
    if start == 0:
        return None
    return (current / start - 1) * 100


def metric_summary(
    history: list[dict[str, Any]],
    *path: str,
    peak_and_drawdown: bool = False,
) -> dict[str, Any]:
    points = metric_points(history, *path)
    if not points:
        return {}
    values = [value for _, value in points]
    result: dict[str, Any] = {
        "start": rounded(values[0]),
        "current": rounded(values[-1]),
        "min": rounded(min(values)),
        "max": rounded(max(values)),
        "change_pct": rounded(change_pct(values[0], values[-1])),
    }
    if peak_and_drawdown:
        peak_index = max(range(len(values)), key=values.__getitem__)
        running_peak = values[0]
        max_drawdown = 0.0
        for value in values:
            running_peak = max(running_peak, value)
            if running_peak > 0:
                max_drawdown = min(
                    max_drawdown,
                    (value / running_peak - 1) * 100,
                )
        result["peak_at"] = points[peak_index][0]
        result["max_drawdown_pct"] = rounded(max_drawdown)
    return result


def bucket_last(bucket: dict[str, Any], *path: str) -> float | None:
    metric = get_path(bucket, *path)
    if not isinstance(metric, dict):
        return None
    return numeric(metric.get("last"))


def summarize_values(values: list[float]) -> dict[str, Any]:
    if not values:
        return {}
    return {
        "current": rounded(values[-1]),
        "median": rounded(percentile(values, 0.5)),
        "min": rounded(min(values)),
        "max": rounded(max(values)),
    }


def ratio_values(
    buckets: list[dict[str, Any]],
    left: tuple[str, ...],
    right: tuple[str, ...],
    mode: str,
) -> list[float]:
    values: list[float] = []
    for bucket in buckets:
        a = bucket_last(bucket, *left)
        b = bucket_last(bucket, *right)
        if a is None or b is None:
            continue
        a = float(a)
        b = float(b)
        if mode == "divide":
            if b != 0:
                values.append(a / b)
        elif mode == "net":
            total = a + b
            if total != 0:
                values.append((a - b) / total)
    return values


def ownership_summary(history: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for field in ("top_holders_pct", "dev_balance_pct"):
        points = metric_points(history, "audit", field)
        if points:
            start = points[0][1]
            current = points[-1][1]
            result[field] = {
                "start": rounded(start),
                "current": rounded(current),
                "change_pp": rounded(current - start),
            }
    dev_mints = metric_points(history, "audit", "dev_mints")
    if dev_mints:
        result["dev_mints_current"] = rounded(dev_mints[-1][1])
    return result


def activity_summary(buckets: list[dict[str, Any]]) -> dict[str, Any]:
    field_names: set[str] = set()
    for bucket in buckets:
        stats = bucket.get("stats_1h")
        if isinstance(stats, dict):
            field_names.update(
                key
                for key, value in stats.items()
                if isinstance(value, dict) and "last" in value
            )

    fields: dict[str, Any] = {}
    for field in sorted(field_names):
        values = [
            float(value)
            for bucket in buckets
            if (value := bucket_last(bucket, "stats_1h", field)) is not None
        ]
        if values:
            fields[field] = {
                "current": rounded(values[-1]),
                "median": rounded(percentile(values, 0.5)),
            }

    derived: dict[str, Any] = {}
    for name, left, right, mode in (
        (
            "buy_sell_volume_ratio",
            ("stats_1h", "buy_volume"),
            ("stats_1h", "sell_volume"),
            "divide",
        ),
        (
            "net_flow_ratio",
            ("stats_1h", "buy_volume"),
            ("stats_1h", "sell_volume"),
            "net",
        ),
        (
            "buy_sell_count_ratio",
            ("stats_1h", "num_buys"),
            ("stats_1h", "num_sells"),
            "divide",
        ),
    ):
        values = ratio_values(buckets, left, right, mode)
        if values:
            derived[name] = summarize_values(values)

    result: dict[str, Any] = {}
    if fields:
        result["fields"] = fields
    if derived:
        result["derived"] = derived
    return result


def organic_summary(
    history: list[dict[str, Any]],
    buckets: list[dict[str, Any]],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    score = metric_points(history, "organic_score")
    if score:
        values = [value for _, value in score]
        result["score"] = {
            "start": rounded(values[0]),
            "current": rounded(values[-1]),
            "median": rounded(percentile(values, 0.5)),
        }

    shares: list[float] = []
    for bucket in buckets:
        buy = bucket_last(bucket, "stats_1h", "buy_volume")
        sell = bucket_last(bucket, "stats_1h", "sell_volume")
        organic_buy = bucket_last(bucket, "stats_1h", "buy_organic_volume")
        organic_sell = bucket_last(bucket, "stats_1h", "sell_organic_volume")
        if None in (buy, sell, organic_buy, organic_sell):
            continue
        total = float(buy) + float(sell)
        if total != 0:
            shares.append((float(organic_buy) + float(organic_sell)) / total)
    if shares:
        result["volume_share"] = summarize_values(shares)
    return result


def derived_summary(
    history: list[dict[str, Any]],
    buckets: list[dict[str, Any]],
    duration_seconds: float,
    resolution_minutes: int,
) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "history": {
            "hours": rounded(duration_seconds / 3600, 4),
            "resolution_minutes": resolution_minutes,
            "observations": len(history),
            "buckets": len(buckets),
            "from": history[0]["t"],
            "to": history[-1]["t"],
        }
    }

    market_cap = metric_summary(history, "market_cap", peak_and_drawdown=True)
    if market_cap:
        summary["market_cap"] = market_cap

    liquidity = metric_summary(history, "liquidity")
    if liquidity:
        ratios = ratio_values(
            buckets,
            ("liquidity",),
            ("market_cap",),
            "divide",
        )
        if ratios:
            liquidity["liquidity_to_market_cap"] = summarize_values(ratios)
        summary["liquidity"] = liquidity

    holders = metric_summary(history, "holders")
    if holders:
        summary["holders"] = holders

    ownership = ownership_summary(history)
    if ownership:
        summary["ownership"] = ownership

    activity = activity_summary(buckets)
    if activity:
        summary["activity_1h"] = activity

    organic = organic_summary(history, buckets)
    if organic:
        summary["organic"] = organic

    return summary


def projected_payload_sql() -> str:
    fields = (
        "id name symbol dev icon website twitter decimals tokenProgram launchpad "
        "createdAt firstPool isVerified mintAuthority freezeAuthority circSupply "
        "totalSupply mcap liquidity holderCount organicScore audit stats1h apy updatedAt"
    ).split()
    parts = ",\n                ".join(
        f"'{field}', payload->'{field}'" for field in fields
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
    load_dotenv()
    database_url = args.database_url or os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        raise SystemExit("DATABASE_URL is not configured.")

    rows = load_rows(database_url, args.mint)
    if not rows:
        raise SystemExit(f"No mint_snapshots found for: {args.mint}")

    times = [row["observed_at"] for row in rows]
    payloads = [row["payload"] for row in rows]
    duration_seconds = (times[-1] - times[0]).total_seconds()
    resolution_minutes = (
        1 if duration_seconds <= ONE_MINUTE_MAX_HISTORY_HOURS * 3600 else 5
    )

    header, dynamic_supply = build_header(args.mint, payloads)
    history = [
        history_row(row["observed_at"], row["payload"], dynamic_supply)
        for row in rows
    ]
    buckets = make_buckets(history, resolution_minutes)
    summary = derived_summary(
        history,
        buckets,
        duration_seconds,
        resolution_minutes,
    )

    llm_context = {
        "token": header,
        "summary": summary,
        "temporal_history": {
            "resolution_minutes": resolution_minutes,
            "buckets": buckets,
        },
    }
    size = context_size(llm_context)

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
        "projection": {
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
                "the model must inspect temporal_history and use it to confirm, "
                "qualify, or challenge summary; judgment from summary alone is forbidden"
            ),
        },
        "notes": {
            "missing": "missing stays missing; no zero fill or interpolation",
            "rolling_stats": (
                "stats_1h is rolling source data; medians use bucket-last values and "
                "rolling values are never summed across buckets"
            ),
            "token_estimate": "characters / 4 is only a rough comparison metric",
        },
    }

    output_dir = Path(
        args.out or f"history_inspection_{args.mint[:12]}"
    ).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
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
    print("LLM PROJECTION")
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
        "Summary is derived context only. The future system prompt must require "
        "temporal_history inspection and forbid judgment from summary alone."
    )
    print()
    print(f"Output: {output_dir}")
    print("Files: llm_context.json, report.json")


if __name__ == "__main__":
    main()
