from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timezone
from urllib.parse import parse_qs

import httpx
import pytest

from guardian_voc.connectors.marketplace_api import (
    LAZADA_GET_PRODUCTS_PATH,
    LAZADA_REVIEW_LIST_PATH,
    SHOPEE_GET_COMMENT_PATH,
    SHOPEE_GET_ITEM_LIST_PATH,
    LazadaCredentials,
    LazadaReviewConnector,
    MarketplaceAPIError,
    MarketplaceAuthorizationError,
    MarketplaceCredentialsError,
    ShopeeCredentials,
    ShopeeReviewConnector,
    sign_lazada_request,
    sign_shopee_request,
)
from guardian_voc.schemas.feedback import Brand, IngestionRun


NOW = datetime(2026, 7, 11, 12, tzinfo=timezone.utc)


def run() -> IngestionRun:
    return IngestionRun(
        id="marketplace-test",
        connector="marketplace_api",
        source_name="guardian_official_store",
        status="running",
        started_at=NOW,
    )


def fixed_clock() -> datetime:
    return datetime(2026, 7, 11, 12, 1, 2, tzinfo=timezone.utc)


def epoch(value: str) -> int:
    return int(datetime.fromisoformat(value).timestamp())


def test_credentials_and_owned_shop_permission_are_required_and_secret_safe() -> None:
    with pytest.raises(MarketplaceCredentialsError, match="partner_key is required"):
        ShopeeCredentials(
            partner_id=1, partner_key="", access_token="seller-token", shop_id=2
        )
    with pytest.raises(MarketplaceCredentialsError, match="access_token is required"):
        LazadaCredentials(app_key="app", app_secret="secret", access_token=" ")

    shopee = ShopeeCredentials(
        partner_id=11,
        partner_key="partner-secret",
        access_token="seller-token",
        shop_id=22,
    )
    lazada = LazadaCredentials(
        app_key="app-key", app_secret="app-secret", access_token="access-token"
    )
    assert "partner-secret" not in repr(shopee)
    assert "seller-token" not in repr(shopee)
    assert "app-secret" not in repr(lazada)
    assert "access-token" not in repr(lazada)

    with pytest.raises(MarketplaceAuthorizationError, match="Guardian-owned"):
        ShopeeReviewConnector(shopee, item_ids=[100])
    with pytest.raises(MarketplaceAuthorizationError, match="Guardian-owned"):
        LazadaReviewConnector(lazada, item_ids=[100])
    with pytest.raises(ValueError, match="official HTTPS endpoint"):
        ShopeeReviewConnector(
            shopee,
            item_ids=[100],
            owned_shop_authorized=True,
            base_url="https://attacker.example",
        )


def test_signature_helpers_match_platform_algorithms() -> None:
    shopee_base = "123/api/v2/product/get_comment1700000000token456"
    expected_shopee = hmac.new(
        b"partner-key", shopee_base.encode(), hashlib.sha256
    ).hexdigest()
    assert sign_shopee_request(
        partner_id=123,
        api_path=SHOPEE_GET_COMMENT_PATH,
        timestamp=1_700_000_000,
        access_token="token",
        shop_id=456,
        partner_key="partner-key",
    ) == expected_shopee

    lazada_params = {
        "app_key": "app",
        "timestamp": 1_700_000_000_000,
        "item_id": "789",
        "sign_method": "sha256",
        "access_token": "token",
    }
    base = LAZADA_REVIEW_LIST_PATH + "".join(
        f"{key}{lazada_params[key]}" for key in sorted(lazada_params)
    )
    expected_lazada = hmac.new(
        b"app-secret", base.encode(), hashlib.sha256
    ).hexdigest().upper()
    assert sign_lazada_request(
        api_path=LAZADA_REVIEW_LIST_PATH,
        parameters=lazada_params,
        app_secret="app-secret",
    ) == expected_lazada


