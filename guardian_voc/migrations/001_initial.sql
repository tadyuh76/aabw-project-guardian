CREATE TABLE IF NOT EXISTS ingestion_runs (
    id VARCHAR PRIMARY KEY,
    connector VARCHAR NOT NULL,
    source_name VARCHAR NOT NULL,
    source_file VARCHAR,
    status VARCHAR NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    records_seen BIGINT NOT NULL DEFAULT 0,
    records_inserted BIGINT NOT NULL DEFAULT 0,
    records_updated BIGINT NOT NULL DEFAULT 0,
    records_skipped BIGINT NOT NULL DEFAULT 0,
    records_failed BIGINT NOT NULL DEFAULT 0,
    error_summary VARCHAR,
    metadata JSON NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS source_status (
    source_name VARCHAR PRIMARY KEY,
    source_group VARCHAR NOT NULL,
    last_success_at TIMESTAMPTZ,
    last_attempt_at TIMESTAMPTZ,
    last_record_at TIMESTAMPTZ,
    status VARCHAR NOT NULL,
    recent_volume BIGINT NOT NULL DEFAULT 0,
    expected_volume_range JSON NOT NULL DEFAULT '{}',
    failure_rate DOUBLE NOT NULL DEFAULT 0,
    notes VARCHAR
);

CREATE TABLE IF NOT EXISTS feedback_items (
    feedback_id VARCHAR PRIMARY KEY,
    ingestion_run_id VARCHAR NOT NULL,
    source_external_id VARCHAR,
    source_group VARCHAR NOT NULL,
    source_platform VARCHAR NOT NULL,
    visibility VARCHAR NOT NULL,
    brand VARCHAR,
    brand_candidates VARCHAR[] NOT NULL DEFAULT [],
    brand_attribution VARCHAR NOT NULL,
    experience_subject VARCHAR NOT NULL,
    occurred_at TIMESTAMPTZ,
    observed_at TIMESTAMPTZ NOT NULL,
    occurred_at_quality VARCHAR NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL,
    original_timezone VARCHAR,
    language VARCHAR NOT NULL,
    language_confidence DOUBLE,
    title VARCHAR,
    text_redacted VARCHAR NOT NULL,
    rating DOUBLE,
    product_name VARCHAR,
    product_category VARCHAR,
    region VARCHAR,
    store VARCHAR,
    source_url VARCHAR,
    canonical_url VARCHAR,
    author_hash VARCHAR,
    conversation_hash VARCHAR,
    message_count INTEGER,
    media_urls VARCHAR[] NOT NULL DEFAULT [],
    content_hash VARCHAR NOT NULL,
    content_fingerprint VARCHAR,
    repost_group_id VARCHAR,
    crawler_record_id VARCHAR,
    sanitized_metadata JSON NOT NULL DEFAULT '{}',
    is_synthetic BOOLEAN NOT NULL DEFAULT FALSE,
    quality_status VARCHAR NOT NULL,
    duplicate_of VARCHAR,
    analysis_status VARCHAR NOT NULL
);

-- DuckDB does not support partial indexes.  The repository enforces canonical
-- URL uniqueness for social/web records while this index keeps lookups cheap;
-- marketplace product URLs are intentionally allowed to repeat.
CREATE INDEX IF NOT EXISTS feedback_canonical_url_idx
    ON feedback_items(canonical_url);
CREATE INDEX IF NOT EXISTS feedback_source_external_idx
    ON feedback_items(source_platform, source_external_id);
CREATE INDEX IF NOT EXISTS feedback_occurred_idx
    ON feedback_items(occurred_at);
CREATE INDEX IF NOT EXISTS feedback_content_hash_idx
    ON feedback_items(content_hash);
CREATE INDEX IF NOT EXISTS feedback_repost_group_idx
    ON feedback_items(repost_group_id);

CREATE TABLE IF NOT EXISTS feedback_analyses (
    feedback_id VARCHAR PRIMARY KEY,
    is_relevant BOOLEAN NOT NULL,
    primary_brand VARCHAR,
    mentioned_brands VARCHAR[] NOT NULL DEFAULT [],
    brand_attribution_confidence DOUBLE,
    brand_evidence_span VARCHAR,
    experience_subject VARCHAR NOT NULL,
    primary_topic VARCHAR NOT NULL,
    subtopic VARCHAR,
    intent VARCHAR NOT NULL,
    sentiment VARCHAR NOT NULL,
    sentiment_score DOUBLE NOT NULL,
    urgency VARCHAR NOT NULL,
    customer_stated_reason VARCHAR,
    journey_stage VARCHAR,
    evidence_span VARCHAR,
    confidence DOUBLE NOT NULL,
    model_version VARCHAR NOT NULL,
    prompt_version VARCHAR NOT NULL,
    taxonomy_version VARCHAR NOT NULL,
    raw_result JSON NOT NULL,
    analyzed_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS business_events (
    event_id VARCHAR PRIMARY KEY,
    event_type VARCHAR NOT NULL,
    title VARCHAR NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL,
    ended_at TIMESTAMPTZ,
    affected_channel VARCHAR,
    affected_category VARCHAR,
    notes VARCHAR
);

CREATE TABLE IF NOT EXISTS pipeline_runs (
    id VARCHAR PRIMARY KEY,
    trigger VARCHAR NOT NULL,
    ingestion_run_id VARCHAR,
    status VARCHAR NOT NULL,
    current_stage VARCHAR,
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    stage_results JSON NOT NULL DEFAULT '{}',
    error_summary VARCHAR,
    metadata JSON NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS human_corrections (
    correction_id VARCHAR PRIMARY KEY,
    feedback_id VARCHAR NOT NULL,
    field VARCHAR NOT NULL,
    old_value JSON,
    new_value JSON NOT NULL,
    corrected_at TIMESTAMPTZ NOT NULL,
    corrected_by VARCHAR NOT NULL,
    note VARCHAR,
    model_version VARCHAR,
    prompt_version VARCHAR,
    taxonomy_version VARCHAR
);

CREATE TABLE IF NOT EXISTS daily_metrics (
    metric_id VARCHAR PRIMARY KEY,
    date DATE NOT NULL,
    resolved_brand VARCHAR,
    visibility VARCHAR NOT NULL,
    source_group VARCHAR NOT NULL,
    source_platform VARCHAR NOT NULL,
    experience_subject VARCHAR NOT NULL,
    primary_topic VARCHAR,
    subtopic VARCHAR,
    product_category VARCHAR,
    journey_stage VARCHAR,
    raw_record_count BIGINT NOT NULL,
    independent_signal_count BIGINT NOT NULL,
    unique_author_or_conversation_count BIGINT NOT NULL,
    negative_count BIGINT NOT NULL,
    negative_share DOUBLE,
    positive_count BIGINT NOT NULL,
    positive_share DOUBLE,
    average_sentiment DOUBLE,
    average_rating DOUBLE,
    analyzed_count BIGINT NOT NULL,
    low_confidence_count BIGINT NOT NULL,
    built_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS daily_metrics_date_idx ON daily_metrics(date);

CREATE TABLE IF NOT EXISTS insight_series (
    insight_series_id VARCHAR PRIMARY KEY,
    brand VARCHAR NOT NULL,
    cohort_scope VARCHAR NOT NULL,
    topic VARCHAR NOT NULL,
    subtopic VARCHAR,
    product_category VARCHAR,
    created_at TIMESTAMPTZ NOT NULL,
    latest_observation_id VARCHAR
);

CREATE TABLE IF NOT EXISTS insight_observations (
    observation_id VARCHAR PRIMARY KEY,
    insight_series_id VARCHAR NOT NULL,
    pipeline_run_id VARCHAR NOT NULL,
    window_start DATE NOT NULL,
    window_end DATE NOT NULL,
    numerator BIGINT NOT NULL,
    denominator BIGINT NOT NULL,
    current_share DOUBLE,
    baseline_share DOUBLE,
    fact_packet JSON NOT NULL,
    source_health_snapshot JSON NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS insight_status_history (
    status_event_id VARCHAR PRIMARY KEY,
    insight_series_id VARCHAR NOT NULL,
    status VARCHAR NOT NULL,
    changed_at TIMESTAMPTZ NOT NULL,
    changed_by VARCHAR NOT NULL,
    note VARCHAR,
    reference_observation_id VARCHAR
);

CREATE TABLE IF NOT EXISTS insight_cards (
    insight_id VARCHAR PRIMARY KEY,
    insight_series_id VARCHAR NOT NULL,
    observation_id VARCHAR NOT NULL,
    insight_type VARCHAR NOT NULL,
    topic VARCHAR NOT NULL,
    subtopic VARCHAR,
    window_start DATE NOT NULL,
    window_end DATE NOT NULL,
    title VARCHAR NOT NULL,
    what_changed VARCHAR NOT NULL,
    reach_summary VARCHAR NOT NULL,
    likely_driver VARCHAR,
    market_context VARCHAR,
    primary_owner VARCHAR NOT NULL,
    supporting_owner VARCHAR,
    recommended_actions VARCHAR[] NOT NULL DEFAULT [],
    confidence VARCHAR NOT NULL,
    fact_packet JSON NOT NULL,
    status VARCHAR NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS insight_evidence (
    insight_id VARCHAR NOT NULL,
    feedback_id VARCHAR NOT NULL,
    evidence_role VARCHAR NOT NULL,
    rank INTEGER NOT NULL,
    PRIMARY KEY (insight_id, feedback_id, evidence_role)
);

CREATE TABLE IF NOT EXISTS import_quarantine (
    quarantine_id VARCHAR PRIMARY KEY,
    ingestion_run_id VARCHAR NOT NULL,
    source_name VARCHAR NOT NULL,
    source_file VARCHAR,
    row_number BIGINT NOT NULL,
    reason_code VARCHAR NOT NULL,
    reason_message VARCHAR NOT NULL,
    field VARCHAR,
    masked_sample JSON NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS quarantine_run_idx
    ON import_quarantine(ingestion_run_id);

CREATE TABLE IF NOT EXISTS imported_files (
    source_name VARCHAR NOT NULL,
    file_sha256 VARCHAR NOT NULL,
    filename VARCHAR NOT NULL,
    first_ingestion_run_id VARCHAR NOT NULL,
    first_imported_at TIMESTAMPTZ NOT NULL,
    last_ingestion_run_id VARCHAR NOT NULL,
    last_seen_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (source_name, file_sha256)
);

CREATE TABLE IF NOT EXISTS page_reader_cache (
    canonical_url VARCHAR PRIMARY KEY,
    title VARCHAR,
    text_redacted VARCHAR,
    reader VARCHAR NOT NULL,
    metadata JSON NOT NULL DEFAULT '{}',
    fetched_at TIMESTAMPTZ NOT NULL
);
