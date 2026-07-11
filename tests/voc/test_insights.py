from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from guardian_voc.ai.validator import (
    InsightValidationError,
    insight_copy_word_count,
    validate_insight_draft,
)
from guardian_voc.insights.fact_packets import build_fact_packet
from guardian_voc.insights.generator import (
    deterministic_draft,
    generate_insight_card,
)
from guardian_voc.insights.playbooks import get_playbook, load_playbooks
from guardian_voc.insights.ranking import rank_today_candidates
from guardian_voc.schemas.analysis import (
    AnalysisWindows,
    Brand,
    DriverCandidate,
    ExperienceSubject,
    PrimaryTopic,
    RateCell,
    SourceGroup,
    SourceStratum,
    TrendResult,
    TrendStratumResult,
)
from guardian_voc.schemas.insights import (
    BenchmarkBrandCell,
    BenchmarkStratumFact,
    ConfidenceLevel,
    InsightDraft,
    InsightType,
    MatchedPublicBenchmarkFact,
    RankableInsight,
    Team,
    TopSubtopicFact,
)


def _packet():
    windows = AnalysisWindows(
        current_start=datetime(2026, 7, 4, 17, tzinfo=timezone.utc),
        current_end=datetime(2026, 7, 11, 17, tzinfo=timezone.utc),
        baseline_start=datetime(2026, 6, 6, 17, tzinfo=timezone.utc),
        baseline_end=datetime(2026, 7, 4, 17, tzinfo=timezone.utc),
        business_timezone="Asia/Ho_Chi_Minh",
        current_days=7,
        baseline_days=28,
    )
    strata = []
    for group, platform in (
        (SourceGroup.MARKETPLACE, "shopee"),
        (SourceGroup.OWNED, "guardian_ecommerce"),
    ):
        strata.append(
            TrendStratumResult(
                stratum=SourceStratum(
                    brand=Brand.GUARDIAN,
                    source_group=group,
                    source_platform=platform,
                    experience_subject=ExperienceSubject.RETAILER,
                ),
                current=RateCell(numerator=42, denominator=247, share=42 / 247),
                baseline=RateCell(numerator=15, denominator=247, share=15 / 247),
                baseline_weight=0.5,
                excess_items=27,
                percentage_point_change=27 / 247,
                growth_multiple=2.8,
                confidence_p_value=0.001,
                confidence_passes=True,
                direction="up",
            )
        )
    trend = TrendResult(
        topic=PrimaryTopic.PRICE_PROMOTION,
        brand=Brand.GUARDIAN,
        scope="all_channel",
        windows=windows,
        current_numerator=84,
        current_denominator=494,
        baseline_numerator=30,
        baseline_denominator=494,
        weighted_current_share=42 / 247,
        weighted_baseline_share=15 / 247,
        growth_multiple=2.8,
        percentage_point_change=27 / 247,
        excess_items=54,
        source_groups_moving=(SourceGroup.MARKETPLACE, SourceGroup.OWNED),
        participating_strata=tuple(strata),
        qualifies=True,
    )
    driver = DriverCandidate(
        dimension="subtopic",
        value="unclear_eligibility",
        support=51,
        current_share=51 / 84,
        baseline_support=10,
        baseline_share=1 / 3,
        lift=(51 / 84) / (1 / 3),
        contribution_to_excess=23,
        source_group_breadth=2,
        evidence_ids=("evidence-1", "evidence-2"),
    )
    benchmark = MatchedPublicBenchmarkFact(
        experience_subject="retailer",
        comparable=True,
        strata=(
            BenchmarkStratumFact(
                source_group=SourceGroup.MARKETPLACE,
                source_platform="shopee",
                product_category="skincare",
                language="vi",
                experience_subject="retailer",
                common_weight=1.0,
                guardian=BenchmarkBrandCell(numerator=14, denominator=100, share=0.14),
                hasaki=BenchmarkBrandCell(numerator=7, denominator=100, share=0.07),
                watsons=BenchmarkBrandCell(numerator=9, denominator=100, share=0.09),
            ),
        ),
        guardian_weighted_share=0.14,
        hasaki_weighted_share=0.07,
        watsons_weighted_share=0.09,
        guardian_sample_size=100,
        hasaki_sample_size=100,
        watsons_sample_size=100,
        source_platforms=("shopee",),
    )
    return build_fact_packet(
        trend,
        insight_type=InsightType.ACT_NOW,
        subtopic="unclear_eligibility",
        top_subtopic=TopSubtopicFact(name="unclear_eligibility", support=51, share=51 / 84),
        likely_drivers=(driver,),
        benchmark=benchmark,
        allowed_evidence_ids=("evidence-1", "evidence-2"),
    )


def test_fact_packet_is_immutable_and_has_stable_digest() -> None:
    packet = _packet()
    rebuilt = _packet()
    assert packet.digest == rebuilt.digest
    with pytest.raises(ValidationError):
        packet.topic = PrimaryTopic.OTHER
    with pytest.raises(TypeError):
        packet.allowed_evidence_ids[0] = "changed"


