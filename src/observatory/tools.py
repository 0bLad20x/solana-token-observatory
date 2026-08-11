from __future__ import annotations

from typing import Any

QUERY_FIELDS = (
    "market_cap",
    "liquidity",
    "holders",
    "trades_5m",
    "traders_5m",
    "volume_5m",
    "age_seconds",
    "change_age_seconds",
)
DEFAULT_LIMIT = 5
MAX_LIMIT = 20

QUERY_TOKENS_TOOL = {
    "type": "function",
    "function": {
        "name": "query_tokens",
        "description": (
            "Query the current active Solana token population. Use only the explicitly "
            "available current fields; never substitute one metric for an unavailable "
            "metric such as historical or five-minute price change."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "sort_by": {
                    "type": "string",
                    "enum": list(QUERY_FIELDS),
                    "description": "Current field used to rank the matching tokens.",
                },
                "sort_order": {
                    "type": "string",
                    "enum": ["asc", "desc"],
                    "description": "Ascending or descending rank order.",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": MAX_LIMIT,
                    "description": "Number of rows to return. Defaults to 5.",
                },
                "launchpad": {
                    "type": "string",
                    "description": "Optional exact, case-insensitive launchpad filter.",
                },
            },
            "additionalProperties": False,
        },
    },
}

_ARGUMENTS = {
    "sort_by",
    "sort_order",
    "limit",
    "launchpad",
}
_OUTPUT_FIELDS = (
    "mint",
    "name",
    "symbol",
    "launchpad",
    *QUERY_FIELDS,
)


class QueryToolError(ValueError):
    """Invalid model-produced arguments at the bounded tool boundary."""


def _arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    unknown = set(arguments) - _ARGUMENTS
    if unknown:
        raise QueryToolError(f"unsupported arguments: {', '.join(sorted(unknown))}")

    sort_by = arguments.get("sort_by", "market_cap")
    if sort_by not in QUERY_FIELDS:
        raise QueryToolError("unsupported sort_by field")

    sort_order = arguments.get("sort_order", "desc")
    if sort_order not in {"asc", "desc"}:
        raise QueryToolError("sort_order must be asc or desc")

    limit = arguments.get("limit", DEFAULT_LIMIT)
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise QueryToolError("limit must be an integer")
    if not 1 <= limit <= MAX_LIMIT:
        raise QueryToolError(f"limit must be between 1 and {MAX_LIMIT}")

    launchpad = arguments.get("launchpad")
    if launchpad is not None:
        if not isinstance(launchpad, str) or not launchpad.strip():
            raise QueryToolError("launchpad must be a non-empty string")
        launchpad = launchpad.strip()

    return {
        "sort_by": sort_by,
        "sort_order": sort_order,
        "limit": limit,
        "launchpad": launchpad,
    }


def query_tokens(
    tokens: list[dict[str, Any]], arguments: dict[str, Any]
) -> dict[str, Any]:
    """Filter and rank a bounded current projection without touching operational state."""

    if not isinstance(arguments, dict):
        raise QueryToolError("query_tokens arguments must be an object")
    query = _arguments(arguments)

    matching = [token for token in tokens if token.get("tracking_enabled") is not False]
    if query["launchpad"] is not None:
        launchpad = query["launchpad"].casefold()
        matching = [
            token
            for token in matching
            if str(token.get("launchpad") or "unknown").casefold() == launchpad
        ]

    matching = [token for token in matching if token.get(query["sort_by"]) is not None]
    matching.sort(key=lambda token: token.get("mint", ""))
    matching.sort(
        key=lambda token: token[query["sort_by"]],
        reverse=query["sort_order"] == "desc",
    )

    rows = [
        {field: token.get(field) for field in _OUTPUT_FIELDS}
        for token in matching[: query["limit"]]
    ]
    return {
        "query": query,
        "matched_count": len(matching),
        "returned_count": len(rows),
        "tokens": rows,
    }
