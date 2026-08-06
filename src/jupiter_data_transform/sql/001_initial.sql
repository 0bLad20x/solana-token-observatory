CREATE TABLE IF NOT EXISTS jupiter_observations (
    mint TEXT NOT NULL,
    payload_hash CHAR(64) NOT NULL,
    first_seen_at TIMESTAMPTZ NOT NULL,
    last_seen_at TIMESTAMPTZ NOT NULL,
    source_updated_at TIMESTAMPTZ,
    seen_count BIGINT NOT NULL DEFAULT 1 CHECK (seen_count >= 1),
    payload JSONB NOT NULL,
    PRIMARY KEY (mint, payload_hash),
    CHECK (last_seen_at >= first_seen_at)
);

CREATE INDEX IF NOT EXISTS ix_jupiter_observations_mint_last_seen
    ON jupiter_observations (mint, last_seen_at DESC);
