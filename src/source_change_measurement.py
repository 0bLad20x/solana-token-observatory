from __future__ import annotations

import bisect
import csv
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import psycopg


INTERVAL_BOUNDS_SECONDS = (
    0.25,
    0.5,
    1.0,
    2.0,
    5.0,
    10.0,
    30.0,
    60.0,
    300.0,
)
CAPACITY_TARGET_SWEEPS_SECONDS = (0.5, 1.0, 2.0, 5.0, 10.0)
DEFAULT_QUERY_BATCH_SIZE = 50_000
TOP_MINT_LIMIT = 20
MIN_PLAUSIBLE_SOURCE_AT = datetime(2000, 1, 1, tzinfo=timezone.utc)


def _parse_datetime(value: Any) -> datetime | None:
    parsed: datetime
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None

    if parsed.tzinfo is None:
        return None
    if parsed.astimezone(timezone.utc) < MIN_PLAUSIBLE_SOURCE_AT:
        return None
    return parsed


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _ratio(numerator: int | float, denominator: int | float) -> float | None:
    if denominator <= 0:
        return None
    return numerator / denominator


def _percentile(sorted_values: list[float], fraction: float) -> float | None:
    if not sorted_values:
        return None
    position = max(
        0.0,
        min(len(sorted_values) - 1, fraction * (len(sorted_values) - 1)),
    )
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return sorted_values[lower]
    weight = position - lower
    return sorted_values[lower] * (1.0 - weight) + sorted_values[upper] * weight


def _numeric_summary(values: Iterable[float]) -> dict[str, float | int | None]:
    ordered = sorted(
        converted
        for value in values
        if math.isfinite(converted := float(value))
    )
    if not ordered:
        return {
            "count": 0,
            "min": None,
            "p10": None,
            "p25": None,
            "p50": None,
            "p75": None,
            "p90": None,
            "p95": None,
            "p99": None,
            "max": None,
            "mean": None,
        }
    return {
        "count": len(ordered),
        "min": ordered[0],
        "p10": _percentile(ordered, 0.10),
        "p25": _percentile(ordered, 0.25),
        "p50": _percentile(ordered, 0.50),
        "p75": _percentile(ordered, 0.75),
        "p90": _percentile(ordered, 0.90),
        "p95": _percentile(ordered, 0.95),
        "p99": _percentile(ordered, 0.99),
        "max": ordered[-1],
        "mean": sum(ordered) / len(ordered),
    }


def _target_label(seconds: float) -> str:
    return f"{seconds:g}"


def _csv_target_field(seconds: float) -> str:
    return f"intervals_lt_{_target_label(seconds).replace('.', '_')}s"


def _read_only_connection(database_url: str):
    return psycopg.connect(
        database_url,
        options="-c default_transaction_read_only=on",
    )


@dataclass
class IntervalHistogram:
    bounds: tuple[float, ...] = INTERVAL_BOUNDS_SECONDS
    counts: list[int] = field(
        default_factory=lambda: [0] * (len(INTERVAL_BOUNDS_SECONDS) + 1)
    )

    def consume(self, seconds: float) -> None:
        if not math.isfinite(seconds) or seconds <= 0:
            return
        self.counts[bisect.bisect_right(self.bounds, seconds)] += 1

    @property
    def total(self) -> int:
        return sum(self.counts)

    def count_below(self, seconds: float) -> int:
        boundary_count = bisect.bisect_right(self.bounds, seconds)
        return sum(self.counts[:boundary_count])

    def snapshot(self) -> list[dict[str, Any]]:
        total = self.total
        rows: list[dict[str, Any]] = []
        lower = 0.0
        for index, count in enumerate(self.counts):
            upper = self.bounds[index] if index < len(self.bounds) else None
            rows.append(
                {
                    "lower_seconds_inclusive": lower,
                    "upper_seconds_exclusive": upper,
                    "count": count,
                    "share": _ratio(count, total),
                }
            )
            if upper is not None:
                lower = upper
        return rows


