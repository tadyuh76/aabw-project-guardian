"""Canonical feedback and ingestion schemas.

``RawFeedback`` is the connector boundary.  ``FeedbackItem`` is the only
shape written to the durable store and therefore contains redacted text and
hashed identifiers only.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SourceGroup(StrEnum):
    MARKETPLACE = "marketplace"
    OWNED = "owned"
    CUSTOMER_SERVICE = "customer_service"
    SOCIAL = "social"


class Visibility(StrEnum):
    OWNED = "owned"
    PUBLIC = "public"


class Brand(StrEnum):
    GUARDIAN = "guardian"
    HASAKI = "hasaki"
    WATSONS = "watsons"
    OTHER = "other"


class OccurredAtQuality(StrEnum):
    EXACT = "exact"
    PARSED = "parsed"
    INFERRED = "inferred"
    MISSING = "missing"


class BrandAttribution(StrEnum):
    SOURCE_FIXED = "source_fixed"
    AI_PRIMARY = "ai_primary"
    AMBIGUOUS = "ambiguous"
    UNKNOWN = "unknown"


class ExperienceSubject(StrEnum):
    RETAILER = "retailer"
    PRODUCT = "product"
    DELIVERY_PARTNER = "delivery_partner"
    UNKNOWN = "unknown"


class QualityStatus(StrEnum):
    VALID = "valid"
    PARTIAL = "partial"
    QUARANTINED = "quarantined"


class AnalysisStatus(StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"
    LOW_CONFIDENCE = "low_confidence"
    FAILED = "failed"
    SKIPPED = "skipped"


class IngestionRunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


class SourceHealthStatus(StrEnum):
    HEALTHY = "healthy"
    STALE = "stale"
    PARTIAL = "partial"
    FAILED = "failed"


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must include a timezone")
    return value.astimezone(timezone.utc)


class RawFeedback(BaseModel):
    """Source-neutral record emitted by every connector.

    Direct identifiers are accepted only at this ephemeral boundary.  They
    are hashed by the normalization stage and are never written verbatim to
    ``feedback_items``.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    source_external_id: str | None = None
    source_group: SourceGroup
    source_platform: str = Field(min_length=1, max_length=100)
    visibility: Visibility
    brand: Brand | None = None
    brand_candidates: list[Brand] = Field(default_factory=list)
    occurred_at: datetime | None = None
    observed_at: datetime
    occurred_at_quality: OccurredAtQuality = OccurredAtQuality.MISSING
    original_timezone: str | None = None
    language: str | None = None
    language_confidence: float | None = Field(default=None, ge=0, le=1)
    title: str | None = Field(default=None, max_length=2_000)
    text: str = Field(min_length=1, max_length=500_000)
    rating: float | None = Field(default=None, ge=0, le=5)
    product_name: str | None = Field(default=None, max_length=1_000)
    product_category: str | None = Field(default=None, max_length=500)
    region: str | None = Field(default=None, max_length=500)
    store: str | None = Field(default=None, max_length=500)
    source_url: str | None = Field(default=None, max_length=8_192)
    author_id: str | None = Field(default=None, max_length=4_096)
    conversation_id: str | None = Field(default=None, max_length=4_096)
    message_count: int | None = Field(default=None, ge=1)
    media_urls: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    is_synthetic: bool = False

    @field_validator("observed_at", "occurred_at")
    @classmethod
    def _normalize_datetimes(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _aware_utc(value)

    @field_validator("brand_candidates")
    @classmethod
    def _unique_brand_candidates(cls, value: list[Brand]) -> list[Brand]:
        return list(dict.fromkeys(value))

    @field_validator("language")
    @classmethod
    def _normalize_language(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower().replace("_", "-")
        aliases = {
            "eng": "en",
            "english": "en",
            "en-us": "en",
            "en-gb": "en",
            "vie": "vi",
            "vietnamese": "vi",
            "vi-vn": "vi",
            "und": "unknown",
        }
        return aliases.get(normalized, normalized)

    @model_validator(mode="after")
    def _validate_contract(self) -> "RawFeedback":
        if not self.text.strip():
            raise ValueError("text must contain non-whitespace characters")
        if self.brand is None and not self.brand_candidates:
            raise ValueError("brand or at least one brand_candidate is required")
        if self.brand is not None and self.brand not in self.brand_candidates:
            self.brand_candidates.insert(0, self.brand)
        if self.occurred_at is None:
            self.occurred_at_quality = OccurredAtQuality.MISSING
        elif self.occurred_at_quality is OccurredAtQuality.MISSING:
            self.occurred_at_quality = OccurredAtQuality.PARSED
        if self.language is None:
            self.language_confidence = None
        if self.source_group is SourceGroup.CUSTOMER_SERVICE and self.visibility is not Visibility.OWNED:
            raise ValueError("customer_service feedback must have owned visibility")
        return self


class FeedbackItem(BaseModel):
    """Privacy-safe canonical record stored in DuckDB."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    feedback_id: str = Field(min_length=8, max_length=100)
    ingestion_run_id: str = Field(min_length=1, max_length=100)
    source_external_id: str | None = None
    source_group: SourceGroup
    source_platform: str
    visibility: Visibility
    brand: Brand | None = None
    brand_candidates: list[Brand] = Field(default_factory=list)
    brand_attribution: BrandAttribution = BrandAttribution.UNKNOWN
    experience_subject: ExperienceSubject = ExperienceSubject.UNKNOWN
    occurred_at: datetime | None = None
    observed_at: datetime
    occurred_at_quality: OccurredAtQuality
    ingested_at: datetime
    original_timezone: str | None = None
    language: str = "unknown"
    language_confidence: float | None = Field(default=None, ge=0, le=1)
    title: str | None = None
    text_redacted: str = Field(min_length=1, max_length=100_000)
    rating: float | None = Field(default=None, ge=0, le=5)
    product_name: str | None = None
    product_category: str | None = None
    region: str | None = None
    store: str | None = None
    source_url: str | None = None
    canonical_url: str | None = None
    author_hash: str | None = None
    conversation_hash: str | None = None
    message_count: int | None = Field(default=None, ge=1)
    media_urls: list[str] = Field(default_factory=list)
    content_hash: str = Field(min_length=64, max_length=64)
    content_fingerprint: str | None = Field(default=None, min_length=64, max_length=64)
    repost_group_id: str | None = None
    crawler_record_id: str | None = None
    sanitized_metadata: dict[str, Any] = Field(default_factory=dict)
    is_synthetic: bool = False
    quality_status: QualityStatus = QualityStatus.VALID
    duplicate_of: str | None = None
    analysis_status: AnalysisStatus = AnalysisStatus.PENDING

    @field_validator("observed_at", "occurred_at", "ingested_at")
    @classmethod
    def _normalize_datetimes(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _aware_utc(value)

    @model_validator(mode="after")
    def _validate_storage_contract(self) -> "FeedbackItem":
        if self.occurred_at is None and self.occurred_at_quality is not OccurredAtQuality.MISSING:
            raise ValueError("a missing occurrence time must use occurred_at_quality=missing")
        if self.occurred_at is not None and self.occurred_at_quality is OccurredAtQuality.MISSING:
            raise ValueError("a present occurrence time cannot use occurred_at_quality=missing")
        if self.visibility is Visibility.OWNED and self.repost_group_id is not None:
            raise ValueError("owned feedback must never be grouped as a public repost")
        return self


class IngestionRun(BaseModel):
    """Connector execution context and persisted run counters."""

    model_config = ConfigDict(extra="forbid")

    id: str
    connector: str
    source_name: str
    source_file: str | None = None
    status: IngestionRunStatus = IngestionRunStatus.QUEUED
    started_at: datetime
    completed_at: datetime | None = None
    records_seen: int = Field(default=0, ge=0)
    records_inserted: int = Field(default=0, ge=0)
    records_updated: int = Field(default=0, ge=0)
    records_skipped: int = Field(default=0, ge=0)
    records_failed: int = Field(default=0, ge=0)
    error_summary: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("started_at", "completed_at")
    @classmethod
    def _normalize_datetimes(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _aware_utc(value)


class SourceStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_name: str
    source_group: SourceGroup
    last_success_at: datetime | None = None
    last_attempt_at: datetime | None = None
    last_record_at: datetime | None = None
    status: SourceHealthStatus
    recent_volume: int = Field(default=0, ge=0)
    expected_volume_range: dict[str, int | float] = Field(default_factory=dict)
    failure_rate: float = Field(default=0, ge=0, le=1)
    notes: str | None = None

    @field_validator("last_success_at", "last_attempt_at", "last_record_at")
    @classmethod
    def _normalize_datetimes(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _aware_utc(value)


__all__ = [
    "AnalysisStatus",
    "Brand",
    "BrandAttribution",
    "ExperienceSubject",
    "FeedbackItem",
    "IngestionRun",
    "IngestionRunStatus",
    "OccurredAtQuality",
    "QualityStatus",
    "RawFeedback",
    "SourceGroup",
    "SourceHealthStatus",
    "SourceStatus",
    "Visibility",
]
