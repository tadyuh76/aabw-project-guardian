"""Deterministic Today ranking and the non-negotiable three-card cap."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence

from guardian_voc.schemas.insights import ConfidenceLevel, InsightType, RankableInsight


_TYPE_SEVERITY = {
    InsightType.ACT_NOW: 3,
    InsightType.MARKET_GAP: 2,
    InsightType.WATCH: 1,
    InsightType.IMPROVING: 0,
}
_CONFIDENCE = {
    ConfidenceLevel.HIGH: 2,
    ConfidenceLevel.MEDIUM: 1,
    ConfidenceLevel.LOW: 0,
}


def _key(candidate: RankableInsight, owner_load: int = 0) -> tuple[object, ...]:
    return (
        candidate.urgency,
        _TYPE_SEVERITY[candidate.insight_type],
        candidate.excess_items,
        candidate.growth_multiple or 0.0,
        candidate.source_group_breadth,
        _CONFIDENCE[candidate.confidence],
        -owner_load,
        # Use reverse ordering for all substantive fields, but stable ID is
        # handled separately by the caller to keep lexical ascending ties.
    )


def rank_today_candidates(
    candidates: Sequence[RankableInsight],
    *,
    limit: int = 3,
) -> tuple[RankableInsight, ...]:
    """Rank by documented fields and prefer owner diversity only after evidence."""

    if limit < 0 or limit > 3:
        raise ValueError("Today card limit must be between zero and three")
    remaining = [candidate for candidate in candidates if candidate.healthy]
    selected: list[RankableInsight] = []
    owner_counts: Counter[object] = Counter()
    while remaining and len(selected) < limit:
        remaining.sort(
            key=lambda candidate: candidate.candidate_id,
        )
        remaining.sort(
            key=lambda candidate: _key(candidate, owner_counts[candidate.primary_owner]),
            reverse=True,
        )
        chosen = remaining.pop(0)
        selected.append(chosen)
        owner_counts[chosen.primary_owner] += 1
    return tuple(selected)
