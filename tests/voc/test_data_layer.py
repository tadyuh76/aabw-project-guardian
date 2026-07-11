from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from guardian_voc.config import Settings
from guardian_voc.data_layer import LiveDataLayer
from guardian_voc.db import Database
from guardian_voc.source_registry import load_source_registry
from guardian_voc.schemas.extraction import PageExtractionResult


class FakeSerpApiClient:
    instances: list["FakeSerpApiClient"] = []

    def __init__(self, api_key: str, base_url: str) -> None:
        assert api_key == "serp-test-key"
        self.base_url = base_url
        self.searches: list[dict[str, Any]] = []
        self.account_calls = 0
        self.closed = False
        self.instances.append(self)

    async def account(self) -> dict[str, Any]:
        self.account_calls += 1
        return {"total_searches_left": 50 if self.account_calls == 1 else 45}

    async def google_search(self, **kwargs: Any) -> dict[str, Any]:
        self.searches.append(dict(kwargs))
        query = str(kwargs["query"])
        if query.startswith("site:guardian.com.vn"):
            return {
                "organic_results": [
                    {
                        "position": 1,
                        "link": "https://www.guardian.com.vn/products/serum?utm_source=test",
                        "title": "Guardian serum",
                        "snippet": "Tôi mua sản phẩm này và giao hàng rất chậm.",
                    },
                    {
                        "position": 2,
                        "link": "https://www.guardian.com.vn/review",
                        "title": "Blocked review endpoint",
                        "snippet": "This is discovery evidence only.",
                    },
                    {
                        "position": 3,
                        "link": "https://attacker.example/review",
                        "title": "Off-domain result",
                        "snippet": "Không được phép tải nội dung này.",
                    },
                ]
            }
        if query.startswith("site:shopee.vn"):
            return {
                "organic_results": [
                    {
                        "position": 1,
                        "link": "https://shopee.vn/product/guardian-serum",
                        "title": "Guardian Official Store",
                        "snippet": "Đánh giá năm sao từ kết quả tìm kiếm.",
                    }
                ]
            }
        return {
            "organic_results": [
                {
                    "position": 1,
                    "link": "https://www.facebook.com/customer/posts/guardian-review",
                    "title": "Bài viết của khách hàng",
                    "snippet": "Mình mua tại Guardian nhưng mã giảm giá không dùng được.",
                }
            ]
        }

    async def aclose(self) -> None:
        self.closed = True


class FakeTinyFishResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self.payload


class FakeTinyFishClient:
    requested_batches: list[list[str]] = []

    def __init__(self, **_: Any) -> None:
        pass

    async def __aenter__(self) -> "FakeTinyFishClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def post(self, _url: str, **kwargs: Any) -> FakeTinyFishResponse:
        urls = list(kwargs["json"]["urls"])
        self.requested_batches.append(urls)
        results: list[dict[str, Any]] = []
        for url in urls:
            if "/products/serum" in url:
                results.append(
                    {
                        "url": url,
                        "final_url": "https://guardian.com.vn/review",
                        "title": "Blocked redirect",
                        "text": "x" * 200,
                    }
                )
            elif "facebook.com" in url:
                results.append(
                    {
                        "url": url,
                        "final_url": "https://attacker.example/copied-post",
                        "title": "Off-domain redirect",
                        "text": "x" * 200,
                    }
                )
            else:
                # Exercise the documented description fallback as well as the
                # normal successful TinyFish result path.
                results.append(
                    {
                        "url": url,
                        "final_url": url,
                        "title": "Public page",
                        "description": (
                            "Nội dung công khai đã được đọc từ trang gốc và đủ dài "
                            "để sử dụng làm dữ liệu bổ trợ cho bước xử lý tiếp theo."
                        ),
                        "language": "vi",
                    }
                )
        return FakeTinyFishResponse({"results": results, "errors": []})


class FakeExtractionProvider:
    requests: list[Any] = []

    def __init__(self, **_: Any) -> None:
        pass

    async def extract_page(self, request: Any) -> PageExtractionResult:
        self.requests.append(request)
        block = request.blocks[0]
        return PageExtractionResult.model_validate(
            {
                "schema_version": "voc-feedback-extractor.v1",
                "page_state": "usable",
                "units": [
                    {
                        "container_id": block.container_id,
                        "customer_text_spans": [
                            {
                                "block_id": block.block_id,
                                "quote": block.text,
                                "occurrence_index": 0,
                            }
                        ],
                        "seller_response_spans": [],
                        "occurred_at_span": None,
                        "rating_span": None,
                        "product_name_span": None,
                        "extraction_confidence": 0.98,
                    }
                ],
            }
        )

    async def aclose(self) -> None:
        return None


