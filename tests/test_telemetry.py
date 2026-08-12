from __future__ import annotations

import asyncio
import json
import socket
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from observatory.telemetry import TelemetryStore
from telemetry import TelemetryEmitter, validate_telemetry_event


def lane_event(at: str = "2026-08-12T18:00:00+00:00") -> dict:
    return {
        "type": "search_lane_tick",
        "at": at,
        "lane": "lane17",
        "status": 200,
        "requested": 100,
        "received": 100,
        "rpm60": 58,
        "latency_ms": 210,
    }


class TelemetryContractTests(unittest.TestCase):
    def test_rejects_secret_fields(self) -> None:
        event = lane_event()
        event["api_key"] = "must-not-leak"
        self.assertFalse(validate_telemetry_event(event))

    def test_udp_emitter_sends_valid_compact_event(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as receiver:
            receiver.bind(("127.0.0.1", 0))
            receiver.settimeout(1.0)
            port = receiver.getsockname()[1]

            emitter = TelemetryEmitter(port=port)
            try:
                sent = emitter.emit(
                    "search_lane_tick",
                    lane="lane3",
                    status=200,
                    requested=100,
                    received=99,
                    rpm60=58,
                    latency_ms=190,
                )
                self.assertTrue(sent)
                payload = json.loads(receiver.recvfrom(65_535)[0])
            finally:
                emitter.close()

        self.assertTrue(validate_telemetry_event(payload))
        self.assertEqual(payload["lane"], "lane3")
        self.assertNotIn("api_key", payload)


class TelemetryStoreTests(unittest.IsolatedAsyncioTestCase):
    async def test_snapshot_and_subscription_share_one_event_contract(self) -> None:
        store = TelemetryStore(retention_seconds=600)
        first = lane_event()
        self.assertTrue(store.push(first))

        queue, snapshot = store.subscribe_with_snapshot()
        self.assertEqual(snapshot, [first])

        second = {**lane_event("2026-08-12T18:00:01+00:00"), "lane": "lane18"}
        self.assertTrue(store.push(second))
        self.assertEqual(await asyncio.wait_for(queue.get(), timeout=0.1), second)

        store.unsubscribe(queue)

    async def test_invalid_events_never_enter_buffer(self) -> None:
        store = TelemetryStore(retention_seconds=600)
        self.assertFalse(store.push({"type": "unknown", "at": "x"}))
        self.assertEqual(store.snapshot(), [])
        self.assertEqual(store.invalid_count, 1)


if __name__ == "__main__":
    unittest.main()
