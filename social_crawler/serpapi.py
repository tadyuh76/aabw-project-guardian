from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

import httpx


# SerpAPI authenticates with a query parameter. HTTPX's INFO request log would
# otherwise print the full URL and leak that credential.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


class SerpApiClient:
    def __init__(self, api_key: str, base_url: str = "https://serpapi.com") -> None:
        self._api_key = api_key
        self._client = httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=60)

    async def google_search(
        self,
        *,
        query: str,
        tbs: str | None = None,
        start: int = 0,
        no_cache: bool = False,
        google_domain: str | None = None,
        gl: str | None = None,
        hl: str | None = None,
        lr: str | None = None,
        filter_similar: bool | None = None,
        nfpr: bool | None = None,
    ) -> dict[str, Any]:
        params: dict[str, str] = {
            "engine": "google",
            "q": query,
            "device": "desktop",
            "no_cache": str(no_cache).lower(),
            "api_key": self._api_key,
            "start": str(start),
        }
        if tbs:
            params["tbs"] = tbs
        if google_domain:
            params["google_domain"] = google_domain
        if gl:
            params["gl"] = gl
        if hl:
            params["hl"] = hl
        if lr:
            params["lr"] = lr
        if filter_similar is not None:
            params["filter"] = "1" if filter_similar else "0"
        if nfpr is not None:
            params["nfpr"] = "1" if nfpr else "0"
        response = await self._client.get("/search.json", params=params)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("SerpAPI returned a non-object response")
        if payload.get("error"):
            raise ValueError("SerpAPI returned an error payload")
        return payload

    async def account(self) -> dict[str, Any]:
        """Return quota metadata without exposing the API key."""

        response = await self._client.get("/account.json", params={"api_key": self._api_key})
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("SerpAPI returned a non-object account response")
        return payload

    async def aclose(self) -> None:
        await self._client.aclose()


def has_valid_organic_results(result: dict[str, Any]) -> bool:
    """Reject relaxed or spelling-corrected results returned by Google."""
    info = result.get("search_information") or {}
    state = str(info.get("organic_results_state") or "").lower()
    if "empty" in state:
        return False
    return not bool(info.get("spelling_fix"))


def filter_organic_results_by_domains(
    organic_results: list[dict[str, Any]],
    domains: list[str],
) -> list[dict[str, Any]]:
    """Keep only results whose host belongs to an explicitly requested domain."""
    if not organic_results or not domains:
        return organic_results

    allowed = [domain.lower() for domain in domains]
    kept: list[dict[str, Any]] = []
    for result in organic_results:
        if not isinstance(result, dict):
            continue
        link = str(result.get("link") or "")
        try:
            host = urlparse(link).netloc.lower().removeprefix("www.")
        except Exception:
            continue
        if any(host == domain or host.endswith("." + domain) for domain in allowed):
            kept.append(result)
    return kept
