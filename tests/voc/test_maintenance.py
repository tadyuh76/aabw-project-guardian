from __future__ import annotations

from pathlib import Path

import duckdb

from guardian_voc.db import Database
from guardian_voc.maintenance import repair_discovery_cache


def test_discovery_repair_is_backed_up_and_preserves_canonical_tables(
    tmp_path: Path,
) -> None:
    path = tmp_path / "repair.duckdb"
    database = Database(path)
    database.initialize()
    database.execute(
        """
        INSERT INTO discovery_results VALUES (
            'discovery-one', 'guardian_public_social', 'query-one', 'guardian',
            'https://example.com/post', 'https://example.com/post', NULL, NULL,
            1, current_timestamp, 'test', true, NULL, '{}'
        )
        """
    )
    database.execute(
        """
        INSERT INTO source_checkpoints VALUES (
            'guardian_public_social', 'test', '{}', current_timestamp
        )
        """
    )
    database.close()

    backup = repair_discovery_cache(path)

    assert backup is not None and backup.is_file()
    connection = duckdb.connect(str(path))
    try:
        assert connection.execute(
            "SELECT count(*) FROM discovery_results"
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT count(*) FROM source_checkpoints"
        ).fetchone() == (1,)
        indexes = connection.execute(
            "SELECT index_name FROM duckdb_indexes() WHERE table_name = 'discovery_results'"
        ).fetchall()
        assert {row[0] for row in indexes} == {
            "discovery_source_idx",
            "discovery_url_idx",
        }
    finally:
        connection.close()
