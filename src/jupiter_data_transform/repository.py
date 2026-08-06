from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from importlib.resources import files
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from .jupiter import FetchedToken

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class StoreSummary:
    inserted: int
    repeated: int


def canonical_payload_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def source_updated_at(payload: dict[str, Any]) -> datetime | None:
    value = payload.get("updatedAt")
    if value is None:
        return None
    if not isinstance(value, str):
        LOGGER.warning("invalid_updated_at_type mint=%s", payload.get("id"))
        return None

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        LOGGER.warning("invalid_updated_at_value mint=%s value=%r", payload.get("id"), value)
        return None

    if parsed.tzinfo is None:
        LOGGER.warning("naive_updated_at_value mint=%s value=%r", payload.get("id"), value)
        return None
    return parsed


class JupiterRepository:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def initialize_schema(self) -> None:
        schema_path = files("jupiter_data_transform").joinpath("sql/001_initial.sql")
        statements = [
            statement.strip()
            for statement in schema_path.read_text(encoding="utf-8").split(";")
            if statement.strip()
        ]
        with psycopg.connect(self._database_url) as connection:
            for statement in statements:
                connection.execute(statement)

    def store_many(self, fetched_tokens: Sequence[FetchedToken]) -> StoreSummary:
        inserted = 0
        repeated = 0

        with psycopg.connect(self._database_url) as connection:
            for fetched in fetched_tokens:
                payload = fetched.payload
                mint = payload["id"]
                payload_hash = canonical_payload_hash(payload)
                cursor = connection.execute(
                    """
                    INSERT INTO jupiter_observations (
                        mint,
                        payload_hash,
                        first_seen_at,
                        last_seen_at,
                        source_updated_at,
                        seen_count,
                        payload
                    )
                    VALUES (%s, %s, %s, %s, %s, 1, %s)
                    ON CONFLICT (mint, payload_hash) DO UPDATE SET
                        first_seen_at = LEAST(
                            jupiter_observations.first_seen_at,
                            EXCLUDED.first_seen_at
                        ),
                        last_seen_at = GREATEST(
                            jupiter_observations.last_seen_at,
                            EXCLUDED.last_seen_at
                        ),
                        seen_count = jupiter_observations.seen_count + 1
                    RETURNING seen_count
                    """,
                    (
                        mint,
                        payload_hash,
                        fetched.received_at,
                        fetched.received_at,
                        source_updated_at(payload),
                        Jsonb(payload),
                    ),
                )
                row = cursor.fetchone()
                if row is None:
                    raise RuntimeError("observation upsert returned no seen_count")
                if row[0] == 1:
                    inserted += 1
                else:
                    repeated += 1

        return StoreSummary(inserted=inserted, repeated=repeated)
