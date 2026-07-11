from __future__ import annotations

from pathlib import Path

import pytest

from guardian_voc.source_registry import load_source_registry


EXCLUDED_MARKETPLACE_SOURCES = {
    "guardian_shopee_hcm",
    "guardian_shopee_hn",
    "guardian_lazada",
    "guardian_tiktok_shop",
}
DEFAULT_SOURCES = {
    "guardian_web",
    "guardian_grabmart",
    "guardian_public_social",
    "hasaki_public_social",
    "watsons_public_social",
}
PUBLIC_SOCIAL_SOURCES = {
    "guardian_public_social": "guardian",
    "hasaki_public_social": "hasaki",
    "watsons_public_social": "watsons",
}
EXCLUSION_TERMS = (
    "-site:shopee.vn",
    "-site:lazada.vn",
    "-site:shop.tiktok.com",
)


def test_default_registry_excludes_marketplaces_and_uses_per_source_owners() -> None:
    load_source_registry.cache_clear()
    registry = load_source_registry()

    assert {source.source_id for source in registry.sources} == DEFAULT_SOURCES
    assert {
        source.source_id for source in registry.excluded_sources
    } == EXCLUDED_MARKETPLACE_SOURCES
    assert {source.source_id for source in registry.all_sources} == (
        DEFAULT_SOURCES | EXCLUDED_MARKETPLACE_SOURCES
    )
    for source_id in EXCLUDED_MARKETPLACE_SOURCES:
        assert registry.get(source_id).default_crawl is False
    for source_id, owner in PUBLIC_SOCIAL_SOURCES.items():
        source = registry.get(source_id)
        assert source.default_crawl is True
        assert source.owner_brand == owner


def test_default_query_pack_is_exclusion_safe_and_covers_platforms_and_problems() -> None:
    load_source_registry.cache_clear()
    registry = load_source_registry()

    for source in registry.sources:
        for query in source.search_queries:
            assert all(term in query.query for term in EXCLUSION_TERMS), query.id

    expected_suffixes = {
        "facebook_review_vi",
        "facebook_order_vi",
        "instagram_review_vi",
        "threads_review_vi",
        "tiktok_video_review_vi",
        "youtube_review_vi",
        "reddit_review_vi",
        "product_reaction_vi",
        "product_quality_vi",
        "service_delivery_vi",
        "service_staff_payment_vi",
        "promo_value_vi",
    }
    for source_id in PUBLIC_SOCIAL_SOURCES:
        queries = registry.get(source_id).search_queries
        assert len(queries) == 12
        assert {
            suffix
            for query in queries
            for suffix in expected_suffixes
            if query.id.endswith(suffix)
        } == expected_suffixes
        by_id = {query.id: query.query for query in queries}
        reddit = next(
            value for key, value in by_id.items() if key.endswith("reddit_review_vi")
        )
        tiktok = next(
            value
            for key, value in by_id.items()
            if key.endswith("tiktok_video_review_vi")
        )
        assert "site:reddit.com" in reddit and "inurl:/comments/" in reddit
        assert "site:tiktok.com" in tiktok and "inurl:/video/" in tiktok
        assert "-site:shop.tiktok.com" in tiktok
        assert not any(
            "mình mua" in query.query and "tích điểm" in query.query
            for query in queries
        )
        assert any(
            "kích ứng" in value and "nổi mụn" in value for value in by_id.values()
        )
        assert any(
            "giao trễ" in value and "thiếu hàng" in value for value in by_id.values()
        )
        assert any(
            "không mua lại" in value and "voucher không áp dụng" in value
            for value in by_id.values()
        )


def test_registry_requires_owner_brand_on_each_source(tmp_path: Path) -> None:
    path = tmp_path / "registry.yaml"
    path.write_text(
        """
version: test.v1
owner_brand: guardian
market_scope: vn
business_unit_scope: retail
sources:
  - source_id: missing_source_owner
    source_group: social
    source_platform: public_social
    canonical_url: https://example.com
    verified_account_ids: []
    acquisition_mode: test
    tinyfish_policy: allowed_public_fetch
    permission_status: public
    search_queries:
      - id: test_query
        query: site:example.com test
""".strip(),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="owner_brand"):
        load_source_registry(path)


def test_registry_rejects_unknown_per_source_owner(tmp_path: Path) -> None:
    path = tmp_path / "registry.yaml"
    path.write_text(
        """
version: test.v1
market_scope: vn
business_unit_scope: retail
sources:
  - source_id: invalid_owner
    owner_brand: competitor
    source_group: social
    source_platform: public_social
    canonical_url: https://example.com
    verified_account_ids: []
    acquisition_mode: test
    tinyfish_policy: allowed_public_fetch
    permission_status: public
    search_queries:
      - id: test_query
        query: site:example.com test
""".strip(),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="invalid owner_brand"):
        load_source_registry(path)
