from __future__ import annotations

import statistics
from collections import defaultdict

import psycopg

from config import Settings


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
    intervals = defaultdict(list)
    last_seen = {}
    for priority, mint, observed_at in rows:
        if mint in last_seen:
            intervals[priority].append((observed_at - last_seen[mint]).total_seconds())
        last_seen[mint] = observed_at
    for priority in sorted(intervals):
        values = intervals[priority]
        print(f"priority={priority} samples={len(values)} avg={statistics.mean(values):.2f}s median={statistics.median(values):.2f}s min={min(values):.2f}s max={max(values):.2f}s")


if __name__ == "__main__":
    main()
