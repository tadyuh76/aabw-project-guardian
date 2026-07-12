from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

import guardian_voc.application as application_module
from guardian_voc.api.main import app, service_from_request
from guardian_voc.application import GuardianService
from guardian_voc.config import Settings
from guardian_voc.schemas.analysis import ClassificationResult
from guardian_voc.schemas.feedback import RawFeedback


AS_OF = datetime.fromisoformat("2026-07-11T12:00:00+07:00")


class FixedAsOfGuardianService(GuardianService):
    @property
    def as_of(self) -> datetime:
        return AS_OF


def _service(
    tmp_path: Path,
    name: str,
    *,
    competitor_min_sample: int = 10,
) -> FixedAsOfGuardianService:
    settings = Settings(
        voc_db_path=tmp_path / f"{name}.duckdb",
        voc_data_dir=tmp_path,
        voc_inbox_dir=tmp_path / "inbox",
        voc_demo_mode=False,
        voc_competitor_min_sample=competitor_min_sample,
        ai_provider="cached",
    )
    service = FixedAsOfGuardianService(settings)
    service.initialize(seed_demo=False, process_existing=False)
    return service


def _raw(
    external_id: str,
    *,
    occurred_at: str | None,
    text: str,
    rating: float | None,
    product: bool = True,
    product_id: str = "P-1",
    product_name: str = "Serum A",
    brand: str = "guardian",
    source_group: str = "marketplace",
    source_platform: str = "shopee",
    visibility: str = "public",
    source_url: str | None = None,
    synthetic: bool = False,
) -> RawFeedback:
    return RawFeedback(
        source_external_id=external_id,
        source_group=source_group,
        source_platform=source_platform,
        visibility=visibility,
        brand=brand,
        brand_candidates=[brand],
        occurred_at=datetime.fromisoformat(occurred_at) if occurred_at else None,
        observed_at=datetime.fromisoformat("2026-07-11T10:00:00+07:00"),
        occurred_at_quality="exact" if occurred_at else "missing",
        language="vi",
        text=text,
        rating=rating,
        product_name=product_name if product else None,
        product_category="Serum" if product else None,
        source_url=source_url,
        metadata=(
            {
                "product_id": product_id,
                "short_name": product_name,
                "sku": f"SKU-{product_id}",
                "pack": "30 ml",
                "experience_subject": "product",
            }
            if product
            else {"experience_subject": "product"}
        ),
        is_synthetic=synthetic,
    )


def _classification(
    text: str,
    *,
    intent: str,
    sentiment: str,
    sentiment_score: float,
    brand: str = "guardian",
) -> ClassificationResult:
    return ClassificationResult.model_validate(
        {
            "is_relevant": True,
            "primary_brand": brand,
            "mentioned_brands": [brand],
            "brand_attribution_confidence": 0.99,
            "brand_evidence_span": "Guardian",
            "experience_subject": "product",
            "primary_topic": "product_quality_authenticity",
            "subtopic": "product_performance",
            "intent": intent,
            "sentiment": sentiment,
            "sentiment_score": sentiment_score,
            "urgency": "normal",
            "customer_stated_reason": None,
            "journey_stage": "post_purchase",
            "evidence_span": text,
            "confidence": 0.95,
        }
    )


def _persist_by_external_id(
    service: GuardianService,
    classifications: dict[str, tuple[str, str, float]],
) -> None:
    for row in service.database.query(
        "SELECT feedback_id, source_external_id, text_redacted FROM feedback_items"
    ):
        external_id = str(row["source_external_id"])
        intent, sentiment, score = classifications[external_id]
        service._persist_analysis(
            str(row["feedback_id"]),
            _classification(
                str(row["text_redacted"]),
                intent=intent,
                sentiment=sentiment,
                sentiment_score=score,
            ),
            model_version="dashboard-test",
            review_required=False,
        )


