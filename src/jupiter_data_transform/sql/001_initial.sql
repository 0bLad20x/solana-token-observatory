CREATE TABLE IF NOT EXISTS jupiter_raw_updates (
    id BIGSERIAL PRIMARY KEY,
    request_id UUID NOT NULL,
    mint TEXT NOT NULL,
    source_updated_at TIMESTAMPTZ,
    received_at TIMESTAMPTZ NOT NULL,
    payload_hash CHAR(64) NOT NULL,
    payload JSONB NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_jupiter_raw_mint_received
    ON jupiter_raw_updates (mint, received_at DESC);

CREATE INDEX IF NOT EXISTS ix_jupiter_raw_request
    ON jupiter_raw_updates (request_id);

CREATE TABLE IF NOT EXISTS jupiter_snapshots (
    id BIGSERIAL PRIMARY KEY,
    raw_update_id BIGINT NOT NULL UNIQUE
        REFERENCES jupiter_raw_updates(id) ON DELETE CASCADE,
    request_id UUID NOT NULL,
    mint TEXT NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL,
    source_updated_at TIMESTAMPTZ,
    name TEXT,
    symbol TEXT,
    decimals INTEGER,
    token_program TEXT,
    price_block_id BIGINT,
    usd_price NUMERIC,
    market_cap NUMERIC,
    fdv NUMERIC,
    liquidity NUMERIC,
    holder_count BIGINT,
    circ_supply NUMERIC,
    total_supply NUMERIC,
    organic_score NUMERIC,
    is_verified BOOLEAN,
    buy_volume_5m NUMERIC,
    sell_volume_5m NUMERIC,
    num_buys_5m BIGINT,
    num_sells_5m BIGINT,
    num_traders_5m BIGINT,
    holder_change_5m NUMERIC
);

CREATE INDEX IF NOT EXISTS ix_jupiter_snapshots_mint_observed
    ON jupiter_snapshots (mint, observed_at DESC);

CREATE INDEX IF NOT EXISTS ix_jupiter_snapshots_source_updated
    ON jupiter_snapshots (mint, source_updated_at DESC);
