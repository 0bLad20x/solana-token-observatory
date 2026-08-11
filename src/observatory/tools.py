from __future__ import annotations

from collections import Counter
from typing import Any

QUERY_FIELDS = {
    "market_cap": {
        "label": "Market cap",
        "description": "Current market capitalization (Market Cap, MC, Marktkapitalisierung).",
    },
    "liquidity": {
        "label": "Liquidity",
        "description": "Current available liquidity (Liquidity, Liquidität, Liq).",
    },
    "holders": {
        "label": "Holders",
        "description": "Current number of token holders.",
    },
    "trades_5m": {
        "label": "Trades 5m",
        "description": "Number of buys and sells during the last five minutes.",
    },
    "traders_5m": {
        "label": "Traders 5m",
        "description": "Number of distinct traders during the last five minutes.",
    },
    "volume_5m": {
        "label": "Volume 5m",
        "description": "Buy plus sell volume during the last five minutes.",
    },
    "age_seconds": {
        "label": "Token age",
        "description": "Time since the token or its first pool was created.",
    },
    "change_age_seconds": {
        "label": "Last change",
        "description": "Time since the latest observed source-data change.",
    },
}
SORT_ORDERS = {
    "desc": "Highest, largest, most, top; höchste, größte, meiste.",
    "asc": "Lowest, smallest, least, bottom; niedrigste, kleinste, wenigste.",
}
DEFAULT_LIMIT = 5
MAX_LIMIT = 20

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


def query_capabilities(tokens: list[dict[str, Any]]) -> dict[str, Any]:
    launchpad_counts = Counter(
        str(token.get("launchpad") or "unknown")
        for token in tokens
        if token.get("tracking_enabled") is not False
    )
    return {
        "fields": [
            {"key": key, **description}
            for key, description in QUERY_FIELDS.items()
        ],
        "sort_orders": [
            {"key": key, "description": description}
            for key, description in SORT_ORDERS.items()
        ],
        "launchpads": [
            {"value": value, "active_tokens": launchpad_counts[value]}
            for value in sorted(launchpad_counts, key=str.casefold)
        ],
        "default_limit": DEFAULT_LIMIT,
        "maximum_limit": MAX_LIMIT,
    }


def query_tokens_tool(capabilities: dict[str, Any]) -> dict[str, Any]:
    launchpads = [item["value"] for item in capabilities["launchpads"]]
    launchpad_property: dict[str, Any] = {
        "type": "string",
        "description": "Optional launchpad filter using one canonical available value.",
    }
    if launchpads:
        launchpad_property["enum"] = launchpads

    return {
        "type": "function",
        "function": {
            "name": "query_tokens",
            "description": (
                "Query the current active Solana token population. Use only the "
                "provided vocabulary and never substitute an unavailable metric."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "sort_by": {
                        "type": "string",
                        "enum": list(QUERY_FIELDS),
                        "description": "Canonical current field used for ranking.",
                    },
                    "sort_order": {
                        "type": "string",
                        "enum": list(SORT_ORDERS),
                        "description": "Canonical ascending or descending order.",
                    },
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": MAX_LIMIT,
                        "description": "Number of rows to return. Defaults to 5.",
                    },
                    "launchpad": launchpad_property,
                },
                "additionalProperties": False,
            },
        },
    }


def _arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    unknown = set(arguments) - _ARGUMENTS
    if unknown:
        raise QueryToolError(f"unsupported arguments: {', '.join(sorted(unknown))}")

    sort_by = arguments.get("sort_by", "market_cap")
    if sort_by not in QUERY_FIELDS:
        raise QueryToolError("unsupported sort_by field")

    sort_order = arguments.get("sort_order", "desc")
    if sort_order not in SORT_ORDERS:
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
        launchpads = {
            item["value"].casefold(): item["value"]
            for item in query_capabilities(tokens)["launchpads"]
        }
        launchpad = launchpads.get(query["launchpad"].casefold())
        if launchpad is None:
            raise QueryToolError("unsupported launchpad")
        query["launchpad"] = launchpad
        matching = [
            token
            for token in matching
            if str(token.get("launchpad") or "unknown").casefold()
            == launchpad.casefold()
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