def test_dashboard_aggregates_current_and_baseline_product_periods(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path, "dashboard-periods")
    rows = [
        _raw(
            "current-complaint",
            occurred_at="2026-07-10T09:00:00+07:00",
            text="Guardian Serum A gây thất vọng và hiệu quả kém.",
            rating=1,
        ),
        _raw(
            "current-positive",
            occurred_at="2026-07-09T09:00:00+07:00",
            text="Guardian Serum A dùng tốt và dịu da.",
            rating=5,
        ),
        _raw(
            "current-neutral",
            occurred_at="2026-07-08T09:00:00+07:00",
            text="Guardian Serum A có dùng buổi sáng được không?",
            rating=3,
        ),
        _raw(
            "baseline-complaint",
            occurred_at="2026-07-03T09:00:00+07:00",
            text="Guardian Serum A trước đây không đạt kỳ vọng.",
            rating=2,
        ),
        _raw(
            "baseline-positive",
            occurred_at="2026-07-02T09:00:00+07:00",
            text="Guardian Serum A trước đây dùng ổn.",
            rating=4,
        ),
        _raw(
            "synthetic-hidden",
            occurred_at="2026-07-10T10:00:00+07:00",
            text="Synthetic Guardian Serum A must not be counted live.",
            rating=1,
            synthetic=True,
        ),
    ]
    assert service._ingest_raw_rows(
        rows, source_name="dashboard_period_fixture", source_file=None
    )["inserted"] == 6
    _persist_by_external_id(
        service,
        {
            "current-complaint": ("complaint", "negative", -0.8),
            "current-positive": ("praise", "positive", 0.6),
            "current-neutral": ("question_request", "neutral", 0.0),
            "baseline-complaint": ("complaint", "negative", -0.5),
            "baseline-positive": ("praise", "positive", 0.5),
            "synthetic-hidden": ("complaint", "negative", -1.0),
        },
    )

    result = service.dashboard()

    assert result.mode == "live"
    assert result.data_state == "ready"
    assert result.coverage.model_dump() == {
        "feedback_items": 5,
        "analyzed_items": 5,
        "relevant_items": 5,
        "time_eligible_items": 5,
        "product_attributed_items": 5,
    }
    assert len(result.products) == 1
    product = result.products[0]
    assert product.id == "P-1"
    assert product.name == "Serum A"
    assert product.short_name == "Serum A"
    assert product.metadata_complete is True
    assert product.rating == pytest.approx(3.0)
    assert product.rating_count == 5
    assert product.total_feedback == 5
    assert product.current.model_dump() == {
        "feedback": 3,
        "complaints": 1,
        "positive": 1,
        "neutral": 1,
    }
    assert product.baseline.model_dump() == {
        "feedback": 2,
        "complaints": 1,
        "positive": 1,
        "neutral": 0,
    }
    assert product.sentiment_delta == pytest.approx(-6.6666666667)
    assert product.sources == {"marketplace": 3}
    assert [theme.model_dump() for theme in product.themes] == [
        {"label": "product_performance", "count": 1}
    ]
    assert [item.model_dump() for item in product.rating_distribution] == [
        {"rating": 5, "count": 1},
        {"rating": 3, "count": 1},
        {"rating": 1, "count": 1},
    ]
    assert [item.model_dump() for item in product.baseline_rating_distribution] == [
        {"rating": 4, "count": 1},
        {"rating": 2, "count": 1},
    ]
    shopee_trend = [item for item in product.rating_trend if item.platform == "Shopee"]
    assert len([item for item in shopee_trend if not item.predicted]) == 2
    assert len([item for item in shopee_trend if item.predicted]) == 1
    assert {item.platform for item in product.rating_trend} == {"Shopee"}
    assert [item.average_rating for item in shopee_trend if not item.predicted] == [
        pytest.approx(3.0),
        pytest.approx(3.0),
    ]
    assert [item.model_dump() for item in product.negative_feedback] == [
        {
            "label": "product_quality_authenticity",
            "count": 1,
            "baseline_count": 1,
            "percentage_change": 0.0,
        }
    ]
    assert [item.model_dump() for item in product.problems] == [
        {
            "label": "product_performance",
            "count": 1,
            "baseline_count": 1,
            "percentage_change": 0.0,
        }
    ]
    assert len(result.evidence) == 5
    assert all(item.product_id == "P-1" for item in result.evidence)
    word_counts = {item.keyword: item.count for item in result.word_cloud}
    assert word_counts["serum"] == 5
    assert "guardian" not in word_counts
    assert "synthetic" not in word_counts
    assert "không" not in word_counts
    assert "được" not in word_counts
    assert "dùng" in word_counts
    assert result.benchmark.comparable is False
    assert result.benchmark.aggregates == []
    assert result.benchmark.reason

    app.dependency_overrides[service_from_request] = lambda: service
    client = TestClient(app)
    try:
        response = client.get("/api/v1/dashboard")
        assert response.status_code == 200
        payload = response.json()
        assert payload["products"][0]["id"] == "P-1"
        assert payload["products"][0]["current"]["complaints"] == 1
        assert payload["coverage"]["feedback_items"] == 5
        assert payload["word_cloud"][0]["keyword"] == "serum"
    finally:
        client.close()
        app.dependency_overrides.pop(service_from_request, None)
        service.close()


