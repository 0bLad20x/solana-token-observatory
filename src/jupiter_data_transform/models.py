from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class RollingStats(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    price_change: Decimal | None = Field(default=None, alias="priceChange")
    holder_change: Decimal | None = Field(default=None, alias="holderChange")
    liquidity_change: Decimal | None = Field(default=None, alias="liquidityChange")
    volume_change: Decimal | None = Field(default=None, alias="volumeChange")
    buy_volume: Decimal | None = Field(default=None, alias="buyVolume")
    sell_volume: Decimal | None = Field(default=None, alias="sellVolume")
    num_buys: int | None = Field(default=None, alias="numBuys")
    num_sells: int | None = Field(default=None, alias="numSells")
    num_traders: int | None = Field(default=None, alias="numTraders")


class JupiterToken(BaseModel):
    """Typed subset of Tokens V2. Unknown fields stay available in the raw payload."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    mint: str = Field(alias="id")
    name: str | None = None
    symbol: str | None = None
    decimals: int | None = None
    token_program: str | None = Field(default=None, alias="tokenProgram")
    created_at: datetime | None = Field(default=None, alias="createdAt")
    updated_at: datetime | None = Field(default=None, alias="updatedAt")
    usd_price: Decimal | None = Field(default=None, alias="usdPrice")
    market_cap: Decimal | None = Field(default=None, alias="mcap")
    fdv: Decimal | None = None
    liquidity: Decimal | None = None
    holder_count: int | None = Field(default=None, alias="holderCount")
    circ_supply: Decimal | None = Field(default=None, alias="circSupply")
    total_supply: Decimal | None = Field(default=None, alias="totalSupply")
    organic_score: Decimal | None = Field(default=None, alias="organicScore")
    is_verified: bool | None = Field(default=None, alias="isVerified")
    price_block_id: int | None = Field(default=None, alias="priceBlockId")
    stats_5m: RollingStats | None = Field(default=None, alias="stats5m")


@dataclass(frozen=True, slots=True)
class FetchedToken:
    request_id: UUID
    received_at: datetime
    payload: dict[str, Any]

    def __post_init__(self) -> None:
        if self.received_at.tzinfo is None:
            raise ValueError("received_at must be timezone-aware")


@dataclass(frozen=True, slots=True)
class TokenSnapshot:
    request_id: UUID
    mint: str
    observed_at: datetime
    source_updated_at: datetime | None
    name: str | None
    symbol: str | None
    decimals: int | None
    token_program: str | None
    price_block_id: int | None
    usd_price: Decimal | None
    market_cap: Decimal | None
    fdv: Decimal | None
    liquidity: Decimal | None
    holder_count: int | None
    circ_supply: Decimal | None
    total_supply: Decimal | None
    organic_score: Decimal | None
    is_verified: bool | None
    buy_volume_5m: Decimal | None
    sell_volume_5m: Decimal | None
    num_buys_5m: int | None
    num_sells_5m: int | None
    num_traders_5m: int | None
    holder_change_5m: Decimal | None

    @classmethod
    def from_fetched(cls, fetched: FetchedToken) -> TokenSnapshot:
        token = JupiterToken.model_validate(fetched.payload)
        stats = token.stats_5m
        return cls(
            request_id=fetched.request_id,
            mint=token.mint,
            observed_at=fetched.received_at.astimezone(timezone.utc),
            source_updated_at=token.updated_at,
            name=token.name,
            symbol=token.symbol,
            decimals=token.decimals,
            token_program=token.token_program,
            price_block_id=token.price_block_id,
            usd_price=token.usd_price,
            market_cap=token.market_cap,
            fdv=token.fdv,
            liquidity=token.liquidity,
            holder_count=token.holder_count,
            circ_supply=token.circ_supply,
            total_supply=token.total_supply,
            organic_score=token.organic_score,
            is_verified=token.is_verified,
            buy_volume_5m=stats.buy_volume if stats else None,
            sell_volume_5m=stats.sell_volume if stats else None,
            num_buys_5m=stats.num_buys if stats else None,
            num_sells_5m=stats.num_sells if stats else None,
            num_traders_5m=stats.num_traders if stats else None,
            holder_change_5m=stats.holder_change if stats else None,
        )
