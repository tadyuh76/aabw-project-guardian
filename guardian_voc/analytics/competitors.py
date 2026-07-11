"""Fair public-only competitor cohorts with one common set of weights."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

from guardian_voc.analytics.metrics import units_in_window
from guardian_voc.schemas.analysis import (
    AnalysisWindows,
    AnalyticsUnit,
    Brand,
    ExperienceSubject,
    PrimaryTopic,
    Sentiment,
    SourceGroup,
    Visibility,
)
from guardian_voc.schemas.insights import (
    BenchmarkBrandCell,
    BenchmarkExclusion,
    BenchmarkStratumFact,
    MarketExpectationFact,
    MatchedPublicBenchmarkFact,
)


_BRANDS = (Brand.GUARDIAN, Brand.HASAKI, Brand.WATSONS)
_UNKNOWN_LANGUAGES = {"", "unknown", "und", "undetermined"}


@dataclass(frozen=True, order=True)
class _BenchmarkKey:
    source_group: SourceGroup
    source_platform: str
    product_category: str | None
    language: str
    experience_subject: ExperienceSubject

    def stable_key(self) -> str:
        return "|".join(
            (
                self.source_group.value,
                self.source_platform,
                self.product_category or "<none>",
                self.language,
                self.experience_subject.value,
            )
        )


def _cell(records: Sequence[AnalyticsUnit], topic: PrimaryTopic) -> BenchmarkBrandCell:
    denominator = len(records)
    numerator = sum(
        record.sentiment is Sentiment.NEGATIVE and record.primary_topic is topic
        for record in records
    )
    return BenchmarkBrandCell(
        numerator=numerator,
        denominator=denominator,
        share=numerator / denominator,
    )


def _market_expectation(
    matched_records: Sequence[AnalyticsUnit],
    *,
    topic: PrimaryTopic,
    minimum_support: int,
) -> MarketExpectationFact | None:
    praise = [
        record
        for record in matched_records
        if record.resolved_brand in {Brand.HASAKI, Brand.WATSONS}
        and record.sentiment is Sentiment.POSITIVE
        and record.primary_topic is topic
        and record.subtopic != "other"
    ]
    counts = Counter((record.resolved_brand, record.subtopic) for record in praise)
    eligible = [
        (support, brand, subtopic)
        for (brand, subtopic), support in counts.items()
        if support >= minimum_support
    ]
    if not eligible:
        return None
    support, brand, subtopic = sorted(
        eligible,
        key=lambda item: (-item[0], item[1].value, item[2]),
    )[0]
    evidence_ids = tuple(
        sorted(
            record.feedback_id
            for record in praise
            if record.resolved_brand is brand and record.subtopic == subtopic
        )
    )
    return MarketExpectationFact(
        brand=brand,
        praised_subtopic=subtopic,
        support=support,
        evidence_ids=evidence_ids,
    )


def build_matched_public_benchmark(
    units: Sequence[AnalyticsUnit],
    *,
    topic: PrimaryTopic,
    windows: AnalysisWindows,
    experience_subject: ExperienceSubject = ExperienceSubject.RETAILER,
    minimum_sample: int = 10,
    minimum_praise_support: int = 2,
    allow_inferred_dates: bool = False,
) -> MatchedPublicBenchmarkFact:
    """Compare only strata present above threshold for every named brand."""

    dated = units_in_window(
        units,
        start=windows.current_start,
        end=windows.current_end,
        allow_inferred_dates=allow_inferred_dates,
    )
    eligible = [
        unit
        for unit in dated
        if unit.visibility is Visibility.PUBLIC
        and unit.source_group in {SourceGroup.MARKETPLACE, SourceGroup.SOCIAL}
        and unit.resolved_brand in _BRANDS
        and unit.experience_subject is experience_subject
        and unit.is_relevant
        and unit.analysis_succeeded
        and unit.language is not None
        and unit.language.strip().lower() not in _UNKNOWN_LANGUAGES
    ]
    grouped: dict[_BenchmarkKey, dict[Brand, list[AnalyticsUnit]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for unit in eligible:
        key = _BenchmarkKey(
            source_group=unit.source_group,
            source_platform=unit.source_platform,
            product_category=unit.product_category,
            language=unit.language.strip().lower(),  # type: ignore[union-attr]
            experience_subject=unit.experience_subject,
        )
        grouped[key][unit.resolved_brand].append(unit)  # type: ignore[index]

    common: list[tuple[_BenchmarkKey, dict[Brand, list[AnalyticsUnit]]]] = []
    exclusions: list[BenchmarkExclusion] = []
    for key in sorted(grouped, key=lambda item: item.stable_key()):
        records_by_brand = grouped[key]
        reasons = tuple(
            f"{brand.value}_below_minimum_sample"
            for brand in _BRANDS
            if len(records_by_brand.get(brand, ())) < minimum_sample
        )
        if reasons:
            exclusions.append(BenchmarkExclusion(stratum_key=key.stable_key(), reasons=reasons))
        else:
            common.append((key, records_by_brand))

    if not common:
        return MatchedPublicBenchmarkFact(
            experience_subject=experience_subject.value,
            comparable=False,
            insufficiency_reason="Not enough comparable public feedback",
            excluded_strata=tuple(exclusions),
        )

    pooled_denominator = sum(
        len(records_by_brand[brand])
        for _, records_by_brand in common
        for brand in _BRANDS
    )
    strata: list[BenchmarkStratumFact] = []
    all_matched_records: list[AnalyticsUnit] = []
    weighted = {brand: 0.0 for brand in _BRANDS}
    samples = {brand: 0 for brand in _BRANDS}
    for key, records_by_brand in common:
        cells = {brand: _cell(records_by_brand[brand], topic) for brand in _BRANDS}
        weight = sum(cell.denominator for cell in cells.values()) / pooled_denominator
        for brand in _BRANDS:
            weighted[brand] += weight * cells[brand].share
            samples[brand] += cells[brand].denominator
            all_matched_records.extend(records_by_brand[brand])
        strata.append(
            BenchmarkStratumFact(
                source_group=key.source_group,
                source_platform=key.source_platform,
                product_category=key.product_category,
                language=key.language,
                experience_subject=key.experience_subject.value,
                common_weight=weight,
                guardian=cells[Brand.GUARDIAN],
                hasaki=cells[Brand.HASAKI],
                watsons=cells[Brand.WATSONS],
            )
        )

    return MatchedPublicBenchmarkFact(
        experience_subject=experience_subject.value,
        comparable=True,
        strata=tuple(strata),
        excluded_strata=tuple(exclusions),
        guardian_weighted_share=weighted[Brand.GUARDIAN],
        hasaki_weighted_share=weighted[Brand.HASAKI],
        watsons_weighted_share=weighted[Brand.WATSONS],
        guardian_sample_size=samples[Brand.GUARDIAN],
        hasaki_sample_size=samples[Brand.HASAKI],
        watsons_sample_size=samples[Brand.WATSONS],
        source_platforms=tuple(sorted({key.source_platform for key, _ in common})),
        market_expectation=_market_expectation(
            all_matched_records,
            topic=topic,
            minimum_support=minimum_praise_support,
        ),
    )