def test_dashboard_range_query_changes_product_period_counts(tmp_path: Path) -> None:
    service = _service(tmp_path, "dashboard-range-filter")
    rows = [
        _raw(
            "recent-complaint",
            occurred_at="2026-07-10T09:00:00+07:00",
            text="Guardian Serum A gần đây gây thất vọng.",
            rating=1,
        ),
        _raw(
            "older-positive",
            occurred_at="2026-01-10T09:00:00+07:00",
            text="Guardian Serum A đầu năm dùng tốt.",
            rating=5,
        ),
        _raw(
            "previous-year-complaint",
            occurred_at="2025-08-10T09:00:00+07:00",
            text="Guardian Serum A năm trước giao hàng kém.",
            rating=2,
        ),
    ]
    assert service._ingest_raw_rows(
        rows, source_name="dashboard_range_fixture", source_file=None
    )["inserted"] == 3
    _persist_by_external_id(
        service,
        {
            "recent-complaint": ("complaint", "negative", -0.8),
            "older-positive": ("praise", "positive", 0.8),
            "previous-year-complaint": ("complaint", "negative", -0.6),
        },
    )

    thirty_days = service.dashboard(dashboard_range="30d")
    one_year = service.dashboard(dashboard_range="1y")

    zone = ZoneInfo(thirty_days.windows.business_timezone)
    assert thirty_days.windows.current_start.astimezone(zone).date().isoformat() == "2026-06-11"
    assert one_year.windows.current_start.astimezone(zone).date().isoformat() == "2025-07-11"
    assert thirty_days.products[0].current.model_dump() == {
        "feedback": 1,
        "complaints": 1,
        "positive": 0,
        "neutral": 0,
    }
    assert one_year.products[0].current.model_dump() == {
        "feedback": 3,
        "complaints": 2,
        "positive": 1,
        "neutral": 0,
    }
    assert [item.count for item in thirty_days.word_cloud if item.keyword == "serum"] == [1]
    assert [item.count for item in one_year.word_cloud if item.keyword == "serum"] == [3]

    app.dependency_overrides[service_from_request] = lambda: service
    client = TestClient(app)
    try:
        response = client.get("/api/v1/dashboard", params={"range": "30d"})
        assert response.status_code == 200
        assert response.json()["products"][0]["current"]["feedback"] == 1
        invalid = client.get(
            "/api/v1/dashboard",
            params={"range": "custom", "date_from": "2026-07-10"},
        )
        assert invalid.status_code == 422
    finally:
        client.close()
        app.dependency_overrides.pop(service_from_request, None)
        service.close()


