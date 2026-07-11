from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

import guardian_voc.application as application
import social_crawler.engine as engine
import social_crawler.scrapers as scrapers
from guardian_voc.application import GuardianService
from guardian_voc.config import Settings
from guardian_voc.connectors.page_reader import (
    CachedPageReader,
    FallbackPageReader,
    MetadataPageReader,
    PageContent,
    TinyFishPageReader,
)
from guardian_voc.connectors.public_social import LiveSocialCrawlerConnector
from guardian_voc.schemas.feedback import IngestionRun, IngestionRunStatus
from social_crawler.engine import CrawlResult
from social_crawler.serpapi import SerpApiClient
from social_crawler.tinyfish import FallbackSearchClient, TinyFishSearchClient


NOW = datetime(2026, 7, 11, 12, tzinfo=timezone.utc)
TEST_KEY = "tinyfish-test-credential"
SEARCH_ENDPOINT = "https://api.search.tinyfish.ai"
FETCH_ENDPOINT = "https://api.fetch.tinyfish.ai"


async def _allow_public_test_url(_: str) -> None:
    """Keep connector tests deterministic; URL validation itself has its own suite."""


class StubReader:
    def __init__(
        self,
        content: PageContent | None = None,
        error: Exception | None = None,
    ) -> None:
        self.content = content
        self.error = error
        self.calls: list[tuple[str, str | None]] = []

    async def read(self, url: str, *, platform: str | None = None) -> PageContent:
        self.calls.append((url, platform))
        if self.error is not None:
            raise self.error
        assert self.content is not None
        return self.content


class StubSearchClient:
    def __init__(
        self,
        payload: dict[str, Any] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.payload = payload
        self.error = error
        self.calls: list[dict[str, Any]] = []
        self.closed = False

    async def google_search(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        assert self.payload is not None
        return self.payload

    async def aclose(self) -> None:
        self.closed = True


def _run() -> IngestionRun:
    return IngestionRun(
        id="tinyfish-run",
        connector="public_social",
        source_name="social",
        status=IngestionRunStatus.RUNNING,
        started_at=NOW,
    )


def test_tinyfish_configuration_fails_closed_and_uses_official_https_endpoints() -> None:
    disabled = Settings(tinyfish_enabled=False, tinyfish_api_key="")
    assert disabled.tinyfish_search_base_url == SEARCH_ENDPOINT
    assert disabled.tinyfish_fetch_base_url == FETCH_ENDPOINT

    with pytest.raises(ValidationError, match="TINYFISH_API_KEY"):
        Settings(tinyfish_enabled=True, tinyfish_api_key="")

    for field in ("tinyfish_search_base_url", "tinyfish_fetch_base_url"):
        with pytest.raises(ValidationError, match="HTTPS"):
            Settings(
                tinyfish_enabled=True,
                tinyfish_api_key=TEST_KEY,
                **{field: "http://tinyfish.invalid"},
            )

    enabled = Settings(
        tinyfish_enabled=True,
        tinyfish_api_key=f"  {TEST_KEY}  ",
        serp_api_key="",
    )
    assert enabled.tinyfish_api_key == TEST_KEY
    assert enabled.serp_api_key == ""
    assert enabled.tinyfish_location == "VN"
    assert enabled.tinyfish_language == "vi"
    assert "tinyfish_api_key" not in enabled.model_dump()
    assert TEST_KEY not in repr(enabled)


@pytest.mark.asyncio
async def test_search_client_uses_get_query_and_x_api_key_and_adapts_results() -> None:
    requests: list[httpx.Request] = []
    query = '"guardian" (site:facebook.com)'

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "query": query,
                "results": [
                    {
                        "position": 1,
                        "site_name": "facebook.com",
                        "title": "Guardian promotion discussion",
                        "snippet": "Customers discuss a promotion that did not apply.",
                        "url": "https://www.facebook.com/example/posts/123",
                        "date": "2026-07-10",
                    }
                ],
                "total_results": 1,
                "page": 2,
            },
        )

    client = TinyFishSearchClient(
        api_key=TEST_KEY,
        base_url=SEARCH_ENDPOINT,
        location="VN",
        language="vi",
        transport=httpx.MockTransport(handler),
    )
    try:
        payload = await client.google_search(
            query=query,
            tbs="cdr:1,cd_min:7/10/2026,cd_max:7/11/2026,sbd:1",
            start=20,
            no_cache=True,
        )
    finally:
        await client.aclose()

    assert len(requests) == 1
    request = requests[0]
    assert request.method == "GET"
    assert request.url.copy_with(query=None) == httpx.URL(SEARCH_ENDPOINT)
    assert dict(request.url.params) == {
        "query": query,
        "page": "2",
        "location": "VN",
        "language": "vi",
        "after_date": "2026-07-10",
        "before_date": "2026-07-11",
    }
    assert request.headers["X-API-Key"] == TEST_KEY
    assert "authorization" not in request.headers
    assert request.content == b""
    assert TEST_KEY not in str(request.url)

    organic = payload["organic_results"]
    assert len(organic) == 1
    assert organic[0]["position"] == 1
    assert organic[0]["title"] == "Guardian promotion discussion"
    assert organic[0]["snippet"] == "Customers discuss a promotion that did not apply."
    assert organic[0]["link"] == "https://www.facebook.com/example/posts/123"
    assert organic[0]["date"] == "2026-07-10"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response_payload",
    [
        pytest.param([{"title": "not an object"}], id="non-object"),
        pytest.param({"query": "x", "results": {}}, id="results-not-an-array"),
    ],
)
async def test_search_client_rejects_malformed_response_shapes(
    response_payload: object,
) -> None:
    transport = httpx.MockTransport(
        lambda _: httpx.Response(200, json=response_payload)
    )
    client = TinyFishSearchClient(
        api_key=TEST_KEY,
        base_url=SEARCH_ENDPOINT,
        transport=transport,
    )
    try:
        with pytest.raises(ValueError, match="TinyFish"):
            await client.google_search(query="guardian")
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_search_stream_rejects_declared_oversized_response() -> None:
    transport = httpx.MockTransport(
        lambda _: httpx.Response(
            200,
            headers={"content-length": str(3 * 1024 * 1024)},
            content=b"{}",
        )
    )
    client = TinyFishSearchClient(api_key=TEST_KEY, transport=transport)
    try:
        with pytest.raises(ValueError, match="too large"):
            await client.google_search(query="guardian")
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_search_fallback_uses_primary_then_falls_back_on_empty_or_failure() -> None:
    expected = {
        "search_information": {},
        "organic_results": [{"link": "https://facebook.com/post/1"}],
    }
    preferred = StubSearchClient(expected)
    fallback = StubSearchClient(
        error=AssertionError("fallback must not run when primary has results")
    )
    client = FallbackSearchClient(preferred, fallback)
    assert await client.google_search(query="guardian") == expected
    assert len(preferred.calls) == 1
    assert fallback.calls == []

    for primary in (
        StubSearchClient({"search_information": {}, "organic_results": []}),
        StubSearchClient(error=httpx.ReadTimeout("provider timed out")),
    ):
        secondary = StubSearchClient(expected)
        client = FallbackSearchClient(primary, secondary)
        assert await client.google_search(query="guardian") == expected
        assert len(secondary.calls) == 1
        await client.aclose()
        assert primary.closed is True
        assert secondary.closed is True


