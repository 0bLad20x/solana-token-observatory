from __future__ import annotations

import argparse
import hashlib
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

BUCKET_MINUTES = (1, 5, 15)
_MISSING = object()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Inspect one mint_snapshots history and compare the raw Jupiter "
            "payload size with the current LLM-oriented temporal contract."
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
    parser.add_argument(
        "--profile-fields",
        action="store_true",
        help=(
            "Fetch full raw payloads and profile every JSON path. This is "
            "intentionally expensive and is disabled by default."
        ),
    )
    parser.add_argument(
        "--write-raw",
        action="store_true",
        help="Fetch and write raw.json. Disabled by default because it is large.",
    )
    parser.add_argument(
        "--top-fields",
        type=int,
        default=30,
        help="Number of changing raw payload paths to print with --profile-fields.",
    )
    return parser.parse_args()


def iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat()


def json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return iso(value)
    raise TypeError(f"Cannot JSON-serialize {type(value).__name__}")


def compact_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        default=json_default,
    )


def size_metrics(value: Any) -> dict[str, int]:
    text = compact_json(value)
    return {
        "characters": len(text),
        "utf8_bytes": len(text.encode("utf-8")),
        "estimated_llm_tokens_chars_div_4": math.ceil(len(text) / 4),
    }


def human_bytes(value: int) -> str:
    size = float(value)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.2f} {unit}"
        size /= 1024
    return f"{size:.2f} GB"


def human_duration(seconds: float | None) -> str:
    if seconds is None:
        return "n/a"
    seconds = max(0.0, seconds)
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes = seconds / 60
    if minutes < 60:
        return f"{minutes:.2f}m"
    hours = minutes / 60
    if hours < 24:
        return f"{hours:.2f}h"
    return f"{hours / 24:.2f}d"


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * q
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def numeric(value: Any) -> int | float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def snake_case(value: str) -> str:
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value)
    value = re.sub(r"[^a-zA-Z0-9]+", "_", value)
    return value.strip("_").lower()


def value_fingerprint(value: Any) -> str:
    return hashlib.sha1(compact_json(value).encode("utf-8")).hexdigest()


def reduction_pct(raw_bytes: int, candidate_bytes: int) -> float:
    if raw_bytes <= 0:
        return 0.0
    return round((1 - candidate_bytes / raw_bytes) * 100, 4)


def write_json(path: Path, value: Any) -> int:
    path.write_text(
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            default=json_default,
        ),
        encoding="utf-8",
    )
    return path.stat().st_size


def get_path(value: dict[str, Any], *path: str) -> Any:
    current: Any = value
    for part in path:
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def last_non_null(payloads: list[dict[str, Any]], *path: str) -> Any:
    for payload in reversed(payloads):
        value = get_path(payload, *path)
        if value is not None:
            return value
    return None


def distinct_non_null_values(
    payloads: list[dict[str, Any]],
    *path: str,
) -> dict[str, Any]:
    fingerprints: dict[str, Any] = {}
    present = 0
    for payload in payloads:
        value = get_path(payload, *path)
        if value is None:
            continue
        present += 1
        fingerprints.setdefault(value_fingerprint(value), value)
    return {
        "present": present,
        "missing": len(payloads) - present,
        "unique_count": len(fingerprints),
        "values": list(fingerprints.values()),
    }