def test_dashboard_rating_trend_includes_guardian_ecommerce_and_custom_forecast(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path, "dashboard-owned-rating-trend")
    rows = [
        _raw(
            "owned-week-1",
            occurred_at="2026-06-02T09:00:00+07:00",
            text="Guardian Serum A chính hãng và giao tốt.",
            rating=4,
            source_group="owned",
            source_platform="guardian_ecommerce",
            visibility="owned",
        ),
        _raw(
            "owned-week-3",
            occurred_at="2026-06-15T09:00:00+07:00",
            text="Guardian Serum A lần sau tốt hơn.",
            rating=5,
            source_group="owned",
            source_platform="guardian_ecommerce",
            visibility="owned",
        ),
    ]
    assert service._ingest_raw_rows(
        rows, source_name="dashboard_owned_trend_fixture", source_file=None
    )["inserted"] == 2
    _persist_by_external_id(
        service,
        {
            "owned-week-1": ("praise", "positive", 0.6),
            "owned-week-3": ("praise", "positive", 0.8),
        },
    )

    result = service.dashboard(
        dashboard_range="custom",
        date_from=date(2026, 6, 1),
        date_to=date(2026, 6, 20),
    )

    trend = result.products[0].rating_trend
    guardian_trend = [item for item in trend if item.platform == "Guardian.com.vn"]
    assert len([item for item in guardian_trend if not item.predicted]) == 2
    predicted = [item for item in guardian_trend if item.predicted]
    assert len(predicted) == 1
    assert predicted[0].date == date(2026, 6, 21)
    assert predicted[0].date > max(
        item.date for item in guardian_trend if not item.predicted
    )
    service.close()


def test_live_missing_date_and_product_is_partial_but_keeps_actual_evidence(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path, "dashboard-partial")
    text = "Guardian giao một sản phẩm không đúng kỳ vọng."
    assert service._ingest_raw_rows(
        [
            _raw(
                "missing-context",
                occurred_at=None,
                text=text,
                rating=2,
                product=False,
            )
        ],
        source_name="dashboard_partial_fixture",
        source_file=None,
    )["inserted"] == 1
    _persist_by_external_id(
        service,
        {"missing-context": ("complaint", "negative", -0.7)},
    )

    result = service.dashboard()

    assert result.data_state == "partial"
    assert result.coverage.model_dump() == {
        "feedback_items": 1,
        "analyzed_items": 1,
        "relevant_items": 1,
        "time_eligible_items": 0,
        "product_attributed_items": 0,
    }
    assert len(result.products) == 1
    product = result.products[0]
    assert product.id == "unattributed"
    assert product.total_feedback == 1
    assert product.current.model_dump() == {
        "feedback": 0,
        "complaints": 0,
        "positive": 0,
        "neutral": 0,
    }
    assert product.baseline == product.current
    assert product.sentiment_delta is None
    assert len(result.evidence) == 1
    assert result.evidence[0].text == text
    assert result.evidence[0].product_id == "unattributed"
    assert result.evidence[0].timestamp is None
    assert any("occurrence dates" in message for message in result.messages)
    assert any("unattributed" in message for message in result.messages)
    assert result.benchmark.comparable is False
    assert result.benchmark.aggregates == []
    service.close()


def test_dashboard_exposes_only_public_evidence_urls(tmp_path: Path) -> None:
    service = _service(tmp_path, "dashboard-public-evidence-url")
    social_url = "https://www.facebook.com/groups/example/posts/123"
    canonical_url = "https://facebook.com/groups/example/posts/123"
    private_url = "https://seller.shopee.vn/private-review-path"
    rows = [
        _raw(
            "social-public",
            occurred_at="2026-07-10T09:00:00+07:00",
            text="Guardian public social complaint.",
            rating=None,
            product=False,
            source_group="social",
            source_platform="facebook",
            source_url=social_url,
        ),
        _raw(
            "marketplace-private",
            occurred_at="2026-07-10T10:00:00+07:00",
            text="Guardian marketplace complaint.",
            rating=2,
            source_url=private_url,
        ),
    ]
    assert service._ingest_raw_rows(
        rows, source_name="dashboard_url_fixture", source_file=None
    )["inserted"] == 2
    _persist_by_external_id(
        service,
        {
            "social-public": ("complaint", "negative", -0.7),
            "marketplace-private": ("complaint", "negative", -0.7),
        },
    )

    by_text = {item.text: item for item in service.dashboard().evidence}

    assert by_text["Guardian public social complaint."].source_url == canonical_url
    assert by_text["Guardian marketplace complaint."].source_url is None
    service.close()


