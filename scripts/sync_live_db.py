#!/usr/bin/env python3
"""Fail-closed DuckDB handoff from the host build to the live named volume.

Only feedback identities are compared. Customer text, URLs, identifiers, and
credentials are never printed. The caller must stop the live service before
invoking this helper so DuckDB has exactly one writer.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import stat
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import duckdb


_CHECKSUM_RE = re.compile(r"[0-9a-f]{64}\Z")


class SyncRefused(RuntimeError):
    """A safe refusal whose code contains no database content or path."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class FileStamp:
    device: int
    inode: int
    size: int
    modified_ns: int


@dataclass(frozen=True)
class DatabaseSnapshot:
    feedback_ids: frozenset[str]
    schema_versions: tuple[tuple[int, str, str], ...]
    stamp: FileStamp


@dataclass(frozen=True)
class SyncResult:
    action: str
    source_feedback_count: int
    destination_feedback_count_before: int


def _wal_path(path: Path) -> Path:
    return path.with_name(f"{path.name}.wal")


def _path_entry_exists(path: Path) -> bool:
    """Return whether a directory entry exists, including a broken symlink."""

    try:
        path.lstat()
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise SyncRefused("path_not_readable") from exc
    return True


def _file_stamp(path: Path, *, role: str) -> FileStamp:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise SyncRefused(f"{role}_not_readable") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise SyncRefused(f"{role}_not_regular")
    return FileStamp(
        device=metadata.st_dev,
        inode=metadata.st_ino,
        size=metadata.st_size,
        modified_ns=metadata.st_mtime_ns,
    )


def _assert_no_wal(path: Path, *, role: str) -> None:
    if _path_entry_exists(_wal_path(path)):
        raise SyncRefused(f"{role}_wal_present")


def _inspect_database(path: Path, *, role: str) -> DatabaseSnapshot:
    stamp = _file_stamp(path, role=role)
    if stamp.size <= 0:
        raise SyncRefused(f"{role}_invalid_database")
    _assert_no_wal(path, role=role)
    try:
        connection = duckdb.connect(str(path), read_only=True)
    except Exception as exc:
        raise SyncRefused(f"{role}_not_readable") from exc
    try:
        tables = {
            str(row[0])
            for row in connection.execute(
                """
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = 'main'
                """
            ).fetchall()
        }
        if not {"schema_version", "feedback_items"}.issubset(tables):
            raise SyncRefused(f"{role}_schema_invalid")
        raw_versions = connection.execute(
            "SELECT version, name, checksum FROM schema_version ORDER BY version"
        ).fetchall()
        if not raw_versions:
            raise SyncRefused(f"{role}_schema_invalid")
        versions: list[tuple[int, str, str]] = []
        previous_version = 0
        for raw_version, raw_name, raw_checksum in raw_versions:
            name = str(raw_name)
            checksum = str(raw_checksum).lower()
            if (
                not isinstance(raw_version, int)
                or raw_version <= previous_version
                or not isinstance(raw_name, str)
                or not raw_name
                or not _CHECKSUM_RE.fullmatch(checksum)
            ):
                raise SyncRefused(f"{role}_schema_invalid")
            versions.append((raw_version, name, checksum))
            previous_version = raw_version
        raw_ids = connection.execute(
            "SELECT feedback_id FROM feedback_items ORDER BY feedback_id"
        ).fetchall()
    except SyncRefused:
        raise
    except Exception as exc:
        raise SyncRefused(f"{role}_schema_invalid") from exc
    finally:
        connection.close()

    feedback_ids: list[str] = []
    for row in raw_ids:
        value = row[0]
        if not isinstance(value, str) or not value:
            raise SyncRefused(f"{role}_feedback_ids_invalid")
        feedback_ids.append(value)
    if len(feedback_ids) != len(set(feedback_ids)):
        raise SyncRefused(f"{role}_feedback_ids_invalid")

    if _file_stamp(path, role=role) != stamp:
        raise SyncRefused(f"{role}_changed_during_inspection")
    _assert_no_wal(path, role=role)
    return DatabaseSnapshot(
        feedback_ids=frozenset(feedback_ids),
        schema_versions=tuple(versions),
        stamp=stamp,
    )


def _destination_state(path: Path) -> tuple[DatabaseSnapshot | None, FileStamp | None]:
    if not _path_entry_exists(path):
        return None, None
    stamp = _file_stamp(path, role="destination")
    _assert_no_wal(path, role="destination")
    if stamp.size == 0:
        return None, stamp
    return _inspect_database(path, role="destination"), stamp


