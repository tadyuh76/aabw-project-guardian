from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from guardian_voc.config import Settings
from guardian_voc.pipeline.dedupe import canonicalize_url
from guardian_voc.pipeline.language import detect_language
from guardian_voc.pipeline.normalize import normalize_raw_feedback, parse_timestamp
from guardian_voc.pipeline.pii import preview_text, redact_text
from guardian_voc.schemas.feedback import RawFeedback


NOW = datetime(2026, 7, 11, 12, tzinfo=timezone.utc)


def raw(**changes) -> RawFeedback:
    values = {
        "source_external_id": None,
        "source_group": "social",
        "source_platform": "facebook",
        "visibility": "public",
        "brand": None,
        "brand_candidates": ["guardian"],
        "occurred_at": None,
        "observed_at": NOW,
        "occurred_at_quality": "missing",
        "title": "A title",
        "text": "Guardian voucher không áp dụng khi tôi đến bước thanh toán.",
        "source_url": "https://www.facebook.com/posts/42?utm_source=ad&b=2&a=1#comments",
        "metadata": {"crawler_record_id": "title-dependent-id"},
    }
    values.update(changes)
    return RawFeedback.model_validate(values)


def settings() -> Settings:
    return Settings(voc_db_path=":memory:", voc_hash_salt="test-salt")


def test_csv_environment_settings_are_parsed(monkeypatch) -> None:
    monkeypatch.setenv("CRAWLER_KEYWORDS", "guardian,hasaki,watsons")
    monkeypatch.setenv(
        "VOC_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
    )
    monkeypatch.setenv(
        "VOC_VERIFIED_FEEDBACK_FILES",
        "/exports/analysis_ready.jsonl,/exports/next.jsonl",
    )
    monkeypatch.setenv(
        "VOC_LIVE_COLLECTION_SOURCE_IDS",
        "guardian_public_social,hasaki_public_social",
    )
    configured = Settings(_env_file=None)
    assert configured.crawler_keywords == ("guardian", "hasaki", "watsons")
    assert configured.voc_cors_origins == (
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    )
    assert configured.voc_verified_feedback_files == (
        Path("/exports/analysis_ready.jsonl"),
        Path("/exports/next.jsonl"),
    )
    assert configured.voc_live_collection_source_ids == (
        "guardian_public_social",
        "hasaki_public_social",
    )
    assert configured.voc_default_locale == "en"
    assert configured.voc_scheduler_crawl_enabled is False
    assert configured.voc_scheduler_full_flow_enabled is False
    assert configured.voc_scheduler_interval_seconds == 1_800
    assert configured.crawler_lookback_days == 1


def test_url_canonicalization_removes_only_tracking_and_fragment() -> None:
    assert canonicalize_url(
        "HTTPS://WWW.Facebook.com:443/posts/42/?utm_source=ad&b=2&a=1#comments"
    ) == "https://facebook.com/posts/42?a=1&b=2"
    assert canonicalize_url("javascript:alert(1)") is None
    assert canonicalize_url("https://user:pass@example.com/path") is None


def test_same_crawler_url_changed_title_keeps_feedback_identity() -> None:
    first = normalize_raw_feedback(
        raw(title="Old result title"),
        ingestion_run_id="run-1",
        source_name="social_crawler",
        settings=settings(),
        ingested_at=NOW,
    )
    second = normalize_raw_feedback(
        raw(title="A changed result title", source_url="https://facebook.com/posts/42?a=1&b=2"),
        ingestion_run_id="run-2",
        source_name="social_crawler",
        settings=settings(),
        ingested_at=NOW,
    )
    assert first.feedback_id == second.feedback_id
    assert first.crawler_record_id == "title-dependent-id"
    assert first.canonical_url == "https://facebook.com/posts/42?a=1&b=2"


def test_extracted_units_on_one_public_page_use_stable_external_identities() -> None:
    shared_url = "https://facebook.com/guardianvn/posts/42#comments"
    first = normalize_raw_feedback(
        raw(
            source_external_id="post-42-comment-1",
            source_url=shared_url,
            text="Guardian giao hàng nhanh và đóng gói sản phẩm rất kỹ.",
            metadata={"identity_type": "extracted_unit"},
        ),
        ingestion_run_id="run-1",
        source_name="guardian_public_social_extracted",
        settings=settings(),
        ingested_at=NOW,
    )
    second = normalize_raw_feedback(
        raw(
            source_external_id="post-42-comment-2",
            source_url=shared_url,
            text="Mã giảm giá Guardian không áp dụng được khi thanh toán.",
            metadata={"identity_type": "extracted_unit"},
        ),
        ingestion_run_id="run-1",
        source_name="guardian_public_social_extracted",
        settings=settings(),
        ingested_at=NOW,
    )
    replay = normalize_raw_feedback(
        raw(
            source_external_id="post-42-comment-1",
            source_url="https://www.facebook.com/guardianvn/posts/42",
            title="Title changed on a later fetch",
            text="Guardian giao hàng nhanh và đóng gói sản phẩm kỹ hơn mô tả cũ.",
            metadata={"identity_type": "extracted_unit"},
        ),
        ingestion_run_id="run-2",
        source_name="guardian_public_social_extracted",
        settings=settings(),
        ingested_at=NOW,
    )

    assert first.canonical_url == second.canonical_url == replay.canonical_url
    assert first.feedback_id != second.feedback_id
    assert replay.feedback_id == first.feedback_id
    assert first.sanitized_metadata["identity_type"] == "extracted_unit"
    assert first.sanitized_metadata["identity_kind"] == "source_external_id"


