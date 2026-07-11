"""Grounded card generation with a deterministic, playbook-backed fallback."""

from __future__ import annotations

from uuid import UUID, uuid5

from guardian_voc.ai.provider import AIProvider
from guardian_voc.ai.validator import validate_insight_draft
from guardian_voc.insights.playbooks import ActionPlaybook, get_playbook, viewer_action
from guardian_voc.schemas.analysis import DriverCandidate, PrimaryTopic
from guardian_voc.schemas.insights import (
    ConfidenceLevel,
    FactPacket,
    InsightCard,
    InsightDraft,
    InsightStatus,
    InsightWritingRequest,
)


_NAMESPACE = UUID("8bd498cb-7571-4e21-b1c1-9e2845476dd4")
_TOPIC_LABELS = {
    PrimaryTopic.PRODUCT_QUALITY_AUTHENTICITY: "Product quality and authenticity",
    PrimaryTopic.PRICE_PROMOTION: "Promotion eligibility needs attention",
    PrimaryTopic.AVAILABILITY_ASSORTMENT: "Availability friction needs attention",
    PrimaryTopic.DELIVERY_FULFILMENT: "Delivery friction needs attention",
    PrimaryTopic.ONLINE_CHECKOUT_PAYMENT: "Checkout friction needs attention",
    PrimaryTopic.STORE_STAFF_EXPERIENCE: "Store experience needs attention",
    PrimaryTopic.CUSTOMER_SERVICE: "Customer-service friction needs attention",
    PrimaryTopic.RETURNS_REFUNDS: "Return and refund friction needs attention",
    PrimaryTopic.LOYALTY_MEMBERSHIP: "Loyalty friction needs attention",
    PrimaryTopic.OTHER: "Feedback pattern needs review",
}


def _percent(value: float) -> str:
    rounded = round(value * 100.0, 1)
    return f"{rounded:g}%"


def _humanize(value: str) -> str:
    return value.replace("_", " ")


def _best_driver(packet: FactPacket) -> DriverCandidate | None:
    return packet.likely_driver_dimensions[0] if packet.likely_driver_dimensions else None


def deterministic_draft(
    packet: FactPacket,
    *,
    playbook: ActionPlaybook | None = None,
) -> InsightDraft:
    """Render concise copy entirely from values already in the fact packet."""

    playbook = playbook or get_playbook(packet.topic)
    trend = packet.guardian_all_channel_trend
    what_changed = (
        f"Negative {_humanize(packet.topic.value)} feedback was "
        f"{_percent(trend.weighted_current_share)} "
        f"({trend.current_numerator} of {trend.current_denominator}), versus "
        f"{_percent(trend.weighted_baseline_share)} baseline."
    )
    driver = _best_driver(packet)
    if driver is None:
        likely_driver = "No clear driver yet."
    else:
        likely_driver = (
            f"Likely driver: {_humanize(driver.value)} appeared in "
            f"{_percent(driver.current_share)} of affected feedback."
        )

    benchmark = packet.matched_public_benchmark
    if benchmark is None:
        market_context = None
    elif not benchmark.comparable:
        market_context = "Not enough comparable public feedback."
    else:
        expectation = benchmark.market_expectation
        expectation_clause = (
            ""
            if expectation is None
            else (
                f"; {expectation.brand.value.title()} praise highlights "
                f"{_humanize(expectation.praised_subtopic)}"
            )
        )
        market_context = (
            f"Matched public share: Guardian {_percent(benchmark.guardian_weighted_share)} "
            f"({benchmark.guardian_sample_size}), Hasaki "
            f"{_percent(benchmark.hasaki_weighted_share)} ({benchmark.hasaki_sample_size}), "
            f"and Watsons {_percent(benchmark.watsons_weighted_share)} "
            f"({benchmark.watsons_sample_size}){expectation_clause}."
        )
    return InsightDraft(
        title=_TOPIC_LABELS[packet.topic],
        what_changed=what_changed,
        likely_driver=likely_driver,
        market_context=market_context,
        recommended_actions=playbook.actions,
        primary_owner=playbook.primary_owner,
        supporting_owner=playbook.supporting_owner,
        evidence_ids=packet.allowed_evidence_ids[:3],
    )


def _confidence(packet: FactPacket) -> ConfidenceLevel:
    trend = packet.guardian_all_channel_trend
    checks = sum(item.confidence_passes for item in trend.strata)
    if not packet.source_health_notes and checks >= 2 and trend.current_numerator >= 20:
        return ConfidenceLevel.HIGH
    if checks >= 1 and trend.current_numerator >= 8:
        return ConfidenceLevel.MEDIUM
    return ConfidenceLevel.LOW


async def generate_insight_card(
    packet: FactPacket,
    *,
    provider: AIProvider | None = None,
    role: str = "leadership",
    status: InsightStatus = InsightStatus.OPEN,
    insight_id: str | None = None,
    insight_series_id: str | None = None,
    observation_id: str | None = None,
) -> InsightCard:
    """Use AI only when it passes all grounding rules; otherwise template facts."""

    playbook = get_playbook(packet.topic)
    generation_mode = "deterministic"
    draft: InsightDraft
    if provider is not None:
        try:
            candidate = await provider.write_insight(
                InsightWritingRequest(
                    fact_packet=packet,
                    approved_primary_owner=playbook.primary_owner,
                    approved_supporting_owner=playbook.supporting_owner,
                    approved_actions=playbook.actions,
                )
            )
            draft = validate_insight_draft(
                candidate,
                packet,
                expected_primary_owner=playbook.primary_owner,
                expected_supporting_owner=playbook.supporting_owner,
                allowed_actions=playbook.actions,
            )
            generation_mode = "ai_validated"
        except Exception:
            # Provider failures and validation failures are both safe fallbacks.
            draft = deterministic_draft(packet, playbook=playbook)
    else:
        draft = deterministic_draft(packet, playbook=playbook)
    draft = validate_insight_draft(
        draft,
        packet,
        expected_primary_owner=playbook.primary_owner,
        expected_supporting_owner=playbook.supporting_owner,
        allowed_actions=playbook.actions,
    )

    prefix = packet.digest
    insight_id = insight_id or str(uuid5(_NAMESPACE, f"insight:{prefix}"))
    insight_series_id = insight_series_id or str(
        uuid5(_NAMESPACE, f"series:{packet.topic.value}:{packet.subtopic or '*'}")
    )
    observation_id = observation_id or str(uuid5(_NAMESPACE, f"observation:{prefix}"))
    trend = packet.guardian_all_channel_trend
    reach = (
        f"{trend.current_numerator} feedback items across "
        f"{trend.source_groups} source groups; {trend.current_denominator} analyzed."
    )
    return InsightCard(
        insight_id=insight_id,
        insight_series_id=insight_series_id,
        observation_id=observation_id,
        insight_type=packet.insight_type,
        topic=packet.topic,
        subtopic=packet.subtopic,
        window_start=packet.window_start,
        window_end=packet.window_end,
        title=draft.title,
        what_changed=draft.what_changed,
        reach_summary=reach,
        likely_driver=draft.likely_driver,
        market_context=draft.market_context,
        primary_owner=draft.primary_owner,
        supporting_owner=draft.supporting_owner,
        recommended_actions=draft.recommended_actions,
        confidence=_confidence(packet),
        evidence_ids=draft.evidence_ids,
        fact_packet=packet,
        fact_packet_digest=packet.digest,
        generation_mode=generation_mode,
        status=status,
        viewer_action=viewer_action(packet.topic, role),
    )