def test_isolated_undated_feedback_is_a_note_when_period_windows_are_usable(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path, "dashboard-undated-note")
    rows = [
        _raw(
            "current-dated",
            occurred_at="2026-07-10T09:00:00+07:00",
            text="Guardian Serum A current feedback.",
            rating=4,
        ),
        _raw(
            "baseline-dated",
            occurred_at="2026-07-03T09:00:00+07:00",
            text="Guardian Serum A baseline feedback.",
            rating=3,
        ),
        _raw(
            "undated-extra",
            occurred_at=None,
            text="Guardian Serum A feedback without a trustworthy date.",
            rating=2,
        ),
    ]
    assert service._ingest_raw_rows(
        rows, source_name="dashboard_undated_note_fixture", source_file=None
    )["inserted"] == 3
    _persist_by_external_id(
        service,
        {
            "current-dated": ("praise", "positive", 0.6),
            "baseline-dated": ("question_request", "neutral", 0.0),
            "undated-extra": ("complaint", "negative", -0.7),
        },
    )

    result = service.dashboard()

    assert result.data_state == "ready"
    assert result.coverage.feedback_items == 3
    assert result.coverage.time_eligible_items == 2
    assert result.products[0].current.feedback == 1
    assert result.products[0].baseline.feedback == 1
    assert any("no trustworthy occurrence date" in message for message in result.messages)
    service.close()


def test_all_undated_product_feedback_remains_partial(tmp_path: Path) -> None:
    service = _service(tmp_path, "dashboard-all-undated")
    assert service._ingest_raw_rows(
        [
            _raw(
                "undated-product",
                occurred_at=None,
                text="Guardian Serum A feedback without a trustworthy date.",
                rating=2,
            )
        ],
        source_name="dashboard_all_undated_fixture",
        source_file=None,
    )["inserted"] == 1
    _persist_by_external_id(
        service,
        {"undated-product": ("complaint", "negative", -0.7)},
    )

    result = service.dashboard()

    assert result.data_state == "partial"
    assert result.coverage.product_attributed_items == 1
    assert result.coverage.time_eligible_items == 0
    assert result.products[0].current.feedback == 0
    assert result.products[0].baseline.feedback == 0
    assert any("no trustworthy occurrence dates" in message for message in result.messages)
    service.close()


def test_empty_dashboard_is_explicitly_empty(tmp_path: Path) -> None:
    service = _service(tmp_path, "dashboard-empty")

    result = service.dashboard()

    assert result.data_state == "empty"
    assert result.coverage.model_dump() == {
        "feedback_items": 0,
        "analyzed_items": 0,
        "relevant_items": 0,
        "time_eligible_items": 0,
        "product_attributed_items": 0,
    }
    assert result.products == []
    assert result.evidence == []
    assert result.benchmark.comparable is False
    assert result.benchmark.aggregates == []
    assert result.benchmark.reason
    service.close()


def test_matched_benchmark_returns_guardian_and_competitors_from_same_cohort(
    tmp_path: Path,
) -> None:
    service = _service(
        tmp_path, "dashboard-benchmark", competitor_min_sample=1
    )
    rows: list[RawFeedback] = []
    for brand in ("guardian", "hasaki", "watsons"):
        rows.append(
            RawFeedback(
                source_external_id=f"benchmark-{brand}",
                source_group="marketplace",
                source_platform="shopee",
                visibility="public",
                brand=brand,
                brand_candidates=[brand],
                occurred_at=datetime.fromisoformat("2026-07-10T09:00:00+07:00"),
                observed_at=datetime.fromisoformat("2026-07-11T10:00:00+07:00"),
                occurred_at_quality="exact",
                language="vi",
                text=f"{brand} serum feedback for the matched cohort.",
                rating=4,
                product_name=f"{brand.title()} Serum",
                product_category="Serum",
                metadata={
                    "product_id": f"{brand}-serum",
                    "experience_subject": "product",
                },
            )
        )
    assert service._ingest_raw_rows(
        rows, source_name="dashboard_benchmark_fixture", source_file=None
    )["inserted"] == 3
    for row in service.database.query(
        "SELECT feedback_id, source_external_id, text_redacted FROM feedback_items"
    ):
        brand = str(row["source_external_id"]).removeprefix("benchmark-")
        intent, sentiment, score = {
            "guardian": ("complaint", "negative", -0.7),
            "hasaki": ("praise", "positive", 0.7),
            "watsons": ("question_request", "neutral", 0.0),
        }[brand]
        service._persist_analysis(
            str(row["feedback_id"]),
            _classification(
                str(row["text_redacted"]),
                intent=intent,
                sentiment=sentiment,
                sentiment_score=score,
                brand=brand,
            ),
            model_version="dashboard-test",
            review_required=False,
        )

    benchmark = service.dashboard().benchmark

    assert benchmark.comparable is True
    assert benchmark.reason is None
    assert [aggregate.brand for aggregate in benchmark.aggregates] == [
        "guardian",
        "hasaki",
        "watsons",
    ]
    assert all(aggregate.feedback == 1 for aggregate in benchmark.aggregates)
    assert benchmark.aggregates[0].complaints == 1
    assert benchmark.aggregates[1].positive == 1
    assert benchmark.aggregates[2].neutral == 1
    service.close()