@pytest.mark.asyncio
async def test_out_of_scope_search_results_trigger_fallback() -> None:
    transport = httpx.MockTransport(
        lambda _: httpx.Response(
            200,
            json={
                "query": "guardian site:facebook.com",
                "results": [
                    {
                        "position": 1,
                        "site_name": "example.com",
                        "title": "Out of scope",
                        "snippet": "Not a requested social domain",
                        "url": "https://example.com/not-social",
                    }
                ],
                "total_results": 1,
                "page": 0,
            },
        )
    )
    primary = TinyFishSearchClient(api_key=TEST_KEY, transport=transport)
    expected = {
        "search_information": {},
        "organic_results": [{"link": "https://facebook.com/post/1"}],
    }
    fallback = StubSearchClient(expected)
    client = FallbackSearchClient(primary, fallback)
    try:
        assert await client.google_search(query="guardian site:facebook.com") == expected
    finally:
        await client.aclose()
    assert len(fallback.calls) == 1


@pytest.mark.asyncio
async def test_page_reader_uses_fetch_contract_and_parses_extracted_markdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(scrapers, "_validate_social_url", _allow_public_test_url)
    requests: list[httpx.Request] = []
    input_url = "https://www.facebook.com/example/posts/123?utm_source=test#comments"
    canonical = "https://facebook.com/example/posts/123"

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "url": canonical,
                        "final_url": canonical,
                        "title": "Guardian delivery review",
                        "description": "Public post",
                        "language": "vi",
                        "format": "markdown",
                        "text": "# Review\n\nĐơn hàng của tôi bị hủy vì hết hàng.",
                    }
                ],
                "errors": [],
            },
        )

    reader = TinyFishPageReader(
        endpoint=FETCH_ENDPOINT,
        api_key=TEST_KEY,
        transport=httpx.MockTransport(handler),
    )
    result = await reader.read(input_url, platform="Facebook")

    assert len(requests) == 1
    request = requests[0]
    assert request.method == "POST"
    assert request.url == httpx.URL(FETCH_ENDPOINT)
    assert request.headers["X-API-Key"] == TEST_KEY
    assert "authorization" not in request.headers
    assert json.loads(request.content) == {
        "urls": [canonical],
        "format": "markdown",
    }
    assert TEST_KEY not in request.content.decode("utf-8")
    assert result == PageContent(
        url=canonical,
        title="Guardian delivery review",
        text="# Review\n\nĐơn hàng của tôi bị hủy vì hết hàng.",
        reader="tinyfish",
        metadata=result.metadata,
    )
    assert result.metadata == {"final_url": canonical, "language": "vi"}


