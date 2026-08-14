import json
import os
import socket
from datetime import datetime, timezone
from typing import Any

EVENT_TYPES = {
    "discovery_tick",
    "search_lane_tick",
    "search_flush",
    "lifecycle_tick",
}

REQUIRED_FIELDS = {
    "discovery_tick": {
        "source",
        "status",
        "response_items",
        "candidate_occurrences",
        "unique_candidates",
        "new_mints",
        "latency_ms",
    },
    "search_lane_tick": {
        "lane",
        "status",
        "requested",
        "received",
        "rpm60",
        "latency_ms",
    },
    "search_flush": {
        "polled_tokens",
        "source_versions",
        "new_snapshots",
        "write_ms",
        "queue_size",
    },
    "lifecycle_tick": {
        "apply",
        "affected_count",
        "breakdown",
        "active_remaining",
        "duration_ms",
    },
}

_FORBIDDEN_KEYS = {
    "api_key",
    "apikey",
    "authorization",
    "secret",
}


def _has_forbidden_key(value: Any) -> bool:
    if isinstance(value, dict):
        for key, nested in value.items():
            if str(key).lower() in _FORBIDDEN_KEYS:
                return True
            if _has_forbidden_key(nested):
                return True
    elif isinstance(value, (list, tuple)):
        return any(_has_forbidden_key(item) for item in value)
    return False


def validate_telemetry_event(event: Any) -> bool:
    if not isinstance(event, dict):
        return False

    event_type = event.get("type")
    if event_type not in EVENT_TYPES:
        return False
    if not isinstance(event.get("at"), str) or not event["at"]:
        return False
    if not REQUIRED_FIELDS[event_type].issubset(event):
        return False
    if _has_forbidden_key(event):
        return False
    return True


class TelemetryEmitter:
    """Best-effort localhost UDP telemetry.

    Telemetry is deliberately lossy and must never become an operational dependency.
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 8765) -> None:
        self._address = (host, port)
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setblocking(False)
            self._socket: socket.socket | None = sock
        except OSError:
            self._socket = None

    @classmethod
    def from_env(cls) -> "TelemetryEmitter":
        return cls(
            host=os.getenv("TELEMETRY_HOST", "127.0.0.1").strip() or "127.0.0.1",
            port=int(os.getenv("TELEMETRY_PORT", "8765")),
        )

    def emit(self, event_type: str, **fields: Any) -> bool:
        if self._socket is None:
            return False

        event = {
            "type": event_type,
            "at": datetime.now(timezone.utc).isoformat(),
            **fields,
        }
        if not validate_telemetry_event(event):
            return False

        try:
            payload = json.dumps(
                event,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
            if len(payload) > 60_000:
                return False
            self._socket.sendto(payload, self._address)
            return True
        except (OSError, TypeError, ValueError):
            return False

    def close(self) -> None:
        if self._socket is not None:
            self._socket.close()
            self._socket = None
