"""Immutable fact-packet and grounded insight contracts."""

from __future__ import annotations

import hashlib
from datetime import date, datetime
from enum import StrEnum

from pydantic import Field, field_validator, model_validator

from guardian_voc.schemas.analysis import (
    Brand,
    DriverCandidate,
    ExcludedStratum,
    FrozenModel,
    PrimaryTopic,
    SourceGroup,
    StrictModel,
    TrendStratumResult,
    canonical_json,
)


class InsightType(StrEnum):
    ACT_NOW = "act_now"
    WATCH = "watch"
    MARKET_GAP = "market_gap"
    IMPROVING = "improving"


class InsightStatus(StrEnum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    MONITORING = "monitoring"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


class Team(StrEnum):
    CUSTOMER_SERVICE = "Customer Service"
    COMMERCIAL = "Commercial"
    MARKETING = "Marketing"
    ECOMMERCE = "E-commerce"


class ConfidenceLevel(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class TopSubtopicFact(FrozenModel):
    name: str
    support: int = Field(ge=0)
    share: float = Field(ge=0.0, le=1.0)


class BusinessEventFact(FrozenModel):
    event_id: str
    event_type: str
    title: str
    occurred_at: datetime
    ended_at: datetime | None = None
    notes: str | None = None


class GuardianTrendFact(FrozenModel):
    metric: str = "negative_topic_share"
    unit: str = "independent_feedback_signal"
    current_numerator: int = Field(ge=0)
    current_denominator: int = Field(ge=0)
    baseline_numerator: int = Field(ge=0)
    baseline_denominator: int = Field(ge=0)
    weighted_current_share: float = Field(ge=0.0, le=1.0)
    weighted_baseline_share: float = Field(ge=0.0, le=1.0)
    growth_multiple: float | None = Field(default=None, ge=0.0)
    percentage_point_change: float = Field(ge=-1.0, le=1.0)
    excess_items: float = Field(ge=0.0)
    source_groups: int = Field(ge=0)
    strata: tuple[TrendStratumResult, ...]
    excluded_strata: tuple[ExcludedStratum, ...] = ()


class BenchmarkBrandCell(FrozenModel):
    numerator: int = Field(ge=0)
    denominator: int = Field(ge=0)
    share: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_share(self) -> BenchmarkBrandCell:
        if self.numerator > self.denominator or self.denominator == 0:
            raise ValueError("benchmark cells require 0 <= numerator <= nonzero denominator")
        if abs(self.share - self.numerator / self.denominator) > 1e-12:
            raise ValueError("share must equal numerator / denominator")
        return self


class BenchmarkStratumFact(FrozenModel):
    source_group: SourceGroup
    source_platform: str
    product_category: str | None
    language: str
    experience_subject: str
    common_weight: float = Field(ge=0.0, le=1.0)
    guardian: BenchmarkBrandCell
    hasaki: BenchmarkBrandCell
    watsons: BenchmarkBrandCell


class BenchmarkExclusion(FrozenModel):
    stratum_key: str
    reasons: tuple[str, ...]


class MarketExpectationFact(FrozenModel):
    brand: Brand
    praised_subtopic: str
    support: int = Field(ge=1)
    evidence_ids: tuple[str, ...] = ()


class MatchedPublicBenchmarkFact(FrozenModel):
    metric: str = "negative_topic_share"
    unit: str = "independent_feedback_signal"
    aggregation: str = "common_weighted_strata"
    experience_subject: str
    comparable: bool
    insufficiency_reason: str | None = None
    strata: tuple[BenchmarkStratumFact, ...] = ()
    excluded_strata: tuple[BenchmarkExclusion, ...] = ()
    guardian_weighted_share: float | None = Field(default=None, ge=0.0, le=1.0)
    hasaki_weighted_share: float | None = Field(default=None, ge=0.0, le=1.0)
    watsons_weighted_share: float | None = Field(default=None, ge=0.0, le=1.0)
    guardian_sample_size: int = Field(default=0, ge=0)
    hasaki_sample_size: int = Field(default=0, ge=0)
    watsons_sample_size: int = Field(default=0, ge=0)
    source_platforms: tuple[str, ...] = ()
    market_expectation: MarketExpectationFact | None = None

    @model_validator(mode="after")
    def validate_comparability(self) -> MatchedPublicBenchmarkFact:
        shares = (
            self.guardian_weighted_share,
            self.hasaki_weighted_share,
            self.watsons_weighted_share,
        )
        if self.comparable:
            if not self.strata or any(value is None for value in shares):
                raise ValueError("comparable benchmark requires strata and every weighted share")
            if self.insufficiency_reason:
                raise ValueError("comparable benchmark cannot have an insufficiency reason")
            weight = sum(stratum.common_weight for stratum in self.strata)
            if abs(weight - 1.0) > 1e-9:
                raise ValueError("common benchmark weights must sum to one")
        elif any(value is not None for value in shares):
            raise ValueError("insufficient benchmark cannot expose combined weighted shares")
        return self


class FactPacket(FrozenModel):
    """Facts sealed before any narrative is generated."""

    fact_packet_version: str = "guardian-fact-packet-v1"
    topic: PrimaryTopic
    subtopic: str | None = None
    insight_type: InsightType
    window_start: date
    window_end: date
    guardian_all_channel_trend: GuardianTrendFact
    top_subtopic: TopSubtopicFact | None = None
    likely_driver_dimensions: tuple[DriverCandidate, ...] = ()
    business_events: tuple[BusinessEventFact, ...] = ()
    matched_public_benchmark: MatchedPublicBenchmarkFact | None = None
    allowed_evidence_ids: tuple[str, ...] = ()
    source_health_notes: tuple[str, ...] = ()

    @field_validator("allowed_evidence_ids")
    @classmethod
    def unique_evidence_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("allowed_evidence_ids must be unique")
        return value

    @model_validator(mode="after")
    def validate_window(self) -> FactPacket:
        if self.window_start > self.window_end:
            raise ValueError("window_start must be on or before window_end")
        return self

    @property
    def digest(self) -> str:
        return hashlib.sha256(canonical_json(self).encode("utf-8")).hexdigest()


class InsightDraft(StrictModel):
    """The only narrative shape accepted from an insight writer."""

    title: str = Field(min_length=1, max_length=120)
    what_changed: str = Field(min_length=1, max_length=500)
    likely_driver: str = Field(min_length=1, max_length=500)
    market_context: str | None = Field(default=None, max_length=500)
    recommended_actions: tuple[str, ...] = Field(min_length=1, max_length=2)
    primary_owner: Team
    supporting_owner: Team | None = None
    evidence_ids: tuple[str, ...] = ()

    @field_validator("recommended_actions")
    @classmethod
    def nonempty_actions(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value or any(not item.strip() for item in value):
            raise ValueError("at least one non-empty action is required")
        return value


class InsightWritingRequest(FrozenModel):
    fact_packet: FactPacket
    approved_primary_owner: Team
    approved_supporting_owner: Team | None
    approved_actions: tuple[str, ...] = Field(min_length=1, max_length=2)
    playbook_version: str = "guardian-action-playbooks-v1"
    prompt_version: str = "insight-writer-v1"

    @model_validator(mode="after")
    def validate_playbook(self) -> InsightWritingRequest:
        if self.approved_primary_owner == self.approved_supporting_owner:
            raise ValueError("approved supporting owner must differ from primary owner")
        return self

    def cache_key(self, model_version: str) -> str:
        return hashlib.sha256(
            canonical_json(
                {
                    "fact_packet_digest": self.fact_packet.digest,
                    "prompt_version": self.prompt_version,
                    "playbook_version": self.playbook_version,
                    "primary_owner": self.approved_primary_owner,
                    "supporting_owner": self.approved_supporting_owner,
                    "actions": self.approved_actions,
                    "model_version": model_version,
                }
            ).encode("utf-8")
        ).hexdigest()


class InsightCard(FrozenModel):
    insight_id: str
    insight_series_id: str
    observation_id: str
    insight_type: InsightType
    topic: PrimaryTopic
    subtopic: str | None
    window_start: date
    window_end: date
    title: str
    what_changed: str
    reach_summary: str
    likely_driver: str
    market_context: str | None
    primary_owner: Team
    supporting_owner: Team | None
    recommended_actions: tuple[str, ...]
    confidence: ConfidenceLevel
    evidence_ids: tuple[str, ...]
    fact_packet: FactPacket
    fact_packet_digest: str
    generation_mode: str
    status: InsightStatus = InsightStatus.OPEN
    viewer_action: str | None = None

    @model_validator(mode="after")
    def fact_packet_is_unchanged(self) -> InsightCard:
        if self.fact_packet_digest != self.fact_packet.digest:
            raise ValueError("fact_packet_digest does not match fact_packet")
        if (
            self.topic is not self.fact_packet.topic
            or self.subtopic != self.fact_packet.subtopic
            or self.insight_type is not self.fact_packet.insight_type
            or self.window_start != self.fact_packet.window_start
            or self.window_end != self.fact_packet.window_end
        ):
            raise ValueError("card identity fields must match the sealed fact packet")
        if not self.recommended_actions or len(self.recommended_actions) > 2:
            raise ValueError("card must contain one or two actions")
        if self.primary_owner == self.supporting_owner:
            raise ValueError("supporting owner must differ from primary owner")
        if not set(self.evidence_ids).issubset(self.fact_packet.allowed_evidence_ids):
            raise ValueError("card evidence must be allowed by the fact packet")
        return self


class InsightObservation(FrozenModel):
    observation_id: str
    insight_series_id: str
    cohort_signature: str
    current_share: float = Field(ge=0.0, le=1.0)
    denominator: int = Field(ge=0)
    source_groups: tuple[SourceGroup, ...]
    healthy: bool
    classification_succeeded: bool = True
    observed_at: datetime


class MonitoringReference(FrozenModel):
    status: InsightStatus
    reference_observation_id: str
    observation: InsightObservation

    @model_validator(mode="after")
    def must_be_monitorable(self) -> MonitoringReference:
        if self.status not in {InsightStatus.ACKNOWLEDGED, InsightStatus.MONITORING}:
            raise ValueError("improvement requires acknowledged or monitoring status")
        if self.reference_observation_id != self.observation.observation_id:
            raise ValueError("reference_observation_id must identify the frozen observation")
        return self


class ImprovementResult(FrozenModel):
    insight_series_id: str
    qualifies: bool
    ratio_to_reference: float | None = Field(default=None, ge=0.0)
    reason: str


class RankableInsight(FrozenModel):
    candidate_id: str
    insight_type: InsightType
    topic: PrimaryTopic
    primary_owner: Team
    urgency: int = Field(default=0, ge=0, le=3)
    excess_items: float = Field(default=0.0, ge=0.0)
    growth_multiple: float | None = Field(default=None, ge=0.0)
    source_group_breadth: int = Field(default=0, ge=0)
    confidence: ConfidenceLevel = ConfidenceLevel.LOW
    healthy: bool = True
    payload: InsightCard | None = None
