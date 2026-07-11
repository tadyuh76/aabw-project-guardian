from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from guardian_voc.analytics import compute_stratified_trend
from guardian_voc.application import GuardianService
from guardian_voc.config import Settings
from guardian_voc.schemas.analysis import PrimaryTopic, SourceGroup
from guardian_voc.schemas.api import InsightPatchRequest


LIVE_AS_OF = datetime.fromisoformat("2026-07-11T23:59:59+07:00")
DELIVERY_ISSUE_AS_OF = datetime.fromisoformat("2026-06-23T23:59:59+07:00")
DELIVERY_SERIES_ID = "series-delivery-improving"
DELIVERY_REFERENCE_ID = "observation-delivery-monitoring-reference"


class FixedAsOfGuardianService(GuardianService):
    @property
    def as_of(self) -> datetime:
        return LIVE_AS_OF


class MutableAsOfGuardianService(GuardianService):
    def __init__(self, settings: Settings) -> None:
        self.current_as_of = LIVE_AS_OF
        super().__init__(settings)

    @property
    def as_of(self) -> datetime:
        return self.current_as_of


@pytest.fixture()
def live_service(tmp_path):
    settings = Settings(
        voc_db_path=tmp_path / "guardian.duckdb",
        voc_data_dir=tmp_path,
        voc_inbox_dir=tmp_path / "inbox",
        voc_demo_mode=False,
        voc_write_api_enabled=False,
        ai_provider="cached",
    )
    service = FixedAsOfGuardianService(settings)
    result = service.seed_demo(reset=True)
    assert result["status"] == "completed"
    yield service
    service.close()


@pytest.fixture()
def monitorable_live_service(tmp_path):
    settings = Settings(
        voc_db_path=tmp_path / "guardian-monitoring.duckdb",
        voc_data_dir=tmp_path,
        voc_inbox_dir=tmp_path / "inbox",
        voc_demo_mode=False,
        voc_write_api_enabled=False,
        ai_provider="cached",
    )
    service = MutableAsOfGuardianService(settings)
    service.current_as_of = DELIVERY_ISSUE_AS_OF
    result = service.seed_demo(reset=True)
    assert result["status"] == "completed"
    yield service
    service.close()


def test_first_live_rebuild_requires_persisted_acknowledged_monitoring_reference(
    live_service: GuardianService,
) -> None:
    units = live_service._analytics_units()
    trend = compute_stratified_trend(
        units,
        topic=PrimaryTopic.DELIVERY_FULFILMENT,
        windows=live_service._windows(),
        thresholds=live_service._thresholds(),
        health_assessments=live_service._health_assessments(units),
        require_explicit_health=True,
        required_source_groups=tuple(SourceGroup),
        allow_inferred_dates=live_service.settings.voc_allow_inferred_dates,
    )

    assert trend.weighted_baseline_share is not None
    assert trend.weighted_current_share is not None
    assert trend.weighted_baseline_share > 0
    assert trend.weighted_current_share / trend.weighted_baseline_share < 0.75
    assert trend.current_denominator >= 20
    assert not any(
        card.label == "improving"
        for card in live_service.today(role="leadership", locale="en").cards
    )
    assert live_service.database.query_one(
        "SELECT insight_id FROM insight_cards WHERE insight_type = 'improving'"
    ) is None
    assert live_service.database.query_one(
        "SELECT observation_id FROM insight_observations WHERE observation_id = ?",
        [DELIVERY_REFERENCE_ID],
    ) is None
    assert live_service.database.query_one(
        """
        SELECT status_event_id FROM insight_status_history
        WHERE insight_series_id = ?
          AND status IN ('acknowledged', 'monitoring')
          AND reference_observation_id IS NOT NULL
        """,
        [DELIVERY_SERIES_ID],
    ) is None


def test_data_health_api_ages_healthy_source_status_to_stale(
    live_service: GuardianService,
) -> None:
    expired_at = LIVE_AS_OF - timedelta(
        hours=live_service.settings.voc_source_stale_hours,
        seconds=1,
    )
    live_service.database.execute(
        """
        UPDATE source_status
        SET status = 'healthy', last_success_at = ?
        WHERE source_group = 'social'
        """,
        [expired_at],
    )
    persisted = live_service.database.query(
        "SELECT status, last_success_at FROM source_status WHERE source_group = 'social'"
    )
    assert persisted
    assert {row["status"] for row in persisted} == {"healthy"}

    response = live_service.data_health()
    social = next(
        source for source in response["sources"] if source["source_group"] == "social"
    )
    assert social["status"] == "stale"


