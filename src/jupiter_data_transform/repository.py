from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from importlib.resources import files
from typing import Any

import psycopg
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
        self._database_url = database_url
        self._last_updated_at: dict[str, str] = {}
        self._pool = ConnectionPool(database_url, min_size=2, max_size=pool_max_size, open=True)

    def initialize_schema(self) -> None:
        schema_path = files("jupiter_data_transform").joinpath("sql/schema.sql")
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
        query = """
            SELECT mint FROM mints
            WHERE tracking_enabled = true AND priority = %s
        """
        with self._pool.connection() as connection:
            rows = connection.execute(query, (priority,)).fetchall()
        return [row[0] for row in rows]

    def insert_new_mints(self, candidates: Sequence[str]) -> int:
        """Discovery-Einstiegspunkt: legt Mint-Stubs (nur mint/priority/tracking_enabled) an.
        Bereits bekannte Adressen werden per Bulk-SELECT gegen den PK-Index verworfen,
        bevor ueberhaupt ein Insert versucht wird."""
        if not candidates:
            return 0

        unique_candidates = list(dict.fromkeys(candidates))

        with self._pool.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT mint FROM mints WHERE mint = ANY(%s)",
                    (unique_candidates,),
                )
                existing = {row[0] for row in cursor.fetchall()}
                new_candidates = [c for c in unique_candidates if c not in existing]

                if new_candidates:
                    cursor.executemany(
                        """
                        INSERT INTO mints (mint, priority, tracking_enabled)
                        VALUES (%s, 1, true)
                        ON CONFLICT (mint) DO NOTHING
                        """,
                        [(c,) for c in new_candidates],
                    )
            connection.commit()

        return len(new_candidates)

    def store_tokens_grouped(self, tokens: Sequence[dict[str, Any]]) -> StoreSummary:
        """Search-Endpoint-Ergebnisse: befuellt fehlende Basisdaten (nur beim allerersten
        Mal, siehe WHERE mints.name IS NULL) und schreibt mint_snapshots."""
        if not tokens:
            return StoreSummary(new_mints=0, new_snapshots=0)

        mint_rows: list[tuple] = []
        snapshot_rows: list[tuple] = []

        for token in tokens:
            mint = token["id"]
            updated_at = token["updatedAt"]
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

            if self._last_updated_at.get(mint) != updated_at:
                token_copy = {k: v for k, v in token.items() if k != "_observed_at"}
                snapshot_rows.append((mint, observed_at, Jsonb(token_copy)))
                self._last_updated_at[mint] = updated_at

        mint_addresses = [row[0] for row in mint_rows]

        with self._pool.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT mint, name FROM mints WHERE mint = ANY(%s)",
                    (mint_addresses,),
                )
                existing_names = dict(cursor.fetchall())
                enriched = sum(1 for m in mint_addresses if existing_names.get(m) is None)

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
                    mint_rows,
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

        return StoreSummary(new_mints=enriched, new_snapshots=len(snapshot_rows))