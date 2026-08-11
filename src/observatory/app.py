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

from .data import FrontendReader

PROJECT_ROOT = Path(__file__).resolve().parents[2]
STATIC_DIR = Path(__file__).with_name("static")
STREAM_INTERVAL_SECONDS = float(os.getenv("FRONTEND_STREAM_INTERVAL_SECONDS", "2"))
RECENT_DISABLED_MINUTES = int(os.getenv("FRONTEND_RECENT_DISABLED_MINUTES", "5"))

load_dotenv(PROJECT_ROOT / ".env")
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL must be set in .env or the environment")

reader = FrontendReader(DATABASE_URL, RECENT_DISABLED_MINUTES)


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


@asynccontextmanager
async def lifespan(_: FastAPI):
    reader.open()
    try:
        yield
    finally:
        reader.close()


app = FastAPI(title="Jupiter Token Observatory", lifespan=lifespan)
app.mount("/assets", StaticFiles(directory=STATIC_DIR), name="observatory-assets")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


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