def test_one_stale_connector_makes_its_group_and_analytics_unhealthy(
    live_service: GuardianService,
) -> None:
    marketplace_sources = live_service.database.query(
        """
        SELECT source_name FROM source_status
        WHERE source_group = 'marketplace'
        ORDER BY source_name
        """
    )
    assert len(marketplace_sources) >= 2, "fixture must exercise mixed connector freshness"

    live_service.database.execute(
        """
        UPDATE source_status
        SET status = 'healthy', last_success_at = ?
        WHERE source_group = 'marketplace'
        """,
        [LIVE_AS_OF],
    )
    expired_at = LIVE_AS_OF - timedelta(
        hours=live_service.settings.voc_source_stale_hours,
        seconds=1,
    )
    live_service.database.execute(
        """
        UPDATE source_status SET last_success_at = ?
        WHERE source_name = 'guardian_marketplace'
        """,
        [expired_at],
    )

    response = live_service.data_health()
    marketplace_api = next(
        source
        for source in response["sources"]
        if source["source_group"] == "marketplace"
    )
    assessments = live_service._health_assessments(live_service._analytics_units())
    marketplace_analytics = [
        assessment
        for assessment in assessments.values()
        if assessment.stratum.source_group is SourceGroup.MARKETPLACE
    ]
    api_is_stale = marketplace_api["status"] == "stale"
    analytics_are_unhealthy = bool(marketplace_analytics) and all(
        not assessment.healthy
        and any("stale" in reason for reason in assessment.reasons)
        for assessment in marketplace_analytics
    )
    assert api_is_stale and analytics_are_unhealthy, (
        f"mixed connector freshness was masked: API={marketplace_api['status']}, "
        f"analytics={[(item.healthy, item.reasons) for item in marketplace_analytics]}"
    )


def test_live_delivery_can_be_monitored_before_a_later_improvement(
    monitorable_live_service: MutableAsOfGuardianService,
) -> None:
    service = monitorable_live_service
    initial = service.database.query_one(
        """
        SELECT insight_id, insight_type, observation_id
        FROM insight_cards
        WHERE insight_series_id = ?
        """,
        [DELIVERY_SERIES_ID],
    )
    assert initial is not None, (
        "a live delivery issue needs a persisted Watch/Act card so an operator "
        "can start monitoring it"
    )
    assert initial["insight_type"] in {"watch", "act_now"}

    patched = service.patch_insight(
        str(initial["insight_id"]),
        InsightPatchRequest(
            status="monitoring",
            note="Track delivery recovery from this observation.",
        ),
    )
    assert patched is not None and patched.status == "monitoring"
    monitoring = service.database.query_one(
        """
        SELECT status, reference_observation_id
        FROM insight_status_history
        WHERE insight_series_id = ?
        ORDER BY changed_at DESC, status_event_id DESC
        LIMIT 1
        """,
        [DELIVERY_SERIES_ID],
    )
    assert monitoring == {
        "status": "monitoring",
        "reference_observation_id": initial["observation_id"],
    }

    service._rebuild_insights(pipeline_run_id="same-delivery-observation")
    same_observation = service.database.query_one(
        """
        SELECT insight_type FROM insight_cards
        WHERE insight_series_id = ?
        """,
        [DELIVERY_SERIES_ID],
    )
    assert same_observation is not None
    assert same_observation["insight_type"] != "improving"

    service.current_as_of = LIVE_AS_OF
    service.database.execute(
        "UPDATE source_status SET status = 'healthy', last_success_at = ?",
        [service.current_as_of],
    )
    service._rebuild_insights(pipeline_run_id="later-delivery-observation")
    later_observation = service.database.query_one(
        """
        SELECT insight_type FROM insight_cards
        WHERE insight_series_id = ?
        """,
        [DELIVERY_SERIES_ID],
    )
    assert later_observation == {"insight_type": "improving"}
