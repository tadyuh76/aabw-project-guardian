from __future__ import annotations

import json
from datetime import date, datetime, timezone

import pytest

from guardian_voc.config import Settings
from guardian_voc.connectors.file_import import (
    GUARDIAN_VOC_PERIOD_END,
    GUARDIAN_VOC_PERIOD_START,
    FileImportConnector,
    preview_import,
)
from guardian_voc.connectors.mapping_profiles import get_profile, list_profiles
from guardian_voc.connectors.public_social import SocialCrawlerConnector
from guardian_voc.pipeline.normalize import normalize_raw_feedback
from guardian_voc.schemas.feedback import IngestionRun


NOW = datetime(2026, 7, 11, 12, tzinfo=timezone.utc)


def run() -> IngestionRun:
    return IngestionRun(
        id="run-test",
        connector="test",
        source_name="test",
        status="running",
        started_at=NOW,
    )


def config(tmp_path) -> Settings:
    return Settings(
        voc_db_path=tmp_path / "test.duckdb",
        voc_preview_text_limit=120,
        voc_max_import_rows=100,
    )


def test_required_profiles_are_available() -> None:
    required = {
        "shopee",
        "lazada",
        "tiktok_shop",
        "grabmart",
        "guardian_ecommerce",
        "hasaki_owned",
        "watsons_owned",
        "customer_service_ticket",
        "live_chat",
        "call_transcript",
        "hasaki",
        "watsons",
        "generic",
    }
    assert required <= set(list_profiles())
    assert get_profile("tiktok").name == "tiktok_shop"
    assert get_profile("guardian official page").name == "guardian_ecommerce"


@pytest.mark.asyncio
async def test_csv_partial_import_masks_preview_and_quarantines_bad_rows(tmp_path) -> None:
    source = tmp_path / "reviews.csv"
    source.write_text(
        "review_id,review_text,rating,review_date,author_id\n"
        'r1,"Good service, email me at jane@example.com",5,11/07/2026,cust-1\n'
        'r2,"Call 0909123456 about this order",not-a-rating,11/07/2026,cust-2\n',
        encoding="utf-8",
    )
    preview = preview_import(source, "shopee", settings=config(tmp_path))
    assert (preview.total_rows, preview.valid_rows, preview.invalid_rows) == (2, 1, 1)
    serialized = preview.model_dump_json()
    assert "jane@example.com" not in serialized
    assert "0909123456" not in serialized
    assert "[EMAIL]" in serialized

    connector = FileImportConnector(source, "shopee", settings=config(tmp_path))
    collected = [item async for item in connector.collect(run())]
    assert len(collected) == 1
    assert collected[0].source_external_id == "r1"
    assert len(connector.quarantined) == 1
    assert connector.quarantined[0].field == "rating"


@pytest.mark.asyncio
async def test_live_chat_rows_become_one_complete_conversation(tmp_path) -> None:
    source = tmp_path / "chat.jsonl"
    rows = [
        {
            "chat_id": "chat-1",
            "sent_at": "2026-07-11T09:01:00+07:00",
            "sender": "customer",
            "message": "Voucher không dùng được",
        },
        {
            "chat_id": "chat-1",
            "sent_at": "2026-07-11T09:02:00+07:00",
            "sender": "agent",
            "message": "Tôi sẽ kiểm tra điều kiện",
        },
    ]
    source.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )
    connector = FileImportConnector(source, "live_chat", settings=config(tmp_path))
    items = [item async for item in connector.collect(run())]
    assert len(items) == 1
    assert items[0].conversation_id == "chat-1"
    assert items[0].message_count == 2
    assert "customer: Voucher" in items[0].text
    assert "agent: Tôi" in items[0].text


@pytest.mark.asyncio
async def test_malformed_jsonl_line_does_not_drop_valid_neighbors(tmp_path) -> None:
    source = tmp_path / "reviews.jsonl"
    source.write_text(
        '{"review_id":"one","review_text":"Great staff","rating":5}\n'
        '{bad json}\n'
        '{"review_id":"two","review_text":"Late delivery","rating":1}\n',
        encoding="utf-8",
    )
    connector = FileImportConnector(source, "lazada", settings=config(tmp_path))
    items = [item async for item in connector.collect(run())]
    assert [item.source_external_id for item in items] == ["one", "two"]
    assert len(connector.quarantined) == 1
    assert connector.quarantined[0].code == "malformed_json"


