from pathlib import Path

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
