from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from guardian_voc.config import Settings
from guardian_voc.connectors.file_import import FileImportConnector
from guardian_voc.db import Database, Repository, WriteCounts
from guardian_voc.pipeline.normalize import normalize_raw_feedback
from guardian_voc.schemas.feedback import RawFeedback


NOW = datetime(2026, 7, 11, 12, tzinfo=timezone.utc)


def settings(tmp_path) -> Settings:
    return Settings(voc_db_path=tmp_path / "guardian.duckdb", voc_hash_salt="tests")


def raw(**changes) -> RawFeedback:
    values = {
        "source_external_id": "review-1",
        "source_group": "marketplace",
        "source_platform": "shopee",
        "visibility": "public",
        "brand": "guardian",
        "brand_candidates": ["guardian"],
        "occurred_at": NOW,
        "observed_at": NOW,
        "occurred_at_quality": "exact",
        "text": "Voucher terms were unclear at checkout for this public review.",
        "metadata": {},
    }
    values.update(changes)
    return RawFeedback.model_validate(values)


def test_migrations_are_idempotent_and_create_complete_core_schema(tmp_path) -> None:
    db = Database(settings(tmp_path))
    assert db.initialize() == [1, 2]
    assert db.initialize() == []
    assert db.schema_version() == 2
    tables = {
        row["table_name"]
        for row in db.query(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
        )
    }
    assert {
        "ingestion_runs",
        "source_status",
        "feedback_items",
        "feedback_analyses",
        "daily_metrics",
        "insight_cards",
        "import_quarantine",
        "source_registry",
        "discovery_results",
        "fetch_attempts",
        "source_checkpoints",
        "classification_failures",
        "page_extractions",
    } <= tables
    db.close()


def test_cross_run_source_identity_is_idempotent(tmp_path) -> None:
    cfg = settings(tmp_path)
    repo = Repository(Database(cfg))
    repo.initialize()
    first_run = repo.create_ingestion_run(
        connector="file", source_name="guardian_shopee", run_id="first"
    )
    second_run = repo.create_ingestion_run(
        connector="file", source_name="guardian_shopee", run_id="second"
    )
    first = normalize_raw_feedback(
        raw(),
        ingestion_run_id=first_run.id,
        source_name="guardian_shopee",
        settings=cfg,
        ingested_at=NOW,
    )
    second = normalize_raw_feedback(
        raw(text="The export text was corrected after the first run."),
        ingestion_run_id=second_run.id,
        source_name="guardian_shopee",
        settings=cfg,
        ingested_at=NOW + timedelta(hours=1),
    )
    assert first.feedback_id == second.feedback_id
    assert repo.insert_feedback(first) is True
    assert repo.insert_feedback(second) is False
    assert repo.feedback_count() == 1


def test_extracted_units_share_page_but_insert_separately_and_replay_skips(
    tmp_path,
) -> None:
    cfg = settings(tmp_path)
    repo = Repository(Database(cfg))
    repo.initialize()
    first_run = repo.create_ingestion_run(
        connector="page_feedback_extractor",
        source_name="guardian_public_social_extracted",
        run_id="first-extraction",
    )
    second_run = repo.create_ingestion_run(
        connector="page_feedback_extractor",
        source_name="guardian_public_social_extracted",
        run_id="second-extraction",
    )
    shared_url = "https://facebook.com/guardianvn/posts/42"

    def extracted(external_id: str, text: str) -> RawFeedback:
        return raw(
            source_external_id=external_id,
            source_group="social",
            source_platform="facebook",
            visibility="public",
            brand=None,
            brand_candidates=["guardian"],
            source_url=shared_url,
            text=text,
            metadata={"identity_type": "extracted_unit"},
        )

    first = normalize_raw_feedback(
        extracted("post-42-comment-1", "Guardian giao hàng rất nhanh và đóng gói kỹ."),
        ingestion_run_id=first_run.id,
        source_name="guardian_public_social_extracted",
        settings=cfg,
        ingested_at=NOW,
    )
    second = normalize_raw_feedback(
        extracted(
            "post-42-comment-2",
            "Mã giảm giá không áp dụng được khi thanh toán.",
        ),
        ingestion_run_id=first_run.id,
        source_name="guardian_public_social_extracted",
        settings=cfg,
        ingested_at=NOW,
    )
    replay = normalize_raw_feedback(
        extracted("post-42-comment-1", "Nội dung được đọc lại ở lần chạy sau."),
        ingestion_run_id=second_run.id,
        source_name="guardian_public_social_extracted",
        settings=cfg,
        ingested_at=NOW + timedelta(hours=1),
    )

    assert first.feedback_id != second.feedback_id
    assert replay.feedback_id == first.feedback_id
    assert repo.insert_feedback_many([first, second]) == WriteCounts(
        seen=2, inserted=2, skipped=0, failed=0
    )
    assert repo.insert_feedback(replay) is False
    assert repo.feedback_count() == 2


def test_extracted_unit_with_new_identity_and_exact_page_content_is_skipped(
    tmp_path,
) -> None:
    cfg = settings(tmp_path)
    repo = Repository(Database(cfg))
    repo.initialize()
    run = repo.create_ingestion_run(
        connector="page_feedback_extractor",
        source_name="guardian_public_social_extracted",
        run_id="exact-replay",
    )
    shared = {
        "source_group": "social",
        "source_platform": "facebook",
        "visibility": "public",
        "brand": None,
        "brand_candidates": ["guardian"],
        "source_url": "https://facebook.com/guardianvn/posts/42",
        "text": "Guardian giao hàng rất nhanh và đóng gói kỹ.",
        "metadata": {"identity_type": "extracted_unit"},
    }
    first = normalize_raw_feedback(
        raw(source_external_id="comment-old", **shared),
        ingestion_run_id=run.id,
        source_name="guardian_public_social_extracted",
        settings=cfg,
        ingested_at=NOW,
    )
    replay = normalize_raw_feedback(
        raw(source_external_id="comment-new", **shared),
        ingestion_run_id=run.id,
        source_name="guardian_public_social_extracted",
        settings=cfg,
        ingested_at=NOW + timedelta(minutes=30),
    )

    assert first.feedback_id != replay.feedback_id
    assert repo.insert_feedback(first) is True
    assert repo.insert_feedback(replay) is False
    assert repo.feedback_count() == 1


