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


def repair_discovery_cache(
    database_path: str | Path,
    *,
    create_backup: bool = True,
) -> Path | None:
    """Rebuild only the derived SERP discovery table and its indexes.

    The application must be stopped before this operation. Canonical feedback,
    classifications, fetch audits, and page extractions are intentionally left
    untouched. Discovery identities are deterministic and are repopulated by
    the next collection.
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
            connection.execute("DROP TABLE IF EXISTS discovery_results")
            connection.execute(DISCOVERY_TABLE_SQL)
            connection.execute(
                "CREATE INDEX discovery_source_idx "
                "ON discovery_results(source_id, discovered_at)"
            )
            connection.execute(
                "CREATE INDEX discovery_url_idx ON discovery_results(canonical_url)"
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
