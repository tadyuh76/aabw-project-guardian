from __future__ import annotations

from pathlib import Path

import pytest

import guardian_voc.application as application_module
from guardian_voc.application import GuardianService
from guardian_voc.config import Settings
from guardian_voc.schemas.analysis import Brand, PrimaryTopic, TrendResult


def _settings(root: Path) -> Settings:
    return Settings(
        voc_db_path=root / "guardian.duckdb",
        voc_data_dir=root,
        voc_inbox_dir=root / "inbox",
        voc_demo_mode=False,
        voc_write_api_enabled=False,
        ai_provider="cached",
    )


def test_empty_live_today_recommends_building_dated_evidence(tmp_path: Path) -> None:
    service = GuardianService(_settings(tmp_path))
    try:
        today = service.today(role="leadership", locale="en")
    finally:
        service.close()

    assert today.mode == "live"
    assert today.cards == []
    assert today.overall_health == "partial"
    assert today.brief[0].insight_id is None
    assert "Not enough dated Guardian feedback" in today.brief[0].text
    assert today.messages == [
        "Best next step: collect dated Guardian-owned or customer-support "
        "feedback, or enable full page reading."
    ]


def test_read_probes_do_not_retry_startup_hydration_when_no_card_qualifies(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = GuardianService(_settings(tmp_path))
    calls = {"classify": 0, "rebuild": 0}

    monkeypatch.setattr(service.repository, "feedback_count", lambda: 1)

    def classify() -> dict[str, int]:
        calls["classify"] += 1
        return {"analyzed": 0, "failed": 1, "low_confidence": 0}

    def rebuild(*, pipeline_run_id: str) -> dict[str, int]:
        assert pipeline_run_id == "startup"
        calls["rebuild"] += 1
        service._built.clear()
        return {"daily_metrics": 0, "insights": 0}

    monkeypatch.setattr(service, "_classify_pending", classify)
    monkeypatch.setattr(service, "_rebuild_insights", rebuild)
    try:
        service.health()
        service.health()
    finally:
        service.close()

    assert calls == {"classify": 1, "rebuild": 1}


@pytest.mark.parametrize(
    ("classification", "expected_status"),
    [
        ({"analyzed": 0, "failed": 2, "low_confidence": 0}, "failed"),
        ({"analyzed": 3, "failed": 1, "low_confidence": 0}, "partial"),
    ],
)
def test_pipeline_status_includes_classification_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    classification: dict[str, int],
    expected_status: str,
) -> None:
    service = GuardianService(_settings(tmp_path))
    monkeypatch.setattr(service, "_classify_pending", lambda: classification)
    monkeypatch.setattr(
        service,
        "_rebuild_insights",
        lambda *, pipeline_run_id: {"daily_metrics": 0, "insights": 0},
    )
    try:
        result = service._execute_pipeline(
            trigger="test",
            ingest=lambda: {"seen": 4, "inserted": 4, "skipped": 0, "failed": 0},
        )
    finally:
        service.close()

    assert result.status == expected_status
    assert result.stage == "published"
    assert result.error_summary == (
        f"Classification failed for {classification['failed']} feedback item(s)."
    )


def test_pipeline_exception_summary_does_not_persist_provider_content_or_keys(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = GuardianService(_settings(tmp_path))

    def fail_classification() -> dict[str, int]:
        raise RuntimeError("sk-secret customer prompt text")

    monkeypatch.setattr(service, "_classify_pending", fail_classification)
    try:
        result = service._execute_pipeline(
            trigger="test",
            ingest=lambda: {"seen": 1, "inserted": 1, "skipped": 0, "failed": 0},
        )
    finally:
        service.close()

    assert result.status == "failed"
    assert result.error_summary == "Pipeline classify failed (RuntimeError)."
    assert "secret" not in result.error_summary
    assert "prompt" not in result.error_summary


def test_live_builder_checks_every_actionable_topic_and_suppresses_noise(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = GuardianService(_settings(tmp_path))
    service.initialize(seed_demo=False)
    checked: list[PrimaryTopic] = []

    monkeypatch.setattr(service, "_analytics_units", lambda: (object(),))
    monkeypatch.setattr(service, "_persist_daily_metrics", lambda units: 0)
    monkeypatch.setattr(service, "_health_assessments", lambda units: {})
    monkeypatch.setattr(service, "_weekly_topic_metrics", lambda *args, **kwargs: ())
    monkeypatch.setattr(service, "_analysis_coverage", lambda: 1.0)

    def non_material_trend(units, *, topic, windows, **kwargs):
        checked.append(topic)
        return TrendResult(
            topic=topic,
            brand=Brand.GUARDIAN,
            scope="all_channel",
            windows=windows,
            current_numerator=2,
            current_denominator=100,
            baseline_numerator=2,
            baseline_denominator=100,
            weighted_current_share=0.02,
            weighted_baseline_share=0.02,
            percentage_point_change=0.0,
            excess_items=0,
            qualifies=False,
            suppression_reasons=("rate_delta_below_threshold",),
        )

    monkeypatch.setattr(
        application_module,
        "compute_stratified_trend",
        non_material_trend,
    )
    try:
        result = service._rebuild_insights(pipeline_run_id="test-live-topics")
    finally:
        service.close()

    assert set(checked) == set(PrimaryTopic) - {PrimaryTopic.OTHER}
    assert result == {"daily_metrics": 0, "insights": 0}
    assert service._built == {}