def live_settings(tmp_path: Path) -> Settings:
    return Settings(
        voc_db_path=tmp_path / "live.duckdb",
        voc_data_dir=tmp_path / "data",
        serp_api_key="serp-test-key",
        tinyfish_api_key="tinyfish-test-key",
        tinyfish_useful_text_chars=50,
    )


def test_registry_ids_and_live_data_migration_load(tmp_path: Path) -> None:
    registry = load_source_registry()
    expected = {
        "guardian_web",
        "guardian_grabmart",
        "guardian_public_social",
        "hasaki_public_social",
        "watsons_public_social",
    }
    assert {source.source_id for source in registry.sources} == expected
    assert {source.source_id for source in registry.excluded_sources} == {
        "guardian_shopee_hcm",
        "guardian_shopee_hn",
        "guardian_lazada",
        "guardian_tiktok_shop",
    }
    assert {"152872415", "guardian_officialstore"} <= set(
        registry.get("guardian_shopee_hcm").verified_account_ids
    )
    assert registry.get("guardian_shopee_hcm").default_crawl is False
    assert registry.get("hasaki_public_social").owner_brand == "hasaki"
    assert registry.get("watsons_public_social").owner_brand == "watsons"
    guardian_web = registry.get("guardian_web")
    assert guardian_web.blocked_path("https://guardian.com.vn/review") is True
    assert guardian_web.blocked_path("https://guardian.com.vn/%72eview/item") is True
    assert guardian_web.blocked_path("https://guardian.com.vn/reviews") is False

    layer = LiveDataLayer(settings=live_settings(tmp_path))
    layer.initialize()
    assert layer.database.schema_version() == 2
    rows = layer.database.query(
        "SELECT source_id, verified_account_ids FROM source_registry ORDER BY source_id"
    )
    assert {str(row["source_id"]) for row in rows} == expected
    assert all(row["source_id"] != "guardian_shopee_hcm" for row in rows)
    tables = {
        row["table_name"]
        for row in layer.database.query(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
        )
    }
    assert {
        "source_registry",
        "discovery_results",
        "fetch_attempts",
        "source_checkpoints",
        "classification_failures",
        "page_extractions",
    } <= tables


