from __future__ import annotations

from pathlib import Path

import pytest

from guardian_voc.application import GuardianService
from guardian_voc.config import Settings


ROOT = Path(__file__).parents[2]


@pytest.fixture(scope="module")
def demo_service(tmp_path_factory: pytest.TempPathFactory):
    root = tmp_path_factory.mktemp("guardian-service")
    settings = Settings(
        voc_db_path=root / "guardian.duckdb",
        voc_data_dir=root,
        voc_inbox_dir=root / "inbox",
        voc_demo_mode=True,
        voc_write_api_enabled=False,
        ai_provider="cached",
    )
    service = GuardianService(settings)
    result = service.seed_demo(reset=True)
    assert result["status"] == "completed"
    yield service
    service.close()


def test_01_seed_to_today_recomputes_the_hero_and_public_benchmark(
    demo_service: GuardianService,
) -> None:
    today = demo_service.today(role="leadership", locale="en")
    assert today.mode == "demo"
    assert today.demo_label == "Demo data — synthetic"
    assert len(today.cards) == 3

    hero = today.cards[0]
    assert hero.label == "act_now"
    assert hero.topic == "price_promotion"
    assert hero.metrics.current_numerator == 84
    assert hero.metrics.current_denominator == 494
    assert hero.metrics.baseline_numerator == 24
    assert hero.metrics.baseline_denominator == 400
    assert hero.metrics.current_share == pytest.approx(0.169060991)
    assert hero.metrics.growth_multiple == pytest.approx(2.817683184)
    assert "61%" in hero.likely_driver
    assert hero.primary_owner == "E-commerce"
    assert len(hero.recommended_actions) == 2

    assert hero.benchmark is not None and hero.benchmark.comparable
    samples = {brand.brand: brand.denominator for brand in hero.benchmark.brands}
    assert samples == {"guardian": 62, "hasaki": 100, "watsons": 100}
    shares = {brand.brand: brand.weighted_share for brand in hero.benchmark.brands}
    assert shares["guardian"] == pytest.approx(0.147623738)
    assert shares["hasaki"] == pytest.approx(0.067239186)
    assert shares["watsons"] == pytest.approx(0.086450382)
    assert hero.metrics.current_denominator != samples["guardian"]


def test_02_roles_locales_and_evidence_keep_company_facts_invariant(
    demo_service: GuardianService,
) -> None:
    leadership = demo_service.today(role="leadership", locale="en")
    marketing = demo_service.today(role="marketing", locale="en")
    vietnamese = demo_service.today(role="leadership", locale="vi")

    for base, role_view in zip(leadership.cards, marketing.cards, strict=True):
        assert role_view.metrics == base.metrics
        assert role_view.primary_owner == base.primary_owner
        assert role_view.recommended_actions == base.recommended_actions
    assert marketing.cards[0].viewer_action
    assert leadership.cards[0].viewer_action is None
    assert vietnamese.cards[0].title != leadership.cards[0].title
    assert vietnamese.cards[0].metrics == leadership.cards[0].metrics

    evidence = demo_service.evidence("insight-price-promotion")
    assert evidence is not None
    assert evidence.fact_packet["guardian_all_channel_trend"]["current_numerator"] == 84
    assert len(evidence.evidence) >= 4
    assert all(item.is_synthetic for item in evidence.evidence)
    assert "public" in (evidence.competitor_definition or "").lower()

    stored = "\n".join(
        str(row["text_redacted"])
        for row in demo_service.database.query(
            "SELECT text_redacted FROM feedback_items WHERE source_group = 'customer_service'"
        )
    )
    assert "demo.customer@example.com" not in stored
    assert "0901 234 567" not in stored


def test_03_stale_source_cannot_create_false_improvement(
    demo_service: GuardianService,
) -> None:
    demo_service.database.execute(
        "UPDATE source_status SET status = 'stale' WHERE source_group = 'social'"
    )
    demo_service._rebuild_insights(pipeline_run_id="test-stale")
    today = demo_service.today(role="leadership", locale="en")
    assert not any(card.label == "improving" for card in today.cards)
    promotion = next(card for card in today.cards if card.topic == "price_promotion")
    assert promotion.label != "act_now"

    demo_service.database.execute(
        "UPDATE source_status SET status = 'healthy', last_success_at = ? WHERE source_group = 'social'",
        [demo_service.as_of],
    )
    demo_service._rebuild_insights(pipeline_run_id="test-restored")
    assert any(
        card.label == "improving"
        for card in demo_service.today(role="leadership", locale="en").cards
    )


def test_04_demo_increment_crosses_threshold_once_and_is_idempotent(
    demo_service: GuardianService,
) -> None:
    path = ROOT / "fixtures/demo_increment/stock_cancellation.jsonl"
    first = demo_service.import_file(path, profile="generic")
    assert first.status == "completed"
    assert first.records_seen == first.records_inserted == 28

    stock = next(
        card
        for card in demo_service.today(role="leadership", locale="en").cards
        if card.topic == "availability_assortment"
    )
    assert stock.label == "act_now"
    assert stock.metrics.current_numerator == 32
    assert stock.metrics.baseline_numerator == 4
    assert stock.metrics.growth_multiple is not None and stock.metrics.growth_multiple > 1.8
    assert stock.metrics.percentage_point_change >= 0.05

    second = demo_service.import_file(path, profile="generic")
    assert second.status == "completed"
    assert second.records_inserted == 0
    assert second.records_seen == second.records_skipped == 28