@pytest.mark.asyncio
async def test_shopee_export_aliases_epoch_rating_and_reply_metadata(tmp_path) -> None:
    source = tmp_path / "shopee.csv"
    source.write_text(
        "cmtid,rating_star,comment,ctime,item_id,item_name,shop_id,shop_name,"
        "product_url,seller_reply,seller_reply_at,order_id\n"
        'cmt-1,5 sao,"Giao hàng nhanh và đóng gói rất tốt",1752278400,'
        'item-9,"Kem chống nắng",shop-7,"Guardian Official Store",'
        'https://shopee.vn/product/item-9,"Cảm ơn bạn",1752282000,order-secret\n',
        encoding="utf-8",
    )
    connector = FileImportConnector(source, "shopee", settings=config(tmp_path))
    items = [item async for item in connector.collect(run())]
    assert len(items) == 1
    item = items[0]
    assert item.source_external_id == "cmt-1"
    assert item.rating == 5
    assert item.product_name == "Kem chống nắng"
    assert item.store == "Guardian Official Store"
    assert item.occurred_at == datetime(2025, 7, 12, tzinfo=timezone.utc)
    assert item.metadata["product_id"] == "item-9"
    assert item.metadata["shop_id"] == "shop-7"
    assert item.metadata["seller_reply"] == "Cảm ơn bạn"
    assert item.metadata["seller_reply_at"] == "1752282000"
    assert "order-secret" not in json.dumps(item.metadata, ensure_ascii=False)


@pytest.mark.asyncio
async def test_lazada_and_vietnamese_diacritic_headers_are_resolved(tmp_path) -> None:
    source = tmp_path / "lazada.csv"
    source.write_text(
        "Mã đánh giá,review_content,Số sao,review_date,Tên sản phẩm\n"
        'lz-1,"Nhân viên tư vấn rất nhiệt tình",5/5,12/07/2025,"Sữa rửa mặt"\n',
        encoding="utf-8",
    )
    preview = preview_import(source, "lazada", settings=config(tmp_path))
    assert preview.resolved_mapping["source_external_id"] == "Mã đánh giá"
    assert preview.resolved_mapping["rating"] == "Số sao"
    connector = FileImportConnector(source, "lazada", settings=config(tmp_path))
    items = [item async for item in connector.collect(run())]
    assert len(items) == 1
    assert items[0].source_external_id == "lz-1"
    assert items[0].rating == 5
    assert items[0].text == "Nhân viên tư vấn rất nhiệt tình"


