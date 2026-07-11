"""Bounded public-page reader abstraction with cache and optional fallback."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

import httpx

from guardian_voc.pipeline.dedupe import canonicalize_url
from social_crawler.tinyfish import _bounded_json_response, _https_endpoint


_MAX_TINYFISH_RESPONSE_BYTES = 8 * 1024 * 1024
_MAX_TINYFISH_TEXT_CHARS = 100_000
_TINYFISH_FETCH_ERROR_CODES = {
    "target_http_error",
    "page_not_found",
    "target_unreachable",
    "timeout",
    "bot_blocked",
    "empty_content",
    "invalid_url",
    "invalid_redirect_url",
    "proxy_error",
    "conditional_unsupported",
    "fetch_error",
}


@dataclass(frozen=True)
class PageContent:
    url: str
    title: str = ""
    text: str = ""
    reader: str = ""
    metadata: dict[str, Any] | None = None


@runtime_checkable
class PageReader(Protocol):
    async def read(self, url: str, *, platform: str | None = None) -> PageContent: ...


class MetadataPageReader:
    """Use the preserved crawler's SSRF-safe metadata/browser reader."""

    def __init__(self, *, use_browser: bool = False) -> None:
        self.use_browser = use_browser

    async def read(self, url: str, *, platform: str | None = None) -> PageContent:
        canonical = canonicalize_url(url)
        if canonical is None:
            raise ValueError("invalid HTTP(S) page URL")
        from social_crawler.engine import detect_platform
        from social_crawler.scrapers import scrape_social_description

        scraped = await scrape_social_description(
            platform=platform or detect_platform(canonical),
            link=canonical,
            fallback_title=canonical,
            fallback_description="",
            use_browser=self.use_browser,
        )
        return PageContent(
            url=canonical,
            title=scraped.title,
            text=scraped.description,
            reader=scraped.source or "metadata",
        )


class CachedPageReader:
    """Concurrency-safe canonical-URL cache around any reader."""

    def __init__(self, reader: PageReader) -> None:
        self.reader = reader
        self._cache: dict[str, PageContent] = {}
        self._inflight: dict[str, asyncio.Task[PageContent]] = {}
        self._lock = asyncio.Lock()

    async def read(self, url: str, *, platform: str | None = None) -> PageContent:
        canonical = canonicalize_url(url)
        if canonical is None:
            raise ValueError("invalid HTTP(S) page URL")
        async with self._lock:
            cached = self._cache.get(canonical)
            if cached is not None:
                return cached
            task = self._inflight.get(canonical)
            if task is None:
                task = asyncio.create_task(
                    self.reader.read(canonical, platform=platform)
                )
                self._inflight[canonical] = task
        try:
            result = await task
        finally:
            async with self._lock:
                self._inflight.pop(canonical, None)
        async with self._lock:
            self._cache[canonical] = result
        return result

    def clear(self) -> None:
        self._cache.clear()


class FallbackPageReader:
    """Call an optional expensive reader only when primary text is not useful."""

    def __init__(
        self,
        primary: PageReader,
        fallback: PageReader | None,
        *,
        useful_text_chars: int = 80,
    ) -> None:
        self.primary = primary
        self.fallback = fallback
        self.useful_text_chars = useful_text_chars

    async def read(self, url: str, *, platform: str | None = None) -> PageContent:
        try:
            primary = await self.primary.read(url, platform=platform)
        except Exception:
            if self.fallback is None:
                raise
            return await self.fallback.read(url, platform=platform)
        if len(primary.text.strip()) >= self.useful_text_chars or self.fallback is None:
            return primary
        try:
            fallback = await self.fallback.read(url, platform=platform)
        except Exception:
            # Optional enrichment can never block canonical ingestion.
            return primary
        return fallback if len(fallback.text.strip()) > len(primary.text.strip()) else primary


class TinyFishPageReader:
    """Extract one public page with the official TinyFish Fetch API."""

    def __init__(
        self,
        *,
        endpoint: str,
        api_key: str,
        timeout_seconds: float = 150,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        key = api_key.strip()
        if not key:
            raise ValueError("TinyFish API key is required")
        if timeout_seconds <= 0:
            raise ValueError("TinyFish timeout must be greater than zero")
        self.endpoint = _https_endpoint(endpoint)
        self.api_key = key
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    async def read(self, url: str, *, platform: str | None = None) -> PageContent:
        canonical = canonicalize_url(url)
        if canonical is None:
            raise ValueError("invalid HTTP(S) page URL")
        # Reuse the crawler's host allowlist, DNS, credential, and port checks.
        from social_crawler.scrapers import _validate_social_url  # type: ignore[attr-defined]

        await _validate_social_url(canonical)
        async with httpx.AsyncClient(
            timeout=self.timeout_seconds,
            transport=self.transport,
            follow_redirects=False,
        ) as client:
            async with client.stream(
                "POST",
                self.endpoint,
                headers={
                    "X-API-Key": self.api_key,
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                json={"urls": [canonical], "format": "markdown"},
            ) as response:
                payload = await _bounded_json_response(
                    response,
                    max_bytes=_MAX_TINYFISH_RESPONSE_BYTES,
                    provider="TinyFish Fetch",
                )
        if not isinstance(payload, Mapping):
            raise ValueError("TinyFish Fetch response must be an object")
        results = payload.get("results")
        if not isinstance(results, list):
            raise ValueError("TinyFish Fetch response has no results array")

        selected: Mapping[str, Any] | None = None
        for item in results:
            if not isinstance(item, Mapping):
                continue
            if canonicalize_url(item.get("url")) == canonical:
                selected = item
                break
        if selected is None:
            errors = payload.get("errors")
            if isinstance(errors, list):
                for item in errors:
                    if not isinstance(item, Mapping):
                        continue
                    if canonicalize_url(item.get("url")) != canonical:
                        continue
                    error_code = item.get("error")
                    if error_code in _TINYFISH_FETCH_ERROR_CODES:
                        raise RuntimeError(f"TinyFish Fetch failed: {error_code}")
            raise ValueError("TinyFish Fetch returned no result for the requested URL")

        final_url = canonicalize_url(selected.get("final_url")) or canonical
        await _validate_social_url(final_url)
        raw_text = selected.get("text")
        raw_description = selected.get("description")
        text = raw_text if isinstance(raw_text, str) else ""
        if not text.strip() and isinstance(raw_description, str):
            text = raw_description
        raw_title = selected.get("title")
        title = raw_title if isinstance(raw_title, str) else ""
        return PageContent(
            url=canonical,
            title=title.strip()[:500],
            text=text.strip()[:_MAX_TINYFISH_TEXT_CHARS],
            reader="tinyfish",
            metadata={
                "final_url": final_url,
                "language": selected.get("language")
                if isinstance(selected.get("language"), str)
                else None,
            },
        )


__all__ = [
    "CachedPageReader",
    "FallbackPageReader",
    "MetadataPageReader",
    "PageContent",
    "PageReader",
    "TinyFishPageReader",
]
