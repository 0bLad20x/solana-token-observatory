from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from psycopg.types.json import Jsonb

from database import Database, retry_on_deadlock


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _payload(token: dict[str, Any]) -> Jsonb:
    return Jsonb(
        {
            key: value
            for key, value in token.items()
            if key not in {"_observed_at", "_last_polled_at"}
        }
    )


@dataclass(frozen=True, slots=True)
class StoreSummary:
    new_mints: int
    new_snapshots: int


class MintRepository:
    """Persistence only: mint facts, observations, active state."""

    def __init__(self, database: Database) -> None:
        self._db = database

    def load_active_mints_by_priority(self, priority: int) -> list[str]:
        with self._db.connection() as connection:
            rows = connection.execute(
                "SELECT mint FROM mints "
                "WHERE tracking_enabled = true AND priority = %s "
                "ORDER BY mint",
                (priority,),
            ).fetchall()
        return [row[0] for row in rows]

    @retry_on_deadlock
    def insert_new_mints(self, candidates: Sequence[str]) -> int:
        if not candidates:
            return 0

        unique_candidates = sorted(set(candidates))

        with self._db.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO mints (mint, priority, tracking_enabled)
                    SELECT mint, 1, true
                    FROM unnest(%s::text[]) AS candidate(mint)
                    ORDER BY mint
                    ON CONFLICT (mint) DO NOTHING
                    RETURNING mint
                    """,
                    (unique_candidates,),
                )
                inserted = len(cursor.fetchall())
            connection.commit()

        return inserted

    @retry_on_deadlock
    def store_tokens_grouped(
        self,
        tokens: Sequence[dict[str, Any]],
    ) -> StoreSummary:
        """Persist every observed Jupiter source version in one transaction.

        WriteQueue already collapses identical `(mint, updatedAt)` versions.
        This method advances each mint monotonically by Jupiter `updatedAt`,
        persists every newer source version, and updates `last_polled_at`
        independently from source changes.
        """
        if not tokens:
            return StoreSummary(new_mints=0, new_snapshots=0)

        versions_by_mint: dict[
            str,
            list[tuple[datetime, dict[str, Any]]],
        ] = {}
        last_polled_by_mint: dict[str, datetime] = {}

        for token in tokens:
            mint = token["id"]
            source_time = _parse_datetime(token["updatedAt"])
            versions_by_mint.setdefault(mint, []).append((source_time, token))

            last_polled = token.get("_last_polled_at", token["_observed_at"])
            previous_poll = last_polled_by_mint.get(mint)
            if previous_poll is None or last_polled > previous_poll:
                last_polled_by_mint[mint] = last_polled

        for rows in versions_by_mint.values():
            rows.sort(key=lambda row: row[0])

        poll_mints = sorted(versions_by_mint)

        # Descriptive mint facts come from the newest source version in this
        # flush, never from whichever HTTP response happened to finish last.
        mint_rows = []
        for mint in poll_mints:
            token = versions_by_mint[mint][-1][1]
            first_pool = token.get("firstPool")
            audit = token.get("audit", {})

            mint_rows.append(
                (
                    mint,
                    token.get("dev"),
                    token["name"],
                    token["symbol"],
                    token["decimals"],
                    token.get("icon"),
                    token.get("twitter"),
                    token.get("website"),
                    token["tokenProgram"],
                    _parse_datetime(token["createdAt"])
                    if token.get("createdAt")
                    else None,
                    first_pool["id"] if first_pool else None,
                    _parse_datetime(first_pool["createdAt"])
                    if first_pool
                    else None,
                    audit.get("mintAuthorityDisabled"),
                    audit.get("freezeAuthorityDisabled"),
                )
            )

        with self._db.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT mint, name, source_updated_at
                    FROM mints
                    WHERE mint = ANY(%s)
                    """,
                    (poll_mints,),
                )
                existing_rows = {
                    mint: (name, source_updated_at)
                    for mint, name, source_updated_at in cursor.fetchall()
                }

                mint_rows_to_enrich = sorted(
                    (
                        row
                        for row in mint_rows
                        if existing_rows.get(row[0], (None, None))[0] is None
                    ),
                    key=lambda row: row[0],
                )
                enriched = len(mint_rows_to_enrich)

                if mint_rows_to_enrich:
                    cursor.executemany(
                        """
                        INSERT INTO mints (
                            mint, dev, name, symbol, decimals, icon, twitter, website,
                            token_program, created_at, first_pool_id, first_pool_created_at,
                            mint_authority_disabled, freeze_authority_disabled
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (mint) DO UPDATE SET
                            dev = EXCLUDED.dev,
                            name = EXCLUDED.name,
                            symbol = EXCLUDED.symbol,
                            decimals = EXCLUDED.decimals,
                            icon = EXCLUDED.icon,
                            twitter = EXCLUDED.twitter,
                            website = EXCLUDED.website,
                            token_program = EXCLUDED.token_program,
                            created_at = EXCLUDED.created_at,
                            first_pool_id = EXCLUDED.first_pool_id,
                            first_pool_created_at = EXCLUDED.first_pool_created_at,
                            mint_authority_disabled = EXCLUDED.mint_authority_disabled,
                            freeze_authority_disabled = EXCLUDED.freeze_authority_disabled
                        WHERE mints.name IS NULL
                        """,
                        mint_rows_to_enrich,
                    )

                snapshot_rows: list[tuple[str, datetime, Jsonb]] = []
                source_updates: dict[
                    str,
                    tuple[str | None, datetime | None, datetime | None],
                ] = {}

                for mint in poll_mints:
                    previous_text = existing_rows.get(mint, (None, None))[1]
                    previous_time = (
                        _parse_datetime(previous_text)
                        if previous_text
                        else None
                    )

                    newer = [
                        (source_time, token)
                        for source_time, token in versions_by_mint[mint]
                        if previous_time is None or source_time > previous_time
                    ]

                    for _source_time, token in newer:
                        snapshot_rows.append(
                            (
                                mint,
                                token["_observed_at"],
                                _payload(token),
                            )
                        )

                    if newer:
                        newest_token = newer[-1][1]
                        source_updates[mint] = (
                            newest_token["updatedAt"],
                            newest_token["_observed_at"],
                            min(
                                token["_observed_at"]
                                for _source_time, token in newer
                            ),
                        )
                    else:
                        source_updates[mint] = (None, None, None)

                cursor.execute(
                    """
                    WITH polled AS (
                        SELECT * FROM unnest(
                            %s::text[],
                            %s::timestamptz[],
                            %s::text[],
                            %s::timestamptz[],
                            %s::timestamptz[]
                        ) AS p(
                            mint,
                            last_polled_at,
                            source_updated_at,
                            last_changed_at,
                            first_observed_at
                        )
                        ORDER BY mint
                    )
                    UPDATE mints AS m
                    SET
                        first_observed_at = COALESCE(
                            m.first_observed_at,
                            p.first_observed_at
                        ),
                        last_polled_at = CASE
                            WHEN m.last_polled_at IS NULL
                              OR p.last_polled_at > m.last_polled_at
                            THEN p.last_polled_at
                            ELSE m.last_polled_at
                        END,
                        last_changed_at = COALESCE(
                            p.last_changed_at,
                            m.last_changed_at
                        ),
                        source_updated_at = COALESCE(
                            p.source_updated_at,
                            m.source_updated_at
                        )
                    FROM polled AS p
                    WHERE m.mint = p.mint
                    """,
                    (
                        poll_mints,
                        [last_polled_by_mint[mint] for mint in poll_mints],
                        [source_updates[mint][0] for mint in poll_mints],
                        [source_updates[mint][1] for mint in poll_mints],
                        [source_updates[mint][2] for mint in poll_mints],
                    ),
                )

                if snapshot_rows:
                    cursor.executemany(
                        """
                        INSERT INTO mint_snapshots (mint, observed_at, payload)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (mint, observed_at) DO NOTHING
                        """,
                        snapshot_rows,
                    )

            connection.commit()

        return StoreSummary(
            new_mints=enriched,
            new_snapshots=len(snapshot_rows),
        )

    @retry_on_deadlock
    def delete_expired_snapshots(
        self,
        cutoff: datetime,
        batch_size: int,
    ) -> int:
        """Delete one batch of raw snapshots older than the retention cutoff."""
        if batch_size <= 0:
            raise ValueError("batch_size must be greater than zero")

        with self._db.connection() as connection:
            cursor = connection.execute(
                """
                WITH candidates AS (
                    SELECT ctid
                    FROM mint_snapshots
                    WHERE observed_at < %(cutoff)s
                    ORDER BY observed_at
                    LIMIT %(batch_size)s
                )
                DELETE FROM mint_snapshots AS s
                USING candidates AS c
                WHERE s.ctid = c.ctid
                """,
                {
                    "cutoff": cutoff,
                    "batch_size": batch_size,
                },
            )
            deleted = cursor.rowcount
            connection.commit()

        return deleted

    @retry_on_deadlock
    def disable_mints(self, candidates: Sequence[dict[str, Any]]) -> set[str]:
        if not candidates:
            return set()

        with self._db.connection() as connection:
            rows = connection.execute(
                """
                WITH candidates AS (
                    SELECT * FROM unnest(
                        %(mints)s::text[],
                        %(reasons)s::text[]
                    ) AS c(mint, reason)
                    ORDER BY mint
                )
                UPDATE mints AS m
                SET
                    tracking_enabled = false,
                    disabled_at = CURRENT_TIMESTAMP,
                    disabled_reason = c.reason
                FROM candidates AS c
                WHERE m.mint = c.mint
                  AND m.tracking_enabled = true
                RETURNING m.mint
                """,
                {
                    "mints": [candidate["mint"] for candidate in candidates],
                    "reasons": [candidate["reason"] for candidate in candidates],
                },
            ).fetchall()
            connection.commit()

        return {row[0] for row in rows}

    def count_active(self) -> int:
        with self._db.connection() as connection:
            return connection.execute(
                "SELECT COUNT(*) FROM mints WHERE tracking_enabled = true"
            ).fetchone()[0]
