"""Fixed-baseline stratified trends, recurring friction, and improvement."""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Iterable, Mapping, Sequence

from guardian_voc.analytics.data_health import HealthAssessment
from guardian_voc.analytics.metrics import units_in_window
from guardian_voc.schemas.analysis import (
    AnalysisWindows,
    AnalyticsUnit,
    Brand,
    ExcludedStratum,
    PrimaryTopic,
    RateCell,
    RecurringResult,
    Sentiment,
    SourceGroup,
    SourceStratum,
    TrendResult,
    TrendStratumResult,
    TrendThresholds,
    WeeklyTopicMetric,
)
from guardian_voc.schemas.insights import (
    ImprovementResult,
    InsightObservation,
    MonitoringReference,
)


def two_proportion_p_value(
    current_numerator: int,
    current_denominator: int,
    baseline_numerator: int,
    baseline_denominator: int,
) -> float | None:
    """One-sided pooled z-test for an increase in the current proportion."""

    if current_denominator <= 0 or baseline_denominator <= 0:
        return None
    pooled = (current_numerator + baseline_numerator) / (
        current_denominator + baseline_denominator
    )
    variance = pooled * (1.0 - pooled) * (
        1.0 / current_denominator + 1.0 / baseline_denominator
    )
    if variance <= 0:
        return 1.0
    current_share = current_numerator / current_denominator
    baseline_share = baseline_numerator / baseline_denominator
    z_score = (current_share - baseline_share) / math.sqrt(variance)
    return 0.5 * math.erfc(z_score / math.sqrt(2.0))


def _source_stratum(unit: AnalyticsUnit) -> SourceStratum:
    if unit.resolved_brand is None:
        raise ValueError("unresolved brand cannot form a rate stratum")
    return SourceStratum(
        brand=unit.resolved_brand,
        source_group=unit.source_group,
        source_platform=unit.source_platform,
        experience_subject=unit.experience_subject,
    )


def _rate(units: Sequence[AnalyticsUnit], topic: PrimaryTopic) -> RateCell:
    denominator = sum(unit.is_relevant and unit.analysis_succeeded for unit in units)
    numerator = sum(
        unit.is_relevant
        and unit.analysis_succeeded
        and unit.sentiment is Sentiment.NEGATIVE
        and unit.primary_topic is topic
        for unit in units
    )
    return RateCell(
        numerator=numerator,
        denominator=denominator,
        share=None if not denominator else numerator / denominator,
    )


