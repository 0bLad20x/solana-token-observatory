from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from config import Settings


DEFAULT_INPUT = Path("data/gmgn_mints.jsonl")

INSERT_SQL = """
    INSERT INTO gmgn_mint_observations (
        run_id,
        mint,
        source,
        market_cap,
        liquidity,
        volume_24h,
        holder_count,
        priority_fee,
        tip_fee,
        trade_fee,
        total_fee,
        bot_degen_count,
        bot_degen_rate,
        smart_degen_count,
        bundler_mhr,
        bundler_trader_amount_rate,
        sniper_count,
        top70_sniper_hold_rate,
        fresh_wallet_rate,
        rat_trader_amount_rate,
        suspected_insider_hold_rate,
        rug_ratio,
        entrapment_ratio,
        dev_team_hold_rate,
        burn_status,
        is_honeypot,
        is_wash_trading,
        creator_token_status,
        creator_created_count,
        creator_created_open_ratio,
        raw_data
    )
    VALUES (
        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
        %s
    )
    ON CONFLICT (run_id, mint) DO NOTHING
"""


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None

    text = str(value).strip()
    return text or None


def _optional_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value

    if value is None:
        return None

    text = str(value).strip().lower()

    if text in {"true", "yes", "1"}:
        return True

    if text in {"false", "no", "0"}:
        return False

    return None


def _extract_data(
    record: dict[str, Any],
    line_number: int,
) -> dict[str, Any]:
    raw_records = record.get("raw_records")

    if not isinstance(raw_records, list) or not raw_records:
        raise ValueError(
            f"line {line_number}: raw_records is missing or empty"
        )

    raw = raw_records[0]

    if not isinstance(raw, dict):
        raise ValueError(
            f"line {line_number}: raw_records[0] is not an object"
        )

    data = raw.get("data", raw)

    if not isinstance(data, dict):
        raise ValueError(
            f"line {line_number}: GMGN data is not an object"
        )

    return data


def _to_row(
    record: dict[str, Any],
    line_number: int,
) -> tuple[Any, ...]:
    try:
        run_id = _parse_datetime(record["run_id"])
        mint = record["mint_address"]
        source = record["source"]
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(
            f"line {line_number}: invalid identity fields"
        ) from exc

    data = _extract_data(record, line_number)

    return (
        run_id,
        mint,
        source,

        data.get("market_cap"),
        data.get("liquidity"),
        data.get("volume_24h"),
        data.get("holder_count"),

        data.get("priority_fee"),
        data.get("tip_fee"),
        data.get("trade_fee"),
        data.get("total_fee"),

        data.get("bot_degen_count"),
        data.get("bot_degen_rate"),
        data.get("smart_degen_count"),

        data.get("bundler_mhr"),
        data.get("bundler_trader_amount_rate"),

        data.get("sniper_count"),
        data.get("top70_sniper_hold_rate"),

        data.get("fresh_wallet_rate"),
        data.get("rat_trader_amount_rate"),
        data.get("suspected_insider_hold_rate"),

        data.get("rug_ratio"),
        data.get("entrapment_ratio"),
        data.get("dev_team_hold_rate"),

        _optional_text(data.get("burn_status")),
        _optional_bool(data.get("is_honeypot")),
        _optional_bool(data.get("is_wash_trading")),

        _optional_text(data.get("creator_token_status")),
        data.get("creator_created_count"),
        data.get("creator_created_open_ratio"),

        Jsonb(data),
    )


def load_rows(path: Path) -> list[tuple[Any, ...]]:
    rows: list[tuple[Any, ...]] = []

    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue

            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"line {line_number}: invalid JSON"
                ) from exc

            if not isinstance(record, dict):
                raise ValueError(
                    f"line {line_number}: JSON value is not an object"
                )

            rows.append(_to_row(record, line_number))

    return rows


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Upload GMGN mint observations to PostgreSQL."
    )

    parser.add_argument(
        "--file",
        type=Path,
        default=DEFAULT_INPUT,
        help=f"JSONL input file (default: {DEFAULT_INPUT})",
    )

    args = parser.parse_args()

    rows = load_rows(args.file)

    if not rows:
        print("No GMGN records found.")
        return

    settings = Settings.from_env()

    with psycopg.connect(settings.database_url) as connection:
        with connection.cursor() as cursor:
            cursor.executemany(INSERT_SQL, rows)
            inserted = cursor.rowcount

    print(
        f"GMGN upload complete: "
        f"read={len(rows)} "
        f"inserted={inserted} "
        f"skipped={len(rows) - inserted}"
    )


if __name__ == "__main__":
    main()