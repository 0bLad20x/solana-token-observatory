from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from maintenance import (
    SNAPSHOT_DELETE_BATCH_SIZE,
    SNAPSHOT_RETENTION_HOURS,
    run_snapshot_retention_once,
)


class FakeRepository:
    def __init__(self, deleted_batches: list[int]) -> None:
        self._deleted_batches = iter(deleted_batches)
        self.calls: list[tuple[datetime, int]] = []

    def delete_expired_snapshots(self, cutoff: datetime, batch_size: int) -> int:
        self.calls.append((cutoff, batch_size))
        return next(self._deleted_batches)


class MaintenanceTests(unittest.IsolatedAsyncioTestCase):
    async def test_retention_uses_24_hour_cutoff_and_drains_batches(self):
        now = datetime(2026, 8, 12, 9, 30, tzinfo=timezone.utc)
        repository = FakeRepository([SNAPSHOT_DELETE_BATCH_SIZE, 321])

        deleted = await run_snapshot_retention_once(repository, now=now)

        self.assertEqual(deleted, SNAPSHOT_DELETE_BATCH_SIZE + 321)
        self.assertEqual(len(repository.calls), 2)
        self.assertEqual(
            repository.calls[0][0],
            now - timedelta(hours=SNAPSHOT_RETENTION_HOURS),
        )
        self.assertTrue(
            all(
                batch_size == SNAPSHOT_DELETE_BATCH_SIZE
                for _cutoff, batch_size in repository.calls
            )
        )


if __name__ == "__main__":
    unittest.main()
