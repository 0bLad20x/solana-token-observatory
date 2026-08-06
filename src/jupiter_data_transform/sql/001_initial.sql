CREATE TABLE IF NOT EXISTS jupiter_payloads (
    mint TEXT NOT NULL,
    raw_hash CHAR(64) NOT NULL,
    content_hash CHAR(64) NOT NULL,
    source_updated_at TIMESTAMPTZ,
    payload JSONB NOT NULL,
    PRIMARY KEY (mint, raw_hash)
);

CREATE INDEX IF NOT EXISTS ix_jupiter_payloads_mint_content
    ON jupiter_payloads (mint, content_hash);

CREATE INDEX IF NOT EXISTS ix_jupiter_payloads_mint_source_updated
    ON jupiter_payloads (mint, source_updated_at DESC);

CREATE TABLE IF NOT EXISTS jupiter_observations (
    id BIGSERIAL PRIMARY KEY,
    mint TEXT NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL,
    raw_hash CHAR(64) NOT NULL,
    FOREIGN KEY (mint, raw_hash)
        REFERENCES jupiter_payloads (mint, raw_hash)
);

CREATE INDEX IF NOT EXISTS ix_jupiter_observations_mint_observed
    ON jupiter_observations (mint, observed_at DESC);
