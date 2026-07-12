"""Application service joining ingestion, analytics, insights, and the HTTP API.

The service is deliberately synchronous at its public boundary. DuckDB remains
the single durable writer; provider coroutines are executed in bounded batches
inside the same pipeline run.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import tempfile
import threading
import unicodedata
import uuid
from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from guardian_voc.ai.openai_compatible import OpenAICompatibleProvider
from guardian_voc.ai.provider import AIProviderError
from guardian_voc.ai.prompts import ITEM_CLASSIFIER_PROMPT_VERSION
from guardian_voc.ai.validator import apply_low_confidence_policy, validate_classification
from guardian_voc.analytics import (
    aggregate_daily_metrics,
    build_analysis_windows,
    build_matched_public_benchmark,
    compute_stratified_trend,
    rank_likely_drivers,
)
from guardian_voc.analytics.metrics import collapse_independent_units, units_in_window
from guardian_voc.analytics.data_health import assess_all_sources
from guardian_voc.analytics.trends import detect_improving, detect_recurring_friction
from guardian_voc.config import Settings, get_settings
from guardian_voc.connectors.file_import import FileImportConnector, preview_import, read_import_sample
from guardian_voc.connectors.mapping_profiles import MappingProfile, get_profile
from guardian_voc.schemas.import_mapping import ImportColumnMapping
from guardian_voc.connectors.marketplace_api import (
    LazadaCredentials,
    LazadaReviewConnector,
    MarketplaceReconciliationManifest,
    ShopeeCredentials,
    ShopeeReviewConnector,
)
from guardian_voc.connectors.public_social import LiveSocialCrawlerConnector
from guardian_voc.db import Database, GuardianVocRepository, WriteCounts
from guardian_voc.insights import build_fact_packet, generate_insight_card
from guardian_voc.insights.playbooks import get_playbook, viewer_action
from guardian_voc.insights.ranking import rank_today_candidates
from guardian_voc.pipeline.normalize import normalize_raw_feedback, utc_now
from guardian_voc.pipeline.pii import mask_preview_mapping
from guardian_voc.schemas.analysis import (
    AnalysisWindows,
    AnalyticsUnit,
    Brand,
    ClassificationRequest,
    ClassificationResult,
    ExperienceSubject,
    HealthStatus,
    JourneyStage,
    OccurredAtQuality,
    PrimaryTopic,
    Sentiment,
    SourceGroup,
    SourceHealthSnapshot,
    SourceStratum,
    TrendResult,
    TrendThresholds,
    TrustedSourceMetadata,
    Urgency,
    Visibility,
    WeeklyTopicMetric,
)
from guardian_voc.schemas.api import (
    BenchmarkBrandView,
    BenchmarkView,
    BriefLineView,
    CardMetricsView,
    ConfidenceView,
    CoverageView,
    DashboardBenchmarkAggregateView,
    DashboardBenchmarkView,
    DashboardComparisonThemeView,
    DashboardCoverageView,
    DashboardEvidenceView,
    DashboardProblemDetailView,
    DashboardPeriodCountsView,
    DashboardProductView,
    DashboardRatingCountView,
    DashboardRatingTrendPointView,
    DashboardResponse,
    DashboardSentimentTrendPointView,
    DashboardThemeView,
    DashboardWordCloudTermView,
    DashboardWindowsView,
    EvidencePreviewView,
    EvidenceResponse,
    FeedbackListItem,
    FeedbackListResponse,
    InsightCardView,
    InsightPatchRequest,
    ProblemBreakdownView,
    ProblemReviewView,
    ProblemSummaryThemeView,
    ProblemTrendPointView,
    Role,
    RunResponse,
    SourceStatusView,
    StratumView,
    TodayResponse,
    TrendPointView,
)
from guardian_voc.schemas.feedback import (
    IngestionRunStatus,
    RawFeedback,
    SourceGroup as FeedbackSourceGroup,
)
from guardian_voc.schemas.insights import (
    BusinessEventFact,
    FactPacket,
    InsightCard,
    InsightObservation,
    InsightStatus,
    InsightType,
    MatchedPublicBenchmarkFact,
    MonitoringReference,
    RankableInsight,
    TopSubtopicFact,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures"
DASHBOARD_EVIDENCE_LIMIT = 200
DASHBOARD_WORD_CLOUD_LIMIT = 70
WORD_CLOUD_STOPWORDS = {
    "and", "are", "but", "cac", "can", "cho", "con", "cua", "cung",
    "duoc", "for", "guardian", "hang", "hon", "kha", "khi", "khong",
    "lai", "lan", "minh", "mot", "nay", "nen", "nha", "nhung", "qua",
    "rat", "san", "the", "thi", "toi", "trong", "voi", "was", "were",
    "you",
}
WORD_CLOUD_TOKEN_RE = re.compile(r"[^\W\d_]{3,}", re.UNICODE)


def _word_cloud_stopword_key(value: str) -> str:
    normalized = unicodedata.normalize("NFD", value).replace("đ", "d").replace("Đ", "D")
    return normalized.encode("ascii", "ignore").decode("ascii")


def _json_dump(value: object) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _json_load(value: object, default: object) -> object:
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return default


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _safe_filename(value: str) -> str:
    name = Path(value).name
    if not name or name in {".", ".."} or "\x00" in name:
        raise ValueError("invalid import filename")
    return name


def _dashboard_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _dashboard_metadata_value(
    metadata: Mapping[str, Any], *keys: str
) -> str | None:
    for key in keys:
        value = _dashboard_text(metadata.get(key))
        if value is not None and value != "[REDACTED]":
            return value
    return None


def _dashboard_word_cloud(
    rows: Sequence[Mapping[str, Any]],
) -> list[DashboardWordCloudTermView]:
    counts: Counter[str] = Counter()
    for row in rows:
        text = _dashboard_text(row.get("text_redacted"))
        if text is None:
            continue
        for match in WORD_CLOUD_TOKEN_RE.finditer(text.lower()):
            keyword = match.group(0)
            if _word_cloud_stopword_key(keyword) in WORD_CLOUD_STOPWORDS:
                continue
            counts[keyword] += 1
    return [
        DashboardWordCloudTermView(keyword=keyword, count=count)
        for keyword, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[
            :DASHBOARD_WORD_CLOUD_LIMIT
        ]
    ]


def _dashboard_product_id(row: Mapping[str, Any]) -> str:
    metadata_value = _json_load(row.get("sanitized_metadata"), {})
    metadata = metadata_value if isinstance(metadata_value, Mapping) else {}
    explicit_id = _dashboard_metadata_value(metadata, "product_id")
    if explicit_id is not None:
        return explicit_id
    product_name = _dashboard_text(row.get("product_name"))
    if product_name is None:
        return "unattributed"
    digest = hashlib.sha256(product_name.encode("utf-8")).hexdigest()[:20]
    return f"product-name-{digest}"


def _public_evidence_source_url(row: Mapping[str, Any]) -> str | None:
    """Expose only public, operator-actionable evidence URLs."""

    if bool(row.get("is_synthetic")):
        return None
    source_group = str(row.get("source_group") or "").strip().lower()
    source_platform = str(row.get("source_platform") or "").strip().lower()
    if source_group == "social":
        url = _dashboard_text(row.get("canonical_url")) or _dashboard_text(
            row.get("source_url")
        )
    elif source_group == "owned" and source_platform.endswith("_ecommerce"):
        url = _dashboard_text(row.get("source_url")) or _dashboard_text(
            row.get("canonical_url")
        )
    else:
        return None
    if url is None:
        return None
    try:
        parsed = urlsplit(url)
        _ = parsed.port
    except (TypeError, ValueError):
        return None
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not parsed.netloc
        or parsed.username
        or parsed.password
    ):
        return None
    return url


def _dashboard_dominant(values: Iterable[str | None]) -> str | None:
    counts = Counter(value for value in values if value)
    if not counts:
        return None
    return sorted(counts, key=lambda value: (-counts[value], value))[0]


@dataclass(frozen=True)
class BuiltInsight:
    card: InsightCard
    trend: TrendResult
    benchmark: MatchedPublicBenchmarkFact | None
    evidence_roles: tuple[tuple[str, str], ...]


class GuardianService:
    """One-process application service with one serialized DuckDB writer."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.database = Database(settings=self.settings)
        self.repository = GuardianVocRepository(self.database, settings=self.settings)
        self._initialized = False
        self._hydrated = False
        self._pipeline_lock = threading.RLock()
        self._run_state_lock = threading.Lock()
        self._active_run_id: str | None = None
        self._built: dict[str, BuiltInsight] = {}
        self._labels: dict[str, dict[str, Any]] | None = None

    @property
    def as_of(self) -> datetime:
        if self.settings.voc_demo_mode and self.settings.voc_demo_as_of is not None:
            return self.settings.voc_demo_as_of
        return datetime.now(timezone.utc)

    def initialize(
        self,
        *,
        seed_demo: bool = False,
        process_existing: bool = True,
    ) -> None:
        with self._pipeline_lock:
            if not self._initialized:
                self.repository.initialize()
                self._initialized = True
            if self._hydrated:
                return
            # This flag describes the startup attempt, not whether an insight
            # happened to qualify. Set it before any paid classification call
            # so sparse/failed data cannot make health/read probes retry AI.
            self._hydrated = True
            if not process_existing:
                return
            count = self.repository.feedback_count()
            if seed_demo and count == 0:
                self.seed_demo(reset=False)
            elif count and self._active_run_id is None:
                self._classify_pending()
                self._rebuild_insights(pipeline_run_id="startup")

    def close(self) -> None:
        self.repository.close()
        self._initialized = False
        self._hydrated = False

    def _reset_database(self) -> None:
        path = Path(self.settings.voc_db_path)
        self.close()
        for candidate in (path, Path(f"{path}.wal")):
            try:
                candidate.unlink()
            except FileNotFoundError:
                pass
        self.database = Database(settings=self.settings)
        self.repository = GuardianVocRepository(self.database, settings=self.settings)
        self.repository.initialize()
        self._initialized = True
        self._hydrated = False
        self._built.clear()

    def health(self) -> dict[str, Any]:
        self.initialize(seed_demo=False)
        row = self.database.query_one("SELECT count(*) AS count FROM feedback_items") or {"count": 0}
        return {
            "status": "ok",
            "mode": "demo" if self.settings.voc_demo_mode else "live",
            "database": "ready",
            "schema_version": self.database.schema_version(),
            "feedback_items": int(row["count"]),
            "write_api_enabled": self.settings.voc_write_api_enabled,
            "live_search_provider": (
                "tinyfish"
                if self.settings.tinyfish_enabled
                else "serpapi"
                if self.settings.serp_api_key
                else "none"
            ),
            "tinyfish_fetch_fallback": self.settings.tinyfish_enabled,
        }

    # ------------------------------------------------------------------ runs
    def _create_pipeline_run(
        self,
        trigger: str,
        *,
        status: str = "running",
        stage: str = "ingest",
        metadata: Mapping[str, Any] | None = None,
    ) -> str:
        run_id = f"pipeline_{uuid.uuid4().hex}"
        self.database.execute(
            """
            INSERT INTO pipeline_runs (
                id, trigger, ingestion_run_id, status, current_stage,
                started_at, completed_at, stage_results, error_summary, metadata
            ) VALUES (?, ?, NULL, ?, ?, ?, NULL, '{}', NULL, ?)
            """,
            [
                run_id,
                trigger,
                status,
                stage,
                utc_now(),
                _json_dump(
                    {
                        "demo": self.settings.voc_demo_mode,
                        **dict(metadata or {}),
                    }
                ),
            ],
        )
        return run_id

    def _update_pipeline_run(
        self,
        run_id: str,
        *,
        status: str,
        stage: str,
        stage_results: Mapping[str, Any] | None = None,
        error_summary: str | None = None,
        ingestion_run_id: str | None = None,
    ) -> None:
        completed = utc_now() if status in {"completed", "partial", "failed"} else None
        self.database.execute(
            """
            UPDATE pipeline_runs SET status = ?, current_stage = ?, completed_at = ?,
                stage_results = ?, error_summary = ?,
                ingestion_run_id = coalesce(?, ingestion_run_id)
            WHERE id = ?
            """,
            [
                status,
                stage,
                completed,
                _json_dump(dict(stage_results or {})),
                error_summary,
                ingestion_run_id,
                run_id,
            ],
        )

    def _execute_pipeline(
        self,
        *,
        trigger: str,
        ingest: Callable[[], Mapping[str, Any]],
        post_classify: Callable[[], Mapping[str, Any]] | None = None,
        coalesce_if_busy: bool = True,
        queued_run_id: str | None = None,
    ) -> RunResponse:
        # Elect one writer before waiting on the serialized pipeline lock. This
        # lets concurrent HTTP requests observe and return the active run instead
        # of queueing a duplicate pipeline that starts as soon as the first ends.
        while True:
            with self._run_state_lock:
                active_run_id = self._active_run_id
                if active_run_id is None:
                    self._pipeline_lock.acquire()
                    try:
                        # A write pipeline performs classification and publish
                        # explicitly below. Initialize only the schema here so
                        # the first write request cannot pay for startup
                        # hydration and then repeat the same work.
                        if not self._initialized:
                            self.repository.initialize()
                            self._initialized = True
                        self._hydrated = True
                        if queued_run_id is None:
                            run_id = self._create_pipeline_run(trigger)
                        else:
                            queued = self.database.query_one(
                                "SELECT status FROM pipeline_runs WHERE id = ?",
                                [queued_run_id],
                            )
                            if queued is None:
                                raise ValueError("queued pipeline run does not exist")
                            if str(queued["status"]) != "queued":
                                existing = self.get_run(queued_run_id)
                                assert existing is not None
                                self._pipeline_lock.release()
                                return existing
                            run_id = queued_run_id
                            self._update_pipeline_run(
                                run_id,
                                status="running",
                                stage="ingest",
                            )
                    except BaseException:
                        self._pipeline_lock.release()
                        raise
                    self._active_run_id = run_id
                    break
            active = self.get_run(active_run_id)
            if active is not None and coalesce_if_busy:
                return active
            if active is not None:
                # File uploads are unique work and must never disappear behind
                # an active scheduled run. Wait for the elected writer, then
                # retry the election and execute this import exactly once.
                with self._pipeline_lock:
                    pass
                continue
            # Defensive recovery for an impossible/damaged dangling in-memory
            # run ID. Only the thread that observed that same ID clears it.
            with self._run_state_lock:
                if self._active_run_id == active_run_id:
                    self._active_run_id = None

        results: dict[str, Any] = {}
        try:
            results["ingest"] = dict(ingest())
            results["dedupe"] = {
                "exact_replays_marked": self.repository.mark_exact_content_duplicates()
            }
            self._update_pipeline_run(
                run_id,
                status="running",
                stage="classify",
                stage_results=results,
                ingestion_run_id=results["ingest"].get("ingestion_run_id"),
            )
            results["classify"] = self._classify_pending()
            if post_classify is not None:
                results["post_classify"] = dict(post_classify())
            self._update_pipeline_run(
                run_id,
                status="running",
                stage="aggregate",
                stage_results=results,
            )
            results["publish"] = self._rebuild_insights(pipeline_run_id=run_id)
            classification_failures = int(results["classify"].get("failed", 0))
            classified = int(results["classify"].get("analyzed", 0))
            ingestion_failures = int(results["ingest"].get("failed", 0))
            if classification_failures and classified == 0:
                final_status = "failed"
            elif classification_failures or ingestion_failures:
                final_status = "partial"
            else:
                final_status = "completed"
            error_summary = (
                f"Classification failed for {classification_failures} feedback item(s)."
                if classification_failures
                else f"Ingestion failed for {ingestion_failures} feedback item(s)."
                if ingestion_failures
                else None
            )
            self._update_pipeline_run(
                run_id,
                status=final_status,
                stage="published",
                stage_results=results,
                error_summary=error_summary,
            )
        except Exception as exc:
            failure_stage = (
                "publish"
                if "classify" in results
                else "classify"
                if "ingest" in results
                else "ingest"
            )
            # Provider exceptions can contain request fragments or credentials;
            # durable run status exposes only the exception class and stage.
            error = f"Pipeline {failure_stage} failed ({type(exc).__name__})."
            self._update_pipeline_run(
                run_id,
                status="failed",
                stage="failed",
                stage_results=results,
                error_summary=error,
            )
        finally:
            with self._run_state_lock:
                self._active_run_id = None
            self._pipeline_lock.release()
        result = self.get_run(run_id)
        assert result is not None
        return result

    def get_run(self, run_id: str) -> RunResponse | None:
        if not self._initialized:
            self.initialize(seed_demo=False)
        row = self.database.query_one("SELECT * FROM pipeline_runs WHERE id = ?", [run_id])
        if row is None:
            return None
        results = _json_load(row.get("stage_results"), {})
        results = results if isinstance(results, dict) else {}
        ingest = results.get("ingest", {}) if isinstance(results.get("ingest"), dict) else {}
        published_at = row.get("completed_at") if row.get("current_stage") == "published" else None
        return RunResponse(
            pipeline_run_id=str(row["id"]),
            status=row["status"],
            stage=row.get("current_stage"),
            started_at=row.get("started_at"),
            completed_at=row.get("completed_at"),
            records_seen=int(ingest.get("seen", 0)),
            records_inserted=int(ingest.get("inserted", 0)),
            records_skipped=int(ingest.get("skipped", 0)),
            records_failed=int(ingest.get("failed", 0)),
            published_at=published_at,
            error_summary=row.get("error_summary"),
        )

    # --------------------------------------------------------------- ingestion
    def _ingest_raw_rows(
        self,
        rows: Sequence[RawFeedback],
        *,
        source_name: str,
        source_file: str | Path | None,
    ) -> dict[str, Any]:
        if not rows:
            return {"seen": 0, "inserted": 0, "skipped": 0, "failed": 0}
        group = rows[0].source_group
        run = self.repository.create_ingestion_run(
            connector="canonical_jsonl",
            source_name=source_name,
            source_file=source_file,
            metadata={"synthetic": all(row.is_synthetic for row in rows)},
        )
        seen = inserted = skipped = failed = 0
        last_record_at: datetime | None = None
        for raw in rows:
            seen += 1
            try:
                item = normalize_raw_feedback(
                    raw,
                    ingestion_run_id=run.id,
                    source_name=source_name,
                    settings=self.settings,
                )
                if self.repository.insert_feedback(item):
                    inserted += 1
                else:
                    skipped += 1
                at = item.occurred_at or item.observed_at
                last_record_at = max(last_record_at, at) if last_record_at else at
            except Exception as exc:
                failed += 1
                self.repository.record_quarantine(
                    ingestion_run_id=run.id,
                    source_name=source_name,
                    source_file=source_file,
                    row_number=seen,
                    reason_code="normalization_error",
                    reason_message=f"{type(exc).__name__}: {exc}"[:500],
                    masked_sample={"source_external_id": raw.source_external_id},
                )
        status = (
            IngestionRunStatus.PARTIAL
            if failed and (inserted or skipped)
            else IngestionRunStatus.FAILED
            if failed
            else IngestionRunStatus.COMPLETED
        )
        self.repository.finish_ingestion_run(
            run.id,
            status=status,
            counts=WriteCounts(
                seen=seen,
                inserted=inserted,
                skipped=skipped,
                failed=failed,
            ),
            source_group=FeedbackSourceGroup(group.value),
            last_record_at=last_record_at,
        )
        return {
            "ingestion_run_id": run.id,
            "seen": seen,
            "inserted": inserted,
            "skipped": skipped,
            "failed": failed,
        }

    @staticmethod
    def _canonical_rows(content: bytes, filename: str) -> list[RawFeedback]:
        suffix = Path(filename).suffix.lower()
        text = content.decode("utf-8-sig")
        values: list[object]
        if suffix in {".jsonl", ".ndjson"}:
            values = [json.loads(line) for line in text.splitlines() if line.strip()]
        elif suffix == ".json":
            payload = json.loads(text)
            if isinstance(payload, dict):
                payload = payload.get("records") or payload.get("items") or [payload]
            values = payload if isinstance(payload, list) else [payload]
        else:
            raise ValueError("generic canonical imports require JSON or JSONL")
        return [RawFeedback.model_validate(value) for value in values]

    def _with_temp_upload(
        self,
        *,
        filename: str,
        content: bytes,
        callback: Callable[[Path], Any],
    ) -> Any:
        name = _safe_filename(filename)
        suffix = Path(name).suffix.lower()
        with tempfile.TemporaryDirectory(prefix="guardian-voc-") as directory:
            path = Path(directory) / f"upload{suffix}"
            path.write_bytes(content)
            return callback(path)

    def preview_import(
        self,
        *,
        filename: str,
        content: bytes,
        profile: str,
        vietnamese_only: bool = False,
        mapping: Mapping[str, str | None] | None = None,
    ) -> dict[str, Any]:
        if profile == "generic":
            try:
                rows = self._canonical_rows(content, filename)
            except (UnicodeDecodeError, json.JSONDecodeError, ValidationError, ValueError) as exc:
                return {
                    "profile": profile,
                    "filename": _safe_filename(filename),
                    "total_rows": 0,
                    "valid_rows": 0,
                    "invalid_rows": 1,
                    "samples": [],
                    "issues": [{"code": "validation_error", "message": str(exc)[:500]}],
                }
            return {
                "profile": profile,
                "filename": _safe_filename(filename),
                "total_rows": len(rows),
                "valid_rows": len(rows),
                "invalid_rows": 0,
                "samples": [
                    mask_preview_mapping(
                        {
                            "source_group": row.source_group.value,
                            "source_platform": row.source_platform,
                            "brand": row.brand.value if row.brand else None,
                            "occurred_at": row.occurred_at.isoformat() if row.occurred_at else None,
                            "text": row.text,
                        },
                        text_limit=self.settings.voc_preview_text_limit,
                    )
                    for row in rows[:5]
                ],
                "issues": [],
            }
        name = _safe_filename(filename)
        profile_obj = self._import_profile(profile, mapping)
        value = self._with_temp_upload(
            filename=filename,
            content=content,
            callback=lambda path: preview_import(
                path,
                profile_obj,
                settings=self.settings,
                vietnamese_only=vietnamese_only,
            ),
        )
        payload = value.model_dump(mode="json")
        payload["filename"] = name
        payload["duplicate_file"] = self.is_imported_file(profile=profile, content=content)
        return payload

    @staticmethod
    def _import_profile(
        profile: str, mapping: Mapping[str, str | None] | None = None
    ) -> MappingProfile:
        base = get_profile(profile)
        if not mapping:
            return base
        canonical = {
            "reviewer_name": "author_id",
            "review_body": "text",
            "star_rating": "rating",
            "product_url": "source_url",
            "product_name": "product_name",
            "review_id": "source_external_id",
            "review_date": "occurred_at",
        }
        fields = {
            canonical[key]: (str(value),)
            for key, value in mapping.items()
            if key in canonical and value
        }
        if "text" not in fields:
            raise ValueError("review_body mapping is required")
        return base.with_overrides(fields=fields)

    def detect_import_mapping(
        self, *, filename: str, content: bytes, profile: str
    ) -> dict[str, Any]:
        """Ask the configured model to map only a bounded spreadsheet sample."""

        get_profile(profile)
        if not self.settings.ai_api_key:
            raise ValueError("AI_API_KEY is required for automatic column detection")

        def sample(path: Path) -> tuple[list[str], list[dict[str, Any]]]:
            return read_import_sample(path, settings=self.settings, limit=5)

        columns, rows = self._with_temp_upload(
            filename=filename, content=content, callback=sample
        )
        if not columns or not rows:
            raise ValueError("the spreadsheet has no data rows")
        provider = OpenAICompatibleProvider(
            base_url=self.settings.ai_base_url,
            api_key=self.settings.ai_api_key,
            model=self.settings.ai_model,
            timeout_seconds=self.settings.ai_request_timeout_seconds,
        )

        async def run() -> ImportColumnMapping:
            try:
                return await provider.detect_import_columns(columns=columns, sample_rows=rows)
            finally:
                await provider.aclose()

        detected = asyncio.run(run())
        mapping = detected.model_dump()
        preview = self.preview_import(
            filename=filename,
            content=content,
            profile=profile,
            vietnamese_only=False,
            mapping=mapping,
        )
        preview["mapping"] = mapping
        preview["sample_rows_sent"] = min(5, len(rows))
        preview["duplicate_file"] = self.is_imported_file(
            profile=profile, content=content
        )
        return preview

    def is_imported_file(self, *, profile: str, content: bytes) -> bool:
        source_name = get_profile(profile).source_name
        digest = hashlib.sha256(content).hexdigest()
        return self.database.query_one(
            """
            SELECT 1 AS found
            FROM imported_files files
            JOIN ingestion_runs runs ON runs.id = files.last_ingestion_run_id
            WHERE files.source_name = ? AND files.file_sha256 = ?
              AND runs.status IN ('completed', 'partial')
            """,
            [source_name, digest],
        ) is not None

    def import_history(self, *, limit: int = 20) -> list[dict[str, Any]]:
        return self.database.query(
            """
            SELECT files.source_name AS profile, files.filename, files.file_sha256,
                   files.first_imported_at, files.last_seen_at, files.first_ingestion_run_id
            FROM imported_files files
            JOIN ingestion_runs runs ON runs.id = files.last_ingestion_run_id
            WHERE runs.status IN ('completed', 'partial')
            ORDER BY first_imported_at DESC LIMIT ?
            """,
            [limit],
        )

    def queue_import_bytes(
        self,
        *,
        filename: str,
        content: bytes,
        profile: str,
        vietnamese_only: bool = False,
        mapping: Mapping[str, str | None] | None = None,
    ) -> RunResponse:
        """Validate an upload and persist its pipeline run before background work."""

        name = _safe_filename(filename)
        if len(content) > self.settings.voc_max_import_bytes:
            raise ValueError("import exceeds the configured size limit")
        if profile == "generic":
            # Validate the canonical trust boundary before returning 202-like
            # queued semantics. The background worker reparses the immutable
            # bytes and remains the only code path that writes feedback.
            self._canonical_rows(content, name)
        else:
            self._import_profile(profile, mapping)
            if self.is_imported_file(profile=profile, content=content):
                raise ValueError("this exact file has already been imported")
        if not self._initialized:
            with self._pipeline_lock:
                if not self._initialized:
                    self.repository.initialize()
                    self._initialized = True
        run_id = self._create_pipeline_run(
            "import",
            status="queued",
            stage="queued",
            metadata={
                "filename": name,
                "profile": profile,
                "vietnamese_only": vietnamese_only,
                "content_sha256": hashlib.sha256(content).hexdigest(),
                "column_mapping": dict(mapping or {}),
            },
        )
        queued = self.get_run(run_id)
        assert queued is not None
        return queued

    def execute_queued_import(
        self,
        *,
        pipeline_run_id: str,
        filename: str,
        content: bytes,
        profile: str,
        vietnamese_only: bool = False,
        mapping: Mapping[str, str | None] | None = None,
    ) -> RunResponse:
        """Adopt one durable queued run and execute its upload exactly once."""

        return self._execute_import_bytes(
            filename=filename,
            content=content,
            profile=profile,
            vietnamese_only=vietnamese_only,
            mapping=mapping,
            queued_run_id=pipeline_run_id,
        )

    def import_bytes(
        self,
        *,
        filename: str,
        content: bytes,
        profile: str,
        vietnamese_only: bool = False,
        period_start: date | str | None = None,
        period_end: date | str | None = None,
        mapping: Mapping[str, str | None] | None = None,
    ) -> RunResponse:
        return self._execute_import_bytes(
            filename=filename,
            content=content,
            profile=profile,
            vietnamese_only=vietnamese_only,
            period_start=period_start,
            period_end=period_end,
            mapping=mapping,
        )

    def _execute_import_bytes(
        self,
        *,
        filename: str,
        content: bytes,
        profile: str,
        vietnamese_only: bool = False,
        period_start: date | str | None = None,
        period_end: date | str | None = None,
        queued_run_id: str | None = None,
        mapping: Mapping[str, str | None] | None = None,
    ) -> RunResponse:
        name = _safe_filename(filename)

        def ingest() -> Mapping[str, Any]:
            if profile == "generic":
                rows = self._canonical_rows(content, name)
                return self._ingest_raw_rows(
                    rows,
                    source_name="generic",
                    source_file=name,
                )

            def run_connector(path: Path) -> dict[str, Any]:
                profile_obj = self._import_profile(profile, mapping)
                connector = FileImportConnector(
                    path,
                    profile_obj,
                    settings=self.settings,
                    vietnamese_only=vietnamese_only,
                    period_start=period_start,
                    period_end=period_end,
                )
                result = asyncio.run(
                    self.repository.ingest_connector(
                        connector,
                        connector_name="file_import",
                        source_name=profile_obj.source_name,
                        source_group=profile_obj.source_group,
                        source_file=name,
                        raise_on_error=False,
                    )
                )
                return {
                    "ingestion_run_id": result.id,
                    "seen": result.records_seen,
                    "inserted": result.records_inserted,
                    "skipped": result.records_skipped,
                    "failed": result.records_failed,
                }

            return self._with_temp_upload(filename=name, content=content, callback=run_connector)

        return self._execute_pipeline(
            trigger="import",
            ingest=ingest,
            coalesce_if_busy=False,
            queued_run_id=queued_run_id,
        )

    def import_file(
        self,
        path: Path,
        *,
        profile: str,
        vietnamese_only: bool = False,
        period_start: date | str | None = None,
        period_end: date | str | None = None,
    ) -> RunResponse:
        return self.import_bytes(
            filename=path.name,
            content=path.read_bytes(),
            profile=profile,
            vietnamese_only=vietnamese_only,
            period_start=period_start,
            period_end=period_end,
        )

    def seed_demo(self, *, reset: bool = False) -> dict[str, Any]:
        if reset:
            self._reset_database()
        else:
            self.initialize(seed_demo=False)

        def ingest() -> Mapping[str, Any]:
            totals = {"seen": 0, "inserted": 0, "skipped": 0, "failed": 0}
            first_run: str | None = None
            for path in sorted((FIXTURES / "raw").glob("*.jsonl")):
                rows = self._canonical_rows(path.read_bytes(), path.name)
                result = self._ingest_raw_rows(rows, source_name=path.stem, source_file=path)
                first_run = first_run or result.get("ingestion_run_id")
                for key in totals:
                    totals[key] += int(result.get(key, 0))
            totals["ingestion_run_id"] = first_run
            self.database.execute(
                """
                INSERT INTO business_events VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (event_id) DO NOTHING
                """,
                [
                    "demo-mid-year-glow",
                    "campaign",
                    "Mid-Year Glow campaign started",
                    datetime(2026, 7, 6, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh")),
                    None,
                    "ecommerce",
                    "beauty_personal_care",
                    "Synthetic context only; not confirmed causality.",
                ],
            )
            return totals

        run = self._execute_pipeline(trigger="seed_demo", ingest=ingest)
        return run.model_dump(mode="json")

    def run_all(self) -> RunResponse:
        def ingest() -> Mapping[str, Any]:
            totals = {"seen": 0, "inserted": 0, "skipped": 0, "failed": 0}
            first_run: str | None = None
            inbox = Path(self.settings.voc_inbox_dir)
            inbox.mkdir(parents=True, exist_ok=True)
            for path in sorted(item for item in inbox.glob("*/*") if item.is_file()):
                profile = path.parent.name
                if profile == "generic":
                    result = self._ingest_raw_rows(
                        self._canonical_rows(path.read_bytes(), path.name),
                        source_name="generic",
                        source_file=path,
                    )
                else:
                    profile_obj = get_profile(profile)
                    connector = FileImportConnector(path, profile_obj, settings=self.settings)
                    run = asyncio.run(
                        self.repository.ingest_connector(
                            connector,
                            connector_name="file_import",
                            source_name=profile_obj.source_name,
                            source_group=profile_obj.source_group,
                            source_file=path,
                            raise_on_error=False,
                        )
                    )
                    result = {
                        "ingestion_run_id": run.id,
                        "seen": run.records_seen,
                        "inserted": run.records_inserted,
                        "skipped": run.records_skipped,
                        "failed": run.records_failed,
                    }
                first_run = first_run or result.get("ingestion_run_id")
                for key in ("seen", "inserted", "skipped", "failed"):
                    totals[key] += int(result.get(key, 0))
            totals["ingestion_run_id"] = first_run
            return totals

        return self._execute_pipeline(trigger="scheduled", ingest=ingest)

    def crawl(self, *, keyword: str) -> RunResponse:
        def ingest() -> Mapping[str, Any]:
            if not self.settings.tinyfish_enabled and not self.settings.serp_api_key:
                raise RuntimeError(
                    "No live search provider is configured; the offline demo remains available"
                )
            connector = LiveSocialCrawlerConnector(
                settings=self.settings,
                keywords=(keyword.strip(),),
            )
            result = asyncio.run(
                self.repository.ingest_connector(
                    connector,
                    connector_name="public_social",
                    source_name=f"social_{keyword.strip().lower()}",
                    source_group=FeedbackSourceGroup.SOCIAL,
                    raise_on_error=False,
                )
            )
            return {
                "ingestion_run_id": result.id,
                "seen": result.records_seen,
                "inserted": result.records_inserted,
                "skipped": result.records_skipped,
                "failed": result.records_failed,
            }

        return self._execute_pipeline(trigger="crawl", ingest=ingest)

    def run_live_collection(
        self,
        *,
        source_ids: Sequence[str] | None = None,
        pages_per_query: int | None = None,
        fetch_limit: int | None = None,
        extraction_limit: int | None = None,
        lookback_days: int | None = None,
        refresh: bool | None = None,
    ) -> RunResponse:
        """Run the strict Serp → TinyFish → OpenAI acquisition flow once.

        All stages share this service's DuckDB handle and pipeline lock. Search
        snippets stay in the discovery audit; only strict page-extracted,
        Vietnamese customer units cross into feedback and current-model
        classification. Existing discovery, fetch, extraction, and feedback
        identities make overlapping collection windows idempotent.
        """

        from guardian_voc.data_layer import LiveDataLayer

        local_today = datetime.now(ZoneInfo(self.settings.voc_business_timezone)).date()
        selected_source_ids = tuple(
            source_ids or self.settings.voc_live_collection_source_ids
        )
        selected_lookback_days = (
            lookback_days
            if lookback_days is not None
            else self.settings.voc_live_collection_lookback_days
        )
        period_start = local_today - timedelta(days=selected_lookback_days - 1)
        layer = LiveDataLayer(
            settings=self.settings,
            database=self.database,
            period_start=period_start,
            period_end=local_today,
        )
        state: dict[str, Any] = {}

        def ingest() -> Mapping[str, Any]:
            manifest = asyncio.run(
                layer.run(
                    source_ids=selected_source_ids,
                    pages_per_query=(
                        pages_per_query
                        if pages_per_query is not None
                        else self.settings.voc_live_collection_pages_per_query
                    ),
                    fetch_limit=(
                        fetch_limit
                        if fetch_limit is not None
                        else self.settings.voc_live_collection_fetch_limit
                    ),
                    extraction_limit=(
                        extraction_limit
                        if extraction_limit is not None
                        else self.settings.voc_live_collection_extraction_limit
                    ),
                    extract_public=True,
                    refresh=(
                        refresh
                        if refresh is not None
                        else self.settings.voc_live_collection_refresh
                    ),
                )
            )
            ownership = layer.apply_verified_source_ownership()
            stages = dict(manifest.get("stages") or {})
            state["stages"] = stages
            extract = stages.get("extract")
            extract = extract if isinstance(extract, Mapping) else {}
            discover = stages.get("discover")
            discover = discover if isinstance(discover, Mapping) else {}
            fetch = stages.get("fetch")
            fetch = fetch if isinstance(fetch, Mapping) else {}
            discovery_errors = discover.get("errors")
            discovery_error_count = (
                len(discovery_errors) if isinstance(discovery_errors, list) else 0
            )
            return {
                "ingestion_run_id": extract.get("ingestion_run_id"),
                "seen": int(extract.get("accepted_units") or 0),
                "inserted": int(extract.get("inserted") or 0),
                "skipped": int(extract.get("skipped") or 0),
                "failed": int(extract.get("failed") or 0) + discovery_error_count,
                "collection": {
                    "period_start": period_start.isoformat(),
                    "period_end": local_today.isoformat(),
                    "source_ids": list(
                        selected_source_ids
                    ),
                    "searches": int(discover.get("searches") or 0),
                    "discovery_errors": discovery_error_count,
                    "serp_available_before": discover.get("available_before"),
                    "serp_available_after": discover.get("available_after"),
                    "discovered": int(discover.get("unique_results") or 0),
                    "fetch_attempted": int(fetch.get("attempted") or 0),
                    "extraction_attempted": int(extract.get("attempted") or 0),
                    "ownership_updates": int(ownership.get("updated") or 0),
                },
            }

        def post_classify() -> Mapping[str, Any]:
            manifest = layer.build_manifest(stages=state.get("stages") or {})
            counts = manifest.get("counts")
            counts = counts if isinstance(counts, Mapping) else {}
            return {
                "feedback_items": int(counts.get("feedback_items") or 0),
                "analyzed_feedback_items": int(
                    counts.get("analyzed_feedback_items") or 0
                ),
                "guardian_relevant_analysis_rows": int(
                    counts.get("guardian_relevant_analysis_rows") or 0
                ),
                "time_eligible_real_feedback_items": int(
                    counts.get("time_eligible_real_feedback_items") or 0
                ),
            }

        return self._execute_pipeline(
            trigger="scheduled_full_flow",
            ingest=ingest,
            post_classify=post_classify,
        )

    def _ingest_marketplace_connector(
        self,
        connector: ShopeeReviewConnector | LazadaReviewConnector,
        *,
        platform: str,
    ) -> dict[str, Any]:
        """Run one authorized seller connector through the canonical pipeline."""

        source_name = f"guardian_{platform}_api"

        def ingest() -> Mapping[str, Any]:
            result = asyncio.run(
                self.repository.ingest_connector(
                    connector,
                    connector_name="marketplace_api",
                    source_name=source_name,
                    source_group=FeedbackSourceGroup.MARKETPLACE,
                    metadata={
                        "platform": platform,
                        "authorization_scope": "guardian_owned_shop",
                    },
                    raise_on_error=False,
                )
            )
            return {
                "ingestion_run_id": result.id,
                "seen": result.records_seen,
                "inserted": result.records_inserted,
                "skipped": result.records_skipped,
                "failed": result.records_failed,
                "reconciliation": connector.manifest.as_dict(),
            }

        run = self._execute_pipeline(
            trigger=f"marketplace_{platform}",
            ingest=ingest,
        )
        manifest: MarketplaceReconciliationManifest = connector.manifest
        source_id: str | None
        if platform == "lazada":
            source_id = "guardian_lazada"
        else:
            shop_id = getattr(getattr(connector, "credentials", None), "shop_id", None)
            source_id = {
                152872415: "guardian_shopee_hcm",
                412741369: "guardian_shopee_hn",
            }.get(shop_id)
        reconciliation = manifest.as_dict()
        source_complete = bool(
            manifest.item_discovery_requested
            and manifest.item_discovery_complete
            and all(
                item.pagination_complete and item.reconciliation == "matched"
                for item in manifest.items.values()
            )
        )
        if source_id is not None:
            self.database.execute(
                """
                INSERT INTO source_checkpoints VALUES (?, ?, ?, ?)
                ON CONFLICT (source_id, checkpoint_key) DO UPDATE SET
                    checkpoint_value = excluded.checkpoint_value,
                    updated_at = excluded.updated_at
                """,
                [
                    source_id,
                    "review_reconciliation",
                    _json_dump(
                        {
                            "source_complete": source_complete,
                            "platform": platform,
                            "reconciliation": reconciliation,
                        }
                    ),
                    utc_now(),
                ],
            )
        return {
            "run": run.model_dump(mode="json"),
            "source_id": source_id,
            "source_complete": source_complete,
            "reconciliation": reconciliation,
        }

    def ingest_shopee_reviews(
        self,
        *,
        partner_id: int,
        partner_key: str,
        access_token: str,
        shop_id: int,
        item_ids: Sequence[int | str] = (),
        discover_all_items: bool = False,
        owned_shop_authorized: bool,
        page_size: int = 100,
        max_pages_per_item: int = 10_000,
        lookback_days: int = 365,
        vietnamese_only: bool = True,
    ) -> dict[str, Any]:
        """Ingest reviews available to Guardian's Shopee seller token."""

        connector = ShopeeReviewConnector(
            ShopeeCredentials(
                partner_id=partner_id,
                partner_key=partner_key,
                access_token=access_token,
                shop_id=shop_id,
            ),
            item_ids=item_ids,
            discover_all_items=discover_all_items,
            owned_shop_authorized=owned_shop_authorized,
            page_size=page_size,
            max_pages_per_item=max_pages_per_item,
            lookback_days=lookback_days,
            vietnamese_only=vietnamese_only,
        )
        return self._ingest_marketplace_connector(connector, platform="shopee")

    def ingest_lazada_reviews(
        self,
        *,
        app_key: str,
        app_secret: str,
        access_token: str,
        item_ids: Sequence[int | str] = (),
        discover_all_items: bool = False,
        owned_shop_authorized: bool,
        page_size: int = 100,
        max_pages_per_item: int = 10_000,
        lookback_days: int = 365,
        vietnamese_only: bool = True,
    ) -> dict[str, Any]:
        """Ingest reviews available to Guardian's Lazada seller token."""

        connector = LazadaReviewConnector(
            LazadaCredentials(
                app_key=app_key,
                app_secret=app_secret,
                access_token=access_token,
            ),
            item_ids=item_ids,
            discover_all_items=discover_all_items,
            owned_shop_authorized=owned_shop_authorized,
            page_size=page_size,
            max_pages_per_item=max_pages_per_item,
            lookback_days=lookback_days,
            vietnamese_only=vietnamese_only,
        )
        return self._ingest_marketplace_connector(connector, platform="lazada")

    # ------------------------------------------------------------ classification
    def _fixture_labels(self) -> dict[str, dict[str, Any]]:
        if self._labels is not None:
            return self._labels
        labels: dict[str, dict[str, Any]] = {}
        for path in (
            FIXTURES / "labels" / "cached_analyses.jsonl",
            FIXTURES / "demo_increment" / "cached_analyses.jsonl",
        ):
            if not path.is_file():
                continue
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    row = json.loads(line)
                    labels[str(row["source_external_id"])] = row
        self._labels = labels
        return labels

    @staticmethod
    def _classification_request(row: Mapping[str, Any]) -> ClassificationRequest:
        brand_candidates = tuple(str(item) for item in (row.get("brand_candidates") or []))
        if not brand_candidates and row.get("brand"):
            brand_candidates = (str(row["brand"]),)
        return ClassificationRequest(
            content_hash=str(row["content_hash"]),
            text_redacted=str(row["text_redacted"]),
            trusted_metadata=TrustedSourceMetadata(
                source_group=str(row["source_group"]),
                source_platform=str(row["source_platform"]),
                visibility=str(row["visibility"]),
                source_fixed_brand=str(row["brand"]) if row.get("brand") else None,
                product_category=row.get("product_category"),
                language=row.get("language"),
            ),
            brand_candidates=brand_candidates,
        )

    def _persist_analysis(
        self,
        feedback_id: str,
        result: ClassificationResult,
        *,
        model_version: str,
        review_required: bool,
        prompt_version: str = ITEM_CLASSIFIER_PROMPT_VERSION,
    ) -> None:
        now = utc_now()
        raw_result = result.model_dump(mode="json")
        self.database.execute(
            """
            INSERT INTO feedback_analyses (
                feedback_id, is_relevant, primary_brand, mentioned_brands,
                brand_attribution_confidence, brand_evidence_span,
                experience_subject, primary_topic, subtopic, intent, sentiment,
                sentiment_score, urgency, customer_stated_reason, journey_stage,
                evidence_span, confidence, model_version, prompt_version,
                taxonomy_version, raw_result, analyzed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (feedback_id) DO UPDATE SET
                is_relevant = excluded.is_relevant,
                primary_brand = excluded.primary_brand,
                mentioned_brands = excluded.mentioned_brands,
                brand_attribution_confidence = excluded.brand_attribution_confidence,
                brand_evidence_span = excluded.brand_evidence_span,
                experience_subject = excluded.experience_subject,
                primary_topic = excluded.primary_topic,
                subtopic = excluded.subtopic,
                intent = excluded.intent,
                sentiment = excluded.sentiment,
                sentiment_score = excluded.sentiment_score,
                urgency = excluded.urgency,
                customer_stated_reason = excluded.customer_stated_reason,
                journey_stage = excluded.journey_stage,
                evidence_span = excluded.evidence_span,
                confidence = excluded.confidence,
                model_version = excluded.model_version,
                prompt_version = excluded.prompt_version,
                taxonomy_version = excluded.taxonomy_version,
                raw_result = excluded.raw_result,
                analyzed_at = excluded.analyzed_at
            """,
            [
                feedback_id,
                result.is_relevant,
                result.primary_brand.value if result.primary_brand else None,
                [brand.value for brand in result.mentioned_brands],
                result.brand_attribution_confidence,
                result.brand_evidence_span,
                result.experience_subject.value,
                result.primary_topic.value,
                result.subtopic,
                result.intent.value,
                result.sentiment.value,
                result.sentiment_score,
                result.urgency.value,
                result.customer_stated_reason,
                result.journey_stage.value,
                result.evidence_span,
                result.confidence,
                model_version,
                prompt_version,
                "voc-v1",
                _json_dump(raw_result),
                now,
            ],
        )
        self.database.execute(
            "UPDATE feedback_items SET analysis_status = ? WHERE feedback_id = ?",
            ["low_confidence" if review_required else "completed", feedback_id],
        )

    def _record_classification_failure(
        self,
        row: Mapping[str, Any],
        *,
        model_version: str,
        error_code: str,
        failure_type: str = "classification",
    ) -> None:
        """Persist a text-free, secret-free classifier failure audit."""

        feedback_id = str(row["feedback_id"])
        prompt_version = ITEM_CLASSIFIER_PROMPT_VERSION
        digest = hashlib.sha256(
            "\0".join(
                (
                    feedback_id,
                    model_version,
                    prompt_version,
                    failure_type,
                    error_code,
                )
            ).encode("utf-8")
        ).hexdigest()
        self.database.execute(
            """
            INSERT INTO classification_failures VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (failure_id) DO UPDATE SET
                occurred_at = excluded.occurred_at,
                metadata = excluded.metadata
            """,
            [
                f"classification_failure_{digest[:32]}",
                feedback_id,
                model_version,
                prompt_version,
                failure_type,
                error_code[:120],
                utc_now(),
                _json_dump(
                    {
                        "source_group": row.get("source_group"),
                        "source_platform": row.get("source_platform"),
                        "contains_feedback_text": False,
                    }
                ),
            ],
        )

    def _classify_pending(self) -> dict[str, int]:
        # The provider already performs one transport retry and one structured-
        # output repair attempt. A malformed result after that boundary is a
        # record-level quarantine, not a reason to fail every future scheduler
        # cycle. Other failures retain one later pipeline retry.
        # A prompt/provider contract upgrade gets one fresh attempt while old
        # failures remain in the audit table. Current-version malformed output
        # still fails closed and is skipped on later scheduler cycles.
        self.database.execute(
            """
            UPDATE feedback_items
            SET analysis_status = 'pending'
            WHERE analysis_status = 'skipped'
              AND duplicate_of IS NULL
              AND NOT EXISTS (
                  SELECT 1 FROM feedback_analyses fa
                  WHERE fa.feedback_id = feedback_items.feedback_id
              )
              AND NOT EXISTS (
                  SELECT 1 FROM classification_failures cf
                  WHERE cf.feedback_id = feedback_items.feedback_id
                    AND cf.prompt_version = ?
              )
            """,
            [ITEM_CLASSIFIER_PROMPT_VERSION],
        )
        exhausted = self.database.query(
            """
            SELECT fi.feedback_id
            FROM feedback_items fi
            LEFT JOIN feedback_analyses fa ON fa.feedback_id = fi.feedback_id
            JOIN classification_failures cf ON cf.feedback_id = fi.feedback_id
            WHERE fa.feedback_id IS NULL
              AND fi.duplicate_of IS NULL
              AND fi.analysis_status <> 'skipped'
              AND cf.prompt_version = ?
            GROUP BY fi.feedback_id
            HAVING count(*) >= 2
                OR bool_or(cf.error_code = 'MalformedProviderResponse')
            """,
            [ITEM_CLASSIFIER_PROMPT_VERSION],
        )
        for row in exhausted:
            self.database.execute(
                "UPDATE feedback_items SET analysis_status = 'skipped' WHERE feedback_id = ?",
                [row["feedback_id"]],
            )
        rows = self.database.query(
            """
            SELECT fi.* FROM feedback_items fi
            LEFT JOIN feedback_analyses fa ON fa.feedback_id = fi.feedback_id
            WHERE fa.feedback_id IS NULL
              AND fi.duplicate_of IS NULL
              AND fi.analysis_status <> 'skipped'
            ORDER BY fi.feedback_id
            """
        )
        labels = self._fixture_labels()
        analyzed = failed = low_confidence = 0
        live_provider: OpenAICompatibleProvider | None = None
        live_runner: asyncio.Runner | None = None
        if self.settings.ai_provider == "openai_compatible":
            live_provider = OpenAICompatibleProvider(
                base_url=self.settings.ai_base_url,
                api_key=self.settings.ai_api_key,
                model=self.settings.ai_model,
                timeout_seconds=self.settings.ai_request_timeout_seconds,
            )
            # HTTPX transports are event-loop bound. Reuse one loop for the
            # entire synchronous batch instead of creating one loop per item.
            live_runner = asyncio.Runner()
        try:
            for row in rows:
                request = self._classification_request(row)
                label = labels.get(str(row.get("source_external_id")))
                metadata_value = _json_load(row.get("sanitized_metadata"), {})
                metadata = metadata_value if isinstance(metadata_value, Mapping) else {}
                inline_label = metadata.get("inline_classification")
                inline_model = _dashboard_text(
                    metadata.get("inline_classification_model")
                )
                inline_prompt_version = _dashboard_text(
                    metadata.get("inline_classification_prompt_version")
                )
                try:
                    if isinstance(inline_label, Mapping):
                        result = ClassificationResult.model_validate(inline_label)
                        result = validate_classification(result, request)
                        model_version = inline_model or self.settings.ai_model
                        prompt_version = (
                            inline_prompt_version or ITEM_CLASSIFIER_PROMPT_VERSION
                        )
                    elif label is not None:
                        payload = dict(label)
                        payload.pop("source_external_id", None)
                        result = ClassificationResult.model_validate(payload)
                        result = validate_classification(result, request)
                        model_version = "cached-fixture-v1"
                        prompt_version = ITEM_CLASSIFIER_PROMPT_VERSION
                    elif live_provider is not None:
                        assert live_runner is not None
                        result = live_runner.run(live_provider.classify(request))
                        model_version = live_provider.model_version
                        prompt_version = ITEM_CLASSIFIER_PROMPT_VERSION
                    else:
                        failed += 1
                        self._record_classification_failure(
                            row,
                            model_version="provider-unconfigured",
                            error_code="classifier_provider_unconfigured",
                            failure_type="configuration",
                        )
                        self.database.execute(
                            "UPDATE feedback_items SET analysis_status = 'failed' WHERE feedback_id = ?",
                            [row["feedback_id"]],
                        )
                        continue
                    result, review_required = apply_low_confidence_policy(
                        result,
                        minimum_confidence=self.settings.voc_classifier_min_confidence,
                    )
                    self._persist_analysis(
                        str(row["feedback_id"]),
                        result,
                        model_version=model_version,
                        prompt_version=prompt_version,
                        review_required=review_required,
                    )
                    analyzed += 1
                    low_confidence += int(review_required)
                except Exception as exc:
                    failed += 1
                    self._record_classification_failure(
                        row,
                        model_version=(
                            live_provider.model_version
                            if live_provider is not None
                            else "cached-fixture-v1"
                        ),
                        error_code=type(exc).__name__,
                    )
                    self.database.execute(
                        "UPDATE feedback_items SET analysis_status = 'failed' WHERE feedback_id = ?",
                        [row["feedback_id"]],
                    )
        finally:
            if live_provider is not None:
                assert live_runner is not None
                try:
                    live_runner.run(live_provider.aclose())
                finally:
                    live_runner.close()
        return {
            "analyzed": analyzed,
            "failed": failed,
            "low_confidence": low_confidence,
            "skipped_after_retry": len(exhausted),
        }

    # --------------------------------------------------------------- analytics
    def _analytics_units(self) -> tuple[AnalyticsUnit, ...]:
        rows = self.database.query(
            """
            SELECT fi.*, fa.is_relevant, fa.primary_brand, fa.mentioned_brands,
                fa.brand_attribution_confidence, fa.brand_evidence_span,
                fa.experience_subject AS analyzed_experience_subject,
                fa.primary_topic, fa.subtopic, fa.intent, fa.sentiment,
                fa.sentiment_score, fa.urgency, fa.customer_stated_reason,
                fa.journey_stage, fa.evidence_span, fa.confidence
            FROM feedback_items fi
            JOIN feedback_analyses fa ON fa.feedback_id = fi.feedback_id
            WHERE fi.duplicate_of IS NULL
            """
        )
        units: list[AnalyticsUnit] = []
        for row in rows:
            resolved = row.get("brand")
            if resolved is None and row.get("primary_brand") is not None:
                span = row.get("brand_evidence_span")
                if (
                    float(row.get("brand_attribution_confidence") or 0)
                    >= self.settings.voc_classifier_min_confidence
                    and isinstance(span, str)
                    and span
                    and span in str(row["text_redacted"])
                ):
                    resolved = row["primary_brand"]
            status = str(row.get("analysis_status"))
            units.append(
                AnalyticsUnit(
                    analytics_unit_id=str(row.get("repost_group_id") or row["feedback_id"]),
                    feedback_id=str(row["feedback_id"]),
                    resolved_brand=resolved,
                    visibility=str(row["visibility"]),
                    source_group=str(row["source_group"]),
                    source_platform=str(row["source_platform"]),
                    experience_subject=str(row["analyzed_experience_subject"]),
                    occurred_at=row.get("occurred_at"),
                    occurred_at_quality=str(row["occurred_at_quality"]),
                    language=row.get("language"),
                    product_category=row.get("product_category"),
                    region=row.get("region"),
                    store=row.get("store"),
                    is_relevant=bool(row["is_relevant"]),
                    analysis_succeeded=status == "completed",
                    analysis_confidence=float(row["confidence"]),
                    primary_topic=str(row["primary_topic"]),
                    subtopic=str(row["subtopic"] or "other"),
                    sentiment=str(row["sentiment"]),
                    urgency=str(row["urgency"]),
                    customer_stated_reason=row.get("customer_stated_reason"),
                    journey_stage=str(row.get("journey_stage") or "unknown"),
                    rating=row.get("rating"),
                )
            )
        return tuple(units)

    def _windows(self):
        return build_analysis_windows(
            self.as_of,
            current_days=self.settings.voc_current_window_days,
            baseline_days=self.settings.voc_baseline_window_days,
            business_timezone=self.settings.voc_business_timezone,
            as_of_date_is_complete=self.settings.voc_demo_mode,
        )

    def _dashboard_windows(
        self,
        dashboard_range: str = "all",
        *,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> AnalysisWindows:
        windows = self._windows()
        if dashboard_range == "all":
            return windows

        zone = ZoneInfo(windows.business_timezone)
        current_end = windows.current_end
        if dashboard_range == "7d":
            current_start = current_end - timedelta(days=7)
        elif dashboard_range == "30d":
            current_start = current_end - timedelta(days=30)
        elif dashboard_range == "1y":
            current_start = current_end - timedelta(days=365)
        elif dashboard_range == "custom":
            if date_from is None or date_to is None:
                raise ValueError("date_from and date_to are required for custom dashboard range")
            if date_to < date_from:
                raise ValueError("date_to must be on or after date_from")
            current_start = datetime.combine(
                date_from,
                datetime.min.time(),
                tzinfo=zone,
            ).astimezone(timezone.utc)
            current_end = datetime.combine(
                date_to + timedelta(days=1),
                datetime.min.time(),
                tzinfo=zone,
            ).astimezone(timezone.utc)
        else:
            raise ValueError("dashboard range must be one of 7d, 30d, 1y, all, or custom")

        duration = current_end - current_start
        baseline_end = current_start
        baseline_start = baseline_end - duration
        days = max(1, duration.days)
        return AnalysisWindows(
            current_start=current_start,
            current_end=current_end,
            baseline_start=baseline_start,
            baseline_end=baseline_end,
            business_timezone=windows.business_timezone,
            current_days=days,
            baseline_days=days,
        )

    def _thresholds(self) -> TrendThresholds:
        return TrendThresholds(
            min_support=self.settings.voc_alert_min_support,
            min_excess=self.settings.voc_alert_min_excess,
            min_growth=self.settings.voc_alert_min_growth,
            min_rate_delta=self.settings.voc_alert_min_rate_delta,
        )

    def _effective_source_status(self, row: Mapping[str, Any]) -> str:
        """Age each connector before aggregating it into a source group."""

        status = str(row.get("status") or "failed")
        if status == "failed":
            return status
        last_success = row.get("last_success_at")
        stale_before = _as_utc(self.as_of) - timedelta(
            hours=self.settings.voc_source_stale_hours
        )
        if (
            not isinstance(last_success, datetime)
            or _as_utc(last_success) < stale_before
        ):
            return "stale"
        return status

    def _health_assessments(self, units: Sequence[AnalyticsUnit]):
        """Build per-platform health snapshots from durable source state.

        Source state is connector-level in the MVP. A failed/stale source group
        therefore qualifies every Guardian platform stratum in that group, so a
        missing feed cannot be mistaken for issue improvement.
        """

        status_rows = self.database.query(
            "SELECT source_group, status, last_success_at FROM source_status"
        )
        by_group: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
        for row in status_rows:
            by_group[str(row["source_group"])].append(row)
        severity = {"healthy": 0, "partial": 1, "stale": 2, "failed": 3}
        grouped: dict[SourceStratum, list[AnalyticsUnit]] = defaultdict(list)
        for unit in units:
            if unit.resolved_brand is Brand.GUARDIAN:
                grouped[
                    SourceStratum(
                        brand=Brand.GUARDIAN,
                        source_group=unit.source_group,
                        source_platform=unit.source_platform,
                        experience_subject=unit.experience_subject,
                    )
                ].append(unit)
        snapshots: list[SourceHealthSnapshot] = []
        current = units_in_window(
            units,
            start=self._windows().current_start,
            end=self._windows().current_end,
            allow_inferred_dates=self.settings.voc_allow_inferred_dates,
        )
        current_counts = Counter(
            (
                unit.source_group,
                unit.source_platform,
                unit.experience_subject,
            )
            for unit in current
            if unit.resolved_brand is Brand.GUARDIAN
        )
        for stratum, records in grouped.items():
            group_state = by_group.get(stratum.source_group.value, [])
            worst = max(
                (self._effective_source_status(row) for row in group_state),
                key=lambda value: severity.get(value, 3),
                default="failed",
            )
            successes = [
                row.get("last_success_at")
                for row in group_state
                if row.get("last_success_at") is not None
            ]
            last_success = max(successes) if successes else None
            known_timestamps = sum(
                unit.occurred_at is not None
                and unit.occurred_at_quality is not OccurredAtQuality.MISSING
                for unit in records
            )
            independent = len(collapse_independent_units(records))
            classifications = sum(unit.analysis_succeeded for unit in records)
            confidence_values = [
                unit.analysis_confidence for unit in records if unit.analysis_succeeded
            ]
            snapshots.append(
                SourceHealthSnapshot(
                    stratum=stratum,
                    status=HealthStatus(worst),
                    last_success_at=last_success,
                    recent_volume=current_counts[
                        (
                            stratum.source_group,
                            stratum.source_platform,
                            stratum.experience_subject,
                        )
                    ],
                    timestamp_coverage=known_timestamps / len(records),
                    duplicate_share=1.0 - independent / len(records),
                    classification_coverage=classifications / len(records),
                    mean_classification_confidence=(
                        sum(confidence_values) / len(confidence_values)
                        if confidence_values
                        else 0.0
                    ),
                )
            )
        return assess_all_sources(snapshots, as_of=self.as_of)

    def _weekly_topic_metrics(
        self,
        units: Sequence[AnalyticsUnit],
        *,
        windows: Any,
        healthy: bool,
    ) -> tuple[WeeklyTopicMetric, ...]:
        zone = ZoneInfo(self.settings.voc_business_timezone)
        baseline = [
            unit
            for unit in units_in_window(
                units,
                start=windows.baseline_start,
                end=windows.baseline_end,
                allow_inferred_dates=self.settings.voc_allow_inferred_dates,
            )
            if unit.resolved_brand is Brand.GUARDIAN
            and unit.is_relevant
            and unit.analysis_succeeded
        ]
        baseline_start = windows.baseline_start.astimezone(zone).date()
        week_rows: dict[date, list[AnalyticsUnit]] = defaultdict(list)
        for unit in baseline:
            local_date = unit.occurred_at.astimezone(zone).date()  # type: ignore[union-attr]
            week_index = (local_date - baseline_start).days // 7
            week_rows[baseline_start + timedelta(days=week_index * 7)].append(unit)
        metrics: list[WeeklyTopicMetric] = []
        for week_start, records in sorted(week_rows.items()):
            counts = Counter(
                unit.primary_topic
                for unit in records
                if unit.sentiment is Sentiment.NEGATIVE
            )
            ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0].value))
            for rank, (topic, negative_count) in enumerate(ranked, start=1):
                metrics.append(
                    WeeklyTopicMetric(
                        week_start=week_start,
                        topic=topic,
                        negative_count=negative_count,
                        denominator=len(records),
                        rank=rank,
                        healthy=healthy,
                    )
                )
        return tuple(metrics)

    def _latest_series_status(self, insight_series_id: str) -> Mapping[str, Any] | None:
        return self.database.query_one(
            """
            SELECT status, reference_observation_id
            FROM insight_status_history
            WHERE insight_series_id = ?
            ORDER BY changed_at DESC, status_event_id DESC
            LIMIT 1
            """,
            [insight_series_id],
        )

    def _delivery_improves(
        self,
        trend: TrendResult,
        *,
        health_assessments: Mapping[str, Any],
    ) -> bool:
        if trend.weighted_current_share is None or trend.weighted_baseline_share is None:
            return False
        groups = tuple(
            sorted(
                {item.stratum.source_group for item in trend.participating_strata},
                key=lambda item: item.value,
            )
        )
        health_keys = [item.stratum.stable_key() for item in trend.participating_strata]
        healthy = bool(groups) and all(
            key in health_assessments and health_assessments[key].healthy
            for key in health_keys
        )
        cohort_signature = "guardian|all_channel|delivery_fulfilment|platform_strata-v1"
        status_history = self._latest_series_status("series-delivery-improving")
        acknowledged_reference = bool(
            status_history is not None
            and status_history.get("status")
            in {InsightStatus.ACKNOWLEDGED.value, InsightStatus.MONITORING.value}
            and status_history.get("reference_observation_id")
        )
        if not self.settings.voc_demo_mode and not acknowledged_reference:
            return False
        reference_id = (
            str(status_history["reference_observation_id"])
            if acknowledged_reference
            else "observation-delivery-monitoring-reference"
        )
        stored_reference = self.database.query_one(
            "SELECT * FROM insight_observations WHERE observation_id = ?",
            [reference_id],
        )
        if stored_reference is None and not self.settings.voc_demo_mode:
            return False
        stored_health = (
            _json_load(stored_reference.get("source_health_snapshot"), {})
            if stored_reference is not None
            else {}
        )
        stored_health = stored_health if isinstance(stored_health, dict) else {}
        reference_groups = tuple(
            SourceGroup(value)
            for value in stored_health.get(
                "source_groups", [group.value for group in SourceGroup]
            )
        )
        reference = InsightObservation(
            observation_id=reference_id,
            insight_series_id="series-delivery-improving",
            cohort_signature=cohort_signature,
            current_share=(
                float(stored_reference["current_share"])
                if stored_reference is not None
                else trend.weighted_baseline_share
            ),
            denominator=(
                int(stored_reference["denominator"])
                if stored_reference is not None
                else trend.baseline_denominator
            ),
            source_groups=reference_groups,
            healthy=bool(stored_health.get("healthy", healthy)),
            classification_succeeded=True,
            observed_at=(
                stored_reference["observed_at"]
                if stored_reference is not None
                else trend.windows.current_start
            ),
        )
        latest = InsightObservation(
            observation_id="observation-delivery-latest",
            insight_series_id="series-delivery-improving",
            cohort_signature=cohort_signature,
            current_share=trend.weighted_current_share,
            denominator=trend.current_denominator,
            source_groups=groups,
            healthy=healthy,
            classification_succeeded=all(
                item.current.denominator > 0 for item in trend.participating_strata
            ),
            observed_at=self.as_of,
        )
        monitoring = MonitoringReference(
            status=InsightStatus.MONITORING,
            reference_observation_id=reference_id,
            observation=reference,
        )
        return detect_improving(monitoring, latest).qualifies

    @staticmethod
    def _current_issue_units(
        units: Sequence[AnalyticsUnit],
        *,
        topic: PrimaryTopic,
        windows: Any,
    ) -> tuple[AnalyticsUnit, ...]:
        return tuple(
            unit
            for unit in units_in_window(units, start=windows.current_start, end=windows.current_end)
            if unit.resolved_brand is Brand.GUARDIAN
            and unit.is_relevant
            and unit.analysis_succeeded
            and unit.sentiment is Sentiment.NEGATIVE
            and unit.primary_topic is topic
        )

    @staticmethod
    def _evidence_roles(
        units: Sequence[AnalyticsUnit],
        *,
        topic: PrimaryTopic,
        windows: Any,
        preferred_subtopic: str | None,
    ) -> tuple[tuple[str, str], ...]:
        current = units_in_window(units, start=windows.current_start, end=windows.current_end)
        issue = [
            unit
            for unit in current
            if unit.resolved_brand is Brand.GUARDIAN
            and unit.is_relevant
            and unit.analysis_succeeded
            and unit.sentiment is Sentiment.NEGATIVE
            and unit.primary_topic is topic
        ]
        issue.sort(
            key=lambda unit: (
                unit.subtopic != preferred_subtopic,
                unit.source_group.value,
                unit.feedback_id,
            )
        )
        selected: list[tuple[str, str]] = []
        seen_groups: set[SourceGroup] = set()
        for unit in issue:
            if unit.source_group not in seen_groups:
                selected.append((unit.feedback_id, "representative"))
                seen_groups.add(unit.source_group)
            if len(selected) >= 4:
                break
        for unit in issue:
            if unit.feedback_id not in {item[0] for item in selected}:
                selected.append((unit.feedback_id, "supporting"))
            if len(selected) >= 6:
                break
        counterexample = next(
            (
                unit
                for unit in current
                if unit.resolved_brand is Brand.GUARDIAN
                and unit.is_relevant
                and unit.analysis_succeeded
                and unit.sentiment is Sentiment.POSITIVE
                and unit.primary_topic is topic
            ),
            None,
        )
        if counterexample is not None:
            selected.append((counterexample.feedback_id, "counterexample"))
        return tuple(selected)

    def _persist_daily_metrics(self, units: Sequence[AnalyticsUnit]) -> int:
        metrics = aggregate_daily_metrics(
            units,
            business_timezone=self.settings.voc_business_timezone,
            low_confidence_threshold=self.settings.voc_classifier_min_confidence,
            allow_inferred_dates=self.settings.voc_allow_inferred_dates,
        )
        self.database.execute("DELETE FROM daily_metrics")
        built_at = utc_now()
        for metric in metrics:
            payload = metric.model_dump(mode="json")
            metric_id = hashlib.sha256(_json_dump(payload).encode()).hexdigest()
            self.database.execute(
                """
                INSERT INTO daily_metrics VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                [
                    metric_id,
                    metric.date,
                    metric.resolved_brand.value,
                    metric.visibility.value,
                    metric.source_group.value,
                    metric.source_platform,
                    metric.experience_subject.value,
                    metric.primary_topic.value,
                    metric.subtopic,
                    metric.product_category,
                    metric.journey_stage.value,
                    metric.raw_record_count,
                    metric.independent_signal_count,
                    0,
                    metric.negative_count,
                    metric.negative_share,
                    metric.positive_count,
                    metric.positive_share,
                    None,
                    metric.average_rating,
                    metric.analyzed_count,
                    metric.low_confidence_count,
                    built_at,
                ],
            )
        return len(metrics)

    def _persist_built_insight(self, built: BuiltInsight, *, pipeline_run_id: str) -> None:
        card = built.card
        now = utc_now()
        existing = self.database.query_one(
            "SELECT status, primary_owner, created_at FROM insight_cards WHERE insight_id = ?",
            [card.insight_id],
        )
        status = str(existing["status"]) if existing else card.status.value
        primary_owner = str(existing["primary_owner"]) if existing else card.primary_owner.value
        created_at = existing["created_at"] if existing else now
        self.database.execute(
            """
            INSERT INTO insight_series VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (insight_series_id) DO UPDATE SET
                latest_observation_id = excluded.latest_observation_id
            """,
            [
                card.insight_series_id,
                "guardian",
                card.fact_packet.guardian_all_channel_trend.metric,
                card.topic.value,
                card.subtopic,
                None,
                created_at,
                card.observation_id,
            ],
        )
        if (
            card.insight_series_id == "series-delivery-improving"
            and self.settings.voc_demo_mode
        ):
            zone = ZoneInfo(self.settings.voc_business_timezone)
            reference_id = "observation-delivery-monitoring-reference"
            reference_start = built.trend.windows.baseline_start.astimezone(zone).date()
            reference_end = (
                built.trend.windows.baseline_end.astimezone(zone) - timedelta(days=1)
            ).date()
            self.database.execute(
                """
                INSERT INTO insight_observations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (observation_id) DO NOTHING
                """,
                [
                    reference_id,
                    card.insight_series_id,
                    "seed-monitoring-reference",
                    reference_start,
                    reference_end,
                    built.trend.baseline_numerator,
                    built.trend.baseline_denominator,
                    built.trend.weighted_baseline_share,
                    built.trend.weighted_baseline_share,
                    _json_dump(
                        {
                            "reference_observation": True,
                            "cohort": "guardian|all_channel|delivery_fulfilment|platform_strata-v1",
                        }
                    ),
                    _json_dump(
                        {
                            "healthy": not card.fact_packet.source_health_notes,
                            "source_groups": [group.value for group in SourceGroup],
                        }
                    ),
                    built.trend.windows.current_start,
                ],
            )
            self.database.execute(
                """
                INSERT INTO insight_status_history VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (status_event_id) DO NOTHING
                """,
                [
                    "status-delivery-monitoring-reference",
                    card.insight_series_id,
                    "monitoring",
                    built.trend.windows.current_start,
                    "demo-seed",
                    "Frozen monitoring reference for deterministic improvement checks.",
                    reference_id,
                ],
            )
        self.database.execute(
            """
            INSERT INTO insight_observations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (observation_id) DO UPDATE SET fact_packet = excluded.fact_packet,
                source_health_snapshot = excluded.source_health_snapshot,
                observed_at = excluded.observed_at
            """,
            [
                card.observation_id,
                card.insight_series_id,
                pipeline_run_id,
                card.window_start,
                card.window_end,
                built.trend.current_numerator,
                built.trend.current_denominator,
                built.trend.weighted_current_share,
                built.trend.weighted_baseline_share,
                _json_dump(card.fact_packet),
                _json_dump({"healthy": True, "notes": list(card.fact_packet.source_health_notes)}),
                self.as_of,
            ],
        )
        self.database.execute(
            """
            INSERT INTO insight_cards VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            ON CONFLICT (insight_id) DO UPDATE SET
                observation_id = excluded.observation_id,
                insight_type = excluded.insight_type,
                window_start = excluded.window_start,
                window_end = excluded.window_end,
                title = excluded.title,
                what_changed = excluded.what_changed,
                reach_summary = excluded.reach_summary,
                likely_driver = excluded.likely_driver,
                market_context = excluded.market_context,
                supporting_owner = excluded.supporting_owner,
                recommended_actions = excluded.recommended_actions,
                confidence = excluded.confidence,
                fact_packet = excluded.fact_packet,
                updated_at = excluded.updated_at
            """,
            [
                card.insight_id,
                card.insight_series_id,
                card.observation_id,
                card.insight_type.value,
                card.topic.value,
                card.subtopic,
                card.window_start,
                card.window_end,
                card.title,
                card.what_changed,
                card.reach_summary,
                card.likely_driver,
                card.market_context,
                primary_owner,
                card.supporting_owner.value if card.supporting_owner else None,
                [str(action) for action in card.recommended_actions],
                card.confidence.value,
                _json_dump(card.fact_packet),
                status,
                created_at,
                now,
            ],
        )
        self.database.execute("DELETE FROM insight_evidence WHERE insight_id = ?", [card.insight_id])
        for rank, (feedback_id, role) in enumerate(built.evidence_roles, start=1):
            self.database.execute(
                "INSERT INTO insight_evidence VALUES (?, ?, ?, ?)",
                [card.insight_id, feedback_id, role, rank],
            )

    @staticmethod
    def _insight_identity(topic: PrimaryTopic) -> tuple[str, str]:
        """Return stable, human-readable IDs for one topic-level decision series."""

        special = {
            PrimaryTopic.PRICE_PROMOTION: (
                "insight-price-promotion",
                "series-price-promotion",
            ),
            PrimaryTopic.AVAILABILITY_ASSORTMENT: (
                "insight-stock-cancellation",
                "series-stock-cancellation",
            ),
            PrimaryTopic.DELIVERY_FULFILMENT: (
                "insight-delivery-improving",
                "series-delivery-improving",
            ),
        }
        if topic in special:
            return special[topic]
        slug = topic.value.replace("_", "-")
        return f"insight-{slug}", f"series-{slug}"

    @staticmethod
    def _trend_health_notes(trend: TrendResult) -> tuple[str, ...]:
        """Keep health qualification distinct from ordinary threshold misses."""

        health_reasons = {
            "required_source_unhealthy",
            "source_health_unknown",
            "no_success_timestamp",
            "naive_freshness_timestamp",
            "source_stale",
            "source_volume_below_expected",
            "source_volume_above_expected",
            "timestamp_coverage_low",
            "duplicate_share_high",
            "classification_coverage_low",
            "classification_confidence_low",
        }
        notes = {
            reason
            for reason in trend.suppression_reasons
            if reason in health_reasons or reason.startswith("source_status_")
        }
        for excluded in trend.excluded_strata:
            notes.update(
                reason
                for reason in excluded.reasons
                if reason in health_reasons or reason.startswith("source_status_")
            )
        return tuple(sorted(notes))

    @staticmethod
    def _top_subtopic(
        issue_units: Sequence[AnalyticsUnit],
        *,
        preferred: str | None = None,
    ) -> TopSubtopicFact | None:
        if not issue_units:
            return None
        counts = Counter(
            unit.subtopic for unit in issue_units if unit.subtopic and unit.subtopic != "other"
        )
        if not counts:
            return None
        if preferred and counts.get(preferred):
            name = preferred
        else:
            name = min(counts, key=lambda value: (-counts[value], value))
        return TopSubtopicFact(
            name=name,
            support=counts[name],
            share=counts[name] / len(issue_units),
        )

    @staticmethod
    def _candidate_urgency(issue_units: Sequence[AnalyticsUnit]) -> int:
        severity = {
            Urgency.LOW: 0,
            Urgency.NORMAL: 1,
            Urgency.HIGH: 2,
            Urgency.CRITICAL: 3,
        }
        return max((severity[unit.urgency] for unit in issue_units), default=0)

    async def _write_selected_live_insights(
        self,
        selected: Sequence[BuiltInsight],
    ) -> tuple[BuiltInsight, ...]:
        """Use the configured writer for the three selected cards only.

        Analytics and ranking happen before this call. A provider or validation
        failure still returns the deterministic, playbook-backed card.
        """

        if (
            self.settings.voc_demo_mode
            or self.settings.ai_provider != "openai_compatible"
            or not self.settings.ai_api_key
            or not self.settings.ai_base_url
            or not self.settings.ai_model
        ):
            return tuple(selected)
        provider = OpenAICompatibleProvider(
            base_url=self.settings.ai_base_url,
            api_key=self.settings.ai_api_key,
            model=self.settings.ai_model,
            timeout_seconds=self.settings.ai_request_timeout_seconds,
        )
        rewritten: list[BuiltInsight] = []
        try:
            for built in selected:
                source = built.card
                card = await generate_insight_card(
                    source.fact_packet,
                    provider=provider,
                    role="leadership",
                    status=source.status,
                    insight_id=source.insight_id,
                    insight_series_id=source.insight_series_id,
                    observation_id=source.observation_id,
                )
                rewritten.append(
                    BuiltInsight(
                        card=card,
                        trend=built.trend,
                        benchmark=built.benchmark,
                        evidence_roles=built.evidence_roles,
                    )
                )
        finally:
            await provider.aclose()
        return tuple(rewritten)

    def _rebuild_insights(self, *, pipeline_run_id: str) -> dict[str, Any]:
        units = self._analytics_units()
        if not units:
            self._built.clear()
            return {"daily_metrics": 0, "insights": 0}
        daily_count = self._persist_daily_metrics(units)
        windows = self._windows()
        thresholds = self._thresholds()
        health_assessments = self._health_assessments(units)
        all_sources_healthy = bool(health_assessments) and all(
            assessment.healthy for assessment in health_assessments.values()
        )
        required_source_groups = tuple(
            sorted(
                {
                    assessment.stratum.source_group
                    for assessment in health_assessments.values()
                },
                key=lambda group: group.value,
            )
        )
        weekly_metrics = self._weekly_topic_metrics(
            units,
            windows=windows,
            healthy=all_sources_healthy,
        )
        analysis_ready = self._analysis_coverage() >= 0.80

        # The demo has three deliberate storylines. Live mode evaluates every
        # actionable taxonomy topic so collected data cannot disappear merely
        # because it does not resemble the fixture.
        if self.settings.voc_demo_mode:
            definitions: tuple[tuple[PrimaryTopic, str | None], ...] = (
                (PrimaryTopic.PRICE_PROMOTION, "unclear_eligibility"),
                (PrimaryTopic.AVAILABILITY_ASSORTMENT, "order_cancelled_out_of_stock"),
                (PrimaryTopic.DELIVERY_FULFILMENT, "late_delivery"),
            )
        else:
            definitions = tuple(
                (topic, None) for topic in PrimaryTopic if topic is not PrimaryTopic.OTHER
            )

        candidates: dict[str, BuiltInsight] = {}
        rankables: list[RankableInsight] = []
        for topic, preferred_subtopic in definitions:
            insight_id, series_id = self._insight_identity(topic)
            trend = compute_stratified_trend(
                units,
                topic=topic,
                windows=windows,
                thresholds=thresholds,
                health_assessments=health_assessments,
                require_explicit_health=True,
                required_source_groups=required_source_groups,
                allow_inferred_dates=self.settings.voc_allow_inferred_dates,
            )
            if trend.weighted_current_share is None or trend.weighted_baseline_share is None:
                continue
            health_notes = self._trend_health_notes(trend)
            if not self.settings.voc_demo_mode and (not analysis_ready or health_notes):
                continue

            recurring = detect_recurring_friction(
                weekly_metrics,
                topic=topic,
                top_n=3,
                weeks_required=3,
                lookback_weeks=4,
            )
            card_status = InsightStatus.OPEN
            if topic is PrimaryTopic.DELIVERY_FULFILMENT:
                improves = self._delivery_improves(
                    trend,
                    health_assessments=health_assessments,
                )
                monitoring_status = self._latest_series_status(series_id)
                has_monitoring_reference = bool(
                    monitoring_status is not None
                    and monitoring_status.get("status")
                    in {
                        InsightStatus.ACKNOWLEDGED.value,
                        InsightStatus.MONITORING.value,
                    }
                    and monitoring_status.get("reference_observation_id")
                )
                material_current_issue = (
                    trend.current_numerator >= self.settings.voc_alert_min_support
                    and trend.current_denominator >= 20
                    and all_sources_healthy
                )
                if improves:
                    insight_type = InsightType.IMPROVING
                    card_status = InsightStatus.MONITORING
                elif trend.qualifies:
                    insight_type = InsightType.ACT_NOW
                elif has_monitoring_reference:
                    insight_type = InsightType.WATCH
                    card_status = InsightStatus.MONITORING
                elif recurring.qualifies or material_current_issue:
                    insight_type = InsightType.WATCH
                else:
                    continue
            elif self.settings.voc_demo_mode and topic is PrimaryTopic.PRICE_PROMOTION:
                # Retain the deterministic demo fallback while clearly
                # downgrading any suppressed spike from Act now to Watch.
                insight_type = InsightType.ACT_NOW if trend.qualifies else InsightType.WATCH
            elif trend.qualifies:
                insight_type = InsightType.ACT_NOW
            elif recurring.qualifies and trend.current_numerator >= max(
                3, self.settings.voc_alert_min_support // 2
            ):
                insight_type = InsightType.WATCH
            else:
                continue

            issue_units = self._current_issue_units(units, topic=topic, windows=windows)
            top = self._top_subtopic(issue_units, preferred=preferred_subtopic)
            subtopic = top.name if top is not None else None
            drivers = rank_likely_drivers(
                units,
                topic=topic,
                windows=windows,
                minimum_support=3,
                allow_inferred_dates=self.settings.voc_allow_inferred_dates,
            )
            benchmark_candidate = build_matched_public_benchmark(
                units,
                topic=topic,
                windows=windows,
                minimum_sample=self.settings.voc_competitor_min_sample,
                allow_inferred_dates=self.settings.voc_allow_inferred_dates,
            )
            # An insufficient comparison is available in supporting analytics;
            # it does not deserve scarce space in an executive decision card.
            benchmark = benchmark_candidate if benchmark_candidate.comparable else None
            roles = self._evidence_roles(
                units,
                topic=topic,
                windows=windows,
                preferred_subtopic=subtopic,
            )
            if not roles:
                continue
            events = (
                (
                    BusinessEventFact(
                        event_id="demo-mid-year-glow",
                        event_type="campaign",
                        title="Mid-Year Glow campaign started",
                        occurred_at=datetime(
                            2026, 7, 6, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh")
                        ),
                        notes="Synthetic context only; not confirmed causality.",
                    ),
                )
                if topic is PrimaryTopic.PRICE_PROMOTION and self.settings.voc_demo_mode
                else ()
            )
            packet = build_fact_packet(
                trend,
                insight_type=insight_type,
                subtopic=subtopic,
                top_subtopic=top,
                likely_drivers=drivers[:6],
                business_events=events,
                benchmark=benchmark,
                allowed_evidence_ids=(item[0] for item in roles),
                source_health_notes=health_notes,
            )
            card = asyncio.run(
                generate_insight_card(
                    packet,
                    role="leadership",
                    status=card_status,
                    insight_id=insight_id,
                    insight_series_id=series_id,
                    observation_id=f"observation-{topic.value}-{pipeline_run_id}",
                )
            )
            built = BuiltInsight(
                card=card,
                trend=trend,
                benchmark=benchmark,
                evidence_roles=roles,
            )
            candidates[insight_id] = built
            rankables.append(
                RankableInsight(
                    candidate_id=insight_id,
                    insight_type=insight_type,
                    topic=topic,
                    primary_owner=card.primary_owner,
                    urgency=self._candidate_urgency(issue_units),
                    excess_items=trend.excess_items,
                    growth_multiple=trend.growth_multiple,
                    source_group_breadth=len(
                        {item.stratum.source_group for item in trend.participating_strata}
                    ),
                    confidence=card.confidence,
                    healthy=not health_notes or self.settings.voc_demo_mode,
                    payload=card,
                )
            )

        selected = tuple(
            candidates[candidate.candidate_id]
            for candidate in rank_today_candidates(rankables, limit=3)
        )
        selected = asyncio.run(self._write_selected_live_insights(selected))
        # Keep selected cards first for Today, while retaining other qualified
        # series for evidence and the monitoring workflow.
        built = {item.card.insight_id: item for item in selected}
        built.update(
            (insight_id, item)
            for insight_id, item in candidates.items()
            if insight_id not in built
        )
        for item in built.values():
            self._persist_built_insight(item, pipeline_run_id=pipeline_run_id)

        self._built = built
        return {"daily_metrics": daily_count, "insights": len(selected)}

    def rebuild(self, *, stage: str) -> dict[str, Any]:
        # Let the explicitly requested stage own and report its work instead
        # of consuming pending rows during automatic startup hydration.
        self.initialize(seed_demo=False, process_existing=False)
        if stage == "analyze":
            return self._classify_pending()
        return self._rebuild_insights(pipeline_run_id=f"cli-{stage}-{uuid.uuid4().hex[:8]}")

    # --------------------------------------------------------------- API views
    @staticmethod
    def _percent(value: float | None) -> str:
        return "—" if value is None else f"{value * 100:.1f}%"

    def _trend_points(self, built: BuiltInsight) -> list[TrendPointView]:
        units = self._analytics_units()
        zone = ZoneInfo(self.settings.voc_business_timezone)
        current = units_in_window(
            units,
            start=built.trend.windows.current_start,
            end=built.trend.windows.current_end,
        )
        grouped: dict[date, list[AnalyticsUnit]] = defaultdict(list)
        for unit in current:
            if unit.resolved_brand is Brand.GUARDIAN and unit.occurred_at is not None:
                grouped[unit.occurred_at.astimezone(zone).date()].append(unit)
        points: list[TrendPointView] = []
        day = built.card.window_start
        while day <= built.card.window_end:
            rows = [unit for unit in grouped.get(day, []) if unit.is_relevant and unit.analysis_succeeded]
            numerator = sum(
                unit.sentiment is Sentiment.NEGATIVE
                and unit.primary_topic is built.card.topic
                for unit in rows
            )
            share = numerator / len(rows) if rows else 0.0
            points.append(
                TrendPointView(
                    date=day,
                    current_share=share,
                    baseline_share=built.trend.weighted_baseline_share,
                )
            )
            day += timedelta(days=1)
        return points

    def _evidence_preview(self, insight_id: str, *, limit: int = 7) -> list[EvidencePreviewView]:
        rows = self.database.query(
            """
            SELECT ie.evidence_role, ie.rank, fi.feedback_id, fi.source_platform,
                fi.source_group, fi.source_url, fi.canonical_url, fi.occurred_at,
                fi.text_redacted, fi.is_synthetic,
                fa.sentiment, fa.primary_topic
            FROM insight_evidence ie
            JOIN feedback_items fi ON fi.feedback_id = ie.feedback_id
            JOIN feedback_analyses fa ON fa.feedback_id = fi.feedback_id
            WHERE ie.insight_id = ? ORDER BY ie.rank LIMIT ?
            """,
            [insight_id, limit],
        )
        return [
            EvidencePreviewView(
                feedback_id=str(row["feedback_id"]),
                evidence_role=row["evidence_role"],
                source_platform=str(row["source_platform"]),
                source_group=str(row["source_group"]),
                source_url=_public_evidence_source_url(row),
                occurred_at=row.get("occurred_at"),
                text_redacted=str(row["text_redacted"]),
                sentiment=str(row["sentiment"]),
                topic=str(row["primary_topic"]),
                is_synthetic=bool(row["is_synthetic"]),
            )
            for row in rows
        ]

    def _localized_actions(self, topic: PrimaryTopic, locale: str) -> list[str]:
        if locale == "en":
            return list(get_playbook(topic).actions)
        return {
            PrimaryTopic.PRODUCT_QUALITY_AUTHENTICITY: [
                "Rà soát bằng chứng về sản phẩm và nhà cung cấp bị ảnh hưởng.",
                "Chuẩn bị hướng dẫn phản hồi khách hàng.",
            ],
            PrimaryTopic.PRICE_PROMOTION: [
                "Kiểm tra hành vi áp dụng điều kiện ở bước thanh toán.",
                "Hiển thị điều kiện rõ ràng trước khi mua.",
            ],
            PrimaryTopic.AVAILABILITY_ASSORTMENT: [
                "Rà soát mức tập trung hết hàng ở các sản phẩm bị ảnh hưởng.",
                "Cập nhật thông báo tình trạng hàng.",
            ],
            PrimaryTopic.DELIVERY_FULFILMENT: [
                "Tiếp tục theo dõi mẫu vận chuyển và hoàn tất đơn.",
                "Duy trì hướng dẫn hỗ trợ khách hàng.",
            ],
            PrimaryTopic.ONLINE_CHECKOUT_PAYMENT: [
                "Tái hiện hành trình thanh toán bị ảnh hưởng.",
                "Khắc phục hoặc giải thích rõ bước gặp lỗi.",
            ],
            PrimaryTopic.STORE_STAFF_EXPERIENCE: [
                "Rà soát mức tập trung theo cửa hàng.",
                "Hướng dẫn lại bộ phận vận hành liên quan.",
            ],
            PrimaryTopic.CUSTOMER_SERVICE: [
                "Cập nhật hướng dẫn phản hồi.",
                "Rà soát tiêu chí chuyển cấp xử lý.",
            ],
            PrimaryTopic.RETURNS_REFUNDS: [
                "Rà soát mức rõ ràng của chính sách.",
                "Rà soát điểm nghẽn về thời gian xử lý.",
            ],
            PrimaryTopic.LOYALTY_MEMBERSHIP: [
                "Làm rõ quyền lợi thành viên.",
                "Xử lý vướng mắc lặp lại khi tích hoặc đổi điểm.",
            ],
            PrimaryTopic.OTHER: ["Rà soát bằng chứng đại diện."],
        }.get(topic, ["Rà soát bằng chứng đại diện."])

    def _localized_viewer_action(self, topic: PrimaryTopic, role: Role, locale: str) -> str | None:
        if role == "leadership":
            return None
        english = viewer_action(topic, role)
        if locale == "en":
            return english
        translations = {
            (PrimaryTopic.PRICE_PROMOTION, "ecommerce"): "Kiểm tra lại điều kiện trên các hành trình thanh toán bị ảnh hưởng.",
            (PrimaryTopic.PRICE_PROMOTION, "marketing"): "Đơn giản hóa nội dung chiến dịch theo điều kiện đã xác minh.",
            (PrimaryTopic.PRICE_PROMOTION, "customer_service"): "Dùng một cách giải thích đã xác minh cho câu hỏi về điều kiện.",
            (PrimaryTopic.AVAILABILITY_ASSORTMENT, "commercial"): "Rà soát bổ sung hàng và mức tập trung danh mục.",
            (PrimaryTopic.AVAILABILITY_ASSORTMENT, "ecommerce"): "Hiển thị rõ tình trạng hàng và phương án thay thế.",
            (PrimaryTopic.AVAILABILITY_ASSORTMENT, "customer_service"): "Ghi nhận sản phẩm liên quan khi xử lý hủy đơn.",
            (PrimaryTopic.DELIVERY_FULFILMENT, "ecommerce"): "Tách riêng tuyến vận chuyển hoặc hoàn tất đơn trong bằng chứng.",
            (PrimaryTopic.DELIVERY_FULFILMENT, "customer_service"): "Áp dụng nhất quán hướng dẫn hỗ trợ cho các trường hợp bị ảnh hưởng.",
        }
        return translations.get((topic, role), english)

    def _live_vietnamese_copy(
        self,
        card: InsightCard,
        trend: TrendResult,
    ) -> tuple[str, str, str]:
        labels = {
            PrimaryTopic.PRODUCT_QUALITY_AUTHENTICITY: "chất lượng và tính xác thực sản phẩm",
            PrimaryTopic.PRICE_PROMOTION: "giá và ưu đãi",
            PrimaryTopic.AVAILABILITY_ASSORTMENT: "tình trạng hàng và danh mục",
            PrimaryTopic.DELIVERY_FULFILMENT: "giao hàng và hoàn tất đơn",
            PrimaryTopic.ONLINE_CHECKOUT_PAYMENT: "thanh toán trực tuyến",
            PrimaryTopic.STORE_STAFF_EXPERIENCE: "trải nghiệm cửa hàng và nhân viên",
            PrimaryTopic.CUSTOMER_SERVICE: "dịch vụ khách hàng",
            PrimaryTopic.RETURNS_REFUNDS: "đổi trả và hoàn tiền",
            PrimaryTopic.LOYALTY_MEMBERSHIP: "thành viên và tích điểm",
            PrimaryTopic.OTHER: "phản hồi khác",
        }
        subject = labels[card.topic]
        title = f"Xử lý tín hiệu về {subject}"
        what_changed = (
            f"Phản hồi tiêu cực về {subject} đạt "
            f"{self._percent(trend.weighted_current_share)} "
            f"({trend.current_numerator}/{trend.current_denominator}), so với "
            f"{self._percent(trend.weighted_baseline_share)} ở giai đoạn nền."
        )
        driver = (
            card.fact_packet.likely_driver_dimensions[0]
            if card.fact_packet.likely_driver_dimensions
            else None
        )
        likely_driver = (
            "Chưa có yếu tố lặp lại nào đủ bằng chứng."
            if driver is None
            else (
                f"{driver.value.replace('_', ' ')} xuất hiện trong "
                f"{self._percent(driver.current_share)} phản hồi bị ảnh hưởng."
            )
        )
        return title, what_changed, likely_driver

    def _card_view(self, built: BuiltInsight, *, role: Role, locale: str) -> InsightCardView:
        card = built.card
        trend = built.trend
        stored = self.database.query_one(
            "SELECT status, primary_owner FROM insight_cards WHERE insight_id = ?",
            [card.insight_id],
        ) or {}
        status = str(stored.get("status") or card.status.value)
        primary_owner = str(stored.get("primary_owner") or card.primary_owner.value)
        benchmark = built.benchmark

        if not self.settings.voc_demo_mode:
            if card.insight_type is InsightType.IMPROVING:
                if locale == "vi":
                    title = "Mức cải thiện giao hàng đang được duy trì"
                    what_changed = (
                        f"Phản hồi tiêu cực về giao hàng giảm còn "
                        f"{self._percent(trend.weighted_current_share)}; cùng tập nguồn "
                        "khỏe mạnh hiện thấp hơn ngưỡng theo dõi đã cố định."
                    )
                    likely_driver = (
                        "Mức giảm xuất hiện trên các nhóm nguồn vẫn đủ độ phủ; tiếp tục theo dõi."
                    )
                else:
                    title = "Delivery recovery is holding"
                    what_changed = (
                        f"Negative delivery feedback fell to "
                        f"{self._percent(trend.weighted_current_share)}; the same healthy "
                        "cohort is now below its frozen monitoring threshold."
                    )
                    likely_driver = (
                        "The decline is visible across source groups with healthy coverage; "
                        "continue monitoring."
                    )
            elif locale == "vi":
                title, what_changed, likely_driver = self._live_vietnamese_copy(card, trend)
            else:
                title = card.title
                what_changed = card.what_changed
                likely_driver = card.likely_driver
        elif card.topic is PrimaryTopic.PRICE_PROMOTION:
            top = card.fact_packet.top_subtopic
            share = (top.share if top else 0.0) * 100
            if locale == "vi":
                title = "Nói rõ điều kiện ưu đãi trước thanh toán"
                if trend.growth_multiple is None:
                    what_changed = (
                        f"Phản hồi tiêu cực về ưu đãi đạt {self._percent(trend.weighted_current_share)} "
                        "và là tín hiệu mới so với mức nền gần đây."
                    )
                else:
                    what_changed = (
                        f"Phản hồi tiêu cực về ưu đãi đạt {self._percent(trend.weighted_current_share)}, "
                        f"cao gấp {trend.growth_multiple:.1f} lần mức nền gần đây."
                    )
                likely_driver = (
                    f"{share:.0f}% phản hồi bị ảnh hưởng nói điều kiện chi tiêu tối thiểu hoặc sản phẩm "
                    "bị loại trừ chỉ xuất hiện ở bước thanh toán."
                )
            else:
                title = "Make promotion eligibility clear before checkout"
                if trend.growth_multiple is None:
                    what_changed = (
                        f"Promotion complaints reached {self._percent(trend.weighted_current_share)} "
                        "this week and are a new signal versus the recent baseline."
                    )
                else:
                    what_changed = (
                        f"Promotion complaints reached {self._percent(trend.weighted_current_share)} "
                        f"this week—{trend.growth_multiple:.1f}× the recent baseline."
                    )
                likely_driver = (
                    f"{share:.0f}% of affected feedback mentions minimum-spend or excluded-item "
                    "rules appearing only at checkout."
                )
        elif card.topic is PrimaryTopic.AVAILABILITY_ASSORTMENT:
            is_act = card.insight_type is InsightType.ACT_NOW
            if locale == "vi":
                title = "Xử lý hủy đơn do lệch tồn kho" if is_act else "Theo dõi hủy đơn do lệch tồn kho"
                what_changed = (
                    f"Phản hồi hủy đơn do hết hàng đạt {self._percent(trend.weighted_current_share)} "
                    f"so với mức nền {self._percent(trend.weighted_baseline_share)}."
                )
                likely_driver = "Phản hồi lặp lại việc đơn đã được xác nhận trước khi khách được báo hết hàng."
            else:
                title = "Resolve stock-linked cancellations now" if is_act else "Watch stock-linked cancellations"
                what_changed = (
                    f"Stock-linked cancellations are {self._percent(trend.weighted_current_share)} "
                    f"of current feedback versus {self._percent(trend.weighted_baseline_share)} baseline."
                )
                likely_driver = "Repeated feedback says orders were confirmed before customers were told the item was unavailable."
        else:
            improving = card.insight_type is InsightType.IMPROVING
            if locale == "vi":
                title = (
                    "Mức cải thiện giao hàng đang được duy trì"
                    if improving
                    else "Xử lý phản hồi tiêu cực về giao hàng"
                )
                if improving:
                    what_changed = (
                        f"Phản hồi tiêu cực về giao hàng giảm còn {self._percent(trend.weighted_current_share)}; "
                        "cùng tập nguồn khỏe mạnh hiện thấp hơn ngưỡng theo dõi đã cố định."
                    )
                    likely_driver = "Mức giảm xuất hiện trên các nhóm nguồn vẫn đủ độ phủ; tiếp tục theo dõi."
                else:
                    what_changed = (
                        f"Phản hồi tiêu cực về giao hàng đạt {self._percent(trend.weighted_current_share)} "
                        f"so với mức nền {self._percent(trend.weighted_baseline_share)}."
                    )
                    likely_driver = "Phản hồi lặp lại vấn đề giao hàng trễ hoặc hoàn tất đơn chưa đúng kỳ vọng."
            else:
                title = (
                    "Delivery recovery is holding"
                    if improving
                    else "Address rising delivery friction"
                )
                if improving:
                    what_changed = (
                        f"Negative delivery feedback fell to {self._percent(trend.weighted_current_share)}; "
                        "the same healthy cohort is now below its frozen monitoring threshold."
                    )
                    likely_driver = "The decline is visible across source groups with healthy coverage; continue monitoring."
                else:
                    what_changed = (
                        f"Negative delivery feedback reached {self._percent(trend.weighted_current_share)} "
                        f"versus a {self._percent(trend.weighted_baseline_share)} baseline."
                    )
                    likely_driver = "Repeated feedback points to late delivery or fulfilment that missed expectations."

        market_context: str | None = (
            card.market_context if not self.settings.voc_demo_mode else None
        )
        benchmark_view: BenchmarkView | None = None
        if benchmark is not None:
            if benchmark.comparable:
                values = {
                    "guardian": benchmark.guardian_weighted_share or 0,
                    "hasaki": benchmark.hasaki_weighted_share or 0,
                    "watsons": benchmark.watsons_weighted_share or 0,
                }
                expectation = benchmark.market_expectation
                expectation_clause = ""
                if expectation is not None:
                    expectation_brand = expectation.brand.value.capitalize()
                    praised = expectation.praised_subtopic.replace("_", " ")
                    expectation_clause = (
                        f"; khách của {expectation_brand} thường khen {praised}"
                        if locale == "vi"
                        else f"; {expectation_brand} customers most often praise {praised}"
                    )
                market_context = (
                    f"Trong nhóm công khai tương đồng, Guardian {self._percent(values['guardian'])}, "
                    f"Hasaki {self._percent(values['hasaki'])} và Watsons "
                    f"{self._percent(values['watsons'])}{expectation_clause}."
                    if locale == "vi"
                    else f"In the matched public cohort, Guardian is at "
                    f"{self._percent(values['guardian'])}, Hasaki "
                    f"{self._percent(values['hasaki'])}, and Watsons "
                    f"{self._percent(values['watsons'])}{expectation_clause}."
                )
                cells: dict[str, tuple[int, int]] = {brand: (0, 0) for brand in values}
                for stratum in benchmark.strata:
                    for brand in values:
                        cell = getattr(stratum, brand)
                        cells[brand] = (cells[brand][0] + cell.numerator, cells[brand][1] + cell.denominator)
                benchmark_view = BenchmarkView(
                    period_start=card.window_start,
                    period_end=card.window_end,
                    cohort_label=(
                        "Chỉ phản hồi công khai; cùng nền tảng, ngành hàng, ngôn ngữ và chủ thể trải nghiệm."
                        if locale == "vi"
                        else "Public only; matched platform, category, language, and experience subject."
                    ),
                    source_coverage=list(benchmark.source_platforms),
                    comparable=True,
                    brands=[
                        BenchmarkBrandView(
                            brand=brand,
                            numerator=cells[brand][0],
                            denominator=cells[brand][1],
                            weighted_share=values[brand],
                        )
                        for brand in ("guardian", "hasaki", "watsons")
                    ],
                    market_expectation=market_context,
                )
            else:
                market_context = (
                    "Chưa đủ phản hồi công khai tương đồng để so sánh."
                    if locale == "vi"
                    else "Not enough comparable public feedback."
                )
                benchmark_view = BenchmarkView(
                    period_start=card.window_start,
                    period_end=card.window_end,
                    cohort_label="Matched public feedback only",
                    source_coverage=[],
                    comparable=False,
                    insufficiency_reason=market_context,
                )

        strata = [
            StratumView(
                source_group=item.stratum.source_group.value,
                source_platform=item.stratum.source_platform,
                current_numerator=item.current.numerator,
                current_denominator=item.current.denominator,
                baseline_numerator=item.baseline.numerator,
                baseline_denominator=item.baseline.denominator,
                baseline_weight=item.baseline_weight,
            )
            for item in trend.participating_strata
        ]
        confidence_score = {"high": 0.92, "medium": 0.78, "low": 0.60}[card.confidence.value]
        participating_group_count = len(
            {item.stratum.source_group for item in trend.participating_strata}
        )
        if self.settings.voc_demo_mode:
            data_quality = (
                ["Dữ liệu demo tổng hợp; mọi số liệu được tính lại từ DuckDB."]
                if locale == "vi"
                else ["Synthetic demo data; every metric is recomputed from DuckDB."]
            )
        else:
            data_quality = []
        return InsightCardView(
            insight_id=card.insight_id,
            insight_series_id=card.insight_series_id,
            label=card.insight_type.value,
            status=status,
            topic=card.topic.value,
            subtopic=card.subtopic,
            title=title,
            what_changed=what_changed,
            reach_summary=(
                f"{trend.current_numerator} tín hiệu độc lập trên {participating_group_count} nhóm nguồn; "
                f"{trend.current_denominator} phản hồi đã phân tích."
                if locale == "vi"
                else f"{trend.current_numerator} independent signals across "
                f"{participating_group_count} source groups; {trend.current_denominator} analyzed."
            ),
            likely_driver=likely_driver,
            market_context=market_context,
            recommended_actions=self._localized_actions(card.topic, locale),
            primary_owner=primary_owner,
            supporting_owner=card.supporting_owner.value if card.supporting_owner else None,
            viewer_action=self._localized_viewer_action(card.topic, role, locale),
            confidence=ConfidenceView(
                level=card.confidence.value,
                score=confidence_score,
                sample_size=trend.current_denominator,
                source_groups=participating_group_count,
                analysis_coverage=self._analysis_coverage(),
                note=(
                    "Bằng chứng chỉ sử dụng các tầng nguồn đủ mới và đủ dữ liệu phân tích."
                    if locale == "vi"
                    else "Evidence uses only fresh, sufficiently analyzed source strata."
                ),
            ),
            metrics=CardMetricsView(
                current_numerator=trend.current_numerator,
                current_denominator=trend.current_denominator,
                current_share=trend.weighted_current_share or 0,
                baseline_numerator=trend.baseline_numerator,
                baseline_denominator=trend.baseline_denominator,
                baseline_share=trend.weighted_baseline_share or 0,
                growth_multiple=trend.growth_multiple,
                percentage_point_change=trend.percentage_point_change or 0,
                excess_items=trend.excess_items,
                raw_record_reach=trend.current_numerator,
                independent_signal_count=trend.current_numerator,
                strata=strata,
            ),
            benchmark=benchmark_view,
            trend=self._trend_points(built),
            evidence_preview=self._evidence_preview(card.insight_id, limit=3),
            data_quality_notes=data_quality,
        )

    def _analysis_coverage(self) -> float:
        row = self.database.query_one(
            """
            SELECT count(*) AS total,
                count(*) FILTER (WHERE analysis_status IN ('completed', 'low_confidence')) AS analyzed
            FROM feedback_items WHERE duplicate_of IS NULL
            """
        ) or {"total": 0, "analyzed": 0}
        total = int(row["total"])
        return 0.0 if not total else int(row["analyzed"]) / total

    def _source_status_views(self, locale: str) -> list[SourceStatusView]:
        rows = self.database.query(
            """
            SELECT source_group, status, last_success_at, last_record_at,
                recent_volume, notes
            FROM source_status ORDER BY source_group, source_name
            """
        )
        labels = {
            "marketplace": ("Marketplace reviews", "Đánh giá sàn TMĐT"),
            "owned": ("Guardian e-commerce", "TMĐT Guardian"),
            "customer_service": ("Customer service", "Chăm sóc khách hàng"),
            "social": ("Social & community", "Mạng xã hội & cộng đồng"),
        }
        by_group: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
        for row in rows:
            by_group[str(row["source_group"])].append(row)
        severity = {"healthy": 0, "partial": 1, "stale": 2, "failed": 3}
        views: list[SourceStatusView] = []
        for source_group, group_rows in sorted(by_group.items()):
            status = max(
                (self._effective_source_status(row) for row in group_rows),
                key=lambda value: severity.get(value, 3),
            )
            success_times = [
                row["last_success_at"]
                for row in group_rows
                if isinstance(row.get("last_success_at"), datetime)
            ]
            record_times = [
                row["last_record_at"]
                for row in group_rows
                if isinstance(row.get("last_record_at"), datetime)
            ]
            all_connectors_succeeded = len(success_times) == len(group_rows)
            notes = list(
                dict.fromkeys(
                    str(row["notes"])
                    for row in group_rows
                    if row.get("notes")
                )
            )
            views.append(
                SourceStatusView(
                    name=source_group,
                    label=labels.get(
                        source_group,
                        (source_group, source_group),
                    )[1 if locale == "vi" else 0],
                    source_group=source_group,
                    status=status,
                    last_success_at=(
                        min(success_times) if all_connectors_succeeded else None
                    ),
                    last_record_at=max(record_times) if record_times else None,
                    recent_volume=sum(
                        int(row.get("recent_volume") or 0) for row in group_rows
                    ),
                    note="; ".join(notes)[:1_000] or None,
                )
            )
        return views

    def _live_evidence_readiness(self) -> dict[str, int]:
        """Count only dated, relevant, confidently analyzed Guardian signals."""

        windows = self._windows()
        inferred_clause = (
            ""
            if self.settings.voc_allow_inferred_dates
            else "AND fi.occurred_at_quality <> 'inferred'"
        )
        row = self.database.query_one(
            f"""
            SELECT
                count(DISTINCT CASE
                    WHEN fi.occurred_at >= ? AND fi.occurred_at < ?
                    THEN coalesce(fi.repost_group_id, fi.feedback_id)
                END) AS current_signals,
                count(DISTINCT CASE
                    WHEN fi.occurred_at >= ? AND fi.occurred_at < ?
                    THEN coalesce(fi.repost_group_id, fi.feedback_id)
                END) AS baseline_signals,
                count(DISTINCT CASE
                    WHEN fi.occurred_at >= ? AND fi.occurred_at < ?
                    THEN fi.source_group
                END) AS source_groups
            FROM feedback_items fi
            JOIN feedback_analyses fa ON fa.feedback_id = fi.feedback_id
            WHERE fi.duplicate_of IS NULL
              AND coalesce(fi.brand, fa.primary_brand) = 'guardian'
              AND fa.is_relevant
              AND fi.analysis_status = 'completed'
              AND fi.occurred_at IS NOT NULL
              AND fi.occurred_at_quality <> 'missing'
              {inferred_clause}
            """,
            [
                windows.current_start,
                windows.current_end,
                windows.baseline_start,
                windows.baseline_end,
                windows.baseline_start,
                windows.current_end,
            ],
        ) or {"current_signals": 0, "baseline_signals": 0, "source_groups": 0}
        return {key: int(value or 0) for key, value in row.items()}

    def _dashboard_resolved_brand(self, row: Mapping[str, Any]) -> str | None:
        fixed = _dashboard_text(row.get("brand"))
        if fixed is not None:
            return fixed
        primary = _dashboard_text(row.get("primary_brand"))
        span = _dashboard_text(row.get("brand_evidence_span"))
        if (
            primary is not None
            and span is not None
            and float(row.get("brand_attribution_confidence") or 0)
            >= self.settings.voc_classifier_min_confidence
            and span in str(row.get("text_redacted") or "")
        ):
            return primary
        return None

    def _dashboard_time_eligible(self, row: Mapping[str, Any]) -> bool:
        occurred_at = row.get("occurred_at")
        if not isinstance(occurred_at, datetime) or occurred_at.tzinfo is None:
            return False
        quality = str(row.get("occurred_at_quality") or "missing")
        if quality == "missing":
            return False
        return self.settings.voc_allow_inferred_dates or quality != "inferred"

    def _dashboard_benchmark(
        self,
        rows: Sequence[Mapping[str, Any]],
        *,
        current_start: datetime,
        current_end: datetime,
    ) -> DashboardBenchmarkView:
        brands = ("guardian", "hasaki", "watsons")

        def aggregate_brand_rows(
            brand_rows: Sequence[Mapping[str, Any]],
        ) -> list[DashboardBenchmarkAggregateView]:
            aggregates: list[DashboardBenchmarkAggregateView] = []
            for brand in brands:
                matched = [
                    row
                    for row in brand_rows
                    if self._dashboard_resolved_brand(row) == brand
                ]
                ratings = [
                    float(row["rating"])
                    for row in matched
                    if row.get("rating") is not None
                ]
                aggregates.append(
                    DashboardBenchmarkAggregateView(
                        brand=brand,
                        feedback=len(matched),
                        complaints=sum(str(row.get("intent")) == "complaint" for row in matched),
                        positive=sum(str(row.get("sentiment")) == "positive" for row in matched),
                        neutral=sum(str(row.get("sentiment")) == "neutral" for row in matched),
                        rating=(sum(ratings) / len(ratings) if ratings else None),
                        rating_count=len(ratings),
                    )
                )
            return aggregates

        grouped: dict[
            tuple[str, str, str, str, str],
            dict[str, list[Mapping[str, Any]]],
        ] = defaultdict(lambda: defaultdict(list))
        current_dated = 0
        for row in rows:
            if not self._dashboard_time_eligible(row):
                continue
            occurred_at = row.get("occurred_at")
            assert isinstance(occurred_at, datetime)
            if not current_start <= occurred_at < current_end:
                continue
            current_dated += 1
            brand = self._dashboard_resolved_brand(row)
            language = str(row.get("language") or "").strip().lower()
            category = _dashboard_text(row.get("product_category"))
            if (
                brand not in brands
                or str(row.get("visibility")) != "public"
                or str(row.get("source_group")) not in {"marketplace", "social"}
                or str(row.get("analysis_status")) != "completed"
                or not bool(row.get("is_relevant"))
                or category is None
                or language in {"", "unknown", "und", "undetermined"}
            ):
                continue
            key = (
                str(row.get("source_group")),
                str(row.get("source_platform")),
                category,
                language,
                str(row.get("analyzed_experience_subject") or "unknown"),
            )
            grouped[key][brand].append(row)

        minimum = self.settings.voc_competitor_min_sample
        common = [
            cohort
            for cohort in grouped.values()
            if all(len(cohort.get(brand, ())) >= minimum for brand in brands)
        ]
        if not common:
            fallback_rows = [
                row
                for row in rows
                if self._dashboard_resolved_brand(row) in brands
                and str(row.get("analysis_status")) == "completed"
                and bool(row.get("is_relevant"))
            ]
            fallback_counts = Counter(
                self._dashboard_resolved_brand(row)
                for row in fallback_rows
            )
            if all(fallback_counts[brand] >= minimum for brand in brands):
                return DashboardBenchmarkView(
                    comparable=True,
                    reason=(
                        "Directional all-source comparison across analyzed Guardian, "
                        "Hasaki, and Watsons feedback."
                    ),
                    aggregates=aggregate_brand_rows(fallback_rows),
                )
            reason = (
                "No dated feedback is available in the current analysis window."
                if current_dated == 0
                else "No public source/platform/category/language cohort meets "
                f"the minimum sample of {minimum} for Guardian, Hasaki, and Watsons."
            )
            return DashboardBenchmarkView(
                comparable=False,
                reason=reason,
                aggregates=[],
            )

        return DashboardBenchmarkView(
            comparable=True,
            reason=None,
            aggregates=aggregate_brand_rows(
                [row for cohort in common for matched_rows in cohort.values() for row in matched_rows]
            ),
        )

    def dashboard(
        self,
        *,
        dashboard_range: str = "all",
        date_from: date | None = None,
        date_to: date | None = None,
        preset: str = "all",
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> DashboardResponse:
        """Return the product dashboard from canonical, non-duplicate feedback.

        Window counts use independent feedback signals. Coverage deliberately
        remains item-level so missing classification, dates, and product
        attribution are visible rather than disappearing during aggregation.
        """

        self.initialize(seed_demo=self.settings.voc_demo_mode)
        synthetic_clause = "" if self.settings.voc_demo_mode else "AND fi.is_synthetic = FALSE"
        rows = self.database.query(
            f"""
            SELECT fi.feedback_id, fi.repost_group_id, fi.source_group,
                fi.source_platform, fi.visibility, fi.brand, fi.occurred_at,
                fi.observed_at, fi.occurred_at_quality, fi.ingested_at,
                fi.language, fi.text_redacted, fi.rating, fi.product_name,
                fi.product_category, fi.source_url, fi.canonical_url,
                fi.sanitized_metadata, fi.is_synthetic, fi.analysis_status,
                fa.feedback_id AS analysis_feedback_id, fa.is_relevant,
                fa.primary_brand, fa.brand_attribution_confidence,
                fa.brand_evidence_span,
                fa.experience_subject AS analyzed_experience_subject,
                fa.primary_topic, fa.subtopic, fa.intent, fa.sentiment,
                fa.sentiment_score, fa.confidence, fa.analyzed_at
            FROM feedback_items fi
            LEFT JOIN feedback_analyses fa ON fa.feedback_id = fi.feedback_id
            WHERE fi.duplicate_of IS NULL
              {synthetic_clause}
            ORDER BY fi.feedback_id
            """
        )
        if dashboard_range != "all" or date_from is not None or date_to is not None:
            windows = self._dashboard_windows(
                dashboard_range,
                date_from=date_from,
                date_to=date_to,
            )
        elif preset not in {"7d", "30d", "1y", "all", "custom"}:
            raise ValueError("preset must be one of 7d, 30d, 1y, all, custom")
        elif preset == "custom":
            if start_date is None or end_date is None or end_date < start_date:
                raise ValueError("custom range requires a valid start and end date")
            business_zone = ZoneInfo(self.settings.voc_business_timezone)
            current_start = datetime.combine(start_date, datetime.min.time(), business_zone)
            current_end = datetime.combine(end_date + timedelta(days=1), datetime.min.time(), business_zone)
            duration = current_end - current_start
            windows = AnalysisWindows(
                current_start=current_start.astimezone(timezone.utc),
                current_end=current_end.astimezone(timezone.utc),
                baseline_start=(current_start - duration).astimezone(timezone.utc),
                baseline_end=current_start.astimezone(timezone.utc),
                business_timezone=self.settings.voc_business_timezone,
                current_days=duration.days,
                baseline_days=duration.days,
            )
        elif preset == "all":
            windows = self._windows()
        else:
            days = {"7d": 7, "30d": 30, "1y": 365}[preset]
            windows = build_analysis_windows(
                self.as_of,
                current_days=days,
                baseline_days=days,
                business_timezone=self.settings.voc_business_timezone,
                as_of_date_is_complete=self.settings.voc_demo_mode,
            )

        representatives: dict[str, Mapping[str, Any]] = {}
        for row in rows:
            unit_id = str(row.get("repost_group_id") or row["feedback_id"])
            representatives.setdefault(unit_id, row)
        independent = list(representatives.values())

        analyzed_items = sum(row.get("analysis_feedback_id") is not None for row in rows)
        relevant_items = sum(
            row.get("analysis_feedback_id") is not None and bool(row.get("is_relevant"))
            for row in rows
        )
        time_eligible_items = sum(self._dashboard_time_eligible(row) for row in rows)
        product_attributed_items = sum(
            _dashboard_product_id(row) != "unattributed" for row in rows
        )
        coverage = DashboardCoverageView(
            feedback_items=len(rows),
            analyzed_items=analyzed_items,
            relevant_items=relevant_items,
            time_eligible_items=time_eligible_items,
            product_attributed_items=product_attributed_items,
        )

        guardian_rows = [
            row for row in rows if self._dashboard_resolved_brand(row) == "guardian"
        ]
        guardian_independent = [
            row
            for row in independent
            if self._dashboard_resolved_brand(row) == "guardian"
        ]

        def guardian_in_window(start: datetime, end: datetime) -> list[Mapping[str, Any]]:
            matched: list[Mapping[str, Any]] = []
            for row in guardian_independent:
                if not self._dashboard_time_eligible(row):
                    continue
                occurred_at = row.get("occurred_at")
                assert isinstance(occurred_at, datetime)
                if start <= occurred_at < end:
                    matched.append(row)
            return matched

        guardian_current_rows = guardian_in_window(
            windows.current_start, windows.current_end
        )
        guardian_baseline_rows = guardian_in_window(
            windows.baseline_start, windows.baseline_end
        )
        if not rows:
            data_state = "empty"
        elif (
            analyzed_items < len(rows)
            or time_eligible_items == 0
            or product_attributed_items == 0
            or not guardian_rows
            or not guardian_current_rows
            or not guardian_baseline_rows
            or any(_dashboard_product_id(row) == "unattributed" for row in guardian_rows)
        ):
            data_state = "partial"
        else:
            data_state = "ready"

        messages: list[str] = []
        if not rows:
            messages.append(
                "No feedback data is available. Import or collect verified feedback to populate the dashboard."
            )
        else:
            if not guardian_rows:
                messages.append(
                    "Feedback is available, but no rows can be defensibly attributed to Guardian products."
                )
            if not guardian_current_rows:
                messages.append(
                    "No resolved Guardian feedback occurs in the current analysis window; current product metrics are zero."
                )
            if not guardian_baseline_rows:
                messages.append(
                    "No resolved Guardian feedback occurs in the baseline analysis window; comparisons and sentiment deltas are unavailable."
                )
            if analyzed_items < len(rows):
                messages.append(
                    f"{len(rows) - analyzed_items} feedback item(s) are still awaiting analysis."
                )
            if time_eligible_items == 0:
                messages.append(
                    "Feedback is available, but no trustworthy occurrence dates are available for current or baseline metrics."
                )
            elif any(not self._dashboard_time_eligible(row) for row in guardian_rows):
                messages.append(
                    "Some Guardian feedback has no trustworthy occurrence date and is excluded from period metrics."
                )
            unattributed_guardian = sum(
                _dashboard_product_id(row) == "unattributed" for row in guardian_rows
            )
            if unattributed_guardian:
                messages.append(
                    f"{unattributed_guardian} Guardian feedback item(s) have no product attribution and are grouped as unattributed."
                )

        by_product: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
        for row in independent:
            if self._dashboard_resolved_brand(row) == "guardian":
                by_product[_dashboard_product_id(row)].append(row)

        def period_rows(
            product_rows: Sequence[Mapping[str, Any]],
            start: datetime,
            end: datetime,
        ) -> list[Mapping[str, Any]]:
            result: list[Mapping[str, Any]] = []
            for row in product_rows:
                if not self._dashboard_time_eligible(row):
                    continue
                occurred_at = row.get("occurred_at")
                assert isinstance(occurred_at, datetime)
                if start <= occurred_at < end:
                    result.append(row)
            return result

        def analyzed_period_rows(
            period: Sequence[Mapping[str, Any]],
        ) -> list[Mapping[str, Any]]:
            return [
                row
                for row in period
                if str(row.get("analysis_status")) == "completed"
                and bool(row.get("is_relevant"))
            ]

        def period_counts(
            period: Sequence[Mapping[str, Any]],
        ) -> DashboardPeriodCountsView:
            analyzed = analyzed_period_rows(period)
            return DashboardPeriodCountsView(
                feedback=len(period),
                complaints=sum(str(row.get("intent")) == "complaint" for row in analyzed),
                positive=sum(str(row.get("sentiment")) == "positive" for row in analyzed),
                neutral=sum(str(row.get("sentiment")) == "neutral" for row in analyzed),
            )

        def shift_month(value: date, offset: int) -> date:
            index = value.year * 12 + value.month - 1 + offset
            return date(index // 12, index % 12 + 1, 1)

        business_zone = ZoneInfo(self.settings.voc_business_timezone)
        trend_start_date = windows.current_start.astimezone(business_zone).date()
        trend_end_date = (windows.current_end - timedelta(microseconds=1)).astimezone(business_zone).date()
        trend_days = (trend_end_date - trend_start_date).days + 1
        trend_preset = dashboard_range if dashboard_range != "all" else preset
        sentiment_trend_granularity = (
            "month"
            if trend_preset in {"all", "1y"} or trend_days > 62
            else "day"
        )
        if sentiment_trend_granularity == "day":
            trend_periods = [trend_start_date + timedelta(days=index) for index in range(trend_days)]
        else:
            trend_end_month = trend_end_date.replace(day=1)
            trend_start_month = (
                shift_month(trend_end_month, -11)
                if trend_preset in {"all", "1y"}
                else trend_start_date.replace(day=1)
            )
            month_count = (
                12
                if trend_preset in {"all", "1y"}
                else (trend_end_month.year - trend_start_month.year) * 12
                + trend_end_month.month - trend_start_month.month
                + 1
            )
            trend_periods = [shift_month(trend_start_month, index) for index in range(month_count)]
        sentiment_months: dict[date, Counter[str]] = {
            period: Counter() for period in trend_periods
        }
        for row in guardian_independent:
            if not self._dashboard_time_eligible(row):
                continue
            occurred_at = row.get("occurred_at")
            if not isinstance(occurred_at, datetime):
                continue
            occurred_date = occurred_at.astimezone(business_zone).date()
            period = occurred_date if sentiment_trend_granularity == "day" else occurred_date.replace(day=1)
            if period not in sentiment_months:
                continue
            if str(row.get("analysis_status")) != "completed" or not bool(row.get("is_relevant")):
                continue
            sentiment = str(row.get("sentiment"))
            if sentiment in {"positive", "neutral", "negative"}:
                sentiment_months[period][sentiment] += 1
        overall_sentiment_trend = [
            DashboardSentimentTrendPointView(
                date=period,
                total=sum(counts.values()),
                positive=counts["positive"],
                neutral=counts["neutral"],
                negative=counts["negative"],
            )
            for period, counts in sorted(sentiment_months.items())
        ]

        platform_aliases = {
            "guardian_ecommerce": "Guardian.com.vn",
            "tiktok": "TikTok Shop",
            "tiktok_shop": "TikTok Shop",
            "shopee": "Shopee",
            "lazada": "Lazada",
            "grabmart": "GrabMart",
        }
        marketplace_platforms = tuple(dict.fromkeys(platform_aliases.values()))

        def projected_rating_point(
            platform: str,
            observed: Sequence[tuple[int, date, float, int]],
        ) -> DashboardRatingTrendPointView | None:
            if len(observed) < 2:
                return None
            xs = [float(week) for week, _, _, _ in observed]
            ys = [average for _, _, average, _ in observed]
            x_mean = sum(xs) / len(xs)
            y_mean = sum(ys) / len(ys)
            denominator = sum((x - x_mean) ** 2 for x in xs)
            slope = (
                0.0
                if denominator == 0
                else sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys, strict=True))
                / denominator
            )
            intercept = y_mean - slope * x_mean
            last_week, last_date, _, sample_size = observed[-1]
            next_week = last_week + 1
            return DashboardRatingTrendPointView(
                date=last_date + timedelta(days=7),
                platform=platform,
                average_rating=max(1.0, min(5.0, intercept + slope * next_week)),
                count=sample_size,
                predicted=True,
            )

        products: list[DashboardProductView] = []
        for product_id, product_rows in by_product.items():
            metadata_values = [
                value
                for row in product_rows
                if isinstance((value := _json_load(row.get("sanitized_metadata"), {})), Mapping)
            ]
            names = [_dashboard_text(row.get("product_name")) for row in product_rows]
            name = (
                "Unattributed feedback"
                if product_id == "unattributed"
                else _dashboard_dominant(names) or product_id
            )
            short_name = _dashboard_dominant(
                _dashboard_metadata_value(metadata, "short_name", "product_short_name")
                for metadata in metadata_values
            ) or name
            category = _dashboard_dominant(
                _dashboard_text(row.get("product_category")) for row in product_rows
            )
            sku = _dashboard_dominant(
                _dashboard_metadata_value(
                    metadata, "sku", "product_sku", "seller_sku", "sku_id"
                )
                for metadata in metadata_values
            )
            pack = _dashboard_dominant(
                _dashboard_metadata_value(metadata, "pack", "pack_size", "variation")
                for metadata in metadata_values
            )
            ratings = [
                float(row["rating"])
                for row in product_rows
                if row.get("rating") is not None
            ]
            current_rows = period_rows(
                product_rows, windows.current_start, windows.current_end
            )
            baseline_rows = period_rows(
                product_rows, windows.baseline_start, windows.baseline_end
            )
            current_analyzed = analyzed_period_rows(current_rows)
            baseline_analyzed = analyzed_period_rows(baseline_rows)
            all_analyzed = [
                row
                for row in product_rows
                if row.get("analysis_feedback_id") is not None
                and bool(row.get("is_relevant"))
            ]
            current_scores = [
                float(row["sentiment_score"])
                for row in current_analyzed
                if row.get("sentiment_score") is not None
            ]
            baseline_scores = [
                float(row["sentiment_score"])
                for row in baseline_analyzed
                if row.get("sentiment_score") is not None
            ]
            complaint_rows = [
                row for row in current_analyzed if str(row.get("intent")) == "complaint"
            ]
            baseline_complaint_rows = [
                row for row in baseline_analyzed if str(row.get("intent")) == "complaint"
            ]
            all_complaint_rows = [
                row for row in all_analyzed if str(row.get("intent")) == "complaint"
            ]
            source_counts = Counter(str(row.get("source_group")) for row in current_rows)
            feedback_counts = Counter(
                str(row.get("primary_topic") or "other")
                for row in complaint_rows
            )
            problem_counts = Counter(
                str(row.get("subtopic") or row.get("primary_topic") or "other")
                for row in complaint_rows
            )
            baseline_feedback_counts = Counter(
                str(row.get("primary_topic") or "other")
                for row in baseline_complaint_rows
            )
            baseline_problem_counts = Counter(
                str(row.get("subtopic") or row.get("primary_topic") or "other")
                for row in baseline_complaint_rows
            )
            all_feedback_counts = Counter(
                str(row.get("primary_topic") or "other")
                for row in all_complaint_rows
            )
            all_problem_counts = Counter(
                str(row.get("subtopic") or row.get("primary_topic") or "other")
                for row in all_complaint_rows
            )
            rating_counts = Counter(
                max(1, min(5, int(float(row["rating"]) + 0.5)))
                for row in current_rows
                if row.get("rating") is not None
            )
            baseline_rating_counts = Counter(
                max(1, min(5, int(float(row["rating"]) + 0.5)))
                for row in baseline_rows
                if row.get("rating") is not None
            )
            all_rating_counts = Counter(
                max(1, min(5, int(float(row["rating"]) + 0.5)))
                for row in product_rows
                if row.get("rating") is not None
            )

            eligible_occurrences = [
                row["occurred_at"]
                for row in product_rows
                if self._dashboard_time_eligible(row)
                and isinstance(row.get("occurred_at"), datetime)
            ]
            trend_start = (
                min(eligible_occurrences)
                if dashboard_range == "all" and preset == "all" and eligible_occurrences
                else windows.current_start
            )
            trend_rows: dict[tuple[str, int], list[float]] = defaultdict(list)
            for row in product_rows:
                platform = platform_aliases.get(str(row.get("source_platform") or "").lower())
                occurred_at = row.get("occurred_at")
                if (
                    platform is None
                    or row.get("rating") is None
                    or not self._dashboard_time_eligible(row)
                    or not isinstance(occurred_at, datetime)
                    or occurred_at < trend_start
                    or occurred_at >= windows.current_end
                ):
                    continue
                week_index = (occurred_at - trend_start).days // 7
                trend_rows[(platform, week_index)].append(float(row["rating"]))

            rating_trend: list[DashboardRatingTrendPointView] = []
            for platform in marketplace_platforms:
                observed = sorted(
                    (week, values)
                    for (candidate, week), values in trend_rows.items()
                    if candidate == platform
                )
                if not observed:
                    continue
                observed_points: list[tuple[int, date, float, int]] = []
                for week, values in observed:
                    average = sum(values) / len(values)
                    point_date = (trend_start + timedelta(days=week * 7)).date()
                    observed_points.append((week, point_date, average, len(values)))
                    rating_trend.append(
                        DashboardRatingTrendPointView(
                            date=point_date,
                            platform=platform,
                            average_rating=average,
                            count=len(values),
                        )
                    )
                projection = projected_rating_point(platform, observed_points)
                if projection is not None:
                    rating_trend.append(projection)

            sentiment_rows: dict[int, Counter[str]] = defaultdict(Counter)
            for row in product_rows:
                sentiment = str(row.get("sentiment") or "")
                occurred_at = row.get("occurred_at")
                if (
                    sentiment not in {"positive", "negative", "neutral"}
                    or str(row.get("analysis_status")) != "completed"
                    or not bool(row.get("is_relevant"))
                    or not self._dashboard_time_eligible(row)
                    or not isinstance(occurred_at, datetime)
                    or occurred_at < trend_start
                    or occurred_at >= windows.current_end
                ):
                    continue
                week_index = (occurred_at - trend_start).days // 7
                sentiment_rows[week_index][sentiment] += 1

            product_sentiment_trend: list[DashboardSentimentTrendPointView] = []
            if sentiment_rows:
                for week in range(min(sentiment_rows), max(sentiment_rows) + 1):
                    counts = sentiment_rows[week]
                    product_sentiment_trend.append(
                        DashboardSentimentTrendPointView(
                            date=(trend_start + timedelta(days=week * 7)).date(),
                            total=sum(counts.values()),
                            positive=counts["positive"],
                            negative=counts["negative"],
                            neutral=counts["neutral"],
                        )
                    )
            sorted_feedback = sorted(
                ((label, feedback_counts[label]) for label in set(feedback_counts) | set(baseline_feedback_counts)),
                key=lambda item: (-item[1], item[0]),
            )
            sorted_problems = sorted(
                ((label, problem_counts[label]) for label in set(problem_counts) | set(baseline_problem_counts)),
                key=lambda item: (-item[1], item[0]),
            )
            sorted_all_feedback = sorted(
                all_feedback_counts.items(),
                key=lambda item: (-item[1], item[0]),
            )
            sorted_all_problems = sorted(
                all_problem_counts.items(),
                key=lambda item: (-item[1], item[0]),
            )
            products.append(
                DashboardProductView(
                    id=product_id,
                    name=name,
                    short_name=short_name,
                    category=category,
                    sku=sku,
                    pack=pack,
                    metadata_complete=bool(
                        product_id != "unattributed"
                        and _dashboard_dominant(names)
                        and category
                        and sku
                        and pack
                    ),
                    rating=sum(ratings) / len(ratings) if ratings else None,
                    rating_count=len(ratings),
                    total_feedback=len(product_rows),
                    current=period_counts(current_rows),
                    baseline=period_counts(baseline_rows),
                    overall=period_counts(product_rows),
                    sentiment_delta=(
                        100
                        * (
                            sum(current_scores) / len(current_scores)
                            - sum(baseline_scores) / len(baseline_scores)
                        )
                        if current_scores and baseline_scores
                        else None
                    ),
                    sources=dict(sorted(source_counts.items())),
                    themes=[
                        DashboardThemeView(label=label, count=count)
                        for label, count in sorted_problems
                    ],
                    rating_distribution=[
                        DashboardRatingCountView(rating=rating, count=rating_counts[rating])
                        for rating in range(5, 0, -1)
                        if rating_counts[rating]
                    ],
                    baseline_rating_distribution=[
                        DashboardRatingCountView(rating=rating, count=baseline_rating_counts[rating])
                        for rating in range(5, 0, -1)
                        if baseline_rating_counts[rating]
                    ],
                    all_rating_distribution=[
                        DashboardRatingCountView(rating=rating, count=all_rating_counts[rating])
                        for rating in range(5, 0, -1)
                        if all_rating_counts[rating]
                    ],
                    rating_trend=rating_trend,
                    sentiment_trend=product_sentiment_trend,
                    negative_feedback=[
                        DashboardComparisonThemeView(
                            label=label,
                            count=count,
                            baseline_count=baseline_feedback_counts[label],
                            percentage_change=(
                                None
                                if baseline_feedback_counts[label] == 0
                                else 100 * (count - baseline_feedback_counts[label]) / baseline_feedback_counts[label]
                            ),
                        )
                        for label, count in sorted_feedback
                    ],
                    problems=[
                        DashboardComparisonThemeView(
                            label=label,
                            count=count,
                            baseline_count=baseline_problem_counts[label],
                            percentage_change=(
                                None
                                if baseline_problem_counts[label] == 0
                                else 100 * (count - baseline_problem_counts[label]) / baseline_problem_counts[label]
                            ),
                        )
                        for label, count in sorted_problems
                    ],
                    all_negative_feedback=[
                        DashboardComparisonThemeView(label=label, count=count)
                        for label, count in sorted_all_feedback
                    ],
                    all_problems=[
                        DashboardComparisonThemeView(label=label, count=count)
                        for label, count in sorted_all_problems
                    ],
                )
            )
        products.sort(
            key=lambda product: (
                -product.current.complaints,
                -product.current.feedback,
                product.id == "unattributed",
                product.id,
            )
        )

        evidence: list[DashboardEvidenceView] = []
        for row in independent:
            if (
                self._dashboard_resolved_brand(row) != "guardian"
                or row.get("analysis_feedback_id") is None
                or not bool(row.get("is_relevant"))
            ):
                continue
            if dashboard_range != "all":
                if not self._dashboard_time_eligible(row):
                    continue
                occurred_at = row.get("occurred_at")
                if not isinstance(occurred_at, datetime) or not (
                    windows.current_start <= occurred_at < windows.current_end
                ):
                    continue
            sentiment = str(row.get("sentiment"))
            evidence.append(
                DashboardEvidenceView(
                    id=str(row["feedback_id"]),
                    product_id=_dashboard_product_id(row),
                    text=str(row.get("text_redacted") or ""),
                    source_group=str(row.get("source_group")),
                    source_platform=str(row.get("source_platform")),
                    source_url=_public_evidence_source_url(row),
                    timestamp=row.get("occurred_at"),
                    confidence=float(row.get("confidence") or 0),
                    stance=("contradict" if sentiment == "positive" else "support"),
                    topic=str(row.get("primary_topic") or "other"),
                    subtopic=str(row.get("subtopic") or "other"),
                    sentiment=sentiment,
                )
            )
        minimum_time = datetime.min.replace(tzinfo=timezone.utc)
        evidence.sort(
            key=lambda item: (
                item.timestamp is not None,
                _as_utc(item.timestamp) if item.timestamp is not None else minimum_time,
                item.confidence,
                item.id,
            ),
            reverse=True,
        )
        # The dashboard is an overview, not a bulk feedback export. Sample in
        # product rounds so one high-volume product cannot consume the whole
        # response before lower-volume products receive representative proof.
        evidence_by_product: dict[str, deque[DashboardEvidenceView]] = defaultdict(deque)
        for item in evidence:
            evidence_by_product[item.product_id].append(item)
        product_order = [
            product.id for product in products if product.id in evidence_by_product
        ]
        product_order.extend(
            sorted(set(evidence_by_product).difference(product_order))
        )
        sampled_evidence: list[DashboardEvidenceView] = []
        while len(sampled_evidence) < DASHBOARD_EVIDENCE_LIMIT:
            added = False
            for product_id in product_order:
                bucket = evidence_by_product[product_id]
                if not bucket:
                    continue
                sampled_evidence.append(bucket.popleft())
                added = True
                if len(sampled_evidence) == DASHBOARD_EVIDENCE_LIMIT:
                    break
            if not added:
                break
        evidence = sampled_evidence

        source_views = self._source_status_views("en")
        overall_health = (
            "failed"
            if any(item.status == "failed" for item in source_views)
            else "stale"
            if any(item.status == "stale" for item in source_views)
            else "partial"
            if not source_views or any(item.status == "partial" for item in source_views)
            else "healthy"
        )
        update_times = [
            value
            for row in rows
            for value in (row.get("ingested_at"), row.get("analyzed_at"))
            if isinstance(value, datetime)
        ]
        last_updated = max(update_times, default=self.as_of)
        primary_insight = (
            self._card_view(
                next(iter(self._built.values())), role="leadership", locale="en"
            )
            if self._built
            else None
        )
        return DashboardResponse(
            mode="demo" if self.settings.voc_demo_mode else "live",
            as_of=self.as_of,
            last_updated=last_updated,
            overall_health=overall_health,
            data_state=data_state,
            windows=DashboardWindowsView(
                current_start=windows.current_start,
                current_end=windows.current_end,
                baseline_start=windows.baseline_start,
                baseline_end=windows.baseline_end,
                business_timezone=windows.business_timezone,
            ),
            coverage=coverage,
            messages=messages,
            products=products,
            sentiment_trend=overall_sentiment_trend,
            sentiment_trend_granularity=sentiment_trend_granularity,
            evidence=evidence,
            word_cloud=_dashboard_word_cloud(
                guardian_independent if dashboard_range == "all" else guardian_current_rows
            ),
            primary_insight=primary_insight,
            benchmark=self._dashboard_benchmark(
                independent,
                current_start=windows.current_start,
                current_end=windows.current_end,
            ),
        )

    async def problem_detail(
        self,
        *,
        problem: str,
        preset: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> DashboardProblemDetailView:
        """Return one complaint cohort and an optional grounded AI summary."""

        self.initialize(seed_demo=self.settings.voc_demo_mode)
        normalized_problem = problem.strip().lower()
        if not re.fullmatch(r"[a-z0-9_]{1,80}", normalized_problem):
            raise ValueError("problem must be a valid taxonomy label")
        if preset not in {"7d", "30d", "1y", "all", "custom"}:
            raise ValueError("preset must be one of 7d, 30d, 1y, all, custom")

        windows = self._windows()
        business_zone = ZoneInfo(self.settings.voc_business_timezone)
        current_end = windows.current_end
        if preset == "all":
            period_start = period_end = None
            previous_start = previous_end = None
            period_label = "All time"
        elif preset == "custom":
            if start_date is None or end_date is None or end_date < start_date:
                raise ValueError("custom range requires a valid start and end date")
            period_start = datetime.combine(start_date, datetime.min.time(), business_zone)
            period_end = datetime.combine(end_date + timedelta(days=1), datetime.min.time(), business_zone)
            duration = period_end - period_start
            previous_start = period_start - duration
            previous_end = period_start
            period_label = f"{start_date.isoformat()} to {end_date.isoformat()}"
        else:
            days = {"7d": 7, "30d": 30, "1y": 365}[preset]
            period_end = current_end
            period_start = period_end - timedelta(days=days)
            previous_start = period_start - timedelta(days=days)
            previous_end = period_start
            period_label = {"7d": "Last 7 days", "30d": "Last 30 days", "1y": "Last year"}[preset]

        synthetic_clause = "" if self.settings.voc_demo_mode else "AND fi.is_synthetic = FALSE"
        rows = self.database.query(
            f"""
            SELECT fi.feedback_id, fi.repost_group_id, fi.source_group,
                fi.source_platform, fi.brand, fi.occurred_at, fi.occurred_at_quality,
                fi.text_redacted, fi.rating,
                fi.product_name, fi.sanitized_metadata, fi.source_url,
                fi.analysis_status,
                fa.feedback_id AS analysis_feedback_id, fa.is_relevant,
                fa.primary_brand, fa.brand_attribution_confidence,
                fa.brand_evidence_span, fa.primary_topic, fa.subtopic,
                fa.intent, fa.sentiment, fa.confidence
            FROM feedback_items fi
            LEFT JOIN feedback_analyses fa ON fa.feedback_id = fi.feedback_id
            WHERE fi.duplicate_of IS NULL
              {synthetic_clause}
            ORDER BY fi.feedback_id
            """
        )
        representatives: dict[str, Mapping[str, Any]] = {}
        for row in rows:
            unit_id = str(row.get("repost_group_id") or row["feedback_id"])
            representatives.setdefault(unit_id, row)
        complaints = [
            row
            for row in representatives.values()
            if self._dashboard_resolved_brand(row) == "guardian"
            and row.get("analysis_feedback_id") is not None
            and bool(row.get("is_relevant"))
            and str(row.get("intent")) == "complaint"
        ]

        def in_period(row: Mapping[str, Any], start: datetime | None, end: datetime | None) -> bool:
            if start is None or end is None:
                return True
            if not self._dashboard_time_eligible(row):
                return False
            occurred_at = row.get("occurred_at")
            return isinstance(occurred_at, datetime) and start <= occurred_at < end

        current_complaints = [row for row in complaints if in_period(row, period_start, period_end)]
        problem_rows = [
            row for row in current_complaints
            if str(row.get("subtopic") or row.get("primary_topic") or "other") == normalized_problem
        ]
        previous_problem_rows = [
            row for row in complaints
            if in_period(row, previous_start, previous_end)
            and str(row.get("subtopic") or row.get("primary_topic") or "other") == normalized_problem
        ] if previous_start is not None else []

        product_counts: Counter[str] = Counter()
        source_counts: Counter[str] = Counter()
        dated_counts: Counter[date] = Counter()
        reviews: list[ProblemReviewView] = []
        for row in problem_rows:
            product_id = _dashboard_product_id(row)
            product_name = _dashboard_text(row.get("product_name")) or (
                "Unattributed feedback" if product_id == "unattributed" else product_id
            )
            source_platform = str(row.get("source_platform") or "Unknown source")
            product_counts[product_name] += 1
            source_counts[source_platform] += 1
            occurred_at = row.get("occurred_at")
            if isinstance(occurred_at, datetime):
                dated_counts[occurred_at.date()] += 1
            reviews.append(ProblemReviewView(
                id=str(row["feedback_id"]),
                product_id=product_id,
                product_name=product_name,
                text=str(row.get("text_redacted") or ""),
                source_group=str(row.get("source_group") or "Unknown source group"),
                source_platform=source_platform,
                source_url=_dashboard_text(row.get("source_url")),
                timestamp=occurred_at if isinstance(occurred_at, datetime) else None,
                rating=float(row["rating"]) if row.get("rating") is not None else None,
                sentiment=str(row.get("sentiment") or "unknown"),
                confidence=float(row.get("confidence") or 0),
            ))
        reviews.sort(
            key=lambda item: (item.timestamp or datetime.min.replace(tzinfo=timezone.utc), item.id),
            reverse=True,
        )

        def top_breakdown(counts: Counter[str], limit: int = 5) -> list[ProblemBreakdownView]:
            return [
                ProblemBreakdownView(label=label, count=count)
                for label, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit]
            ]

        count = len(problem_rows)
        previous_count = len(previous_problem_rows) if previous_start is not None else None
        percentage_change = None if previous_count in {None, 0} else 100 * (count - previous_count) / previous_count
        top_products = top_breakdown(product_counts)
        top_sources = top_breakdown(source_counts)
        readable_problem = normalized_problem.replace("_", " ").title()
        if not count:
            deterministic_summary = f"No {readable_problem.lower()} complaints match this period."
        else:
            product_phrase = top_products[0].label if top_products else "the selected products"
            source_phrase = top_sources[0].label if top_sources else "the connected sources"
            deterministic_summary = (
                f"{count} {readable_problem.lower()} complaint{'s' if count != 1 else ''} were found "
                f"in this period. The largest concentrations are in {product_phrase} and "
                f"{source_phrase}; inspect the representative reviews below for the evidence."
            )

        summary = deterministic_summary
        summary_source = "deterministic"
        summary_model: str | None = None
        themes: list[ProblemSummaryThemeView] = []
        if (
            count
            and self.settings.ai_provider == "openai_compatible"
            and self.settings.ai_api_key
            and self.settings.ai_base_url
            and self.settings.ai_model
        ):
            provider = OpenAICompatibleProvider(
                base_url=self.settings.ai_base_url,
                api_key=self.settings.ai_api_key,
                model=self.settings.ai_model,
                timeout_seconds=self.settings.ai_request_timeout_seconds,
            )
            try:
                draft = await provider.summarize_problem(
                    problem=readable_problem,
                    total_complaints=count,
                    reviews=[{
                        "id": item.id,
                        "product": item.product_name,
                        "platform": item.source_platform,
                        "rating": item.rating,
                        "date": item.timestamp,
                        "text": item.text,
                    } for item in reviews[:50]],
                )
                summary = draft.summary
                themes = [theme for theme in draft.themes if theme.count <= count]
                summary_source = "ai"
                summary_model = provider.model_version
            except (AIProviderError, ValidationError, ValueError):
                pass
            finally:
                await provider.aclose()

        return DashboardProblemDetailView(
            problem=normalized_problem,
            count=count,
            total_complaints=len(current_complaints),
            share=(count / len(current_complaints)) if current_complaints else None,
            previous_count=previous_count,
            percentage_change=percentage_change,
            period_label=period_label,
            summary=summary,
            summary_source=summary_source,
            summary_model=summary_model,
            themes=themes,
            trend=[ProblemTrendPointView(date=day, count=value) for day, value in sorted(dated_counts.items())],
            products=top_products,
            sources=top_sources,
            reviews=reviews[:20],
        )

    def today(self, *, role: Role, locale: str | None = None) -> TodayResponse:
        self.initialize(seed_demo=self.settings.voc_demo_mode)
        locale = locale or self.settings.voc_default_locale
        # _rebuild_insights inserts the deterministic ranking winners first.
        # Today is therefore topic-agnostic while the demo retains its seeded
        # order through the same ranking path.
        built_order = list(self._built.values())[:3]
        cards = [self._card_view(item, role=role, locale=locale) for item in built_order]
        count_row = self.database.query_one(
            """
            SELECT count(*) AS total,
                count(DISTINCT coalesce(repost_group_id, feedback_id)) AS independent,
                count(DISTINCT source_group) AS groups
            FROM feedback_items WHERE duplicate_of IS NULL
            """
        ) or {"total": 0, "independent": 0, "groups": 0}
        analyzed_row = self.database.query_one(
            "SELECT count(*) AS count FROM feedback_analyses"
        ) or {"count": 0}
        source_views = self._source_status_views(locale)
        overall = (
            "failed"
            if any(item.status == "failed" for item in source_views)
            else "stale"
            if any(item.status == "stale" for item in source_views)
            else "partial"
            if not source_views or any(item.status == "partial" for item in source_views)
            else "healthy"
        )
        by_label = Counter(card.label for card in cards)
        act = next(
            (card for card in cards if card.label in {"act_now", "market_gap"}),
            None,
        )
        watch = next((card for card in cards if card.label == "watch"), None)
        improving = next((card for card in cards if card.label == "improving"), None)
        analysis_coverage = self._analysis_coverage()
        analysis_incomplete = int(count_row["total"]) > 0 and analysis_coverage < 0.80
        readiness = self._live_evidence_readiness()
        thresholds = self._thresholds()
        evidence_insufficient = (
            readiness["current_signals"]
            < thresholds.min_current_denominator * thresholds.min_source_groups
            or readiness["baseline_signals"]
            < thresholds.min_baseline_denominator * thresholds.min_source_groups
            or readiness["source_groups"] < thresholds.min_source_groups
        )
        messages: list[str] = []
        if not self.settings.voc_demo_mode and analysis_incomplete:
            messages.append(
                (
                    "Bước tiếp theo: để phân loại hoàn tất; tín hiệu được giữ lại cho đến khi "
                    "độ phủ phân tích đạt ít nhất 80%."
                    if locale == "vi"
                    else "Best next step: let classification finish; signals stay withheld until "
                    "analysis coverage reaches at least 80%."
                )
            )
        elif not self.settings.voc_demo_mode and evidence_insufficient:
            messages.append(
                (
                    "Bước tiếp theo: kết nối phản hồi Guardian có ngày từ kênh sở hữu hoặc "
                    "chăm sóc khách hàng; phản hồi công khai hiện tại chưa có ngày xảy ra đáng tin cậy."
                    if locale == "vi"
                    else "Best next step: connect dated Guardian-owned or customer-support "
                    "feedback; current public feedback has no trustworthy occurrence dates."
                )
                if int(count_row["total"]) > 0
                else (
                    "Bước tiếp theo: thu thập phản hồi Guardian có ngày từ kênh sở hữu hoặc "
                    "chăm sóc khách hàng, hoặc bật đọc toàn bộ nội dung trang."
                    if locale == "vi"
                    else "Best next step: collect dated Guardian-owned or customer-support "
                    "feedback, or enable full page reading."
                )
            )
        elif not self.settings.voc_demo_mode and overall != "healthy":
            messages.append(
                (
                    "Bước tiếp theo: khôi phục nguồn đã lỗi hoặc quá hạn; các tín hiệu liên quan "
                    "đang được giữ lại."
                    if locale == "vi"
                    else "Best next step: restore failed or stale sources; affected signals are "
                    "being withheld."
                )
            )
        if locale == "vi":
            empty_act = (
                "Phân tích đang hoàn tất."
                if not self.settings.voc_demo_mode and analysis_incomplete
                else "Chưa đủ phản hồi Guardian có ngày để đưa ra quyết định."
                if not self.settings.voc_demo_mode and evidence_insufficient
                else "Không phát hiện vấn đề trọng yếu."
            )
            brief = [
                BriefLineView(kind="act", insight_id=act.insight_id if act else None, text=act.title if act else empty_act),
                BriefLineView(kind="watch", insight_id=watch.insight_id if watch else None, text=watch.title if watch else "Không có tín hiệu cần theo dõi thêm."),
                BriefLineView(kind="improving", insight_id=improving.insight_id if improving else None, text=improving.title if improving else "Chưa có tín hiệu cải thiện đủ bằng chứng."),
            ]
        else:
            empty_act = (
                "Analysis is still catching up."
                if not self.settings.voc_demo_mode and analysis_incomplete
                else "Not enough dated Guardian feedback for a decision yet."
                if not self.settings.voc_demo_mode and evidence_insufficient
                else "No material issue detected."
            )
            brief = [
                BriefLineView(kind="act", insight_id=act.insight_id if act else None, text=act.title if act else empty_act),
                BriefLineView(kind="watch", insight_id=watch.insight_id if watch else None, text=watch.title if watch else "No additional watch signal."),
                BriefLineView(kind="improving", insight_id=improving.insight_id if improving else None, text=improving.title if improving else "No evidenced improving signal yet."),
            ]
        market_takeaway = next(
            (card.market_context for card in cards if card.market_context),
            None,
        )
        return TodayResponse(
            mode="demo" if self.settings.voc_demo_mode else "live",
            demo_label="Demo data — synthetic" if self.settings.voc_demo_mode else None,
            as_of=self.as_of,
            last_updated=max(
                (item.last_success_at for item in source_views if item.last_success_at),
                default=self.as_of,
            ),
            role=role,
            locale=locale,
            overall_health=overall,
            source_statuses=source_views,
            coverage=CoverageView(
                feedback_items=int(count_row["total"]),
                independent_signals=int(count_row["independent"]),
                source_groups=int(count_row["groups"]),
                analyzed_items=int(analyzed_row["count"]),
                analysis_coverage=analysis_coverage,
                act_now_count=by_label["act_now"],
                watch_count=by_label["watch"],
                improving_count=by_label["improving"],
            ),
            brief=brief,
            cards=cards,
            market_takeaway=market_takeaway,
            messages=messages,
        )

    def insights(self) -> list[InsightCardView]:
        return self.today(role="leadership").cards

    def insight(self, insight_id: str) -> InsightCardView | None:
        self.initialize(seed_demo=self.settings.voc_demo_mode)
        built = self._built.get(insight_id)
        return None if built is None else self._card_view(built, role="leadership", locale="en")

    def evidence(self, insight_id: str) -> EvidenceResponse | None:
        card = self.insight(insight_id)
        built = self._built.get(insight_id)
        if card is None or built is None:
            return None
        events = [event.model_dump(mode="json") for event in built.card.fact_packet.business_events]
        return EvidenceResponse(
            insight=card,
            current_definition=(
                "Latest seven completed business days; independent, relevant, successfully analyzed feedback."
            ),
            baseline_definition=(
                "Preceding 28 completed days; each source-platform stratum keeps its baseline denominator weight."
            ),
            competitor_definition=(
                "Public feedback only; common platform, category, language, and experience-subject strata use identical pooled weights."
                if built.benchmark is not None
                else None
            ),
            evidence=self._evidence_preview(insight_id),
            business_events=events,
            fact_packet=built.card.fact_packet.model_dump(mode="json"),
        )

    def feedback(
        self,
        *,
        source_group: str | None,
        source_platform: str | None,
        brand: str | None,
        topic: str | None,
        sentiment: str | None,
        insight_id: str | None,
        query: str | None,
        date_from: date | None,
        date_to: date | None,
        min_confidence: float | None,
        max_confidence: float | None,
        limit: int,
        offset: int,
    ) -> FeedbackListResponse:
        self.initialize(seed_demo=self.settings.voc_demo_mode)
        clauses = ["fi.duplicate_of IS NULL"]
        params: list[object] = []
        if date_from is not None and date_to is not None and date_to < date_from:
            raise ValueError("date_to must be on or after date_from")
        if (
            min_confidence is not None
            and max_confidence is not None
            and max_confidence < min_confidence
        ):
            raise ValueError("max_confidence must be greater than or equal to min_confidence")
        if not self.settings.voc_demo_mode:
            clauses.append("fi.is_synthetic = FALSE")
        if source_group:
            clauses.append("fi.source_group = ?")
            params.append(source_group)
        if source_platform:
            clauses.append("fi.source_platform = ?")
            params.append(source_platform)
        if brand:
            clauses.append("coalesce(fi.brand, fa.primary_brand) = ?")
            params.append(brand)
        if topic:
            clauses.append("fa.primary_topic = ?")
            params.append(topic)
        if sentiment:
            clauses.append("fa.sentiment = ?")
            params.append(sentiment)
        if insight_id:
            clauses.append("EXISTS (SELECT 1 FROM insight_evidence ie WHERE ie.feedback_id = fi.feedback_id AND ie.insight_id = ?)")
            params.append(insight_id)
        if query:
            clauses.append("fi.text_redacted ILIKE ?")
            params.append(f"%{query}%")
        zone = ZoneInfo(self.settings.voc_business_timezone)
        if date_from is not None:
            clauses.append("fi.occurred_at >= ?")
            params.append(
                datetime.combine(date_from, datetime.min.time(), tzinfo=zone).astimezone(
                    timezone.utc
                )
            )
        if date_to is not None:
            clauses.append("fi.occurred_at < ?")
            params.append(
                datetime.combine(
                    date_to + timedelta(days=1), datetime.min.time(), tzinfo=zone
                ).astimezone(timezone.utc)
            )
        if min_confidence is not None:
            clauses.append("fa.confidence >= ?")
            params.append(min_confidence)
        if max_confidence is not None:
            clauses.append("fa.confidence <= ?")
            params.append(max_confidence)
        where = " AND ".join(clauses)
        count = self.database.query_one(
            f"""
            SELECT count(*) AS count,
                count(*) FILTER (WHERE fi.is_synthetic) AS synthetic_count
            FROM feedback_items fi
            LEFT JOIN feedback_analyses fa ON fa.feedback_id = fi.feedback_id
            WHERE {where}
            """,
            params,
        ) or {"count": 0, "synthetic_count": 0}
        rows = self.database.query(
            f"""
            SELECT fi.feedback_id, fi.occurred_at, fi.observed_at,
                fi.occurred_at_quality, fi.source_group,
                fi.source_platform, fi.source_url,
                coalesce(fi.brand, fa.primary_brand) AS brand,
                fa.primary_topic, fa.subtopic, fa.intent, fa.sentiment,
                fa.confidence, fi.rating, fi.product_name, fi.product_category,
                fi.store, fi.text_redacted, fi.is_synthetic,
                coalesce(list(ie.insight_id) FILTER (WHERE ie.insight_id IS NOT NULL), []) AS insight_ids
            FROM feedback_items fi
            LEFT JOIN feedback_analyses fa ON fa.feedback_id = fi.feedback_id
            LEFT JOIN insight_evidence ie ON ie.feedback_id = fi.feedback_id
            WHERE {where}
            GROUP BY ALL
            ORDER BY fi.occurred_at DESC NULLS LAST, fi.feedback_id
            LIMIT ? OFFSET ?
            """,
            [*params, limit, offset],
        )
        return FeedbackListResponse(
            items=[
                FeedbackListItem(
                    feedback_id=str(row["feedback_id"]),
                    occurred_at=row.get("occurred_at"),
                    observed_at=row["observed_at"],
                    occurred_at_quality=str(row["occurred_at_quality"]),
                    source_group=str(row["source_group"]),
                    source_platform=str(row["source_platform"]),
                    source_url=row.get("source_url"),
                    brand=row.get("brand"),
                    topic=row.get("primary_topic"),
                    subtopic=row.get("subtopic"),
                    intent=row.get("intent"),
                    sentiment=row.get("sentiment"),
                    confidence=row.get("confidence"),
                    rating=row.get("rating"),
                    product_name=row.get("product_name"),
                    product_category=row.get("product_category"),
                    store=row.get("store"),
                    text_redacted=str(row["text_redacted"]),
                    insight_ids=[str(item) for item in (row.get("insight_ids") or [])],
                    is_synthetic=bool(row["is_synthetic"]),
                )
                for row in rows
            ],
            mode="demo" if self.settings.voc_demo_mode else "live",
            synthetic_items=int(count["synthetic_count"]),
            total=int(count["count"]),
            limit=limit,
            offset=offset,
        )

    def benchmarks(self) -> dict[str, Any]:
        built = self._built.get("insight-price-promotion")
        return (
            {"comparable": False, "reason": "Not enough comparable public feedback"}
            if built is None or built.benchmark is None
            else built.benchmark.model_dump(mode="json")
        )

    def data_health(self) -> dict[str, Any]:
        sources = self._source_status_views("en")
        return {
            "as_of": self.as_of.isoformat(),
            "sources": [item.model_dump(mode="json") for item in sources],
            "analysis_coverage": self._analysis_coverage(),
        }

    def patch_insight(
        self, insight_id: str, payload: InsightPatchRequest
    ) -> InsightCardView | None:
        self.initialize(seed_demo=self.settings.voc_demo_mode)
        row = self.database.query_one(
            "SELECT * FROM insight_cards WHERE insight_id = ?", [insight_id]
        )
        if row is None:
            return None
        if payload.primary_owner is not None:
            allowed = {"Customer Service", "Commercial", "Marketing", "E-commerce"}
            if payload.primary_owner not in allowed:
                raise ValueError("primary_owner is outside the approved team list")
            self.database.execute(
                "UPDATE insight_cards SET primary_owner = ?, updated_at = ? WHERE insight_id = ?",
                [payload.primary_owner, utc_now(), insight_id],
            )
        if payload.status is not None:
            reference = row["observation_id"] if payload.status == "monitoring" else None
            self.database.execute(
                "UPDATE insight_cards SET status = ?, updated_at = ? WHERE insight_id = ?",
                [payload.status, utc_now(), insight_id],
            )
            self.database.execute(
                "INSERT INTO insight_status_history VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    f"status_{uuid.uuid4().hex}",
                    row["insight_series_id"],
                    payload.status,
                    utc_now(),
                    "api-admin",
                    payload.note,
                    reference,
                ],
            )
        return self.insight(insight_id)

    def live_ai_smoke(self) -> dict[str, Any]:
        if self.settings.ai_provider != "openai_compatible":
            raise RuntimeError("Set AI_PROVIDER=openai_compatible for the opt-in live smoke test")
        row = self.database.query_one("SELECT * FROM feedback_items ORDER BY feedback_id LIMIT 1")
        if row is None:
            raise RuntimeError("No feedback is available; seed or import one record first")
        provider = OpenAICompatibleProvider(
            base_url=self.settings.ai_base_url,
            api_key=self.settings.ai_api_key,
            model=self.settings.ai_model,
            timeout_seconds=self.settings.ai_request_timeout_seconds,
        )
        try:
            result = asyncio.run(provider.classify(self._classification_request(row)))
        finally:
            asyncio.run(provider.aclose())
        return {"model": provider.model_version, "classification": result.model_dump(mode="json")}


@lru_cache(maxsize=1)
def get_service() -> GuardianService:
    return GuardianService(get_settings())


__all__ = ["GuardianService", "get_service"]