@pytest.mark.asyncio
async def test_rating_only_row_is_kept_but_seller_reply_is_not_a_customer_unit(
    tmp_path,
) -> None:
    source = tmp_path / "ratings.jsonl"
    source.write_text(
        json.dumps(
            {
                "cmtid": "rating-only",
                "rating_star": "4 sao",
                "ctime": "2026-07-11 08:00:00",
                "product_url": "https://shopee.vn/guardian-item",
            },
            ensure_ascii=False,
        )
        + "\n"
        + json.dumps(
            {
                "seller_reply_id": "reply-only",
                "reply_content": "Guardian cảm ơn quý khách",
                "ctime": "2026-07-11 09:00:00",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    connector = FileImportConnector(source, "shopee", settings=config(tmp_path))
    items = [item async for item in connector.collect(run())]
    assert len(items) == 1
    assert items[0].source_external_id == "rating-only"
    assert items[0].rating == 4
    assert items[0].text == "Đánh giá 4 sao"
    assert items[0].metadata["rating_only"] is True
    assert len(connector.quarantined) == 1
    assert connector.quarantined[0].field == "text"


@pytest.mark.asyncio
async def test_order_id_is_never_review_identity_and_product_url_does_not_dedupe(
    tmp_path,
) -> None:
    source = tmp_path / "identity.csv"
    source.write_text(
        "cmtid,order_id,comment,ctime,product_url\n"
        'review-a,order-1,"Sản phẩm tốt và giao hàng nhanh",12/07/2025,'
        "https://shopee.vn/guardian-item\n"
        'review-b,order-2,"Sản phẩm tốt và giao hàng nhanh",12/07/2025,'
        "https://shopee.vn/guardian-item\n"
        ',order-only,"Nhân viên hỗ trợ rất tốt",13/07/2025,'
        "https://shopee.vn/guardian-item\n",
        encoding="utf-8",
    )
    connector = FileImportConnector(source, "shopee", settings=config(tmp_path))
    raw = [item async for item in connector.collect(run())]
    assert [item.source_external_id for item in raw] == ["review-a", "review-b", None]
    normalized = [
        normalize_raw_feedback(
            item,
            ingestion_run_id="identity-run",
            source_name="shopee",
            settings=config(tmp_path),
            ingested_at=NOW,
        )
        for item in raw[:2]
    ]
    assert normalized[0].canonical_url == normalized[1].canonical_url
    assert normalized[0].feedback_id != normalized[1].feedback_id
    assert all(item.sanitized_metadata["identity_kind"] == "source_external_id" for item in normalized)


@pytest.mark.asyncio
async def test_vietnamese_only_period_filter_is_inclusive_in_vietnam_timezone(
    tmp_path,
) -> None:
    assert GUARDIAN_VOC_PERIOD_START == date(2025, 7, 12)
    assert GUARDIAN_VOC_PERIOD_END == date(2026, 7, 11)
    source = tmp_path / "period.csv"
    source.write_text(
        "cmtid,comment,rating_star,ctime\n"
        'first,"Giao hàng nhanh và sản phẩm rất tốt",5,2025-07-12 00:00:00\n'
        'last,"Nhân viên tư vấn rất nhiệt tình",5,2026-07-11 23:59:59\n'
        'before,"Sản phẩm tốt nhưng giao hàng chậm",3,2025-07-11 23:59:59\n'
        'after,"Sản phẩm tốt và giá rất hợp lý",5,2026-07-12 00:00:00\n'
        'english,"The delivery was late and the product was damaged",1,2026-01-02\n'
        'undated,"Nhân viên hỗ trợ rất tốt",5,\n'
        "stars-only,,4 sao,2026-03-04\n",
        encoding="utf-8",
    )
    connector = FileImportConnector(
        source,
        "shopee",
        settings=config(tmp_path),
        vietnamese_only=True,
        period_start="2025-07-12",
        period_end="2026-07-11",
    )
    items = [item async for item in connector.collect(run())]
    assert [item.source_external_id for item in items] == [
        "first",
        "last",
        "stars-only",
    ]
    assert [item.occurred_at for item in items[:2]] == [
        datetime(2025, 7, 11, 17, tzinfo=timezone.utc),
        datetime(2026, 7, 11, 16, 59, 59, tzinfo=timezone.utc),
    ]
    assert [issue.code for issue in connector.quarantined].count("period_filtered") == 3
    assert [issue.code for issue in connector.quarantined].count("language_filtered") == 1


@pytest.mark.asyncio
async def test_social_adapter_keeps_all_keyword_brand_candidates_and_undated_item() -> None:
    connector = SocialCrawlerConnector(
        [
            {
                "record_id": "crawler-title-hash",
                "keywords": ["guardian", "hasaki comparison"],
                "platform": "Facebook",
                "title": "Guardian or Hasaki?",
                "description": "Both retailers are discussed without a clear primary target.",
                "link": "https://facebook.com/posts/abc?utm_campaign=x",
                "published_date": None,
                "bucket_end": "2026-07-11T12:00:00Z",
                "scraper_source": "metadata",
            }
        ]
    )
    items = [item async for item in connector.collect(run())]
    assert len(items) == 1
    item = items[0]
    assert item.brand is None
    assert {value.value for value in item.brand_candidates} == {"guardian", "hasaki"}
    assert item.occurred_at is None
    assert item.occurred_at_quality.value == "missing"
    assert item.metadata["crawler_record_id"] == "crawler-title-hash"
