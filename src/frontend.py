from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.sse import EventSourceResponse, ServerSentEvent
from fastapi.staticfiles import StaticFiles
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_DIR = Path(__file__).with_name("frontend")
STREAM_INTERVAL_SECONDS = float(os.getenv("FRONTEND_STREAM_INTERVAL_SECONDS", "2"))
RECENT_DISABLED_MINUTES = int(os.getenv("FRONTEND_RECENT_DISABLED_MINUTES", "5"))

load_dotenv(PROJECT_ROOT / ".env")
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL must be set in .env or the environment")


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    return str(value)


def _float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class FrontendReader:
    """Read-only projection of the operational token state for the local UI."""

    def __init__(self, database_url: str) -> None:
        self._pool = ConnectionPool(
            database_url,
            min_size=1,
            max_size=4,
            open=False,
            kwargs={
                "autocommit": True,
                "options": "-c default_transaction_read_only=on -c statement_timeout=5000",
            },
        )

    def open(self) -> None:
        self._pool.open(wait=True)

    def close(self) -> None:
        self._pool.close()

    def _rows(
        self,
        include_recent_disabled: bool,
        mint: str | None = None,
    ) -> list[dict[str, Any]]:
        params: list[Any] = []
        if include_recent_disabled:
            visibility = """
                (
                    m.tracking_enabled = true
                    OR COALESCE(
                        NULLIF(to_jsonb(m)->>'disabled_at', '')::timestamptz,
                        '-infinity'::timestamptz
                    ) >= NOW() - (%s * INTERVAL '1 minute')
                )
            """
            params.append(RECENT_DISABLED_MINUTES)
        else:
            visibility = "m.tracking_enabled = true"

        if mint is not None:
            visibility += " AND m.mint = %s"
            params.append(mint)

        query = f"""
            SELECT
                m.mint,
                COALESCE(s.payload->>'name', m.name, '') AS name,
                COALESCE(s.payload->>'symbol', m.symbol, '') AS symbol,
                m.tracking_enabled,
                m.created_at,
                m.first_pool_created_at,
                m.first_observed_at,
                m.last_polled_at,
                m.last_changed_at,
                m.source_updated_at,
                to_jsonb(m)->>'disabled_at' AS disabled_at,
                to_jsonb(m)->>'disabled_reason' AS disabled_reason,
                s.observed_at AS snapshot_observed_at,
                COALESCE(NULLIF(s.payload->>'launchpad', ''), 'unknown') AS launchpad,
                NULLIF(s.payload->>'mcap', '')::double precision AS market_cap,
                NULLIF(s.payload->>'liquidity', '')::double precision AS liquidity,
                NULLIF(s.payload->>'holderCount', '')::integer AS holders,
                COALESCE(NULLIF(s.payload->'stats5m'->>'numBuys', '')::integer, 0)
                  + COALESCE(NULLIF(s.payload->'stats5m'->>'numSells', '')::integer, 0)
                    AS trades_5m,
                NULLIF(s.payload->'stats5m'->>'numTraders', '')::integer AS traders_5m,
                COALESCE(NULLIF(s.payload->'stats5m'->>'buyVolume', '')::double precision, 0)
                  + COALESCE(NULLIF(s.payload->'stats5m'->>'sellVolume', '')::double precision, 0)
                    AS volume_5m,
                EXTRACT(EPOCH FROM (
                    NOW() - COALESCE(
                        m.first_pool_created_at,
                        m.created_at,
                        m.first_observed_at,
                        s.observed_at
                    )
                )) AS age_seconds,
                EXTRACT(EPOCH FROM (NOW() - m.last_polled_at)) AS poll_age_seconds,
                EXTRACT(EPOCH FROM (NOW() - m.last_changed_at)) AS change_age_seconds
            FROM mints AS m
            JOIN LATERAL (
                SELECT observed_at, payload
                FROM mint_snapshots
                WHERE mint = m.mint
                ORDER BY observed_at DESC
                LIMIT 1
            ) AS s ON true
            WHERE {visibility}
            ORDER BY m.mint
        """

        with self._pool.connection() as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(query, tuple(params))
                return list(cursor.fetchall())

    @staticmethod
    def _token(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "mint": row["mint"],
            "name": row["name"] or "",
            "symbol": row["symbol"] or "",
            "launchpad": row["launchpad"] or "unknown",
            "tracking_enabled": bool(row["tracking_enabled"]),
            "market_cap": _float(row["market_cap"]),
            "liquidity": _float(row["liquidity"]),
            "holders": _int(row["holders"]),
            "trades_5m": _int(row["trades_5m"]),
            "traders_5m": _int(row["traders_5m"]),
            "volume_5m": _float(row["volume_5m"]),
            "age_seconds": _float(row["age_seconds"]),
            "poll_age_seconds": _float(row["poll_age_seconds"]),
            "change_age_seconds": _float(row["change_age_seconds"]),
            "last_polled_at": _iso(row["last_polled_at"]),
            "last_changed_at": _iso(row["last_changed_at"]),
            "source_updated_at": row["source_updated_at"],
            "snapshot_observed_at": _iso(row["snapshot_observed_at"]),
            "disabled_at": _iso(row["disabled_at"]),
            "disabled_reason": row["disabled_reason"],
        }

    def snapshot(self, include_recent_disabled: bool = False) -> list[dict[str, Any]]:
        return [self._token(row) for row in self._rows(include_recent_disabled)]

    def token(self, mint: str) -> dict[str, Any] | None:
        rows = self._rows(include_recent_disabled=True, mint=mint)
        return self._token(rows[0]) if rows else None


