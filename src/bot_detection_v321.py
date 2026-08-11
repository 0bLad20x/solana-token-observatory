from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from statistics import median, pstdev
from typing import Any, Callable, Literal


WINDOW_MINUTES = {
    "stats5m": 5,
    "stats1h": 60,
    "stats6h": 360,
    "stats24h": 1440,
}

CHECKPOINTS = (10, 30, 60, 120)

# Fixed-grid sampling. No fill-forward.
ACTIVITY_SAMPLE_INTERVAL_MINUTES = 5
ACTIVITY_SAMPLE_TOLERANCE_SECONDS = 30
SHAPE_SAMPLE_INTERVAL_MINUTES = 1
SHAPE_SAMPLE_TOLERANCE_SECONDS = 25

BotLevel = Literal["NONE", "DISCOVERY", "CANDIDATE", "HARD_BOT"]
AnomalyLevel = Literal["NONE", "DISCOVERY", "HIGH"]
Classification = Literal[
    "HARD_BOT",
    "BOT_CANDIDATE",
    "ANOMALY_ONLY",
    "DISCOVERY",
]
DetectorStatus = Literal["FROZEN", "CANDIDATE", "DISCOVERY"]
DetectorScope = Literal["SNAPSHOT", "CROSS_WINDOW", "TEMPORAL"]
EvidenceAxis = Literal[
    "MECHANICAL",
    "ACTIVITY",
    "PARTICIPATION",
    "ECONOMIC_RESPONSE",
    "TEMPORAL",
]

BOT_LEVEL_RANK = {
    "NONE": 0,
    "DISCOVERY": 1,
    "CANDIDATE": 2,
    "HARD_BOT": 3,
}

ANOMALY_LEVEL_RANK = {
    "NONE": 0,
    "DISCOVERY": 1,
    "HIGH": 2,
}


# =============================================================================
# Stable detector contract / registry
# =============================================================================

@dataclass(frozen=True)
class DetectorContract:
    """
    Stable extension contract for every bot/anomaly archetype.

    The future Lifecycle Manager only needs this metadata plus the emitted
    archetype tag. It never needs to know detector internals.
    """

    name: str
    family: str
    axis: EvidenceAxis
    classification: Classification
    status: DetectorStatus
    scope: DetectorScope
    min_age_minutes: int
    needs_history: bool
    required_windows: tuple[str, ...]
    required_features: tuple[str, ...]
    description: str


@dataclass(frozen=True)
class DetectionHit:
    name: str
    family: str
    axis: EvidenceAxis
    classification: Classification
    status: DetectorStatus
    scope: DetectorScope
    window: str
    reasons: tuple[str, ...]
    metrics: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["reasons"] = list(self.reasons)
        return data


@dataclass
class DetectionContext:
    payload: dict[str, Any]
    monitoring_age_minutes: float
    market_age_minutes: float | None
    maturity_age_minutes: float
    age_basis: str
    decision_at: datetime | None
    windows: dict[str, dict[str, Any]]
    cross_window: dict[str, Any]
    temporal: dict[str, Any] | None


DetectorFn = Callable[[DetectionContext, DetectorContract], list[DetectionHit]]


@dataclass(frozen=True)
class RegisteredDetector:
    contract: DetectorContract
    detect: DetectorFn


# =============================================================================
# Primitive helpers
# =============================================================================

def num(value: Any) -> float | None:
    if value is None:
        return None
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def get(payload: dict, *path: str) -> Any:
    value: Any = payload
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def div(a: float | None, b: float | None) -> float | None:
    if a is None or b is None or b == 0:
        return None
    return a / b


def symmetry(a: float | None, b: float | None) -> float | None:
    if a is None or b is None:
        return None
    total = a + b
    if total <= 0:
        return None
    return 1.0 - abs(a - b) / total


def ratio_similarity(a: float | None, b: float | None) -> float | None:
    if a is None or b is None:
        return None
    a = abs(a)
    b = abs(b)
    if max(a, b) == 0:
        return None
    return min(a, b) / max(a, b)


def ge(value: float | None, threshold: float) -> bool:
    return value is not None and value >= threshold


def le(value: float | None, threshold: float) -> bool:
    return value is not None and value <= threshold


def cv(values: list[float | None]) -> float | None:
    clean = [x for x in values if x is not None and math.isfinite(x)]
    if len(clean) < 2:
        return None
    mean = sum(clean) / len(clean)
    if mean == 0:
        return None
    return pstdev(clean) / abs(mean)


def med(values: list[float | None]) -> float | None:
    clean = [x for x in values if x is not None and math.isfinite(x)]
    return median(clean) if clean else None


