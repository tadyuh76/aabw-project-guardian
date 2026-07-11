"""Narrow, auditable production maintenance operations."""

from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path

import duckdb


DISCOVERY_TABLE_SQL = """
CREATE TABLE discovery_results (
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
)
"""

FETCH_TABLE_SQL = """
CREATE TABLE fetch_attempts (
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
)
"""

EXTRACTION_TABLE_SQL = """
CREATE TABLE page_extractions (
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
)
"""


def repair_discovery_cache(
    database_path: str | Path,
    *,
    create_backup: bool = True,
) -> Path | None:
    """Rebuild only the derived acquisition audit tables and their indexes.

    The application must be stopped before this operation. Canonical feedback,
    classifications, checkpoints, and insights are intentionally left
    untouched. Discovery, fetch, and extraction identities are deterministic
    and are repopulated by the next collection. A full database backup makes
    the discarded acquisition audit rows recoverable.
    """

    path = Path(database_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"database does not exist: {path}")

    backup: Path | None = None
    if create_backup:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = path.with_name(f"{path.name}.pre-discovery-repair-{timestamp}.bak")
        shutil.copy2(path, backup)

    connection = duckdb.connect(str(path))
    try:
        connection.execute("SET TimeZone='UTC'")
        connection.execute("BEGIN TRANSACTION")
        try:
            connection.execute("DROP TABLE IF EXISTS page_extractions")
            connection.execute("DROP TABLE IF EXISTS fetch_attempts")
            connection.execute("DROP TABLE IF EXISTS discovery_results")
            connection.execute(DISCOVERY_TABLE_SQL)
            connection.execute(
                "CREATE INDEX discovery_source_idx "
                "ON discovery_results(source_id, discovered_at)"
            )
            connection.execute(
                "CREATE INDEX discovery_url_idx ON discovery_results(canonical_url)"
            )
            connection.execute(FETCH_TABLE_SQL)
            connection.execute(
                "CREATE INDEX fetch_source_idx ON fetch_attempts(source_id, fetched_at)"
            )
            connection.execute(
                "CREATE INDEX fetch_url_idx ON fetch_attempts(canonical_url)"
            )
            connection.execute(EXTRACTION_TABLE_SQL)
            connection.execute(
                "CREATE INDEX extraction_source_idx "
                "ON page_extractions(source_id, extracted_at)"
            )
            connection.execute(
                "CREATE INDEX extraction_fetch_idx ON page_extractions(fetch_id)"
            )
            connection.execute(
                """
                UPDATE pipeline_runs
                SET status = 'failed',
                    current_stage = 'failed',
                    completed_at = current_timestamp,
                    error_summary = 'Interrupted collection was recovered by operator.'
                WHERE status = 'running'
                """
            )
            connection.execute("COMMIT")
        except BaseException:
            connection.execute("ROLLBACK")
            raise
        connection.execute("CHECKPOINT")
    finally:
        connection.close()
    return backup
