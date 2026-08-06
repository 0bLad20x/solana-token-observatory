from __future__ import annotations

import hashlib
import json
from importlib.resources import files

from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from .models import FetchedToken, TokenSnapshot


class JupiterRepository:
    def __init__(self, database_url: str) -> None:
        self._pool = AsyncConnectionPool(
            conninfo=database_url,
            min_size=1,
            max_size=5,
            open=False,
        )

    async def __aenter__(self) -> JupiterRepository:
        await self.open()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def open(self) -> None:
        await self._pool.open()
        await self._pool.wait()

    async def close(self) -> None:
        await self._pool.close()

    async def initialize_schema(self) -> None:
        schema_path = files("jupiter_data_transform").joinpath("sql/001_initial.sql")
        schema_sql = schema_path.read_text(encoding="utf-8")
        statements = [statement.strip() for statement in schema_sql.split(";") if statement.strip()]
        async with self._pool.connection() as connection:
            for statement in statements:
                await connection.execute(statement)

    async def store(self, fetched: FetchedToken) -> int:
        snapshot = TokenSnapshot.from_fetched(fetched)
        canonical_payload = json.dumps(
            fetched.payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        payload_hash = hashlib.sha256(canonical_payload.encode("utf-8")).hexdigest()

        async with self._pool.connection() as connection:
            async with connection.transaction():
                cursor = await connection.execute(
                    """
                    INSERT INTO jupiter_raw_updates (
                        request_id, mint, source_updated_at, received_at, payload_hash, payload
                    )
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        fetched.request_id,
                        snapshot.mint,
                        snapshot.source_updated_at,
                        snapshot.observed_at,
                        payload_hash,
                        Jsonb(fetched.payload),
                    ),
                )
                raw_row = await cursor.fetchone()
                if raw_row is None:
                    raise RuntimeError("raw Jupiter insert returned no id")
                raw_update_id = int(raw_row[0])

                await connection.execute(
                    """
                    INSERT INTO jupiter_snapshots (
                        raw_update_id, request_id, mint, observed_at, source_updated_at,
                        name, symbol, decimals, token_program, price_block_id,
                        usd_price, market_cap, fdv, liquidity, holder_count,
                        circ_supply, total_supply, organic_score, is_verified,
                        buy_volume_5m, sell_volume_5m, num_buys_5m, num_sells_5m,
                        num_traders_5m, holder_change_5m
                    )
                    VALUES (
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s
                    )
                    """,
                    (
                        raw_update_id,
                        snapshot.request_id,
                        snapshot.mint,
                        snapshot.observed_at,
                        snapshot.source_updated_at,
                        snapshot.name,
                        snapshot.symbol,
                        snapshot.decimals,
                        snapshot.token_program,
                        snapshot.price_block_id,
                        snapshot.usd_price,
                        snapshot.market_cap,
                        snapshot.fdv,
                        snapshot.liquidity,
                        snapshot.holder_count,
                        snapshot.circ_supply,
                        snapshot.total_supply,
                        snapshot.organic_score,
                        snapshot.is_verified,
                        snapshot.buy_volume_5m,
                        snapshot.sell_volume_5m,
                        snapshot.num_buys_5m,
                        snapshot.num_sells_5m,
                        snapshot.num_traders_5m,
                        snapshot.holder_change_5m,
                    ),
                )

        return raw_update_id
