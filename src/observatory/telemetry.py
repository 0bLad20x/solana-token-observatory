import asyncio
import json
import time
from collections import deque
from typing import Any

from telemetry import validate_telemetry_event


class TelemetryStore:
    def __init__(self, retention_seconds: float = 600.0, max_events: int = 50_000) -> None:
        if retention_seconds <= 0:
            raise ValueError("retention_seconds must be greater than zero")
        if max_events <= 0:
            raise ValueError("max_events must be greater than zero")

        self.retention_seconds = retention_seconds
        self._events: deque[tuple[float, dict[str, Any]]] = deque(maxlen=max_events)
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self.received_count = 0
        self.invalid_count = 0

    def _prune(self, now: float | None = None) -> None:
        current = time.monotonic() if now is None else now
        cutoff = current - self.retention_seconds
        while self._events and self._events[0][0] < cutoff:
            self._events.popleft()

    def push(self, event: Any) -> bool:
        if not validate_telemetry_event(event):
            self.invalid_count += 1
            return False

        now = time.monotonic()
        self._prune(now)
        clean = dict(event)
        self._events.append((now, clean))
        self.received_count += 1

        for queue in tuple(self._subscribers):
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            try:
                queue.put_nowait(clean)
            except asyncio.QueueFull:
                pass
        return True

    def snapshot(self) -> list[dict[str, Any]]:
        self._prune()
        return [dict(event) for _received_at, event in self._events]

    def subscribe_with_snapshot(
        self,
        max_queue_size: int = 2_000,
    ) -> tuple[asyncio.Queue[dict[str, Any]], list[dict[str, Any]]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=max_queue_size)
        self._subscribers.add(queue)
        return queue, self.snapshot()

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._subscribers.discard(queue)


class _TelemetryDatagramProtocol(asyncio.DatagramProtocol):
    def __init__(self, store: TelemetryStore) -> None:
        self._store = store

    def datagram_received(self, data: bytes, _addr: tuple[str, int]) -> None:
        try:
            payload = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._store.invalid_count += 1
            return
        self._store.push(payload)


class TelemetryReceiver:
    def __init__(
        self,
        store: TelemetryStore,
        host: str = "127.0.0.1",
        port: int = 8765,
    ) -> None:
        self._store = store
        self._host = host
        self._port = port
        self._transport: asyncio.DatagramTransport | None = None
        self.bind_error: str | None = None

    @property
    def listening(self) -> bool:
        return self._transport is not None

    async def start(self) -> None:
        if self._transport is not None:
            return
        loop = asyncio.get_running_loop()
        try:
            transport, _protocol = await loop.create_datagram_endpoint(
                lambda: _TelemetryDatagramProtocol(self._store),
                local_addr=(self._host, self._port),
            )
        except OSError as error:
            self.bind_error = str(error)
            return

        self._transport = transport
        self.bind_error = None

    def close(self) -> None:
        if self._transport is not None:
            self._transport.close()
            self._transport = None