def test_dashboard_benchmark_falls_back_to_all_source_brand_scores(
    tmp_path: Path,
) -> None:
    service = _service(
        tmp_path, "dashboard-benchmark-all-source", competitor_min_sample=2
    )
    rows: list[RawFeedback] = []
    sentiments = {
        "guardian": [("praise", "positive", 0.8), ("complaint", "negative", -0.6)],
        "hasaki": [("praise", "positive", 0.7), ("praise", "positive", 0.6)],
        "watsons": [("question_request", "neutral", 0.0), ("complaint", "negative", -0.5)],
    }
    for brand, classifications in sentiments.items():
        for index, _classification_values in enumerate(classifications, start=1):
            rows.append(
                _raw(
                    f"fallback-{brand}-{index}",
                    brand=brand,
                    source_group="owned",
                    source_platform=f"{brand}_ecommerce",
                    visibility="owned",
                    occurred_at="2026-05-10T09:00:00+07:00",
                    text=f"{brand} official product review {index}.",
                    rating=5 if index == 1 else 2,
                    product_id=f"{brand}-product",
                    product_name=f"{brand.title()} Product",
                )
            )
    assert service._ingest_raw_rows(
        rows, source_name="dashboard_benchmark_fallback_fixture", source_file=None
    )["inserted"] == 6
    for row in service.database.query(
        "SELECT feedback_id, source_external_id, text_redacted FROM feedback_items"
    ):
        external_id = str(row["source_external_id"])
        brand = external_id.split("-")[1]
        index = int(external_id.rsplit("-", 1)[1]) - 1
        intent, sentiment, score = sentiments[brand][index]
        service._persist_analysis(
            str(row["feedback_id"]),
            _classification(
                str(row["text_redacted"]),
                intent=intent,
                sentiment=sentiment,
                sentiment_score=score,
                brand=brand,
            ),
            model_version="dashboard-test",
            review_required=False,
        )

    benchmark = service.dashboard().benchmark

    assert benchmark.comparable is True
    assert benchmark.reason
    assert [aggregate.brand for aggregate in benchmark.aggregates] == [
        "guardian",
        "hasaki",
        "watsons",
    ]
    assert all(aggregate.feedback == 2 for aggregate in benchmark.aggregates)
    assert benchmark.aggregates[0].positive == 1
    assert benchmark.aggregates[1].positive == 2
    assert benchmark.aggregates[2].neutral == 1
    service.close()


def test_old_dated_guardian_feedback_is_partial_without_current_or_baseline_data(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path, "dashboard-old-data")
    assert service._ingest_raw_rows(
        [
            _raw(
                "old-feedback",
                occurred_at="2026-05-01T09:00:00+07:00",
                text="Guardian Serum A historical feedback.",
                rating=4,
            )
        ],
        source_name="dashboard_old_fixture",
        source_file=None,
    )["inserted"] == 1
    _persist_by_external_id(
        service,
        {"old-feedback": ("praise", "positive", 0.5)},
    )

    result = service.dashboard()

    assert result.coverage.time_eligible_items == 1
    assert result.data_state == "partial"
    assert result.products[0].current.feedback == 0
    assert result.products[0].baseline.feedback == 0
    assert any("current analysis window" in message for message in result.messages)
    assert any("baseline analysis window" in message for message in result.messages)
    service.close()


