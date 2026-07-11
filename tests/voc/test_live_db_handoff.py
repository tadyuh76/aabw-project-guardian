from __future__ import annotations

import os
from pathlib import Path
import sys

import duckdb
import pytest

ROOT = Path(__file__).resolve().parents[2]
LIVE_UP = ROOT / "scripts" / "live-up"
sys.path.insert(0, str(ROOT))

import scripts.sync_live_db as sync_live_db  # noqa: E402
from scripts.sync_live_db import SyncRefused, main, synchronize_live_database  # noqa: E402


def _database(
    path: Path,
    feedback_ids: list[str],
    *,
    marker: str = "fixture",
    schema_versions: int = 1,
) -> Path:
    connection = duckdb.connect(str(path))
    connection.execute(
        """
        CREATE TABLE schema_version (
            version INTEGER PRIMARY KEY,
            name VARCHAR NOT NULL,
            checksum VARCHAR NOT NULL,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT current_timestamp
        )
        """
    )
    connection.execute(
        "INSERT INTO schema_version (version, name, checksum) VALUES (1, ?, ?)",
        ["001_fixture.sql", "a" * 64],
    )
    if schema_versions == 2:
        connection.execute(
            "INSERT INTO schema_version (version, name, checksum) VALUES (2, ?, ?)",
            ["002_fixture.sql", "b" * 64],
        )
    connection.execute(
        """
        CREATE TABLE feedback_items (
            feedback_id VARCHAR PRIMARY KEY,
            text_redacted VARCHAR NOT NULL,
            source_url VARCHAR NOT NULL
        )
        """
    )
    for feedback_id in feedback_ids:
        connection.execute(
            "INSERT INTO feedback_items VALUES (?, ?, ?)",
            [
                feedback_id,
                f"customer-{marker}",
                f"https://customer.invalid/{marker}",
            ],
        )
    connection.execute("CHECKPOINT")
    connection.close()
    assert not Path(f"{path}.wal").exists()
    return path


def _ids(path: Path) -> frozenset[str]:
    connection = duckdb.connect(str(path), read_only=True)
    try:
        return frozenset(
            row[0]
            for row in connection.execute(
                "SELECT feedback_id FROM feedback_items"
            ).fetchall()
        )
    finally:
        connection.close()


def _temporary_copies(directory: Path, destination_name: str) -> list[Path]:
    return list(directory.glob(f".{destination_name}.sync-*.tmp"))


def test_equal_six_record_destination_is_preserved_byte_for_byte(
    tmp_path: Path,
) -> None:
    feedback_ids = [f"feedback-{number}" for number in range(6)]
    source = _database(tmp_path / "source.duckdb", feedback_ids, marker="source")
    destination = _database(
        tmp_path / "destination.duckdb",
        feedback_ids,
        marker="destination-must-survive",
    )
    before = destination.read_bytes()
    before_stat = destination.stat()

    result = synchronize_live_database(source, destination)

    assert result.action == "preserved_equal"
    assert result.source_feedback_count == 6
    assert result.destination_feedback_count_before == 6
    assert destination.read_bytes() == before
    assert destination.stat().st_ino == before_stat.st_ino
    assert destination.stat().st_mtime_ns == before_stat.st_mtime_ns
    assert _temporary_copies(tmp_path, destination.name) == []


def test_missing_destination_is_seeded_atomically(tmp_path: Path) -> None:
    source = _database(tmp_path / "source.duckdb", ["one", "two"])
    destination = tmp_path / "destination.duckdb"

    result = synchronize_live_database(source, destination)

    assert result.action == "seeded_destination"
    assert result.destination_feedback_count_before == 0
    assert _ids(destination) == {"one", "two"}
    assert destination.stat().st_mode & 0o777 == 0o600
    assert _temporary_copies(tmp_path, destination.name) == []


