from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from psycopg.types.json import Jsonb

from database import Database, retry_on_deadlock


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


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
    def store_tokens_grouped(self, tokens: Sequence[dict[str, Any]]) -> StoreSummary:
        """Persist one collector flush in one transaction.

        High-throughput behaviour is intentionally unchanged: if one mint is
        returned more than once inside a writer flush, only its newest poll
        participates in that flush.
        """
        if not tokens:
            return StoreSummary(new_mints=0, new_snapshots=0)

        latest_by_mint: dict[str, dict[str, Any]] = {}
        for token in tokens:
            mint = token["id"]
            existing = latest_by_mint.get(mint)
            if existing is None or token["_observed_at"] > existing["_observed_at"]:
                latest_by_mint[mint] = token

        mint_rows = []
        poll_mints: list[str] = []
        poll_times: list[datetime] = []
        poll_updated_at: list[str] = []
        payloads: dict[str, tuple[datetime, Jsonb]] = {}

        for token in latest_by_mint.values():
            mint = token["id"]
            observed_at = token["_observed_at"]
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
                    _parse_datetime(token["createdAt"]) if token.get("createdAt") else None,
                    first_pool["id"] if first_pool else None,
                    _parse_datetime(first_pool["createdAt"]) if first_pool else None,
                    audit.get("mintAuthorityDisabled"),
                    audit.get("freezeAuthorityDisabled"),
                )
            )

            poll_mints.append(mint)
            poll_times.append(observed_at)
            poll_updated_at.append(token["updatedAt"])
            payloads[mint] = (
                observed_at,
                Jsonb({key: value for key, value in token.items() if key != "_observed_at"}),
            )

        with self._db.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT mint, name FROM mints WHERE mint = ANY(%s)",
                    (poll_mints,),
                )
                existing_names = dict(cursor.fetchall())

                mint_rows_to_enrich = sorted(
                    (row for row in mint_rows if existing_names.get(row[0]) is None),
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

                # One atomic poll-state update. `previous` sees the committed
                # pre-update state, so change detection and snapshot creation
                # cannot diverge through a rollback.
                cursor.execute(
                    """
                    WITH polled AS (
                        SELECT * FROM unnest(
                            %s::text[],
                            %s::timestamptz[],
                            %s::text[]
                        ) AS p(mint, observed_at, source_updated_at)
                        ORDER BY mint
                    ),
                    previous AS (
                        SELECT
                            m.mint,
                            m.source_updated_at AS previous_updated_at
                        FROM mints m
                        JOIN polled p ON p.mint = m.mint
                    )
                    UPDATE mints AS m
                    SET
                        first_observed_at = CASE
                            WHEN m.first_observed_at IS NULL
                             AND prev.previous_updated_at
                                 IS DISTINCT FROM p.source_updated_at
                            THEN p.observed_at
                            ELSE m.first_observed_at
                        END,
                        last_polled_at = p.observed_at,
                        last_changed_at = CASE
                            WHEN prev.previous_updated_at
                                 IS DISTINCT FROM p.source_updated_at
                            THEN p.observed_at
                            ELSE m.last_changed_at
                        END,
                        source_updated_at = p.source_updated_at
                    FROM polled AS p
                    JOIN previous AS prev ON prev.mint = p.mint
                    WHERE m.mint = p.mint
                    RETURNING
                        m.mint,
                        (
                            prev.previous_updated_at
                            IS DISTINCT FROM p.source_updated_at
                        ) AS changed
                    """,
                    (poll_mints, poll_times, poll_updated_at),
                )
                poll_results = cursor.fetchall()

                snapshot_rows = [
                    (mint, payloads[mint][0], payloads[mint][1])
                    for mint, changed in poll_results
                    if changed
                ]

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
    def disable_mints(self, candidates: Sequence[dict[str, Any]]) -> set[str]:
        if not candidates:
            return set()

        with self._db.connection() as connection:
            rows = connection.execute(
                """
                WITH candidates AS (
                    SELECT * FROM unnest(
                        %(mints)s::text[],
                        %(last_polled_at)s::timestamptz[],
                        %(reasons)s::text[]
                    ) AS c(mint, last_polled_at, reason)
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
                  AND m.last_polled_at IS NOT DISTINCT FROM c.last_polled_at
                RETURNING m.mint
                """,
                {
                    "mints": [candidate["mint"] for candidate in candidates],
                    "last_polled_at": [
                        candidate["last_polled_at"] for candidate in candidates
                    ],
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