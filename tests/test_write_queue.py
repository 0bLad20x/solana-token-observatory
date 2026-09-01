from __future__ import annotations

import asyncio
import threading
import unittest
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import refresh
from refresh import WriteQueue


class FakeRepository:
    def __init__(self) -> None:
        self.rows: list[list[dict]] = []
        self.flushed = threading.Event()

    def store_tokens_grouped(self, rows: list[dict]) -> SimpleNamespace:
        self.rows.append(rows)
        self.flushed.set()
        return SimpleNamespace(new_mints=1, new_snapshots=len(rows))


class WriteQueueTests(unittest.IsolatedAsyncioTestCase):
    async def test_delayed_first_submission_after_flush_interval_is_persisted(self):
        repository = FakeRepository()
        writer = WriteQueue(repository)
        observed_at = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)
        token = {
            "id": "mint-1",
            "updatedAt": "2026-09-01T10:00:00Z",
        }

        with patch.object(refresh, "FLUSH_INTERVAL_SECONDS", 0.02):
            task = asyncio.create_task(writer.run())
            try:
                await asyncio.sleep(0.05)
                await writer.submit([token], observed_at)

                flushed = await asyncio.to_thread(repository.flushed.wait, 1.0)

                self.assertTrue(flushed)
                self.assertEqual(writer._queue.qsize(), 0)
                self.assertEqual(len(repository.rows), 1)
                self.assertEqual(repository.rows[0][0]["id"], "mint-1")
                self.assertEqual(
                    repository.rows[0][0]["_observed_at"],
                    observed_at,
                )
            finally:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task


if __name__ == "__main__":
    unittest.main()
