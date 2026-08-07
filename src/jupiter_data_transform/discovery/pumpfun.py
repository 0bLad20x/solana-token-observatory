from __future__ import annotations

import asyncio
import json
import ssl
import time
import traceback

import certifi
import websockets

from ..config import Settings
from ..repository import MintRepository

RECONNECT_DELAY_BASE_SECONDS = 5.0
RECONNECT_DELAY_MAX_SECONDS = 60.0
STABLE_CONNECTION_THRESHOLD_SECONDS = 60.0


async def pump_loop(settings: Settings, repository: MintRepository) -> None:
    uri = f"wss://pumpportal.fun/api/data?api-key={settings.pumpportal_api_key}"
    ssl_context = ssl.create_default_context(cafile=certifi.where())
    interval = settings.pumpfun_batch_interval_seconds
    reconnect_delay = RECONNECT_DELAY_BASE_SECONDS

    while True:
        connected_at = time.monotonic()
        buffer: list[str] = []
        last_flush = time.monotonic()

        try:
            async with websockets.connect(uri, ssl=ssl_context) as websocket:
                await websocket.send(json.dumps({"method": "subscribeNewToken"}))
                print("[pumpfun] OK verbunden, subscribeNewToken aktiv")
                reconnect_delay = RECONNECT_DELAY_BASE_SECONDS

                async for message in websocket:
                    event = json.loads(message)
                    mint = event.get("mint")
                    if isinstance(mint, str) and mint:
                        buffer.append(mint)

                    if time.monotonic() - last_flush >= interval and buffer:
                        inserted = await asyncio.to_thread(repository.insert_new_mints, buffer)
                        print(f"[pumpfun] OK gesammelt={len(buffer)} neue_mints={inserted}")
                        buffer = []
                        last_flush = time.monotonic()

        except Exception:
            print("[pumpfun] VERBINDUNG UNTERBROCHEN, Details folgen:")
            traceback.print_exc()

        was_stable = time.monotonic() - connected_at >= STABLE_CONNECTION_THRESHOLD_SECONDS
        if was_stable:
            reconnect_delay = RECONNECT_DELAY_BASE_SECONDS
        else:
            reconnect_delay = min(reconnect_delay * 2, RECONNECT_DELAY_MAX_SECONDS)

        print(f"[pumpfun] Reconnect in {reconnect_delay:.0f}s")
        await asyncio.sleep(reconnect_delay)