#!/usr/bin/env python3
"""Copy and verify every application row from DuckDB to PostgreSQL."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from guardian_voc.config import Settings
from guardian_voc.db import Database


_IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]*$")


def _identifier(value: str) -> str:
    if not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"unsafe SQL identifier: {value!r}")
    return f'"{value}"'


def _canonical(value: object, *, json_value: bool = False) -> object:
    if json_value and isinstance(value, str):
        value = json.loads(value)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {
            str(key): _canonical(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    if isinstance(value, memoryview):
        return value.tobytes().hex()
    if isinstance(value, bytes):
        return value.hex()
    return value


def _table_digest(
    rows: Iterable[Mapping[str, Any]],
    columns: Sequence[str],
    json_columns: set[str],
) -> str:
    canonical_rows = []
    for row in rows:
        values = [
            _canonical(row.get(column), json_value=column in json_columns)
            for column in columns
        ]
        canonical_rows.append(
            json.dumps(values, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        )
    digest = hashlib.sha256()
    for encoded in sorted(canonical_rows):
        digest.update(encoded.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def _source_tables(source: Database) -> list[str]:
    tables = sorted(str(row["name"]) for row in source.query("SHOW TABLES"))
    for table in tables:
        _identifier(table)
    return tables


def _source_columns(source: Database, table: str) -> tuple[list[str], set[str]]:
    rows = source.query(f"PRAGMA table_info({_identifier(table)})")
    columns = [str(row["name"]) for row in rows]
    json_columns = {
        str(row["name"])
        for row in rows
        if str(row["type"]).upper() == "JSON"
    }
    return columns, json_columns


def migrate(source_path: Path, target_url: str, *, replace: bool) -> dict[str, int]:
    source = Database(source_path, read_only=True)
    target = Database(settings=Settings(database_url=target_url))
    try:
        target.initialize()
        tables = _source_tables(source)
        app_tables = [table for table in tables if table != "schema_version"]

        target_rows = sum(
            int(
                (
                    target.query_one(
                        f"SELECT count(*) AS count FROM {_identifier(table)}"
                    )
                    or {"count": 0}
                )["count"]
            )
            for table in app_tables
        )
        if target_rows and not replace:
            raise RuntimeError(
                "target PostgreSQL already contains application rows; rerun with --replace"
            )

        source_payload: dict[str, tuple[list[str], set[str], list[dict[str, Any]]]] = {}
        for table in app_tables:
            columns, json_columns = _source_columns(source, table)
            rows = source.query(f"SELECT * FROM {_identifier(table)}")
            source_payload[table] = (columns, json_columns, rows)

        with target.transaction():
            if replace:
                for table in app_tables:
                    target.execute(f"DELETE FROM {_identifier(table)}")
            for table in app_tables:
                columns, _, rows = source_payload[table]
                if not rows:
                    continue
                column_sql = ", ".join(_identifier(column) for column in columns)
                placeholders = ", ".join("?" for _ in columns)
                target.executemany(
                    f"INSERT INTO {_identifier(table)} ({column_sql}) "
                    f"VALUES ({placeholders})",
                    ([row[column] for column in columns] for row in rows),
                )

        source_versions = source.query(
            "SELECT version, name, checksum FROM schema_version ORDER BY version"
        )
        target_versions = target.query(
            "SELECT version, name, checksum FROM schema_version ORDER BY version"
        )
        if source_versions != target_versions:
            raise RuntimeError("schema migration versions or checksums do not match")

        counts: dict[str, int] = {}
        for table in app_tables:
            columns, json_columns, source_rows = source_payload[table]
            target_rows_for_table = target.query(f"SELECT * FROM {_identifier(table)}")
            if len(source_rows) != len(target_rows_for_table):
                raise RuntimeError(f"row count mismatch for {table}")
            if _table_digest(source_rows, columns, json_columns) != _table_digest(
                target_rows_for_table, columns, json_columns
            ):
                raise RuntimeError(f"content checksum mismatch for {table}")
            counts[table] = len(source_rows)
        return counts
    finally:
        source.close()
        target.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        default=Path("data/guardian_voc.duckdb"),
        help="source DuckDB file",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="delete existing target application rows before copying",
    )
    args = parser.parse_args()
    target_url = (
        os.environ.get("DATABASE_URL_UNPOOLED", "").strip()
        or os.environ.get("DATABASE_URL", "").strip()
    )
    if not target_url:
        parser.error("DATABASE_URL_UNPOOLED or DATABASE_URL is required")
    if not args.source.is_file():
        parser.error(f"source database does not exist: {args.source}")

    counts = migrate(args.source, target_url, replace=args.replace)
    print(f"Migrated and verified {sum(counts.values())} rows across {len(counts)} tables.")
    for table, count in counts.items():
        print(f"  {table}: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
