"""TinyFish Search API adapter for the crawler's search-client protocol."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx


_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_MAX_RESULTS = 100
_MAX_QUERY_CHARS = 4_000
_TBS_DATE_RANGE = re.compile(
    r"(?:^|,)cd_min:(\d{1,2}/\d{1,2}/\d{4}),cd_max:(\d{1,2}/\d{1,2}/\d{4})(?:,|$)"
)
_SITE_OPERATOR = re.compile(r"(?<![-\w])site:([a-z0-9.-]+)", re.IGNORECASE)


def _https_endpoint(value: str) -> str:
    """Validate a configured API endpoint without resolving or contacting it."""

    raw = str(value).strip()
    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except (TypeError, ValueError) as exc:
        raise ValueError("TinyFish base URL is invalid") from exc
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise ValueError("TinyFish base URL must use HTTPS")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("TinyFish base URL cannot contain credentials, query, or fragment")
    host = parsed.hostname.encode("idna").decode("ascii").lower().rstrip(".")
    netloc = host if port in {None, 443} else f"{host}:{port}"
    path = (parsed.path or "").rstrip("/")
    return urlunsplit(("https", netloc, path, "", ""))


def _text(value: object, *, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()[:limit]


def _public_result_url(value: object) -> str | None:
    """Accept only ordinary absolute HTTP(S) result URLs without credentials."""

    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    try:
        parsed = urlsplit(raw)
        _ = parsed.port
    except (TypeError, ValueError):
        return None
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        return None
    return raw


async def _bounded_json_response(
    response: httpx.Response,
    *,
    max_bytes: int,
    provider: str,
) -> object:
    """Read a streamed JSON response without allowing unbounded buffering."""

    response.raise_for_status()
    content_length = response.headers.get("content-length")
    if content_length is not None:
        try:
            declared_length = int(content_length)
        except ValueError:
            declared_length = 0
        if declared_length > max_bytes:
            raise ValueError(f"{provider} response is too large")
    chunks: list[bytes] = []
    total = 0
    async for chunk in response.aiter_bytes():
        total += len(chunk)
        if total > max_bytes:
            raise ValueError(f"{provider} response is too large")
        chunks.append(chunk)
    try:
        return json.loads(b"".join(chunks))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{provider} response is not valid JSON") from exc


def _matches_required_site(url: str, required_sites: tuple[str, ...]) -> bool:
    if not required_sites:
        return True
    host = (urlsplit(url).hostname or "").lower().rstrip(".")
    return any(host == site or host.endswith(f".{site}") for site in required_sites)


def _tinyfish_date_bounds(tbs: str | None) -> tuple[str, str] | None:
    """Translate the crawler's explicit Google date range to TinyFish dates."""

    match = _TBS_DATE_RANGE.search(tbs or "")
    if match is None:
        return None
    try:
        after = datetime.strptime(match.group(1), "%m/%d/%Y").date().isoformat()
        before = datetime.strptime(match.group(2), "%m/%d/%Y").date().isoformat()
    except ValueError:
        return None
    return after, before


class TinyFishSearchClient:
    """Adapt TinyFish Search responses to crawler ``organic_results``.

    The API key is carried only in the ``X-API-Key`` request header. It is
    deliberately excluded from URLs, exceptions created here, and response
    metadata.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.search.tinyfish.ai",
        *,
        timeout_seconds: float = 150,
        location: str | None = None,
        language: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        key = api_key.strip()
        if not key:
            raise ValueError("TinyFish API key is required")
        if timeout_seconds <= 0:
            raise ValueError("TinyFish timeout must be greater than zero")
        self._api_key = key
        self._base_url = _https_endpoint(base_url)
        self._location = location.strip() if location and location.strip() else None
        self._language = language.strip() if language and language.strip() else None
        self._client = httpx.AsyncClient(
            timeout=timeout_seconds,
            transport=transport,
            follow_redirects=False,
        )

    async def google_search(
        self,
        *,
        query: str,
        tbs: str | None = None,
        start: int = 0,
        no_cache: bool = False,
    ) -> dict[str, Any]:
        """Run TinyFish Search and return the shape consumed by the crawler.

        TinyFish accepts absolute date bounds, so the crawler's ``tbs`` window
        is translated when present. ``no_cache`` has no TinyFish equivalent.
        """

        del no_cache
        normalized_query = query.strip()
        if not normalized_query:
            raise ValueError("TinyFish search query is required")
        if len(normalized_query) > _MAX_QUERY_CHARS:
            raise ValueError("TinyFish search query is too long")
        if start < 0:
            raise ValueError("TinyFish search start must not be negative")
        page = start // 10
        if page > 10:
            raise ValueError("TinyFish search page exceeds the API limit")

        params = {"query": normalized_query, "page": str(page)}
        if self._location is not None:
            params["location"] = self._location
        if self._language is not None:
            params["language"] = self._language
        bounds = _tinyfish_date_bounds(tbs)
        if bounds is not None:
            params["after_date"], params["before_date"] = bounds

        async with self._client.stream(
            "GET",
            self._base_url,
            params=params,
            headers={"X-API-Key": self._api_key, "Accept": "application/json"},
        ) as response:
            payload = await _bounded_json_response(
                response,
                max_bytes=_MAX_RESPONSE_BYTES,
                provider="TinyFish Search",
            )
        if not isinstance(payload, Mapping):
            raise ValueError("TinyFish Search response must be an object")
        raw_results = payload.get("results")
        if not isinstance(raw_results, list):
            raise ValueError("TinyFish Search response has no results array")

        required_sites = tuple(
            dict.fromkeys(site.lower().rstrip(".") for site in _SITE_OPERATOR.findall(query))
        )
        organic_results: list[dict[str, Any]] = []
        for index, item in enumerate(raw_results[:_MAX_RESULTS], start=1):
            if not isinstance(item, Mapping):
                continue
            link = _public_result_url(item.get("url"))
            if link is None or not _matches_required_site(link, required_sites):
                continue
            position = item.get("position")
            if not isinstance(position, int) or isinstance(position, bool) or position < 1:
                position = index
            organic = {
                "position": position,
                "title": _text(item.get("title"), limit=500),
                "snippet": _text(item.get("snippet"), limit=4_000),
                "link": link,
                "displayed_link": _text(item.get("site_name"), limit=255),
            }
            result_date = _text(item.get("date"), limit=100)
            if result_date:
                organic["date"] = result_date
            organic_results.append(organic)
        return {
            "organic_results": organic_results,
            "search_information": {"organic_results_state": "Results for exact spelling"},
        }

    async def aclose(self) -> None:
        await self._client.aclose()


class FallbackSearchClient:
    """Use a secondary search client when the preferred provider fails or is empty."""

    def __init__(self, primary: object, fallback: object | None = None) -> None:
        self.primary = primary
        self.fallback = fallback

    async def google_search(self, **kwargs: Any) -> dict[str, Any]:
        try:
            payload = await self.primary.google_search(**kwargs)  # type: ignore[attr-defined]
            results = payload.get("organic_results") if isinstance(payload, Mapping) else None
            if isinstance(results, list) and results:
                return dict(payload)
            if self.fallback is None:
                return dict(payload)
        except Exception:
            if self.fallback is None:
                raise
        return await self.fallback.google_search(**kwargs)  # type: ignore[union-attr]

    async def aclose(self) -> None:
        for client in (self.primary, self.fallback):
            closer = getattr(client, "aclose", None)
            if closer is not None:
                await closer()


__all__ = ["FallbackSearchClient", "TinyFishSearchClient"]