@pytest.mark.asyncio
@pytest.mark.parametrize("error_code", ["bot_blocked", "fetch_error"])
async def test_page_reader_parses_per_url_fetch_errors(
    monkeypatch: pytest.MonkeyPatch,
    error_code: str,
) -> None:
    monkeypatch.setattr(scrapers, "_validate_social_url", _allow_public_test_url)
    canonical = "https://facebook.com/example/posts/blocked"
    transport = httpx.MockTransport(
        lambda _: httpx.Response(
            200,
            json={
                "results": [],
                "errors": [{"url": canonical, "error": error_code}],
            },
        )
    )
    reader = TinyFishPageReader(
        endpoint=FETCH_ENDPOINT,
        api_key=TEST_KEY,
        transport=transport,
    )

    with pytest.raises(RuntimeError, match=error_code):
        await reader.read(canonical)


@pytest.mark.asyncio
async def test_fetch_stream_rejects_declared_oversized_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(scrapers, "_validate_social_url", _allow_public_test_url)
    transport = httpx.MockTransport(
        lambda _: httpx.Response(
            200,
            headers={"content-length": str(9 * 1024 * 1024)},
            content=b"{}",
        )
    )
    reader = TinyFishPageReader(
        endpoint=FETCH_ENDPOINT,
        api_key=TEST_KEY,
        transport=transport,
    )
    with pytest.raises(ValueError, match="too large"):
        await reader.read("https://facebook.com/example/posts/oversized")


@pytest.mark.asyncio
async def test_metadata_is_primary_and_tinyfish_is_only_a_nonblocking_fallback() -> None:
    useful_primary = StubReader(
        PageContent(
            url="https://facebook.com/post/1",
            title="Metadata title",
            text="M" * 100,
            reader="metadata",
        )
    )
    unused_fallback = StubReader(
        error=AssertionError("fallback must not run for useful metadata")
    )
    reader = FallbackPageReader(useful_primary, unused_fallback, useful_text_chars=80)
    result = await reader.read("https://facebook.com/post/1")
    assert result.reader == "metadata"
    assert unused_fallback.calls == []

    short_primary = StubReader(
        PageContent(
            url="https://facebook.com/post/2",
            title="Generic metadata",
            text="Log in",
            reader="metadata",
        )
    )
    rich_fallback = StubReader(
        PageContent(
            url="https://facebook.com/post/2",
            title="Rendered post",
            text="Full rendered customer feedback " * 8,
            reader="tinyfish",
        )
    )
    reader = FallbackPageReader(short_primary, rich_fallback, useful_text_chars=80)
    result = await reader.read("https://facebook.com/post/2")
    assert result.reader == "tinyfish"
    assert len(rich_fallback.calls) == 1

    failed_fallback = StubReader(error=httpx.ReadTimeout("fetch timed out"))
    reader = FallbackPageReader(short_primary, failed_fallback, useful_text_chars=80)
    result = await reader.read("https://facebook.com/post/2")
    assert result.reader == "metadata"