def _fingerprint(token: dict[str, Any]) -> tuple[Any, ...]:
    return (
        token["tracking_enabled"],
        token["source_updated_at"],
        token["last_changed_at"],
        token["market_cap"],
        token["liquidity"],
        token["holders"],
        token["trades_5m"],
        token["traders_5m"],
        token["volume_5m"],
    )


def _numeric_change(before: float | int | None, after: float | int | None) -> dict[str, float | None]:
    if before is None or after is None:
        return {"absolute": None, "percent": None}
    absolute = float(after) - float(before)
    percent = None if before == 0 else absolute / abs(float(before)) * 100.0
    return {"absolute": absolute, "percent": percent}


def _changes(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    return {
        "market_cap": _numeric_change(before.get("market_cap"), after.get("market_cap")),
        "liquidity": _numeric_change(before.get("liquidity"), after.get("liquidity")),
        "holders": _numeric_change(before.get("holders"), after.get("holders")),
        "traders_5m": _numeric_change(before.get("traders_5m"), after.get("traders_5m")),
    }


reader = FrontendReader(DATABASE_URL)


@asynccontextmanager
async def lifespan(_: FastAPI):
    reader.open()
    try:
        yield
    finally:
        reader.close()


app = FastAPI(title="Jupiter Live Frontend", lifespan=lifespan)
app.mount("/assets", StaticFiles(directory=FRONTEND_DIR), name="frontend-assets")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/universe")
async def universe() -> dict[str, Any]:
    tokens = await asyncio.to_thread(reader.snapshot)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tokens": tokens,
    }


@app.get("/api/token/{mint}")
async def token_detail(mint: str) -> dict[str, Any]:
    token = await asyncio.to_thread(reader.token, mint)
    if token is None:
        raise HTTPException(status_code=404, detail="mint not found")
    return token


@app.get("/api/events", response_class=EventSourceResponse)
async def events() -> AsyncIterator[ServerSentEvent]:
    previous_tokens = await asyncio.to_thread(reader.snapshot)
    previous = {token["mint"]: token for token in previous_tokens}
    sequence = 0

    while True:
        await asyncio.sleep(STREAM_INTERVAL_SECONDS)
        current_tokens = await asyncio.to_thread(reader.snapshot, True)
        current = {token["mint"]: token for token in current_tokens}
        active = {mint: token for mint, token in current.items() if token["tracking_enabled"]}
        delta: list[dict[str, Any]] = []

        for mint, token in active.items():
            before = previous.get(mint)
            if before is None:
                delta.append({"type": "token_added", "token": token})
            elif _fingerprint(before) != _fingerprint(token):
                delta.append(
                    {
                        "type": "token_updated",
                        "token": token,
                        "changes": _changes(before, token),
                    }
                )

        for mint, before in previous.items():
            if not before["tracking_enabled"]:
                continue
            after = current.get(mint)
            if after is None or not after["tracking_enabled"]:
                delta.append(
                    {
                        "type": "token_retired",
                        "token": after or before,
                        "reason": (after or {}).get("disabled_reason"),
                    }
                )

        previous = active
        if not delta:
            continue

        sequence += 1
        yield ServerSentEvent(
            event="universe_delta",
            id=str(sequence),
            retry=3000,
            data={
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "events": delta,
            },
        )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host=os.getenv("FRONTEND_HOST", "127.0.0.1"),
        port=int(os.getenv("FRONTEND_PORT", "8000")),
    )
