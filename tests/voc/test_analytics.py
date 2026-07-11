from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from guardian_voc.analytics.competitors import build_matched_public_benchmark
from guardian_voc.analytics.data_health import assess_all_sources
from guardian_voc.analytics.drivers import rank_likely_drivers, select_likely_driver
from guardian_voc.analytics.metrics import (
    aggregate_daily_metrics,
    build_analysis_windows,
    collapse_independent_units,
)
from guardian_voc.analytics.trends import (
    compute_stratified_trend,
    detect_improving,
    detect_recurring_friction,
)
from guardian_voc.schemas.analysis import (
    AnalyticsUnit,
    Brand,
    ExperienceSubject,
    HealthStatus,
    JourneyStage,
    OccurredAtQuality,
    PrimaryTopic,
    Sentiment,
    SourceGroup,
    SourceHealthSnapshot,
    SourceStratum,
    TrendThresholds,
    Urgency,
    Visibility,
    WeeklyTopicMetric,
)
from guardian_voc.schemas.insights import (
    InsightObservation,
    InsightStatus,
    MonitoringReference,
)


AS_OF = datetime(2026, 7, 11, 23, 59, 59, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh"))
WINDOWS = build_analysis_windows(AS_OF)
BASELINE_AT = datetime(2026, 6, 20, 12, tzinfo=timezone.utc)
CURRENT_AT = datetime(2026, 7, 8, 12, tzinfo=timezone.utc)


def _unit(
    identifier: str,
    *,
    occurred_at: datetime = CURRENT_AT,
    brand: Brand = Brand.GUARDIAN,
    visibility: Visibility = Visibility.PUBLIC,
    source_group: SourceGroup = SourceGroup.MARKETPLACE,
    platform: str = "shopee",
    sentiment: Sentiment = Sentiment.NEUTRAL,
    topic: PrimaryTopic = PrimaryTopic.OTHER,
    subtopic: str = "other",
    unit_id: str | None = None,
    language: str | None = "vi",
    category: str | None = "skincare",
    reason: str | None = None,
    journey_stage: JourneyStage = JourneyStage.UNKNOWN,
) -> AnalyticsUnit:
    return AnalyticsUnit(
        analytics_unit_id=unit_id or identifier,
        feedback_id=identifier,
        resolved_brand=brand,
        visibility=visibility,
        source_group=source_group,
        source_platform=platform,
        experience_subject=ExperienceSubject.RETAILER,
        occurred_at=occurred_at,
        occurred_at_quality=OccurredAtQuality.PARSED,
        language=language,
        product_category=category,
        is_relevant=True,
        analysis_succeeded=True,
        analysis_confidence=0.95,
        primary_topic=topic,
        subtopic=subtopic,
        sentiment=sentiment,
        urgency=Urgency.NORMAL,
        customer_stated_reason=reason,
        journey_stage=journey_stage,
    )


def _cohort(
    prefix: str,
    *,
    when: datetime,
    group: SourceGroup,
    platform: str,
    denominator: int,
    numerator: int,
    brand: Brand = Brand.GUARDIAN,
    visibility: Visibility = Visibility.PUBLIC,
    language: str = "vi",
    category: str = "skincare",
) -> list[AnalyticsUnit]:
    return [
        _unit(
            f"{prefix}-{index}",
            occurred_at=when,
            brand=brand,
            visibility=visibility,
            source_group=group,
            platform=platform,
            sentiment=Sentiment.NEGATIVE if index < numerator else Sentiment.NEUTRAL,
            topic=(
                PrimaryTopic.PRICE_PROMOTION if index < numerator else PrimaryTopic.OTHER
            ),
            subtopic="unclear_eligibility" if index < numerator else "other",
            language=language,
            category=category,
        )
        for index in range(denominator)
    ]


def test_calendar_windows_are_built_at_local_midnight_then_converted_to_utc() -> None:
    zone = ZoneInfo("Asia/Ho_Chi_Minh")
    assert WINDOWS.current_start.astimezone(zone).isoformat() == "2026-07-05T00:00:00+07:00"
    assert WINDOWS.current_end.astimezone(zone).isoformat() == "2026-07-12T00:00:00+07:00"
    assert WINDOWS.baseline_start.astimezone(zone).date() == date(2026, 6, 7)
    assert WINDOWS.baseline_end == WINDOWS.current_start


def test_public_reposts_are_one_independent_analytics_unit() -> None:
    records = [
        _unit("post-a", unit_id="repost-wave", source_group=SourceGroup.SOCIAL, platform="tiktok"),
        _unit("post-b", unit_id="repost-wave", source_group=SourceGroup.SOCIAL, platform="facebook"),
        _unit("post-c", unit_id="original", source_group=SourceGroup.SOCIAL, platform="tiktok"),
    ]
    collapsed = collapse_independent_units(records)
    assert len(collapsed) == 2
    assert {record.analytics_unit_id for record in collapsed} == {"repost-wave", "original"}


def test_daily_metrics_preserve_raw_reach_but_use_independent_units_for_rates() -> None:
    records = [
        _unit(
            "copy-a",
            unit_id="same",
            sentiment=Sentiment.NEGATIVE,
            topic=PrimaryTopic.PRICE_PROMOTION,
            subtopic="unclear_eligibility",
        ),
        _unit(
            "copy-b",
            unit_id="same",
            sentiment=Sentiment.NEGATIVE,
            topic=PrimaryTopic.PRICE_PROMOTION,
            subtopic="unclear_eligibility",
        ),
    ]
    row = aggregate_daily_metrics(records)[0]
    assert row.raw_record_count == 2
    assert row.independent_signal_count == 1
    assert row.negative_count == 1


def test_cross_source_spike_passes_fixed_baseline_thresholds() -> None:
    records = []
    for group, platform in (
        (SourceGroup.MARKETPLACE, "shopee"),
        (SourceGroup.OWNED, "guardian_ecommerce"),
    ):
        records += _cohort(
            f"base-{group.value}",
            when=BASELINE_AT,
            group=group,
            platform=platform,
            denominator=100,
            numerator=5,
        )
        records += _cohort(
            f"current-{group.value}",
            when=CURRENT_AT,
            group=group,
            platform=platform,
            denominator=100,
            numerator=20,
        )
    result = compute_stratified_trend(
        records, topic=PrimaryTopic.PRICE_PROMOTION, windows=WINDOWS
    )
    assert result.qualifies
    assert result.weighted_baseline_share == pytest.approx(0.05)
    assert result.weighted_current_share == pytest.approx(0.20)
    assert result.growth_multiple == pytest.approx(4.0)
    assert result.excess_items == pytest.approx(30.0)
    assert set(result.source_groups_moving) == {SourceGroup.MARKETPLACE, SourceGroup.OWNED}
    assert sum(item.baseline_weight for item in result.participating_strata) == pytest.approx(1)


def test_source_mix_change_alone_does_not_create_a_false_alert() -> None:
    records = (
        _cohort(
            "base-market",
            when=BASELINE_AT,
            group=SourceGroup.MARKETPLACE,
            platform="shopee",
            denominator=90,
            numerator=9,
        )
        + _cohort(
            "base-owned",
            when=BASELINE_AT,
            group=SourceGroup.OWNED,
            platform="guardian_ecommerce",
            denominator=10,
            numerator=3,
        )
        + _cohort(
            "current-market",
            when=CURRENT_AT,
            group=SourceGroup.MARKETPLACE,
            platform="shopee",
            denominator=10,
            numerator=1,
        )
        + _cohort(
            "current-owned",
            when=CURRENT_AT,
            group=SourceGroup.OWNED,
            platform="guardian_ecommerce",
            denominator=90,
            numerator=27,
        )
    )
    result = compute_stratified_trend(
        records, topic=PrimaryTopic.PRICE_PROMOTION, windows=WINDOWS
    )
    assert result.weighted_baseline_share == pytest.approx(0.12)
    assert result.weighted_current_share == pytest.approx(0.12)
    assert not result.qualifies
    assert "rate_delta_below_threshold" in result.suppression_reasons


def test_zero_baseline_is_a_new_signal_not_infinite_growth() -> None:
    records = []
    for group, platform in (
        (SourceGroup.MARKETPLACE, "shopee"),
        (SourceGroup.CUSTOMER_SERVICE, "live_chat"),
    ):
        records += _cohort(
            f"base-zero-{group.value}",
            when=BASELINE_AT,
            group=group,
            platform=platform,
            denominator=100,
            numerator=0,
        )
        records += _cohort(
            f"new-{group.value}",
            when=CURRENT_AT,
            group=group,
            platform=platform,
            denominator=50,
            numerator=10,
        )
    result = compute_stratified_trend(
        records, topic=PrimaryTopic.PRICE_PROMOTION, windows=WINDOWS
    )
    assert result.is_new_signal
    assert result.growth_multiple is None
    assert result.qualifies


def test_required_unhealthy_source_suppresses_signal() -> None:
    records = []
    strata = []
    for group, platform in (
        (SourceGroup.MARKETPLACE, "shopee"),
        (SourceGroup.OWNED, "guardian_ecommerce"),
    ):
        records += _cohort(
            f"hb-{group.value}",
            when=BASELINE_AT,
            group=group,
            platform=platform,
            denominator=100,
            numerator=5,
        )
        records += _cohort(
            f"hc-{group.value}",
            when=CURRENT_AT,
            group=group,
            platform=platform,
            denominator=100,
            numerator=20,
        )
        strata.append(
            SourceStratum(
                brand=Brand.GUARDIAN,
                source_group=group,
                source_platform=platform,
                experience_subject=ExperienceSubject.RETAILER,
            )
        )
    snapshots = [
        SourceHealthSnapshot(
            stratum=strata[0],
            status=HealthStatus.HEALTHY,
            last_success_at=AS_OF.astimezone(timezone.utc),
            recent_volume=100,
        ),
        SourceHealthSnapshot(
            stratum=strata[1],
            status=HealthStatus.STALE,
            last_success_at=AS_OF.astimezone(timezone.utc) - timedelta(days=3),
            recent_volume=100,
        ),
    ]
    health = assess_all_sources(snapshots, as_of=AS_OF.astimezone(timezone.utc))
    result = compute_stratified_trend(
        records,
        topic=PrimaryTopic.PRICE_PROMOTION,
        windows=WINDOWS,
        health_assessments=health,
        require_explicit_health=True,
        required_source_groups=(SourceGroup.MARKETPLACE, SourceGroup.OWNED),
    )
    assert not result.qualifies
    assert "required_source_unhealthy" in result.suppression_reasons


def test_recurring_issue_requires_three_of_four_healthy_weeks() -> None:
    metrics = tuple(
        WeeklyTopicMetric(
            week_start=date(2026, 6, 8) + timedelta(days=7 * index),
            topic=PrimaryTopic.RETURNS_REFUNDS,
            negative_count=10,
            denominator=100,
            rank=rank,
        )
        for index, rank in enumerate((1, 2, 4, 1))
    )
    result = detect_recurring_friction(metrics, topic=PrimaryTopic.RETURNS_REFUNDS)
    assert result.qualifies
    assert result.qualifying_weeks == 3


def test_improvement_uses_frozen_reference_and_rejects_coverage_decline() -> None:
    reference_observation = InsightObservation(
        observation_id="reference",
        insight_series_id="series",
        cohort_signature="same-cohort",
        current_share=0.20,
        denominator=100,
        source_groups=(SourceGroup.MARKETPLACE, SourceGroup.OWNED),
        healthy=True,
        observed_at=BASELINE_AT,
    )
    reference = MonitoringReference(
        status=InsightStatus.MONITORING,
        reference_observation_id="reference",
        observation=reference_observation,
    )
    latest = InsightObservation(
        observation_id="latest",
        insight_series_id="series",
        cohort_signature="same-cohort",
        current_share=0.10,
        denominator=100,
        source_groups=(SourceGroup.MARKETPLACE, SourceGroup.OWNED),
        healthy=True,
        observed_at=CURRENT_AT,
    )
    assert detect_improving(reference, latest).qualifies
    declined = latest.model_copy(update={"source_groups": (SourceGroup.MARKETPLACE,)})
    result = detect_improving(reference, declined)
    assert not result.qualifies
    assert result.reason == "source_coverage_declined"
    stale = latest.model_copy(update={"healthy": False})
    assert detect_improving(reference, stale).reason == "latest_source_health_failed"


def test_likely_driver_prefers_cross_source_excess_concentration() -> None:
    records: list[AnalyticsUnit] = []
    for index in range(10):
        unclear = index < 2
        records.append(
            _unit(
                f"driver-base-{index}",
                occurred_at=BASELINE_AT,
                source_group=(
                    SourceGroup.MARKETPLACE if index % 2 else SourceGroup.OWNED
                ),
                platform="shopee" if index % 2 else "guardian_ecommerce",
                sentiment=Sentiment.NEGATIVE,
                topic=PrimaryTopic.PRICE_PROMOTION,
                subtopic="unclear_eligibility" if unclear else "voucher_not_applied",
                reason="minimum spend shown at checkout" if unclear else "voucher rejected",
                journey_stage=JourneyStage.CHECKOUT,
            )
        )
    for index in range(20):
        unclear = index < 12
        records.append(
            _unit(
                f"driver-current-{index}",
                source_group=(
                    SourceGroup.MARKETPLACE if index % 2 else SourceGroup.OWNED
                ),
                platform="shopee" if index % 2 else "guardian_ecommerce",
                sentiment=Sentiment.NEGATIVE,
                topic=PrimaryTopic.PRICE_PROMOTION,
                subtopic="unclear_eligibility" if unclear else "voucher_not_applied",
                reason="minimum spend shown at checkout" if unclear else "voucher rejected",
                journey_stage=JourneyStage.CHECKOUT,
            )
        )
    drivers = rank_likely_drivers(
        records, topic=PrimaryTopic.PRICE_PROMOTION, windows=WINDOWS
    )
    selected = select_likely_driver(drivers)
    assert selected is not None
    assert selected.value in {"unclear_eligibility", "minimum spend shown at checkout"}
    assert selected.support == 12
    assert selected.source_group_breadth == 2
    assert selected.contribution_to_excess == pytest.approx(8)


def _benchmark_cohort(
    prefix: str,
    *,
    brand: Brand,
    platform: str,
    denominator: int,
    negative: int,
    praise: int = 0,
    language: str = "vi",
    visibility: Visibility = Visibility.PUBLIC,
    source_group: SourceGroup = SourceGroup.MARKETPLACE,
) -> list[AnalyticsUnit]:
    rows = []
    for index in range(denominator):
        if index < negative:
            sentiment, topic, subtopic = (
                Sentiment.NEGATIVE,
                PrimaryTopic.PRICE_PROMOTION,
                "unclear_eligibility",
            )
        elif index < negative + praise:
            sentiment, topic, subtopic = (
                Sentiment.POSITIVE,
                PrimaryTopic.PRICE_PROMOTION,
                "good_value",
            )
        else:
            sentiment, topic, subtopic = Sentiment.NEUTRAL, PrimaryTopic.OTHER, "other"
        rows.append(
            _unit(
                f"{prefix}-{index}",
                brand=brand,
                visibility=visibility,
                source_group=source_group,
                platform=platform,
                sentiment=sentiment,
                topic=topic,
                subtopic=subtopic,
                language=language,
            )
        )
    return rows


def test_competitor_benchmark_uses_public_common_strata_and_identical_weights() -> None:
    records = (
        _benchmark_cohort("sg", brand=Brand.GUARDIAN, platform="shopee", denominator=20, negative=10)
        + _benchmark_cohort("sh", brand=Brand.HASAKI, platform="shopee", denominator=10, negative=1)
        + _benchmark_cohort("sw", brand=Brand.WATSONS, platform="shopee", denominator=10, negative=2, praise=3)
        + _benchmark_cohort("tg", brand=Brand.GUARDIAN, platform="tiktok", denominator=10, negative=1)
        + _benchmark_cohort("th", brand=Brand.HASAKI, platform="tiktok", denominator=30, negative=6)
        + _benchmark_cohort("tw", brand=Brand.WATSONS, platform="tiktok", denominator=20, negative=6, praise=4)
        + _benchmark_cohort(
            "owned-noise",
            brand=Brand.GUARDIAN,
            platform="shopee",
            denominator=100,
            negative=100,
            visibility=Visibility.OWNED,
            source_group=SourceGroup.OWNED,
        )
        + _benchmark_cohort(
            "unknown-language",
            brand=Brand.GUARDIAN,
            platform="shopee",
            denominator=20,
            negative=20,
            language="unknown",
        )
    )
    for brand in (Brand.GUARDIAN, Brand.HASAKI, Brand.WATSONS):
        records += _benchmark_cohort(
            f"small-{brand.value}",
            brand=brand,
            platform="facebook",
            denominator=5,
            negative=1,
            source_group=SourceGroup.SOCIAL,
        )
    result = build_matched_public_benchmark(
        records,
        topic=PrimaryTopic.PRICE_PROMOTION,
        windows=WINDOWS,
        minimum_sample=10,
    )
    assert result.comparable
    weights = {row.source_platform: row.common_weight for row in result.strata}
    assert weights == pytest.approx({"shopee": 0.4, "tiktok": 0.6})
    assert result.guardian_weighted_share == pytest.approx(0.4 * 0.5 + 0.6 * 0.1)
    assert result.hasaki_weighted_share == pytest.approx(0.4 * 0.1 + 0.6 * 0.2)
    assert result.watsons_weighted_share == pytest.approx(0.4 * 0.2 + 0.6 * 0.3)
    assert result.guardian_sample_size == 30
    assert result.hasaki_sample_size == 40
    assert result.watsons_sample_size == 30
    assert result.market_expectation is not None
    assert result.market_expectation.brand is Brand.WATSONS
    assert result.market_expectation.praised_subtopic == "good_value"
    assert any("facebook" in item.stratum_key for item in result.excluded_strata)


def test_competitor_benchmark_fails_closed_when_no_common_stratum() -> None:
    records = _benchmark_cohort(
        "only-guardian",
        brand=Brand.GUARDIAN,
        platform="shopee",
        denominator=20,
        negative=5,
    )
    result = build_matched_public_benchmark(
        records,
        topic=PrimaryTopic.PRICE_PROMOTION,
        windows=WINDOWS,
        minimum_sample=10,
    )
    assert not result.comparable
    assert result.guardian_weighted_share is None
    assert result.insufficiency_reason == "Not enough comparable public feedback"