def test_deterministic_draft_is_grounded_playbook_copy_under_word_limit() -> None:
    packet = _packet()
    playbook = get_playbook(packet.topic)
    draft = deterministic_draft(packet)
    validated = validate_insight_draft(
        draft,
        packet,
        expected_primary_owner=playbook.primary_owner,
        expected_supporting_owner=playbook.supporting_owner,
        allowed_actions=playbook.actions,
    )
    assert validated.primary_owner is Team.ECOMMERCE
    assert len(validated.recommended_actions) == 2
    assert insight_copy_word_count(validated) <= 80
    assert "Likely driver" in validated.likely_driver


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"what_changed": "Negative feedback reached 999%."}, "number"),
        ({"evidence_ids": ("unknown-id",)}, "evidence"),
        ({"likely_driver": "The campaign caused all complaints."}, "causal"),
        (
            {
                "recommended_actions": (
                    "Verify checkout eligibility behavior.",
                    "Clarify eligibility before purchase.",
                    "Launch an unsupported campaign.",
                )
            },
            "at most two",
        ),
        ({"primary_owner": Team.MARKETING}, "primary owner"),
    ],
)
def test_grounding_validator_rejects_unsupported_claims(changes, message) -> None:
    packet = _packet()
    playbook = get_playbook(packet.topic)
    invalid = deterministic_draft(packet).model_copy(update=changes)
    with pytest.raises(InsightValidationError, match=message):
        validate_insight_draft(
            invalid,
            packet,
            expected_primary_owner=playbook.primary_owner,
            expected_supporting_owner=playbook.supporting_owner,
            allowed_actions=playbook.actions,
        )


class _InvalidWriter:
    model_version = "invalid-writer"

    async def classify(self, request):  # pragma: no cover - protocol completeness
        raise AssertionError(request)

    async def write_insight(self, request):
        draft = deterministic_draft(request.fact_packet)
        return draft.model_copy(update={"what_changed": "Feedback increased by 999%."})


@pytest.mark.asyncio
async def test_invalid_ai_writer_falls_back_to_deterministic_card() -> None:
    card = await generate_insight_card(_packet(), provider=_InvalidWriter())
    assert card.generation_mode == "deterministic"
    assert "999" not in card.what_changed
    assert card.fact_packet_digest == card.fact_packet.digest
    assert card.primary_owner is Team.ECOMMERCE


@pytest.mark.asyncio
async def test_role_guidance_never_changes_fact_owner_or_core_actions() -> None:
    leadership = await generate_insight_card(_packet(), role="leadership")
    marketing = await generate_insight_card(_packet(), role="marketing")
    assert leadership.primary_owner == marketing.primary_owner == Team.ECOMMERCE
    assert leadership.recommended_actions == marketing.recommended_actions
    assert leadership.fact_packet_digest == marketing.fact_packet_digest
    assert leadership.viewer_action is None
    assert marketing.viewer_action is not None


def test_every_topic_has_a_bounded_playbook() -> None:
    playbooks = load_playbooks()
    assert set(playbooks) == set(PrimaryTopic)
    assert all(1 <= len(playbook.actions) <= 2 for playbook in playbooks.values())
    assert all(playbook.primary_owner in set(Team) for playbook in playbooks.values())


def test_today_ranking_caps_three_and_uses_owner_load_only_after_priority() -> None:
    equal = [
        RankableInsight(
            candidate_id="a",
            insight_type=InsightType.ACT_NOW,
            topic=PrimaryTopic.PRICE_PROMOTION,
            primary_owner=Team.ECOMMERCE,
            urgency=3,
            excess_items=10,
            growth_multiple=2,
            source_group_breadth=2,
            confidence=ConfidenceLevel.HIGH,
        ),
        RankableInsight(
            candidate_id="b",
            insight_type=InsightType.ACT_NOW,
            topic=PrimaryTopic.DELIVERY_FULFILMENT,
            primary_owner=Team.ECOMMERCE,
            urgency=3,
            excess_items=10,
            growth_multiple=2,
            source_group_breadth=2,
            confidence=ConfidenceLevel.HIGH,
        ),
        RankableInsight(
            candidate_id="c",
            insight_type=InsightType.ACT_NOW,
            topic=PrimaryTopic.LOYALTY_MEMBERSHIP,
            primary_owner=Team.MARKETING,
            urgency=3,
            excess_items=10,
            growth_multiple=2,
            source_group_breadth=2,
            confidence=ConfidenceLevel.HIGH,
        ),
        RankableInsight(
            candidate_id="unhealthy",
            insight_type=InsightType.ACT_NOW,
            topic=PrimaryTopic.RETURNS_REFUNDS,
            primary_owner=Team.CUSTOMER_SERVICE,
            urgency=3,
            excess_items=1_000,
            growth_multiple=10,
            source_group_breadth=4,
            confidence=ConfidenceLevel.HIGH,
            healthy=False,
        ),
    ]
    ranked = rank_today_candidates(equal, limit=3)
    assert len(ranked) == 3
    assert [candidate.candidate_id for candidate in ranked] == ["a", "c", "b"]
    assert all(candidate.candidate_id != "unhealthy" for candidate in ranked)
    with pytest.raises(ValueError, match="between zero and three"):
        rank_today_candidates(equal, limit=4)
