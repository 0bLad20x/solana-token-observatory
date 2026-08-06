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
    observations: int
    new_payloads: int


def canonical_json_hash(value: Any) -> str:
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def raw_payload_hash(payload: dict[str, Any]) -> str:
    return canonical_json_hash(payload)


def content_payload_hash(payload: dict[str, Any]) -> str:
    content = dict(payload)
    content.pop("updatedAt", None)
    return canonical_json_hash(content)


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
        observations = 0
        new_payloads = 0

        with psycopg.connect(self._database_url) as connection:
            for fetched in fetched_tokens:
                payload = fetched.payload
                mint = payload["id"]
                raw_hash = raw_payload_hash(payload)
                content_hash = content_payload_hash(payload)

                payload_cursor = connection.execute(
                    """
                    INSERT INTO jupiter_payloads (
                        mint,
                        raw_hash,
                        content_hash,
                        source_updated_at,
                        payload
                    )
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (mint, raw_hash) DO NOTHING
                    RETURNING raw_hash
                    """,
                    (
                        mint,
                        raw_hash,
                        content_hash,
                        source_updated_at(payload),
                        Jsonb(payload),
                    ),
                )
                if payload_cursor.fetchone() is not None:
                    new_payloads += 1

                connection.execute(
                    """
                    INSERT INTO jupiter_observations (
                        mint,
                        observed_at,
                        raw_hash
                    )
                    VALUES (%s, %s, %s)
                    """,
                    (mint, fetched.received_at, raw_hash),
                )
                observations += 1

        return StoreSummary(
            observations=observations,
            new_payloads=new_payloads,
        )
