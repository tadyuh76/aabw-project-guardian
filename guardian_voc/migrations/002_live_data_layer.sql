CREATE TABLE IF NOT EXISTS source_registry (
    source_id VARCHAR PRIMARY KEY,
    source_group VARCHAR NOT NULL,
    source_platform VARCHAR NOT NULL,
    owner_brand VARCHAR NOT NULL,
    market_scope VARCHAR NOT NULL,
    business_unit_scope VARCHAR NOT NULL,
    canonical_url VARCHAR,
    verified_account_ids VARCHAR[] NOT NULL DEFAULT [],
    acquisition_mode VARCHAR NOT NULL,
    tinyfish_policy VARCHAR NOT NULL,
    permission_status VARCHAR NOT NULL,
    metadata JSON NOT NULL DEFAULT '{}',
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS discovery_results (
    discovery_id VARCHAR PRIMARY KEY,
    source_id VARCHAR NOT NULL,
    query_id VARCHAR NOT NULL,
    query VARCHAR NOT NULL,
    canonical_url VARCHAR NOT NULL,
    raw_url VARCHAR NOT NULL,
    title_redacted VARCHAR,
    snippet_redacted VARCHAR,
    search_position INTEGER,
    discovered_at TIMESTAMPTZ NOT NULL,
    provider VARCHAR NOT NULL,
    eligible_for_fetch BOOLEAN NOT NULL,
    rejection_reason VARCHAR,
    metadata JSON NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS discovery_source_idx
    ON discovery_results(source_id, discovered_at);
CREATE INDEX IF NOT EXISTS discovery_url_idx
    ON discovery_results(canonical_url);

CREATE TABLE IF NOT EXISTS fetch_attempts (
    fetch_id VARCHAR PRIMARY KEY,
    discovery_id VARCHAR,
    source_id VARCHAR NOT NULL,
    canonical_url VARCHAR NOT NULL,
    final_url VARCHAR,
    reader VARCHAR NOT NULL,
    status VARCHAR NOT NULL,
    error_code VARCHAR,
    content_hash VARCHAR,
    content_chars BIGINT NOT NULL DEFAULT 0,
    customer_voice_units BIGINT NOT NULL DEFAULT 0,
    fetched_at TIMESTAMPTZ NOT NULL,
    metadata JSON NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS fetch_source_idx
    ON fetch_attempts(source_id, fetched_at);
CREATE INDEX IF NOT EXISTS fetch_url_idx
    ON fetch_attempts(canonical_url);

CREATE TABLE IF NOT EXISTS page_extractions (
    extraction_id VARCHAR PRIMARY KEY,
    fetch_id VARCHAR NOT NULL,
    discovery_id VARCHAR NOT NULL,
    source_id VARCHAR NOT NULL,
    canonical_url VARCHAR NOT NULL,
    page_state VARCHAR NOT NULL,
    status VARCHAR NOT NULL,
    error_code VARCHAR,
    unit_count BIGINT NOT NULL DEFAULT 0,
    model_version VARCHAR NOT NULL,
    prompt_version VARCHAR NOT NULL,
    extracted_at TIMESTAMPTZ NOT NULL,
    metadata JSON NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS extraction_source_idx
    ON page_extractions(source_id, extracted_at);
CREATE INDEX IF NOT EXISTS extraction_fetch_idx
    ON page_extractions(fetch_id);

CREATE TABLE IF NOT EXISTS source_checkpoints (
    source_id VARCHAR NOT NULL,
    checkpoint_key VARCHAR NOT NULL,
    checkpoint_value JSON NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (source_id, checkpoint_key)
);

CREATE TABLE IF NOT EXISTS classification_failures (
    failure_id VARCHAR PRIMARY KEY,
    feedback_id VARCHAR NOT NULL,
    model_version VARCHAR NOT NULL,
    prompt_version VARCHAR NOT NULL,
    failure_type VARCHAR NOT NULL,
    error_code VARCHAR NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL,
    metadata JSON NOT NULL DEFAULT '{}'
);
