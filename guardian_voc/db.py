"""Database migrations and the canonical ingestion repository.

Local development keeps the zero-service DuckDB default. Cloud deployments can
provide ``DATABASE_URL`` to use durable PostgreSQL through the same serialized
repository interface.
"""

from __future__ import annotations

import hashlib
import json
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

import duckdb
import psycopg
from pydantic import BaseModel

from guardian_voc.config import Settings, get_settings
from guardian_voc.pipeline.normalize import normalize_raw_feedback, utc_now
from guardian_voc.schemas.feedback import (
    FeedbackItem,
    IngestionRun,
    IngestionRunStatus,
    SourceGroup,
    SourceHealthStatus,
    SourceStatus,
)


MIGRATIONS_DIR = Path(__file__).with_name("migrations")


@dataclass(frozen=True)
class WriteCounts:
    seen: int = 0
    inserted: int = 0
    updated: int = 0
    skipped: int = 0
    failed: int = 0


def _json_default(value: object) -> object:
    if isinstance(value, (datetime,)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    raise TypeError(f"cannot serialize {type(value).__name__}")


def _json_dump(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, default=_json_default, sort_keys=True)


def _json_load(value: object, default: object) -> object:
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return default


def _rows(cursor: Any) -> list[dict[str, Any]]:
    columns = [item[0] for item in (cursor.description or [])]
    return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def _translate_qmark(sql: str) -> str:
    """Translate qmark parameters without touching quoted text or comments."""

    output: list[str] = []
    index = 0
    state = "sql"
    dollar_tag = ""
    while index < len(sql):
        char = sql[index]
        following = sql[index + 1] if index + 1 < len(sql) else ""
        if state == "sql":
            if char == "'":
                state = "single"
            elif char == '"':
                state = "double"
            elif char == "-" and following == "-":
                output.extend((char, following))
                index += 2
                state = "line_comment"
                continue
            elif char == "/" and following == "*":
                output.extend((char, following))
                index += 2
                state = "block_comment"
                continue
            elif char == "$":
                end = sql.find("$", index + 1)
                if end != -1:
                    candidate = sql[index : end + 1]
                    if candidate == "$$" or candidate[1:-1].replace("_", "a").isalnum():
                        dollar_tag = candidate
                        state = "dollar"
                        output.append(candidate)
                        index = end + 1
                        continue
            elif char == "?":
                output.append("%s")
                index += 1
                continue
        elif state == "single":
            if char == "'":
                if following == "'":
                    output.extend((char, following))
                    index += 2
                    continue
                state = "sql"
        elif state == "double":
            if char == '"':
                if following == '"':
                    output.extend((char, following))
                    index += 2
                    continue
                state = "sql"
        elif state == "line_comment":
            if char in "\r\n":
                state = "sql"
        elif state == "block_comment":
            if char == "*" and following == "/":
                output.extend((char, following))
                index += 2
                state = "sql"
                continue
        elif state == "dollar" and sql.startswith(dollar_tag, index):
            output.append(dollar_tag)
            index += len(dollar_tag)
            state = "sql"
            continue
        output.append(char)
        index += 1
    return "".join(output)


def _postgres_migration_sql(sql: str) -> str:
    """Map the small DuckDB type/default surface used by our migrations."""

    import re

    sql = re.sub(r"\bDOUBLE\b", "DOUBLE PRECISION", sql, flags=re.IGNORECASE)
    return re.sub(r"\bDEFAULT\s+\[\]", "DEFAULT '{}'", sql, flags=re.IGNORECASE)


def _postgres_parameters(parameters: Sequence[object] | None) -> tuple[object, ...]:
    # Psycopg adapts lists to PostgreSQL arrays; tuples represent composite
    # values, while the application uses tuples only for array-valued fields.
    return tuple(
        list(value) if isinstance(value, tuple) else value
        for value in (parameters or ())
    )


class _PostgresConnection:
    """Minimal connection facade matching the DuckDB methods used below."""

    def __init__(self, connection: psycopg.Connection[Any]) -> None:
        self.raw = connection

    @property
    def closed(self) -> bool:
        return self.raw.closed

    def execute(
        self, sql: str, parameters: Sequence[object] | None = None
    ) -> psycopg.Cursor[Any]:
        return self.raw.execute(_translate_qmark(sql), _postgres_parameters(parameters))

    def executemany(
        self, sql: str, parameters: Iterable[Sequence[object]]
    ) -> psycopg.Cursor[Any]:
        cursor = self.raw.cursor()
        cursor.executemany(
            _translate_qmark(sql),
            (_postgres_parameters(row) for row in parameters),
        )
        return cursor

    def close(self) -> None:
        self.raw.close()


DatabaseConnection = duckdb.DuckDBPyConnection | _PostgresConnection


class Database:
    """A serialized DuckDB or PostgreSQL handle with ordered migrations."""

    def __init__(
        self,
        path: str | Path | Settings | None = None,
        *,
        settings: Settings | None = None,
        read_only: bool = False,
    ) -> None:
        if isinstance(path, Settings):
            settings = path
            path = None
        self.settings = settings or get_settings()
        self.database_url = "" if path is not None else self.settings.database_url
        self.is_postgres = bool(self.database_url)
        self.path = str(path or self.settings.voc_db_path)
        self.read_only = read_only
        self._connection: DatabaseConnection | None = None
        self._lock = threading.RLock()

    def _open(self) -> DatabaseConnection:
        if self._connection is None or (
            isinstance(self._connection, _PostgresConnection) and self._connection.closed
        ):
            if self.is_postgres:
                raw = psycopg.connect(self.database_url, autocommit=True)
                self._connection = _PostgresConnection(raw)
                self._connection.execute("SET TIME ZONE 'UTC'")
                if self.read_only:
                    self._connection.execute(
                        "SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY"
                    )
                return self._connection
            if self.path != ":memory:" and not self.read_only:
                Path(self.path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
            self._connection = duckdb.connect(self.path, read_only=self.read_only)
            self._connection.execute("SET TimeZone='UTC'")
        return self._connection

    @property
    def conn(self) -> DatabaseConnection:
        return self._open()

    @contextmanager
    def connection(self) -> Iterator[DatabaseConnection]:
        with self._lock:
            yield self._open()

    @contextmanager
    def transaction(self) -> Iterator[DatabaseConnection]:
        with self.connection() as connection:
            connection.execute("BEGIN TRANSACTION")
            try:
                yield connection
            except BaseException:
                connection.execute("ROLLBACK")
                raise
            else:
                connection.execute("COMMIT")

    def initialize(self) -> list[int]:
        return self.migrate()

    def migrate(self, migrations_dir: str | Path | None = None) -> list[int]:
        if self.read_only:
            raise RuntimeError("cannot migrate a read-only database")
        directory = Path(migrations_dir or MIGRATIONS_DIR)
        files = sorted(directory.glob("[0-9][0-9][0-9]_*.sql"))
        applied: list[int] = []
        with self.connection() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_version (
                    version INTEGER PRIMARY KEY,
                    name VARCHAR NOT NULL,
                    checksum VARCHAR NOT NULL,
                    applied_at TIMESTAMPTZ NOT NULL
                )
                """
            )
        for migration in files:
            version = int(migration.name.split("_", 1)[0])
            sql = migration.read_text(encoding="utf-8")
            checksum = hashlib.sha256(sql.encode("utf-8")).hexdigest()
            existing = self.query_one(
                "SELECT checksum FROM schema_version WHERE version = ?", [version]
            )
            if existing is not None:
                if existing["checksum"] != checksum:
                    raise RuntimeError(
                        f"migration {version} checksum differs from the applied migration"
                    )
                continue
            with self.transaction() as connection:
                connection.execute(
                    _postgres_migration_sql(sql) if self.is_postgres else sql
                )
                connection.execute(
                    "INSERT INTO schema_version VALUES (?, ?, ?, ?)",
                    [version, migration.name, checksum, utc_now()],
                )
            applied.append(version)
        return applied

    def execute(
        self, sql: str, parameters: Sequence[object] | None = None
    ) -> Any:
        with self.connection() as connection:
            return connection.execute(sql, list(parameters or []))

    def executemany(
        self, sql: str, parameters: Iterable[Sequence[object]]
    ) -> Any:
        with self.connection() as connection:
            return connection.executemany(sql, parameters)

    def query(
        self, sql: str, parameters: Sequence[object] | None = None
    ) -> list[dict[str, Any]]:
        with self.connection() as connection:
            cursor = connection.execute(sql, list(parameters or []))
            return _rows(cursor)

    read = query

    def query_one(
        self, sql: str, parameters: Sequence[object] | None = None
    ) -> dict[str, Any] | None:
        rows = self.query(sql, parameters)
        return rows[0] if rows else None

    def schema_version(self) -> int:
        try:
            row = self.query_one("SELECT max(version) AS version FROM schema_version")
        except (duckdb.CatalogException, psycopg.errors.UndefinedTable):
            return 0
        return int(row["version"] or 0) if row else 0

    def close(self) -> None:
        with self._lock:
            if self._connection is not None:
                self._connection.close()
                self._connection = None

    def __enter__(self) -> "Database":
        self._open()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


def _run_from_row(row: Mapping[str, Any]) -> IngestionRun:
    values = dict(row)
    values["metadata"] = _json_load(values.get("metadata"), {})
    return IngestionRun.model_validate(values)


def _source_status_from_row(row: Mapping[str, Any]) -> SourceStatus:
    values = dict(row)
    values["expected_volume_range"] = _json_load(
        values.get("expected_volume_range"), {}
    )
    return SourceStatus.model_validate(values)


class GuardianVocRepository:
    """Repository for ingestion, feedback identity, quarantine, and source health."""

    def __init__(
        self,
        database: Database | str | Path | None = None,
        *,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or (
            database.settings if isinstance(database, Database) else get_settings()
        )
        self.db = (
            database
            if isinstance(database, Database)
            else Database(database, settings=self.settings)
        )

    def initialize(self) -> list[int]:
        return self.db.initialize()

    def create_ingestion_run(
        self,
        *,
        connector: str,
        source_name: str,
        source_file: str | Path | None = None,
        metadata: Mapping[str, Any] | None = None,
        run_id: str | None = None,
        started_at: datetime | None = None,
        status: IngestionRunStatus = IngestionRunStatus.RUNNING,
    ) -> IngestionRun:
        started_at = started_at or utc_now()
        status = IngestionRunStatus(status)
        run = IngestionRun(
            id=run_id or f"ingest_{uuid.uuid4().hex}",
            connector=connector,
            source_name=source_name,
            source_file=str(source_file) if source_file is not None else None,
            status=status,
            started_at=started_at,
            metadata=dict(metadata or {}),
        )
        self.db.execute(
            """
            INSERT INTO ingestion_runs (
                id, connector, source_name, source_file, status, started_at,
                completed_at, records_seen, records_inserted, records_updated,
                records_skipped, records_failed, error_summary, metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                run.id,
                run.connector,
                run.source_name,
                run.source_file,
                run.status.value,
                run.started_at,
                run.completed_at,
                0,
                0,
                0,
                0,
                0,
                None,
                _json_dump(run.metadata),
            ],
        )
        return run

    def get_ingestion_run(self, run_id: str) -> IngestionRun | None:
        row = self.db.query_one("SELECT * FROM ingestion_runs WHERE id = ?", [run_id])
        return None if row is None else _run_from_row(row)

    def list_ingestion_runs(
        self, *, source_name: str | None = None, limit: int = 100
    ) -> list[IngestionRun]:
        if source_name:
            rows = self.db.query(
                """
                SELECT * FROM ingestion_runs WHERE source_name = ?
                ORDER BY started_at DESC LIMIT ?
                """,
                [source_name, limit],
            )
        else:
            rows = self.db.query(
                "SELECT * FROM ingestion_runs ORDER BY started_at DESC LIMIT ?", [limit]
            )
        return [_run_from_row(row) for row in rows]

    def finish_ingestion_run(
        self,
        run_id: str,
        *,
        status: IngestionRunStatus,
        counts: WriteCounts | None = None,
        records_seen: int | None = None,
        records_inserted: int | None = None,
        records_updated: int | None = None,
        records_skipped: int | None = None,
        records_failed: int | None = None,
        error_summary: str | None = None,
        completed_at: datetime | None = None,
        source_group: SourceGroup | str | None = None,
        last_record_at: datetime | None = None,
        notes: str | None = None,
    ) -> IngestionRun:
        status = IngestionRunStatus(status)
        existing = self.get_ingestion_run(run_id)
        if existing is None:
            raise KeyError(f"unknown ingestion run: {run_id}")
        counts = counts or WriteCounts(
            seen=records_seen or 0,
            inserted=records_inserted or 0,
            updated=records_updated or 0,
            skipped=records_skipped or 0,
            failed=records_failed or 0,
        )
        completed_at = completed_at or utc_now()
        self.db.execute(
            """
            UPDATE ingestion_runs SET
                status = ?, completed_at = ?, records_seen = ?,
                records_inserted = ?, records_updated = ?, records_skipped = ?,
                records_failed = ?, error_summary = ?
            WHERE id = ?
            """,
            [
                status.value,
                completed_at,
                counts.seen,
                counts.inserted,
                counts.updated,
                counts.skipped,
                counts.failed,
                error_summary,
                run_id,
            ],
        )

        if source_group is None or last_record_at is None:
            group_row = self.db.query_one(
                """
                SELECT source_group, max(coalesce(occurred_at, observed_at)) AS last_record_at
                FROM feedback_items WHERE ingestion_run_id = ? GROUP BY source_group LIMIT 1
                """,
                [run_id],
            )
            if group_row is not None:
                source_group = source_group or group_row["source_group"]
                last_record_at = last_record_at or group_row["last_record_at"]
        if source_group is not None:
            self.update_source_status(
                source_name=existing.source_name,
                source_group=SourceGroup(source_group),
                run_status=status,
                attempted_at=completed_at,
                last_record_at=last_record_at,
                recent_volume=counts.inserted,
                notes=notes or error_summary,
            )
        result = self.get_ingestion_run(run_id)
        assert result is not None
        return result

    complete_ingestion_run = finish_ingestion_run

    def _existing_feedback_id(self, item: FeedbackItem) -> str | None:
        row = self.db.query_one(
            "SELECT feedback_id FROM feedback_items WHERE feedback_id = ?", [item.feedback_id]
        )
        if row:
            return str(row["feedback_id"])
        # Extractors may assign a new unit identifier when re-reading a page.
        # Preserve genuinely distinct comments, but never insert the exact same
        # normalized content twice for one canonical social URL.
        if item.canonical_url and item.source_group is SourceGroup.SOCIAL:
            row = self.db.query_one(
                """
                SELECT feedback_id FROM feedback_items
                WHERE source_group = 'social'
                  AND canonical_url = ?
                  AND content_hash = ?
                LIMIT 1
                """,
                [item.canonical_url, item.content_hash],
            )
            if row:
                return str(row["feedback_id"])
        # Ordinary public-social records remain one stable record per canonical
        # URL.  A trusted page extractor is the narrow exception: it can emit
        # several independently identified units from the same page, and its
        # sanitized marker makes the feedback_id/source_external_id the durable
        # identity instead.
        extracted_unit_identity = (
            item.sanitized_metadata.get("identity_type") == "extracted_unit"
        )
        if (
            item.canonical_url
            and item.source_group is SourceGroup.SOCIAL
            and not extracted_unit_identity
        ):
            row = self.db.query_one(
                """
                SELECT feedback_id FROM feedback_items
                WHERE source_group = 'social' AND canonical_url = ? LIMIT 1
                """,
                [item.canonical_url],
            )
            if row:
                return str(row["feedback_id"])
        return None

    def mark_exact_content_duplicates(self) -> int:
        """Collapse historical exact replays while retaining distinct page units."""

        rows = self.db.query(
            """
            SELECT feedback_id, canonical_feedback_id
            FROM (
                SELECT
                    feedback_id,
                    first_value(feedback_id) OVER duplicate_window
                        AS canonical_feedback_id,
                    row_number() OVER duplicate_window AS duplicate_rank
                FROM feedback_items
                WHERE source_group = 'social'
                  AND canonical_url IS NOT NULL
                  AND content_hash IS NOT NULL
                WINDOW duplicate_window AS (
                    PARTITION BY source_group, canonical_url, content_hash
                    ORDER BY ingested_at, feedback_id
                )
            ) ranked
            WHERE duplicate_rank > 1
            """
        )
        marked = 0
        with self.db.transaction():
            for row in rows:
                self.db.execute(
                    """
                    UPDATE feedback_items
                    SET duplicate_of = ?, analysis_status = 'skipped'
                    WHERE feedback_id = ? AND duplicate_of IS NULL
                    """,
                    [row["canonical_feedback_id"], row["feedback_id"]],
                )
                marked += 1
        return marked

    def insert_feedback(self, item: FeedbackItem) -> bool:
        """Insert one item; return ``False`` for an existing stable identity."""

        if self._existing_feedback_id(item) is not None:
            return False
        cursor = self.db.execute(
            """
            INSERT INTO feedback_items (
                feedback_id, ingestion_run_id, source_external_id, source_group,
                source_platform, visibility, brand, brand_candidates,
                brand_attribution, experience_subject, occurred_at, observed_at,
                occurred_at_quality, ingested_at, original_timezone, language,
                language_confidence, title, text_redacted, rating, product_name,
                product_category, region, store, source_url, canonical_url,
                author_hash, conversation_hash, message_count, media_urls,
                content_hash, content_fingerprint, repost_group_id,
                crawler_record_id, sanitized_metadata, is_synthetic,
                quality_status, duplicate_of, analysis_status
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            ON CONFLICT DO NOTHING
            RETURNING feedback_id
            """,
            [
                item.feedback_id,
                item.ingestion_run_id,
                item.source_external_id,
                item.source_group.value,
                item.source_platform,
                item.visibility.value,
                item.brand.value if item.brand else None,
                [brand.value for brand in item.brand_candidates],
                item.brand_attribution.value,
                item.experience_subject.value,
                item.occurred_at,
                item.observed_at,
                item.occurred_at_quality.value,
                item.ingested_at,
                item.original_timezone,
                item.language,
                item.language_confidence,
                item.title,
                item.text_redacted,
                item.rating,
                item.product_name,
                item.product_category,
                item.region,
                item.store,
                item.source_url,
                item.canonical_url,
                item.author_hash,
                item.conversation_hash,
                item.message_count,
                item.media_urls,
                item.content_hash,
                item.content_fingerprint,
                item.repost_group_id,
                item.crawler_record_id,
                _json_dump(item.sanitized_metadata),
                item.is_synthetic,
                item.quality_status.value,
                item.duplicate_of,
                item.analysis_status.value,
            ],
        )
        return cursor.fetchone() is not None

    def insert_feedback_many(self, items: Iterable[FeedbackItem]) -> WriteCounts:
        seen = inserted = skipped = failed = 0
        with self.db.transaction():
            for item in items:
                seen += 1
                try:
                    if self.insert_feedback(item):
                        inserted += 1
                    else:
                        skipped += 1
                except Exception:
                    failed += 1
                    raise
        return WriteCounts(
            seen=seen, inserted=inserted, skipped=skipped, failed=failed
        )

    insert_many = insert_feedback_many

    def get_feedback(self, feedback_id: str) -> dict[str, Any] | None:
        row = self.db.query_one(
            "SELECT * FROM feedback_items WHERE feedback_id = ?", [feedback_id]
        )
        return self._decode_feedback_row(row) if row else None

    @staticmethod
    def _decode_feedback_row(row: Mapping[str, Any]) -> dict[str, Any]:
        result = dict(row)
        result["sanitized_metadata"] = _json_load(
            result.get("sanitized_metadata"), {}
        )
        return result

    def list_feedback(
        self,
        *,
        source_group: SourceGroup | str | None = None,
        brand: str | None = None,
        language: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[object] = []
        if source_group is not None:
            clauses.append("source_group = ?")
            params.append(
                source_group.value if isinstance(source_group, SourceGroup) else source_group
            )
        if brand is not None:
            clauses.append("brand = ?")
            params.append(brand)
        if language is not None:
            clauses.append("language = ?")
            params.append(language)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        params.extend([limit, offset])
        rows = self.db.query(
            f"SELECT * FROM feedback_items{where} ORDER BY observed_at DESC LIMIT ? OFFSET ?",
            params,
        )
        return [self._decode_feedback_row(row) for row in rows]

    def feedback_count(self) -> int:
        row = self.db.query_one("SELECT count(*) AS count FROM feedback_items")
        return int(row["count"]) if row else 0

    def record_quarantine(
        self,
        *,
        ingestion_run_id: str,
        source_name: str,
        row_number: int,
        reason_code: str,
        reason_message: str,
        masked_sample: Mapping[str, Any],
        source_file: str | Path | None = None,
        field: str | None = None,
        quarantine_id: str | None = None,
        created_at: datetime | None = None,
    ) -> str:
        identifier = quarantine_id or f"quarantine_{uuid.uuid4().hex}"
        self.db.execute(
            """
            INSERT INTO import_quarantine VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                identifier,
                ingestion_run_id,
                source_name,
                str(source_file) if source_file else None,
                row_number,
                reason_code,
                reason_message,
                field,
                _json_dump(dict(masked_sample)),
                created_at or utc_now(),
            ],
        )
        return identifier

    def list_quarantine(self, ingestion_run_id: str) -> list[dict[str, Any]]:
        rows = self.db.query(
            """
            SELECT * FROM import_quarantine WHERE ingestion_run_id = ?
            ORDER BY row_number, quarantine_id
            """,
            [ingestion_run_id],
        )
        for row in rows:
            row["masked_sample"] = _json_load(row.get("masked_sample"), {})
        return rows

    def register_import_file(
        self,
        *,
        source_name: str,
        file_sha256: str,
        filename: str,
        ingestion_run_id: str,
        seen_at: datetime | None = None,
    ) -> bool:
        seen_at = seen_at or utc_now()
        existing = self.db.query_one(
            """
            SELECT 1 AS found FROM imported_files
            WHERE source_name = ? AND file_sha256 = ?
            """,
            [source_name, file_sha256],
        )
        if existing:
            self.db.execute(
                """
                UPDATE imported_files SET last_ingestion_run_id = ?, last_seen_at = ?
                WHERE source_name = ? AND file_sha256 = ?
                """,
                [ingestion_run_id, seen_at, source_name, file_sha256],
            )
            return False
        self.db.execute(
            """
            INSERT INTO imported_files VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                source_name,
                file_sha256,
                filename,
                ingestion_run_id,
                seen_at,
                ingestion_run_id,
                seen_at,
            ],
        )
        return True

    def update_source_status(
        self,
        *,
        source_name: str,
        source_group: SourceGroup,
        run_status: IngestionRunStatus,
        attempted_at: datetime | None = None,
        last_record_at: datetime | None = None,
        recent_volume: int = 0,
        expected_volume_range: Mapping[str, int | float] | None = None,
        notes: str | None = None,
    ) -> SourceStatus:
        source_group = SourceGroup(source_group)
        run_status = IngestionRunStatus(run_status)
        attempted_at = attempted_at or utc_now()
        health = {
            IngestionRunStatus.COMPLETED: SourceHealthStatus.HEALTHY,
            IngestionRunStatus.PARTIAL: SourceHealthStatus.PARTIAL,
            IngestionRunStatus.FAILED: SourceHealthStatus.FAILED,
            IngestionRunStatus.RUNNING: SourceHealthStatus.PARTIAL,
            IngestionRunStatus.QUEUED: SourceHealthStatus.PARTIAL,
        }[run_status]
        recent = self.db.query(
            """
            SELECT status FROM ingestion_runs WHERE source_name = ?
            ORDER BY started_at DESC LIMIT 10
            """,
            [source_name],
        )
        failures = sum(
            row["status"] in {"partial", "failed"} for row in recent
        )
        failure_rate = failures / len(recent) if recent else 0.0
        existing = self.db.query_one(
            "SELECT * FROM source_status WHERE source_name = ?", [source_name]
        )
        last_success_at = (
            attempted_at
            if run_status is IngestionRunStatus.COMPLETED
            else existing.get("last_success_at") if existing else None
        )
        expected = expected_volume_range or (
            _json_load(existing.get("expected_volume_range"), {}) if existing else {}
        )
        stored_last_record = last_record_at or (
            existing.get("last_record_at") if existing else None
        )
        self.db.execute(
            """
            INSERT INTO source_status VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (source_name) DO UPDATE SET
                source_group = excluded.source_group,
                last_success_at = excluded.last_success_at,
                last_attempt_at = excluded.last_attempt_at,
                last_record_at = excluded.last_record_at,
                status = excluded.status,
                recent_volume = excluded.recent_volume,
                expected_volume_range = excluded.expected_volume_range,
                failure_rate = excluded.failure_rate,
                notes = excluded.notes
            """,
            [
                source_name,
                source_group.value,
                last_success_at,
                attempted_at,
                stored_last_record,
                health.value,
                recent_volume,
                _json_dump(expected),
                failure_rate,
                notes,
            ],
        )
        result = self.get_source_status(source_name)
        assert result is not None
        return result

    def get_source_status(self, source_name: str) -> SourceStatus | None:
        row = self.db.query_one(
            "SELECT * FROM source_status WHERE source_name = ?", [source_name]
        )
        return None if row is None else _source_status_from_row(row)

    def list_source_status(self) -> list[SourceStatus]:
        return [
            _source_status_from_row(row)
            for row in self.db.query("SELECT * FROM source_status ORDER BY source_name")
        ]

    def mark_stale_sources(
        self,
        *,
        now: datetime | None = None,
        stale_after: timedelta | None = None,
    ) -> int:
        now = now or utc_now()
        stale_after = stale_after or timedelta(hours=self.settings.voc_source_stale_hours)
        threshold = now - stale_after
        self.db.execute(
            """
            UPDATE source_status SET status = 'stale', notes = 'source is stale'
            WHERE status IN ('healthy', 'partial')
              AND (last_success_at IS NULL OR last_success_at < ?)
            """,
            [threshold],
        )
        row = self.db.query_one(
            "SELECT count(*) AS count FROM source_status WHERE status = 'stale'"
        )
        return int(row["count"]) if row else 0

    async def ingest_connector(
        self,
        connector: Any,
        *,
        connector_name: str,
        source_name: str,
        source_group: SourceGroup,
        source_file: str | Path | None = None,
        metadata: Mapping[str, Any] | None = None,
        raise_on_error: bool = True,
    ) -> IngestionRun:
        """Run one connector end to end while preserving partial success."""

        run = self.create_ingestion_run(
            connector=connector_name,
            source_name=source_name,
            source_file=source_file,
            metadata=metadata,
        )
        seen = inserted = skipped = failed = 0
        last_record_at: datetime | None = None
        error_summary: str | None = None
        try:
            async for raw in connector.collect(run):
                seen += 1
                item = normalize_raw_feedback(
                    raw,
                    ingestion_run_id=run.id,
                    source_name=source_name,
                    settings=self.settings,
                )
                if self.insert_feedback(item):
                    inserted += 1
                else:
                    skipped += 1
                record_at = item.occurred_at or item.observed_at
                last_record_at = max(last_record_at, record_at) if last_record_at else record_at

            quarantine = list(getattr(connector, "quarantined", []) or [])
            for problem in quarantine:
                failed += 1
                seen += 1
                self.record_quarantine(
                    ingestion_run_id=run.id,
                    source_name=source_name,
                    source_file=source_file,
                    row_number=problem.row_number,
                    reason_code=problem.code,
                    reason_message=problem.message,
                    field=problem.field,
                    masked_sample=problem.masked_sample,
                )
            connector_errors = list(getattr(connector, "errors", []) or [])
            if connector_errors:
                failed += len(connector_errors)
                error_summary = "; ".join(str(error) for error in connector_errors)[:2_000]
            file_sha256 = getattr(connector, "file_sha256", None)
            if file_sha256 and source_file is not None:
                self.register_import_file(
                    source_name=source_name,
                    file_sha256=str(file_sha256),
                    filename=Path(source_file).name,
                    ingestion_run_id=run.id,
                )
            status = (
                IngestionRunStatus.PARTIAL
                if failed and (inserted or skipped)
                else IngestionRunStatus.FAILED
                if failed
                else IngestionRunStatus.COMPLETED
            )
        except Exception as exc:
            failed += 1
            error_summary = f"{type(exc).__name__}: {exc}"[:2_000]
            status = (
                IngestionRunStatus.PARTIAL
                if inserted or skipped
                else IngestionRunStatus.FAILED
            )
            result = self.finish_ingestion_run(
                run.id,
                status=status,
                counts=WriteCounts(
                    seen=seen,
                    inserted=inserted,
                    skipped=skipped,
                    failed=failed,
                ),
                error_summary=error_summary,
                source_group=source_group,
                last_record_at=last_record_at,
            )
            if raise_on_error:
                raise
            return result

        return self.finish_ingestion_run(
            run.id,
            status=status,
            counts=WriteCounts(
                seen=seen,
                inserted=inserted,
                skipped=skipped,
                failed=failed,
            ),
            error_summary=error_summary,
            source_group=source_group,
            last_record_at=last_record_at,
        )

    def close(self) -> None:
        self.db.close()


Repository = GuardianVocRepository


__all__ = [
    "Database",
    "GuardianVocRepository",
    "MIGRATIONS_DIR",
    "Repository",
    "WriteCounts",
]
