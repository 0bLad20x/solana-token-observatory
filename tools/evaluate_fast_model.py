from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from observatory.analyst import AnalystError, query_current_tokens

CASES: tuple[tuple[str, dict[str, Any] | None], ...] = (
    (
        "Which five tokens have the highest market cap?",
        {"sort_by": "market_cap", "sort_order": "desc", "limit": 5, "launchpad": None},
    ),
    (
        "Show the 3 pump.fun tokens with the lowest liquidity.",
        {"sort_by": "liquidity", "sort_order": "asc", "limit": 3, "launchpad": "pump.fun"},
    ),
    (
        "Welche 4 Tokens haben die meisten Holder?",
        {"sort_by": "holders", "sort_order": "desc", "limit": 4, "launchpad": None},
    ),
    (
        "Top 7 by 5m volume",
        {"sort_by": "volume_5m", "sort_order": "desc", "limit": 7, "launchpad": None},
    ),
    (
        "Which 2 tokens have the fewest distinct traders in the last 5 minutes?",
        {"sort_by": "traders_5m", "sort_order": "asc", "limit": 2, "launchpad": None},
    ),
    (
        "Show the 5 youngest tokens.",
        {"sort_by": "age_seconds", "sort_order": "asc", "limit": 5, "launchpad": None},
    ),
    (
        "Which 5 tokens have gone longest without a source-data change?",
        {"sort_by": "change_age_seconds", "sort_order": "desc", "limit": 5, "launchpad": None},
    ),
    ("Which tokens have the highest 1h volume?", None),
    ("Which token is best?", None),
)


def sample_tokens() -> list[dict[str, Any]]:
    tokens: list[dict[str, Any]] = []
    launchpads = ("pump.fun", "bags.fun", "meteora")
    for index in range(1, 25):
        tokens.append(
            {
                "mint": f"1111111111111111111111111111111{index % 9 + 1}",
                "name": f"Token {index}",
                "symbol": f"T{index}",
                "launchpad": launchpads[index % len(launchpads)],
                "tracking_enabled": True,
                "market_cap": float(index * 1000),
                "liquidity": float(index * 100),
                "holders": index * 10,
                "trades_5m": index * 2,
                "traders_5m": index,
                "volume_5m": float(index * 50),
                "age_seconds": index * 60,
                "change_age_seconds": index * 30,
            }
        )
    return tokens


async def evaluate(model: str, api_key: str) -> bool:
    tokens = sample_tokens()
    passed = 0
    print(f"FAST MODEL CONTRACT · {model}")
    print()

    for question, expected in CASES:
        try:
            result = await query_current_tokens(
                api_key=api_key,
                model=model,
                tokens=tokens,
                question=question,
            )
            actual = result["tool"]["arguments"] if result.get("tool") else None
            ok = actual == expected
        except AnalystError as error:
            actual = f"ERROR: {error}"
            ok = False

        passed += int(ok)
        print(f"{'PASS' if ok else 'FAIL'} · {question}")
        if not ok:
            print(f"  expected: {expected}")
            print(f"  actual:   {actual}")

    print()
    print(f"RESULT {passed}/{len(CASES)}")
    return passed == len(CASES)


def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env")
    parser = argparse.ArgumentParser(
        description="Evaluate one Mistral FAST candidate against query_tokens semantics."
    )
    parser.add_argument(
        "--model",
        default=os.getenv("MISTRAL_MODEL_FAST", "ministral-3b-latest"),
    )
    args = parser.parse_args()

    api_key = os.getenv("MISTRAL_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("MISTRAL_API_KEY is required")

    ok = asyncio.run(evaluate(args.model, api_key))
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
