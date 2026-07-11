"""Strict, provider-neutral schemas for classification and deterministic analytics.

The models in this module deliberately contain no database or model-provider
objects.  Repositories can map rows into :class:`AnalyticsUnit`, and every
analytics function can consequently be replayed in tests or an offline demo.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from enum import StrEnum
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from guardian_voc.schemas.feedback import (
    Brand,
    ExperienceSubject,
    OccurredAtQuality,
    SourceGroup,
    Visibility,
)


class StrictModel(BaseModel):
    """Base model used at trust boundaries."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class FrozenModel(StrictModel):
    """A shallowly immutable value object.

    Collection fields in the public schemas use tuples as well, making fact
    inputs safe to retain across insight-writing attempts.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)


class PrimaryTopic(StrEnum):
    PRODUCT_QUALITY_AUTHENTICITY = "product_quality_authenticity"
    PRICE_PROMOTION = "price_promotion"
    AVAILABILITY_ASSORTMENT = "availability_assortment"
    DELIVERY_FULFILMENT = "delivery_fulfilment"
    ONLINE_CHECKOUT_PAYMENT = "online_checkout_payment"
    STORE_STAFF_EXPERIENCE = "store_staff_experience"
    CUSTOMER_SERVICE = "customer_service"
    RETURNS_REFUNDS = "returns_refunds"
    LOYALTY_MEMBERSHIP = "loyalty_membership"
    OTHER = "other"


SUBTOPICS_BY_TOPIC: dict[PrimaryTopic, frozenset[str]] = {
    PrimaryTopic.PRODUCT_QUALITY_AUTHENTICITY: frozenset(
        {
            "suspected_counterfeit",
            "damaged_product",
            "expired_product",
            "packaging_quality",
            "adverse_reaction",
            "product_performance",
            "authenticity_praise",
        }
    ),
    PrimaryTopic.PRICE_PROMOTION: frozenset(
        {
            "voucher_not_applied",
            "unclear_eligibility",
            "missing_gift",
            "price_mismatch",
            "good_value",
        }
    ),
    PrimaryTopic.AVAILABILITY_ASSORTMENT: frozenset(
        {
            "out_of_stock",
            "order_cancelled_out_of_stock",
            "assortment_gap",
            "restock_request",
            "availability_praise",
        }
    ),
    PrimaryTopic.DELIVERY_FULFILMENT: frozenset(
        {
            "late_delivery",
            "damaged_package",
            "missing_item",
            "wrong_item",
            "tracking_problem",
            "fast_delivery",
        }
    ),
    PrimaryTopic.ONLINE_CHECKOUT_PAYMENT: frozenset(
        {
            "payment_failed",
            "checkout_error",
            "duplicate_charge",
            "payment_method_unavailable",
            "checkout_ease",
        }
    ),
    PrimaryTopic.STORE_STAFF_EXPERIENCE: frozenset(
        {
            "unhelpful_staff",
            "rude_staff",
            "wait_time",
            "product_advice",
            "helpful_staff",
        }
    ),
    PrimaryTopic.CUSTOMER_SERVICE: frozenset(
        {
            "slow_response",
            "unresolved_case",
            "poor_response",
            "difficult_contact",
            "helpful_resolution",
        }
    ),
    PrimaryTopic.RETURNS_REFUNDS: frozenset(
        {
            "refund_delay",
            "return_rejected",
            "unclear_policy",
            "return_process",
            "fast_refund",
        }
    ),
    PrimaryTopic.LOYALTY_MEMBERSHIP: frozenset(
        {
            "points_missing",
            "earn_redeem_problem",
            "unclear_benefits",
            "account_problem",
            "valuable_benefits",
        }
    ),
    PrimaryTopic.OTHER: frozenset({"other"}),
}


class Intent(StrEnum):
    COMPLAINT = "complaint"
    PRAISE = "praise"
    QUESTION_REQUEST = "question_request"
    SUGGESTION = "suggestion"
    PURCHASE_CONSIDERATION = "purchase_consideration"


class Sentiment(StrEnum):
    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"


class Urgency(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class JourneyStage(StrEnum):
    AWARENESS = "awareness"
    CONSIDERATION = "consideration"
    PRODUCT_DETAIL = "product_detail"
    PROMOTION = "promotion"
    CART = "cart"
    CHECKOUT = "checkout"
    PAYMENT = "payment"
    FULFILMENT = "fulfilment"
    DELIVERY = "delivery"
    STORE = "store"
    POST_PURCHASE = "post_purchase"
    RETURNS = "returns"
    LOYALTY = "loyalty"
    SUPPORT = "support"
    UNKNOWN = "unknown"


class HealthStatus(StrEnum):
    HEALTHY = "healthy"
    STALE = "stale"
    PARTIAL = "partial"
    FAILED = "failed"
    UNKNOWN = "unknown"


class ClassificationResult(StrictModel):
    """Exact structured output requested from the item classifier."""

    is_relevant: bool
    primary_brand: Brand | None
    mentioned_brands: tuple[Brand, ...] = ()
    brand_attribution_confidence: float = Field(ge=0.0, le=1.0)
    brand_evidence_span: str | None = Field(default=None, max_length=240)
    experience_subject: ExperienceSubject
    primary_topic: PrimaryTopic
    subtopic: str = Field(min_length=1, max_length=80)
    intent: Intent
    sentiment: Sentiment
    sentiment_score: float = Field(ge=-1.0, le=1.0)
    urgency: Urgency
    customer_stated_reason: str | None = Field(default=None, max_length=500)
    journey_stage: JourneyStage
    evidence_span: str = Field(min_length=1, max_length=1_000)
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("mentioned_brands")
    @classmethod
    def deduplicate_brands(cls, value: tuple[Brand, ...]) -> tuple[Brand, ...]:
        if len(set(value)) != len(value):
            raise ValueError("mentioned_brands must not contain duplicates")
        return value

    @model_validator(mode="after")
    def validate_taxonomy_relationships(self) -> ClassificationResult:
        if self.subtopic not in SUBTOPICS_BY_TOPIC[self.primary_topic]:
            raise ValueError(
                f"subtopic {self.subtopic!r} is not valid for {self.primary_topic.value}"
            )
        if self.primary_brand is not None and self.primary_brand not in self.mentioned_brands:
            raise ValueError("primary_brand must be included in mentioned_brands")
        return self


class TrustedSourceMetadata(FrozenModel):
    """Allow-listed metadata safe to include in an external model request."""

    source_group: SourceGroup
    source_platform: str = Field(min_length=1, max_length=80)
    visibility: Visibility
    source_fixed_brand: Brand | None = None
    product_category: str | None = Field(default=None, max_length=120)
    language: str | None = Field(default=None, max_length=16)


class ClassificationRequest(FrozenModel):
    """Sanitized classifier input.

    Deliberately absent: raw identifiers, author information, media URLs,
    arbitrary connector metadata, and source URLs.
    """

    content_hash: str = Field(min_length=16, max_length=128)
    text_redacted: str = Field(min_length=1, max_length=12_000)
    trusted_metadata: TrustedSourceMetadata
    brand_candidates: tuple[Brand, ...]
    prompt_version: str = Field(default="item-classifier-v2", min_length=1, max_length=80)
    taxonomy_version: str = Field(default="voc-v1", min_length=1, max_length=80)

    @field_validator("brand_candidates")
    @classmethod
    def validate_candidates(cls, value: tuple[Brand, ...]) -> tuple[Brand, ...]:
        if not value:
            raise ValueError("at least one brand candidate is required")
        if len(set(value)) != len(value):
            raise ValueError("brand_candidates must be unique")
        return value

    def cache_key(self, model_version: str) -> str:
        material = {
            "content_hash": self.content_hash,
            "prompt_version": self.prompt_version,
            "taxonomy_version": self.taxonomy_version,
            "model_version": model_version,
        }
        return hashlib.sha256(
            json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()


class FeedbackAnalysis(FrozenModel):
    feedback_id: str = Field(min_length=1, max_length=200)
    result: ClassificationResult
    model_version: str
    prompt_version: str
    taxonomy_version: str
    analyzed_at: datetime
    review_required: bool = False


class AnalyticsUnit(FrozenModel):
    """The independent unit consumed by metric and benchmark functions.

    Ingestion should set ``analytics_unit_id`` to a feedback ID for ordinary
    records and to the repost-group ID for public exact reposts.  Analytics
    defensively collapses duplicate IDs again before calculating any rate.
    """

    analytics_unit_id: str = Field(min_length=1, max_length=200)
    feedback_id: str = Field(min_length=1, max_length=200)
    resolved_brand: Brand | None
    visibility: Visibility
    source_group: SourceGroup
    source_platform: str = Field(min_length=1, max_length=80)
    experience_subject: ExperienceSubject
    occurred_at: datetime | None
    occurred_at_quality: OccurredAtQuality
    language: str | None = Field(default=None, max_length=16)
    product_category: str | None = Field(default=None, max_length=120)
    region: str | None = Field(default=None, max_length=120)
    store: str | None = Field(default=None, max_length=120)
    is_relevant: bool
    analysis_succeeded: bool = True
    analysis_confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    primary_topic: PrimaryTopic
    subtopic: str
    sentiment: Sentiment
    urgency: Urgency = Urgency.NORMAL
    customer_stated_reason: str | None = Field(default=None, max_length=500)
    journey_stage: JourneyStage = JourneyStage.UNKNOWN
    rating: float | None = Field(default=None, ge=0.0, le=5.0)

    @model_validator(mode="after")
    def validate_occurrence(self) -> AnalyticsUnit:
        if self.occurred_at_quality is OccurredAtQuality.MISSING and self.occurred_at:
            raise ValueError("missing occurred_at_quality requires occurred_at=None")
        if self.occurred_at_quality is not OccurredAtQuality.MISSING and not self.occurred_at:
            raise ValueError("dated quality requires occurred_at")
        return self


class SourceStratum(FrozenModel):
    brand: Brand
    source_group: SourceGroup
    source_platform: str
    experience_subject: ExperienceSubject

    def stable_key(self) -> str:
        return "|".join(
            (
                self.brand.value,
                self.source_group.value,
                self.source_platform,
                self.experience_subject.value,
            )
        )


class SourceHealthSnapshot(FrozenModel):
    stratum: SourceStratum
    status: HealthStatus
    last_success_at: datetime | None = None
    recent_volume: int = Field(default=0, ge=0)
    expected_volume_min: int | None = Field(default=None, ge=0)
    expected_volume_max: int | None = Field(default=None, ge=0)
    timestamp_coverage: float = Field(default=1.0, ge=0.0, le=1.0)
    duplicate_share: float = Field(default=0.0, ge=0.0, le=1.0)
    classification_coverage: float = Field(default=1.0, ge=0.0, le=1.0)
    mean_classification_confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class AnalysisWindows(FrozenModel):
    current_start: datetime
    current_end: datetime
    baseline_start: datetime
    baseline_end: datetime
    business_timezone: str
    current_days: int = Field(gt=0)
    baseline_days: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_ordering(self) -> AnalysisWindows:
        if not (
            self.baseline_start < self.baseline_end == self.current_start < self.current_end
        ):
            raise ValueError("windows must be contiguous and ordered")
        if any(
            value.tzinfo is None
            for value in (
                self.current_start,
                self.current_end,
                self.baseline_start,
                self.baseline_end,
            )
        ):
            raise ValueError("window boundaries must be timezone-aware")
        return self


class RateCell(FrozenModel):
    numerator: int = Field(ge=0)
    denominator: int = Field(ge=0)
    share: float | None = Field(default=None, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def check_rate(self) -> RateCell:
        if self.numerator > self.denominator:
            raise ValueError("numerator cannot exceed denominator")
        expected = None if self.denominator == 0 else self.numerator / self.denominator
        if expected is None and self.share is not None:
            raise ValueError("zero denominator requires share=None")
        if expected is not None and (self.share is None or abs(self.share - expected) > 1e-12):
            raise ValueError("share must equal numerator / denominator")
        return self


class ExcludedStratum(FrozenModel):
    stratum: SourceStratum
    reasons: tuple[str, ...]


class TrendStratumResult(FrozenModel):
    stratum: SourceStratum
    current: RateCell
    baseline: RateCell
    baseline_weight: float = Field(ge=0.0, le=1.0)
    excess_items: float = Field(ge=0.0)
    percentage_point_change: float = Field(ge=-1.0, le=1.0)
    growth_multiple: float | None = Field(default=None, ge=0.0)
    confidence_p_value: float | None = Field(default=None, ge=0.0, le=1.0)
    confidence_passes: bool
    direction: str


class TrendThresholds(FrozenModel):
    min_current_denominator: int = Field(default=10, ge=1)
    min_baseline_denominator: int = Field(default=10, ge=1)
    min_support: int = Field(default=8, ge=1)
    min_excess: float = Field(default=5.0, ge=0.0)
    min_growth: float = Field(default=1.8, gt=1.0)
    min_rate_delta: float = Field(default=0.05, gt=0.0, le=1.0)
    confidence_alpha: float = Field(default=0.05, gt=0.0, lt=1.0)
    min_source_groups: int = Field(default=2, ge=1)


class TrendResult(FrozenModel):
    topic: PrimaryTopic
    brand: Brand
    scope: str
    windows: AnalysisWindows
    current_numerator: int = Field(ge=0)
    current_denominator: int = Field(ge=0)
    baseline_numerator: int = Field(ge=0)
    baseline_denominator: int = Field(ge=0)
    weighted_current_share: float | None = Field(default=None, ge=0.0, le=1.0)
    weighted_baseline_share: float | None = Field(default=None, ge=0.0, le=1.0)
    growth_multiple: float | None = Field(default=None, ge=0.0)
    percentage_point_change: float | None = Field(default=None, ge=-1.0, le=1.0)
    excess_items: float = Field(default=0.0, ge=0.0)
    source_groups_moving: tuple[SourceGroup, ...] = ()
    participating_strata: tuple[TrendStratumResult, ...] = ()
    excluded_strata: tuple[ExcludedStratum, ...] = ()
    is_new_signal: bool = False
    qualifies: bool = False
    suppression_reasons: tuple[str, ...] = ()


class DailyMetric(FrozenModel):
    date: date
    resolved_brand: Brand
    visibility: Visibility
    source_group: SourceGroup
    source_platform: str
    experience_subject: ExperienceSubject
    primary_topic: PrimaryTopic
    subtopic: str
    product_category: str | None
    journey_stage: JourneyStage
    raw_record_count: int = Field(ge=0)
    independent_signal_count: int = Field(ge=0)
    negative_count: int = Field(ge=0)
    negative_share: float | None = Field(default=None, ge=0.0, le=1.0)
    positive_count: int = Field(ge=0)
    positive_share: float | None = Field(default=None, ge=0.0, le=1.0)
    average_rating: float | None = Field(default=None, ge=0.0, le=5.0)
    analyzed_count: int = Field(ge=0)
    low_confidence_count: int = Field(ge=0)


class DriverCandidate(FrozenModel):
    dimension: str
    value: str
    support: int = Field(ge=0)
    current_share: float = Field(ge=0.0, le=1.0)
    baseline_support: int = Field(ge=0)
    baseline_share: float = Field(ge=0.0, le=1.0)
    lift: float | None = Field(default=None, ge=0.0)
    contribution_to_excess: float = Field(ge=0.0)
    source_group_breadth: int = Field(ge=0)
    evidence_ids: tuple[str, ...] = ()


class WeeklyTopicMetric(FrozenModel):
    week_start: date
    topic: PrimaryTopic
    negative_count: int = Field(ge=0)
    denominator: int = Field(ge=0)
    rank: int = Field(ge=1)
    healthy: bool = True


class RecurringResult(FrozenModel):
    topic: PrimaryTopic
    qualifying_weeks: int = Field(ge=0)
    weeks_considered: int = Field(ge=0)
    qualifies: bool
    reason: str


def canonical_json(value: Any) -> str:
    """Return stable JSON for cache keys and fact-packet fingerprints."""

    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
