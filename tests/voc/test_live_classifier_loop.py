from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from guardian_voc import application
from guardian_voc.ai.provider import MalformedProviderResponse
from guardian_voc.application import GuardianService
from guardian_voc.config import Settings
from guardian_voc.schemas.analysis import ClassificationResult
from guardian_voc.schemas.feedback import RawFeedback


class LoopBoundProvider:
    loop_ids: list[int] = []

    def __init__(self, **kwargs: Any) -> None:
        self.model_version = str(kwargs["model"])

    async def classify(self, request: Any) -> ClassificationResult:
        self.loop_ids.append(id(asyncio.get_running_loop()))
        return ClassificationResult.model_validate(
            {
                "is_relevant": True,
                "primary_brand": "guardian",
                "mentioned_brands": ["guardian"],
                "brand_attribution_confidence": 0.99,
                "brand_evidence_span": None,
                "experience_subject": "retailer",
                "primary_topic": "price_promotion",
                "subtopic": "voucher_not_applied",
                "intent": "complaint",
                "sentiment": "negative",
                "sentiment_score": -0.8,
                "urgency": "normal",
                "customer_stated_reason": None,
                "journey_stage": "checkout",
                "evidence_span": request.text_redacted,
                "confidence": 0.96,
            }
        )

    async def aclose(self) -> None:
        self.loop_ids.append(id(asyncio.get_running_loop()))


class MalformedProvider(LoopBoundProvider):
    async def classify(self, request: Any) -> ClassificationResult:
        raise MalformedProviderResponse("invalid structured output")


def test_live_classifier_reuses_one_event_loop_for_whole_batch(
    tmp_path: Path, monkeypatch
) -> None:
    settings = Settings(
        voc_db_path=tmp_path / "classifier.duckdb",
        voc_data_dir=tmp_path,
        voc_inbox_dir=tmp_path / "inbox",
        voc_demo_mode=False,
        ai_provider="openai_compatible",
        ai_api_key="test-key",
        ai_model="gpt-5.6-luna",
    )
    service = GuardianService(settings)
    now = datetime(2026, 7, 11, 12, tzinfo=timezone.utc)
    rows = [
        RawFeedback(
            source_external_id=f"review-{index}",
            source_group="marketplace",
            source_platform="shopee",
            visibility="public",
            brand="guardian",
            brand_candidates=["guardian"],
            occurred_at=now,
            observed_at=now,
            occurred_at_quality="exact",
            language="vi",
            text=f"Voucher Guardian không áp dụng cho đơn hàng {index}.",
        )
        for index in (1, 2)
    ]
    try:
        service.initialize(seed_demo=False)
        service._ingest_raw_rows(
            rows,
            source_name="guardian_shopee_test",
            source_file=None,
        )
        LoopBoundProvider.loop_ids.clear()
        monkeypatch.setattr(
            application, "OpenAICompatibleProvider", LoopBoundProvider
        )
        result = service._classify_pending()
        assert result == {
            "analyzed": 2,
            "failed": 0,
            "low_confidence": 0,
            "skipped_after_retry": 0,
        }
        assert len(LoopBoundProvider.loop_ids) == 3
        assert len(set(LoopBoundProvider.loop_ids)) == 1
    finally:
        service.close()


def test_malformed_structured_output_is_quarantined_after_provider_repair(
    tmp_path: Path, monkeypatch
) -> None:
    settings = Settings(
        voc_db_path=tmp_path / "classifier.duckdb",
        voc_data_dir=tmp_path,
        voc_inbox_dir=tmp_path / "inbox",
        voc_demo_mode=False,
        ai_provider="openai_compatible",
        ai_api_key="test-key",
        ai_model="gpt-5.4-mini",
    )
    service = GuardianService(settings)
    now = datetime(2026, 7, 11, 12, tzinfo=timezone.utc)
    row = RawFeedback(
        source_external_id="review-malformed",
        source_group="marketplace",
        source_platform="shopee",
        visibility="public",
        brand="guardian",
        brand_candidates=["guardian"],
        occurred_at=now,
        observed_at=now,
        occurred_at_quality="exact",
        language="vi",
        text="Voucher Guardian không áp dụng cho đơn hàng.",
    )
    try:
        service.initialize(seed_demo=False)
        service._ingest_raw_rows(
            [row], source_name="guardian_shopee_test", source_file=None
        )
        monkeypatch.setattr(application, "OpenAICompatibleProvider", MalformedProvider)

        first = service._classify_pending()
        second = service._classify_pending()

        assert first["failed"] == 1
        assert second == {
            "analyzed": 0,
            "failed": 0,
            "low_confidence": 0,
            "skipped_after_retry": 1,
        }
        stored = service.database.query_one(
            "SELECT analysis_status FROM feedback_items LIMIT 1"
        )
        assert stored is not None
        assert stored["analysis_status"] == "skipped"
    finally:
        service.close()
