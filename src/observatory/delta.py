from __future__ import annotations

from typing import Any

DELTA_NUMERIC_FIELDS = (
    "market_cap",
    "liquidity",
    "holders",
    "trades_5m",
    "traders_5m",
    "volume_5m",
)

FINGERPRINT_FIELDS = (
    "tracking_enabled",
    "source_updated_at",
    "last_changed_at",
    *DELTA_NUMERIC_FIELDS,
)


def fingerprint(token: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(token.get(field) for field in FINGERPRINT_FIELDS)


def numeric_change(
    before: float | int | None,
    after: float | int | None,
) -> dict[str, float | None]:
    if before is None or after is None:
        return {"absolute": None, "percent": None}
    absolute = float(after) - float(before)
    percent = None if before == 0 else absolute / abs(float(before)) * 100.0
    return {"absolute": absolute, "percent": percent}


def changes(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    return {
        field: numeric_change(before.get(field), after.get(field))
        for field in DELTA_NUMERIC_FIELDS
    }
