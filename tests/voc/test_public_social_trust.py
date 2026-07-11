from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

import social_crawler.engine as engine
from guardian_voc.config import Settings
from guardian_voc.connectors.page_reader import (
    CachedPageReader,
    FallbackPageReader,
    MetadataPageReader,
    PageContent,
    TinyFishPageReader,
)
from guardian_voc.connectors.public_social import (
    LiveSocialCrawlerConnector,
    SocialCrawlerConnector,
    _safe_reader_error,
    map_social_record,
)
from guardian_voc.pipeline.dedupe import canonicalize_url
from guardian_voc.schemas.feedback import IngestionRun, IngestionRunStatus
from social_crawler.engine import CrawlResult, Mention
from social_crawler.serpapi import SerpApiClient
from social_crawler.tinyfish import FallbackSearchClient, TinyFishSearchClient


NOW = datetime(2026, 7, 11, 12, tzinfo=timezone.utc)


def _run() -> IngestionRun:
    return IngestionRun(
        id="public-social-trust",
        connector="public_social",
        source_name="social",
        status=IngestionRunStatus.RUNNING,
        started_at=NOW,
    )


def _serp_record(**overrides: Any) -> dict[str, Any]:
    record: dict[str, Any] = {
        "record_id": "serp-title-dependent-id",
        "keywords": ["guardian"],
        "platform": "Facebook",
        "title": "SERP title must remain discovery-only",
        "description": "SERP snippet must never become customer feedback",
        "link": "https://www.facebook.com/guardianvn/posts/123",
        "bucket_end": NOW.isoformat(),
        "scraper_source": "serpapi_google",
    }
    record.update(overrides)
    return record


@pytest.mark.asyncio
async def test_serp_backfill_record_is_discovery_only_without_extraction() -> None:
    record = _serp_record()

    assert map_social_record(record, observed_default=NOW) is None

    connector = SocialCrawlerConnector([record])
    items = [item async for item in connector.collect(_run())]

    assert items == []
    assert connector.discoveries == [
        {
            "crawler_record_id": "serp-title-dependent-id",
            "source_url": "https://www.facebook.com/guardianvn/posts/123",
            "platform": "facebook",
            "discovery_title": "SERP title must remain discovery-only",
            "discovery_description": "SERP snippet must never become customer feedback",
            "discovery_keywords": ["guardian"],
            "scraper_source": "serpapi_google",
            "reason": "no_explicit_page_content",
        }
    ]

    tinyfish_search = _serp_record(scraper_source="tinyfish_search")
    assert map_social_record(tinyfish_search, observed_default=NOW) is None


@pytest.mark.asyncio
async def test_explicit_extracted_text_is_the_only_feedback_content() -> None:
    connector = SocialCrawlerConnector(
        [
            _serp_record(
                extracted_text="Nội dung thật được đọc từ bài đăng.",
                extracted_title="Tiêu đề từ trang",
                extraction_source="tinyfish_fetch",
                page_reader_metadata={"final_url": "https://example.invalid/final"},
            )
        ]
    )

    items = [item async for item in connector.collect(_run())]

    assert len(items) == 1
    item = items[0]
    assert item.text == "Nội dung thật được đọc từ bài đăng."
    assert item.title == "Tiêu đề từ trang"
    assert "SERP title" not in item.text
    assert "SERP snippet" not in item.text
    assert item.metadata["content_provenance"] == {
        "kind": "page_reader",
        "source": "tinyfish_fetch",
    }
    assert item.metadata["discovery_title"] == "SERP title must remain discovery-only"
    assert item.metadata["discovery_description"].startswith("SERP snippet")
    assert item.metadata["page_reader_metadata"] == {
        "final_url": "https://example.invalid/final"
    }


@pytest.mark.asyncio
async def test_structured_page_reader_result_and_source_errors_are_preserved() -> None:
    source = {
        "errors": ["guardian (facebook): TimeoutError"],
        "mentions": [
            _serp_record(
                page_reader_result={
                    "title": "Page title",
                    "text": "Phản hồi đầy đủ từ trang nguồn.",
                    "reader": "metadata",
                    "metadata": {"http_status": 200},
                }
            )
        ],
    }
    connector = SocialCrawlerConnector(source)

    items = [item async for item in connector.collect(_run())]

    assert [item.text for item in items] == ["Phản hồi đầy đủ từ trang nguồn."]
    assert connector.errors == ["guardian (facebook): TimeoutError"]
    assert items[0].metadata["page_reader_metadata"] == {"http_status": 200}