@pytest.mark.asyncio
async def test_api_key_never_appears_in_http_logs_or_fallback_errors(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(scrapers, "_validate_social_url", _allow_public_test_url)
    primary = StubReader(
        PageContent(
            url="https://facebook.com/post/3",
            text="Login",
            reader="metadata",
        )
    )
    transport = httpx.MockTransport(
        lambda _: httpx.Response(
            401,
            json={"error": {"code": "INVALID_API_KEY", "message": "invalid key"}},
        )
    )
    tinyfish = TinyFishPageReader(
        endpoint=FETCH_ENDPOINT,
        api_key=TEST_KEY,
        transport=transport,
    )

    caplog.set_level(logging.DEBUG)
    result = await FallbackPageReader(primary, tinyfish).read(
        "https://facebook.com/post/3"
    )

    assert result.reader == "metadata"
    assert TEST_KEY not in caplog.text


@pytest.mark.asyncio
async def test_crawl_uses_injected_page_reader_and_preserves_discovery_keyword() -> None:
    search = StubSearchClient(
        {
            "search_information": {},
            "organic_results": [
                {
                    "position": 1,
                    "title": "Search result title",
                    "snippet": "Short search result snippet",
                    "link": "https://www.facebook.com/example/posts/456",
                }
            ],
        }
    )
    page_reader = StubReader(
        PageContent(
            url="https://facebook.com/example/posts/456",
            title="Fetched title",
            text="Fetched full customer feedback",
            reader="tinyfish",
        )
    )

    result = await engine.crawl(
        api_key="",
        api_base_url="https://serpapi.invalid",
        keywords=["Guardian Flash Sale"],
        platforms=["facebook"],
        bucket_end=NOW,
        search_client=search,
        page_reader=page_reader,
        use_browser=False,
    )

    assert len(page_reader.calls) == 1
    assert len(result.mentions) == 1
    mention = result.mentions[0]
    assert mention.title == "Fetched title"
    assert mention.description == "Fetched full customer feedback"
    assert mention.scraper_source == "tinyfish"
    assert mention.keywords == ["guardian flash sale"]


@pytest.mark.asyncio
async def test_live_connector_prefers_tinyfish_search_with_serpapi_fallback_and_closes_both(
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
    settings = Settings(
        tinyfish_enabled=True,
        tinyfish_api_key=TEST_KEY,
        serp_api_key="serp-test-credential",
        crawler_keywords=("configured default",),
        crawler_platforms=("facebook",),
        tinyfish_useful_text_chars=123,
    )
    connector = LiveSocialCrawlerConnector(
        settings=settings,
        keywords=("requested campaign",),
    )

    items = [item async for item in connector.collect(_run())]

    assert items == []
    assert captured["keywords"] == ["requested campaign"]
    search_client = captured["search_client"]
    assert isinstance(search_client, FallbackSearchClient)
    assert isinstance(search_client.primary, TinyFishSearchClient)
    assert isinstance(search_client.fallback, SerpApiClient)
    assert captured["api_key"] == ""
    assert search_client.primary._client.is_closed
    assert search_client.fallback._client.is_closed

    page_reader = captured["page_reader"]
    assert isinstance(page_reader, CachedPageReader)
    assert isinstance(page_reader.reader, FallbackPageReader)
    assert isinstance(page_reader.reader.primary, MetadataPageReader)
    assert isinstance(page_reader.reader.fallback, TinyFishPageReader)
    assert page_reader.reader.useful_text_chars == 123
    assert page_reader.reader.fallback.endpoint == FETCH_ENDPOINT


@pytest.mark.asyncio
async def test_live_connector_closes_injected_search_clients_when_crawl_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    async def fake_crawl(**kwargs: Any) -> CrawlResult:
        captured.update(kwargs)
        raise RuntimeError("crawl failed")

    monkeypatch.setattr(engine, "crawl", fake_crawl)
    connector = LiveSocialCrawlerConnector(
        settings=Settings(
            tinyfish_enabled=True,
            tinyfish_api_key=TEST_KEY,
            serp_api_key="serp-test-credential",
            crawler_keywords=("guardian",),
            crawler_platforms=("facebook",),
        )
    )

    with pytest.raises(RuntimeError, match="crawl failed"):
        _ = [item async for item in connector.collect(_run())]

    search_client = captured["search_client"]
    assert isinstance(search_client, FallbackSearchClient)
    assert isinstance(search_client.primary, TinyFishSearchClient)
    assert isinstance(search_client.fallback, SerpApiClient)
    assert search_client.primary._client.is_closed
    assert search_client.fallback._client.is_closed


def test_guardian_service_propagates_manual_crawl_keyword(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    class FakeLiveConnector:
        def __init__(self, *, settings: Settings, keywords: tuple[str, ...]) -> None:
            captured["settings"] = settings
            captured["keywords"] = keywords

    async def fake_ingest_connector(
        _connector: object,
        **_: Any,
    ) -> IngestionRun:
        return IngestionRun(
            id="ingestion-run",
            connector="public_social",
            source_name="social_requested campaign",
            status=IngestionRunStatus.COMPLETED,
            started_at=NOW,
            completed_at=NOW,
        )

    settings = Settings(
        voc_db_path=tmp_path / "guardian.duckdb",
        voc_data_dir=tmp_path,
        voc_inbox_dir=tmp_path / "inbox",
        tinyfish_enabled=True,
        tinyfish_api_key=TEST_KEY,
        serp_api_key="serp-test-credential",
    )
    service = GuardianService(settings)
    monkeypatch.setattr(application, "LiveSocialCrawlerConnector", FakeLiveConnector)
    monkeypatch.setattr(service.repository, "ingest_connector", fake_ingest_connector)
    monkeypatch.setattr(
        service,
        "_execute_pipeline",
        lambda *, trigger, ingest: ingest(),
    )
    try:
        service.crawl(keyword="requested campaign")
    finally:
        service.close()

    assert captured["keywords"] == ("requested campaign",)
