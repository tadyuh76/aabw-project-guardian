"""Seal deterministic analytics before a narrative writer sees them."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import timedelta
from zoneinfo import ZoneInfo

from guardian_voc.schemas.analysis import DriverCandidate, TrendResult
from guardian_voc.schemas.insights import (
    BusinessEventFact,
    FactPacket,
    GuardianTrendFact,
    InsightType,
    MatchedPublicBenchmarkFact,
    TopSubtopicFact,
)


def build_fact_packet(
    trend: TrendResult,
    *,
    insight_type: InsightType,
    subtopic: str | None = None,
    top_subtopic: TopSubtopicFact | None = None,
    likely_drivers: Sequence[DriverCandidate] = (),
    business_events: Sequence[BusinessEventFact] = (),
    benchmark: MatchedPublicBenchmarkFact | None = None,
    allowed_evidence_ids: Iterable[str] = (),
    source_health_notes: Iterable[str] = (),
) -> FactPacket:
    """Create a deeply tuple-backed, fingerprinted fact packet."""

    if trend.weighted_current_share is None or trend.weighted_baseline_share is None:
        raise ValueError("trend must contain eligible weighted strata")
    if trend.percentage_point_change is None:
        raise ValueError("trend must contain a percentage-point change")
    zone = ZoneInfo(trend.windows.business_timezone)
    window_start = trend.windows.current_start.astimezone(zone).date()
    window_end = (trend.windows.current_end.astimezone(zone) - timedelta(days=1)).date()
    source_groups = {
        stratum.stratum.source_group for stratum in trend.participating_strata
    }
    fact = GuardianTrendFact(
        current_numerator=trend.current_numerator,
        current_denominator=trend.current_denominator,
        baseline_numerator=trend.baseline_numerator,
        baseline_denominator=trend.baseline_denominator,
        weighted_current_share=trend.weighted_current_share,
        weighted_baseline_share=trend.weighted_baseline_share,
        growth_multiple=trend.growth_multiple,
        percentage_point_change=trend.percentage_point_change,
        excess_items=trend.excess_items,
        source_groups=len(source_groups),
        strata=trend.participating_strata,
        excluded_strata=trend.excluded_strata,
    )
    evidence_ids = tuple(dict.fromkeys(allowed_evidence_ids))
    return FactPacket(
        topic=trend.topic,
        subtopic=subtopic,
        insight_type=insight_type,
        window_start=window_start,
        window_end=window_end,
        guardian_all_channel_trend=fact,
        top_subtopic=top_subtopic,
        likely_driver_dimensions=tuple(likely_drivers),
        business_events=tuple(business_events),
        matched_public_benchmark=benchmark,
        allowed_evidence_ids=evidence_ids,
        source_health_notes=tuple(dict.fromkeys(source_health_notes)),
    )
