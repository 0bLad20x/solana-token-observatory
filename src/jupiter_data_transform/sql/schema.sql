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
    priority INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS ix_mints_priority_tracking
    ON mints (priority)
    WHERE tracking_enabled = true;

CREATE TABLE IF NOT EXISTS mint_snapshots (
    mint TEXT NOT NULL REFERENCES mints(mint),
    observed_at TIMESTAMPTZ NOT NULL,
    payload JSONB NOT NULL,
    PRIMARY KEY (mint, observed_at)
);

CREATE INDEX IF NOT EXISTS ix_mint_snapshots_mint_observed
    ON mint_snapshots (mint, observed_at DESC);