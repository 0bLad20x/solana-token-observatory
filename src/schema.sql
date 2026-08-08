CREATE TABLE IF NOT EXISTS mints (
    mint TEXT PRIMARY KEY,
    dev TEXT,
    name TEXT,
    symbol TEXT,
    decimals INTEGER,
    icon TEXT,
    twitter TEXT,
    website TEXT,
    token_program TEXT,
    created_at TIMESTAMPTZ,
    first_pool_id TEXT,
    first_pool_created_at TIMESTAMPTZ,
    mint_authority_disabled BOOLEAN,
    freeze_authority_disabled BOOLEAN,
    tracking_enabled BOOLEAN NOT NULL DEFAULT true,
    priority INTEGER NOT NULL DEFAULT 1,
    last_polled_at TIMESTAMPTZ,
    unchanged_since TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS ix_mints_priority_tracking_mint
    ON mints (priority, mint)
    WHERE tracking_enabled = true;

CREATE TABLE IF NOT EXISTS mint_snapshots (
    mint TEXT NOT NULL REFERENCES mints(mint),
    observed_at TIMESTAMPTZ NOT NULL,
    payload JSONB NOT NULL,
    PRIMARY KEY (mint, observed_at)
);

CREATE INDEX IF NOT EXISTS ix_mint_snapshots_mint_observed
    ON mint_snapshots (mint, observed_at DESC);


CREATE TABLE IF NOT EXISTS gmgn_mint_observations (
    run_id TIMESTAMPTZ NOT NULL,
    mint TEXT NOT NULL,
    source TEXT NOT NULL,

    market_cap DOUBLE PRECISION,
    liquidity DOUBLE PRECISION,
    volume_24h DOUBLE PRECISION,
    holder_count INTEGER,

    priority_fee DOUBLE PRECISION,
    tip_fee DOUBLE PRECISION,
    trade_fee DOUBLE PRECISION,
    total_fee DOUBLE PRECISION,

    bot_degen_count INTEGER,
    bot_degen_rate DOUBLE PRECISION,
    smart_degen_count INTEGER,

    bundler_mhr DOUBLE PRECISION,
    bundler_trader_amount_rate DOUBLE PRECISION,

    sniper_count INTEGER,
    top70_sniper_hold_rate DOUBLE PRECISION,

    fresh_wallet_rate DOUBLE PRECISION,
    rat_trader_amount_rate DOUBLE PRECISION,
    suspected_insider_hold_rate DOUBLE PRECISION,

    rug_ratio DOUBLE PRECISION,
    entrapment_ratio DOUBLE PRECISION,
    dev_team_hold_rate DOUBLE PRECISION,

    burn_status TEXT,
    is_honeypot BOOLEAN,
    is_wash_trading BOOLEAN,

    creator_token_status TEXT,
    creator_created_count INTEGER,
    creator_created_open_ratio DOUBLE PRECISION,

    raw_data JSONB NOT NULL,

    PRIMARY KEY (run_id, mint)
);

CREATE INDEX IF NOT EXISTS ix_gmgn_mint_observations_mint_run
    ON gmgn_mint_observations (mint, run_id DESC);