def test_valid_empty_destination_is_seeded(tmp_path: Path) -> None:
    source = _database(tmp_path / "source.duckdb", ["one"])
    destination = _database(tmp_path / "destination.duckdb", [])

    result = synchronize_live_database(source, destination)

    assert result.action == "seeded_destination"
    assert result.destination_feedback_count_before == 0
    assert _ids(destination) == {"one"}


def test_strict_source_superset_replaces_destination(tmp_path: Path) -> None:
    source = _database(tmp_path / "source.duckdb", ["one", "two", "three"])
    destination = _database(tmp_path / "destination.duckdb", ["one", "two"])

    result = synchronize_live_database(source, destination)

    assert result.action == "replaced_strict_superset"
    assert result.source_feedback_count == 3
    assert result.destination_feedback_count_before == 2
    assert _ids(destination) == {"one", "two", "three"}


def test_newer_live_destination_superset_is_preserved(tmp_path: Path) -> None:
    source = _database(tmp_path / "source.duckdb", ["one", "two"])
    destination = _database(
        tmp_path / "destination.duckdb",
        ["one", "two", "live-scheduled-three"],
        marker="keep-near-real-time-live-data",
    )
    before = destination.read_bytes()

    result = synchronize_live_database(source, destination)

    assert result.action == "preserved_destination_superset"
    assert result.source_feedback_count == 2
    assert result.destination_feedback_count_before == 3
    assert destination.read_bytes() == before
    assert _ids(destination) == {"one", "two", "live-scheduled-three"}


@pytest.mark.parametrize(
    ("source_versions", "destination_versions"),
    [(1, 2), (2, 1)],
)
def test_schema_history_mismatch_refuses_superset_replacement(
    tmp_path: Path,
    source_versions: int,
    destination_versions: int,
) -> None:
    source = _database(
        tmp_path / "source.duckdb",
        ["one", "two"],
        schema_versions=source_versions,
    )
    destination = _database(
        tmp_path / "destination.duckdb",
        ["one"],
        marker="keep-newer-live-schema",
        schema_versions=destination_versions,
    )
    before = destination.read_bytes()

    with pytest.raises(SyncRefused, match="schema_history_mismatch"):
        synchronize_live_database(source, destination)

    assert destination.read_bytes() == before
    assert _temporary_copies(tmp_path, destination.name) == []


@pytest.mark.parametrize(
    ("source_ids", "destination_ids"),
    [
        (["one", "two"], ["one", "three"]),
    ],
)
def test_non_superset_source_is_refused_without_touching_destination(
    tmp_path: Path,
    source_ids: list[str],
    destination_ids: list[str],
) -> None:
    source = _database(tmp_path / "source.duckdb", source_ids)
    destination = _database(
        tmp_path / "destination.duckdb",
        destination_ids,
        marker="keep-me",
    )
    before = destination.read_bytes()

    with pytest.raises(SyncRefused, match="feedback_id_sets_diverge"):
        synchronize_live_database(source, destination)

    assert destination.read_bytes() == before
    assert _temporary_copies(tmp_path, destination.name) == []


@pytest.mark.parametrize("wal_role", ["source", "destination"])
def test_wal_is_refused_without_touching_destination(
    tmp_path: Path,
    wal_role: str,
) -> None:
    source = _database(tmp_path / "source.duckdb", ["one", "two"])
    destination = _database(tmp_path / "destination.duckdb", ["one"])
    before = destination.read_bytes()
    wal_owner = source if wal_role == "source" else destination
    Path(f"{wal_owner}.wal").write_bytes(b"unclean")

    with pytest.raises(SyncRefused, match=f"{wal_role}_wal_present"):
        synchronize_live_database(source, destination)

    assert destination.read_bytes() == before
    assert _temporary_copies(tmp_path, destination.name) == []