def compute_stratified_trend(
    units: Sequence[AnalyticsUnit],
    *,
    topic: PrimaryTopic,
    windows: AnalysisWindows,
    brand: Brand = Brand.GUARDIAN,
    thresholds: TrendThresholds | None = None,
    health_assessments: Mapping[str, HealthAssessment] | None = None,
    require_explicit_health: bool = False,
    required_source_groups: Iterable[SourceGroup] = (),
    source_specific: SourceStratum | None = None,
    allow_inferred_dates: bool = False,
) -> TrendResult:
    """Calculate a reproducible trend without allowing source mix to set weights."""

    thresholds = thresholds or TrendThresholds()
    health_assessments = health_assessments or {}
    required_groups = set(required_source_groups)
    brand_units = [unit for unit in units if unit.resolved_brand is brand]
    current_units = units_in_window(
        brand_units,
        start=windows.current_start,
        end=windows.current_end,
        allow_inferred_dates=allow_inferred_dates,
    )
    baseline_units = units_in_window(
        brand_units,
        start=windows.baseline_start,
        end=windows.baseline_end,
        allow_inferred_dates=allow_inferred_dates,
    )
    current_by: dict[SourceStratum, list[AnalyticsUnit]] = defaultdict(list)
    baseline_by: dict[SourceStratum, list[AnalyticsUnit]] = defaultdict(list)
    for unit in current_units:
        current_by[_source_stratum(unit)].append(unit)
    for unit in baseline_units:
        baseline_by[_source_stratum(unit)].append(unit)

    all_strata = set(current_by) | set(baseline_by)
    if source_specific is not None:
        all_strata &= {source_specific}
    eligible: list[tuple[SourceStratum, RateCell, RateCell]] = []
    excluded: list[ExcludedStratum] = []
    unhealthy_required_groups: set[SourceGroup] = set()
    for stratum in sorted(all_strata, key=lambda item: item.stable_key()):
        current = _rate(current_by[stratum], topic)
        baseline = _rate(baseline_by[stratum], topic)
        reasons: list[str] = []
        assessment = health_assessments.get(stratum.stable_key())
        if assessment is None and require_explicit_health:
            reasons.append("source_health_unknown")
        elif assessment is not None and not assessment.healthy:
            reasons.extend(assessment.reasons)
            if stratum.source_group in required_groups:
                unhealthy_required_groups.add(stratum.source_group)
        if current.denominator < thresholds.min_current_denominator:
            reasons.append("current_denominator_insufficient")
        if baseline.denominator < thresholds.min_baseline_denominator:
            reasons.append("baseline_denominator_insufficient")
        if reasons:
            excluded.append(ExcludedStratum(stratum=stratum, reasons=tuple(dict.fromkeys(reasons))))
        else:
            eligible.append((stratum, current, baseline))

    suppressions: list[str] = []
    if unhealthy_required_groups:
        suppressions.append("required_source_unhealthy")
    eligible_groups = {stratum.source_group for stratum, _, _ in eligible}
    if required_groups - eligible_groups:
        suppressions.append("required_source_unavailable")
    if not eligible:
        suppressions.append("no_eligible_strata")
        return TrendResult(
            topic=topic,
            brand=brand,
            scope="source_specific" if source_specific else "all_channel",
            windows=windows,
            current_numerator=0,
            current_denominator=0,
            baseline_numerator=0,
            baseline_denominator=0,
            excluded_strata=tuple(excluded),
            suppression_reasons=tuple(dict.fromkeys(suppressions)),
        )

    total_baseline_denominator = sum(cell.denominator for _, _, cell in eligible)
    participating: list[TrendStratumResult] = []
    weighted_current = 0.0
    weighted_baseline = 0.0
    for stratum, current, baseline in eligible:
        weight = baseline.denominator / total_baseline_denominator
        current_share = current.share or 0.0
        baseline_share = baseline.share or 0.0
        delta = current_share - baseline_share
        p_value = two_proportion_p_value(
            current.numerator,
            current.denominator,
            baseline.numerator,
            baseline.denominator,
        )
        participating.append(
            TrendStratumResult(
                stratum=stratum,
                current=current,
                baseline=baseline,
                baseline_weight=weight,
                excess_items=max(0.0, current.numerator - current.denominator * baseline_share),
                percentage_point_change=delta,
                growth_multiple=(
                    None if baseline.numerator == 0 else current_share / baseline_share
                ),
                confidence_p_value=p_value,
                confidence_passes=p_value is not None and p_value < thresholds.confidence_alpha,
                direction="up" if delta > 0 else "down" if delta < 0 else "flat",
            )
        )
        weighted_current += weight * current_share
        weighted_baseline += weight * baseline_share

    current_numerator = sum(item.current.numerator for item in participating)
    current_denominator = sum(item.current.denominator for item in participating)
    baseline_numerator = sum(item.baseline.numerator for item in participating)
    baseline_denominator = sum(item.baseline.denominator for item in participating)
    delta = weighted_current - weighted_baseline
    excess = sum(item.excess_items for item in participating)
    moving_groups = tuple(
        sorted(
            {item.stratum.source_group for item in participating if item.direction == "up"},
            key=lambda group: group.value,
        )
    )
    growth = None if weighted_baseline == 0 else weighted_current / weighted_baseline
    is_new_signal = baseline_numerator == 0

    if current_numerator < thresholds.min_support:
        suppressions.append("current_support_below_threshold")
    if excess < thresholds.min_excess:
        suppressions.append("excess_below_threshold")
    if delta < thresholds.min_rate_delta:
        suppressions.append("rate_delta_below_threshold")
    if not is_new_signal and (growth is None or growth < thresholds.min_growth):
        suppressions.append("growth_below_threshold")
    if not any(item.confidence_passes for item in participating):
        suppressions.append("confidence_check_failed")
    if source_specific is None and len(moving_groups) < thresholds.min_source_groups:
        suppressions.append("cross_source_confirmation_missing")

    return TrendResult(
        topic=topic,
        brand=brand,
        scope="source_specific" if source_specific else "all_channel",
        windows=windows,
        current_numerator=current_numerator,
        current_denominator=current_denominator,
        baseline_numerator=baseline_numerator,
        baseline_denominator=baseline_denominator,
        weighted_current_share=weighted_current,
        weighted_baseline_share=weighted_baseline,
        growth_multiple=growth,
        percentage_point_change=delta,
        excess_items=excess,
        source_groups_moving=moving_groups,
        participating_strata=tuple(participating),
        excluded_strata=tuple(excluded),
        is_new_signal=is_new_signal,
        qualifies=not suppressions,
        suppression_reasons=tuple(dict.fromkeys(suppressions)),
    )