def test_evidence_limit_samples_across_products(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(application_module, "DASHBOARD_EVIDENCE_LIMIT", 3)
    service = _service(tmp_path, "dashboard-evidence-sampling")
    rows = [
        _raw(
            f"product-a-{index}",
            occurred_at=f"2026-07-10T0{index + 5}:00:00+07:00",
            text=f"Guardian Product A complaint {index}.",
            rating=2,
            product_id="P-A",
            product_name="Product A",
        )
        for index in range(3)
    ]
    rows.append(
        _raw(
            "product-b-0",
            occurred_at="2026-07-09T05:00:00+07:00",
            text="Guardian Product B complaint.",
            rating=2,
            product_id="P-B",
            product_name="Product B",
        )
    )
    assert service._ingest_raw_rows(
        rows, source_name="dashboard_evidence_fixture", source_file=None
    )["inserted"] == 4
    _persist_by_external_id(
        service,
        {
            **{
                f"product-a-{index}": ("complaint", "negative", -0.7)
                for index in range(3)
            },
            "product-b-0": ("complaint", "negative", -0.7),
        },
    )

    result = service.dashboard()

    assert len(result.evidence) == 3
    assert [item.product_id for item in result.evidence[:2]] == ["P-A", "P-B"]
    assert {item.product_id for item in result.evidence} == {"P-A", "P-B"}
    service.close()


def test_dashboard_presets_use_distinct_date_windows(tmp_path: Path) -> None:
    service = _service(tmp_path, "dashboard-date-presets")
    rows = [
        _raw("recent", occurred_at="2026-07-10T09:00:00+07:00", text="Guardian recent review.", rating=5),
        _raw("older", occurred_at="2026-03-10T09:00:00+07:00", text="Guardian older review.", rating=1),
    ]
    assert service._ingest_raw_rows(rows, source_name="dashboard_date_fixture", source_file=None)["inserted"] == 2
    _persist_by_external_id(service, {
        "recent": ("praise", "positive", 0.8),
        "older": ("complaint", "negative", -0.8),
    })

    last_30_days = service.dashboard(preset="30d")
    last_year = service.dashboard(preset="1y")

    assert last_30_days.products[0].current.feedback == 1
    assert last_year.products[0].current.feedback == 2
    assert (last_30_days.windows.current_end - last_30_days.windows.current_start).days == 30
    assert (last_year.windows.current_end - last_year.windows.current_start).days == 365
    service.close()


@pytest.mark.asyncio
async def test_problem_detail_uses_the_same_independent_complaint_cohort(tmp_path: Path) -> None:
    service = _service(tmp_path, "problem-detail")
    rows = [
        _raw("complaint-a", occurred_at="2026-07-10T09:00:00+07:00", text="Guardian Serum A performed poorly.", rating=1),
        _raw("complaint-b", occurred_at="2026-07-09T09:00:00+07:00", text="Guardian Serum B performed poorly.", rating=2, product_id="P-2", product_name="Serum B", source_platform="tiktok_shop"),
        _raw("praise-a", occurred_at="2026-07-08T09:00:00+07:00", text="Guardian Serum A works well.", rating=5),
    ]
    assert service._ingest_raw_rows(rows, source_name="problem_detail_fixture", source_file=None)["inserted"] == 3
    _persist_by_external_id(service, {
        "complaint-a": ("complaint", "negative", -0.8),
        "complaint-b": ("complaint", "negative", -0.7),
        "praise-a": ("praise", "positive", 0.7),
    })

    detail = await service.problem_detail(problem="product_performance", preset="all")

    assert detail.count == 2
    assert detail.total_complaints == 2
    assert detail.share == 1
    assert detail.summary_source == "deterministic"
    assert {item.label: item.count for item in detail.products} == {"Serum A": 1, "Serum B": 1}
    assert {item.label: item.count for item in detail.sources} == {"shopee": 1, "tiktok_shop": 1}
    assert [item.id for item in detail.reviews]
    service.close()


@pytest.mark.parametrize("path", ["/api", "/api/v1/does-not-exist"])
def test_unknown_api_routes_return_json_404(path: str) -> None:
    client = TestClient(app)
    try:
        response = client.get(path)
        assert response.status_code == 404
        assert response.headers["content-type"].startswith("application/json")
        assert response.json() == {"detail": "API route not found"}
    finally:
        client.close()
