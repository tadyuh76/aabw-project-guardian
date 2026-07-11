"""Independent-unit normalization, calendar windows, and daily aggregation."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from statistics import fmean
from typing import Iterable, Sequence
from zoneinfo import ZoneInfo

from guardian_voc.schemas.analysis import (
    AnalysisWindows,
    AnalyticsUnit,
    DailyMetric,
    OccurredAtQuality,
    Sentiment,
)


def build_analysis_windows(
    as_of: datetime,
    *,
    current_days: int = 7,
    baseline_days: int = 28,
    business_timezone: str = "Asia/Ho_Chi_Minh",
    as_of_date_is_complete: bool = True,
) -> AnalysisWindows:
    """Build local-midnight boundaries first, then convert them to UTC.

    ``VOC_DEMO_AS_OF`` is an end-of-day fixture anchor, so its calendar date is
    complete by default. Callers using a mid-day live clock should pass
    ``as_of_date_is_complete=False`` to end at today's local midnight.
    """

    if as_of.tzinfo is None:
        raise ValueError("as_of must be timezone-aware")
    if current_days <= 0 or baseline_days <= 0:
        raise ValueError("window lengths must be positive")
    local_zone = ZoneInfo(business_timezone)
    local_as_of = as_of.astimezone(local_zone)
    end_date = local_as_of.date() + timedelta(days=1 if as_of_date_is_complete else 0)
    current_end_local = datetime.combine(end_date, time.min, tzinfo=local_zone)
    current_start_local = current_end_local - timedelta(days=current_days)
    baseline_end_local = current_start_local
    baseline_start_local = baseline_end_local - timedelta(days=baseline_days)
    return AnalysisWindows(
        current_start=current_start_local.astimezone(timezone.utc),
        current_end=current_end_local.astimezone(timezone.utc),
        baseline_start=baseline_start_local.astimezone(timezone.utc),
        baseline_end=baseline_end_local.astimezone(timezone.utc),
        business_timezone=business_timezone,
        current_days=current_days,
        baseline_days=baseline_days,
    )


def is_time_eligible(unit: AnalyticsUnit, *, allow_inferred_dates: bool = False) -> bool:
    if unit.occurred_at is None or unit.occurred_at_quality is OccurredAtQuality.MISSING:
        return False
    if unit.occurred_at.tzinfo is None:
        return False
    if unit.occurred_at_quality is OccurredAtQuality.INFERRED and not allow_inferred_dates:
        return False
    return True


def collapse_independent_units(units: Iterable[AnalyticsUnit]) -> tuple[AnalyticsUnit, ...]:
    """Count a repost group once using a deterministic representative record."""

    selected: dict[str, AnalyticsUnit] = {}
    for unit in units:
        existing = selected.get(unit.analytics_unit_id)
        candidate_key = (
            unit.feedback_id,
            unit.source_group.value,
            unit.source_platform,
        )
        if existing is None:
            selected[unit.analytics_unit_id] = unit
            continue
        existing_key = (
            existing.feedback_id,
            existing.source_group.value,
            existing.source_platform,
        )
        if candidate_key < existing_key:
            selected[unit.analytics_unit_id] = unit
    return tuple(selected[key] for key in sorted(selected))


def units_in_window(
    units: Iterable[AnalyticsUnit],
    *,
    start: datetime,
    end: datetime,
    allow_inferred_dates: bool = False,
) -> tuple[AnalyticsUnit, ...]:
    return collapse_independent_units(
        unit
        for unit in units
        if is_time_eligible(unit, allow_inferred_dates=allow_inferred_dates)
        and start <= unit.occurred_at < end  # type: ignore[operator]
    )


def aggregate_daily_metrics(
    units: Sequence[AnalyticsUnit],
    *,
    business_timezone: str = "Asia/Ho_Chi_Minh",
    low_confidence_threshold: float = 0.70,
    allow_inferred_dates: bool = False,
) -> tuple[DailyMetric, ...]:
    """Aggregate plan-defined dimensions without pooling unrelated channels."""

    zone = ZoneInfo(business_timezone)
    eligible = [
        unit
        for unit in units
        if unit.resolved_brand is not None
        and is_time_eligible(unit, allow_inferred_dates=allow_inferred_dates)
    ]
    raw_groups: dict[tuple[object, ...], list[AnalyticsUnit]] = defaultdict(list)
    for unit in eligible:
        local_date = unit.occurred_at.astimezone(zone).date()  # type: ignore[union-attr]
        key = (
            local_date,
            unit.resolved_brand,
            unit.visibility,
            unit.source_group,
            unit.source_platform,
            unit.experience_subject,
            unit.primary_topic,
            unit.subtopic,
            unit.product_category,
            unit.journey_stage,
        )
        raw_groups[key].append(unit)

    rows: list[DailyMetric] = []
    for key in sorted(raw_groups, key=lambda item: tuple(str(part) for part in item)):
        raw = raw_groups[key]
        independent = collapse_independent_units(raw)
        analyzed = [
            unit for unit in independent if unit.analysis_succeeded and unit.is_relevant
        ]
        negative = sum(unit.sentiment is Sentiment.NEGATIVE for unit in analyzed)
        positive = sum(unit.sentiment is Sentiment.POSITIVE for unit in analyzed)
        analyzed_count = len(analyzed)
        ratings = [unit.rating for unit in independent if unit.rating is not None]
        rows.append(
            DailyMetric(
                date=key[0],
                resolved_brand=key[1],
                visibility=key[2],
                source_group=key[3],
                source_platform=key[4],
                experience_subject=key[5],
                primary_topic=key[6],
                subtopic=key[7],
                product_category=key[8],
                journey_stage=key[9],
                raw_record_count=len(raw),
                independent_signal_count=len(independent),
                negative_count=negative,
                negative_share=None if not analyzed_count else negative / analyzed_count,
                positive_count=positive,
                positive_share=None if not analyzed_count else positive / analyzed_count,
                average_rating=None if not ratings else fmean(ratings),
                analyzed_count=analyzed_count,
                low_confidence_count=sum(
                    unit.analysis_confidence < low_confidence_threshold for unit in analyzed
                ),
            )
        )
    return tuple(rows)


def completed_day(value: datetime, business_timezone: str) -> date:
    if value.tzinfo is None:
        raise ValueError("value must be timezone-aware")
    return value.astimezone(ZoneInfo(business_timezone)).date()