def detect_recurring_friction(
    metrics: Sequence[WeeklyTopicMetric],
    *,
    topic: PrimaryTopic,
    top_n: int = 3,
    weeks_required: int = 3,
    lookback_weeks: int = 4,
) -> RecurringResult:
    available_weeks = sorted({row.week_start for row in metrics}, reverse=True)[:lookback_weeks]
    if len(available_weeks) < lookback_weeks:
        return RecurringResult(
            topic=topic,
            qualifying_weeks=0,
            weeks_considered=len(available_weeks),
            qualifies=False,
            reason="insufficient_weekly_history",
        )
    healthy_weeks = {
        row.week_start for row in metrics if row.week_start in available_weeks and row.healthy
    }
    if len(healthy_weeks) < lookback_weeks:
        return RecurringResult(
            topic=topic,
            qualifying_weeks=0,
            weeks_considered=len(healthy_weeks),
            qualifies=False,
            reason="insufficient_healthy_weekly_history",
        )
    considered = [
        row
        for row in metrics
        if row.topic is topic and row.week_start in available_weeks and row.healthy
    ]
    qualifying = len({row.week_start for row in considered if row.rank <= top_n})
    return RecurringResult(
        topic=topic,
        qualifying_weeks=qualifying,
        weeks_considered=lookback_weeks,
        qualifies=qualifying >= weeks_required,
        reason=(
            "top_issue_in_required_weeks"
            if qualifying >= weeks_required
            else "not_recurrent_enough"
        ),
    )


def detect_improving(
    reference: MonitoringReference,
    latest: InsightObservation,
    *,
    maximum_ratio: float = 0.75,
    minimum_denominator: int = 20,
) -> ImprovementResult:
    frozen = reference.observation
    reason = "improvement_threshold_passed"
    qualifies = True
    ratio: float | None = None
    if latest.insight_series_id != frozen.insight_series_id:
        qualifies, reason = False, "series_mismatch"
    elif latest.cohort_signature != frozen.cohort_signature:
        qualifies, reason = False, "cohort_definition_changed"
    elif not frozen.healthy or not frozen.classification_succeeded:
        qualifies, reason = False, "reference_observation_unhealthy"
    elif latest.observed_at <= frozen.observed_at:
        qualifies, reason = False, "latest_observation_not_newer"
    elif not latest.healthy:
        qualifies, reason = False, "latest_source_health_failed"
    elif not latest.classification_succeeded:
        qualifies, reason = False, "latest_classification_failed"
    elif latest.denominator < minimum_denominator:
        qualifies, reason = False, "latest_sample_insufficient"
    elif not set(frozen.source_groups).issubset(latest.source_groups):
        qualifies, reason = False, "source_coverage_declined"
    elif frozen.current_share <= 0:
        qualifies, reason = False, "reference_share_zero"
    else:
        ratio = latest.current_share / frozen.current_share
        if ratio >= maximum_ratio:
            qualifies, reason = False, "decline_below_improvement_threshold"
    return ImprovementResult(
        insight_series_id=frozen.insight_series_id,
        qualifies=qualifies,
        ratio_to_reference=ratio,
        reason=reason,
    )