@pytest.mark.asyncio
async def test_shopee_signed_cursor_pagination_flattens_and_filters_locally() -> None:
    requests: list[httpx.Request] = []
    token = "shopee-seller-token"
    secret = "shopee-partner-secret"

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        query = parse_qs(request.url.query.decode())
        assert request.url.path == SHOPEE_GET_COMMENT_PATH
        assert query["access_token"] == [token]
        assert query["shop_id"] == ["222"]
        assert query["item_id"] == ["9001"]
        timestamp = int(query["timestamp"][0])
        expected = sign_shopee_request(
            partner_id=111,
            api_path=SHOPEE_GET_COMMENT_PATH,
            timestamp=timestamp,
            access_token=token,
            shop_id=222,
            partner_key=secret,
        )
        assert query["sign"] == [expected]
        if "cursor" not in query:
            return httpx.Response(
                200,
                json={
                    "error": "",
                    "response": {
                        "total_count": 5,
                        "more": True,
                        "next_cursor": "opaque-next-cursor",
                        "item_comment_list": [
                            {
                                "comment_id": "s-1",
                                "comment": "Nhân viên tư vấn rất tốt",
                                "rating_star": 5,
                                "create_time": epoch("2026-07-10T10:00:00+00:00"),
                                "author_username": "buyer-one",
                                "images": ["https://cdn.example/review.jpg"],
                                "reply": {
                                    "comment": "Guardian cảm ơn bạn",
                                    "create_time": epoch(
                                        "2026-07-10T11:00:00+00:00"
                                    ),
                                    "editable": False,
                                },
                            },
                            {
                                "comment_id": "s-old",
                                "comment": "Đánh giá quá cũ",
                                "rating_star": 2,
                                "create_time": epoch("2025-07-10T11:59:59+00:00"),
                            },
                        ],
                    },
                },
            )
        assert query["cursor"] == ["opaque-next-cursor"]
        return httpx.Response(
            200,
            json={
                "error": "",
                "response": {
                    "total_count": 5,
                    "more": False,
                    "item_comment_list": [
                        {
                            "comment_id": "s-2",
                            "comment": "",
                            "rating_star": 4,
                            "create_time": epoch("2026-07-11T11:00:00+00:00"),
                            "product_name": "Kem chống nắng",
                        },
                        {
                            "comment_id": "s-no-date",
                            "comment": "Không có ngày",
                            "rating_star": 3,
                        },
                        {
                            "comment_id": "s-en",
                            "comment": "The delivery was very late and service was bad",
                            "rating_star": 1,
                            "create_time": epoch("2026-07-11T10:00:00+00:00"),
                        },
                    ],
                },
            },
        )

    connector = ShopeeReviewConnector(
        ShopeeCredentials(
            partner_id=111,
            partner_key=secret,
            access_token=token,
            shop_id=222,
        ),
        item_ids=[9001],
        owned_shop_authorized=True,
        page_size=2,
        transport=httpx.MockTransport(handler),
        clock=fixed_clock,
    )
    reviews = [review async for review in connector.collect(run())]

    assert [review.source_external_id for review in reviews] == ["s-1", "s-2"]
    assert all(review.brand is Brand.GUARDIAN for review in reviews)
    assert all(review.source_platform == "shopee" for review in reviews)
    assert reviews[0].media_urls == ["https://cdn.example/review.jpg"]
    assert reviews[0].metadata["seller_reply"]["text"] == "Guardian cảm ơn bạn"
    assert reviews[1].text == "Đánh giá 4/5 không kèm nội dung."
    assert reviews[1].metadata["text_is_generated_rating_summary"] is True
    assert reviews[1].product_name == "Kem chống nắng"
    assert len(requests) == 2

    item = connector.manifest.items["9001"]
    assert item.pages_requested == 2
    assert item.rows_received == 5
    assert item.unique_rows_received == 5
    assert item.records_emitted == 2
    assert item.records_before_window == 1
    assert item.records_missing_date == 1
    assert item.records_language_filtered == 1
    assert item.reported_total == 5
    assert item.pagination_complete is True
    assert item.reconciliation == "matched"
    assert len(item.cursor_chain_sha256) == 1
    assert "opaque-next-cursor" not in json.dumps(connector.manifest.as_dict())
    serialized_manifest = json.dumps(connector.manifest.as_dict())
    assert token not in serialized_manifest
    assert secret not in serialized_manifest


@pytest.mark.asyncio
async def test_shopee_reconciles_missing_cursor_as_incomplete() -> None:
    transport = httpx.MockTransport(
        lambda _: httpx.Response(
            200,
            json={
                "error": "",
                "response": {
                    "total_count": 2,
                    "more": True,
                    "item_comment_list": [
                        {
                            "comment_id": "only-one",
                            "comment": "Một đánh giá",
                            "create_time": epoch("2026-07-10T10:00:00+00:00"),
                        }
                    ],
                },
            },
        )
    )
    connector = ShopeeReviewConnector(
        ShopeeCredentials(
            partner_id=1, partner_key="secret", access_token="token", shop_id=2
        ),
        item_ids=[3],
        owned_shop_authorized=True,
        transport=transport,
        clock=fixed_clock,
    )
    reviews = [review async for review in connector.collect(run())]
    assert len(reviews) == 1
    item = connector.manifest.items["3"]
    assert item.pagination_complete is False
    assert item.reconciliation == "incomplete"
    assert item.warnings == ["provider indicated more rows but omitted next_cursor"]


