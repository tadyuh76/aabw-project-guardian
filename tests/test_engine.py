from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import pytest

import social_crawler.engine as engine
from social_crawler.scrapers import ScrapedMention


class FakeSearchClient:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.calls: list[dict[str, Any]] = []

    async def google_search(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return self.payload


class FailingSearchClient:
    async def google_search(self, **_: Any) -> dict[str, Any]:
        raise RuntimeError("must-not-appear-in-output")


class ConcurrencyTrackingClient:
    def __init__(self) -> None:
        self.active = 0
        self.maximum = 0

    async def google_search(self, **_: Any) -> dict[str, Any]:
        self.active += 1
        self.maximum = max(self.maximum, self.active)
        await asyncio.sleep(0.01)
        self.active -= 1
        return {"search_information": {}, "organic_results": []}


def test_build_crawl_plan_creates_timed_and_untimed_requests() -> None:
    end = datetime(2026, 7, 11, 12, 0, tzinfo=timezone.utc)
    start = datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc)

    plans = engine.build_crawl_plan(
        ["CyPeace"],
        ["facebook", "telegram"],
        bucket_start=start,
        bucket_end=end,
    )

    assert [plan.pool for plan in plans] == ["timed", "untimed"]
    assert plans[0].query == '"cypeace" (site:facebook.com)'
    assert plans[0].tbs == "cdr:1,cd_min:7/10/2026,cd_max:7/11/2026,sbd:1"
    assert plans[1].tbs is None


def test_crawl_merges_duplicate_mentions_across_keywords(monkeypatch: Any) -> None:
    payload = {
        "search_information": {},
        "organic_results": [
            {
                "link": "https://www.facebook.com/example/posts/123",
                "title": "Original title",
                "snippet": "Original snippet",
                "date": "1 hour ago",
            }
        ],
    }
    client = FakeSearchClient(payload)

    async def fake_scrape(**_: Any) -> ScrapedMention:
        return ScrapedMention(
            title="Enriched title",
            description="Enriched description",
            source="metadata",
        )

    monkeypatch.setattr(engine, "scrape_social_description", fake_scrape)
    result = asyncio.run(
        engine.crawl(
            api_key="unused",
            api_base_url="https://example.test",
            keywords=["First Brand", "Second Brand"],
            platforms=["facebook", "telegram"],
            bucket_end=datetime(2026, 7, 11, 12, 0, tzinfo=timezone.utc),
            search_client=client,
            use_browser=False,
        )
    )

    assert result.requests_made == 4
    assert len(client.calls) == 4
    assert len(result.mentions) == 1
    assert result.mentions[0].keywords == ["first brand", "second brand"]
    assert result.mentions[0].scraper_source == "metadata"


def test_crawl_errors_do_not_echo_exception_details() -> None:
    result = asyncio.run(
        engine.crawl(
            api_key="unused",
            api_base_url="https://example.test",
            keywords=["Example Brand"],
            platforms=["facebook"],
            search_client=FailingSearchClient(),
            use_browser=False,
        )
    )

    assert result.errors == ["example brand (timed): RuntimeError"]


def test_keyword_normalization_matches_api_and_syntax() -> None:
    assert engine.normalize_keyword_value("Brand AND Scam") == '"brand" "scam"'
    assert engine.normalize_keyword_value("Brand & Scam") == '"brand" "scam"'
    assert engine.normalize_keyword_value('"Brand" "Scam"') == '"brand" "scam"'

    end = datetime(2026, 7, 11, 12, 0, tzinfo=timezone.utc)
    plans = engine.build_crawl_plan(
        ["Brand AND Scam"],
        ["facebook"],
        bucket_start=end,
        bucket_end=end,
    )
    assert plans[0].query == '"brand" "scam" (site:facebook.com)'


def test_search_concurrency_is_bounded() -> None:
    client = ConcurrencyTrackingClient()
    asyncio.run(
        engine.crawl(
            api_key="unused",
            api_base_url="https://example.test",
            keywords=["one", "two", "three", "four", "five"],
            platforms=["facebook"],
            search_client=client,
            search_concurrency=2,
            use_browser=False,
        )
    )

    assert client.maximum == 2


def test_keyword_input_limits_match_source_api() -> None:
    with pytest.raises(ValueError, match="maximum of 20"):
        engine.normalize_keywords([f"keyword-{index}" for index in range(21)])
    with pytest.raises(ValueError, match="500 characters"):
        engine.normalize_keywords(["x" * 501])
