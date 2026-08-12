from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Any

SUMMARY_SAMPLE_MINUTES = 5
SUMMARY_SAMPLE_SECONDS = SUMMARY_SAMPLE_MINUTES * 60


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


def load_temporal_summary_rows(
    connection: Any,
    mint: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Load exact core history plus sparse fixed-time samples for summary statistics.

    Exact trajectory metrics use all retained observations, but the expensive rolling
    stats1h JSON is fetched only once per five-minute sample interval. This keeps the
    summary exact where needed while avoiding repeated transfer of the same large rolling
    payload on tens of thousands of snapshots.
    """

    history = list(
        connection.execute(
            """
            SELECT
                observed_at,
                payload->>'mcap' AS market_cap,
                payload->>'liquidity' AS liquidity,
                payload->>'holderCount' AS holders,
                payload->>'organicScore' AS organic_score,
                payload->'audit'->>'devMints' AS dev_mints,
                payload->'audit'->>'devBalancePercentage' AS dev_balance_pct,
                payload->'audit'->>'topHoldersPercentage' AS top_holders_pct
            FROM mint_snapshots
            WHERE mint = %s
              AND observed_at >= CURRENT_TIMESTAMP - INTERVAL '24 hours'
            ORDER BY observed_at ASC
            """,
            (mint,),
        ).fetchall()
    )
    if not history:
        return [], []

    samples = list(
        connection.execute(
            f"""
            WITH candidates AS (
                SELECT
                    observed_at,
                    payload,
                    FLOOR(EXTRACT(EPOCH FROM observed_at) / {SUMMARY_SAMPLE_SECONDS})::bigint
                        AS sample_bucket
                FROM mint_snapshots
                WHERE mint = %s
                  AND observed_at >= CURRENT_TIMESTAMP - INTERVAL '24 hours'
            )
            SELECT DISTINCT ON (sample_bucket)
                observed_at,
                payload->>'mcap' AS market_cap,
                payload->>'liquidity' AS liquidity,
                payload->>'organicScore' AS organic_score,
                payload->'stats1h' AS stats_1h
            FROM candidates
            ORDER BY sample_bucket ASC, observed_at DESC
            """,
            (mint,),
        ).fetchall()
    )
    return history, samples


def _normalize_history(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for source in rows:
        observed_at = source.get("observed_at")
        if not isinstance(observed_at, datetime):
            continue
        row: dict[str, Any] = {"t": iso(observed_at)}
        for key in (
            "market_cap",
            "liquidity",
            "holders",
            "organic_score",
            "dev_mints",
            "dev_balance_pct",
            "top_holders_pct",
        ):
            value = numeric(source.get(key))
            if value is not None:
                row[key] = value
        result.append(row)
    return result


def _normalize_samples(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for source in rows:
        observed_at = source.get("observed_at")
        if not isinstance(observed_at, datetime):
            continue
        row: dict[str, Any] = {"t": iso(observed_at)}
        for key in ("market_cap", "liquidity", "organic_score"):
            value = numeric(source.get(key))
            if value is not None:
                row[key] = value
        stats = numeric_object(source.get("stats_1h"))
        if stats:
            row["stats_1h"] = stats
        result.append(row)
    return result


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
    rows: list[dict[str, Any]],
    *path: str,
) -> list[tuple[str, float]]:
    points: list[tuple[str, float]] = []
    for row in rows:
        value = numeric(get_path(row, *path))
        if value is not None:
            points.append((row["t"], float(value)))
    return points


def _change_pct(start: float, current: float) -> float | None:
    if start == 0:
        return None
    return (current / start - 1) * 100


def _metric_summary(
    rows: list[dict[str, Any]],
    *path: str,
    peak_and_drawdown: bool = False,
) -> dict[str, Any]:
    points = _metric_points(rows, *path)
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
                max_drawdown = min(max_drawdown, (value / running_peak - 1) * 100)
        result["peak_at"] = points[peak_index][0]
        result["max_drawdown_pct"] = rounded(max_drawdown)
    return result


def _sampled_values(rows: list[dict[str, Any]], *path: str) -> list[float]:
    values: list[float] = []
    for row in rows:
        value = numeric(get_path(row, *path))
        if value is not None:
            values.append(float(value))
    return values


def _summarize_values(values: list[float]) -> dict[str, Any]:
    if not values:
        return {}
    return {
        "current": rounded(values[-1]),
        "median": rounded(_percentile(values, 0.5)),
        "min": rounded(min(values)),
        "max": rounded(max(values)),
    }


def _ratio_values(
    rows: list[dict[str, Any]],
    left: tuple[str, ...],
    right: tuple[str, ...],
    mode: str,
) -> list[float]:
    values: list[float] = []
    for row in rows:
        a = numeric(get_path(row, *left))
        b = numeric(get_path(row, *right))
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
        points = _metric_points(history, field)
        if points:
            start = points[0][1]
            current = points[-1][1]
            result[field] = {
                "start": rounded(start),
                "current": rounded(current),
                "change_pp": rounded(current - start),
            }
    dev_mints = _metric_points(history, "dev_mints")
    if dev_mints:
        result["dev_mints_current"] = rounded(dev_mints[-1][1])
    return result


def _activity_summary(samples: list[dict[str, Any]]) -> dict[str, Any]:
    field_names: set[str] = set()
    for sample in samples:
        stats = sample.get("stats_1h")
        if isinstance(stats, dict):
            field_names.update(
                key for key, value in stats.items() if numeric(value) is not None
            )

    fields: dict[str, Any] = {}
    for field in sorted(field_names):
        values = _sampled_values(samples, "stats_1h", field)
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
        values = _ratio_values(samples, left, right, mode)
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
    samples: list[dict[str, Any]],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    score = _metric_points(history, "organic_score")
    if score:
        sampled_scores = _sampled_values(samples, "organic_score")
        result["score"] = {
            "start": rounded(score[0][1]),
            "current": rounded(score[-1][1]),
            "median": rounded(_percentile(sampled_scores, 0.5))
            if sampled_scores
            else None,
        }

    shares: list[float] = []
    for sample in samples:
        buy = numeric(get_path(sample, "stats_1h", "buy_volume"))
        sell = numeric(get_path(sample, "stats_1h", "sell_volume"))
        organic_buy = numeric(get_path(sample, "stats_1h", "buy_organic_volume"))
        organic_sell = numeric(get_path(sample, "stats_1h", "sell_organic_volume"))
        if None in (buy, sell, organic_buy, organic_sell):
            continue
        total = float(buy) + float(sell)
        if total != 0:
            shares.append((float(organic_buy) + float(organic_sell)) / total)
    if shares:
        result["volume_share"] = _summarize_values(shares)
    return result


def build_temporal_summary(
    history_rows: list[dict[str, Any]],
    sample_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    history = _normalize_history(history_rows)
    if not history:
        raise ValueError("temporal summary requires at least one observation")
    samples = _normalize_samples(sample_rows or history_rows)

    start = datetime.fromisoformat(history[0]["t"])
    end = datetime.fromisoformat(history[-1]["t"])
    duration_seconds = max(0.0, (end - start).total_seconds())
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
        ratios = _ratio_values(samples, ("liquidity",), ("market_cap",), "divide")
        if ratios:
            liquidity["liquidity_to_market_cap"] = _summarize_values(ratios)
        summary["liquidity"] = liquidity

    holders = _metric_summary(history, "holders")
    if holders:
        summary["holders"] = holders

    ownership = _ownership_summary(history)
    if ownership:
        summary["ownership"] = ownership

    activity = _activity_summary(samples)
    if activity:
        summary["activity_1h"] = activity

    organic = _organic_summary(history, samples)
    if organic:
        summary["organic"] = organic

    return summary


def build_temporal_summary_bundle(
    mint: str,
    history_rows: list[dict[str, Any]],
    sample_rows: list[dict[str, Any]] | None = None,
    token: dict[str, Any] | None = None,
) -> dict[str, Any]:
    identity = {"mint": mint}
    if token:
        for key in ("name", "symbol", "launchpad"):
            value = token.get(key)
            if value not in (None, ""):
                identity[key] = value
    return {
        "token": identity,
        "summary": build_temporal_summary(history_rows, sample_rows),
    }
