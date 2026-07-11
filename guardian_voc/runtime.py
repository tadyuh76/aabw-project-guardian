"""Single-process scheduling and read-only collector-output ingestion.

The scheduler deliberately shares the API process's ``GuardianService``.  That
keeps every DuckDB write behind the service's existing re-entrant pipeline
lock; a second worker or sidecar must not open the database for writing.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import threading
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping

from guardian_voc.config import Settings
from guardian_voc.connectors.page_reader import (
    CachedPageReader,
    FallbackPageReader,
    MetadataPageReader,
    PageContent,
    PageReader,
    TinyFishPageReader,
)
from guardian_voc.connectors.public_social import (
    map_social_record,
    map_verified_feedback_export,
)
from guardian_voc.schemas.api import RunResponse
from guardian_voc.schemas.feedback import IngestionRunStatus, RawFeedback, SourceGroup

if TYPE_CHECKING:
    from guardian_voc.application import GuardianService


logger = logging.getLogger(__name__)

_COUNT_KEYS = (
    "discovered_rows",
    "mapped_rows",
    "discovery_only_rows",
    "enrichment_attempted_rows",
    "enrichment_succeeded_rows",
    "enrichment_failed_rows",
    "verified_rows",
    "verified_mapped_rows",
    "verified_rejected_rows",
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


class _VerifiedFeedbackValidationError(RuntimeError):
    """Fail a strict-export snapshot closed without exposing row contents."""

    def __init__(self, message: str, *, rows_seen: int) -> None:
        super().__init__(message)
        self.rows_seen = rows_seen


class CollectorOutputWatcher:
    """Import changed crawler JSONL snapshots through the canonical pipeline."""

    def __init__(
        self,
        service: GuardianService,
        settings: Settings,
        *,
        page_reader: PageReader | None = None,
    ) -> None:
        self.service = service
        self.settings = settings
        self.paths = tuple(settings.voc_collector_files)
        self.verified_paths = tuple(settings.voc_verified_feedback_files)
        self.checkpoint_path = settings.voc_collector_checkpoint_path or (
            settings.voc_data_dir / "collector-import-checkpoint.json"
        )
        self._fingerprints: dict[str, str] = {}
        self._file_stats: dict[str, dict[str, Any]] = {}
        self._load_checkpoint()
        self.last_file: str | None = None
        self.last_imported_at: datetime | None = None
        self.last_checked_at: datetime | None = None
        self.last_counts = self._aggregate_counts()
        # In-memory only: failed paid reads are not repeated for the same
        # immutable source snapshot when a later import step needs a retry.
        self._failed_enrichment_attempts: set[str] = set()
        self._page_reader = page_reader
        if settings.voc_collector_enrichment_enabled:
            if self._page_reader is None:
                self._page_reader = FallbackPageReader(
                    MetadataPageReader(use_browser=False),
                    TinyFishPageReader(
                        endpoint=settings.tinyfish_fetch_base_url,
                        api_key=settings.tinyfish_resolved_api_key,
                        timeout_seconds=settings.tinyfish_timeout_seconds,
                    ),
                    useful_text_chars=settings.tinyfish_useful_text_chars,
                )
            self._page_reader = CachedPageReader(self._page_reader)
        self.last_status = (
            "waiting" if self.paths or self.verified_paths else "disabled"
        )

    @staticmethod
    def _empty_counts() -> dict[str, int]:
        return {key: 0 for key in _COUNT_KEYS}

    def _configured_file_keys(self) -> tuple[str, ...]:
        return tuple(
            str(path.resolve()) for path in (*self.paths, *self.verified_paths)
        )

    def _aggregate_counts(
        self,
        *,
        pending_key: str | None = None,
        pending_counts: Mapping[str, int] | None = None,
    ) -> dict[str, int]:
        totals = self._empty_counts()
        for key in self._configured_file_keys():
            values: Mapping[str, Any]
            if pending_key == key and pending_counts is not None:
                values = pending_counts
            else:
                values = self._file_stats.get(key, {})
            for count_key in _COUNT_KEYS:
                totals[count_key] += int(values.get(count_key, 0))
        return totals

    def _load_checkpoint(self) -> None:
        path = self.checkpoint_path
        try:
            if not path.is_file() or path.stat().st_size > 1_048_576:
                return
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return
        values = payload.get("files") if isinstance(payload, Mapping) else None
        if not isinstance(values, Mapping):
            return
        for key, value in values.items():
            if not isinstance(key, str):
                continue
            if isinstance(value, str):
                # Backward-compatible with the first checkpoint shape.
                self._fingerprints[key] = value
                continue
            if not isinstance(value, Mapping) or not isinstance(
                value.get("fingerprint"), str
            ):
                continue
            self._fingerprints[key] = str(value["fingerprint"])
            self._file_stats[key] = {
                **{count_key: int(value.get(count_key, 0)) for count_key in _COUNT_KEYS},
                "checked_at": value.get("checked_at"),
            }

    def _save_checkpoint(self) -> None:
        path = self.checkpoint_path
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        files = {
            key: {
                "fingerprint": fingerprint,
                **self._file_stats.get(key, {}),
            }
            for key, fingerprint in self._fingerprints.items()
        }
        payload = json.dumps(
            {"version": 3, "files": files},
            ensure_ascii=False,
            sort_keys=True,
        )
        try:
            temporary.write_text(payload, encoding="utf-8")
            temporary.chmod(0o600)
            temporary.replace(path)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    def _stable_read(self, path: Path) -> bytes | None:
        """Return a bounded snapshot, or defer when a producer is replacing it."""

        try:
            before = path.stat()
        except FileNotFoundError:
            return None
        if not path.is_file():
            raise RuntimeError(f"collector output is not a regular file: {path.name}")
        if before.st_size > self.settings.voc_max_import_bytes:
            raise RuntimeError(f"collector output exceeds import limit: {path.name}")
        content = path.read_bytes()
        after = path.stat()
        if (
            before.st_ino != after.st_ino
            or before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns
            or len(content) != after.st_size
        ):
            logger.info("collector output changed during read; deferring %s", path.name)
            return None
        return content

    @staticmethod
    def _is_guardian_candidate(raw: Mapping[str, Any]) -> bool:
        """Require evidence candidates, never broad discovery-query hints."""

        values = raw.get("brand_candidates")
        if isinstance(values, str):
            values = [values]
        if not isinstance(values, (list, tuple, set)):
            return False
        return any(str(value).strip().lower() == "guardian" for value in values)

    async def _enrich_rows(
        self,
        rows: list[tuple[int, Mapping[str, Any]]],
        *,
        observed_default: datetime,
        snapshot_fingerprint: str,
    ) -> dict[int, RawFeedback]:
        """Read a bounded set of public pages without exposing row-level errors."""

        reader = self._page_reader
        if reader is None or not rows:
            return {}
        semaphore = asyncio.Semaphore(
            self.settings.voc_collector_enrichment_concurrency
        )

        async def enrich_one(
            index: int, raw: Mapping[str, Any]
        ) -> tuple[int, RawFeedback | None]:
            async with semaphore:
                url = str(raw.get("canonical_url") or raw.get("link") or "")
                attempt_key = (
                    f"{snapshot_fingerprint}:"
                    + hashlib.sha256(url.encode("utf-8")).hexdigest()
                )
                if attempt_key in self._failed_enrichment_attempts:
                    return index, None
                try:
                    page = await reader.read(
                        url,
                        platform=str(raw.get("platform") or "other").strip().lower(),
                    )
                    if not isinstance(page, PageContent) or not page.text.strip():
                        self._failed_enrichment_attempts.add(attempt_key)
                        return index, None
                    enriched = dict(raw)
                    enriched["page_reader_result"] = {
                        "title": page.title,
                        "text": page.text,
                        "reader": page.reader or "collector_page_reader",
                        "metadata": page.metadata,
                    }
                    mapped = map_social_record(
                        enriched,
                        observed_default=observed_default,
                        business_timezone=self.settings.voc_business_timezone,
                    )
                    if mapped is None:
                        self._failed_enrichment_attempts.add(attempt_key)
                except Exception:
                    # Page-reader/provider exceptions can contain target URLs or
                    # response text. Only aggregate counts leave this boundary.
                    self._failed_enrichment_attempts.add(attempt_key)
                    return index, None
                return index, mapped

        enriched = await asyncio.gather(
            *(enrich_one(index, raw) for index, raw in rows)
        )
        return {index: mapped for index, mapped in enriched if mapped is not None}

    def _canonical_payload(
        self, content: bytes, *, filename: str, snapshot_fingerprint: str
    ) -> tuple[bytes, dict[str, int]]:
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise RuntimeError(f"collector output is not UTF-8: {filename}") from exc
        observed_default = _utc_now()
        rows: list[Mapping[str, Any]] = []
        for line_number, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            if len(rows) >= self.settings.voc_max_import_rows:
                raise RuntimeError(f"collector output exceeds row limit: {filename}")
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RuntimeError(
                    f"collector output has invalid JSON at line {line_number}: {filename}"
                ) from exc
            if not isinstance(value, Mapping):
                raise RuntimeError(
                    f"collector output row {line_number} is not an object: {filename}"
                )
            rows.append(value)

        mapped_rows: list[RawFeedback | None] = []
        enrichment_candidates: list[tuple[int, Mapping[str, Any]]] = []
        for index, value in enumerate(rows):
            raw = map_social_record(
                value,
                observed_default=observed_default,
                business_timezone=self.settings.voc_business_timezone,
            )
            mapped_rows.append(raw)
            if (
                raw is None
                and self.settings.voc_collector_enrichment_enabled
                and self._is_guardian_candidate(value)
                and len(enrichment_candidates)
                < self.settings.voc_collector_enrichment_max_rows
            ):
                enrichment_candidates.append((index, value))

        enriched: dict[int, RawFeedback] = {}
        if enrichment_candidates:
            try:
                enriched = asyncio.run(
                    self._enrich_rows(
                        enrichment_candidates,
                        observed_default=observed_default,
                        snapshot_fingerprint=snapshot_fingerprint,
                    )
                )
            except Exception:
                # ``_enrich_rows`` absorbs row-level failures. This guards the
                # event-loop boundary while keeping diagnostics aggregate-only.
                enriched = {}
            for index, raw in enriched.items():
                mapped_rows[index] = raw

        canonical = [
            raw.model_dump_json() for raw in mapped_rows if raw is not None
        ]
        payload = ("\n".join(canonical) + ("\n" if canonical else "")).encode("utf-8")
        if len(payload) > self.settings.voc_max_import_bytes:
            raise RuntimeError(f"canonical collector output exceeds import limit: {filename}")
        attempted = len(enrichment_candidates)
        succeeded = len(enriched)
        failed = attempted - succeeded
        if failed:
            logger.warning(
                "collector page enrichment had %d failed attempt(s) out of %d",
                failed,
                attempted,
            )
        return payload, {
            "discovered_rows": len(rows),
            "mapped_rows": len(canonical),
            "discovery_only_rows": len(rows) - len(canonical),
            "enrichment_attempted_rows": attempted,
            "enrichment_succeeded_rows": succeeded,
            "enrichment_failed_rows": failed,
            "verified_rows": 0,
            "verified_mapped_rows": 0,
            "verified_rejected_rows": 0,
        }

    def _verified_payload(
        self, content: bytes, *, filename: str
    ) -> tuple[bytes, dict[str, int]]:
        """Build canonical rows from the explicitly trusted strict export.

        The whole snapshot fails closed when any row is malformed or marked
        synthetic. A rejected snapshot is not checkpointed, so the producer
        can atomically replace it and the scheduler will retry it.
        """

        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise _VerifiedFeedbackValidationError(
                f"verified feedback export is not UTF-8: {filename}",
                rows_seen=1,
            ) from None

        canonical: list[str] = []
        rows_seen = 0
        for line_number, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            rows_seen += 1
            if rows_seen > self.settings.voc_max_import_rows:
                raise _VerifiedFeedbackValidationError(
                    f"verified feedback export exceeds row limit: {filename}",
                    rows_seen=rows_seen,
                )
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                raise _VerifiedFeedbackValidationError(
                    f"verified feedback export has invalid JSON at line "
                    f"{line_number}: {filename}",
                    rows_seen=rows_seen,
                ) from None
            if not isinstance(value, Mapping):
                raise _VerifiedFeedbackValidationError(
                    f"verified feedback export row {line_number} is not an "
                    f"object: {filename}",
                    rows_seen=rows_seen,
                )
            try:
                mapped = map_verified_feedback_export(
                    value,
                    business_timezone=self.settings.voc_business_timezone,
                )
            except Exception:
                # Pydantic input diagnostics can echo customer text. Keep the
                # public/runtime error at row granularity only.
                raise _VerifiedFeedbackValidationError(
                    f"verified feedback export row {line_number} failed strict "
                    f"validation: {filename}",
                    rows_seen=rows_seen,
                ) from None
            canonical.append(mapped.model_dump_json())

        payload = ("\n".join(canonical) + ("\n" if canonical else "")).encode(
            "utf-8"
        )
        if len(payload) > self.settings.voc_max_import_bytes:
            raise _VerifiedFeedbackValidationError(
                f"canonical verified export exceeds import limit: {filename}",
                rows_seen=rows_seen,
            )
        return payload, {
            "discovered_rows": 0,
            "mapped_rows": 0,
            "discovery_only_rows": 0,
            "enrichment_attempted_rows": 0,
            "enrichment_succeeded_rows": 0,
            "enrichment_failed_rows": 0,
            "verified_rows": rows_seen,
            "verified_mapped_rows": len(canonical),
            "verified_rejected_rows": 0,
        }

    @staticmethod
    def _source_note(counts: Mapping[str, int]) -> str:
        discovered = int(counts["discovered_rows"])
        mapped = int(counts["mapped_rows"])
        discovery_only = int(counts["discovery_only_rows"])
        attempted = int(counts.get("enrichment_attempted_rows", 0))
        failed = int(counts.get("enrichment_failed_rows", 0))
        verified = int(counts.get("verified_rows", 0))
        verified_mapped = int(counts.get("verified_mapped_rows", 0))
        verified_rejected = int(counts.get("verified_rejected_rows", 0))
        return (
            f"Watched search snapshot: {discovered} public candidates; {mapped} "
            f"contained pre-verified page content. {discovery_only} unverified rows were not "
            "treated as customer feedback. Guardian-only page enrichment "
            f"attempted {attempted}; {failed} failed. Search titles and snippets "
            "were excluded. Trusted strict export: "
            f"{verified} rows checked; {verified_mapped} accepted for normal "
            f"classification; {verified_rejected} rejected."
        )

    def _record_source_status(self, counts: Mapping[str, int]) -> None:
        repository = getattr(self.service, "repository", None)
        database = getattr(self.service, "database", None)
        if repository is None:
            return
        discovered = int(counts["discovered_rows"])
        mapped = int(counts["mapped_rows"])
        discovery_only = int(counts["discovery_only_rows"])
        enrichment_failed = int(counts.get("enrichment_failed_rows", 0))
        verified_mapped = int(counts.get("verified_mapped_rows", 0))
        verified_rejected = int(counts.get("verified_rejected_rows", 0))
        attempted_at = _utc_now()
        partial = (
            discovery_only > 0
            or enrichment_failed > 0
            or verified_rejected > 0
        )
        note = self._source_note(counts)
        repository.update_source_status(
            source_name="collector_public_social",
            source_group=SourceGroup.SOCIAL,
            run_status=(
                IngestionRunStatus.PARTIAL
                if partial
                else IngestionRunStatus.COMPLETED
            ),
            attempted_at=attempted_at,
            recent_volume=mapped + verified_mapped,
            expected_volume_range={
                "discovered": discovered,
                "enrichment_attempted": int(
                    counts.get("enrichment_attempted_rows", 0)
                ),
                "enrichment_failed": enrichment_failed,
                "verified": int(counts.get("verified_rows", 0)),
                "verified_accepted": verified_mapped,
                "verified_rejected": verified_rejected,
            },
            notes=note,
        )
        if partial and database is not None:
            # The snapshot itself was read successfully. Persist that freshness
            # separately from its partial content-verification coverage.
            database.execute(
                "UPDATE source_status SET last_success_at = ? WHERE source_name = ?",
                [attempted_at, "collector_public_social"],
            )

    def _commit_snapshot(
        self,
        *,
        key: str,
        fingerprint: str,
        checkpoint_stats: Mapping[str, Any],
    ) -> None:
        """Commit source health and the file cursor under the service writer lock."""

        pipeline_lock = getattr(self.service, "_pipeline_lock", None)
        context = pipeline_lock if pipeline_lock is not None else nullcontext()
        with context:
            previous_fingerprint = self._fingerprints.get(key)
            previous_stats = self._file_stats.get(key)
            self._fingerprints[key] = fingerprint
            self._file_stats[key] = dict(checkpoint_stats)
            try:
                aggregate = self._aggregate_counts()
                self._record_source_status(aggregate)
                self._save_checkpoint()
            except Exception:
                if previous_fingerprint is None:
                    self._fingerprints.pop(key, None)
                else:
                    self._fingerprints[key] = previous_fingerprint
                if previous_stats is None:
                    self._file_stats.pop(key, None)
                else:
                    self._file_stats[key] = previous_stats
                raise
            self.last_counts = aggregate
        prefix = f"{fingerprint}:"
        self._failed_enrichment_attempts = {
            item
            for item in self._failed_enrichment_attempts
            if not item.startswith(prefix)
        }

    def _record_failed_source_status(self, counts: Mapping[str, int]) -> None:
        repository = getattr(self.service, "repository", None)
        if repository is None:
            return
        pipeline_lock = getattr(self.service, "_pipeline_lock", None)
        context = pipeline_lock if pipeline_lock is not None else nullcontext()
        with context:
            repository.update_source_status(
                source_name="collector_public_social",
                source_group=SourceGroup.SOCIAL,
                run_status=IngestionRunStatus.FAILED,
                attempted_at=_utc_now(),
                recent_volume=(
                    int(counts["mapped_rows"])
                    + int(counts.get("verified_mapped_rows", 0))
                ),
                expected_volume_range={
                    "discovered": int(counts["discovered_rows"]),
                    "enrichment_attempted": int(
                        counts.get("enrichment_attempted_rows", 0)
                    ),
                    "enrichment_failed": int(
                        counts.get("enrichment_failed_rows", 0)
                    ),
                    "verified": int(counts.get("verified_rows", 0)),
                    "verified_accepted": int(
                        counts.get("verified_mapped_rows", 0)
                    ),
                    "verified_rejected": int(
                        counts.get("verified_rejected_rows", 0)
                    ),
                },
                notes=(
                    f"{self._source_note(counts)} This source snapshot did not "
                    "reach publication and will be retried."
                ),
            )

    def _restore_unchanged_file(self, path: Path, key: str) -> None:
        self.last_file = path.name
        checked_at = self._file_stats.get(key, {}).get("checked_at")
        if not isinstance(checked_at, str):
            return
        try:
            parsed = datetime.fromisoformat(checked_at)
        except ValueError:
            return
        if self.last_checked_at is None or parsed > self.last_checked_at:
            self.last_checked_at = parsed

    @staticmethod
    def _status_from_counts(
        counts: Mapping[str, int], *, default: str
    ) -> str:
        if int(counts.get("verified_rejected_rows", 0)):
            return "failed"
        incomplete = (
            int(counts.get("discovery_only_rows", 0)) > 0
            or int(counts.get("enrichment_failed_rows", 0)) > 0
        )
        mapped = int(counts.get("mapped_rows", 0)) + int(
            counts.get("verified_mapped_rows", 0)
        )
        if incomplete:
            return "partial" if mapped else "discovery_only"
        if int(counts.get("discovered_rows", 0)) and not mapped:
            return "discovery_only"
        return default

    def poll(self) -> list[RunResponse]:
        results: list[RunResponse] = []
        configured_paths = (*self.paths, *self.verified_paths)
        if not configured_paths:
            self.last_status = "disabled"
            return results

        seen_files = 0
        for path in self.paths:
            content = self._stable_read(path)
            if content is None:
                continue
            seen_files += 1
            key = str(path.resolve())
            fingerprint = hashlib.sha256(content).hexdigest()
            if self._fingerprints.get(key) == fingerprint:
                self._restore_unchanged_file(path, key)
                continue
            payload, counts = self._canonical_payload(
                content,
                filename=path.name,
                snapshot_fingerprint=fingerprint,
            )
            self.last_file = path.name
            self.last_checked_at = _utc_now()
            checkpoint_stats = {
                **counts,
                "checked_at": _iso(self.last_checked_at),
            }
            if not counts["mapped_rows"]:
                self._commit_snapshot(
                    key=key,
                    fingerprint=fingerprint,
                    checkpoint_stats=checkpoint_stats,
                )
                continue
            try:
                result = self.service.import_bytes(
                    filename=f"collector-{path.stem}.jsonl",
                    content=payload,
                    profile="generic",
                )
            except Exception as exc:
                failed_counts = self._aggregate_counts(
                    pending_key=key,
                    pending_counts=counts,
                )
                self.last_counts = failed_counts
                self._record_failed_source_status(failed_counts)
                raise RuntimeError(
                    f"collector import failed before publication: {path.name}"
                ) from exc
            if result.status not in {"completed", "partial"}:
                failed_counts = self._aggregate_counts(
                    pending_key=key,
                    pending_counts=counts,
                )
                self.last_counts = failed_counts
                self._record_failed_source_status(failed_counts)
                raise RuntimeError(
                    f"collector import pipeline failed; run {result.pipeline_run_id}"
                )
            self.last_imported_at = result.completed_at or _utc_now()
            self._commit_snapshot(
                key=key,
                fingerprint=fingerprint,
                checkpoint_stats=checkpoint_stats,
            )
            results.append(result)

        for path in self.verified_paths:
            content = self._stable_read(path)
            if content is None:
                continue
            seen_files += 1
            key = str(path.resolve())
            fingerprint = hashlib.sha256(content).hexdigest()
            if self._fingerprints.get(key) == fingerprint:
                self._restore_unchanged_file(path, key)
                continue
            self.last_file = path.name
            self.last_checked_at = _utc_now()
            try:
                payload, counts = self._verified_payload(
                    content,
                    filename=path.name,
                )
            except _VerifiedFeedbackValidationError as exc:
                rejected = self._empty_counts()
                rejected["verified_rows"] = exc.rows_seen
                rejected["verified_rejected_rows"] = 1
                failed_counts = self._aggregate_counts(
                    pending_key=key,
                    pending_counts=rejected,
                )
                self.last_counts = failed_counts
                self.last_status = "failed"
                self._record_failed_source_status(failed_counts)
                raise RuntimeError(str(exc)) from None
            checkpoint_stats = {
                **counts,
                "checked_at": _iso(self.last_checked_at),
            }
            if not counts["verified_mapped_rows"]:
                self._commit_snapshot(
                    key=key,
                    fingerprint=fingerprint,
                    checkpoint_stats=checkpoint_stats,
                )
                continue
            try:
                result = self.service.import_bytes(
                    filename=f"verified-{path.stem}.jsonl",
                    content=payload,
                    profile="generic",
                )
            except Exception as exc:
                failed_counts = self._aggregate_counts(
                    pending_key=key,
                    pending_counts=counts,
                )
                self.last_counts = failed_counts
                self._record_failed_source_status(failed_counts)
                raise RuntimeError(
                    f"verified feedback import failed before publication: {path.name}"
                ) from exc
            if result.status not in {"completed", "partial"}:
                failed_counts = self._aggregate_counts(
                    pending_key=key,
                    pending_counts=counts,
                )
                self.last_counts = failed_counts
                self._record_failed_source_status(failed_counts)
                raise RuntimeError(
                    "verified feedback pipeline failed; run "
                    f"{result.pipeline_run_id}"
                )
            self.last_imported_at = result.completed_at or _utc_now()
            self._commit_snapshot(
                key=key,
                fingerprint=fingerprint,
                checkpoint_stats=checkpoint_stats,
            )
            results.append(result)

        self.last_counts = self._aggregate_counts()
        if not seen_files:
            self.last_status = "waiting"
        else:
            default = (
                "partial"
                if any(result.status == "partial" for result in results)
                else "completed"
                if results
                else "unchanged"
            )
            self.last_status = self._status_from_counts(
                self.last_counts,
                default=default,
            )
            if seen_files < len(configured_paths):
                self.last_status = "partial"
        return results

    def snapshot(self) -> dict[str, Any]:
        return {
            "status": self.last_status,
            "watched_files": len(self.paths) + len(self.verified_paths),
            "raw_discovery_files": len(self.paths),
            "verified_feedback_files": len(self.verified_paths),
            "last_file": self.last_file,
            "last_checked_at": _iso(self.last_checked_at),
            "last_imported_at": _iso(self.last_imported_at),
            "source_note": self._source_note(self.last_counts),
            **self.last_counts,
        }


class PipelineScheduler:
    """Continuously run collector/import/crawl pipelines with bounded backoff."""

    def __init__(self, service: GuardianService, settings: Settings | None = None) -> None:
        self.service = service
        self.settings = settings or service.settings
        self.collector = CollectorOutputWatcher(service, self.settings)
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._state_lock = threading.Lock()
        self._state = "disabled" if not self.settings.voc_scheduler_enabled else "starting"
        self._next_run_at: datetime | None = None
        self._last_started_at: datetime | None = None
        self._last_completed_at: datetime | None = None
        self._last_run_id: str | None = None
        self._last_run_status: str | None = None
        self._consecutive_failures = 0

    def start(self) -> None:
        if not self.settings.voc_scheduler_enabled:
            return
        with self._state_lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._state = "starting"
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run,
                name="guardian-voc-pipeline-scheduler",
                daemon=True,
            )
            self._thread.start()

    def stop(self, timeout: float | None = None) -> bool:
        thread = self._thread
        if thread is None:
            return True
        with self._state_lock:
            self._state = "stopping"
            self._next_run_at = None
        self._stop_event.set()
        thread.join(timeout or self.settings.voc_scheduler_shutdown_timeout_seconds)
        stopped = not thread.is_alive()
        if stopped:
            with self._state_lock:
                self._state = "stopped"
        return stopped

    def _record(self, result: RunResponse) -> None:
        with self._state_lock:
            self._last_run_id = result.pipeline_run_id
            self._last_run_status = result.status

    def _require_success(self, result: RunResponse) -> None:
        self._record(result)
        if result.status == "running":
            raise RuntimeError(f"pipeline busy; active run {result.pipeline_run_id}")
        if result.status == "failed":
            raise RuntimeError(f"pipeline failed; run {result.pipeline_run_id}")

    def run_once(self) -> bool:
        with self._state_lock:
            self._state = "running"
            self._last_started_at = _utc_now()
            self._next_run_at = None
        collector_error: Exception | None = None
        try:
            try:
                for result in self.collector.poll():
                    self._require_success(result)
            except Exception as exc:
                # A malformed optional file snapshot remains failed and
                # retryable, but must not suppress the independently verified
                # SERP → TinyFish → OpenAI collection path for the cycle.
                collector_error = exc
                logger.warning(
                    "collector snapshot failed; continuing strict live collection (%s)",
                    type(exc).__name__,
                )
            if self._stop_event.is_set():
                return True

            # Imports dropped into the canonical inbox are handled even when
            # direct paid crawling is disabled.
            self._require_success(self.service.run_all())

            if self.settings.voc_scheduler_full_flow_enabled:
                if not self._stop_event.is_set():
                    self._require_success(self.service.run_live_collection())
            elif self.settings.voc_scheduler_crawl_enabled:
                for keyword in self.settings.crawler_keywords:
                    if self._stop_event.is_set():
                        break
                    self._require_success(self.service.crawl(keyword=keyword))
            if collector_error is not None:
                raise RuntimeError("collector snapshot failed independently")
        except Exception as exc:
            logger.warning("scheduled pipeline cycle failed: %s", exc)
            with self._state_lock:
                self._consecutive_failures += 1
                self._last_completed_at = _utc_now()
                self._state = "backoff"
            return False
        with self._state_lock:
            self._consecutive_failures = 0
            self._last_completed_at = _utc_now()
            self._state = "idle"
        return True

    def _delay_after_cycle(self) -> int:
        with self._state_lock:
            failures = self._consecutive_failures
        if not failures:
            return self.settings.voc_scheduler_interval_seconds
        return min(
            self.settings.voc_scheduler_interval_seconds * (2 ** (failures - 1)),
            self.settings.voc_scheduler_max_backoff_seconds,
        )

    def _wait(self, seconds: int) -> bool:
        with self._state_lock:
            self._next_run_at = _utc_now() + timedelta(seconds=seconds)
            if self._state == "starting":
                self._state = "idle"
        return self._stop_event.wait(seconds)

    def _run(self) -> None:
        if self._wait(self.settings.voc_scheduler_initial_delay_seconds):
            return
        while not self._stop_event.is_set():
            self.run_once()
            if self._wait(self._delay_after_cycle()):
                return

    def snapshot(self) -> dict[str, Any]:
        thread = self._thread
        with self._state_lock:
            snapshot = {
                "enabled": self.settings.voc_scheduler_enabled,
                "state": self._state,
                "thread_alive": bool(thread and thread.is_alive()),
                "interval_seconds": self.settings.voc_scheduler_interval_seconds,
                "next_run_at": _iso(self._next_run_at),
                "last_started_at": _iso(self._last_started_at),
                "last_completed_at": _iso(self._last_completed_at),
                "last_run_id": self._last_run_id,
                "last_run_status": self._last_run_status,
                "consecutive_failures": self._consecutive_failures,
                "direct_crawl_enabled": self.settings.voc_scheduler_crawl_enabled,
                "full_flow_enabled": self.settings.voc_scheduler_full_flow_enabled,
                "full_flow_source_ids": list(
                    self.settings.voc_live_collection_source_ids
                ),
            }
        snapshot["collector"] = self.collector.snapshot()
        return snapshot


__all__ = ["CollectorOutputWatcher", "PipelineScheduler"]
