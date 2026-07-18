from pathlib import Path
from typing import Any

import psycopg
import pytest

from guardian_voc.config import Settings
from guardian_voc.db import Database, _postgres_migration_sql, _translate_qmark


def test_database_url_selects_postgres_but_explicit_path_selects_duckdb(tmp_path: Path) -> None:
    settings = Settings(database_url="postgresql://example.invalid/test")

    assert Database(settings=settings).is_postgres is True
    assert Database(tmp_path / "local.duckdb", settings=settings).is_postgres is False


def test_qmark_translation_preserves_literals_identifiers_and_comments() -> None:
    source = """SELECT ?, '?', "?" -- ?
    FROM sample /* ? */ WHERE value = ? AND note = $$?$$"""

    assert _translate_qmark(source) == """SELECT %s, '?', "?" -- ?
    FROM sample /* ? */ WHERE value = %s AND note = $$?$$"""


def test_postgres_migration_translation_maps_supported_duckdb_types() -> None:
    source = "values DOUBLE, labels VARCHAR[] NOT NULL DEFAULT []"

    assert (
        _postgres_migration_sql(source)
        == "values DOUBLE PRECISION, labels VARCHAR[] NOT NULL DEFAULT '{}'"
    )


class _Cursor:
    description = (("value",),)

    def fetchall(self) -> list[tuple[int]]:
        return [(1,)]


class _Connection:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.closed = False

    def execute(self, sql: str, parameters: list[object]) -> _Cursor:
        if self.error is not None:
            raise self.error
        return _Cursor()

    def close(self) -> None:
        self.closed = True


class _TransactionalConnection(_Connection):
    def execute(self, sql: str, parameters: list[object] | None = None) -> _Cursor:
        if sql == "BEGIN TRANSACTION":
            return _Cursor()
        return super().execute(sql, list(parameters or []))


def test_postgres_read_reconnects_once_after_closed_ssl_session(monkeypatch: Any) -> None:
    database = Database(settings=Settings(database_url="postgresql://example.invalid/test"))
    failed = _Connection(psycopg.OperationalError("SSL connection has been closed"))
    recovered = _Connection()
    connections = iter((failed, recovered))

    def open_connection() -> _Connection:
        connection = next(connections)
        database._connection = connection  # type: ignore[assignment]
        return connection

    monkeypatch.setattr(database, "_open", open_connection)

    assert database.query("SELECT 1 AS value") == [{"value": 1}]
    assert failed.closed is True


def test_postgres_read_does_not_retry_more_than_once(monkeypatch: Any) -> None:
    database = Database(settings=Settings(database_url="postgresql://example.invalid/test"))
    connections = iter(
        (
            _Connection(psycopg.OperationalError("first failure")),
            _Connection(psycopg.OperationalError("second failure")),
        )
    )

    def open_connection() -> _Connection:
        connection = next(connections)
        database._connection = connection  # type: ignore[assignment]
        return connection

    monkeypatch.setattr(database, "_open", open_connection)

    with pytest.raises(psycopg.OperationalError, match="second failure"):
        database.query("SELECT 1")


def test_postgres_read_does_not_reconnect_inside_transaction(monkeypatch: Any) -> None:
    database = Database(settings=Settings(database_url="postgresql://example.invalid/test"))
    failed = _TransactionalConnection(psycopg.OperationalError("transaction failure"))
    database._connection = failed  # type: ignore[assignment]

    with pytest.raises(psycopg.OperationalError, match="transaction failure"):
        with database.transaction():
            database.query("SELECT 1")

    assert failed.closed is False
