from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from guardian_voc.schemas.analysis import ClassificationResult


ROOT = Path(__file__).parents[2]


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_fixture_shape_and_hero_counts_are_deterministic() -> None:
    expected = json.loads(
        (ROOT / "fixtures/expected/hero_metrics.json").read_text(encoding="utf-8")
    )
    labels = _jsonl(ROOT / "fixtures/labels/cached_analyses.jsonl")
    raw = []
    for path in sorted((ROOT / "fixtures/raw").glob("*.jsonl")):
        raw.extend(_jsonl(path))

    assert len(raw) == expected["raw_record_count"] == 1_102
    assert all(row["metadata"]["fixture"] for row in raw)
    assert all(row["is_synthetic"] for row in raw)
    by_id = {row["source_external_id"]: row for row in raw}
    current_guardian = [
        label
        for label in labels
        if (
            by_id[label["source_external_id"]]["brand"] == "guardian"
            or (
                    by_id[label["source_external_id"]]["brand"] is None
                    and label["primary_brand"] == "guardian"
                    and label["brand_attribution_confidence"] >= 0.70
                    and label["brand_evidence_span"] is not None
                    and label["brand_evidence_span"] in by_id[label["source_external_id"]]["text"]
            )
        )
        and by_id[label["source_external_id"]]["metadata"]["period"] == "current"
        and by_id[label["source_external_id"]]["occurred_at"] is not None
        and label["is_relevant"]
        and label["confidence"] >= 0.70
    ]
    hero = [
        label
        for label in current_guardian
        if label["primary_topic"] == "price_promotion" and label["sentiment"] == "negative"
    ]
    assert len(current_guardian) == expected["guardian_current_denominator"] == 494
    assert len(hero) == expected["promotion_current_numerator"] == 84
    assert Counter(label["subtopic"] for label in hero)["unclear_eligibility"] == 51
    assert {by_id[label["source_external_id"]]["source_group"] for label in hero} == {
        "marketplace",
        "owned",
        "customer_service",
        "social",
    }


def test_cached_labels_validate_against_the_live_classifier_schema() -> None:
    paths = [
        ROOT / "fixtures/labels/cached_analyses.jsonl",
        ROOT / "fixtures/demo_increment/cached_analyses.jsonl",
    ]
    for path in paths:
        for row in _jsonl(path):
            row.pop("source_external_id")
            ClassificationResult.model_validate(row)


def test_public_repost_wave_and_privacy_cases_are_present() -> None:
    rows = _jsonl(ROOT / "fixtures/raw/guardian_social.jsonl")
    texts = Counter(row["text"] for row in rows)
    assert max(texts.values()) == 4
    assert any(row["occurred_at"] is None for row in rows)
    assert any(row["brand"] is None and len(row["brand_candidates"]) > 1 for row in rows)

    service_rows = _jsonl(ROOT / "fixtures/raw/guardian_customer_service.jsonl")
    assert any("demo.customer@example.com" in row["text"] for row in service_rows)
