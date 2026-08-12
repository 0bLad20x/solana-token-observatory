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
from .delta import changes, fingerprint
from .evidence.rugcheck import RugCheckError, get_token_report
from .model_policy import ModelPolicy
from .rugcheck_analysis import analyze_rugcheck_report

PROJECT_ROOT = Path(__file__).resolve().parents[2]
STATIC_DIR = Path(__file__).with_name("static")

load_dotenv(PROJECT_ROOT / ".env")
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
STREAM_INTERVAL_SECONDS = float(os.getenv("FRONTEND_STREAM_INTERVAL_SECONDS", "2"))
RECENT_DISABLED_MINUTES = int(os.getenv("FRONTEND_RECENT_DISABLED_MINUTES", "5"))
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "").strip()
MISTRAL_MODEL_FAST = os.getenv("MISTRAL_MODEL_FAST", "ministral-14b-latest").strip()
MISTRAL_MODEL_STRONG = os.getenv("MISTRAL_MODEL_STRONG", "mistral-large-latest").strip()
MISTRAL_WEB_SEARCH_MODE = validate_search_mode(
    os.getenv("MISTRAL_WEB_SEARCH_MODE", "web_search")
)

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL must be set in .env or the environment")

reader = FrontendReader(DATABASE_URL, RECENT_DISABLED_MINUTES)
model_policy = ModelPolicy(
    fast_model=MISTRAL_MODEL_FAST,
    strong_model=MISTRAL_MODEL_STRONG,
)
logger = logging.getLogger(__name__)


class AnalystRequest(BaseModel):
    scope: Literal["current_data", "web", "temporal", "rugcheck"] = "current_data"
    mint: str | None = Field(default=None, pattern=r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
    question: str = Field(min_length=1, max_length=1000)


def _traced_temporal_summary(mint: str) -> dict[str, Any] | None:
    started = perf_counter()
    logger.warning("[temporal] summary_load_start mint=%s", mint)
    summary = reader.temporal_summary(mint)
    elapsed = perf_counter() - started
    if summary is None:
        logger.warning(
            "[temporal] summary_load_done mint=%s elapsed=%.2fs result=missing",
            mint,
            elapsed,
        )
        return None

    history = summary.get("history", {})
    logger.warning(
        "[temporal] summary_load_done mint=%s elapsed=%.2fs observations=%s hours=%s",
        mint,
        elapsed,
        history.get("observations"),
        history.get("hours"),
    )
    return summary


def _rugcheck_http_error(error: RugCheckError) -> HTTPException:
    return HTTPException(status_code=error.status_code, detail=str(error))


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


@app.get("/api/evidence/rugcheck/{mint}")
async def rugcheck_evidence(mint: str) -> dict[str, Any]:
    try:
        return await get_token_report(mint)
    except RugCheckError as error:
        raise _rugcheck_http_error(error) from error


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
                model=model_policy.model_for("current_data"),
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
                model=model_policy.model_for("web"),
                search_mode=MISTRAL_WEB_SEARCH_MODE,
                token=token,
                question=question,
            )

        if request.scope == "rugcheck":
            evidence = await get_token_report(request.mint)
            return await analyze_rugcheck_report(
                api_key=MISTRAL_API_KEY,
                model=model_policy.model_for("rugcheck"),
                token=token,
                question=question,
                evidence=evidence,
            )

        temporal_model = model_policy.model_for("temporal")
        started = perf_counter()
        logger.warning(
            "[temporal] request_start mint=%s model=%s",
            request.mint,
            temporal_model,
        )
        result = await analyze_temporal_token(
            api_key=MISTRAL_API_KEY,
            model=temporal_model,
            token=token,
            question=question,
            summary_loader=_traced_temporal_summary,
        )
        logger.warning(
            "[temporal] request_done mint=%s elapsed=%.2fs",
            request.mint,
            perf_counter() - started,
        )
        return result
    except RugCheckError as error:
        logger.warning("RugCheck request failed: %s", error)
        raise _rugcheck_http_error(error) from error
    except AnalystError as error:
        logger.warning("Analyst request failed: %s", error)
        raise HTTPException(status_code=502, detail=str(error)) from error


@app.get("/api/events", response_class=EventSourceResponse)
async def events() -> AsyncIterator[ServerSentEvent]:
    # Every connection starts with one authoritative snapshot. The exact same snapshot is
    # the baseline for subsequent deltas, so bootstrap/connect and reconnect cannot leave
    # an undefined state gap in the browser.
    previous_tokens = await asyncio.to_thread(reader.snapshot, True)
    previous = {token["mint"]: token for token in previous_tokens}
    sequence = 1

    yield ServerSentEvent(
        event="universe_snapshot",
        id=str(sequence),
        retry=3000,
        data={
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "tokens": previous_tokens,
        },
    )

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
            elif fingerprint(before) != fingerprint(token):
                delta.append(
                    {
                        "type": "token_updated",
                        "token": token,
                        "changes": changes(before, token),
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

        previous = current
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