def compact_dict(value: dict[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if item is not None}


def numeric_object(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}

    result: dict[str, Any] = {}
    for key, child in value.items():
        normalized_key = snake_case(str(key))
        if isinstance(child, dict):
            nested = numeric_object(child)
            if nested:
                result[normalized_key] = nested
            continue
        number = numeric(child)
        if number is not None:
            result[normalized_key] = number
    return result


HEADER_STABILITY_FIELDS = {
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
    "first_pool_id": ("firstPool", "id"),
    "first_pool_created_at": ("firstPool", "createdAt"),
    "is_verified": ("isVerified",),
    "mint_authority": ("mintAuthority",),
    "freeze_authority": ("freezeAuthority",),
    "mint_authority_disabled": ("audit", "mintAuthorityDisabled"),
    "freeze_authority_disabled": ("audit", "freezeAuthorityDisabled"),
}


def build_header(
    mint: str,
    payloads: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any], set[str]]:
    header: dict[str, Any] = {"mint": mint}
    stability: dict[str, Any] = {}

    for output_name, path in HEADER_STABILITY_FIELDS.items():
        stats = distinct_non_null_values(payloads, *path)
        stability[output_name] = {
            "present": stats["present"],
            "missing": stats["missing"],
            "unique_values": stats["unique_count"],
            "stable": stats["unique_count"] <= 1,
        }

    header.update(
        compact_dict(
            {
                "name": last_non_null(payloads, "name"),
                "symbol": last_non_null(payloads, "symbol"),
                "dev": last_non_null(payloads, "dev"),
                "icon": last_non_null(payloads, "icon"),
                "website": last_non_null(payloads, "website"),
                "twitter": last_non_null(payloads, "twitter"),
                "decimals": last_non_null(payloads, "decimals"),
                "token_program": last_non_null(payloads, "tokenProgram"),
                "launchpad": last_non_null(payloads, "launchpad"),
                "created_at": last_non_null(payloads, "createdAt"),
            }
        )
    )

    first_pool = compact_dict(
        {
            "id": last_non_null(payloads, "firstPool", "id"),
            "created_at": last_non_null(payloads, "firstPool", "createdAt"),
        }
    )
    if first_pool:
        header["first_pool"] = first_pool

    is_verified = last_non_null(payloads, "isVerified")
    if is_verified is not None:
        header["verification"] = {"is_verified": is_verified}

    authorities = compact_dict(
        {
            "mint_authority": last_non_null(payloads, "mintAuthority"),
            "freeze_authority": last_non_null(payloads, "freezeAuthority"),
            "mint_authority_disabled": last_non_null(
                payloads, "audit", "mintAuthorityDisabled"
            ),
            "freeze_authority_disabled": last_non_null(
                payloads, "audit", "freezeAuthorityDisabled"
            ),
        }
    )
    if authorities:
        header["authorities"] = authorities

    dynamic_supply: set[str] = set()
    constant_supply: dict[str, Any] = {}
    for output_name, path in {
        "circulating": ("circSupply",),
        "total": ("totalSupply",),
    }.items():
        stats = distinct_non_null_values(payloads, *path)
        stability[f"supply.{output_name}"] = {
            "present": stats["present"],
            "missing": stats["missing"],
            "unique_values": stats["unique_count"],
            "stable": stats["unique_count"] <= 1,
        }
        if stats["unique_count"] == 1:
            constant_supply[output_name] = stats["values"][0]
        elif stats["unique_count"] > 1:
            dynamic_supply.add(output_name)

    if constant_supply:
        header["supply"] = constant_supply

    return header, stability, dynamic_supply