@dataclass
class MintChangeStats:
    mint: str
    name: str | None = None
    symbol: str | None = None
    source_versions: int = 0
    measured_intervals: int = 0
    first_observed_at: datetime | None = None
    last_observed_at: datetime | None = None
    first_source_at: datetime | None = None
    last_source_at: datetime | None = None
    interval_sum_seconds: float = 0.0
    min_interval_seconds: float | None = None
    max_interval_seconds: float | None = None
    min_interval_from: datetime | None = None
    min_interval_to: datetime | None = None
    max_interval_from: datetime | None = None
    max_interval_to: datetime | None = None
    histogram: IntervalHistogram = field(default_factory=IntervalHistogram)
    active_seconds: float | None = None
    non_monotonic_versions: int = 0

    def consume(
        self,
        *,
        observed_at: datetime,
        source_at: datetime,
    ) -> float | None:
        self.source_versions += 1
        if self.first_observed_at is None:
            self.first_observed_at = observed_at
            self.first_source_at = source_at
        self.last_observed_at = observed_at

        previous_source = self.last_source_at
        if previous_source is None:
            self.last_source_at = source_at
            return None

        interval = (source_at - previous_source).total_seconds()
        if interval <= 0:
            self.non_monotonic_versions += 1
            if source_at > self.last_source_at:
                self.last_source_at = source_at
            return None

        self.measured_intervals += 1
        self.interval_sum_seconds += interval
        self.histogram.consume(interval)

        if self.min_interval_seconds is None or interval < self.min_interval_seconds:
            self.min_interval_seconds = interval
            self.min_interval_from = previous_source
            self.min_interval_to = source_at
        if self.max_interval_seconds is None or interval > self.max_interval_seconds:
            self.max_interval_seconds = interval
            self.max_interval_from = previous_source
            self.max_interval_to = source_at

        self.last_source_at = source_at
        return interval

    @property
    def mean_interval_seconds(self) -> float | None:
        if self.measured_intervals <= 0:
            return None
        return self.interval_sum_seconds / self.measured_intervals

    @property
    def changes_per_active_hour(self) -> float | None:
        if self.active_seconds is None or self.active_seconds <= 0:
            return None
        return self.measured_intervals / (self.active_seconds / 3600.0)


