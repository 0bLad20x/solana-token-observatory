from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any, Literal

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.sse import EventSourceResponse, ServerSentEvent
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .analyst import (
    AnalystError,
    analyze_temporal_token,
    query_current_tokens,
    research_token,
    validate_search_mode,
)
from .data import FrontendReader

PROJECT_ROOT = Path(__file__).resolve().parents[2]
STATIC_DIR = Path(__file__).with_name("static")

load_dotenv(PROJECT_ROOT / ".env")
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
STREAM_INTERVAL_SECONDS = float(os.getenv("FRONTEND_STREAM_INTERVAL_SECONDS", "2"))
RECENT_DISABLED_MINUTES = int(os.getenv("FRONTEND_RECENT_DISABLED_MINUTES", "5"))
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "").strip()
MISTRAL_MODEL = os.getenv("MISTRAL_MODEL", "mistral-small-latest").strip()
MISTRAL_WEB_SEARCH_MODE = validate_search_mode(
    os.getenv("MISTRAL_WEB_SEARCH_MODE", "web_search")
)

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL must be set in .env or the environment")

reader = FrontendReader(DATABASE_URL, RECENT_DISABLED_MINUTES)
logger = logging.getLogger(__name__)


class AnalystRequest(BaseModel):
    scope: Literal["current_data", "web", "temporal"] = "current_data"
    mint: str | None = Field(default=None, pattern=r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
    question: str = Field(min_length=1, max_length=1000)


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
        "volume_5m": _numeric_change(before.get("volume_5m"), after.get("volume_5m")),
    }


def _traced_temporal_context(mint: str) -> dict[str, Any] | None:
    started = perf_counter()
    logger.warning("[temporal] summary_load_start mint=%s", mint)
    context = reader.temporal_context(mint)
    elapsed = perf_counter() - started
    if context is None:
        logger.warning(
            "[temporal] summary_load_done mint=%s elapsed=%.2fs result=missing",
            mint,
            elapsed,
        )
        return None

    history = context.get("summary", {}).get("history", {})
    logger.warning(
        "[temporal] summary_load_done mint=%s elapsed=%.2fs observations=%s hours=%s",
        mint,
        elapsed,
        history.get("observations"),
        history.get("hours"),
    )
    return context


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


@app.post("/api/analyst")
async def analyst(request: AnalystRequest) -> dict[str, Any]:
    if not MISTRAL_API_KEY:
        raise HTTPException(status_code=503, detail="MISTRAL_API_KEY is not configured")

    question = request.question.strip()
    if not question:
        raise HTTPException(status_code=422, detail="question must not be empty")

    try:
        if request.scope == "current_data":
            tokens = await asyncio.to_thread(reader.snapshot)
            return await query_current_tokens(
                api_key=MISTRAL_API_KEY,
                model=MISTRAL_MODEL,
                tokens=tokens,
                question=question,
            )

        if request.mint is None:
            raise HTTPException(
                status_code=422,
                detail="mint is required for selected-token analysis",
            )
        token = await asyncio.to_thread(reader.token, request.mint)
        if token is None:
            raise HTTPException(status_code=404, detail="mint not found")

        if request.scope == "web":
            return await research_token(
                api_key=MISTRAL_API_KEY,
                model=MISTRAL_MODEL,
                search_mode=MISTRAL_WEB_SEARCH_MODE,
                token=token,
                question=question,
            )

        started = perf_counter()
        logger.warning(
            "[temporal] request_start mint=%s model=%s",
            request.mint,
            MISTRAL_MODEL,
        )
        result = await analyze_temporal_token(
            api_key=MISTRAL_API_KEY,
            model=MISTRAL_MODEL,
            token=token,
            question=question,
            context_loader=_traced_temporal_context,
        )
        logger.warning(
            "[temporal] request_done mint=%s elapsed=%.2fs",
            request.mint,
            perf_counter() - started,
        )
        return result
    except AnalystError as error:
        logger.warning("Analyst request failed: %s", error)
        raise HTTPException(status_code=502, detail=str(error)) from error


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
