from __future__ import annotations

import statistics
from collections import defaultdict

import psycopg

from .config import Settings


def main() -> None:
    settings = Settings.from_env()

    query = """
        SELECT m.priority, s.mint, s.observed_at
        FROM mint_snapshots s
        JOIN mints m ON m.mint = s.mint
        ORDER BY s.mint, s.observed_at
    """
    with psycopg.connect(settings.database_url) as connection:
        rows = connection.execute(query).fetchall()

    intervals_by_priority: dict[int, list[float]] = defaultdict(list)
    last_seen: dict[str, "tuple"] = {}

    for priority, mint, observed_at in rows:
        if mint in last_seen:
            _, prev_time = last_seen[mint]
            delta = (observed_at - prev_time).total_seconds()
            intervals_by_priority[priority].append(delta)
        last_seen[mint] = (priority, observed_at)

    for priority in sorted(intervals_by_priority):
        values = intervals_by_priority[priority]
        print(
            f"priority={priority} samples={len(values)} "
            f"avg={statistics.mean(values):.2f}s "
            f"median={statistics.median(values):.2f}s "
            f"min={min(values):.2f}s max={max(values):.2f}s"
        )


if __name__ == "__main__":
    main()