class SourceChangeAccumulator:
    """Incrementally summarize persisted Jupiter source-version cadence.

    Only persisted snapshots are consumed. The first source version seen for a
    mint inside the measurement window establishes the baseline and therefore
    has no interval. This avoids inventing a cross-window interval.
    """

    def __init__(self, started_at: datetime) -> None:
        self.started_at = started_at
        self.scanned_through = started_at
        self.cursor_observed_at = started_at
        self.cursor_mint = ""
        self.rows_scanned = 0
        self.invalid_source_timestamps = 0
        self.global_histogram = IntervalHistogram()
        self.mints: dict[str, MintChangeStats] = {}
        self.population_metadata_loaded = False
        self.source_observed_population_overlap = 0

    def consume_row(
        self,
        *,
        mint: str,
        observed_at: datetime,
        source_updated_at: Any,
    ) -> None:
        source_at = _parse_datetime(source_updated_at)
        self.rows_scanned += 1
        self.cursor_observed_at = observed_at
        self.cursor_mint = mint

        if source_at is None:
            self.invalid_source_timestamps += 1
            return

        stats = self.mints.setdefault(mint, MintChangeStats(mint=mint))
        interval = stats.consume(observed_at=observed_at, source_at=source_at)
        if interval is not None:
            self.global_histogram.consume(interval)

    def apply_population_metadata(
        self,
        rows: Iterable[
            tuple[str, str | None, str | None, datetime, datetime | None]
        ],
        *,
        ended_at: datetime,
    ) -> None:
        count = 0
        for mint, name, symbol, first_observed_at, disabled_at in rows:
            count += 1
            stats = self.mints.setdefault(mint, MintChangeStats(mint=mint))
            stats.name = name
            stats.symbol = symbol
            active_start = max(self.started_at, first_observed_at)
            active_end = (
                min(ended_at, disabled_at)
                if disabled_at is not None
                else ended_at
            )
            stats.active_seconds = max(
                0.0,
                (active_end - active_start).total_seconds(),
            )
        self.population_metadata_loaded = True
        self.source_observed_population_overlap = count

    def _profile(
        self,
        stats: MintChangeStats,
        *,
        include_histogram: bool = False,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "mint": stats.mint,
            "name": stats.name,
            "symbol": stats.symbol,
            "active_hours": (
                stats.active_seconds / 3600.0
                if stats.active_seconds is not None
                else None
            ),
            "source_versions": stats.source_versions,
            "measured_intervals": stats.measured_intervals,
            "changes_per_active_hour": stats.changes_per_active_hour,
            "min_interval_seconds": stats.min_interval_seconds,
            "mean_interval_seconds": stats.mean_interval_seconds,
            "max_interval_seconds": stats.max_interval_seconds,
            "min_interval_from": _iso(stats.min_interval_from),
            "min_interval_to": _iso(stats.min_interval_to),
            "max_interval_from": _iso(stats.max_interval_from),
            "max_interval_to": _iso(stats.max_interval_to),
            "first_source_at": _iso(stats.first_source_at),
            "last_source_at": _iso(stats.last_source_at),
            "interval_counts_below_target": {
                _target_label(target): stats.histogram.count_below(target)
                for target in CAPACITY_TARGET_SWEEPS_SECONDS
            },
            "non_monotonic_versions": stats.non_monotonic_versions,
        }
        if include_histogram:
            payload["interval_histogram"] = stats.histogram.snapshot()
        return payload

    def summary(self, ended_at: datetime | None = None) -> dict[str, Any]:
        current_end = ended_at or self.scanned_through
        profiles = list(self.mints.values())
        interval_profiles = [
            item for item in profiles if item.measured_intervals > 0
        ]
        total_intervals = self.global_histogram.total

        version_counts = [float(item.source_versions) for item in profiles]
        changes_per_hour = [
            float(rate)
            for item in profiles
            if (rate := item.changes_per_active_hour) is not None
        ]

        target_rows = []
        for target in CAPACITY_TARGET_SWEEPS_SECONDS:
            faster = self.global_histogram.count_below(target)
            mints_faster = sum(
                1
                for item in interval_profiles
                if item.histogram.count_below(target) > 0
            )
            target_rows.append(
                {
                    "target_sweep_seconds": target,
                    "observed_intervals_faster_than_target": faster,
                    "observed_intervals_faster_share": _ratio(
                        faster,
                        total_intervals,
                    ),
                    "mints_with_any_faster_interval": mints_faster,
                    "mints_with_any_faster_interval_share": _ratio(
                        mints_faster,
                        len(interval_profiles),
                    ),
                    "mints_with_any_faster_interval_share_of_window_population": (
                        _ratio(
                            mints_faster,
                            self.source_observed_population_overlap,
                        )
                        if self.population_metadata_loaded
                        else None
                    ),
                }
            )

        fastest = sorted(
            interval_profiles,
            key=lambda item: (
                item.min_interval_seconds
                if item.min_interval_seconds is not None
                else math.inf,
                -item.measured_intervals,
                item.mint,
            ),
        )[:TOP_MINT_LIMIT]
        most_active = sorted(
            (
                item
                for item in profiles
                if item.changes_per_active_hour is not None
            ),
            key=lambda item: (
                -(item.changes_per_active_hour or 0.0),
                -item.measured_intervals,
                item.mint,
            ),
        )[:TOP_MINT_LIMIT]
        largest_gaps = sorted(
            interval_profiles,
            key=lambda item: (
                -(item.max_interval_seconds or 0.0),
                item.mint,
            ),
        )[:TOP_MINT_LIMIT]

        return {
            "measurement_kind": "persisted_source_version_cadence",
            "started_at": self.started_at.isoformat(),
            "ended_at": current_end.isoformat(),
            "scanned_through": self.scanned_through.isoformat(),
            "rows_scanned": self.rows_scanned,
            "invalid_source_timestamps": self.invalid_source_timestamps,
            "mints_with_persisted_source_versions": sum(
                1 for item in profiles if item.source_versions > 0
            ),
            "mints_with_measured_intervals": len(interval_profiles),
            "source_observed_mints_overlapping_window": (
                self.source_observed_population_overlap
                if self.population_metadata_loaded
                else None
            ),
            "mints_without_new_source_version": (
                max(
                    0,
                    self.source_observed_population_overlap
                    - sum(
                        1 for item in profiles if item.source_versions > 0
                    ),
                )
                if self.population_metadata_loaded
                else None
            ),
            "observed_source_intervals": total_intervals,
            "interval_histogram": self.global_histogram.snapshot(),
            "interval_targets": target_rows,
            "source_versions_per_mint": _numeric_summary(version_counts),
            "changes_per_active_hour_per_mint": _numeric_summary(
                changes_per_hour
            ),
            "fastest_observed_mints": [
                self._profile(item) for item in fastest
            ],
            "highest_change_rate_mints": [
                self._profile(item) for item in most_active
            ],
            "largest_observed_change_gaps": [
                self._profile(item) for item in largest_gaps
            ],
            "notes": {
                "interval_semantics": (
                    "Intervals use consecutive Jupiter payload updatedAt values "
                    "that were persisted and observed inside this measurement "
                    "window. The first version per mint establishes a baseline."
                ),
                "visibility_limit": (
                    "These are observed source versions, not proof of every "
                    "upstream intermediate state. Multiple upstream changes "
                    "between two polls can remain invisible."
                ),
                "target_semantics": (
                    "interval_targets reports how much observed source-change "
                    "cadence is faster than each candidate full-population "
                    "sweep. It is not itself a missed-version simulation."
                ),
                "invalid_source_timestamp_semantics": (
                    "Missing, naive or pre-2000 updatedAt values are treated as "
                    "invalid/sentinel source timestamps and never form cadence "
                    "intervals."
                ),
                "retention_strategy": (
                    "Snapshot rows are scanned incrementally during the run so "
                    "the analysis remains complete even though raw snapshots "
                    "have a 24-hour retention window."
                ),
            },
        }

    def per_mint_rows(self) -> list[dict[str, Any]]:
        return [
            self._profile(self.mints[mint], include_histogram=False)
            for mint in sorted(self.mints)
        ]


