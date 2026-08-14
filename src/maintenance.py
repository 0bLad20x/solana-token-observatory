import asyncio
from datetime import datetime, timedelta, timezone

from repository import MintRepository

SNAPSHOT_RETENTION_HOURS = 24
SNAPSHOT_RETENTION_INTERVAL_SECONDS = 60 * 60
SNAPSHOT_DELETE_BATCH_SIZE = 10_000


async def run_snapshot_retention_once(
    repository: MintRepository,
    now: datetime | None = None,
) -> int:
    """Delete eligible raw snapshots older than the 24-hour working window."""
    current = now or datetime.now(timezone.utc)
    cutoff = current - timedelta(hours=SNAPSHOT_RETENTION_HOURS)
    deleted_total = 0

    while True:
        deleted = await asyncio.to_thread(
            repository.delete_expired_snapshots,
            cutoff,
            SNAPSHOT_DELETE_BATCH_SIZE,
        )
        deleted_total += deleted

        if deleted < SNAPSHOT_DELETE_BATCH_SIZE:
            return deleted_total

        await asyncio.sleep(0)


async def snapshot_retention_loop(repository: MintRepository) -> None:
    """Run one bounded retention pass at startup and then once per hour."""
    while True:
        try:
            deleted = await run_snapshot_retention_once(repository)
            print(
                "[maintenance] snapshot_retention "
                f"hours={SNAPSHOT_RETENTION_HOURS} deleted={deleted}"
            )
        except Exception as exc:
            print(
                "[maintenance] snapshot_retention ERROR "
                f"{type(exc).__name__}: {exc}"
            )

        await asyncio.sleep(SNAPSHOT_RETENTION_INTERVAL_SECONDS)
