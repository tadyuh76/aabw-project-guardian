"""Evidence-backed likely-driver ranking without causal claims."""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from collections.abc import Callable, Sequence

from guardian_voc.analytics.metrics import units_in_window
from guardian_voc.schemas.analysis import (
    AnalysisWindows,
    AnalyticsUnit,
    Brand,
    DriverCandidate,
    PrimaryTopic,
    Sentiment,
)


def _normalize_reason(value: str | None) -> str | None:
    if not value:
        return None
    normalized = unicodedata.normalize("NFKC", value).strip().lower()
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized or None


def _dimension_extractors() -> dict[str, Callable[[AnalyticsUnit], str | None]]:
    return {
        "subtopic": lambda unit: unit.subtopic if unit.subtopic != "other" else None,
        "customer_stated_reason": lambda unit: _normalize_reason(unit.customer_stated_reason),
        "source_group": lambda unit: unit.source_group.value,
        "product_category": lambda unit: unit.product_category,
        "journey_stage": lambda unit: (
            None if unit.journey_stage.value == "unknown" else unit.journey_stage.value
        ),
        "region": lambda unit: unit.region,
        "store": lambda unit: unit.store,
    }


def _issue_cohort(
    units: Sequence[AnalyticsUnit],
    *,
    topic: PrimaryTopic,
    brand: Brand,
) -> tuple[AnalyticsUnit, ...]:
    return tuple(
        unit
        for unit in units
        if unit.resolved_brand is brand
        and unit.is_relevant
        and unit.analysis_succeeded
        and unit.sentiment is Sentiment.NEGATIVE
        and unit.primary_topic is topic
    )


def rank_likely_drivers(
    units: Sequence[AnalyticsUnit],
    *,
    topic: PrimaryTopic,
    windows: AnalysisWindows,
    brand: Brand = Brand.GUARDIAN,
    minimum_support: int = 3,
    allow_inferred_dates: bool = False,
) -> tuple[DriverCandidate, ...]:
    """Rank concentrations by breadth, excess contribution, support, then lift."""

    current = _issue_cohort(
        units_in_window(
            units,
            start=windows.current_start,
            end=windows.current_end,
            allow_inferred_dates=allow_inferred_dates,
        ),
        topic=topic,
        brand=brand,
    )
    baseline = _issue_cohort(
        units_in_window(
            units,
            start=windows.baseline_start,
            end=windows.baseline_end,
            allow_inferred_dates=allow_inferred_dates,
        ),
        topic=topic,
        brand=brand,
    )
    if not current:
        return ()

    candidates: list[DriverCandidate] = []
    for dimension, extractor in _dimension_extractors().items():
        current_groups: dict[str, list[AnalyticsUnit]] = defaultdict(list)
        baseline_groups: dict[str, list[AnalyticsUnit]] = defaultdict(list)
        for unit in current:
            value = extractor(unit)
            if value:
                current_groups[value].append(unit)
        for unit in baseline:
            value = extractor(unit)
            if value:
                baseline_groups[value].append(unit)
        for value, records in current_groups.items():
            support = len(records)
            if support < minimum_support:
                continue
            baseline_support = len(baseline_groups.get(value, ()))
            current_share = support / len(current)
            baseline_share = 0.0 if not baseline else baseline_support / len(baseline)
            candidates.append(
                DriverCandidate(
                    dimension=dimension,
                    value=value,
                    support=support,
                    current_share=current_share,
                    baseline_support=baseline_support,
                    baseline_share=baseline_share,
                    lift=None if baseline_share == 0 else current_share / baseline_share,
                    contribution_to_excess=max(
                        0.0, support - len(current) * baseline_share
                    ),
                    source_group_breadth=len({record.source_group for record in records}),
                    evidence_ids=tuple(sorted(record.feedback_id for record in records)),
                )
            )

    def rank_key(candidate: DriverCandidate) -> tuple[object, ...]:
        return (
            candidate.source_group_breadth >= 2,
            candidate.contribution_to_excess,
            candidate.support,
            candidate.lift if candidate.lift is not None else float("inf"),
            candidate.source_group_breadth,
            # Reversed below; these stable fields make ties reproducible.
            candidate.dimension,
            candidate.value,
        )

    return tuple(sorted(candidates, key=rank_key, reverse=True))


def select_likely_driver(
    candidates: Sequence[DriverCandidate],
    *,
    prefer_cross_source: bool = True,
) -> DriverCandidate | None:
    if not candidates:
        return None
    if prefer_cross_source:
        confirmed = [candidate for candidate in candidates if candidate.source_group_breadth >= 2]
        if confirmed:
            return confirmed[0]
    return candidates[0]