def test_ordinary_public_social_rows_keep_canonical_url_identity() -> None:
    shared_url = "https://facebook.com/guardianvn/posts/ordinary"
    first = normalize_raw_feedback(
        raw(
            source_external_id="incidental-source-id-1",
            source_url=shared_url,
            metadata={"crawler_record_id": "crawl-1"},
        ),
        ingestion_run_id="run-1",
        source_name="social_crawler",
        settings=settings(),
        ingested_at=NOW,
    )
    second = normalize_raw_feedback(
        raw(
            source_external_id="incidental-source-id-2",
            source_url=shared_url,
            metadata={"crawler_record_id": "crawl-2"},
        ),
        ingestion_run_id="run-2",
        source_name="social_crawler",
        settings=settings(),
        ingested_at=NOW,
    )

    assert first.feedback_id == second.feedback_id
    assert first.sanitized_metadata["identity_kind"] == "canonical_url"


def test_public_reposts_group_but_owned_interactions_do_not() -> None:
    copied_text = "Guardian promotion terms only appeared after checkout and caused confusion."
    one = normalize_raw_feedback(
        raw(text=copied_text, source_url="https://facebook.com/post/one"),
        ingestion_run_id="one",
        source_name="crawler",
        settings=settings(),
        ingested_at=NOW,
    )
    two = normalize_raw_feedback(
        raw(
            text=copied_text,
            source_platform="reddit",
            source_url="https://reddit.com/r/test/comments/two",
        ),
        ingestion_run_id="two",
        source_name="crawler",
        settings=settings(),
        ingested_at=NOW,
    )
    owned = normalize_raw_feedback(
        raw(
            source_external_id="ticket-2",
            source_group="customer_service",
            source_platform="ticket",
            visibility="owned",
            brand="guardian",
            text=copied_text,
            source_url=None,
            metadata={},
        ),
        ingestion_run_id="three",
        source_name="tickets",
        settings=settings(),
        ingested_at=NOW,
    )
    assert one.feedback_id != two.feedback_id
    assert one.repost_group_id == two.repost_group_id
    assert owned.content_fingerprint is None
    assert owned.repost_group_id is None


def test_redaction_runs_before_preview_truncation_and_hashes_identifiers() -> None:
    text = (
        "Email jane@example.com phone +84 909 123 456, order ID ORD-998877, "
        "loyalty card 1234 5678 9012 and address: 12 Nguyen Hue Street."
    )
    redacted = redact_text(text)
    assert "jane@example.com" not in redacted
    assert "909 123 456" not in redacted
    assert "ORD-998877" not in redacted
    assert "1234 5678 9012" not in redacted
    assert "12 Nguyen Hue" not in redacted
    for placeholder in ("[EMAIL]", "[PHONE]", "[ORDER_ID]", "[LOYALTY_ID]", "[ADDRESS]"):
        assert placeholder in redacted
    assert "jane@example.com" not in preview_text("x" * 300 + text, limit=320)

    item = normalize_raw_feedback(
        raw(text=text, author_id="customer-1", conversation_id="chat-1"),
        ingestion_run_id="run",
        source_name="crawler",
        settings=settings(),
        ingested_at=NOW,
    )
    assert item.author_hash.startswith("sha256:")
    assert item.conversation_hash.startswith("sha256:")
    assert "customer-1" not in item.model_dump_json()


@pytest.mark.parametrize(
    ("text", "language"),
    [
        ("Voucher không áp dụng và giá sản phẩm quá cao", "vi"),
        ("The delivery was late and the product was damaged", "en"),
        ("ok", "unknown"),
    ],
)
def test_language_detection_is_deterministic(text: str, language: str) -> None:
    assert detect_language(text).language == language


def test_timestamp_timezone_relative_and_missing_rules() -> None:
    exact = parse_timestamp("2026-07-11T08:30:00+07:00")
    assert exact.value == datetime(2026, 7, 11, 1, 30, tzinfo=timezone.utc)
    assert exact.quality.value == "parsed"

    local = parse_timestamp("11/07/2026 08:30", timezone_hint="Asia/Ho_Chi_Minh")
    assert local.value == datetime(2026, 7, 11, 1, 30, tzinfo=timezone.utc)
    assert local.original_timezone == "Asia/Ho_Chi_Minh"

    vietnamese_absolute = parse_timestamp(
        "11 thg 7, 2026 lúc 08:30",
        timezone_hint="Asia/Ho_Chi_Minh",
    )
    assert vietnamese_absolute.value == datetime(
        2026, 7, 11, 1, 30, tzinfo=timezone.utc
    )
    assert vietnamese_absolute.quality.value == "parsed"
    assert vietnamese_absolute.original_timezone == "Asia/Ho_Chi_Minh"

    relative = parse_timestamp("2 days ago", observed_at=NOW)
    assert relative.value == NOW.replace(day=9)
    assert relative.quality.value == "inferred"

    malformed = parse_timestamp("not a date", observed_at=NOW)
    assert malformed.value is None
    assert malformed.quality.value == "missing"
