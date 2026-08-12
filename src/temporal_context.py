from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

ONE_MINUTE_MAX_HISTORY_HOURS = 6.0
SUMMARY_SAMPLE_MINUTES = 5
TEMPORAL_SOURCE_FIELDS = (
    "id",
    "name",
    "symbol",
    "dev",
    "icon",
    "website",
    "twitter",
    "decimals",
    "tokenProgram",
    "launchpad",
    "createdAt",
    "firstPool",
    "isVerified",
    "mintAuthority",
    "freezeAuthority",
    "circSupply",
    "totalSupply",
    "mcap",
    "liquidity",
    "holderCount",
    "organicScore",
    "audit",
    "stats1h",
    "apy",
    "updatedAt",
)


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


def _last_present(payloads: list[dict[str, Any]], *path: str) -> Any:
    for payload in reversed(payloads):
        value = get_path(payload, *path)
        if value is not None:
            return value
    return None


def _distinct_present(payloads: list[dict[str, Any]], *path: str) -> list[Any]:
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


def build_token_header(
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
        value = _last_present(payloads, *path)
        if value is not None:
            header[output] = value

    first_pool = {
        "id": _last_present(payloads, "firstPool", "id"),
        "created_at": _last_present(payloads, "firstPool", "createdAt"),
    }
    first_pool = {key: value for key, value in first_pool.items() if value is not None}
    if first_pool:
        header["first_pool"] = first_pool

    verified = _last_present(payloads, "isVerified")
    if verified is not None:
        header["verification"] = {"is_verified": verified}

    authorities = {
        "mint_authority": _last_present(payloads, "mintAuthority"),
        "freeze_authority": _last_present(payloads, "freezeAuthority"),
        "mint_authority_disabled": _last_present(
            payloads, "audit", "mintAuthorityDisabled"
        ),
        "freeze_authority_disabled": _last_present(
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
        values = _distinct_present(payloads, *path)
        if len(values) == 1:
            constant_supply[output] = values[0]
        elif len(values) > 1:
            dynamic_supply.add(output)
    if constant_supply:
        header["supply"] = constant_supply

    return header, dynamic_supply


def normalize_observation(
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


def _normalized(
    mint: str,
    rows: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if not rows:
        raise ValueError("temporal context requires at least one snapshot")

    payloads = [row["payload"] for row in rows]
    header, dynamic_supply = build_token_header(mint, payloads)
    history = [
        normalize_observation(row["observed_at"], row["payload"], dynamic_supply)
        for row in rows
    ]
    return header, history


def _flatten_numeric(value: Any, prefix: str = "") -> dict[str, float | int]:
    result: dict[str, float | int] = {}
    if not isinstance(value, dict):
        return result
    for key, child in value.items():
        if key == "t":
            continue
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(child, dict):
            result.update(_flatten_numeric(child, path))
        else:
            number = numeric(child)
            if number is not None:
                result[path] = number
    return result


def _set_path(target: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    current = target
    for part in parts[:-1]:
        current = current.setdefault(part, {})
    current[parts[-1]] = value


def make_buckets(history: list[dict[str, Any]], minutes: int) -> list[dict[str, Any]]:
    if minutes <= 0:
        raise ValueError("bucket minutes must be positive")
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
            for path, value in _flatten_numeric(row).items():
                values_by_path[path].append(value)

        bucket: dict[str, Any] = {
            "bucket_start": iso(datetime.fromtimestamp(start_ts, tz=timezone.utc)),
            "bucket_end": iso(
                datetime.fromtimestamp(start_ts + seconds, tz=timezone.utc)
            ),
            "observations": len(rows),
        }
        for path, values in sorted(values_by_path.items()):
            _set_path(
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


def _percentile(values: list[float], q: float) -> float | None:
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


def _metric_points(
    history: list[dict[str, Any]],
    *path: str,
) -> list[tuple[str, float]]:
    points: list[tuple[str, float]] = []
    for row in history:
        value = numeric(get_path(row, *path))
        if value is not None:
            points.append((row["t"], float(value)))
    return points


def _change_pct(start: float, current: float) -> float | None:
    if start == 0:
        return None
    return (current / start - 1) * 100


def _metric_summary(
    history: list[dict[str, Any]],
    *path: str,
    peak_and_drawdown: bool = False,
) -> dict[str, Any]:
    points = _metric_points(history, *path)
    if not points:
        return {}
    values = [value for _, value in points]
    result: dict[str, Any] = {
        "start": rounded(values[0]),
        "current": rounded(values[-1]),
        "min": rounded(min(values)),
        "max": rounded(max(values)),
        "change_pct": rounded(_change_pct(values[0], values[-1])),
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


def _bucket_last(bucket: dict[str, Any], *path: str) -> float | None:
    metric = get_path(bucket, *path)
    if not isinstance(metric, dict):
        return None
    return numeric(metric.get("last"))


def _summarize_values(values: list[float]) -> dict[str, Any]:
    if not values:
        return {}
    return {
        "current": rounded(values[-1]),
        "median": rounded(_percentile(values, 0.5)),
        "min": rounded(min(values)),
        "max": rounded(max(values)),
    }


def _sampled_values(
    buckets: list[dict[str, Any]],
    *path: str,
) -> list[float]:
    return [
        float(value)
        for bucket in buckets
        if (value := _bucket_last(bucket, *path)) is not None
    ]


def _ratio_values(
    buckets: list[dict[str, Any]],
    left: tuple[str, ...],
    right: tuple[str, ...],
    mode: str,
) -> list[float]:
    values: list[float] = []
    for bucket in buckets:
        a = _bucket_last(bucket, *left)
        b = _bucket_last(bucket, *right)
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


def _ownership_summary(history: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for field in ("top_holders_pct", "dev_balance_pct"):
        points = _metric_points(history, "audit", field)
        if points:
            start = points[0][1]
            current = points[-1][1]
            result[field] = {
                "start": rounded(start),
                "current": rounded(current),
                "change_pp": rounded(current - start),
            }
    dev_mints = _metric_points(history, "audit", "dev_mints")
    if dev_mints:
        result["dev_mints_current"] = rounded(dev_mints[-1][1])
    return result


def _activity_summary(sampled_buckets: list[dict[str, Any]]) -> dict[str, Any]:
    field_names: set[str] = set()
    for bucket in sampled_buckets:
        stats = bucket.get("stats_1h")
        if isinstance(stats, dict):
            field_names.update(
                key
                for key, value in stats.items()
                if isinstance(value, dict) and "last" in value
            )

    fields: dict[str, Any] = {}
    for field in sorted(field_names):
        values = _sampled_values(sampled_buckets, "stats_1h", field)
        if values:
            fields[field] = {
                "current": rounded(values[-1]),
                "median": rounded(_percentile(values, 0.5)),
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
        values = _ratio_values(sampled_buckets, left, right, mode)
        if values:
            derived[name] = _summarize_values(values)

    result: dict[str, Any] = {}
    if fields:
        result["fields"] = fields
    if derived:
        result["derived"] = derived
    return result


def _organic_summary(
    history: list[dict[str, Any]],
    sampled_buckets: list[dict[str, Any]],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    score = _metric_points(history, "organic_score")
    if score:
        sampled_scores = _sampled_values(sampled_buckets, "organic_score")
        result["score"] = {
            "start": rounded(score[0][1]),
            "current": rounded(score[-1][1]),
            "median": rounded(_percentile(sampled_scores, 0.5))
            if sampled_scores
            else None,
        }

    shares: list[float] = []
    for bucket in sampled_buckets:
        buy = _bucket_last(bucket, "stats_1h", "buy_volume")
        sell = _bucket_last(bucket, "stats_1h", "sell_volume")
        organic_buy = _bucket_last(bucket, "stats_1h", "buy_organic_volume")
        organic_sell = _bucket_last(bucket, "stats_1h", "sell_organic_volume")
        if None in (buy, sell, organic_buy, organic_sell):
            continue
        total = float(buy) + float(sell)
        if total != 0:
            shares.append((float(organic_buy) + float(organic_sell)) / total)
    if shares:
        result["volume_share"] = _summarize_values(shares)
    return result


def build_temporal_summary(history: list[dict[str, Any]]) -> dict[str, Any]:
    if not history:
        raise ValueError("temporal summary requires at least one observation")

    start = datetime.fromisoformat(history[0]["t"])
    end = datetime.fromisoformat(history[-1]["t"])
    duration_seconds = max(0.0, (end - start).total_seconds())
    sampled_buckets = make_buckets(history, SUMMARY_SAMPLE_MINUTES)

    summary: dict[str, Any] = {
        "history": {
            "hours": rounded(duration_seconds / 3600, 4),
            "observations": len(history),
            "from": history[0]["t"],
            "to": history[-1]["t"],
        }
    }

    market_cap = _metric_summary(history, "market_cap", peak_and_drawdown=True)
    if market_cap:
        summary["market_cap"] = market_cap

    liquidity = _metric_summary(history, "liquidity")
    if liquidity:
        ratios = _ratio_values(
            sampled_buckets,
            ("liquidity",),
            ("market_cap",),
            "divide",
        )
        if ratios:
            liquidity["liquidity_to_market_cap"] = _summarize_values(ratios)
        summary["liquidity"] = liquidity

    holders = _metric_summary(history, "holders")
    if holders:
        summary["holders"] = holders

    ownership = _ownership_summary(history)
    if ownership:
        summary["ownership"] = ownership

    activity = _activity_summary(sampled_buckets)
    if activity:
        summary["activity_1h"] = activity

    organic = _organic_summary(history, sampled_buckets)
    if organic:
        summary["organic"] = organic

    return summary


def choose_temporal_resolution(history: list[dict[str, Any]]) -> int:
    if not history:
        raise ValueError("temporal resolution requires at least one observation")
    start = datetime.fromisoformat(history[0]["t"])
    end = datetime.fromisoformat(history[-1]["t"])
    duration_seconds = max(0.0, (end - start).total_seconds())
    return 1 if duration_seconds <= ONE_MINUTE_MAX_HISTORY_HOURS * 3600 else 5


def build_temporal_history(history: list[dict[str, Any]]) -> dict[str, Any]:
    resolution_minutes = choose_temporal_resolution(history)
    return {
        "resolution_minutes": resolution_minutes,
        "buckets": make_buckets(history, resolution_minutes),
    }


def build_temporal_summary_bundle(
    mint: str,
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    header, history = _normalized(mint, rows)
    return {
        "token": header,
        "summary": build_temporal_summary(history),
    }


def build_temporal_context(
    mint: str,
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    header, history = _normalized(mint, rows)
    return {
        "token": header,
        "summary": build_temporal_summary(history),
        "temporal_history": build_temporal_history(history),
    }