async def _discover(layer: LiveDataLayer, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    FakeSerpApiClient.instances.clear()
    monkeypatch.setattr("guardian_voc.data_layer.SerpApiClient", FakeSerpApiClient)
    return await layer.discover(
        source_ids=(
            "guardian_web",
            "guardian_grabmart",
            "guardian_public_social",
        )
    )


@pytest.mark.asyncio
async def test_serp_discovery_is_never_customer_feedback_and_filters_fetch_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layer = LiveDataLayer(settings=live_settings(tmp_path))
    result = await _discover(layer, monkeypatch)
    selected = {
        "guardian_web",
        "guardian_grabmart",
        "guardian_public_social",
    }
    assert result["searches"] == sum(
        len(source.search_queries)
        for source in layer.registry.sources
        if source.source_id in selected
    )
    assert result["available_before"] == 50
    assert result["available_after"] == 45
    assert FakeSerpApiClient.instances[0].closed is True

    # A customer-like search snippet stays in the discovery audit table only.
    snippet = "Tôi mua sản phẩm này và giao hàng rất chậm."
    discovery = layer.database.query(
        """
        SELECT canonical_url, snippet_redacted, eligible_for_fetch, rejection_reason
        FROM discovery_results ORDER BY canonical_url
        """
    )
    assert any(row["snippet_redacted"] == snippet for row in discovery)
    assert layer.database.query_one("SELECT count(*) AS n FROM feedback_items")["n"] == 0
    assert layer.database.query_one("SELECT count(*) AS n FROM feedback_analyses")["n"] == 0
    assert layer.database.query_one("SELECT count(*) AS n FROM page_reader_cache")["n"] == 0

    by_url = {str(row["canonical_url"]): row for row in discovery}
    assert by_url["https://guardian.com.vn/products/serum"]["eligible_for_fetch"] is True
    assert by_url["https://guardian.com.vn/review"]["rejection_reason"] == (
        "robots_or_registry_blocked_path"
    )
    assert by_url["https://attacker.example/review"]["rejection_reason"] == "off_domain"
    assert by_url["https://grab.com/vn/download?shortlink=GMxGuardian"]["rejection_reason"] == (
        "written_permission_or_authorized_export_required"
    )


@pytest.mark.asyncio
async def test_tinyfish_revalidates_permission_and_manifest_uses_database_truth(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layer = LiveDataLayer(settings=live_settings(tmp_path))
    await _discover(layer, monkeypatch)

    # Simulate a stale or corrupted discovery-time decision.  Fetch must apply
    # the current registry again and must never send these GrabMart URLs.
    layer.database.execute(
        """
        UPDATE discovery_results
        SET eligible_for_fetch = TRUE, rejection_reason = NULL
        WHERE source_id = 'guardian_grabmart'
        """
    )
    FakeTinyFishClient.requested_batches.clear()
    discovery_count = layer.database.query_one(
        """
        SELECT count(*) AS n FROM discovery_results
        WHERE source_id IN (
            'guardian_web', 'guardian_grabmart', 'guardian_public_social'
        )
        """
    )["n"]
    monkeypatch.setattr("guardian_voc.data_layer.httpx.AsyncClient", FakeTinyFishClient)
    result = await layer.fetch(
        source_ids=(
            "guardian_web",
            "guardian_grabmart",
            "guardian_public_social",
        )
    )
    requested = [url for batch in FakeTinyFishClient.requested_batches for url in batch]
    assert result == {
        "attempted": 4,
        "snapshot_attempts": 4,
        "permission_revalidated": discovery_count,
        "policy_filtered": 2,
        "status": {"invalid_redirect": 2, "usable": 2},
        "output": str((tmp_path / "data/live/fetches.jsonl").resolve()),
    }
    assert requested
    assert not any("grab.com" in url for url in requested)
    assert not any("attacker.example/review" in url for url in requested)
    assert not any(url.endswith("/review") for url in requested)

    attempts = layer.database.query(
        "SELECT source_id, status, error_code, customer_voice_units FROM fetch_attempts"
    )
    assert {row["error_code"] for row in attempts if row["status"] == "invalid_redirect"} == {
        "redirect_outside_registry",
        "redirect_to_blocked_path",
    }
    assert all(row["source_id"] != "guardian_grabmart" for row in attempts)
    assert all(row["customer_voice_units"] == 0 for row in attempts)
    assert layer.database.query_one("SELECT count(*) AS n FROM feedback_items")["n"] == 0

    manifest = layer.build_manifest(stages={"untrusted_claim": {"feedback_items": 999}})
    assert manifest["counts"] == {
        "feedback_items": 0,
        "real_feedback_items": 0,
        "time_eligible_real_feedback_items": 0,
        "analyzed_feedback_items": 0,
        "analysis_rows": 0,
        "relevant_analysis_rows": 0,
        "guardian_relevant_analysis_rows": 0,
        "real_feedback_analysis_rows": 0,
        "page_extraction_attempts": 0,
        "completed_page_extractions": 0,
        "extracted_customer_units": 0,
        "classification_failures": 0,
        "unresolved_classification_failures": 0,
    }
    assert manifest["ready_for_analysis"] is False
    assert manifest["classification_executed"] is False
    source_manifest = {row["source_id"]: row for row in manifest["sources"]}
    assert source_manifest["guardian_grabmart"]["fetch_eligible"] == 0
    assert source_manifest["guardian_grabmart"]["usable_fetches"] == 0
    assert source_manifest["guardian_web"]["usable_fetches"] == 1
    assert source_manifest["guardian_web"]["failed_fetches"] == 1
    assert source_manifest["guardian_public_social"]["usable_fetches"] == 1
    assert source_manifest["guardian_public_social"]["failed_fetches"] == 1
    on_disk = json.loads(Path(manifest["output"]).read_text(encoding="utf-8"))
    assert on_disk == manifest


@pytest.mark.asyncio
async def test_fetch_rejects_unknown_source_id_before_calling_tinyfish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layer = LiveDataLayer(settings=live_settings(tmp_path))
    FakeTinyFishClient.requested_batches.clear()
    monkeypatch.setattr("guardian_voc.data_layer.httpx.AsyncClient", FakeTinyFishClient)
    with pytest.raises(ValueError, match="unknown source_id"):
        await layer.fetch(source_ids=("not_in_registry",))
    assert FakeTinyFishClient.requested_batches == []


@pytest.mark.asyncio
async def test_tinyfish_page_to_grounded_vietnamese_feedback_uses_extractor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = live_settings(tmp_path).model_copy(
        update={"ai_api_key": "openai-test-key", "ai_model": "gpt-5.6-luna"}
    )
    layer = LiveDataLayer(settings=settings)
    layer.initialize()
    source = layer.registry.get("guardian_public_social")
    event = layer._upsert_discovery(
        source=source,
        query_id="test_public_post",
        query='"Guardian Việt Nam" "trải nghiệm"',
        raw_url="https://www.instagram.com/p/customer-post-1/",
        title="Kết quả tìm kiếm không phải phản hồi",
        snippet="Đây chỉ là snippet và không được phân loại.",
    )
    assert event is not None

    FakeTinyFishClient.requested_batches.clear()
    monkeypatch.setattr("guardian_voc.data_layer.httpx.AsyncClient", FakeTinyFishClient)
    fetched = await layer.fetch(source_ids=("guardian_public_social",))
    assert fetched["status"] == {"usable": 1}

    FakeExtractionProvider.requests.clear()
    monkeypatch.setattr(
        "guardian_voc.data_layer.OpenAICompatibleProvider", FakeExtractionProvider
    )
    extracted = await layer.extract_public_feedback()
    assert extracted["accepted_units"] == 1
    assert extracted["inserted"] == 1
    assert extracted["status"] == {"completed": 1}
    assert len(FakeExtractionProvider.requests) == 1
    request = FakeExtractionProvider.requests[0]
    assert request.max_units == 1
    assert "snippet" not in "\n".join(block.text for block in request.blocks).lower()

    stored = layer.database.query_one(
        "SELECT source_platform, language, text_redacted FROM feedback_items"
    )
    assert stored is not None
    assert stored["source_platform"] == "instagram"
    assert stored["language"] == "vi"
    assert "Nội dung công khai" in stored["text_redacted"]
    assert "Đây chỉ là snippet" not in stored["text_redacted"]
    attempt = layer.database.query_one(
        "SELECT status, unit_count, model_version FROM page_extractions"
    )
    assert attempt == {
        "status": "completed",
        "unit_count": 1,
        "model_version": "gpt-5.6-luna",
    }


def test_guardian_catalog_seed_is_inventory_not_feedback(tmp_path: Path) -> None:
    layer = LiveDataLayer(settings=live_settings(tmp_path))
    catalog = tmp_path / "guardian_catalog.json"
    catalog.write_text(
        json.dumps(
            {
                "pages_crawled": 2,
                "next_url": "https://www.guardian.com.vn/all?p=3",
                "products": [
                    {
                        "product_id": "p1",
                        "title": "Sản phẩm một",
                        "brand": "TEST",
                        "url": "https://www.guardian.com.vn/san-pham-mot.html",
                        "review_url": (
                            "https://www.guardian.com.vn/san-pham-mot.html#reviews"
                        ),
                        "rating": "5 29 Đánh giá",
                    },
                    {
                        "product_id": "p2",
                        "title": "Sản phẩm hai",
                        "brand": "TEST",
                        "url": "https://www.guardian.com.vn/san-pham-hai.html",
                        "review_url": None,
                        "rating": None,
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = layer.seed_guardian_catalog(catalog)

    assert result["unique_products_seeded"] == 2
    assert result["products_with_review_anchor"] == 1
    assert result["visible_aggregate_review_count"] == 29
    assert result["inventory_complete"] is False
    assert layer.database.query_one("SELECT count(*) AS n FROM feedback_items")["n"] == 0
    seeded = layer.database.query_one(
        """
        SELECT canonical_url, metadata FROM discovery_results
        WHERE query_id = 'guardian_catalog_checkpoint'
          AND canonical_url LIKE '%san-pham-mot.html'
        """
    )
    assert seeded is not None
    metadata = json.loads(seeded["metadata"])
    assert metadata["review_url"].endswith("#reviews")
    assert metadata["visible_aggregate_review_count"] == 29


@pytest.mark.asyncio
async def test_competitor_public_social_flows_through_extraction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = live_settings(tmp_path).model_copy(
        update={"ai_api_key": "openai-test-key", "ai_model": "gpt-5.6-luna"}
    )
    layer = LiveDataLayer(settings=settings)
    layer.initialize()
    source = layer.registry.get("hasaki_public_social")
    event = layer._upsert_discovery(
        source=source,
        query_id="hasaki_instagram_vi",
        query='site:instagram.com Hasaki "trải nghiệm"',
        raw_url="https://www.instagram.com/p/hasaki-customer-post/",
        title="Khách hàng nói về Hasaki",
    )
    assert event is not None

    FakeTinyFishClient.requested_batches.clear()
    monkeypatch.setattr("guardian_voc.data_layer.httpx.AsyncClient", FakeTinyFishClient)
    await layer.fetch(source_ids=("hasaki_public_social",))
    FakeExtractionProvider.requests.clear()
    monkeypatch.setattr(
        "guardian_voc.data_layer.OpenAICompatibleProvider", FakeExtractionProvider
    )

    extracted = await layer.extract_public_feedback(
        source_ids=("hasaki_public_social",)
    )

    assert extracted["inserted"] == 1
    stored = layer.database.query_one(
        "SELECT brand, brand_candidates, source_platform FROM feedback_items"
    )
    assert stored is not None
    assert stored["brand"] is None
    assert "hasaki" in stored["brand_candidates"]
    assert stored["source_platform"] == "instagram"