@pytest.mark.asyncio
async def test_shopee_all_items_enumerates_authorized_catalog_before_reviews() -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        query = parse_qs(request.url.query.decode())
        if request.url.path == SHOPEE_GET_ITEM_LIST_PATH:
            items = (
                [{"item_id": 9001}, {"item_id": 9002}]
                if query["item_status"] == ["NORMAL"]
                else []
            )
            return httpx.Response(
                200,
                json={
                    "error": "",
                    "response": {"item": items, "has_next_page": False},
                },
            )
        assert request.url.path == SHOPEE_GET_COMMENT_PATH
        return httpx.Response(
            200,
            json={
                "error": "",
                "response": {
                    "total_count": 0,
                    "more": False,
                    "item_comment_list": [],
                },
            },
        )

    connector = ShopeeReviewConnector(
        ShopeeCredentials(
            partner_id=1,
            partner_key="secret",
            access_token="token",
            shop_id=2,
        ),
        discover_all_items=True,
        owned_shop_authorized=True,
        transport=httpx.MockTransport(handler),
        clock=fixed_clock,
    )
    assert [item async for item in connector.collect(run())] == []
    manifest = connector.manifest
    assert manifest.item_ids == ("9001", "9002")
    assert manifest.item_discovery_requested is True
    assert manifest.item_discovery_complete is True
    assert manifest.item_discovery_pages == 4
    assert manifest.item_discovery_count == 2
    assert paths.count(SHOPEE_GET_ITEM_LIST_PATH) == 4
    assert paths.count(SHOPEE_GET_COMMENT_PATH) == 2


@pytest.mark.asyncio
async def test_lazada_signed_page_pagination_flattens_nested_reviews() -> None:
    requests: list[httpx.Request] = []
    access_token = "lazada-seller-token"
    app_secret = "lazada-app-secret"

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        query = parse_qs(request.url.query.decode())
        assert request.url.path == "/rest/review/seller/list"
        assert query["access_token"] == [access_token]
        unsigned = {
            key: values[0] for key, values in query.items() if key != "sign"
        }
        expected = sign_lazada_request(
            api_path=LAZADA_REVIEW_LIST_PATH,
            parameters=unsigned,
            app_secret=app_secret,
        )
        assert query["sign"] == [expected]
        current = int(query["current"][0])
        if current == 1:
            return httpx.Response(
                200,
                json={
                    "code": "0",
                    "data": {
                        "total_count": 4,
                        "has_more": True,
                        "next_page": 2,
                        "products": [
                            {
                                "item_id": 7001,
                                "product_name": "Sữa rửa mặt",
                                "product_url": "https://www.lazada.vn/products/7001.html",
                                "reviews": [
                                    {
                                        "review_id": "l-1",
                                        "content": "Giao hàng nhanh, đóng gói kỹ",
                                        "rating": 5,
                                        "created_at": "2026-06-01T10:00:00+07:00",
                                        "images": [
                                            {"url": "https://cdn.example/lazada.jpg"}
                                        ],
                                        "seller_reply": {
                                            "content": "Cảm ơn bạn đã mua hàng",
                                            "created_at": "2026-06-02T10:00:00+07:00",
                                        },
                                    },
                                    {
                                        "review_id": "l-old",
                                        "content": "Cũ",
                                        "rating": 1,
                                        "created_at": "2025-07-01T10:00:00+07:00",
                                    },
                                ],
                            }
                        ],
                    },
                },
            )
        assert current == 2
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "total_count": 4,
                    "has_more": False,
                    "products": [
                        {
                            "item_id": 7001,
                            "product_name": "Sữa rửa mặt",
                            "reviews": [
                                {
                                    "review_id": "l-2",
                                    "content": "",
                                    "ratings": {
                                        "overall": 4,
                                        "product_quality": 5,
                                    },
                                    "created_at": "2026-07-01T10:00:00+07:00",
                                    "videos": [
                                        {"video_url": "https://cdn.example/review.mp4"}
                                    ],
                                },
                                {
                                    "review_id": "l-en",
                                    "content": "This product is good but delivery was late",
                                    "rating": 3,
                                    "created_at": "2026-07-02T10:00:00+07:00",
                                },
                            ],
                        }
                    ],
                },
            },
        )

    connector = LazadaReviewConnector(
        LazadaCredentials(
            app_key="lazada-app-key",
            app_secret=app_secret,
            access_token=access_token,
        ),
        item_ids=[7001],
        owned_shop_authorized=True,
        page_size=2,
        transport=httpx.MockTransport(handler),
        clock=fixed_clock,
    )
    reviews = [review async for review in connector.collect(run())]

    assert [review.source_external_id for review in reviews] == ["l-1", "l-2"]
    assert reviews[0].product_name == "Sữa rửa mặt"
    assert reviews[0].source_url == "https://www.lazada.vn/products/7001.html"
    assert reviews[0].media_urls == ["https://cdn.example/lazada.jpg"]
    assert reviews[0].metadata["seller_reply"]["text"] == "Cảm ơn bạn đã mua hàng"
    assert reviews[1].rating == 4
    assert reviews[1].media_urls == ["https://cdn.example/review.mp4"]
    assert reviews[1].metadata["ratings"]["product_quality"] == 5
    assert reviews[1].text == "Đánh giá 4/5 không kèm nội dung."
    assert all(review.brand is Brand.GUARDIAN for review in reviews)
    assert len(requests) == 2

    item = connector.manifest.items["7001"]
    assert item.pages_requested == 2
    assert item.rows_received == 4
    assert item.unique_rows_received == 4
    assert item.records_emitted == 2
    assert item.records_before_window == 1
    assert item.records_language_filtered == 1
    assert item.reported_total == 4
    assert item.pagination_complete is True
    assert item.reconciliation == "matched"
    assert len(item.cursor_chain_sha256) == 1
    manifest = json.dumps(connector.manifest.as_dict())
    assert access_token not in manifest
    assert app_secret not in manifest