def _destination_is_unchanged(path: Path, expected: FileStamp | None) -> bool:
    if expected is None:
        return not _path_entry_exists(path)
    try:
        return _file_stamp(path, role="destination") == expected
    except SyncRefused:
        return False


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic_replace(
    source: Path,
    destination: Path,
    *,
    source_snapshot: DatabaseSnapshot,
    destination_stamp: FileStamp | None,
) -> None:
    temporary = destination.parent / (
        f".{destination.name}.sync-{os.getpid()}-{uuid.uuid4().hex}.tmp"
    )
    try:
        with source.open("rb") as source_handle, temporary.open("xb") as target_handle:
            shutil.copyfileobj(source_handle, target_handle, length=1024 * 1024)
            target_handle.flush()
            os.fchmod(target_handle.fileno(), 0o600)
            os.fsync(target_handle.fileno())

        if _file_stamp(source, role="source") != source_snapshot.stamp:
            raise SyncRefused("source_changed_during_copy")
        _assert_no_wal(source, role="source")
        copied = _inspect_database(temporary, role="copy")
        if (
            copied.feedback_ids != source_snapshot.feedback_ids
            or copied.schema_versions != source_snapshot.schema_versions
        ):
            raise SyncRefused("copy_validation_failed")
        if not _destination_is_unchanged(destination, destination_stamp):
            raise SyncRefused("destination_changed_during_copy")
        _assert_no_wal(destination, role="destination")
        os.replace(temporary, destination)
        try:
            _fsync_directory(destination.parent)
        except OSError:
            # The rename is already an atomic commit. Some mounted filesystems
            # do not support directory fsync; do not misreport a committed copy
            # as a refusal or attempt a lossy rollback.
            pass
    except SyncRefused:
        raise
    except Exception as exc:
        raise SyncRefused("atomic_copy_failed") from exc
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def synchronize_live_database(source: Path, destination: Path) -> SyncResult:
    """Synchronize one clean source DB into a stopped live destination."""

    source = Path(source)
    destination = Path(destination)
    try:
        if source.resolve(strict=True) == destination.resolve(strict=False):
            raise SyncRefused("source_equals_destination")
    except FileNotFoundError as exc:
        raise SyncRefused("source_missing") from exc

    parent = destination.parent
    if not parent.exists() or not parent.is_dir() or parent.is_symlink():
        raise SyncRefused("destination_directory_invalid")

    source_snapshot = _inspect_database(source, role="source")
    destination_snapshot, destination_stamp = _destination_state(destination)
    source_ids = source_snapshot.feedback_ids
    destination_ids = (
        destination_snapshot.feedback_ids
        if destination_snapshot is not None
        else frozenset()
    )

    if destination_snapshot is not None and source_ids == destination_ids:
        if _file_stamp(source, role="source") != source_snapshot.stamp:
            raise SyncRefused("source_changed_during_inspection")
        if not _destination_is_unchanged(destination, destination_stamp):
            raise SyncRefused("destination_changed_during_inspection")
        return SyncResult(
            action="preserved_equal",
            source_feedback_count=len(source_ids),
            destination_feedback_count_before=len(destination_ids),
        )

    if destination_snapshot is not None and source_ids < destination_ids:
        # The live scheduler can legitimately advance beyond the host seed.
        # Never roll those near-real-time rows back during a later deploy.
        if _file_stamp(source, role="source") != source_snapshot.stamp:
            raise SyncRefused("source_changed_during_inspection")
        if not _destination_is_unchanged(destination, destination_stamp):
            raise SyncRefused("destination_changed_during_inspection")
        return SyncResult(
            action="preserved_destination_superset",
            source_feedback_count=len(source_ids),
            destination_feedback_count_before=len(destination_ids),
        )

    if destination_ids and not destination_ids < source_ids:
        raise SyncRefused("feedback_id_sets_diverge")

    if (
        destination_snapshot is not None
        and destination_snapshot.schema_versions != source_snapshot.schema_versions
    ):
        raise SyncRefused("schema_history_mismatch")

    action = "replaced_strict_superset" if destination_ids else "seeded_destination"
    _atomic_replace(
        source,
        destination,
        source_snapshot=source_snapshot,
        destination_stamp=destination_stamp,
    )
    return SyncResult(
        action=action,
        source_feedback_count=len(source_ids),
        destination_feedback_count_before=len(destination_ids),
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Synchronize a stopped live DuckDB")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = synchronize_live_database(args.source, args.destination)
    except SyncRefused as exc:
        print(
            json.dumps(
                {"status": "refused", "reason": exc.code},
                sort_keys=True,
                separators=(",", ":"),
            ),
            file=sys.stderr,
        )
        return 2
    except Exception:
        print(
            json.dumps(
                {"status": "failed", "reason": "internal_error"},
                sort_keys=True,
                separators=(",", ":"),
            ),
            file=sys.stderr,
        )
        return 3
    print(
        json.dumps(
            {
                "action": result.action,
                "destination_feedback_count_before": (
                    result.destination_feedback_count_before
                ),
                "source_feedback_count": result.source_feedback_count,
                "status": "ok",
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