def test_historical_exact_social_replays_are_marked_as_duplicates(tmp_path) -> None:
    cfg = settings(tmp_path)
    repo = Repository(Database(cfg))
    repo.initialize()
    run = repo.create_ingestion_run(
        connector="page_feedback_extractor",
        source_name="guardian_public_social_extracted",
        run_id="historical-replay",
    )
    first = normalize_raw_feedback(
        raw(
            source_external_id="comment-old",
            source_group="social",
            source_platform="facebook",
            visibility="public",
            brand=None,
            brand_candidates=["guardian"],
            source_url="https://facebook.com/guardianvn/posts/42",
            text="Guardian giao hàng rất nhanh và đóng gói kỹ.",
            metadata={"identity_type": "extracted_unit"},
        ),
        ingestion_run_id=run.id,
        source_name="guardian_public_social_extracted",
        settings=cfg,
        ingested_at=NOW,
    )
    assert repo.insert_feedback(first) is True
    repo.db.execute(
        """
        INSERT INTO feedback_items
        SELECT * REPLACE (
            'feedback_historical_replay' AS feedback_id,
            'comment-new' AS source_external_id,
            ? AS ingested_at
        )
        FROM feedback_items WHERE feedback_id = ?
        """,
        [NOW + timedelta(minutes=30), first.feedback_id],
    )

    assert repo.mark_exact_content_duplicates() == 1
    replay = repo.get_feedback("feedback_historical_replay")
    assert replay is not None
    assert replay["duplicate_of"] == first.feedback_id
    assert replay["analysis_status"] == "skipped"


def test_public_repost_rows_remain_evidence_but_share_group(tmp_path) -> None:
    cfg = settings(tmp_path)
    repo = Repository(Database(cfg))
    repo.initialize()
    run = repo.create_ingestion_run(connector="crawler", source_name="social", run_id="social")
    text = "The promotion eligibility only became visible at checkout for this order."
    items = [
        normalize_raw_feedback(
            raw(
                source_external_id=None,
                source_group="social",
                source_platform=platform,
                brand=None,
                source_url=url,
                text=text,
                metadata={"crawler_record_id": platform},
            ),
            ingestion_run_id=run.id,
            source_name="social",
            settings=cfg,
            ingested_at=NOW,
        )
        for platform, url in (
            ("facebook", "https://facebook.com/posts/one"),
            ("reddit", "https://reddit.com/r/x/comments/two"),
        )
    ]
    counts = repo.insert_feedback_many(items)
    assert counts == WriteCounts(seen=2, inserted=2, skipped=0, failed=0)
    stored = repo.list_feedback(limit=10)
    assert len(stored) == 2
    assert len({row["repost_group_id"] for row in stored}) == 1


def test_failed_source_attempt_preserves_last_good_dataset_and_success_time(tmp_path) -> None:
    cfg = settings(tmp_path)
    repo = Repository(Database(cfg))
    repo.initialize()
    good = repo.create_ingestion_run(
        connector="file", source_name="shopee", run_id="good", started_at=NOW
    )
    item = normalize_raw_feedback(
        raw(), ingestion_run_id=good.id, source_name="shopee", settings=cfg, ingested_at=NOW
    )
    repo.insert_feedback(item)
    repo.finish_ingestion_run(
        good.id,
        status="completed",
        counts=WriteCounts(seen=1, inserted=1),
        source_group="marketplace",
    )
    successful_at = repo.get_source_status("shopee").last_success_at

    failed = repo.create_ingestion_run(
        connector="file",
        source_name="shopee",
        run_id="failed",
        started_at=NOW + timedelta(hours=1),
    )
    repo.finish_ingestion_run(
        failed.id,
        status="failed",
        counts=WriteCounts(seen=1, failed=1),
        error_summary="upstream export failed",
        source_group="marketplace",
    )
    health = repo.get_source_status("shopee")
    assert repo.feedback_count() == 1
    assert health.status.value == "failed"
    assert health.last_success_at == successful_at
    assert health.failure_rate == pytest.approx(0.5)


@pytest.mark.asyncio
async def test_repository_ingest_connector_persists_valid_rows_and_quarantine(tmp_path) -> None:
    cfg = settings(tmp_path)
    source = tmp_path / "reviews.csv"
    source.write_text(
        "review_id,review_text,rating\n"
        "good,Guardian staff were helpful,5\n"
        "bad,Call me at 0909123456,invalid\n",
        encoding="utf-8",
    )
    repo = Repository(Database(cfg))
    repo.initialize()
    connector = FileImportConnector(source, "shopee", settings=cfg)
    result = await repo.ingest_connector(
        connector,
        connector_name="file_import",
        source_name="shopee",
        source_group="marketplace",
        source_file=source,
    )
    assert result.status.value == "partial"
    assert result.records_seen == 2
    assert result.records_inserted == 1
    assert result.records_failed == 1
    quarantine = repo.list_quarantine(result.id)
    assert len(quarantine) == 1
    assert "0909123456" not in str(quarantine[0])
    assert repo.db.query_one("SELECT count(*) AS n FROM imported_files")["n"] == 1
