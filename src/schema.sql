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

    -- Collector facts.
    first_observed_at TIMESTAMPTZ,
    last_polled_at TIMESTAMPTZ,
    last_changed_at TIMESTAMPTZ,
    source_updated_at TEXT,

    -- Lifecycle audit facts.
    disabled_at TIMESTAMPTZ,
    disabled_reason TEXT
);

CREATE INDEX IF NOT EXISTS ix_mints_priority_tracking_mint
    ON mints (priority, mint)
    WHERE tracking_enabled = true;

CREATE INDEX IF NOT EXISTS ix_mints_first_observed_tracking
    ON mints (first_observed_at)
    WHERE tracking_enabled = true;

CREATE INDEX IF NOT EXISTS ix_mints_created_at_tracking
    ON mints (created_at)
    WHERE tracking_enabled = true;

CREATE TABLE IF NOT EXISTS mint_snapshots (
    mint TEXT NOT NULL REFERENCES mints(mint),
    observed_at TIMESTAMPTZ NOT NULL,
    payload JSONB NOT NULL,
    PRIMARY KEY (mint, observed_at)
);

-- The primary key (mint, observed_at) already supports both forward and
-- backward B-tree scans for per-mint history. No duplicate DESC index.

CREATE TABLE IF NOT EXISTS lifecycle_rule_state (
    mint TEXT NOT NULL REFERENCES mints(mint) ON DELETE CASCADE,
    rule_key TEXT NOT NULL,
    scanned_through TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (mint, rule_key)
);