def test_failed_atomic_replace_cleans_temp_and_preserves_destination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _database(tmp_path / "source.duckdb", ["one", "two"])
    destination = _database(tmp_path / "destination.duckdb", ["one"])
    before = destination.read_bytes()

    def fail_replace(_source: Path, _destination: Path) -> None:
        raise OSError("simulated rename failure with customer data")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(SyncRefused, match="atomic_copy_failed"):
        synchronize_live_database(source, destination)

    assert destination.read_bytes() == before
    assert _temporary_copies(tmp_path, destination.name) == []


def test_unsupported_directory_fsync_does_not_misreport_committed_copy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _database(tmp_path / "source.duckdb", ["one", "two"])
    destination = _database(tmp_path / "destination.duckdb", ["one"])

    def unsupported_fsync(_directory: Path) -> None:
        raise OSError("directory fsync unsupported")

    monkeypatch.setattr(sync_live_db, "_fsync_directory", unsupported_fsync)
    result = synchronize_live_database(source, destination)

    assert result.action == "replaced_strict_superset"
    assert _ids(destination) == {"one", "two"}
    assert _temporary_copies(tmp_path, destination.name) == []


def test_invalid_source_is_refused_without_touching_destination(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.duckdb"
    source.write_bytes(b"not-a-duckdb")
    destination = _database(tmp_path / "destination.duckdb", ["one"])
    before = destination.read_bytes()

    with pytest.raises(SyncRefused, match="source_not_readable"):
        synchronize_live_database(source, destination)

    assert destination.read_bytes() == before
    assert _temporary_copies(tmp_path, destination.name) == []


def test_cli_output_never_contains_database_content_or_paths(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret_id = "secret-feedback-id"
    source = _database(
        tmp_path / "source-secret-token.duckdb",
        [secret_id, "source-only-id"],
        marker="secret-customer-text",
    )
    destination = _database(
        tmp_path / "destination-secret-token.duckdb",
        [secret_id, "destination-only-id"],
        marker="secret-live-text",
    )

    exit_code = main(
        ["--source", str(source), "--destination", str(destination)]
    )
    captured = capsys.readouterr()

    assert exit_code == 2
    assert '"reason":"feedback_id_sets_diverge"' in captured.err
    output = captured.out + captured.err
    for forbidden in (
        secret_id,
        "source-only-id",
        "destination-only-id",
        "secret-customer-text",
        "secret-live-text",
        "customer.invalid",
        "secret-token",
        str(tmp_path),
    ):
        assert forbidden not in output


def test_live_up_stops_and_verifies_service_before_handoff_then_starts() -> None:
    script = LIVE_UP.read_text(encoding="utf-8")
    build = script.index('"${COMPOSE[@]}" build guardian-voc')
    stop = script.index('"${COMPOSE[@]}" stop guardian-voc')
    stopped_check = script.index("docker ps -q")
    handoff = script.index("python /app/scripts/sync_live_db.py")
    start = script.index('"${COMPOSE[@]}" up --no-build -d')

    assert script.startswith("#!/usr/bin/env bash\nset -euo pipefail\n")
    assert build < stop < stopped_check < handoff < start
    assert '"${HOST_DATA_DIR}:/handoff/host:ro"' in script
    assert '"${COMPOSE[@]}" run --rm --no-deps' in script
    assert 'int(collector.get("verified_mapped_rows") or 0)' in script


def test_live_up_restarts_existing_service_before_returning_handoff_error() -> None:
    script = LIVE_UP.read_text(encoding="utf-8")
    handoff = script.index('if "${COMPOSE[@]}" run --rm --no-deps')
    failure_branch = script.index("handoff_status=$?", handoff)
    restart = script.index('"${COMPOSE[@]}" start guardian-voc', failure_branch)
    failure_exit = script.index('exit "${handoff_status}"', restart)
    successful_start = script.index('"${COMPOSE[@]}" up --no-build -d', failure_exit)

    assert handoff < failure_branch < restart < failure_exit < successful_start
    assert "existing live service restarted" in script
