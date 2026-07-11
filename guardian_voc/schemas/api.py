"""Public API contracts consumed by the executive web application."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


Role = Literal["leadership", "customer_service", "commercial", "marketing", "ecommerce"]
InsightLabel = Literal["act_now", "watch", "market_gap", "improving"]
HealthState = Literal["healthy", "stale", "partial", "failed"]


class SourceStatusView(BaseModel):
    name: str
    label: str
    source_group: str
    status: HealthState
    last_success_at: datetime | None = None
    last_record_at: datetime | None = None
    recent_volume: int = 0
    note: str | None = None


class CoverageView(BaseModel):
    feedback_items: int
    independent_signals: int
    source_groups: int
    analyzed_items: int
    analysis_coverage: float = Field(ge=0, le=1)
    act_now_count: int = 0
    watch_count: int = 0
    improving_count: int = 0


class ConfidenceView(BaseModel):
    level: Literal["high", "medium", "low"]
    score: float = Field(ge=0, le=1)
    sample_size: int
    source_groups: int
    analysis_coverage: float = Field(ge=0, le=1)
    note: str | None = None


class TrendPointView(BaseModel):
    date: date
    current_share: float = Field(ge=0, le=1)
    baseline_share: float | None = Field(default=None, ge=0, le=1)


class StratumView(BaseModel):
    source_group: str
    source_platform: str
    current_numerator: int
    current_denominator: int
    baseline_numerator: int
    baseline_denominator: int
    baseline_weight: float = Field(ge=0, le=1)
    status: str = "included"
    exclusion_reason: str | None = None


class BenchmarkBrandView(BaseModel):
    brand: Literal["guardian", "hasaki", "watsons"]
    numerator: int
    denominator: int
    weighted_share: float = Field(ge=0, le=1)


class BenchmarkView(BaseModel):
    period_start: date
    period_end: date
    cohort_label: str
    source_coverage: list[str]
    comparable: bool
    brands: list[BenchmarkBrandView] = Field(default_factory=list)
    market_expectation: str | None = None
    insufficiency_reason: str | None = None


class CardMetricsView(BaseModel):
    current_numerator: int
    current_denominator: int
    current_share: float = Field(ge=0, le=1)
    baseline_numerator: int
    baseline_denominator: int
    baseline_share: float = Field(ge=0, le=1)
    growth_multiple: float | None = None
    percentage_point_change: float
    excess_items: float
    raw_record_reach: int
    independent_signal_count: int
    strata: list[StratumView] = Field(default_factory=list)


class EvidencePreviewView(BaseModel):
    feedback_id: str
    evidence_role: Literal["representative", "supporting", "counterexample"]
    source_platform: str
    source_group: str
    occurred_at: datetime | None = None
    text_redacted: str
    sentiment: str
    topic: str
    is_synthetic: bool


class InsightCardView(BaseModel):
    insight_id: str
    insight_series_id: str
    label: InsightLabel
    status: Literal["open", "acknowledged", "monitoring", "resolved", "dismissed"] = "open"
    topic: str
    subtopic: str | None = None
    title: str
    what_changed: str
    reach_summary: str
    likely_driver: str
    market_context: str | None = None
    recommended_actions: list[str] = Field(min_length=1, max_length=2)
    primary_owner: str
    supporting_owner: str | None = None
    viewer_action: str | None = None
    confidence: ConfidenceView
    metrics: CardMetricsView
    benchmark: BenchmarkView | None = None
    trend: list[TrendPointView] = Field(default_factory=list)
    evidence_preview: list[EvidencePreviewView] = Field(default_factory=list)
    data_quality_notes: list[str] = Field(default_factory=list)


class BriefLineView(BaseModel):
    kind: Literal["act", "watch", "improving"]
    insight_id: str | None = None
    text: str


class TodayResponse(BaseModel):
    mode: Literal["demo", "live"]
    demo_label: str | None = None
    as_of: datetime
    last_updated: datetime
    role: Role
    locale: Literal["en", "vi"] = "en"
    overall_health: HealthState
    source_statuses: list[SourceStatusView]
    coverage: CoverageView
    brief: list[BriefLineView]
    cards: list[InsightCardView] = Field(max_length=3)
    market_takeaway: str | None = None
    messages: list[str] = Field(default_factory=list)


DashboardDataState = Literal["ready", "partial", "empty"]


class DashboardWindowsView(BaseModel):
    current_start: datetime
    current_end: datetime
    baseline_start: datetime
    baseline_end: datetime
    business_timezone: str


class DashboardCoverageView(BaseModel):
    feedback_items: int = Field(ge=0)
    analyzed_items: int = Field(ge=0)
    relevant_items: int = Field(ge=0)
    time_eligible_items: int = Field(ge=0)
    product_attributed_items: int = Field(ge=0)


class DashboardPeriodCountsView(BaseModel):
    feedback: int = Field(ge=0)
    complaints: int = Field(ge=0)
    positive: int = Field(ge=0)
    neutral: int = Field(ge=0)


class DashboardThemeView(BaseModel):
    label: str
    count: int = Field(ge=0)


class DashboardRatingCountView(BaseModel):
    rating: int = Field(ge=1, le=5)
    count: int = Field(ge=0)


class DashboardProductView(BaseModel):
    id: str
    name: str
    short_name: str
    category: str | None = None
    sku: str | None = None
    pack: str | None = None
    metadata_complete: bool
    rating: float | None = Field(default=None, ge=0, le=5)
    rating_count: int = Field(ge=0)
    total_feedback: int = Field(ge=0)
    current: DashboardPeriodCountsView
    baseline: DashboardPeriodCountsView
    sentiment_delta: float | None = None
    sources: dict[str, int] = Field(default_factory=dict)
    themes: list[DashboardThemeView] = Field(default_factory=list)
    rating_distribution: list[DashboardRatingCountView] = Field(default_factory=list)
    negative_feedback: list[DashboardThemeView] = Field(default_factory=list)
    problems: list[DashboardThemeView] = Field(default_factory=list)


class DashboardEvidenceView(BaseModel):
    id: str
    product_id: str
    text: str
    source_group: str
    source_platform: str
    timestamp: datetime | None = None
    confidence: float = Field(ge=0, le=1)
    stance: Literal["support", "contradict"]
    topic: str
    subtopic: str
    sentiment: str


class DashboardBenchmarkAggregateView(BaseModel):
    brand: Literal["guardian", "hasaki", "watsons"]
    feedback: int = Field(ge=0)
    complaints: int = Field(ge=0)
    positive: int = Field(ge=0)
    neutral: int = Field(ge=0)
    rating: float | None = Field(default=None, ge=0, le=5)
    rating_count: int = Field(ge=0)


class DashboardBenchmarkView(BaseModel):
    comparable: bool
    reason: str | None = None
    aggregates: list[DashboardBenchmarkAggregateView] = Field(default_factory=list)


class DashboardResponse(BaseModel):
    mode: Literal["demo", "live"]
    as_of: datetime
    last_updated: datetime
    overall_health: HealthState
    data_state: DashboardDataState
    windows: DashboardWindowsView
    coverage: DashboardCoverageView
    messages: list[str] = Field(default_factory=list)
    products: list[DashboardProductView] = Field(default_factory=list)
    evidence: list[DashboardEvidenceView] = Field(default_factory=list)
    primary_insight: InsightCardView | None = None
    benchmark: DashboardBenchmarkView


class EvidenceResponse(BaseModel):
    insight: InsightCardView
    current_definition: str
    baseline_definition: str
    competitor_definition: str | None = None
    evidence: list[EvidencePreviewView]
    business_events: list[dict[str, Any]] = Field(default_factory=list)
    fact_packet: dict[str, Any]


class FeedbackListItem(BaseModel):
    feedback_id: str
    occurred_at: datetime | None
    observed_at: datetime
    occurred_at_quality: Literal["exact", "parsed", "inferred", "missing"]
    source_group: str
    source_platform: str
    brand: str | None
    topic: str | None
    subtopic: str | None
    intent: str | None
    sentiment: str | None
    confidence: float | None
    rating: float | None = Field(default=None, ge=0, le=5)
    product_name: str | None
    product_category: str | None
    store: str | None
    text_redacted: str
    insight_ids: list[str] = Field(default_factory=list)
    is_synthetic: bool


class FeedbackListResponse(BaseModel):
    mode: Literal["demo", "live"]
    synthetic_items: int = Field(ge=0)
    items: list[FeedbackListItem]
    total: int
    limit: int
    offset: int


class RunResponse(BaseModel):
    pipeline_run_id: str
    status: Literal["queued", "running", "completed", "partial", "failed"]
    stage: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    records_seen: int = 0
    records_inserted: int = 0
    records_skipped: int = 0
    records_failed: int = 0
    published_at: datetime | None = None
    error_summary: str | None = None


class InsightPatchRequest(BaseModel):
    status: Literal["open", "acknowledged", "monitoring", "resolved", "dismissed"] | None = None
    primary_owner: str | None = None
    note: str | None = Field(default=None, max_length=500)
