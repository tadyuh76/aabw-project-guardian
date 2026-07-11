"""Verified Guardian source/account registry for live acquisition.

Display names discovered on the web are never trusted as ownership evidence.
Only entries curated in the versioned registry may set ``source_owner_brand``.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

import yaml


REGISTRY_PATH = Path(__file__).with_name("taxonomy") / "source_registry_v1.yaml"


@dataclass(frozen=True)
class SearchQuery:
    id: str
    query: str


@dataclass(frozen=True)
class SourceDefinition:
    source_id: str
    source_group: str
    source_platform: str
    owner_brand: str
    default_crawl: bool
    market_scope: str
    business_unit_scope: str
    canonical_url: str
    verified_account_ids: tuple[str, ...]
    acquisition_mode: str
    tinyfish_policy: str
    permission_status: str
    blocked_paths: tuple[str, ...]
    search_queries: tuple[SearchQuery, ...]

    @property
    def canonical_host(self) -> str:
        return (urlsplit(self.canonical_url).hostname or "").lower().removeprefix("www.")

    def host_allowed(self, url: str) -> bool:
        host = (urlsplit(url).hostname or "").lower().removeprefix("www.")
        if self.source_platform == "public_social":
            return any(
                host == domain or host.endswith("." + domain)
                for domain in (
                    "facebook.com",
                    "instagram.com",
                    "threads.com",
                    "threads.net",
                    "tiktok.com",
                    "youtube.com",
                    "reddit.com",
                )
            )
        return host == self.canonical_host or host.endswith("." + self.canonical_host)

    def blocked_path(self, url: str) -> bool:
        # Match both the blocked root and its descendants.  A registry entry
        # written as ``/review/`` must also block ``/review``.  Decode escaped
        # path bytes before matching so ``/%72eview`` cannot bypass policy.
        path = unquote(urlsplit(url).path).lower().rstrip("/") or "/"
        for item in self.blocked_paths:
            blocked = unquote(item).lower().rstrip("/") or "/"
            if path == blocked or path.startswith(blocked + "/"):
                return True
        return False

    @property
    def tinyfish_fetch_allowed(self) -> bool:
        return self.tinyfish_policy in {
            "allowed_public_catalog_only",
            "allowed_public_enrichment_only",
            "allowed_public_fetch",
        }


@dataclass(frozen=True)
class SourceRegistry:
    version: str
    sources: tuple[SourceDefinition, ...]
    excluded_sources: tuple[SourceDefinition, ...] = ()

    @property
    def all_sources(self) -> tuple[SourceDefinition, ...]:
        """Return crawlable and explicitly excluded source definitions."""

        return (*self.sources, *self.excluded_sources)

    def get(self, source_id: str) -> SourceDefinition:
        for source in self.all_sources:
            if source.source_id == source_id:
                return source
        raise KeyError(source_id)


def _required_text(raw: dict[str, Any], key: str) -> str:
    value = str(raw.get(key) or "").strip()
    if not value:
        raise ValueError(f"source registry field {key!r} is required")
    return value


def _optional_bool(raw: dict[str, Any], key: str, *, default: bool) -> bool:
    value = raw.get(key, default)
    if not isinstance(value, bool):
        raise ValueError(f"source registry field {key!r} must be a boolean")
    return value


@lru_cache(maxsize=1)
def load_source_registry(path: str | Path = REGISTRY_PATH) -> SourceRegistry:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("source registry must be a YAML object")
    version = _required_text(payload, "version")
    market_scope = _required_text(payload, "market_scope")
    business_unit_scope = _required_text(payload, "business_unit_scope")
    sources: list[SourceDefinition] = []
    seen: set[str] = set()
    for raw_source in payload.get("sources") or []:
        if not isinstance(raw_source, dict):
            raise ValueError("source registry entries must be objects")
        source_id = _required_text(raw_source, "source_id")
        if source_id in seen:
            raise ValueError(f"duplicate source registry id: {source_id}")
        seen.add(source_id)
        owner_brand = _required_text(raw_source, "owner_brand").lower()
        if owner_brand not in {"guardian", "hasaki", "watsons", "other"}:
            raise ValueError(
                f"invalid owner_brand for {source_id}: {owner_brand!r}"
            )
        canonical_url = _required_text(raw_source, "canonical_url")
        parsed = urlsplit(canonical_url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError(f"invalid canonical source URL for {source_id}")
        queries: list[SearchQuery] = []
        query_ids: set[str] = set()
        for raw_query in raw_source.get("search_queries") or []:
            if not isinstance(raw_query, dict):
                raise ValueError(f"invalid query entry for {source_id}")
            query = SearchQuery(
                id=_required_text(raw_query, "id"),
                query=_required_text(raw_query, "query"),
            )
            if query.id in query_ids:
                raise ValueError(f"duplicate query id for {source_id}: {query.id}")
            query_ids.add(query.id)
            queries.append(query)
        sources.append(
            SourceDefinition(
                source_id=source_id,
                source_group=_required_text(raw_source, "source_group"),
                source_platform=_required_text(raw_source, "source_platform"),
                owner_brand=owner_brand,
                default_crawl=_optional_bool(
                    raw_source, "default_crawl", default=True
                ),
                market_scope=market_scope,
                business_unit_scope=business_unit_scope,
                canonical_url=canonical_url,
                verified_account_ids=tuple(
                    str(item).strip()
                    for item in raw_source.get("verified_account_ids") or []
                    if str(item).strip()
                ),
                acquisition_mode=_required_text(raw_source, "acquisition_mode"),
                tinyfish_policy=_required_text(raw_source, "tinyfish_policy"),
                permission_status=_required_text(raw_source, "permission_status"),
                blocked_paths=tuple(
                    str(item).strip()
                    for item in raw_source.get("blocked_paths") or []
                    if str(item).strip()
                ),
                search_queries=tuple(queries),
            )
        )
    if not sources:
        raise ValueError("source registry contains no sources")
    default_sources = tuple(source for source in sources if source.default_crawl)
    if not default_sources:
        raise ValueError("source registry contains no default crawl sources")
    excluded_sources = tuple(source for source in sources if not source.default_crawl)
    return SourceRegistry(
        version=version,
        sources=default_sources,
        excluded_sources=excluded_sources,
    )


__all__ = [
    "REGISTRY_PATH",
    "SearchQuery",
    "SourceDefinition",
    "SourceRegistry",
    "load_source_registry",
]