def linear_r2(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) != len(ys) or len(xs) < 3:
        return None
    mx = sum(xs) / len(xs)
    my = sum(ys) / len(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx == 0 or syy == 0:
        return None
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    r = sxy / math.sqrt(sxx * syy)
    return r * r


def parse_timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def percent_log_move(change_pct: float | None) -> float | None:
    """
    Convert percentage change to absolute log displacement.
    Example: +100% -> abs(log(2)).
    """
    if change_pct is None:
        return None
    multiplier = 1.0 + change_pct / 100.0
    if multiplier <= 0:
        return None
    return abs(math.log(multiplier))


def signed_imbalance(a: float | None, b: float | None) -> float | None:
    if a is None or b is None:
        return None
    total = a + b
    if total <= 0:
        return None
    return (a - b) / total


def median_abs_available(*values: float | None) -> tuple[float | None, int]:
    clean = [abs(v) for v in values if v is not None and math.isfinite(v)]
    return (median(clean), len(clean)) if clean else (None, 0)


# =============================================================================
# Two clocks: market age vs monitoring age
# =============================================================================

def resolve_age_context(
    payload: dict[str, Any],
    *,
    monitoring_age_minutes: float,
    decision_at: datetime | None,
) -> dict[str, Any]:
    created = parse_timestamp(get(payload, "firstPool", "createdAt"))
    market_age = None

    if created is not None and decision_at is not None:
        dt = decision_at
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        market_age = (dt - created).total_seconds() / 60.0
        if market_age < 0:
            market_age = None

    if market_age is not None:
        maturity_age = market_age
        age_basis = "market_age:firstPool.createdAt"
    else:
        maturity_age = monitoring_age_minutes
        age_basis = "monitoring_age:fallback"

    return {
        "first_pool_created_at": created,
        "market_age_minutes": market_age,
        "monitoring_age_minutes": monitoring_age_minutes,
        "maturity_age_minutes": maturity_age,
        "age_basis": age_basis,
    }


# =============================================================================
# Raw + normalized window feature matrix
# =============================================================================

def extract_window(payload: dict, window: str) -> dict[str, Any]:
    """
    Transparent raw Jupiter fields and algebraic transformations only.

    Never used as decision inputs:
      organicScore / organicScoreLabel
      buyOrganicVolume / sellOrganicVolume
      numOrganicBuyers
      any Jupiter bot/organic classification

    numNetBuyers is extracted only as a raw participation diagnostic because
    it is not an Organic-Wallet label. Readiness is measured separately.
    """
    buy_volume = num(get(payload, window, "buyVolume"))
    sell_volume = num(get(payload, window, "sellVolume"))
    num_buys = num(get(payload, window, "numBuys"))
    num_sells = num(get(payload, window, "numSells"))
    traders = num(get(payload, window, "numTraders"))
    net_buyers = num(get(payload, window, "numNetBuyers"))

    total_volume = (
        None
        if buy_volume is None and sell_volume is None
        else (buy_volume or 0.0) + (sell_volume or 0.0)
    )
    total_trades = (
        None
        if num_buys is None and num_sells is None
        else (num_buys or 0.0) + (num_sells or 0.0)
    )

    avg_buy_size = div(buy_volume, num_buys)
    avg_sell_size = div(sell_volume, num_sells)

    mcap = num(get(payload, "mcap"))
    liquidity = num(get(payload, "liquidity"))
    holders = num(get(payload, "holderCount"))
    minutes = WINDOW_MINUTES[window]

    trades_per_trader = div(total_trades, traders)
    trades_per_hour = (
        total_trades * 60.0 / minutes
        if total_trades is not None
        else None
    )
    volume_per_hour = (
        total_volume * 60.0 / minutes
        if total_volume is not None
        else None
    )

    turnover_liquidity = div(total_volume, liquidity)
    turnover_mcap = div(total_volume, mcap)
    turnover_liquidity_per_hour = (
        turnover_liquidity * 60.0 / minutes
        if turnover_liquidity is not None
        else None
    )
    turnover_mcap_per_hour = (
        turnover_mcap * 60.0 / minutes
        if turnover_mcap is not None
        else None
    )

    price_change = num(get(payload, window, "priceChange"))
    holder_change = num(get(payload, window, "holderChange"))
    liquidity_change = num(get(payload, window, "liquidityChange"))
    abs_log_price_move = percent_log_move(price_change)

    response_median_abs_pct, response_fields_available = median_abs_available(
        price_change,
        holder_change,
        liquidity_change,
    )

    price_impact_per_turnover = None
    if (
        abs_log_price_move is not None
        and turnover_liquidity is not None
        and turnover_liquidity > 0
    ):
        price_impact_per_turnover = abs_log_price_move / turnover_liquidity

    churn_per_response = None
    if turnover_liquidity_per_hour is not None and response_median_abs_pct is not None:
        churn_per_response = (
            turnover_liquidity_per_hour
            / (1.0 + response_median_abs_pct)
        )

    trade_size_symmetry = ratio_similarity(avg_buy_size, avg_sell_size)

    return {
        # Identity / current state
        "window": window,
        "window_minutes": minutes,
        "mcap": mcap,
        "liquidity": liquidity,
        "holders": holders,

        # Raw activity
        "buy_volume": buy_volume,
        "sell_volume": sell_volume,
        "total_volume": total_volume,
        "num_buys": num_buys,
        "num_sells": num_sells,
        "total_trades": total_trades,
        "num_traders": traders,
        "num_net_buyers": net_buyers,

        # Trade-size
        "avg_buy_size": avg_buy_size,
        "avg_sell_size": avg_sell_size,
        "avg_trade_size": div(total_volume, total_trades),

        # Mechanical structure
        "volume_symmetry": symmetry(buy_volume, sell_volume),
        "trade_count_symmetry": symmetry(num_buys, num_sells),
        "trade_size_symmetry": trade_size_symmetry,
        "volume_imbalance": signed_imbalance(buy_volume, sell_volume),
        "trade_count_imbalance": signed_imbalance(num_buys, num_sells),

        # Participation / repetition
        "trades_per_trader": trades_per_trader,
        "trades_per_trader_per_hour": (
            trades_per_trader * 60.0 / minutes
            if trades_per_trader is not None
            else None
        ),
        "volume_per_trader": div(total_volume, traders),
        "traders_per_holder": div(traders, holders),
        "trades_per_holder": div(total_trades, holders),
        "net_buyer_share": div(net_buyers, traders),

        # Window-normalized intensity
        "trades_per_hour": trades_per_hour,
        "volume_per_hour": volume_per_hour,
        "turnover_liquidity": turnover_liquidity,
        "turnover_mcap": turnover_mcap,
        "turnover_liquidity_per_hour": turnover_liquidity_per_hour,
        "turnover_mcap_per_hour": turnover_mcap_per_hour,
        "liquidity_mcap_ratio": div(liquidity, mcap),
        "trades_per_dollar": div(total_trades, total_volume),

        # Economic response
        "price_change": price_change,
        "holder_change": holder_change,
        "liquidity_change": liquidity_change,
        "abs_price_change": abs(price_change) if price_change is not None else None,
        "abs_holder_change": abs(holder_change) if holder_change is not None else None,
        "abs_liquidity_change": (
            abs(liquidity_change) if liquidity_change is not None else None
        ),
        "abs_log_price_move": abs_log_price_move,
        "response_median_abs_pct": response_median_abs_pct,
        "response_fields_available": response_fields_available,
        "price_impact_per_turnover": price_impact_per_turnover,
        "churn_per_response": churn_per_response,
    }


def build_analysis_matrix(
    windows: dict[str, dict[str, Any]],
    temporal: dict[str, Any] | None,
) -> dict[str, Any]:
    """
    Universal research matrix. It does not classify a token.

    It is intentionally verbose and stable so downstream clustering / LLM
    analysis can reason about the same elementary quantities.
    """
    per_window: dict[str, Any] = {}

    for name, x in windows.items():
        per_window[name] = {
            "activity": {
                "total_trades": x["total_trades"],
                "trades_per_hour": x["trades_per_hour"],
                "total_volume": x["total_volume"],
                "volume_per_hour": x["volume_per_hour"],
                "avg_trade_size": x["avg_trade_size"],
                "trades_per_dollar": x["trades_per_dollar"],
            },
            "mechanical_structure": {
                "volume_symmetry": x["volume_symmetry"],
                "trade_count_symmetry": x["trade_count_symmetry"],
                "trade_size_symmetry": x["trade_size_symmetry"],
                "volume_imbalance": x["volume_imbalance"],
                "trade_count_imbalance": x["trade_count_imbalance"],
                "trades_per_trader": x["trades_per_trader"],
                "trades_per_trader_per_hour": x["trades_per_trader_per_hour"],
            },
            "participation": {
                "num_traders": x["num_traders"],
                "num_net_buyers": x["num_net_buyers"],
                "net_buyer_share": x["net_buyer_share"],
                "holders": x["holders"],
                "traders_per_holder": x["traders_per_holder"],
                "trades_per_holder": x["trades_per_holder"],
                "volume_per_trader": x["volume_per_trader"],
            },
            "economic_intensity": {
                "turnover_liquidity": x["turnover_liquidity"],
                "turnover_liquidity_per_hour": x["turnover_liquidity_per_hour"],
                "turnover_mcap": x["turnover_mcap"],
                "turnover_mcap_per_hour": x["turnover_mcap_per_hour"],
                "liquidity_mcap_ratio": x["liquidity_mcap_ratio"],
            },
            "economic_response": {
                "price_change": x["price_change"],
                "holder_change": x["holder_change"],
                "liquidity_change": x["liquidity_change"],
                "abs_log_price_move": x["abs_log_price_move"],
                "response_median_abs_pct": x["response_median_abs_pct"],
                "response_fields_available": x["response_fields_available"],
                "price_impact_per_turnover": x["price_impact_per_turnover"],
                "churn_per_response": x["churn_per_response"],
            },
        }

    return {
        "windows": per_window,
        "temporal_structure": temporal,
    }


# =============================================================================
# Feature presence / semantic telemetry - observational only
# =============================================================================

def _presence_metric(value: float | None) -> dict[str, Any]:
    return {
        "present": value is not None,
        "nonzero": value is not None and value != 0,
        "value": value,
    }


def field_presence(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """
    Presence is NOT readiness.

    This function only records whether a value exists, whether it is non-zero,
    and the numeric value observed at this checkpoint. Semantic usefulness is
    evaluated later from presence/nonzero/change behavior across the replay.

    Organic fields remain diagnostic telemetry only and never enter detector
    decisions.
    """
    buy_volume = num(get(payload, "stats5m", "buyVolume"))
    sell_volume = num(get(payload, "stats5m", "sellVolume"))
    buy_org = num(get(payload, "stats5m", "buyOrganicVolume"))
    sell_org = num(get(payload, "stats5m", "sellOrganicVolume"))

    stats5m_volume = (
        None
        if buy_volume is None and sell_volume is None
        else (buy_volume or 0.0) + (sell_volume or 0.0)
    )
    organic_volume = (
        None
        if buy_org is None and sell_org is None
        else (buy_org or 0.0) + (sell_org or 0.0)
    )

    return {
        "mcap": _presence_metric(num(get(payload, "mcap"))),
        "liquidity": _presence_metric(num(get(payload, "liquidity"))),
        "holderCount": _presence_metric(num(get(payload, "holderCount"))),
        "stats5m_volume": _presence_metric(stats5m_volume),
        "stats5m_numTraders": _presence_metric(
            num(get(payload, "stats5m", "numTraders"))
        ),
        "stats5m_numNetBuyers": _presence_metric(
            num(get(payload, "stats5m", "numNetBuyers"))
        ),
        "stats5m_organicVolume_DIAGNOSTIC_ONLY": _presence_metric(
            organic_volume
        ),
        "organicScore_DIAGNOSTIC_ONLY": _presence_metric(
            num(get(payload, "organicScore"))
        ),
    }


# =============================================================================
# Cross-window diagnostics
# =============================================================================

def cross_window_features(windows: dict[str, dict[str, Any]]) -> dict[str, Any]:
    five = windows.get("stats5m")
    hour = windows.get("stats1h")
    if five is None or hour is None:
        return {
            "available": False,
            "volume_rate_similarity_5m_1h": None,
            "trade_rate_similarity_5m_1h": None,
            "avg_trade_size_similarity_5m_1h": None,
            "stats1h_total_trades": None,
            "stats1h_trades_per_trader": None,
        }

    return {
        "available": True,
        "volume_rate_similarity_5m_1h": ratio_similarity(
            five["volume_per_hour"], hour["volume_per_hour"]
        ),
        "trade_rate_similarity_5m_1h": ratio_similarity(
            five["trades_per_hour"], hour["trades_per_hour"]
        ),
        "avg_trade_size_similarity_5m_1h": ratio_similarity(
            five["avg_trade_size"], hour["avg_trade_size"]
        ),
        "stats1h_total_trades": hour["total_trades"],
        "stats1h_trades_per_trader": hour["trades_per_trader"],
    }


# =============================================================================
# Temporal fixed-grid feature layer
# =============================================================================

def make_temporal_point(
    *,
    observed_at: datetime,
    mcap: Any,
    buy_volume: Any,
    sell_volume: Any,
    num_buys: Any,
    num_sells: Any,
    num_traders: Any,
) -> dict[str, Any]:
    bv = num(buy_volume)
    sv = num(sell_volume)
    nb = num(num_buys)
    ns = num(num_sells)
    nt = num(num_traders)

    total_volume = (
        None if bv is None and sv is None else (bv or 0.0) + (sv or 0.0)
    )
    total_trades = (
        None if nb is None and ns is None else (nb or 0.0) + (ns or 0.0)
    )

    return {
        "observed_at": observed_at,
        "mcap": num(mcap),
        "total_volume_5m": total_volume,
        "total_trades_5m": total_trades,
        "num_traders_5m": nt,
        "avg_trade_size_5m": div(total_volume, total_trades),
        "trades_per_trader_5m": div(total_trades, nt),
    }


def fixed_grid_sample(
    points: list[dict[str, Any]],
    *,
    tracking_started_at: datetime,
    decision_at: datetime,
    interval_minutes: int,
    tolerance_seconds: int,
) -> dict[str, Any]:
    """
    At most one ACTUAL stored state per target slot. No fill-forward.
    """
    if decision_at <= tracking_started_at:
        return {
            "samples": [],
            "expected_slots": 0,
            "coverage": None,
            "span_minutes": None,
            "max_gap_minutes": None,
            "last_sample_lag_seconds": None,
        }

    source = sorted(
        (
            p for p in points
            if tracking_started_at <= p["observed_at"] <= decision_at
        ),
        key=lambda p: p["observed_at"],
    )

    expected_slots = int(
        (decision_at - tracking_started_at).total_seconds()
        // (interval_minutes * 60)
    )
    if not source or expected_slots <= 0:
        return {
            "samples": [],
            "expected_slots": max(0, expected_slots),
            "coverage": 0.0 if expected_slots > 0 else None,
            "span_minutes": None,
            "max_gap_minutes": None,
            "last_sample_lag_seconds": None,
        }

    targets = [
        tracking_started_at + timedelta(minutes=interval_minutes * i)
        for i in range(1, expected_slots + 1)
    ]

    sampled: list[dict[str, Any]] = []
    used_times: set[datetime] = set()
    cursor = 0

    for target in targets:
        lower = target - timedelta(seconds=tolerance_seconds)
        upper = target + timedelta(seconds=tolerance_seconds)

        while cursor < len(source) and source[cursor]["observed_at"] < lower:
            cursor += 1

        candidates: list[dict[str, Any]] = []
        j = cursor
        while j < len(source) and source[j]["observed_at"] <= upper:
            if source[j]["observed_at"] not in used_times:
                candidates.append(source[j])
            j += 1

        if not candidates:
            continue

        chosen = min(
            candidates,
            key=lambda p: abs((p["observed_at"] - target).total_seconds()),
        )
        used_times.add(chosen["observed_at"])
        sampled.append({
            **chosen,
            "target_at": target,
            "target_offset_seconds": (
                chosen["observed_at"] - target
            ).total_seconds(),
        })

    span_minutes = None
    max_gap_minutes = None
    last_lag = None

    if len(sampled) >= 2:
        span_minutes = (
            sampled[-1]["observed_at"] - sampled[0]["observed_at"]
        ).total_seconds() / 60.0
        gaps = [
            (b["observed_at"] - a["observed_at"]).total_seconds() / 60.0
            for a, b in zip(sampled, sampled[1:])
        ]
        max_gap_minutes = max(gaps) if gaps else None

    if sampled:
        last_lag = (
            decision_at - sampled[-1]["observed_at"]
        ).total_seconds()

    return {
        "samples": sampled,
        "expected_slots": expected_slots,
        "coverage": len(sampled) / expected_slots if expected_slots else None,
        "span_minutes": span_minutes,
        "max_gap_minutes": max_gap_minutes,
        "last_sample_lag_seconds": last_lag,
    }


def _growth_ratio(late: float | None, early: float | None) -> float | None:
    if late is None or early is None or early <= 0:
        return None
    return late / early


def temporal_features(
    points: list[dict[str, Any]],
    *,
    tracking_started_at: datetime,
    decision_at: datetime,
) -> dict[str, Any]:
    raw = sorted(
        {
            p["observed_at"]: p
            for p in points
            if tracking_started_at <= p["observed_at"] <= decision_at
        }.values(),
        key=lambda p: p["observed_at"],
    )

    activity_grid = fixed_grid_sample(
        raw,
        tracking_started_at=tracking_started_at,
        decision_at=decision_at,
        interval_minutes=ACTIVITY_SAMPLE_INTERVAL_MINUTES,
        tolerance_seconds=ACTIVITY_SAMPLE_TOLERANCE_SECONDS,
    )
    shape_grid = fixed_grid_sample(
        raw,
        tracking_started_at=tracking_started_at,
        decision_at=decision_at,
        interval_minutes=SHAPE_SAMPLE_INTERVAL_MINUTES,
        tolerance_seconds=SHAPE_SAMPLE_TOLERANCE_SECONDS,
    )

    activity = activity_grid["samples"]
    shape = shape_grid["samples"]

    volumes = [p["total_volume_5m"] for p in activity]
    trades = [p["total_trades_5m"] for p in activity]
    avg_sizes = [p["avg_trade_size_5m"] for p in activity]
    tpt = [p["trades_per_trader_5m"] for p in activity]

    # Early/late medians for transaction-spam research.
    split = max(1, len(activity) // 2)
    early = activity[:split]
    late = activity[split:]

    early_trade_med = med([p["total_trades_5m"] for p in early])
    late_trade_med = med([p["total_trades_5m"] for p in late])
    early_volume_med = med([p["total_volume_5m"] for p in early])
    late_volume_med = med([p["total_volume_5m"] for p in late])
    early_size_med = med([p["avg_trade_size_5m"] for p in early])
    late_size_med = med([p["avg_trade_size_5m"] for p in late])

    mcap_points = [
        (p["observed_at"], p["mcap"])
        for p in shape
        if p["mcap"] is not None and p["mcap"] > 0
    ]

    log_returns: list[float] = []
    if len(mcap_points) >= 2:
        for i in range(1, len(mcap_points)):
            prev = mcap_points[i - 1][1]
            curr = mcap_points[i][1]
            if prev and curr and prev > 0 and curr > 0:
                r = math.log(curr / prev)
                if math.isfinite(r):
                    log_returns.append(r)

    signs = [
        1 if r > 0 else -1
        for r in log_returns
        if abs(r) > 1e-12
    ]

    sign_alternation = None
    up_move_ratio = None
    down_move_ratio = None
    monotonic_ratio = None

    if len(signs) >= 2:
        sign_alternation = (
            sum(a != b for a, b in zip(signs, signs[1:]))
            / (len(signs) - 1)
        )

    if signs:
        up = sum(s > 0 for s in signs)
        down = sum(s < 0 for s in signs)
        up_move_ratio = up / len(signs)
        down_move_ratio = down / len(signs)
        monotonic_ratio = max(up_move_ratio, down_move_ratio)

    log_mcap_r2 = None
    total_log_change = None
    if len(mcap_points) >= 3:
        xs = [
            (ts - tracking_started_at).total_seconds() / 60.0
            for ts, _ in mcap_points
        ]
        ys = [math.log(value) for _, value in mcap_points]
        log_mcap_r2 = linear_r2(xs, ys)
        total_log_change = ys[-1] - ys[0]

    # Observation structure from ACTUAL stored change states. These intervals
    # are not poll intervals and are never treated as such.
    stored_change_intervals_seconds = [
        (b["observed_at"] - a["observed_at"]).total_seconds()
        for a, b in zip(raw, raw[1:])
        if b["observed_at"] > a["observed_at"]
    ]
    raw_span_minutes = None
    stored_change_density_per_minute = None
    decision_to_last_stored_change_seconds = None
    if len(raw) >= 2:
        raw_span_minutes = (
            raw[-1]["observed_at"] - raw[0]["observed_at"]
        ).total_seconds() / 60.0
        if raw_span_minutes > 0:
            stored_change_density_per_minute = (len(raw) - 1) / raw_span_minutes
    if raw:
        decision_to_last_stored_change_seconds = max(
            0.0,
            (decision_at - raw[-1]["observed_at"]).total_seconds(),
        )

    return {
        "raw_distinct_source_states": len(raw),
        "stored_change_span_minutes": raw_span_minutes,
        "stored_change_density_per_minute": stored_change_density_per_minute,
        "stored_change_interval_median_seconds": med(stored_change_intervals_seconds),
        "stored_change_interval_cv": cv(stored_change_intervals_seconds),
        "stored_change_interval_max_seconds": (
            max(stored_change_intervals_seconds)
            if stored_change_intervals_seconds else None
        ),
        "decision_to_last_stored_change_seconds": (
            decision_to_last_stored_change_seconds
        ),
        "decision_to_last_stored_change_semantics": (
            "stored_change_gap_not_verified_poll_silence"
        ),

        "activity_sample_interval_minutes": ACTIVITY_SAMPLE_INTERVAL_MINUTES,
        "activity_sample_tolerance_seconds": ACTIVITY_SAMPLE_TOLERANCE_SECONDS,
        "activity_expected_slots": activity_grid["expected_slots"],
        "activity_sampled_states": len(activity),
        "activity_sample_coverage": activity_grid["coverage"],
        "activity_sample_span_minutes": activity_grid["span_minutes"],
        "activity_max_gap_minutes": activity_grid["max_gap_minutes"],
        "activity_last_sample_lag_seconds": activity_grid["last_sample_lag_seconds"],

        "stats5m_volume_cv": cv(volumes),
        "stats5m_trades_cv": cv(trades),
        "stats5m_avg_trade_size_cv": cv(avg_sizes),
        "stats5m_trades_per_trader_cv": cv(tpt),
        "median_stats5m_volume": med(volumes),
        "median_stats5m_trades": med(trades),
        "median_stats5m_trades_per_trader": med(tpt),

        "early_median_stats5m_trades": early_trade_med,
        "late_median_stats5m_trades": late_trade_med,
        "early_median_stats5m_volume": early_volume_med,
        "late_median_stats5m_volume": late_volume_med,
        "early_median_avg_trade_size": early_size_med,
        "late_median_avg_trade_size": late_size_med,
        "trade_count_growth_ratio": _growth_ratio(late_trade_med, early_trade_med),
        "volume_growth_ratio": _growth_ratio(late_volume_med, early_volume_med),
        "avg_trade_size_growth_ratio": _growth_ratio(late_size_med, early_size_med),

        "shape_sample_interval_minutes": SHAPE_SAMPLE_INTERVAL_MINUTES,
        "shape_sample_tolerance_seconds": SHAPE_SAMPLE_TOLERANCE_SECONDS,
        "shape_expected_slots": shape_grid["expected_slots"],
        "shape_sampled_states": len(shape),
        "shape_sample_coverage": shape_grid["coverage"],
        "shape_sample_span_minutes": shape_grid["span_minutes"],
        "shape_max_gap_minutes": shape_grid["max_gap_minutes"],
        "shape_last_sample_lag_seconds": shape_grid["last_sample_lag_seconds"],

        "mcap_states": len(mcap_points),
        "mcap_steps": len(log_returns),
        "sign_alternation_ratio": sign_alternation,
        "up_move_ratio": up_move_ratio,
        "down_move_ratio": down_move_ratio,
        "monotonic_move_ratio": monotonic_ratio,
        "abs_log_return_cv": cv([abs(r) for r in log_returns]),
        "median_abs_log_return": med([abs(r) for r in log_returns]),
        "log_mcap_time_r2": log_mcap_r2,
        "total_log_mcap_change": total_log_change,

        # Explicit sample trace for reproducibility / AI bundle.
        "activity_sample_times": [
            p["observed_at"].isoformat() for p in activity
        ],
        "activity_samples": [
            {
                "observed_at": p["observed_at"].isoformat(),
                "total_volume_5m": p.get("total_volume_5m"),
                "total_trades_5m": p.get("total_trades_5m"),
                "num_traders_5m": p.get("num_traders_5m"),
                "avg_trade_size_5m": p.get("avg_trade_size_5m"),
                "trades_per_trader_5m": p.get("trades_per_trader_5m"),
            }
            for p in activity
        ],
        "shape_sample_times": [
            p["observed_at"].isoformat() for p in shape
        ],
        "shape_samples": [
            {
                "observed_at": p["observed_at"].isoformat(),
                "mcap": p.get("mcap"),
            }
            for p in shape
        ],
    }


# =============================================================================
# Hit helpers
# =============================================================================

def make_hit(
    contract: DetectorContract,
    *,
    window: str,
    reasons: list[str],
    metrics: dict[str, Any],
) -> DetectionHit:
    return DetectionHit(
        name=contract.name,
        family=contract.family,
        axis=contract.axis,
        classification=contract.classification,
        status=contract.status,
        scope=contract.scope,
        window=window,
        reasons=tuple(reasons),
        metrics=metrics,
    )


def for_each_window(
    ctx: DetectionContext,
    contract: DetectorContract,
    predicate: Callable[[dict[str, Any]], tuple[bool, list[str]]],
    metric_keys: tuple[str, ...],
) -> list[DetectionHit]:
    hits: list[DetectionHit] = []
    for x in ctx.windows.values():
        matched, reasons = predicate(x)
        if not matched:
            continue
        hits.append(make_hit(
            contract,
            window=x["window"],
            reasons=reasons,
            metrics={key: x.get(key) for key in metric_keys},
        ))
    return hits


# =============================================================================
# Existing FROZEN detector implementations
#
# IMPORTANT: Threshold semantics are intentionally preserved from V3.1 so
# V3.2 can be compared against the established baseline. Window-normalized
# metrics are now emitted beside them and can be calibrated before a future
# threshold migration.
# =============================================================================

def detect_mirror_engine_ultra(
    ctx: DetectionContext,
    c: DetectorContract,
) -> list[DetectionHit]:
    def pred(x: dict[str, Any]) -> tuple[bool, list[str]]:
        ok = (
            ge(x["total_trades"], 500)
            and ge(x["trades_per_trader"], 20)
            and ge(x["trades_per_trader_per_hour"], 10)
            and ge(x["volume_symmetry"], 0.995)
            and ge(x["trade_count_symmetry"], 0.995)
            and ge(x["trade_size_symmetry"], 0.990)
        )
        return ok, [
            "total_trades>=500",
            "trades_per_trader>=20",
            "trades_per_trader_per_hour>=10",
            "volume_symmetry>=0.995",
            "trade_count_symmetry>=0.995",
            "trade_size_symmetry>=0.990",
        ]

    return for_each_window(
        ctx, c, pred,
        (
            "total_trades", "trades_per_hour", "num_traders",
            "trades_per_trader", "trades_per_trader_per_hour",
            "volume_symmetry", "trade_count_symmetry",
            "trade_size_symmetry", "turnover_liquidity_per_hour",
        ),
    )


def detect_mirror_engine_strong(
    ctx: DetectionContext,
    c: DetectorContract,
) -> list[DetectionHit]:
    def pred(x: dict[str, Any]) -> tuple[bool, list[str]]:
        ok = (
            ge(x["total_trades"], 100)
            and ge(x["trades_per_trader"], 12)
            and ge(x["trades_per_trader_per_hour"], 5)
            and ge(x["volume_symmetry"], 0.985)
            and ge(x["trade_count_symmetry"], 0.980)
            and ge(x["trade_size_symmetry"], 0.950)
        )
        return ok, [
            "total_trades>=100",
            "trades_per_trader>=12",
            "normalized repetition>=5 per trader/hour",
            "volume_symmetry>=0.985",
            "trade_count_symmetry>=0.980",
            "trade_size_symmetry>=0.950",
        ]

    return for_each_window(
        ctx, c, pred,
        (
            "total_trades", "trades_per_hour", "num_traders",
            "trades_per_trader", "trades_per_trader_per_hour",
            "volume_symmetry", "trade_count_symmetry",
            "trade_size_symmetry", "turnover_liquidity_per_hour",
        ),
    )


def detect_fixed_size_engine(
    ctx: DetectionContext,
    c: DetectorContract,
) -> list[DetectionHit]:
    def pred(x: dict[str, Any]) -> tuple[bool, list[str]]:
        ok = (
            ge(x["total_trades"], 500)
            and ge(x["trades_per_trader"], 20)
            and ge(x["trades_per_trader_per_hour"], 5)
            and ge(x["trade_count_symmetry"], 0.980)
            and ge(x["trade_size_symmetry"], 0.985)
        )
        return ok, [
            "total_trades>=500",
            "trades_per_trader>=20",
            "normalized repetition>=5 per trader/hour",
            "trade_count_symmetry>=0.980",
            "trade_size_symmetry>=0.985",
        ]

    return for_each_window(
        ctx, c, pred,
        (
            "total_trades", "trades_per_hour", "num_traders",
            "trades_per_trader", "trade_count_symmetry",
            "trade_size_symmetry", "avg_trade_size",
        ),
    )


def detect_repetitive_trader_ring(
    ctx: DetectionContext,
    c: DetectorContract,
) -> list[DetectionHit]:
    def pred(x: dict[str, Any]) -> tuple[bool, list[str]]:
        traders = x["num_traders"]
        ok = (
            ge(x["total_trades"], 500)
            and traders is not None
            and traders <= 75
            and ge(x["trades_per_trader"], 50)
            and ge(x["trades_per_trader_per_hour"], 10)
            and ge(x["trade_count_symmetry"], 0.970)
        )
        return ok, [
            "total_trades>=500",
            "num_traders<=75",
            "trades_per_trader>=50",
            "normalized repetition>=10 per trader/hour",
            "trade_count_symmetry>=0.970",
        ]

    return for_each_window(
        ctx, c, pred,
        (
            "total_trades", "trades_per_hour", "num_traders",
            "trades_per_trader", "trades_per_trader_per_hour",
            "trade_count_symmetry", "volume_per_trader",
        ),
    )


def detect_high_turnover_ring(
    ctx: DetectionContext,
    c: DetectorContract,
) -> list[DetectionHit]:
    def pred(x: dict[str, Any]) -> tuple[bool, list[str]]:
        ok = (
            ge(x["total_trades"], 300)
            and ge(x["trades_per_trader"], 15)
            and ge(x["trades_per_trader_per_hour"], 10)
            and ge(x["turnover_liquidity"], 20)
            and ge(x["volume_symmetry"], 0.970)
            and ge(x["trade_count_symmetry"], 0.950)
            and ge(x["trade_size_symmetry"], 0.900)
        )
        return ok, [
            "total_trades>=300",
            "trades_per_trader>=15",
            "normalized repetition>=10 per trader/hour",
            "total_volume/liquidity>=20x",
            "volume_symmetry>=0.970",
            "trade_count_symmetry>=0.950",
            "trade_size_symmetry>=0.900",
        ]

    return for_each_window(
        ctx, c, pred,
        (
            "total_trades", "trades_per_hour", "num_traders",
            "trades_per_trader", "turnover_liquidity",
            "turnover_liquidity_per_hour", "volume_symmetry",
            "trade_count_symmetry", "trade_size_symmetry",
        ),
    )


# =============================================================================
# Candidate / discovery detectors
# =============================================================================

def detect_high_frequency_low_depth(
    ctx: DetectionContext,
    c: DetectorContract,
) -> list[DetectionHit]:
    def pred(x: dict[str, Any]) -> tuple[bool, list[str]]:
        ok = (
            ge(x["total_trades"], 1000)
            and ge(x["trades_per_trader"], 10)
            and ge(x["trades_per_trader_per_hour"], 10)
            and ge(x["turnover_liquidity"], 10)
            and ge(x["volume_symmetry"], 0.900)
            and ge(x["trade_count_symmetry"], 0.900)
            and ge(x["trade_size_symmetry"], 0.850)
        )
        return ok, [
            "V3.1 threshold baseline retained",
            "total_trades>=1000",
            "trades_per_trader>=10",
            "normalized repetition>=10 per trader/hour",
            "total_volume/liquidity>=10x",
            "moderately symmetric flow",
        ]

    return for_each_window(
        ctx, c, pred,
        (
            "total_trades", "trades_per_hour", "volume_per_hour",
            "num_traders", "trades_per_trader",
            "trades_per_trader_per_hour", "turnover_liquidity",
            "turnover_liquidity_per_hour", "volume_symmetry",
            "trade_count_symmetry", "trade_size_symmetry",
        ),
    )


def detect_small_trader_ring_review(
    ctx: DetectionContext,
    c: DetectorContract,
) -> list[DetectionHit]:
    def pred(x: dict[str, Any]) -> tuple[bool, list[str]]:
        traders = x["num_traders"]
        ok = (
            ge(x["total_trades"], 100)
            and traders is not None
            and traders <= 25
            and ge(x["trades_per_trader"], 15)
            and ge(x["trades_per_trader_per_hour"], 10)
        )
        return ok, [
            "small trader set",
            "many trades per trader",
            "manual discovery only",
        ]

    return for_each_window(
        ctx, c, pred,
        ("total_trades", "trades_per_hour", "num_traders", "trades_per_trader"),
    )


def detect_broad_mechanical_churn_review(
    ctx: DetectionContext,
    c: DetectorContract,
) -> list[DetectionHit]:
    def pred(x: dict[str, Any]) -> tuple[bool, list[str]]:
        ok = (
            ge(x["total_trades"], 300)
            and ge(x["trades_per_trader"], 8)
            and ge(x["trades_per_trader_per_hour"], 3)
            and ge(x["turnover_liquidity"], 10)
            and ge(x["volume_symmetry"], 0.950)
            and ge(x["trade_count_symmetry"], 0.900)
            and ge(x["trade_size_symmetry"], 0.850)
        )
        return ok, [
            "looser churn screen",
            "raw metrics only",
            "manual discovery only",
        ]

    return for_each_window(
        ctx, c, pred,
        (
            "total_trades", "trades_per_hour", "trades_per_trader",
            "turnover_liquidity", "turnover_liquidity_per_hour",
            "volume_symmetry", "trade_count_symmetry", "trade_size_symmetry",
        ),
    )


def detect_mcap_churn_review(
    ctx: DetectionContext,
    c: DetectorContract,
) -> list[DetectionHit]:
    def pred(x: dict[str, Any]) -> tuple[bool, list[str]]:
        ok = (
            ge(x["total_trades"], 300)
            and ge(x["trades_per_trader"], 8)
            and ge(x["trades_per_trader_per_hour"], 3)
            and ge(x["turnover_mcap"], 5)
            and ge(x["trade_count_symmetry"], 0.900)
        )
        return ok, [
            "total_volume/mcap>=5x",
            "repeated trading",
            "diagnostic only because mcap is manipulable",
        ]

    return for_each_window(
        ctx, c, pred,
        (
            "total_trades", "trades_per_hour", "trades_per_trader",
            "turnover_mcap", "turnover_mcap_per_hour",
            "trade_count_symmetry",
        ),
    )


def detect_cross_window_rate_lock_review(
    ctx: DetectionContext,
    c: DetectorContract,
) -> list[DetectionHit]:
    f = ctx.cross_window
    matched = (
        f.get("available")
        and ge(f.get("stats1h_total_trades"), 1000)
        and ge(f.get("stats1h_trades_per_trader"), 8)
        and ge(f.get("volume_rate_similarity_5m_1h"), 0.80)
        and ge(f.get("trade_rate_similarity_5m_1h"), 0.80)
        and ge(f.get("avg_trade_size_similarity_5m_1h"), 0.80)
    )
    if not matched:
        return []

    return [make_hit(
        c,
        window="stats5m+stats1h",
        reasons=[
            "nested-window stationarity diagnostic",
            "5m hourly-rate ~= 1h rate",
            "trade-rate ~= across windows",
            "avg trade size ~= across windows",
            "supporting evidence only; windows are not independent",
        ],
        metrics=dict(f),
    )]


def detect_fixed_activity_rate_review(
    ctx: DetectionContext,
    c: DetectorContract,
) -> list[DetectionHit]:
    f = ctx.temporal
    if f is None:
        return []

    matched = (
        ge(f.get("activity_sampled_states"), 6)
        and ge(f.get("activity_sample_span_minutes"), 20)
        and ge(f.get("activity_sample_coverage"), 0.70)
        and ge(f.get("median_stats5m_trades"), 50)
        and le(f.get("stats5m_volume_cv"), 0.30)
        and le(f.get("stats5m_trades_cv"), 0.30)
        and le(f.get("stats5m_avg_trade_size_cv"), 0.20)
    )
    if not matched:
        return []

    return [make_hit(
        c,
        window="stats5m_history_5m_grid",
        reasons=[
            ">=6 actual fixed-grid source states",
            ">=20m sampled span",
            ">=70% grid coverage",
            "stats5m volume CV<=0.30",
            "stats5m trades CV<=0.30",
            "avg trade-size CV<=0.20",
        ],
        metrics={
            key: f.get(key)
            for key in (
                "activity_sampled_states",
                "activity_sample_coverage",
                "activity_sample_span_minutes",
                "activity_max_gap_minutes",
                "stats5m_volume_cv",
                "stats5m_trades_cv",
                "stats5m_avg_trade_size_cv",
            )
        },
    )]


def _ramp_guard(f: dict[str, Any]) -> bool:
    return (
        ge(f.get("mcap_steps"), 6)
        and ge(f.get("shape_sample_coverage"), 0.70)
        and ge(f.get("shape_sample_span_minutes"), 6)
        and le(f.get("shape_max_gap_minutes"), 3.0)
        and le(f.get("shape_last_sample_lag_seconds"), 90.0)
        and ge(f.get("log_mcap_time_r2"), 0.98)
    )


def detect_temporal_linear_ramp_up(
    ctx: DetectionContext,
    c: DetectorContract,
) -> list[DetectionHit]:
    f = ctx.temporal
    if f is None:
        return []
    total = f.get("total_log_mcap_change")

    matched = (
        _ramp_guard(f)
        and ge(f.get("up_move_ratio"), 0.90)
        and total is not None
        and total >= math.log(1.8)
    )
    if not matched:
        return []

    return [make_hit(
        c,
        window="mcap_history_1m_grid",
        reasons=[
            "fixed-grid coverage>=70%",
            "max_gap<=3m",
            "last sample close to decision",
            ">=90% positive MC steps",
            "log(MC) vs time R2>=0.98",
            ">=1.8x total MC rise",
            "ANOMALY_ONLY pending independent validation",
        ],
        metrics={
            key: f.get(key)
            for key in (
                "mcap_steps", "shape_sample_coverage",
                "shape_sample_span_minutes", "shape_max_gap_minutes",
                "shape_last_sample_lag_seconds", "up_move_ratio",
                "log_mcap_time_r2", "total_log_mcap_change",
            )
        },
    )]


def detect_temporal_linear_ramp_down(
    ctx: DetectionContext,
    c: DetectorContract,
) -> list[DetectionHit]:
    f = ctx.temporal
    if f is None:
        return []
    total = f.get("total_log_mcap_change")

    matched = (
        _ramp_guard(f)
        and ge(f.get("down_move_ratio"), 0.90)
        and total is not None
        and total <= -math.log(1.8)
    )
    if not matched:
        return []

    return [make_hit(
        c,
        window="mcap_history_1m_grid",
        reasons=[
            "fixed-grid coverage>=70%",
            "max_gap<=3m",
            "last sample close to decision",
            ">=90% negative MC steps",
            "log(MC) vs time R2>=0.98",
            ">=1.8x equivalent MC decline",
            "retire-relevant temporal anomaly; not same mechanism as ramp-up",
        ],
        metrics={
            key: f.get(key)
            for key in (
                "mcap_steps", "shape_sample_coverage",
                "shape_sample_span_minutes", "shape_max_gap_minutes",
                "shape_last_sample_lag_seconds", "down_move_ratio",
                "log_mcap_time_r2", "total_log_mcap_change",
            )
        },
    )]


def detect_temporal_zigzag_review(
    ctx: DetectionContext,
    c: DetectorContract,
) -> list[DetectionHit]:
    f = ctx.temporal
    if f is None:
        return []

    matched = (
        ge(f.get("mcap_steps"), 6)
        and ge(f.get("shape_sample_coverage"), 0.70)
        and ge(f.get("sign_alternation_ratio"), 0.80)
        and le(f.get("abs_log_return_cv"), 0.60)
        and ge(f.get("median_abs_log_return"), 0.01)
    )
    if not matched:
        return []

    return [make_hit(
        c,
        window="mcap_history_1m_grid",
        reasons=[
            "fixed-grid MC series",
            "frequent +/- sign alternation",
            "similar absolute step sizes",
            "non-trivial price movement",
        ],
        metrics={
            key: f.get(key)
            for key in (
                "mcap_steps", "shape_sample_coverage",
                "sign_alternation_ratio", "abs_log_return_cv",
                "median_abs_log_return",
            )
        },
    )]


# =============================================================================
# New V3.2 Economic Response / participation research detectors
# =============================================================================

def detect_economic_null_churn_review(
    ctx: DetectionContext,
    c: DetectorContract,
) -> list[DetectionHit]:
    def pred(x: dict[str, Any]) -> tuple[bool, list[str]]:
        ok = (
            ge(x["total_trades"], 300)
            and ge(x["trades_per_hour"], 1500)
            and ge(x["turnover_liquidity_per_hour"], 20)
            and ge(x["response_fields_available"], 2)
            and le(x["response_median_abs_pct"], 10)
            and le(x["abs_price_change"], 7.5)
        )
        return ok, [
            "high normalized activity",
            "high liquidity turnover/hour",
            ">=2 economic response fields available",
            "median economic response<=10%",
            "price response<=7.5%",
            "research: high gross activity / low net response",
        ]

    return for_each_window(
        ctx, c, pred,
        (
            "total_trades", "trades_per_hour",
            "turnover_liquidity_per_hour",
            "price_change", "holder_change", "liquidity_change",
            "response_median_abs_pct", "churn_per_response",
        ),
    )


def detect_cheap_displacement_review(
    ctx: DetectionContext,
    c: DetectorContract,
) -> list[DetectionHit]:
    def pred(x: dict[str, Any]) -> tuple[bool, list[str]]:
        ok = (
            ge(x["total_trades"], 50)
            and ge(x["abs_price_change"], 50)
            and x["turnover_liquidity"] is not None
            and x["turnover_liquidity"] <= 2.0
            and ge(x["price_impact_per_turnover"], 0.20)
        )
        return ok, [
            "price displacement>=50%",
            "liquidity turnover<=2x in window",
            "log-price displacement / turnover>=0.20",
            "research: large nominal move from relatively small economic impulse",
        ]

    return for_each_window(
        ctx, c, pred,
        (
            "total_trades", "trades_per_hour", "total_volume",
            "liquidity", "mcap", "turnover_liquidity",
            "turnover_liquidity_per_hour", "price_change",
            "abs_log_price_move", "price_impact_per_turnover",
            "holder_change", "num_traders", "num_net_buyers",
        ),
    )


def detect_participation_mismatch_review(
    ctx: DetectionContext,
    c: DetectorContract,
) -> list[DetectionHit]:
    def pred(x: dict[str, Any]) -> tuple[bool, list[str]]:
        holder_weak = (
            x["abs_holder_change"] is not None
            and x["abs_holder_change"] <= 10
        )
        ok = (
            ge(x["total_trades"], 500)
            and ge(x["num_traders"], 100)
            and ge(x["trades_per_hour"], 1000)
            and ge(x["abs_price_change"], 25)
            and holder_weak
        )
        return ok, [
            "substantial trade/trader activity",
            "material price movement",
            "holder growth remains weak",
            "numNetBuyers is exported as supporting telemetry only",
            "numNetBuyers does not trigger this detector until readiness is validated",
        ]

    return for_each_window(
        ctx, c, pred,
        (
            "total_trades", "trades_per_hour", "num_traders",
            "num_net_buyers", "net_buyer_share", "holders",
            "holder_change", "price_change", "trades_per_holder",
            "volume_per_trader",
        ),
    )


def detect_transaction_spam_review(
    ctx: DetectionContext,
    c: DetectorContract,
) -> list[DetectionHit]:
    f = ctx.temporal
    if f is None:
        return []

    matched = (
        ge(f.get("activity_sampled_states"), 6)
        and ge(f.get("activity_sample_coverage"), 0.70)
        and ge(f.get("trade_count_growth_ratio"), 2.0)
        and f.get("volume_growth_ratio") is not None
        and f["volume_growth_ratio"] <= 1.5
        and f.get("avg_trade_size_growth_ratio") is not None
        and f["avg_trade_size_growth_ratio"] <= 0.75
    )
    if not matched:
        return []

    return [make_hit(
        c,
        window="stats5m_history_5m_grid",
        reasons=[
            "trade-count rate increased >=2x",
            "volume increased <=1.5x",
            "average trade size fell to <=75%",
            "fixed-grid activity samples",
            "research: transaction-count / volume decoupling",
        ],
        metrics={
            key: f.get(key)
            for key in (
                "activity_sampled_states",
                "activity_sample_coverage",
                "trade_count_growth_ratio",
                "volume_growth_ratio",
                "avg_trade_size_growth_ratio",
                "early_median_stats5m_trades",
                "late_median_stats5m_trades",
                "early_median_stats5m_volume",
                "late_median_stats5m_volume",
            )
        },
    )]


# =============================================================================
# Registry
# =============================================================================

def C(
    name: str,
    family: str,
    axis: EvidenceAxis,
    classification: Classification,
    status: DetectorStatus,
    scope: DetectorScope,
    min_age_minutes: int,
    needs_history: bool,
    required_windows: tuple[str, ...],
    required_features: tuple[str, ...],
    description: str,
) -> DetectorContract:
    return DetectorContract(
        name=name,
        family=family,
        axis=axis,
        classification=classification,
        status=status,
        scope=scope,
        min_age_minutes=min_age_minutes,
        needs_history=needs_history,
        required_windows=required_windows,
        required_features=required_features,
        description=description,
    )


DETECTORS: tuple[RegisteredDetector, ...] = (
    RegisteredDetector(
        C(
            "mirror_engine_ultra", "mechanical_mirror", "MECHANICAL",
            "HARD_BOT", "FROZEN", "SNAPSHOT", 10, False,
            ("any_mature_window",),
            ("trades", "traders", "buy/sell volume", "buy/sell counts"),
            "Near-perfect mirrored flow under heavy repeated trading.",
        ),
        detect_mirror_engine_ultra,
    ),
    RegisteredDetector(
        C(
            "mirror_engine_strong", "mechanical_mirror", "MECHANICAL",
            "ANOMALY_ONLY", "FROZEN", "SNAPSHOT", 10, False,
            ("any_mature_window",),
            ("trades", "traders", "buy/sell volume", "buy/sell counts"),
            "Broader mirror structure. Retire/anomaly evidence, not bot identity alone.",
        ),
        detect_mirror_engine_strong,
    ),
    RegisteredDetector(
        C(
            "fixed_size_engine", "mechanical_mirror", "MECHANICAL",
            "BOT_CANDIDATE", "FROZEN", "SNAPSHOT", 10, False,
            ("any_mature_window",),
            ("trades", "traders", "average buy/sell size"),
            "Repeated trades with highly similar buy/sell sizing.",
        ),
        detect_fixed_size_engine,
    ),
    RegisteredDetector(
        C(
            "repetitive_trader_ring", "mechanical_mirror", "PARTICIPATION",
            "BOT_CANDIDATE", "FROZEN", "SNAPSHOT", 10, False,
            ("any_mature_window",),
            ("trades", "traders", "trade counts"),
            "Small actor set producing very high repeated trade counts.",
        ),
        detect_repetitive_trader_ring,
    ),
    RegisteredDetector(
        C(
            "high_turnover_ring", "mechanical_mirror", "ACTIVITY",
            "BOT_CANDIDATE", "FROZEN", "SNAPSHOT", 10, False,
            ("any_mature_window",),
            ("volume", "liquidity", "trades", "symmetry"),
            "Heavy repeated mechanical flow relative to pool depth.",
        ),
        detect_high_turnover_ring,
    ),
    RegisteredDetector(
        C(
            "high_frequency_low_depth", "hf_low_depth", "ACTIVITY",
            "BOT_CANDIDATE", "CANDIDATE", "SNAPSHOT", 10, False,
            ("any_mature_window",),
            ("volume", "liquidity", "trades", "traders", "symmetry"),
            "High-frequency churn against shallow depth. V3.1 candidate baseline.",
        ),
        detect_high_frequency_low_depth,
    ),
    RegisteredDetector(
        C(
            "temporal_linear_ramp_up", "linear_ramp", "TEMPORAL",
            "ANOMALY_ONLY", "CANDIDATE", "TEMPORAL", 10, True,
            ("mcap_history_1m_grid",),
            ("mcap history", "grid coverage"),
            "Near-linear monotonic MC rise. Demoted to anomaly until blind validation.",
        ),
        detect_temporal_linear_ramp_up,
    ),
    RegisteredDetector(
        C(
            "temporal_linear_ramp_down", "linear_ramp", "TEMPORAL",
            "ANOMALY_ONLY", "DISCOVERY", "TEMPORAL", 10, True,
            ("mcap_history_1m_grid",),
            ("mcap history", "grid coverage"),
            "Near-linear monotonic MC decline; separate semantics from ramp-up.",
        ),
        detect_temporal_linear_ramp_down,
    ),
    RegisteredDetector(
        C(
            "economic_null_churn_review", "economic_null_churn", "ECONOMIC_RESPONSE",
            "DISCOVERY", "DISCOVERY", "SNAPSHOT", 10, False,
            ("any_mature_window",),
            ("turnover/hour", "trades/hour", "price/holder/liquidity response"),
            "High gross activity with unusually weak economic state response.",
        ),
        detect_economic_null_churn_review,
    ),
    RegisteredDetector(
        C(
            "cheap_displacement_review", "cheap_displacement", "ECONOMIC_RESPONSE",
            "DISCOVERY", "DISCOVERY", "SNAPSHOT", 10, False,
            ("any_mature_window",),
            ("price change", "volume", "liquidity", "turnover"),
            "Large nominal displacement from relatively little turnover.",
        ),
        detect_cheap_displacement_review,
    ),
    RegisteredDetector(
        C(
            "transaction_spam_review", "transaction_spam", "ACTIVITY",
            "DISCOVERY", "DISCOVERY", "TEMPORAL", 30, True,
            ("stats5m_history_5m_grid",),
            ("trade-count history", "volume history", "average trade size"),
            "Trade count accelerates while volume response lags and trade size falls.",
        ),
        detect_transaction_spam_review,
    ),
    RegisteredDetector(
        C(
            "participation_mismatch_review", "participation_mismatch", "PARTICIPATION",
            "DISCOVERY", "DISCOVERY", "SNAPSHOT", 10, False,
            ("any_mature_window",),
            ("traders", "holders", "numNetBuyers if ready", "price movement"),
            "Market movement is not matched by holder/net-buyer participation.",
        ),
        detect_participation_mismatch_review,
    ),
    RegisteredDetector(
        C(
            "fixed_activity_rate_review", "temporal_rate", "TEMPORAL",
            "DISCOVERY", "DISCOVERY", "TEMPORAL", 30, True,
            ("stats5m_history_5m_grid",),
            ("stats5m activity history",),
            "Fixed-grid activity remains unusually constant.",
        ),
        detect_fixed_activity_rate_review,
    ),
    RegisteredDetector(
        C(
            "temporal_zigzag_review", "temporal_shape", "TEMPORAL",
            "DISCOVERY", "DISCOVERY", "TEMPORAL", 10, True,
            ("mcap_history_1m_grid",),
            ("mcap history",),
            "MC path alternates direction with unusually regular step sizes.",
        ),
        detect_temporal_zigzag_review,
    ),
    RegisteredDetector(
        C(
            "cross_window_rate_lock_review", "nested_rate_lock", "TEMPORAL",
            "DISCOVERY", "DISCOVERY", "CROSS_WINDOW", 60, False,
            ("stats5m", "stats1h"),
            ("volume/hour", "trades/hour", "average trade size"),
            "Nested 5m/1h stationarity diagnostic; intentionally not independent evidence.",
        ),
        detect_cross_window_rate_lock_review,
    ),
    RegisteredDetector(
        C(
            "small_trader_ring_review", "broad_discovery", "PARTICIPATION",
            "DISCOVERY", "DISCOVERY", "SNAPSHOT", 10, False,
            ("any_mature_window",),
            ("trades", "traders"),
            "Loose small-actor-set discovery screen.",
        ),
        detect_small_trader_ring_review,
    ),
    RegisteredDetector(
        C(
            "broad_mechanical_churn_review", "broad_discovery", "MECHANICAL",
            "DISCOVERY", "DISCOVERY", "SNAPSHOT", 10, False,
            ("any_mature_window",),
            ("turnover", "trades", "symmetry"),
            "Loose raw mechanical churn screen.",
        ),
        detect_broad_mechanical_churn_review,
    ),
    RegisteredDetector(
        C(
            "mcap_churn_review", "broad_discovery", "ECONOMIC_RESPONSE",
            "DISCOVERY", "DISCOVERY", "SNAPSHOT", 10, False,
            ("any_mature_window",),
            ("volume", "mcap", "trades"),
            "MC-relative churn diagnostic; MC is manipulable.",
        ),
        detect_mcap_churn_review,
    ),
)

DETECTOR_BY_NAME = {d.contract.name: d.contract for d in DETECTORS}


def detector_registry() -> list[dict[str, Any]]:
    return [asdict(d.contract) for d in DETECTORS]


# =============================================================================
# Unified pure evaluation
# =============================================================================

def evaluate_token(
    payload: dict,
    *,
    monitoring_age_minutes: float,
    history_points: list[dict[str, Any]] | None = None,
    tracking_started_at: datetime | None = None,
    decision_at: datetime | None = None,
) -> dict[str, Any]:
    """
    Pure evaluation. No DB access and no writes.

    Production:
      - current successful Search payload enters here
      - market age determines window maturity when firstPool.createdAt exists
      - detector tags are evidence, not a universal score
    """
    age = resolve_age_context(
        payload,
        monitoring_age_minutes=monitoring_age_minutes,
        decision_at=decision_at,
    )

    maturity_age = age["maturity_age_minutes"]
    windows = {
        window: extract_window(payload, window)
        for window, minutes in WINDOW_MINUTES.items()
        if minutes <= maturity_age
    }

    cross = cross_window_features(windows)

    temporal = None
    if (
        history_points is not None
        and tracking_started_at is not None
        and decision_at is not None
    ):
        temporal = temporal_features(
            history_points,
            tracking_started_at=tracking_started_at,
            decision_at=decision_at,
        )

    ctx = DetectionContext(
        payload=payload,
        monitoring_age_minutes=monitoring_age_minutes,
        market_age_minutes=age["market_age_minutes"],
        maturity_age_minutes=maturity_age,
        age_basis=age["age_basis"],
        decision_at=decision_at,
        windows=windows,
        cross_window=cross,
        temporal=temporal,
    )

    hits: list[DetectionHit] = []
    for registered in DETECTORS:
        contract = registered.contract
        eligibility_age = (
            monitoring_age_minutes
            if contract.needs_history
            else maturity_age
        )
        if eligibility_age < contract.min_age_minutes:
            continue
        if contract.needs_history and temporal is None:
            continue
        hits.extend(registered.detect(ctx, contract))

    hard_hits = [h for h in hits if h.classification == "HARD_BOT"]
    candidate_hits = [h for h in hits if h.classification == "BOT_CANDIDATE"]
    anomaly_hits = [h for h in hits if h.classification == "ANOMALY_ONLY"]
    discovery_hits = [h for h in hits if h.classification == "DISCOVERY"]

    if hard_hits:
        bot_level: BotLevel = "HARD_BOT"
    elif candidate_hits:
        bot_level = "CANDIDATE"
    elif anomaly_hits or discovery_hits:
        bot_level = "DISCOVERY"
    else:
        bot_level = "NONE"

    if hard_hits or candidate_hits or anomaly_hits:
        anomaly_level: AnomalyLevel = "HIGH"
    elif discovery_hits:
        anomaly_level = "DISCOVERY"
    else:
        anomaly_level = "NONE"

    tags = sorted({h.name for h in hits})
    families = sorted({h.family for h in hits})
    axes = sorted({h.axis for h in hits})

    observation_quality = "ADEQUATE"
    if not windows:
        observation_quality = "INSUFFICIENT_OBSERVATION"
    elif temporal is not None:
        expected = temporal.get("activity_expected_slots") or 0
        coverage = temporal.get("activity_sample_coverage")
        if expected >= 6 and coverage is not None and coverage < 0.50:
            observation_quality = "SPARSE"

    if observation_quality == "INSUFFICIENT_OBSERVATION":
        analysis_tag = "INSUFFICIENT_OBSERVATION"
    elif hard_hits:
        analysis_tag = "KNOWN_ARCHETYPE"
    elif candidate_hits or anomaly_hits or discovery_hits:
        analysis_tag = "SYSTEMATIC_WARNING"
    else:
        analysis_tag = "NORMAL_RANGE"

    return {
        "age": {
            **age,
            "first_pool_created_at": (
                age["first_pool_created_at"].isoformat()
                if age["first_pool_created_at"] is not None
                else None
            ),
        },
        "bot_level": bot_level,
        "anomaly_level": anomaly_level,
        "analysis_tag": analysis_tag,
        "observation_quality": observation_quality,
        "retire_review": (
            "STRONG_REVIEW" if anomaly_level == "HIGH"
            else "REVIEW" if anomaly_level == "DISCOVERY"
            else "NONE"
        ),
        "archetype_tags": tags,
        "archetype_families": families,
        "evidence_axes": axes,
        "hard_bot_rules": sorted({h.name for h in hard_hits}),
        "candidate_rules": sorted({h.name for h in candidate_hits}),
        "anomaly_only_rules": sorted({h.name for h in anomaly_hits}),
        "discovery_rules": sorted({h.name for h in discovery_hits}),
        "hits": [h.to_dict() for h in hits],
        "windows": windows,
        "analysis_matrix": build_analysis_matrix(windows, temporal),
        "feature_presence": field_presence(payload),
        "cross_window_features": cross,
        "temporal_features": temporal,
    }
