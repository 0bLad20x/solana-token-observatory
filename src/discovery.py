import asyncio
import json
import ssl
import time
import traceback

import certifi
import httpx
import websockets

from config import Settings
from repository import MintRepository
from telemetry import TelemetryEmitter

DAMM_V2_URL = "https://damm-v2.datapi.meteora.ag/pools"
DLMM_URL = "https://dlmm.datapi.meteora.ag/pools"
DLMM_SORT_ORDERS = ["tvl:desc", "fee_24h:desc", "volume_24h:desc"]


def _meteora_mints(pools: list[dict]) -> list[str]:
    result = []
    for pool in pools:
        for key in ("token_x", "token_y"):
            token = pool.get(key)
            if isinstance(token, dict) and token.get("address"):
                result.append(token["address"])
    return result


def _emit_discovery(
    telemetry: TelemetryEmitter | None,
    *,
    source: str,
    status: int | None,
    response_items: int,
    candidates: list[str],
    new_mints: int,
    latency_ms: float | None,
) -> None:
    if telemetry is None:
        return
    telemetry.emit(
        "discovery_tick",
        source=source,
        status=status,
        response_items=response_items,
        candidate_occurrences=len(candidates),
        unique_candidates=len(set(candidates)),
        new_mints=new_mints,
        latency_ms=round(latency_ms) if latency_ms is not None else None,
    )


async def jupiter_recent_loop(
    settings: Settings,
    repository: MintRepository,
    telemetry: TelemetryEmitter | None = None,
) -> None:
    async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
        while True:
            started = time.monotonic()
            request_started = time.monotonic()
            try:
                response = await client.get(
                    f"{settings.jupiter_base_url}/tokens/v2/recent",
                    headers={"x-api-key": settings.jupiter_recent_api_key},
                )
                latency_ms = (time.monotonic() - request_started) * 1000
                items = response.json() if response.status_code == 200 else []
                mints = [item["id"] for item in items if isinstance(item, dict) and item.get("id")]
                inserted = await asyncio.to_thread(repository.insert_new_mints, mints) if mints else 0
                print(f"[jupiter_recent] status={response.status_code} received={len(items)} new={inserted}")
                _emit_discovery(
                    telemetry,
                    source="jupiter_recent",
                    status=response.status_code,
                    response_items=len(items),
                    candidates=mints,
                    new_mints=inserted,
                    latency_ms=latency_ms,
                )
            except Exception:
                _emit_discovery(
                    telemetry,
                    source="jupiter_recent",
                    status=None,
                    response_items=0,
                    candidates=[],
                    new_mints=0,
                    latency_ms=(time.monotonic() - request_started) * 1000,
                )
                traceback.print_exc()
            await asyncio.sleep(max(0.0, settings.jupiter_seconds_per_key - (time.monotonic() - started)))


async def meteora_damm_v2_loop(
    settings: Settings,
    repository: MintRepository,
    telemetry: TelemetryEmitter | None = None,
) -> None:
    async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
        while True:
            request_started = time.monotonic()
            try:
                response = await client.get(DAMM_V2_URL, params={"page": 1, "page_size": 100, "sort_by": "pool_created_at:desc"})
                latency_ms = (time.monotonic() - request_started) * 1000
                pools = response.json().get("data", []) if response.status_code == 200 else []
                mints = _meteora_mints(pools)
                inserted = await asyncio.to_thread(repository.insert_new_mints, mints) if mints else 0
                print(f"[meteora_damm_v2] status={response.status_code} pools={len(pools)} new={inserted}")
                _emit_discovery(
                    telemetry,
                    source="meteora_damm_v2",
                    status=response.status_code,
                    response_items=len(pools),
                    candidates=mints,
                    new_mints=inserted,
                    latency_ms=latency_ms,
                )
            except Exception:
                _emit_discovery(
                    telemetry,
                    source="meteora_damm_v2",
                    status=None,
                    response_items=0,
                    candidates=[],
                    new_mints=0,
                    latency_ms=(time.monotonic() - request_started) * 1000,
                )
                traceback.print_exc()
            await asyncio.sleep(settings.discovery_interval_seconds)


async def meteora_dlmm_loop(
    settings: Settings,
    repository: MintRepository,
    telemetry: TelemetryEmitter | None = None,
) -> None:
    async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
        while True:
            for sort_by in DLMM_SORT_ORDERS:
                request_started = time.monotonic()
                try:
                    response = await client.get(DLMM_URL, params={"page": 1, "page_size": 100, "sort_by": sort_by})
                    latency_ms = (time.monotonic() - request_started) * 1000
                    pools = response.json().get("data", []) if response.status_code == 200 else []
                    mints = _meteora_mints(pools)
                    inserted = await asyncio.to_thread(repository.insert_new_mints, mints) if mints else 0
                    print(f"[meteora_dlmm:{sort_by}] status={response.status_code} pools={len(pools)} new={inserted}")
                    _emit_discovery(
                        telemetry,
                        source=f"meteora_dlmm:{sort_by}",
                        status=response.status_code,
                        response_items=len(pools),
                        candidates=mints,
                        new_mints=inserted,
                        latency_ms=latency_ms,
                    )
                except Exception:
                    _emit_discovery(
                        telemetry,
                        source=f"meteora_dlmm:{sort_by}",
                        status=None,
                        response_items=0,
                        candidates=[],
                        new_mints=0,
                        latency_ms=(time.monotonic() - request_started) * 1000,
                    )
                    traceback.print_exc()
            await asyncio.sleep(settings.discovery_interval_seconds)


async def pump_loop(
    settings: Settings,
    repository: MintRepository,
    telemetry: TelemetryEmitter | None = None,
) -> None:
    uri = f"wss://pumpportal.fun/api/data?api-key={settings.pumpportal_api_key}"
    ssl_context = ssl.create_default_context(cafile=certifi.where())
    reconnect_delay = 5.0
    while True:
        connected_at = time.monotonic()
        buffer = []
        last_flush = time.monotonic()
        try:
            async with websockets.connect(uri, ssl=ssl_context) as websocket:
                await websocket.send(json.dumps({"method": "subscribeNewToken"}))
                print("[pumpfun] connected")
                reconnect_delay = 5.0
                async for message in websocket:
                    mint = json.loads(message).get("mint")
                    if isinstance(mint, str) and mint:
                        buffer.append(mint)
                    if buffer and time.monotonic() - last_flush >= settings.pumpfun_batch_interval_seconds:
                        inserted = await asyncio.to_thread(repository.insert_new_mints, buffer)
                        print(f"[pumpfun] received={len(buffer)} new={inserted}")
                        _emit_discovery(
                            telemetry,
                            source="pumpfun",
                            status=101,
                            response_items=len(buffer),
                            candidates=buffer,
                            new_mints=inserted,
                            latency_ms=None,
                        )
                        buffer = []
                        last_flush = time.monotonic()
        except Exception:
            traceback.print_exc()
        if time.monotonic() - connected_at < 60.0:
            reconnect_delay = min(reconnect_delay * 2, 60.0)
        else:
            reconnect_delay = 5.0
        await asyncio.sleep(reconnect_delay)