def extract_history_row(
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
        audit_result = compact_dict(
            {
                "dev_mints": numeric(audit.get("devMints")),
                "dev_balance_pct": numeric(audit.get("devBalancePercentage")),
                "top_holders_pct": numeric(audit.get("topHoldersPercentage")),
            }
        )
        if audit_result:
            row["audit"] = audit_result

    stats_1h = numeric_object(payload.get("stats1h"))
    if stats_1h:
        row["stats_1h"] = stats_1h

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


def flatten_numeric_history(
    value: Any,
    prefix: str = "",
) -> dict[str, int | float]:
    result: dict[str, int | float] = {}
    if not isinstance(value, dict):
        return result

    for key, child in value.items():
        if key in {"t", "bucket_start", "bucket_end", "observations"}:
            continue
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(child, dict):
            result.update(flatten_numeric_history(child, path))
            continue
        number = numeric(child)
        if number is not None:
            result[path] = number
    return result


def set_nested(target: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    current = target
    for part in parts[:-1]:
        current = current.setdefault(part, {})
    current[parts[-1]] = value


def parse_iso_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def bucket_start(value: datetime, minutes: int) -> datetime:
    seconds = minutes * 60
    floored = math.floor(value.timestamp() / seconds) * seconds
    return datetime.fromtimestamp(floored, tz=timezone.utc)


def aggregate_bucket(
    rows: list[dict[str, Any]],
    start: datetime,
    minutes: int,
) -> dict[str, Any]:
    end = datetime.fromtimestamp(
        start.timestamp() + minutes * 60,
        tz=timezone.utc,
    )
    values_by_path: dict[str, list[int | float]] = defaultdict(list)

    for row in rows:
        for path, value in flatten_numeric_history(row).items():
            values_by_path[path].append(value)

    result: dict[str, Any] = {
        "bucket_start": iso(start),
        "bucket_end": iso(end),
        "observations": len(rows),
    }

    for path in sorted(values_by_path):
        values = values_by_path[path]
        set_nested(
            result,
            path,
            {
                "first": values[0],
                "last": values[-1],
                "min": min(values),
                "max": max(values),
                "samples": len(values),
            },
        )

    return result


def make_buckets(
    history: list[dict[str, Any]],
    minutes: int,
) -> list[dict[str, Any]]:
    grouped: dict[datetime, list[dict[str, Any]]] = defaultdict(list)
    for row in history:
        observed_at = parse_iso_datetime(row["t"])
        grouped[bucket_start(observed_at, minutes)].append(row)

    return [
        aggregate_bucket(grouped[start], start, minutes)
        for start in sorted(grouped)
    ]


def gap_metrics(observed_times: list[datetime]) -> dict[str, float | int | None]:
    gaps = [
        (after - before).total_seconds()
        for before, after in zip(observed_times, observed_times[1:])
    ]
    if not gaps:
        return {
            "count": 0,
            "min_seconds": None,
            "median_seconds": None,
            "p90_seconds": None,
            "p95_seconds": None,
            "max_seconds": None,
            "mean_seconds": None,
        }
    return {
        "count": len(gaps),
        "min_seconds": min(gaps),
        "median_seconds": percentile(gaps, 0.50),
        "p90_seconds": percentile(gaps, 0.90),
        "p95_seconds": percentile(gaps, 0.95),
        "max_seconds": max(gaps),
        "mean_seconds": sum(gaps) / len(gaps),
    }


def projected_payload_sql() -> str:
    return """
        jsonb_strip_nulls(
            jsonb_build_object(
                'id', payload->'id',
                'name', payload->'name',
                'symbol', payload->'symbol',
                'dev', payload->'dev',
                'icon', payload->'icon',
                'website', payload->'website',
                'twitter', payload->'twitter',
                'decimals', payload->'decimals',
                'tokenProgram', payload->'tokenProgram',
                'launchpad', payload->'launchpad',
                'createdAt', payload->'createdAt',
                'firstPool', payload->'firstPool',
                'isVerified', payload->'isVerified',
                'mintAuthority', payload->'mintAuthority',
                'freezeAuthority', payload->'freezeAuthority',
                'circSupply', payload->'circSupply',
                'totalSupply', payload->'totalSupply',
                'mcap', payload->'mcap',
                'liquidity', payload->'liquidity',
                'holderCount', payload->'holderCount',
                'organicScore', payload->'organicScore',
                'audit', payload->'audit',
                'stats1h', payload->'stats1h',
                'apy', payload->'apy'
            )
        )
    """


def load_history(
    database_url: str,
    mint: str,
) -> tuple[dict[str, Any] | None, dict[str, Any], list[dict[str, Any]]]:
    with psycopg.connect(
        database_url,
        row_factory=dict_row,
        autocommit=True,
        options=(
            "-c default_transaction_read_only=on "
            "-c statement_timeout=60000"
        ),
    ) as connection:
        metadata = connection.execute(
            """
            SELECT
                mint,
                name,
                symbol,
                tracking_enabled,
                priority,
                created_at,
                first_pool_created_at,
                first_observed_at,
                last_polled_at,
                last_changed_at,
                source_updated_at,
                disabled_at,
                disabled_reason
            FROM mints
            WHERE mint = %s
            """,
            (mint,),
        ).fetchone()

        summary = connection.execute(
            """
            SELECT
                COUNT(*) AS snapshots,
                COUNT(DISTINCT payload->>'updatedAt') AS unique_updated_at,
                COALESCE(SUM(octet_length(payload::text)), 0) AS raw_payload_bytes,
                COALESCE(SUM(length(payload::text)), 0) AS raw_payload_characters
            FROM mint_snapshots
            WHERE mint = %s
            """,
            (mint,),
        ).fetchone()

        projection = projected_payload_sql()
        rows = connection.execute(
            f"""
            SELECT
                observed_at,
                {projection} AS payload
            FROM mint_snapshots
            WHERE mint = %s
            ORDER BY observed_at ASC
            """,
            (mint,),
        ).fetchall()

    return metadata, dict(summary), list(rows)


def load_raw_rows(database_url: str, mint: str) -> list[dict[str, Any]]:
    with psycopg.connect(
        database_url,
        row_factory=dict_row,
        autocommit=True,
        options=(
            "-c default_transaction_read_only=on "
            "-c statement_timeout=60000"
        ),
    ) as connection:
        return list(
            connection.execute(
                """
                SELECT observed_at, payload
                FROM mint_snapshots
                WHERE mint = %s
                ORDER BY observed_at ASC
                """,
                (mint,),
            ).fetchall()
        )


def leaf_values(value: Any, prefix: str = "") -> dict[str, Any]:
    if not isinstance(value, dict):
        return {prefix or "$": value}

    result: dict[str, Any] = {}
    for key, child in value.items():
        path = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(child, dict):
            result.update(leaf_values(child, path))
        else:
            result[path] = child
    return result


def profile_payload_fields(
    payloads: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    total = len(payloads)
    presence: dict[str, int] = defaultdict(int)
    unique: dict[str, set[str]] = defaultdict(set)
    changes: dict[str, int] = defaultdict(int)
    previous: dict[str, Any] = {}

    for index, payload in enumerate(payloads):
        leaves = leaf_values(payload)
        current_paths = set(leaves)
        all_paths = current_paths | set(previous)

        for path in current_paths:
            presence[path] += 1
            unique[path].add(value_fingerprint(leaves[path]))

        if index > 0:
            for path in all_paths:
                before = previous.get(path, _MISSING)
                after = leaves.get(path, _MISSING)
                if before is _MISSING or after is _MISSING:
                    if before is not after:
                        changes[path] += 1
                    continue
                if value_fingerprint(before) != value_fingerprint(after):
                    changes[path] += 1

        previous = leaves

    rows = []
    for path in set(presence) | set(changes):
        present = presence[path]
        rows.append(
            {
                "path": path,
                "present": present,
                "presence_pct": round(present / total * 100, 4) if total else 0.0,
                "missing": total - present,
                "unique_values": len(unique[path]),
                "consecutive_changes": changes[path],
                "change_pct": (
                    round(changes[path] / (total - 1) * 100, 4)
                    if total > 1
                    else 0.0
                ),
            }
        )

    rows.sort(
        key=lambda row: (
            -row["consecutive_changes"],
            -row["unique_values"],
            row["path"],
        )
    )
    return rows


def serializable_metadata(metadata: dict[str, Any] | None) -> dict[str, Any] | None:
    if metadata is None:
        return None
    return {
        key: iso(value) if isinstance(value, datetime) else value
        for key, value in metadata.items()
    }


def main() -> None:
    args = parse_args()
    load_dotenv()
    database_url = args.database_url or os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        raise SystemExit("DATABASE_URL is not configured.")

    output_dir = Path(
        args.out or f"history_inspection_{args.mint[:12]}"
    ).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    metadata, source_summary, rows = load_history(database_url, args.mint)
    if metadata is None:
        raise SystemExit(f"Mint not found in mints: {args.mint}")
    if not rows:
        raise SystemExit(f"No mint_snapshots found for: {args.mint}")

    observed_times = [row["observed_at"] for row in rows]
    payloads = [row["payload"] for row in rows]
    duration_seconds = (observed_times[-1] - observed_times[0]).total_seconds()

    header, header_stability, dynamic_supply = build_header(args.mint, payloads)
    history = [
        extract_history_row(row["observed_at"], row["payload"], dynamic_supply)
        for row in rows
    ]
    full_contract = {"token": header, "history": history}

    bucket_sets = {
        minutes: make_buckets(history, minutes)
        for minutes in BUCKET_MINUTES
    }
    bucket_contracts = {
        minutes: {"token": header, "history": bucket_sets[minutes]}
        for minutes in BUCKET_MINUTES
    }

    full_size = size_metrics(full_contract)
    bucket_sizes = {
        minutes: size_metrics(bucket_contracts[minutes])
        for minutes in BUCKET_MINUTES
    }

    raw_bytes = int(source_summary["raw_payload_bytes"] or 0)
    raw_characters = int(source_summary["raw_payload_characters"] or 0)
    raw_estimated_tokens = math.ceil(raw_characters / 4)

    unstable_header_fields = [
        field
        for field, info in header_stability.items()
        if info["unique_values"] > 1 and not field.startswith("supply.")
    ]

    field_profile: list[dict[str, Any]] = []
    raw_rows: list[dict[str, Any]] | None = None
    if args.profile_fields or args.write_raw:
        raw_rows = load_raw_rows(database_url, args.mint)
    if args.profile_fields and raw_rows is not None:
        field_profile = profile_payload_fields(
            [row["payload"] for row in raw_rows]
        )

    report: dict[str, Any] = {
        "mint": args.mint,
        "database_metadata": serializable_metadata(metadata),
        "history": {
            "snapshots": len(rows),
            "unique_updated_at": int(source_summary["unique_updated_at"] or 0),
            "duplicate_updated_at_rows": (
                len(rows) - int(source_summary["unique_updated_at"] or 0)
            ),
            "first_observed_at": iso(observed_times[0]),
            "last_observed_at": iso(observed_times[-1]),
            "duration_seconds": duration_seconds,
            "gap_statistics": gap_metrics(observed_times),
        },
        "llm_contract": {
            "header": header,
            "header_stability": header_stability,
            "unstable_header_fields": unstable_header_fields,
            "dynamic_supply_fields": sorted(dynamic_supply),
            "history_fields": {
                "core": [
                    "t",
                    "market_cap",
                    "liquidity",
                    "holders",
                    "organic_score",
                ],
                "audit": [
                    "dev_mints",
                    "dev_balance_pct",
                    "top_holders_pct",
                ],
                "stats": "all numeric fields available under stats1h",
                "apy": "all numeric fields available under apy",
                "supply": (
                    "circSupply/totalSupply only when they vary over history"
                ),
            },
            "explicitly_excluded": [
                "fdv",
                "usdPrice",
                "priceBlockId",
                "organicScoreLabel",
                "tags",
                "stats5m",
                "stats6h",
                "stats24h",
                "updatedAt",
            ],
        },
        "representations": {
            "raw_payload_text": {
                "rows": len(rows),
                "characters": raw_characters,
                "utf8_bytes": raw_bytes,
                "estimated_llm_tokens_chars_div_4": raw_estimated_tokens,
                "note": "payload text only; observed_at wrapper is not included",
            },
            "llm_full": {
                "rows": len(history),
                **full_size,
                "reduction_vs_raw_payload_pct": reduction_pct(
                    raw_bytes,
                    full_size["utf8_bytes"],
                ),
            },
        },
        "payload_field_profile": field_profile,
        "notes": {
            "token_estimate": (
                "estimated_llm_tokens_chars_div_4 is a rough comparison metric only"
            ),
            "default_query": (
                "The normal path projects only contract-relevant JSON fields in "
                "PostgreSQL. Full raw payloads are fetched only for --profile-fields "
                "or --write-raw."
            ),
        },
    }

    for minutes in BUCKET_MINUTES:
        size = bucket_sizes[minutes]
        report["representations"][f"llm_{minutes}m"] = {
            "buckets": len(bucket_sets[minutes]),
            **size,
            "reduction_vs_raw_payload_pct": reduction_pct(
                raw_bytes,
                size["utf8_bytes"],
            ),
            "reduction_vs_llm_full_pct": reduction_pct(
                full_size["utf8_bytes"],
                size["utf8_bytes"],
            ),
        }

    write_json(output_dir / "llm_full.json", full_contract)
    for minutes in BUCKET_MINUTES:
        write_json(
            output_dir / f"llm_{minutes}m.json",
            bucket_contracts[minutes],
        )
    if args.write_raw and raw_rows is not None:
        write_json(
            output_dir / "raw.json",
            [
                {
                    "observed_at": iso(row["observed_at"]),
                    "payload": row["payload"],
                }
                for row in raw_rows
            ],
        )
    write_json(output_dir / "report.json", report)

    print()
    print("# TOKEN HISTORY INSPECTOR")
    print()
    print(f"Mint:       {args.mint}")
    print(f"Name:       {header.get('name') or '-'}")
    print(f"Symbol:     {header.get('symbol') or '-'}")
    print(f"Snapshots:  {len(rows):,}")
    print(f"updatedAt:  {int(source_summary['unique_updated_at'] or 0):,} unique")
    print(
        "Duplicates:  "
        f"{len(rows) - int(source_summary['unique_updated_at'] or 0):,} rows"
    )
    print(f"From:       {iso(observed_times[0])}")
    print(f"To:         {iso(observed_times[-1])}")
    print(f"Duration:   {human_duration(duration_seconds)}")

    gaps = report["history"]["gap_statistics"]
    print()
    print("SNAPSHOT GAPS")
    print(
        "min={min}  median={median}  p90={p90}  p95={p95}  max={max}".format(
            min=human_duration(gaps["min_seconds"]),
            median=human_duration(gaps["median_seconds"]),
            p90=human_duration(gaps["p90_seconds"]),
            p95=human_duration(gaps["p95_seconds"]),
            max=human_duration(gaps["max_seconds"]),
        )
    )

    print()
    print("LLM HEADER")
    print(json.dumps(header, ensure_ascii=False, indent=2))

    print()
    print("HEADER VALIDATION")
    if unstable_header_fields:
        print("WARNING: candidate header fields changed during history:")
        for field in unstable_header_fields:
            print(
                f"  {field}: "
                f"{header_stability[field]['unique_values']} unique values"
            )
    else:
        print("All candidate header fields were stable when present.")

    if dynamic_supply:
        print("Dynamic supply kept in history: " + ", ".join(sorted(dynamic_supply)))
    else:
        print("Supply is constant or absent.")

    print()
    print("REPRESENTATION SIZE")
    print(
        f"{'representation':<16} "
        f"{'rows':>10} "
        f"{'size':>12} "
        f"{'est.tokens':>14} "
        f"{'vs raw':>10}"
    )
    print("-" * 68)
    print(
        f"{'raw payload':<16} "
        f"{len(rows):>10,} "
        f"{human_bytes(raw_bytes):>12} "
        f"{raw_estimated_tokens:>14,} "
        f"{'0.00%':>10}"
    )
    print(
        f"{'llm full':<16} "
        f"{len(history):>10,} "
        f"{human_bytes(full_size['utf8_bytes']):>12} "
        f"{full_size['estimated_llm_tokens_chars_div_4']:>14,} "
        f"{reduction_pct(raw_bytes, full_size['utf8_bytes']):>9.2f}%"
    )
    for minutes in BUCKET_MINUTES:
        size = bucket_sizes[minutes]
        print(
            f"{f'llm {minutes}m':<16} "
            f"{len(bucket_sets[minutes]):>10,} "
            f"{human_bytes(size['utf8_bytes']):>12} "
            f"{size['estimated_llm_tokens_chars_div_4']:>14,} "
            f"{reduction_pct(raw_bytes, size['utf8_bytes']):>9.2f}%"
        )

    if args.profile_fields:
        print()
        print(
            f"TOP {min(args.top_fields, len(field_profile))} "
            "CHANGING RAW PAYLOAD PATHS"
        )
        print(
            f"{'path':<46} "
            f"{'presence':>10} "
            f"{'unique':>8} "
            f"{'changes':>9}"
        )
        print("-" * 78)
        for item in field_profile[: args.top_fields]:
            print(
                f"{item['path'][:46]:<46} "
                f"{item['presence_pct']:>9.2f}% "
                f"{item['unique_values']:>8,} "
                f"{item['consecutive_changes']:>9,}"
            )

    print()
    print(f"Output: {output_dir}")
    files = [
        "llm_full.json",
        "llm_1m.json",
        "llm_5m.json",
        "llm_15m.json",
        "report.json",
    ]
    if args.write_raw:
        files.insert(0, "raw.json")
    print("Files: " + ", ".join(files))


if __name__ == "__main__":
    main()
