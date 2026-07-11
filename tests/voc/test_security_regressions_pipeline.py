from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest

from guardian_voc.application import GuardianService
from guardian_voc.config import Settings
from guardian_voc.schemas.analysis import RateCell, TrendResult, TrendStratumResult


def _settings(tmp_path, *, demo: bool = False) -> Settings:
    return Settings(
        voc_db_path=tmp_path / "guardian.duckdb",
        voc_data_dir=tmp_path,
        voc_inbox_dir=tmp_path / "inbox",
        voc_demo_mode=demo,
        voc_write_api_enabled=False,
        ai_provider="cached",
    )


def test_concurrent_pipeline_request_returns_the_active_run(tmp_path) -> None:
    service = GuardianService(_settings(tmp_path))
    first_ingest_started = threading.Event()
    second_request_started = threading.Event()
    release_first_ingest = threading.Event()
    second_ingest_calls = 0

    def first_ingest() -> dict[str, int]:
        first_ingest_started.set()
        assert release_first_ingest.wait(timeout=5), "test did not release the first run"
        return {"seen": 0, "inserted": 0, "skipped": 0, "failed": 0}

    def second_ingest() -> dict[str, int]:
        nonlocal second_ingest_calls
        second_ingest_calls += 1
        return {"seen": 0, "inserted": 0, "skipped": 0, "failed": 0}

    def start_second_request():
        second_request_started.set()
        return service._execute_pipeline(trigger="concurrent-second", ingest=second_ingest)

    try:
        service.initialize(seed_demo=False)
        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(
                service._execute_pipeline,
                trigger="concurrent-first",
                ingest=first_ingest,
            )
            assert first_ingest_started.wait(timeout=5), "first run never reached ingestion"

            second = executor.submit(start_second_request)
            assert second_request_started.wait(timeout=5), "second request was not scheduled"
            try:
                # A duplicate-suppressed request must return the in-flight run
                # while its ingest is still blocked, not after that run exits.
                second_result = second.result(timeout=2)
            finally:
                release_first_ingest.set()

            first_result = first.result(timeout=10)

        assert second_result.pipeline_run_id == first_result.pipeline_run_id
        assert second_ingest_calls == 0
    finally:
        release_first_ingest.set()
        service.close()


@pytest.fixture(scope="module")
def demo_service(tmp_path_factory: pytest.TempPathFactory):
    root = tmp_path_factory.mktemp("zero-baseline-card")
    service = GuardianService(_settings(root, demo=True))
    result = service.seed_demo(reset=True)
    assert result["status"] == "completed"
    yield service
    service.close()


def _as_zero_baseline(trend: TrendResult) -> TrendResult:
    strata: list[TrendStratumResult] = []
    for item in trend.participating_strata:
        baseline = RateCell(
            numerator=0,
            denominator=item.baseline.denominator,
            share=0.0,
        )
        strata.append(
            TrendStratumResult(
                stratum=item.stratum,
                current=item.current,
                baseline=baseline,
                baseline_weight=item.baseline_weight,
                excess_items=float(item.current.numerator),
                percentage_point_change=item.current.share or 0.0,
                growth_multiple=None,
                confidence_p_value=item.confidence_p_value,
                confidence_passes=item.confidence_passes,
                direction="up" if item.current.numerator else "flat",
            )
        )

    return TrendResult(
        topic=trend.topic,
        brand=trend.brand,
        scope=trend.scope,
        windows=trend.windows,
        current_numerator=trend.current_numerator,
        current_denominator=trend.current_denominator,
        baseline_numerator=0,
        baseline_denominator=trend.baseline_denominator,
        weighted_current_share=trend.weighted_current_share,
        weighted_baseline_share=0.0,
        growth_multiple=None,
        percentage_point_change=trend.weighted_current_share,
        excess_items=float(trend.current_numerator),
        source_groups_moving=trend.source_groups_moving,
        participating_strata=tuple(strata),
        excluded_strata=trend.excluded_strata,
        is_new_signal=True,
        qualifies=True,
    )


@pytest.mark.parametrize("locale", ["en", "vi"])
def test_zero_baseline_card_renders_without_an_infinite_growth_claim(
    demo_service: GuardianService,
    locale: str,
) -> None:
    original = demo_service._built["insight-price-promotion"]
    zero_baseline = replace(original, trend=_as_zero_baseline(original.trend))

    view = demo_service._card_view(zero_baseline, role="leadership", locale=locale)

    assert view.metrics.baseline_numerator == 0
    assert view.metrics.baseline_share == 0.0
    assert view.metrics.growth_multiple is None
    assert f"{view.metrics.current_share * 100:.1f}%" in view.what_changed
    normalized_copy = view.what_changed.casefold()
    assert "none" not in normalized_copy
    assert "nan" not in normalized_copy
    assert "infinity" not in normalized_copy