class SourceChangeSampler:
    def __init__(
        self,
        *,
        database_url: str,
        started_at: datetime,
        query_batch_size: int = DEFAULT_QUERY_BATCH_SIZE,
    ) -> None:
        if not database_url.strip():
            raise ValueError("database_url must not be empty")
        if query_batch_size <= 0:
            raise ValueError("query_batch_size must be greater than zero")
        self.database_url = database_url
        self.query_batch_size = query_batch_size
        self.accumulator = SourceChangeAccumulator(started_at)

    def scan_until(self, cutoff: datetime) -> int:
        if cutoff <= self.accumulator.scanned_through:
            return 0

        scanned_before = self.accumulator.rows_scanned
        with _read_only_connection(self.database_url) as connection:
            while True:
                rows = connection.execute(
                    """
                    SELECT mint, observed_at, payload->>'updatedAt'
                    FROM mint_snapshots
                    WHERE observed_at >= %(started_at)s
                      AND observed_at < %(cutoff)s
                      AND (observed_at, mint) > (
                          %(cursor_observed_at)s,
                          %(cursor_mint)s
                      )
                    ORDER BY observed_at, mint
                    LIMIT %(batch_size)s
                    """,
                    {
                        "started_at": self.accumulator.started_at,
                        "cutoff": cutoff,
                        "cursor_observed_at": self.accumulator.cursor_observed_at,
                        "cursor_mint": self.accumulator.cursor_mint,
                        "batch_size": self.query_batch_size,
                    },
                ).fetchall()
                if not rows:
                    break

                for mint, observed_at, source_updated_at in rows:
                    self.accumulator.consume_row(
                        mint=mint,
                        observed_at=observed_at,
                        source_updated_at=source_updated_at,
                    )

                if len(rows) < self.query_batch_size:
                    break

        self.accumulator.scanned_through = cutoff
        return self.accumulator.rows_scanned - scanned_before

    def load_population_metadata(self, ended_at: datetime) -> int:
        with _read_only_connection(self.database_url) as connection:
            rows = connection.execute(
                """
                SELECT mint, name, symbol, first_observed_at, disabled_at
                FROM mints
                WHERE first_observed_at IS NOT NULL
                  AND first_observed_at < %(ended_at)s
                  AND (disabled_at IS NULL OR disabled_at >= %(started_at)s)
                ORDER BY mint
                """,
                {
                    "started_at": self.accumulator.started_at,
                    "ended_at": ended_at,
                },
            ).fetchall()
        self.accumulator.apply_population_metadata(rows, ended_at=ended_at)
        return len(rows)

    def summary(self, ended_at: datetime | None = None) -> dict[str, Any]:
        return self.accumulator.summary(ended_at=ended_at)

    def write_per_mint_csv(self, output: Path) -> None:
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_name(f"{output.name}.tmp")
        fieldnames = [
            "mint",
            "name",
            "symbol",
            "active_hours",
            "source_versions",
            "measured_intervals",
            "changes_per_active_hour",
            "min_interval_seconds",
            "mean_interval_seconds",
            "max_interval_seconds",
            "min_interval_from",
            "min_interval_to",
            "max_interval_from",
            "max_interval_to",
            "first_source_at",
            "last_source_at",
            *[
                _csv_target_field(target)
                for target in CAPACITY_TARGET_SWEEPS_SECONDS
            ],
            "non_monotonic_versions",
        ]

        with temporary.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for payload in self.accumulator.per_mint_rows():
                interval_counts = payload.pop("interval_counts_below_target")
                for target in CAPACITY_TARGET_SWEEPS_SECONDS:
                    payload[_csv_target_field(target)] = interval_counts[
                        _target_label(target)
                    ]
                writer.writerow(payload)
        temporary.replace(output)