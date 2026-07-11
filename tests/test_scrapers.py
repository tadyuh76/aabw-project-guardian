import asyncio

import httpx
import pytest

import social_crawler.scrapers as scrapers
from social_crawler.scrapers import (
    _parse_metadata,
    _validate_social_url_sync,
    clean_text,
)


def test_parses_open_graph_description() -> None:
    result = _parse_metadata(
        """
        <html>
          <head>
            <title>Brand post</title>
            <meta property="og:description"
                  content="A sufficiently detailed public social post description for testing." />
          </head>
        </html>
        """
    )

    assert result.title == "Brand post"
    assert result.description.startswith("A sufficiently detailed")
    assert result.source == "metadata"


def test_clean_text_removes_markup_and_whitespace() -> None:
    assert clean_text("  Hello <b>social</b>\n listening  ") == "Hello social listening"


@pytest.mark.parametrize(
    "url",
    (
        "file:///etc/passwd",
        "http://127.0.0.1/internal",
        "http://facebook.com:8080/internal",
        "https://example.com/not-social",
        "https://user:pass@facebook.com/private",
    ),
)
def test_rejects_unsafe_scraper_urls(url: str) -> None:
    with pytest.raises(ValueError):
        _validate_social_url_sync(url)


def test_safe_get_revalidates_redirect_targets(monkeypatch) -> None:
    validated: list[str] = []

    async def fake_validate(url: str) -> None:
        validated.append(url)
        if url.startswith("http://127.0.0.1"):
            raise ValueError("blocked")

    monkeypatch.setattr(scrapers, "_validate_social_url", fake_validate)
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            302,
            headers={"location": "http://127.0.0.1/internal"},
            request=request,
        )
    )

    async def run() -> None:
        async with httpx.AsyncClient(transport=transport) as client:
            with pytest.raises(ValueError, match="blocked"):
                await scrapers._safe_get(client, "https://facebook.com/post")

    asyncio.run(run())
    assert validated == [
        "https://facebook.com/post",
        "http://127.0.0.1/internal",
    ]
