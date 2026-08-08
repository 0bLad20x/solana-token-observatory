from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


@dataclass(frozen=True, slots=True)
class StoreSummary:
    new_mints: int
    new_snapshots: int


class MintRepository:
    def __init__(self, database_url: str, pool_max_size: int = 20) -> None:
        self._last_updated_at: dict[str, str] = {}
        self._pool = ConnectionPool(database_url, min_size=2, max_size=pool_max_size, open=True)

    def initialize_schema(self) -> None:
        schema_path = Path(__file__).with_name("schema.sql")
        statements = [s.strip() for s in schema_path.read_text(encoding="utf-8").split(";") if s.strip()]
        with self._pool.connection() as connection:
            for statement in statements:
                connection.execute(statement)

    def load_last_updated_at(self) -> None:
        query = """
            SELECT DISTINCT ON (mint) mint, payload ->> 'updatedAt'
            FROM mint_snapshots
            ORDER BY mint, observed_at DESC
        """
        with self._pool.connection() as connection:
            rows = connection.execute(query).fetchall()
        self._last_updated_at = dict(rows)

    def load_active_mints_by_priority(self, priority: int) -> list[str]:
        with self._pool.connection() as connection:
            rows = connection.execute(
                "SELECT mint FROM mints WHERE tracking_enabled = true AND priority = %s ORDER BY mint",
                (priority,),
            ).fetchall()
        return [row[0] for row in rows]

    def insert_new_mints(self, candidates: Sequence[str]) -> int:
        if not candidates:
            return 0

        unique_candidates = sorted(set(candidates))

        with self._pool.connection() as connection:
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

    def store_tokens_grouped(self, tokens: Sequence[dict[str, Any]]) -> StoreSummary:
        if not tokens:
            return StoreSummary(new_mints=0, new_snapshots=0)

        mint_rows = []
        snapshot_rows = []
        changed_poll_rows: list[tuple] = []
        unchanged_poll_rows: list[tuple] = []

        for token in tokens:
            mint = token["id"]
            updated_at = token["updatedAt"]
            observed_at = token["_observed_at"]
            first_pool = token.get("firstPool")
            audit = token.get("audit", {})

            mint_rows.append((
                mint, token.get("dev"), token["name"], token["symbol"], token["decimals"],
                token.get("icon"), token.get("twitter"), token.get("website"), token["tokenProgram"],
                _parse_datetime(token["createdAt"]) if token.get("createdAt") else None,
                first_pool["id"] if first_pool else None,
                _parse_datetime(first_pool["createdAt"]) if first_pool else None,
                audit.get("mintAuthorityDisabled"), audit.get("freezeAuthorityDisabled"),
            ))

            previous_updated_at = self._last_updated_at.get(mint)
            if previous_updated_at != updated_at:
                # echte Aenderung (oder allererster Poll): neuer Snapshot,
                # unchanged_since wird auf jetzt zurueckgesetzt.
                payload = {k: v for k, v in token.items() if k != "_observed_at"}
                snapshot_rows.append((mint, observed_at, Jsonb(payload)))
                self._last_updated_at[mint] = updated_at
                changed_poll_rows.append((observed_at, observed_at, mint))
            else:
                # unveraendert seit letztem Poll: nur last_polled_at aktualisieren,
                # unchanged_since bleibt stehen.
                unchanged_poll_rows.append((observed_at, mint))

        mint_addresses = [row[0] for row in mint_rows]

        with self._pool.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT mint, name FROM mints WHERE mint = ANY(%s)",
                    (mint_addresses,),
                )
                existing_names = dict(cursor.fetchall())

                mint_rows_to_enrich = [
                    row
                    for row in mint_rows
                    if existing_names.get(row[0]) is None
                ]

                enriched = len(mint_rows_to_enrich)

                if mint_rows_to_enrich:
                    cursor.executemany(
                        """
                        INSERT INTO mints (
                            mint, dev, name, symbol, decimals, icon, twitter, website, token_program,
                            created_at, first_pool_id, first_pool_created_at,
                            mint_authority_disabled, freeze_authority_disabled
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (mint) DO UPDATE SET
                            dev = EXCLUDED.dev, name = EXCLUDED.name, symbol = EXCLUDED.symbol,
                            decimals = EXCLUDED.decimals, icon = EXCLUDED.icon, twitter = EXCLUDED.twitter,
                            website = EXCLUDED.website, token_program = EXCLUDED.token_program,
                            created_at = EXCLUDED.created_at, first_pool_id = EXCLUDED.first_pool_id,
                            first_pool_created_at = EXCLUDED.first_pool_created_at,
                            mint_authority_disabled = EXCLUDED.mint_authority_disabled,
                            freeze_authority_disabled = EXCLUDED.freeze_authority_disabled
                        WHERE mints.name IS NULL
                        """,
                        mint_rows_to_enrich,
                    )

                if snapshot_rows:
                    cursor.executemany(
                        "INSERT INTO mint_snapshots (mint, observed_at, payload) VALUES (%s, %s, %s) ON CONFLICT (mint, observed_at) DO NOTHING",
                        snapshot_rows,
                    )

                poll_mints = (
                    [mint for _, _, mint in changed_poll_rows]
                    + [mint for _, mint in unchanged_poll_rows]
                )

                poll_times = (
                    [last_polled_at for last_polled_at, _, _ in changed_poll_rows]
                    + [last_polled_at for last_polled_at, _ in unchanged_poll_rows]
                )

                poll_changed = (
                    [True] * len(changed_poll_rows)
                    + [False] * len(unchanged_poll_rows)
                )

                if poll_mints:
                    cursor.execute(
                        """
                        WITH updates AS (
                            SELECT
                                mint,
                                MAX(observed_at) AS last_polled_at,
                                MAX(observed_at) FILTER (WHERE changed) AS changed_at
                            FROM unnest(
                                %s::text[],
                                %s::timestamptz[],
                                %s::boolean[]
                            ) AS u(mint, observed_at, changed)
                            GROUP BY mint
                        )
                        UPDATE mints AS m
                        SET
                            last_polled_at = u.last_polled_at,
                            unchanged_since = COALESCE(u.changed_at, m.unchanged_since)
                        FROM updates AS u
                        WHERE m.mint = u.mint
                        """,
                        (poll_mints, poll_times, poll_changed),
                    )
            connection.commit()

        return StoreSummary(new_mints=enriched, new_snapshots=len(snapshot_rows))