@pytest.mark.asyncio
async def test_live_flow_prefers_tinyfish_search_and_uses_verified_reader_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    url = "https://www.facebook.com/guardianvn/posts/456"

    async def fake_crawl(**kwargs: Any) -> CrawlResult:
        captured.update(kwargs)
        page_reader = kwargs["page_reader"]
        canonical = canonicalize_url(url)
        assert canonical is not None
        page_reader.results[canonical] = PageContent(
            url=canonical,
            title="Title read from canonical page",
            text="Khách hàng phản hồi giao hàng chậm.",
            reader="tinyfish",
            metadata={"final_url": canonical},
        )
        return CrawlResult(
            bucket_start="2026-07-10T12:00:00+00:00",
            bucket_end=NOW.isoformat(),
            keywords=list(kwargs["keywords"]),
            platforms=list(kwargs["platforms"]),
            requests_made=1,
            mentions=[
                Mention(
                    record_id="serp-id",
                    keywords=["guardian"],
                    platform="Facebook",
                    title="SERP search title",
                    description="SERP search snippet",
                    link=url,
                    published_date=None,
                    scraper_source="serpapi_google",
                    bucket_start="2026-07-10T12:00:00+00:00",
                    bucket_end=NOW.isoformat(),
                )
            ],
            errors=["another query (facebook): TimeoutError"],
        )

    monkeypatch.setattr(engine, "crawl", fake_crawl)
    settings = Settings(
        serp_api_key="serp-test-key",
        tinyfish_enabled=True,
        tinyfish_api_key="tinyfish-test-key",
        crawler_keywords=("guardian",),
        crawler_platforms=("facebook",),
        tinyfish_useful_text_chars=123,
    )
    connector = LiveSocialCrawlerConnector(settings=settings)

    items = [item async for item in connector.collect(_run())]

    assert captured["api_key"] == ""
    search_client = captured["search_client"]
    assert isinstance(search_client, FallbackSearchClient)
    assert isinstance(search_client.primary, TinyFishSearchClient)
    assert isinstance(search_client.fallback, SerpApiClient)
    page_reader = captured["page_reader"]
    assert isinstance(page_reader, CachedPageReader)
    assert isinstance(page_reader.reader, FallbackPageReader)
    assert isinstance(page_reader.reader.primary, MetadataPageReader)
    assert isinstance(page_reader.reader.fallback, TinyFishPageReader)
    assert page_reader.reader.useful_text_chars == 123
    assert [item.text for item in items] == ["Khách hàng phản hồi giao hàng chậm."]
    assert items[0].title == "Title read from canonical page"
    assert "SERP search" not in items[0].text
    assert connector.errors == ["another query (facebook): TimeoutError"]


@pytest.mark.asyncio
async def test_live_flow_allows_tinyfish_without_serpapi(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    async def fake_crawl(**kwargs: Any) -> CrawlResult:
        captured.update(kwargs)
        return CrawlResult(
            bucket_start="2026-07-10T12:00:00+00:00",
            bucket_end=NOW.isoformat(),
            keywords=list(kwargs["keywords"]),
            platforms=list(kwargs["platforms"]),
            requests_made=0,
        )

    monkeypatch.setattr(engine, "crawl", fake_crawl)
    connector = LiveSocialCrawlerConnector(
        settings=Settings(
            serp_api_key="",
            tinyfish_enabled=True,
            tinyfish_api_key="tinyfish-test-key",
        )
    )

    assert [item async for item in connector.collect(_run())] == []
    search_client = captured["search_client"]
    assert isinstance(search_client, FallbackSearchClient)
    assert isinstance(search_client.primary, TinyFishSearchClient)
    assert search_client.fallback is None
    assert captured["api_key"] == ""
    assert search_client.primary._client.is_closed


@pytest.mark.asyncio
async def test_live_flow_uses_serpapi_when_tinyfish_is_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    async def fake_crawl(**kwargs: Any) -> CrawlResult:
        captured.update(kwargs)
        return CrawlResult(
            bucket_start="2026-07-10T12:00:00+00:00",
            bucket_end=NOW.isoformat(),
            keywords=list(kwargs["keywords"]),
            platforms=list(kwargs["platforms"]),
            requests_made=0,
        )

    monkeypatch.setattr(engine, "crawl", fake_crawl)
    connector = LiveSocialCrawlerConnector(
        settings=Settings(
            serp_api_key="serp-test-key",
            tinyfish_enabled=False,
            tinyfish_api_key="",
        )
    )

    assert [item async for item in connector.collect(_run())] == []
    assert captured["search_client"] is None
    assert captured["api_key"] == "serp-test-key"
    page_reader = captured["page_reader"]
    assert isinstance(page_reader, CachedPageReader)
    assert isinstance(page_reader.reader, FallbackPageReader)
    assert page_reader.reader.fallback is None


@pytest.mark.asyncio
async def test_live_flow_requires_at_least_one_search_provider() -> None:
    connector = LiveSocialCrawlerConnector(
        settings=Settings(
            serp_api_key="",
            tinyfish_enabled=False,
            tinyfish_api_key="",
        )
    )

    with pytest.raises(RuntimeError, match="Enable TinyFish"):
        _ = [item async for item in connector.collect(_run())]


def test_reader_errors_expose_only_platform_hash_and_exception_type() -> None:
    url = "https://facebook.com/customer/posts/7?access_token=do-not-leak"
    error = RuntimeError("provider-key-do-not-leak")

    first = _safe_reader_error(
        "tinyfish_reader", url, error, platform="Facebook"
    )
    second = _safe_reader_error(
        "tinyfish_reader", url, error, platform="Facebook"
    )

    assert first == second
    assert first.startswith("tinyfish_reader facebook target-")
    assert first.endswith(": RuntimeError")
    assert "facebook.com" not in first
    assert "access_token" not in first
    assert "do-not-leak" not in first
    assert "provider-key" not in first