@pytest.mark.asyncio
async def test_lazada_all_items_enumerates_authorized_catalog_before_reviews() -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path == f"/rest{LAZADA_GET_PRODUCTS_PATH}":
            return httpx.Response(
                200,
                json={
                    "code": "0",
                    "data": {
                        "total_products": 2,
                        "products": [
                            {"item_id": 7001, "product_name": "Sản phẩm 1"},
                            {"item_id": 7002, "product_name": "Sản phẩm 2"},
                        ],
                    },
                },
            )
        assert request.url.path == f"/rest{LAZADA_REVIEW_LIST_PATH}"
        return httpx.Response(
            200,
            json={
                "code": "0",
                "data": {
                    "total_count": 0,
                    "has_more": False,
                    "products": [],
                },
            },
        )

    connector = LazadaReviewConnector(
        LazadaCredentials(
            app_key="app-key", app_secret="secret", access_token="token"
        ),
        discover_all_items=True,
        owned_shop_authorized=True,
        transport=httpx.MockTransport(handler),
        clock=fixed_clock,
    )
    assert [item async for item in connector.collect(run())] == []
    manifest = connector.manifest
    assert manifest.item_ids == ("7001", "7002")
    assert manifest.item_discovery_requested is True
    assert manifest.item_discovery_complete is True
    assert manifest.item_discovery_pages == 1
    assert manifest.item_discovery_count == 2
    assert paths.count(f"/rest{LAZADA_GET_PRODUCTS_PATH}") == 1
    assert paths.count(f"/rest{LAZADA_REVIEW_LIST_PATH}") == 2


@pytest.mark.asyncio
async def test_provider_error_message_never_echoes_secrets() -> None:
    token = "do-not-leak-token"
    secret = "do-not-leak-secret"
    connector = LazadaReviewConnector(
        LazadaCredentials(app_key="key", app_secret=secret, access_token=token),
        item_ids=[123],
        owned_shop_authorized=True,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={
                    "code": "InvalidAccessToken",
                    "message": f"bad {token} signed with {secret}",
                },
            )
        ),
        clock=fixed_clock,
    )
    with pytest.raises(MarketplaceAPIError) as captured:
        _ = [review async for review in connector.collect(run())]
    assert token not in str(captured.value)
    assert secret not in str(captured.value)
