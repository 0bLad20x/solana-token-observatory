from __future__ import annotations

import functools
import time
from pathlib import Path

import psycopg
from psycopg_pool import ConnectionPool

DEFAULT_POOL_MIN_SIZE = 2
DEFAULT_POOL_MAX_SIZE = 20

_DEADLOCK_MAX_ATTEMPTS = 3
_DEADLOCK_RETRY_SECONDS = 0.2


def retry_on_deadlock(fn):
    """Retry a transaction only when PostgreSQL explicitly reports a deadlock."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        for attempt in range(_DEADLOCK_MAX_ATTEMPTS):
            try:
                return fn(*args, **kwargs)
            except psycopg.errors.DeadlockDetected:
                if attempt == _DEADLOCK_MAX_ATTEMPTS - 1:
                    raise
                time.sleep(_DEADLOCK_RETRY_SECONDS * (attempt + 1))

    return wrapper


class Database:
    """Own the process-wide PostgreSQL connection pool."""

    def __init__(
        self,
        database_url: str,
        min_size: int = DEFAULT_POOL_MIN_SIZE,
        max_size: int = DEFAULT_POOL_MAX_SIZE,
    ) -> None:
        self._pool = ConnectionPool(
            database_url,
            min_size=min_size,
            max_size=max_size,
            open=True,
        )

    def connection(self):
        return self._pool.connection()

    def initialize_schema(self) -> None:
        schema_path = Path(__file__).with_name("schema.sql")
        with self.connection() as connection:
            connection.execute(schema_path.read_text(encoding="utf-8"))
            connection.commit()

    def close(self) -> None:
        self._pool.close()

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()
