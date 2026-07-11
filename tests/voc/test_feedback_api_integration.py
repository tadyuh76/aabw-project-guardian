from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from guardian_voc.api.main import app, service_from_request
from guardian_voc.application import GuardianService
from guardian_voc.config import Settings
from guardian_voc.schemas.analysis import ClassificationResult
from guardian_voc.schemas.feedback import RawFeedback


def _classification(text: str, confidence: float) -> ClassificationResult:
    return ClassificationResult.model_validate(
        {
            "is_relevant": True,
            "primary_brand": "guardian",
            "mentioned_brands": ["guardian"],
            "brand_attribution_confidence": 0.99,
            "brand_evidence_span": "Guardian",
            "experience_subject": "product",
            "primary_topic": "product_quality_authenticity",
            "subtopic": "product_performance",
            "intent": "complaint",
            "sentiment": "negative",
            "sentiment_score": -0.7,
            "urgency": "normal",
            "customer_stated_reason": None,
            "journey_stage": "post_purchase",
            "evidence_span": text,
            "confidence": confidence,
        }
    )


@pytest.fixture()
def feedback_service(tmp_path: Path):
    settings = Settings(
        voc_db_path=tmp_path / "feedback-api.duckdb",
        voc_data_dir=tmp_path,
        voc_inbox_dir=tmp_path / "inbox",
        voc_demo_mode=False,
        ai_provider="cached",
    )
    service = GuardianService(settings)
    service.initialize(seed_demo=False, process_existing=False)
    rows = [
        RawFeedback(
            source_external_id="current-high",
            source_group="marketplace",
            source_platform="shopee",
            visibility="public",
            brand="guardian",
            brand_candidates=["guardian"],
            occurred_at=datetime.fromisoformat("2026-07-10T00:30:00+07:00"),
            observed_at=datetime.fromisoformat("2026-07-11T09:00:00+07:00"),
            occurred_at_quality="exact",
            language="vi",
            text="Guardian giao serum đúng mẫu nhưng chất lượng chưa như mong đợi.",
            rating=4.5,
            product_name="Serum Guardian Test",
            product_category="Chăm sóc da",
            store="Guardian Official Store",
            source_url="https://shopee.vn/private-review-path",
        ),
        RawFeedback(
            source_external_id="previous-low",
            source_group="marketplace",
            source_platform="lazada",
            visibility="public",
            brand="guardian",
            brand_candidates=["guardian"],
            occurred_at=datetime.fromisoformat("2026-07-09T23:59:00+07:00"),
            observed_at=datetime.fromisoformat("2026-07-11T09:05:00+07:00"),
            occurred_at_quality="parsed",
            language="vi",
            text="Sản phẩm Guardian này cần cải thiện thêm về hiệu quả sử dụng.",
            rating=2,
        ),
        RawFeedback(
            source_external_id="current-synthetic",
            source_group="marketplace",
            source_platform="tiktok_shop",
            visibility="public",
            brand="guardian",
            brand_candidates=["guardian"],
            occurred_at=datetime.fromisoformat("2026-07-10T12:00:00+07:00"),
            observed_at=datetime.fromisoformat("2026-07-11T09:10:00+07:00"),
            occurred_at_quality="exact",
            language="vi",
            text="Bản ghi tổng hợp không được xuất hiện trong chế độ trực tiếp.",
            rating=1,
            is_synthetic=True,
        ),
    ]
    inserted = service._ingest_raw_rows(
        rows,
        source_name="feedback_api_fixture",
        source_file=None,
    )
    assert inserted["inserted"] == 3

    confidence_by_external_id = {
        "current-high": 0.92,
        "previous-low": 0.60,
        "current-synthetic": 0.99,
    }
    for row in service.database.query(
        "SELECT feedback_id, source_external_id, text_redacted FROM feedback_items"
    ):
        confidence = confidence_by_external_id[str(row["source_external_id"])]
        service._persist_analysis(
            str(row["feedback_id"]),
            _classification(str(row["text_redacted"]), confidence),
            model_version="test-classifier",
            review_required=confidence < 0.7,
        )

    yield service
    service.close()


def test_feedback_application_filters_and_exposes_review_context(
    feedback_service: GuardianService,
) -> None:
    response = feedback_service.feedback(
        source_group=None,
        brand="guardian",
        topic=None,
        sentiment=None,
        insight_id=None,
        query=None,
        date_from=date(2026, 7, 10),
        date_to=date(2026, 7, 10),
        min_confidence=0.85,
        max_confidence=None,
        limit=20,
        offset=0,
    )

    assert response.mode == "live"
    assert response.synthetic_items == 0
    assert response.total == 1
    item = response.items[0]
    assert item.source_platform == "shopee"
    assert item.occurred_at_quality == "exact"
    assert item.observed_at is not None
    assert item.rating == pytest.approx(4.5)
    assert item.product_name == "Serum Guardian Test"
    assert item.product_category == "Chăm sóc da"
    assert item.store == "Guardian Official Store"
    assert not item.is_synthetic
    assert "source_url" not in item.model_dump()


def test_feedback_route_forwards_filters_and_rejects_inverted_ranges(
    feedback_service: GuardianService,
) -> None:
    app.dependency_overrides[service_from_request] = lambda: feedback_service
    client = TestClient(app)
    try:
        response = client.get(
            "/api/v1/feedback",
            params={
                "date_from": "2026-07-10",
                "date_to": "2026-07-10",
                "min_confidence": "0.85",
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["mode"] == "live"
        assert payload["synthetic_items"] == 0
        assert payload["total"] == 1
        assert payload["items"][0]["product_name"] == "Serum Guardian Test"
        assert payload["items"][0]["rating"] == pytest.approx(4.5)
        assert "source_url" not in payload["items"][0]

        low_confidence = client.get(
            "/api/v1/feedback", params={"max_confidence": "0.85"}
        )
        assert low_confidence.status_code == 200
        assert low_confidence.json()["total"] == 1
        assert low_confidence.json()["items"][0]["source_platform"] == "lazada"

        invalid_dates = client.get(
            "/api/v1/feedback",
            params={"date_from": "2026-07-11", "date_to": "2026-07-10"},
        )
        assert invalid_dates.status_code == 422

        invalid_confidence = client.get(
            "/api/v1/feedback",
            params={"min_confidence": "0.9", "max_confidence": "0.8"},
        )
        assert invalid_confidence.status_code == 422
    finally:
        client.close()
        app.dependency_overrides.pop(service_from_request, None)
