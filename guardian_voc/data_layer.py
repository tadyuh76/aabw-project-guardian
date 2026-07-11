"""Auditable live acquisition layer: SerpAPI discovery, TinyFish reading, DuckDB.

Search titles and snippets are stored only in ``discovery_results``. They are
never mapped to feedback items or classified as customer voice. Marketplace
review completeness is delegated to permissioned seller API/export connectors.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import unicodedata
from collections import Counter
from collections.abc import AsyncIterator
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import urlsplit

import httpx

from guardian_voc.ai.extraction import (
    PAGE_FEEDBACK_EXTRACTOR_PROMPT_VERSION,
    assemble_customer_text,
)
from guardian_voc.ai.openai_compatible import OpenAICompatibleProvider
from guardian_voc.config import Settings, get_settings
from guardian_voc.connectors.public_social import brand_candidates_from_keywords
from guardian_voc.db import Database, GuardianVocRepository
from guardian_voc.pipeline.dedupe import canonicalize_url
from guardian_voc.pipeline.language import resolve_language
from guardian_voc.pipeline.normalize import parse_timestamp
from guardian_voc.pipeline.pii import redact_text
from guardian_voc.schemas.extraction import PageBlock, PageExtractionRequest
from guardian_voc.schemas.feedback import (
    Brand,
    IngestionRun,
    OccurredAtQuality,
    RawFeedback,
    SourceGroup,
    Visibility,
)
from guardian_voc.source_registry import SourceDefinition, load_source_registry
from social_crawler.serpapi import SerpApiClient


DEFAULT_PERIOD_START = date(2025, 7, 12)
DEFAULT_PERIOD_END = date(2026, 7, 11)
TARGET_UNIQUE_FEEDBACK_ITEMS = 2_000
# The current run is intentionally public/best-effort.  Public sources cannot
# truthfully be marked exhaustive, and the user explicitly excluded Shopee,
# Lazada, and TikTok Shop.  Keep this tuple for authorized-export deployments,
# but do not make excluded/private sources a readiness gate for this dataset.
REQUIRED_COMPLETE_REVIEW_SOURCES: tuple[str, ...] = ()
PUBLIC_SOCIAL_SOURCE_IDS = (
    "guardian_public_social",
    "hasaki_public_social",
    "watsons_public_social",
)
TINYFISH_AGENT_BASE_URL = "https://agent.tinyfish.ai/v1"
TINYFISH_AGENT_TERMINAL_STATUSES = {"COMPLETED", "FAILED", "CANCELLED"}
_LOGIN_OR_BLOCK_PATTERNS = (
    "security check",
    "verify/traffic/error",
    "accounts/login",
    "log in to continue",
    "đăng nhập để tiếp tục",
)
_PARAGRAPH_SPLIT_RE = re.compile(r"\n\s*\n+")
_RATING_RE = re.compile(
    r"(?<!\d)([0-5](?:[.,]\d+)?)\s*(?:/\s*5|sao|stars?)(?!\w)",
    re.IGNORECASE,
)
_CATALOG_REVIEW_COUNT_RE = re.compile(
    r"(?:^|\s)(\d[\d.,]*)\s*(?:đ[aá]nh\s*gi[aá]|nh[aậ]n\s*x[eé]t)\b",
    re.IGNORECASE,
)


def _sha256(*parts: object) -> str:
    value = "\0".join(str(part) for part in parts)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(str(path) + ".tmp")
    temporary.write_text(_json(payload) + "\n", encoding="utf-8")
    temporary.replace(path)


def _write_jsonl_atomic(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(str(path) + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(_json(row) + "\n")
    temporary.replace(path)


def _date_tbs(start: date, end: date) -> str:
    def fmt(value: date) -> str:
        return f"{value.month}/{value.day}/{value.year}"

    return f"cdr:1,cd_min:{fmt(start)},cd_max:{fmt(end)},sbd:1"


def _atomic_social_platform(url: str) -> str | None:
    """Return a platform only for URL shapes representing one public post.

    Profile, search, and feed pages are intentionally excluded. They can
    contain many unrelated units and TinyFish Fetch does not expose stable DOM
    container identities for safe multi-review extraction.
    """

    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower().removeprefix("www.")
    path = parsed.path.lower()
    if host.endswith("instagram.com") and path.startswith(("/p/", "/reel/", "/tv/")):
        return "instagram"
    if host.endswith(("threads.com", "threads.net")) and "/post/" in path:
        return "threads"
    if host.endswith("tiktok.com") and "/video/" in path:
        return "tiktok"
    if host.endswith("youtube.com") and (
        path == "/watch" or path.startswith("/shorts/")
    ):
        return "youtube"
    if host.endswith("reddit.com") and "/comments/" in path:
        return "reddit"
    if host.endswith("facebook.com") and (
        any(
            token in path
            for token in ("/posts/", "/photos/", "/videos/", "/reel/")
        )
        or path.endswith(("/permalink.php", "/story.php"))
    ):
        return "facebook"
    return None


def _social_platform(url: str) -> str | None:
    host = (urlsplit(url).hostname or "").lower().removeprefix("www.")
    for platform, domains in (
        ("facebook", ("facebook.com",)),
        ("instagram", ("instagram.com",)),
        ("threads", ("threads.com", "threads.net")),
        ("tiktok", ("tiktok.com",)),
        ("youtube", ("youtube.com",)),
        ("reddit", ("reddit.com",)),
    ):
        if any(host == domain or host.endswith("." + domain) for domain in domains):
            return platform
    return None


def _verified_guardian_social_owner(url: str) -> bool:
    """Recognize only Guardian handles verified by first-party references."""

    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower().removeprefix("www.")
    path = parsed.path.lower()
    return bool(
        (host.endswith("facebook.com") and path.startswith("/guardianvn/"))
        or (
            host.endswith("instagram.com")
            and path.startswith("/guardianvietnam/")
        )
        or (
            host.endswith(("tiktok.com", "threads.com", "threads.net"))
            and path.startswith("/@guardianvietnam/")
        )
        or (
            host.endswith("youtube.com")
            and path.startswith("/@guardianvietnamofficial/")
        )
    )


def _page_blocks(text: str, *, container_id: str) -> tuple[PageBlock, ...]:
    """Create bounded ordered blocks without claiming invented review IDs."""

    paragraphs = [part.strip() for part in _PARAGRAPH_SPLIT_RE.split(text) if part.strip()]
    if not paragraphs:
        paragraphs = [text.strip()]
    chunks: list[str] = []
    for paragraph in paragraphs:
        remaining = paragraph
        while remaining:
            if len(remaining) <= 6_000:
                chunks.append(remaining)
                break
            cut = remaining.rfind("\n", 0, 6_000)
            if cut < 1_000:
                cut = remaining.rfind(" ", 0, 6_000)
            if cut < 1_000:
                cut = 6_000
            chunks.append(remaining[:cut].strip())
            remaining = remaining[cut:].strip()
    if len(chunks) > 200:
        chunks = chunks[:200]
    return tuple(
        PageBlock(
            block_id=f"b-{index:03d}",
            container_id=container_id,
            parent_block_id=None,
            role_hint="unknown",
            text=chunk,
        )
        for index, chunk in enumerate(chunks, start=1)
        if chunk
    )


def _rating_from_span(value: str | None) -> float | None:
    if not value:
        return None
    match = _RATING_RE.search(value)
    if match is None:
        return None
    rating = float(match.group(1).replace(",", "."))
    return rating if 0 <= rating <= 5 else None


def _catalog_review_count(value: object) -> int:
    match = _CATALOG_REVIEW_COUNT_RE.search(
        unicodedata.normalize("NFC", str(value or ""))
    )
    if match is None:
        return 0
    digits = re.sub(r"\D", "", match.group(1))
    return int(digits) if digits else 0


def _brand(value: str) -> Brand:
    try:
        return Brand(value.strip().lower())
    except ValueError:
        return Brand.OTHER


def _verified_social_owner(url: str, brand: Brand) -> bool:
    """Recognize only first-party handles declared for the scoped brand."""

    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower().removeprefix("www.")
    path = parsed.path.lower()
    handles = {
        Brand.GUARDIAN: ("guardianvn", "guardianvietnam", "guardianvietnamofficial"),
        Brand.HASAKI: ("hasakibeauty", "hasaki.vn", "hasaki"),
        Brand.WATSONS: ("watsonsvietnam", "watsonsvn"),
    }.get(brand, ())
    if not handles:
        return False
    if host.endswith("facebook.com"):
        return any(path.startswith(f"/{handle}/") for handle in handles)
    if host.endswith(("instagram.com", "threads.com", "threads.net", "tiktok.com")):
        return any(
            path.startswith((f"/{handle}/", f"/@{handle}/"))
            for handle in handles
        )
    if host.endswith("youtube.com"):
        return any(path.startswith(f"/@{handle}/") for handle in handles)
    return False


def _agent_result_object(value: object) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return dict(decoded) if isinstance(decoded, Mapping) else {}
    return {}


def _agent_review_count(result: Mapping[str, Any]) -> int:
    reviews = result.get("reviews")
    return len(reviews) if isinstance(reviews, list) else 0


class _ExtractedRowsConnector:
    """Small connector so extracted units use the canonical repository path."""

    def __init__(self, rows: Iterable[RawFeedback]) -> None:
        self.rows = tuple(rows)
        self.errors: list[str] = []

    async def collect(self, _: IngestionRun) -> AsyncIterator[RawFeedback]:
        for row in self.rows:
            yield row


class LiveDataLayer:
    """Persist a resumable, truthful live acquisition audit in DuckDB."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        database: Database | None = None,
        period_start: date = DEFAULT_PERIOD_START,
        period_end: date = DEFAULT_PERIOD_END,
    ) -> None:
        if period_end < period_start:
            raise ValueError("period_end must be on or after period_start")
        self.settings = settings or get_settings()
        self.database = database or Database(settings=self.settings)
        self.period_start = period_start
        self.period_end = period_end
        self.registry = load_source_registry()

    def initialize(self) -> None:
        self.database.initialize()
        now = datetime.now(timezone.utc)
        for source in self.registry.sources:
            metadata = {
                "registry_version": self.registry.version,
                "blocked_paths": list(source.blocked_paths),
                "default_crawl": source.default_crawl,
            }
            self.database.execute(
                """
                INSERT INTO source_registry VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (source_id) DO UPDATE SET
                    source_group = excluded.source_group,
                    source_platform = excluded.source_platform,
                    owner_brand = excluded.owner_brand,
                    market_scope = excluded.market_scope,
                    business_unit_scope = excluded.business_unit_scope,
                    canonical_url = excluded.canonical_url,
                    verified_account_ids = excluded.verified_account_ids,
                    acquisition_mode = excluded.acquisition_mode,
                    tinyfish_policy = excluded.tinyfish_policy,
                    permission_status = excluded.permission_status,
                    metadata = excluded.metadata,
                    updated_at = excluded.updated_at
                """,
                [
                    source.source_id,
                    source.source_group,
                    source.source_platform,
                    source.owner_brand,
                    source.market_scope,
                    source.business_unit_scope,
                    source.canonical_url,
                    list(source.verified_account_ids),
                    source.acquisition_mode,
                    source.tinyfish_policy,
                    source.permission_status,
                    _json(metadata),
                    now,
                ],
            )

    @staticmethod
    def _fetch_decision(source: SourceDefinition, url: str) -> tuple[bool, str | None]:
        if not source.host_allowed(url):
            return False, "off_domain"
        if source.blocked_path(url):
            return False, "robots_or_registry_blocked_path"
        if not source.tinyfish_fetch_allowed:
            return False, "written_permission_or_authorized_export_required"
        return True, None

    def _upsert_discovery(
        self,
        *,
        source: SourceDefinition,
        query_id: str,
        query: str,
        raw_url: str,
        title: str = "",
        snippet: str = "",
        position: int | None = None,
        provider: str = "serpapi_google",
        extra_metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        canonical = canonicalize_url(raw_url)
        if canonical is None:
            return None
        eligible, rejection = self._fetch_decision(source, canonical)
        discovery_id = "discovery_" + _sha256(source.source_id, canonical)[:32]
        discovered_at = datetime.now(timezone.utc)
        existing = self.database.query_one(
            "SELECT metadata FROM discovery_results WHERE discovery_id = ?",
            [discovery_id],
        )
        previous_metadata: dict[str, Any] = {}
        if existing is not None:
            raw_metadata = existing.get("metadata")
            if isinstance(raw_metadata, Mapping):
                previous_metadata = dict(raw_metadata)
            elif isinstance(raw_metadata, str):
                try:
                    decoded = json.loads(raw_metadata)
                except json.JSONDecodeError:
                    decoded = {}
                if isinstance(decoded, Mapping):
                    previous_metadata = dict(decoded)
        matched_query_ids = list(
            dict.fromkeys(
                [
                    *(
                        previous_metadata.get("matched_query_ids")
                        if isinstance(
                            previous_metadata.get("matched_query_ids"), list
                        )
                        else []
                    ),
                    query_id,
                ]
            )
        )
        matched_queries = list(
            dict.fromkeys(
                [
                    *(
                        previous_metadata.get("matched_queries")
                        if isinstance(previous_metadata.get("matched_queries"), list)
                        else []
                    ),
                    query,
                ]
            )
        )
        metadata = {
            **previous_metadata,
            **dict(extra_metadata or {}),
            "registry_version": self.registry.version,
            "matched_query_ids": matched_query_ids,
            "matched_queries": matched_queries,
        }
        row = {
            "discovery_id": discovery_id,
            "source_id": source.source_id,
            "query_id": query_id,
            "query": query,
            "canonical_url": canonical,
            "raw_url": raw_url,
            "title_redacted": redact_text(title, max_chars=1_000),
            "snippet_redacted": redact_text(snippet, max_chars=2_000),
            "search_position": position,
            "discovered_at": discovered_at.isoformat(),
            "provider": provider,
            "eligible_for_fetch": eligible,
            "rejection_reason": rejection,
            "metadata": metadata,
        }
        self.database.execute(
            """
            INSERT INTO discovery_results VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (discovery_id) DO UPDATE SET
                query_id = excluded.query_id,
                query = excluded.query,
                raw_url = excluded.raw_url,
                title_redacted = excluded.title_redacted,
                snippet_redacted = excluded.snippet_redacted,
                search_position = excluded.search_position,
                discovered_at = excluded.discovered_at,
                provider = excluded.provider,
                eligible_for_fetch = excluded.eligible_for_fetch,
                rejection_reason = excluded.rejection_reason,
                metadata = excluded.metadata
            """,
            [
                row["discovery_id"],
                row["source_id"],
                row["query_id"],
                row["query"],
                row["canonical_url"],
                row["raw_url"],
                row["title_redacted"],
                row["snippet_redacted"],
                row["search_position"],
                discovered_at,
                row["provider"],
                row["eligible_for_fetch"],
                row["rejection_reason"],
                _json(row["metadata"]),
            ],
        )
        return row

    def seed_guardian_catalog(self, path: str | Path) -> dict[str, Any]:
        """Seed verified Guardian product URLs without treating cards as reviews.

        The browser checkpoint is only an inventory.  Aggregate card counts are
        persisted as discovery metadata and never emitted as customer voice.
        Each review body must still be read from the public product-page UI by
        TinyFish and extracted by the OpenAI stage.
        """

        self.initialize()
        source = self.registry.get("guardian_web")
        catalog_path = Path(path).expanduser().resolve()
        payload = json.loads(catalog_path.read_text(encoding="utf-8"))
        if not isinstance(payload, Mapping):
            raise ValueError("Guardian catalog checkpoint must be a JSON object")
        products = payload.get("products")
        if not isinstance(products, list):
            raise ValueError("Guardian catalog checkpoint products must be an array")

        seeded = 0
        with_reviews = 0
        visible_review_total = 0
        seen_product_ids: set[str] = set()
        for raw_product in products:
            if not isinstance(raw_product, Mapping):
                continue
            product_id = str(raw_product.get("product_id") or "").strip()
            raw_url = str(
                raw_product.get("review_url") or raw_product.get("url") or ""
            ).strip()
            if not product_id or not raw_url or product_id in seen_product_ids:
                continue
            seen_product_ids.add(product_id)
            review_count = _catalog_review_count(raw_product.get("rating"))
            has_review_anchor = bool(raw_product.get("review_url"))
            if has_review_anchor:
                with_reviews += 1
            visible_review_total += review_count
            event = self._upsert_discovery(
                source=source,
                query_id="guardian_catalog_checkpoint",
                query="verified Guardian public catalog inventory",
                raw_url=raw_url,
                title=str(raw_product.get("title") or ""),
                provider="guardian_public_catalog_ui",
                extra_metadata={
                    "product_id": product_id,
                    "product_brand": str(raw_product.get("brand") or ""),
                    "review_url": str(raw_product.get("review_url") or raw_url),
                    "has_review_anchor": has_review_anchor,
                    "visible_aggregate_review_count": review_count,
                    "catalog_checkpoint": str(catalog_path),
                },
            )
            seeded += int(event is not None)

        checkpoint = {
            "catalog_checkpoint": str(catalog_path),
            "pages_crawled": int(payload.get("pages_crawled") or 0),
            "next_url": str(payload.get("next_url") or "") or None,
            "products_in_checkpoint": len(products),
            "unique_products_seeded": seeded,
            "products_with_review_anchor": with_reviews,
            "visible_aggregate_review_count": visible_review_total,
            "inventory_complete": not bool(payload.get("next_url")),
        }
        self.database.execute(
            """
            INSERT INTO source_checkpoints VALUES (?, ?, ?, ?)
            ON CONFLICT (source_id, checkpoint_key) DO UPDATE SET
                checkpoint_value = excluded.checkpoint_value,
                updated_at = excluded.updated_at
            """,
            [
                "guardian_web",
                "public_catalog_inventory",
                _json(checkpoint),
                datetime.now(timezone.utc),
            ],
        )
        return checkpoint

    async def discover(
        self,
        *,
        source_ids: Iterable[str] | None = None,
        pages_per_query: int = 1,
    ) -> dict[str, Any]:
        if not self.settings.serp_api_key:
            raise ValueError("SERP_API_KEY is required for source discovery")
        if not 1 <= pages_per_query <= 10:
            raise ValueError("pages_per_query must be between 1 and 10")
        self.initialize()
        selected = set(source_ids or ())
        sources = [
            source
            for source in self.registry.sources
            if not selected or source.source_id in selected
        ]
        if selected - {source.source_id for source in sources}:
            raise ValueError("unknown source_id in discovery selection")
        events: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []
        client = SerpApiClient(
            self.settings.serp_api_key,
            base_url=self.settings.serp_api_base_url,
        )
        searches = 0
        available_before: int | None = None
        available_after: int | None = None
        try:
            try:
                account = await client.account()
                available_before = int(
                    account.get("total_searches_left")
                    or account.get("plan_searches_left")
                    or 0
                )
            except Exception as exc:
                # Quota reporting is useful audit metadata, but an account
                # endpoint outage must not suppress otherwise valid searches.
                errors.append(
                    {
                        "source_id": "_provider",
                        "query_id": "account_before",
                        "error": type(exc).__name__,
                    }
                )
            for source in sources:
                seed = self._upsert_discovery(
                    source=source,
                    query_id="registry_seed",
                    query="verified source registry",
                    raw_url=source.canonical_url,
                    provider="source_registry",
                )
                if seed:
                    events.append(seed)
                for query in source.search_queries:
                    for page in range(pages_per_query):
                        try:
                            payload = await client.google_search(
                                query=query.query,
                                tbs=(
                                    _date_tbs(self.period_start, self.period_end)
                                    if source.source_platform == "public_social"
                                    else None
                                ),
                                start=page * 10,
                                no_cache=False,
                                google_domain="google.com.vn",
                                gl="vn",
                                hl="vi",
                                lr="lang_vi",
                                filter_similar=False,
                                nfpr=True,
                            )
                            searches += 1
                        except Exception as exc:
                            errors.append(
                                {
                                    "source_id": source.source_id,
                                    "query_id": query.id,
                                    "error": type(exc).__name__,
                                }
                            )
                            continue
                        for item in payload.get("organic_results") or []:
                            if not isinstance(item, Mapping):
                                continue
                            event = self._upsert_discovery(
                                source=source,
                                query_id=query.id,
                                query=query.query,
                                raw_url=str(item.get("link") or ""),
                                title=str(item.get("title") or ""),
                                snippet=str(item.get("snippet") or ""),
                                position=(
                                    int(item["position"])
                                    if isinstance(item.get("position"), int)
                                    else None
                                ),
                            )
                            if event:
                                events.append(event)
            try:
                account_after = await client.account()
                available_after = int(
                    account_after.get("total_searches_left")
                    or account_after.get("plan_searches_left")
                    or 0
                )
            except Exception as exc:
                errors.append(
                    {
                        "source_id": "_provider",
                        "query_id": "account_after",
                        "error": type(exc).__name__,
                    }
                )
        finally:
            await client.aclose()
        unique = {str(row["discovery_id"]): row for row in events}
        output = Path(self.settings.voc_data_dir) / "live" / "discovery.jsonl"
        snapshot = self.database.query(
            "SELECT * FROM discovery_results ORDER BY source_id, canonical_url"
        )
        _write_jsonl_atomic(output, snapshot)
        return {
            "searches": searches,
            "available_before": available_before,
            "available_after": available_after,
            "events": len(events),
            "unique_results": len(unique),
            "snapshot_results": len(snapshot),
            "eligible_for_fetch": sum(bool(row["eligible_for_fetch"]) for row in unique.values()),
            "errors": errors,
            "output": str(output.resolve()),
        }

    async def fetch(
        self,
        *,
        source_ids: Iterable[str] | None = None,
        refresh: bool = False,
        limit: int | None = None,
    ) -> dict[str, Any]:
        key = self.settings.tinyfish_resolved_api_key
        if not key:
            raise ValueError("TINYFISH_API_KEY is required for page reading")
        self.initialize()
        selected = tuple(source_ids or ())
        source_by_id = {source.source_id: source for source in self.registry.all_sources}
        unknown = set(selected) - set(source_by_id)
        if unknown:
            raise ValueError("unknown source_id in fetch selection")

        # ``eligible_for_fetch`` is an audit snapshot from discovery time.  A
        # permission or blocked-path policy can change later, so recompute it
        # from the current registry immediately before any TinyFish request.
        policy_sql = "SELECT * FROM discovery_results"
        policy_params: list[object] = []
        if selected:
            placeholders = ",".join("?" for _ in selected)
            policy_sql += f" WHERE source_id IN ({placeholders})"
            policy_params.extend(selected)
        policy_rows = self.database.query(policy_sql, policy_params)
        policy_filtered = 0
        for row in policy_rows:
            source = source_by_id.get(str(row["source_id"]))
            if source is None:
                allowed, rejection = False, "source_not_in_current_registry"
            else:
                allowed, rejection = self._fetch_decision(
                    source, str(row["canonical_url"])
                )
            if bool(row["eligible_for_fetch"]) and not allowed:
                policy_filtered += 1
            if (
                bool(row["eligible_for_fetch"]) != allowed
                or row.get("rejection_reason") != rejection
            ):
                self.database.execute(
                    """
                    UPDATE discovery_results
                    SET eligible_for_fetch = ?, rejection_reason = ?
                    WHERE discovery_id = ?
                    """,
                    [allowed, rejection, row["discovery_id"]],
                )

        params: list[object] = []
        where = "WHERE dr.eligible_for_fetch = TRUE"
        if selected:
            placeholders = ",".join("?" for _ in selected)
            where += f" AND dr.source_id IN ({placeholders})"
            params.extend(selected)
        if not refresh:
            where += " AND NOT EXISTS (SELECT 1 FROM fetch_attempts fa WHERE fa.discovery_id = dr.discovery_id AND fa.status = 'usable')"
        sql = f"""
            SELECT dr.* FROM discovery_results dr
            {where}
            ORDER BY dr.source_id, dr.canonical_url
        """
        rows = self.database.query(sql, params)
        if limit is not None:
            if limit < 0:
                raise ValueError("fetch limit must not be negative")
            rows = rows[:limit]
        audit_rows: list[dict[str, Any]] = []
        status_counts: Counter[str] = Counter()
        async with httpx.AsyncClient(timeout=self.settings.tinyfish_timeout_seconds) as client:
            for offset in range(0, len(rows), 10):
                batch = rows[offset : offset + 10]
                requested_urls = [str(row["canonical_url"]) for row in batch]
                try:
                    response = await client.post(
                        self.settings.tinyfish_fetch_base_url,
                        headers={"X-API-Key": key, "Content-Type": "application/json"},
                        json={
                            "urls": requested_urls,
                            "format": "markdown",
                            "links": False,
                            "image_links": False,
                            "ttl": 0 if refresh else 3600,
                            "per_url_timeout_ms": 60_000,
                        },
                    )
                    response.raise_for_status()
                    payload = response.json()
                    if not isinstance(payload, Mapping):
                        raise ValueError("TinyFish Fetch returned a non-object response")
                    results = {
                        canonicalize_url(item.get("url")): item
                        for item in payload.get("results") or []
                        if isinstance(item, Mapping)
                        and canonicalize_url(item.get("url"))
                    }
                    errors = {
                        canonicalize_url(item.get("url")): item
                        for item in payload.get("errors") or []
                        if isinstance(item, Mapping)
                        and canonicalize_url(item.get("url"))
                    }
                except (httpx.HTTPError, ValueError, TypeError, json.JSONDecodeError) as exc:
                    # Persist one secret-free failure per requested URL and
                    # continue with later batches. Partial source outages must
                    # not erase successful results from other sources.
                    results = {}
                    errors = {
                        url: {
                            "error": f"batch_{type(exc).__name__}",
                            "status": None,
                        }
                        for url in requested_urls
                    }
                for row in batch:
                    canonical = str(row["canonical_url"])
                    source = source_by_id[str(row["source_id"])]
                    item = results.get(canonical)
                    error = errors.get(canonical)
                    fetched_at = datetime.now(timezone.utc)
                    final_url: str | None = None
                    title = ""
                    text = ""
                    error_code: str | None = None
                    status = "failed"
                    metadata: dict[str, Any] = {}
                    if item is not None:
                        raw_final_url = item.get("final_url")
                        final_url = (
                            canonicalize_url(str(raw_final_url))
                            if raw_final_url is not None and str(raw_final_url).strip()
                            else canonical
                        )
                        if final_url is None:
                            status = "invalid_redirect"
                            error_code = "invalid_final_url"
                        elif not source.host_allowed(final_url):
                            status = "invalid_redirect"
                            error_code = "redirect_outside_registry"
                        elif source.blocked_path(final_url):
                            status = "invalid_redirect"
                            error_code = "redirect_to_blocked_path"
                        else:
                            title = redact_text(str(item.get("title") or ""), max_chars=1_000)
                            raw_text = item.get("text")
                            if not isinstance(raw_text, str) or not raw_text.strip():
                                raw_text = item.get("description")
                            text = redact_text(
                                raw_text if isinstance(raw_text, str) else "",
                                max_chars=100_000,
                            )
                            lowered = f"{final_url}\n{title}\n{text}".lower()
                            if len(text.strip()) < self.settings.tinyfish_useful_text_chars or any(
                                marker in lowered for marker in _LOGIN_OR_BLOCK_PATTERNS
                            ):
                                status = "blocked_or_empty"
                                error_code = "login_wall_or_insufficient_content"
                            else:
                                status = "usable"
                            metadata = {
                                "language": item.get("language"),
                                "latency_ms": item.get("latency_ms"),
                                "format": item.get("format"),
                            }
                    elif error is not None:
                        error_code = str(error.get("error") or "fetch_error")
                        metadata = {"upstream_status": error.get("status")}
                    else:
                        error_code = "missing_result"
                    content_digest = _sha256(title, text) if text else None
                    fetch_id = "fetch_" + _sha256(
                        row["discovery_id"], content_digest or error_code or status
                    )[:32]
                    audit = {
                        "fetch_id": fetch_id,
                        "discovery_id": row["discovery_id"],
                        "source_id": row["source_id"],
                        "canonical_url": canonical,
                        "final_url": final_url,
                        "reader": "tinyfish_fetch",
                        "status": status,
                        "error_code": error_code,
                        "content_hash": content_digest,
                        "content_chars": len(text),
                        "customer_voice_units": 0,
                        "fetched_at": fetched_at.isoformat(),
                        "metadata": metadata,
                    }
                    self.database.execute(
                        """
                        INSERT INTO fetch_attempts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT (fetch_id) DO UPDATE SET
                            final_url = excluded.final_url,
                            status = excluded.status,
                            error_code = excluded.error_code,
                            content_hash = excluded.content_hash,
                            content_chars = excluded.content_chars,
                            fetched_at = excluded.fetched_at,
                            metadata = excluded.metadata
                        """,
                        [
                            fetch_id,
                            row["discovery_id"],
                            row["source_id"],
                            canonical,
                            final_url,
                            "tinyfish_fetch",
                            status,
                            error_code,
                            content_digest,
                            len(text),
                            0,
                            fetched_at,
                            _json(metadata),
                        ],
                    )
                    if status == "usable":
                        self.database.execute(
                            """
                            INSERT INTO page_reader_cache VALUES (?, ?, ?, ?, ?, ?)
                            ON CONFLICT (canonical_url) DO UPDATE SET
                                title = excluded.title,
                                text_redacted = excluded.text_redacted,
                                reader = excluded.reader,
                                metadata = excluded.metadata,
                                fetched_at = excluded.fetched_at
                            """,
                            [canonical, title, text, "tinyfish_fetch", _json(metadata), fetched_at],
                        )
                    audit_rows.append(audit)
                    status_counts[status] += 1
        output = Path(self.settings.voc_data_dir) / "live" / "fetches.jsonl"
        snapshot = self.database.query(
            """
            SELECT fetch_id, discovery_id, source_id, canonical_url, final_url,
                reader, status, error_code, content_hash, content_chars,
                customer_voice_units, fetched_at, metadata
            FROM fetch_attempts ORDER BY source_id, canonical_url, fetched_at
            """
        )
        _write_jsonl_atomic(output, snapshot)
        return {
            "attempted": len(rows),
            "snapshot_attempts": len(snapshot),
            "permission_revalidated": len(policy_rows),
            "policy_filtered": policy_filtered,
            "status": dict(sorted(status_counts.items())),
            "output": str(output.resolve()),
        }

    async def fetch_guardian_reviews_with_agent(
        self,
        *,
        refresh: bool = False,
        limit: int | None = None,
        concurrency: int = 3,
        timeout_seconds: float = 300,
        poll_seconds: float = 2,
    ) -> dict[str, Any]:
        """Use TinyFish Agent only after normal Fetch cannot read Guardian UI.

        Agent is credit-bearing, so this path is explicit, resumable, bounded,
        and restricted to catalog products that exposed a public review anchor.
        The goal forbids login, CAPTCHA solving, hidden endpoints, and access-
        control bypass.  Results remain page-reader evidence and still pass
        through the Vietnamese/date and OpenAI extraction/classification gates.
        """

        key = self.settings.tinyfish_resolved_api_key
        if not key:
            raise ValueError("TINYFISH_API_KEY is required for TinyFish Agent")
        if concurrency < 1 or concurrency > 10:
            raise ValueError("TinyFish Agent concurrency must be between 1 and 10")
        if timeout_seconds < 30 or timeout_seconds > 1_800:
            raise ValueError("TinyFish Agent timeout must be between 30 and 1800 seconds")
        if poll_seconds < 0.5 or poll_seconds > 30:
            raise ValueError("TinyFish Agent poll interval must be between 0.5 and 30 seconds")
        if limit is not None and limit < 0:
            raise ValueError("TinyFish Agent limit must not be negative")

        self.initialize()
        refresh_clause = ""
        if not refresh:
            refresh_clause = """
                AND NOT EXISTS (
                    SELECT 1 FROM fetch_attempts fa
                    WHERE fa.discovery_id = dr.discovery_id
                      AND fa.reader = 'tinyfish_agent_public_ui'
                      AND fa.status IN ('usable', 'no_customer_voice')
                )
            """
        candidates = self.database.query(
            f"""
            SELECT dr.* FROM discovery_results dr
            WHERE dr.source_id = 'guardian_web'
              AND dr.eligible_for_fetch = TRUE
              AND dr.provider = 'guardian_public_catalog_ui'
              {refresh_clause}
            ORDER BY dr.canonical_url
            """
        )
        rows: list[dict[str, Any]] = []
        for row in candidates:
            metadata = row.get("metadata")
            if isinstance(metadata, str):
                try:
                    metadata = json.loads(metadata)
                except json.JSONDecodeError:
                    metadata = {}
            if not isinstance(metadata, Mapping):
                metadata = {}
            if not bool(metadata.get("has_review_anchor")):
                continue
            rows.append({**row, "metadata": dict(metadata)})
        if limit is not None:
            rows = rows[:limit]

        semaphore = asyncio.Semaphore(concurrency)
        status_counts: Counter[str] = Counter()

        async def read_one(client: httpx.AsyncClient, row: Mapping[str, Any]) -> None:
            async with semaphore:
                canonical = str(row["canonical_url"])
                row_metadata = row.get("metadata")
                agent_url = canonical
                if isinstance(row_metadata, Mapping):
                    candidate_url = str(row_metadata.get("review_url") or "").strip()
                    if candidate_url.startswith(canonical):
                        agent_url = candidate_url
                started_at = datetime.now(timezone.utc)
                run_id: str | None = None
                run_payload: Mapping[str, Any] = {}
                status = "failed"
                error_code: str | None = None
                result: dict[str, Any] = {}
                try:
                    response = await client.post(
                        f"{TINYFISH_AGENT_BASE_URL}/automation/run-async",
                        headers={"X-API-Key": key, "Content-Type": "application/json"},
                        json={
                            "url": agent_url,
                            "browser_profile": "stealth",
                            "goal": (
                                "Use only the public website UI. Do not log in, solve "
                                "CAPTCHAs, bypass access controls, call hidden APIs, or "
                                "submit forms. The URL opens the customer review anchor. "
                                "Scroll to that section and read only reviews currently "
                                "visible after page load; do not paginate and do not click "
                                "load-more. Collect up to 50 customer-authored reviews. Exclude "
                                "product descriptions, marketing copy, aggregate summaries, "
                                "and retailer replies. Return JSON with product_name, status, "
                                "and reviews. Each review must contain exact customer_text as "
                                "displayed, displayed_date or null, and displayed_rating or "
                                "null. Return an empty reviews array if blocked or none are "
                                "publicly visible."
                            ),
                        },
                        timeout=60,
                    )
                    response.raise_for_status()
                    submitted = response.json()
                    if not isinstance(submitted, Mapping):
                        raise ValueError("TinyFish Agent start returned a non-object")
                    run_id = str(submitted.get("run_id") or "").strip() or None
                    if run_id is None:
                        raise ValueError("TinyFish Agent start returned no run_id")
                    deadline = asyncio.get_running_loop().time() + timeout_seconds
                    while asyncio.get_running_loop().time() < deadline:
                        await asyncio.sleep(poll_seconds)
                        polled = await client.get(
                            f"{TINYFISH_AGENT_BASE_URL}/runs/{run_id}",
                            headers={"X-API-Key": key},
                            timeout=60,
                        )
                        polled.raise_for_status()
                        decoded = polled.json()
                        if not isinstance(decoded, Mapping):
                            raise ValueError("TinyFish Agent poll returned a non-object")
                        run_payload = decoded
                        run_status = str(decoded.get("status") or "").upper()
                        if run_status in TINYFISH_AGENT_TERMINAL_STATUSES:
                            break
                    else:
                        error_code = "agent_timeout"
                    run_status = str(run_payload.get("status") or "").upper()
                    if error_code is None and run_status == "COMPLETED":
                        result = _agent_result_object(run_payload.get("result"))
                        status = (
                            "usable" if _agent_review_count(result) else "no_customer_voice"
                        )
                    elif error_code is None:
                        upstream_error = run_payload.get("error")
                        error_code = (
                            str(upstream_error.get("code") or "agent_failed")
                            if isinstance(upstream_error, Mapping)
                            else "agent_failed"
                        )
                except (httpx.HTTPError, ValueError, TypeError, json.JSONDecodeError) as exc:
                    error_code = f"agent_{type(exc).__name__}"

                finished_at = datetime.now(timezone.utc)
                review_count = _agent_review_count(result)
                title = redact_text(
                    str(result.get("product_name") or row.get("title_redacted") or ""),
                    max_chars=1_000,
                )
                text = redact_text(_json(result), max_chars=100_000) if result else ""
                content_digest = _sha256(title, text) if text else None
                fetch_id = "fetch_" + _sha256(
                    row["discovery_id"], "tinyfish_agent_public_ui",
                    content_digest or error_code or status,
                )[:32]
                metadata = {
                    "run_id": run_id,
                    "run_status": run_payload.get("status"),
                    "num_of_steps": run_payload.get("num_of_steps"),
                    "review_count": review_count,
                    "browser_profile": "stealth",
                    "public_ui_only": True,
                    "started_at": started_at.isoformat(),
                }
                self.database.execute(
                    """
                    INSERT INTO fetch_attempts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT (fetch_id) DO UPDATE SET
                        status = excluded.status,
                        error_code = excluded.error_code,
                        content_hash = excluded.content_hash,
                        content_chars = excluded.content_chars,
                        fetched_at = excluded.fetched_at,
                        metadata = excluded.metadata
                    """,
                    [
                        fetch_id,
                        row["discovery_id"],
                        row["source_id"],
                        canonical,
                        canonical,
                        "tinyfish_agent_public_ui",
                        status,
                        error_code,
                        content_digest,
                        len(text),
                        0,
                        finished_at,
                        _json(metadata),
                    ],
                )
                if status == "usable":
                    self.database.execute(
                        """
                        INSERT INTO page_reader_cache VALUES (?, ?, ?, ?, ?, ?)
                        ON CONFLICT (canonical_url) DO UPDATE SET
                            title = excluded.title,
                            text_redacted = excluded.text_redacted,
                            reader = excluded.reader,
                            metadata = excluded.metadata,
                            fetched_at = excluded.fetched_at
                        """,
                        [
                            canonical,
                            title,
                            text,
                            "tinyfish_agent_public_ui",
                            _json(metadata),
                            finished_at,
                        ],
                    )
                status_counts[status] += 1

        async with httpx.AsyncClient(timeout=60) as client:
            await asyncio.gather(*(read_one(client, row) for row in rows))

        output = Path(self.settings.voc_data_dir) / "live" / "fetches.jsonl"
        snapshot = self.database.query(
            """
            SELECT fetch_id, discovery_id, source_id, canonical_url, final_url,
                reader, status, error_code, content_hash, content_chars,
                customer_voice_units, fetched_at, metadata
            FROM fetch_attempts ORDER BY source_id, canonical_url, fetched_at
            """
        )
        _write_jsonl_atomic(output, snapshot)
        return {
            "attempted": len(rows),
            "status": dict(sorted(status_counts.items())),
            "snapshot_attempts": len(snapshot),
            "output": str(output.resolve()),
        }

    async def extract_public_feedback(
        self,
        *,
        source_ids: Iterable[str] | None = None,
        refresh: bool = False,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """Extract Vietnamese units from TinyFish-read public page content."""

        if not self.settings.ai_api_key:
            raise ValueError("OPENAI_API_KEY or AI_API_KEY is required for extraction")
        self.initialize()
        supported = {
            source.source_id: source
            for source in self.registry.sources
            if source.source_platform == "public_social"
            or source.source_id == "guardian_web"
        }
        requested = set(source_ids or ())
        unknown = requested - {source.source_id for source in self.registry.sources}
        if unknown:
            raise ValueError("unknown source_id in extraction selection")
        selected_ids = tuple(
            sorted(requested & set(supported) if requested else set(supported))
        )
        if not selected_ids:
            selected_ids = ("__no_supported_sources__",)
        placeholders = ",".join("?" for _ in selected_ids)
        params: list[object] = [*selected_ids]
        refresh_clause = ""
        if not refresh:
            refresh_clause = """
                AND NOT EXISTS (
                    SELECT 1 FROM page_extractions pe
                    WHERE pe.fetch_id = fa.fetch_id
                      AND pe.model_version = ?
                      AND pe.prompt_version = ?
                      AND pe.status IN ('completed', 'no_customer_voice',
                                        'filtered_non_vietnamese',
                                        'filtered_out_of_period',
                                        'skipped_non_atomic')
                )
            """
            params.extend(
                [self.settings.ai_model, PAGE_FEEDBACK_EXTRACTOR_PROMPT_VERSION]
            )
        rows = self.database.query(
            f"""
            SELECT fa.fetch_id, fa.discovery_id, fa.source_id, fa.canonical_url,
                fa.fetched_at, fa.reader, dr.query, pr.title, pr.text_redacted
            FROM fetch_attempts fa
            JOIN discovery_results dr ON dr.discovery_id = fa.discovery_id
            JOIN page_reader_cache pr ON pr.canonical_url = fa.canonical_url
            WHERE fa.status = 'usable'
              AND fa.source_id IN ({placeholders})
              AND fa.fetched_at = (
                  SELECT max(fa2.fetched_at) FROM fetch_attempts fa2
                  WHERE fa2.discovery_id = fa.discovery_id
                    AND fa2.status = 'usable'
              )
              {refresh_clause}
            ORDER BY fa.canonical_url
            """,
            params,
        )
        if limit is not None:
            if limit < 0:
                raise ValueError("extraction limit must not be negative")
            rows = rows[:limit]

        provider = OpenAICompatibleProvider(
            base_url=self.settings.ai_base_url,
            api_key=self.settings.ai_api_key,
            model=self.settings.ai_model,
            timeout_seconds=self.settings.ai_request_timeout_seconds,
        )
        raw_rows: list[RawFeedback] = []
        audit_rows: list[dict[str, Any]] = []
        status_counts: Counter[str] = Counter()
        try:
            for row in rows:
                canonical = str(row["canonical_url"])
                source = supported[str(row["source_id"])]
                is_social = source.source_platform == "public_social"
                platform = (
                    _atomic_social_platform(canonical)
                    if is_social
                    else source.source_platform
                )
                extracted_at = datetime.now(timezone.utc)
                extraction_id = "extraction_" + _sha256(
                    row["fetch_id"], self.settings.ai_model,
                    PAGE_FEEDBACK_EXTRACTOR_PROMPT_VERSION,
                )[:32]
                page_state = "not_attempted"
                status = "failed"
                error_code: str | None = None
                accepted_units = 0
                result_digest: str | None = None
                metadata: dict[str, Any] = {}
                if platform is None or (
                    not is_social and not urlsplit(canonical).path.lower().endswith(".html")
                ):
                    status = "skipped_non_atomic"
                    page_state = "extraction_uncertain"
                    error_code = "stable_container_identity_unavailable"
                else:
                    text = str(row.get("text_redacted") or "").strip()
                    block_batches: list[tuple[PageBlock, ...]] = []
                    if str(row.get("reader") or "") == "tinyfish_agent_public_ui":
                        agent_result = _agent_result_object(text)
                        reviews = agent_result.get("reviews")
                        review_blocks: list[PageBlock] = []
                        if isinstance(reviews, list):
                            for index, review in enumerate(reviews):
                                if not isinstance(review, Mapping):
                                    continue
                                customer_text = str(
                                    review.get("customer_text") or ""
                                ).strip()
                                if not customer_text:
                                    continue
                                block_text = redact_text(
                                    _json(
                                        {
                                            "customer_text": customer_text,
                                            "displayed_date": review.get("displayed_date"),
                                            "displayed_rating": review.get(
                                                "displayed_rating"
                                            ),
                                        }
                                    ),
                                    max_chars=7_900,
                                )
                                container = "review-" + _sha256(
                                    canonical, index, block_text
                                )[:24]
                                review_blocks.append(
                                    PageBlock(
                                        block_id=f"r-{index + 1:04d}",
                                        container_id=container,
                                        parent_block_id=None,
                                        role_hint="customer",
                                        text=block_text,
                                    )
                                )
                        block_batches = [
                            tuple(review_blocks[offset : offset + 50])
                            for offset in range(0, len(review_blocks), 50)
                        ]
                    else:
                        container_id = "atomic-" + _sha256(canonical)[:24]
                        blocks = _page_blocks(text, container_id=container_id)
                        if blocks:
                            block_batches = [blocks]

                    if not block_batches:
                        status = "failed"
                        page_state = "blocked_or_empty"
                        error_code = "empty_page_blocks"
                    else:
                        target_brand = _brand(source.owner_brand)
                        detected_candidates = list(
                            brand_candidates_from_keywords(
                                [
                                    str(row.get("query") or ""),
                                    str(row.get("title") or ""),
                                    text,
                                ]
                            )
                        )
                        candidates = tuple(
                            dict.fromkeys([target_brand, *detected_candidates])
                        )
                        conflicting_candidate = any(
                            candidate in {Brand.GUARDIAN, Brand.HASAKI, Brand.WATSONS}
                            and candidate is not target_brand
                            for candidate in candidates
                        )
                        source_owner_brand = (
                            target_brand
                            if (
                                not is_social
                                or _verified_social_owner(canonical, target_brand)
                            )
                            and not conflicting_candidate
                            else None
                        )
                        result_digests: list[str] = []
                        saw_units = 0
                        non_vietnamese_units = 0
                        out_of_period_units = 0
                        missing_date_units = 0
                        try:
                            for batch_index, blocks in enumerate(block_batches):
                                request = PageExtractionRequest(
                                    page_id=(
                                        f"{row['discovery_id']}:{batch_index + 1}"
                                    ),
                                    source_platform=platform,
                                    source_owner_brand=source_owner_brand,
                                    brand_candidates=candidates,
                                    max_units=min(50, max(1, len(blocks))),
                                    title_redacted=str(row.get("title") or ""),
                                    blocks=blocks,
                                )
                                result = await provider.extract_page(request)
                                if result.units:
                                    page_state = result.page_state.value
                                elif page_state == "not_attempted":
                                    page_state = result.page_state.value
                                result_digests.append(
                                    _sha256(_json(result.model_dump(mode="json")))
                                )
                                saw_units += len(result.units)
                                for unit in result.units:
                                    customer_text = assemble_customer_text(unit)
                                    language = resolve_language(customer_text)
                                    if language.language != "vi":
                                        non_vietnamese_units += 1
                                        continue
                                    occurred_quote = (
                                        unit.occurred_at_span.quote
                                        if unit.occurred_at_span is not None
                                        else None
                                    )
                                    parsed = parse_timestamp(
                                        occurred_quote,
                                        timezone_hint=(
                                            self.settings.voc_business_timezone
                                        ),
                                        observed_at=row["fetched_at"],
                                        quality_hint=OccurredAtQuality.PARSED,
                                    )
                                    if parsed.value is not None and not (
                                        self.period_start
                                        <= parsed.value.date()
                                        <= self.period_end
                                    ):
                                        out_of_period_units += 1
                                        continue
                                    if parsed.value is None:
                                        missing_date_units += 1
                                    seller_replies = [
                                        span.quote for span in unit.seller_response_spans
                                    ]
                                    locator = [
                                        {
                                            "block_id": span.block_id,
                                            "occurrence_index": span.occurrence_index,
                                            "quote": span.quote,
                                        }
                                        for span in unit.customer_text_spans
                                    ]
                                    unit_external_id = "page-unit-" + _sha256(
                                        canonical,
                                        _json(locator),
                                        customer_text,
                                        occurred_quote or "",
                                        (
                                            unit.rating_span.quote
                                            if unit.rating_span is not None
                                            else ""
                                        ),
                                    )[:40]
                                    feedback_metadata: dict[str, Any] = {
                                        "experience_subject": "retailer",
                                        "identity_type": "extracted_unit",
                                        "source_id": row["source_id"],
                                        "extraction_id": extraction_id,
                                        "fetch_id": row["fetch_id"],
                                        "discovery_id": row["discovery_id"],
                                        "extractor_model": self.settings.ai_model,
                                        "extractor_prompt_version": (
                                            PAGE_FEEDBACK_EXTRACTOR_PROMPT_VERSION
                                        ),
                                        "extraction_confidence": (
                                            unit.extraction_confidence
                                        ),
                                        "source_owner_brand": (
                                            source_owner_brand.value
                                            if source_owner_brand is not None
                                            else None
                                        ),
                                        "target_brand": target_brand.value,
                                        "market_scope": source.market_scope,
                                        "business_unit_scope": (
                                            source.business_unit_scope
                                        ),
                                        "period_start": self.period_start.isoformat(),
                                        "period_end": self.period_end.isoformat(),
                                    }
                                    if seller_replies:
                                        feedback_metadata["seller_responses"] = (
                                            seller_replies
                                        )
                                    raw_rows.append(
                                        RawFeedback(
                                            source_external_id=unit_external_id,
                                            source_group=(
                                                SourceGroup.SOCIAL
                                                if is_social
                                                else SourceGroup.OWNED
                                            ),
                                            source_platform=platform,
                                            visibility=Visibility.PUBLIC,
                                            brand=source_owner_brand,
                                            brand_candidates=list(candidates),
                                            occurred_at=parsed.value,
                                            observed_at=row["fetched_at"],
                                            occurred_at_quality=parsed.quality,
                                            original_timezone=parsed.original_timezone,
                                            language="vi",
                                            language_confidence=language.confidence,
                                            title=(
                                                str(row.get("title") or "") or None
                                            ),
                                            text=customer_text,
                                            rating=_rating_from_span(
                                                unit.rating_span.quote
                                                if unit.rating_span is not None
                                                else None
                                            ),
                                            product_name=(
                                                unit.product_name_span.quote
                                                if unit.product_name_span is not None
                                                else (
                                                    str(row.get("title") or "")
                                                    or None
                                                )
                                            ),
                                            source_url=canonical,
                                            message_count=1,
                                            metadata=feedback_metadata,
                                        )
                                    )
                                    accepted_units += 1

                            result_digest = _sha256(*result_digests)
                            metadata.update(
                                {
                                    "detected_language": "vi"
                                    if accepted_units
                                    else None,
                                    "extracted_units": saw_units,
                                    "accepted_units": accepted_units,
                                    "filtered_non_vietnamese": non_vietnamese_units,
                                    "filtered_out_of_period": out_of_period_units,
                                    "missing_date_units": missing_date_units,
                                    "request_batches": len(block_batches),
                                }
                            )
                            if accepted_units:
                                status = "completed"
                            elif saw_units and non_vietnamese_units == saw_units:
                                status = "filtered_non_vietnamese"
                            elif saw_units and out_of_period_units:
                                status = "filtered_out_of_period"
                            else:
                                status = "no_customer_voice"
                        except Exception as exc:
                            status = "failed"
                            page_state = "extraction_uncertain"
                            error_code = type(exc).__name__

                metadata["result_sha256"] = result_digest
                self.database.execute(
                    """
                    INSERT INTO page_extractions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT (extraction_id) DO UPDATE SET
                        page_state = excluded.page_state,
                        status = excluded.status,
                        error_code = excluded.error_code,
                        unit_count = excluded.unit_count,
                        extracted_at = excluded.extracted_at,
                        metadata = excluded.metadata
                    """,
                    [
                        extraction_id,
                        row["fetch_id"],
                        row["discovery_id"],
                        row["source_id"],
                        canonical,
                        page_state,
                        status,
                        error_code,
                        accepted_units,
                        self.settings.ai_model,
                        PAGE_FEEDBACK_EXTRACTOR_PROMPT_VERSION,
                        extracted_at,
                        _json(metadata),
                    ],
                )
                self.database.execute(
                    "UPDATE fetch_attempts SET customer_voice_units = ? WHERE fetch_id = ?",
                    [accepted_units, row["fetch_id"]],
                )
                audit_rows.append(
                    {
                        "extraction_id": extraction_id,
                        "fetch_id": row["fetch_id"],
                        "source_id": row["source_id"],
                        "canonical_url": canonical,
                        "page_state": page_state,
                        "status": status,
                        "error_code": error_code,
                        "unit_count": accepted_units,
                        "model_version": self.settings.ai_model,
                        "prompt_version": PAGE_FEEDBACK_EXTRACTOR_PROMPT_VERSION,
                        "extracted_at": extracted_at.isoformat(),
                    }
                )
                status_counts[status] += 1
        finally:
            await provider.aclose()

        repository = GuardianVocRepository(self.database, settings=self.settings)
        ingestion = await repository.ingest_connector(
            _ExtractedRowsConnector(raw_rows),
            connector_name="page_feedback_extractor",
            source_name="tinyfish_page_feedback_extracted",
            source_group=SourceGroup.SOCIAL,
            metadata={
                "model_version": self.settings.ai_model,
                "prompt_version": PAGE_FEEDBACK_EXTRACTOR_PROMPT_VERSION,
                "vietnamese_only": True,
                "period_start": self.period_start.isoformat(),
                "period_end": self.period_end.isoformat(),
                "source_ids": list(selected_ids),
            },
            raise_on_error=False,
        )
        output = Path(self.settings.voc_data_dir) / "live" / "extractions.jsonl"
        snapshot = self.database.query(
            """
            SELECT extraction_id, fetch_id, discovery_id, source_id,
                canonical_url, page_state, status, error_code, unit_count,
                model_version, prompt_version, extracted_at, metadata
            FROM page_extractions ORDER BY source_id, canonical_url, extracted_at
            """
        )
        _write_jsonl_atomic(output, snapshot)
        return {
            "attempted": len(rows),
            "snapshot_attempts": len(snapshot),
            "status": dict(sorted(status_counts.items())),
            "accepted_units": len(raw_rows),
            "ingestion_run_id": ingestion.id,
            "inserted": ingestion.records_inserted,
            "skipped": ingestion.records_skipped,
            "failed": ingestion.records_failed,
            "output": str(output.resolve()),
        }

    def apply_verified_source_ownership(self) -> dict[str, int]:
        """Apply fixed Guardian ownership only to verified official handles.

        Rows that also carry Hasaki or Watsons candidates remain unresolved so
        source context cannot override an explicit cross-brand conflict.
        Existing analyses are invalidated because brand attribution is part of
        the classifier's trusted input.
        """

        self.initialize()
        updated_ids: list[str] = []
        rows = self.database.query(
            """
            SELECT feedback_id, source_url, brand_candidates
            FROM feedback_items
            WHERE source_group = 'social' AND brand IS NULL
            """
        )
        for row in rows:
            source_url = str(row.get("source_url") or "")
            candidates = {str(item) for item in (row.get("brand_candidates") or [])}
            if not _verified_guardian_social_owner(source_url):
                continue
            if candidates & {Brand.HASAKI.value, Brand.WATSONS.value}:
                continue
            feedback_id = str(row["feedback_id"])
            merged = [Brand.GUARDIAN.value, *sorted(candidates - {Brand.GUARDIAN.value})]
            self.database.execute(
                """
                UPDATE feedback_items
                SET brand = 'guardian', brand_candidates = ?,
                    brand_attribution = 'source_fixed', analysis_status = 'pending'
                WHERE feedback_id = ?
                """,
                [merged, feedback_id],
            )
            self.database.execute(
                "DELETE FROM feedback_analyses WHERE feedback_id = ?",
                [feedback_id],
            )
            updated_ids.append(feedback_id)
        return {"updated": len(updated_ids), "analyses_invalidated": len(updated_ids)}

    def export_analysis_dataset(self) -> dict[str, Any]:
        """Materialize the cumulative PII-redacted item/analysis join as JSONL."""

        self.initialize()
        rows = self.database.query(
            """
            SELECT fi.feedback_id, fi.source_group, fi.source_platform,
                fi.visibility, fi.brand AS source_fixed_brand,
                fa.primary_brand, coalesce(fi.brand, fa.primary_brand) AS resolved_brand,
                fi.brand_candidates, fi.experience_subject AS source_experience_subject,
                fa.experience_subject AS analyzed_experience_subject,
                fi.occurred_at, fi.occurred_at_quality, fi.observed_at,
                fi.language, fi.language_confidence, fi.title, fi.text_redacted,
                fi.rating, fi.product_name, fi.product_category, fi.region,
                fi.store, fi.source_url, fi.canonical_url, fi.content_hash,
                fi.repost_group_id, fi.duplicate_of, fi.analysis_status,
                fa.is_relevant, fa.primary_topic, fa.subtopic, fa.intent,
                fa.sentiment, fa.sentiment_score, fa.urgency,
                fa.customer_stated_reason, fa.journey_stage, fa.evidence_span,
                fa.confidence, fa.model_version, fa.prompt_version,
                fa.taxonomy_version, fa.analyzed_at,
                coalesce((
                    fi.is_synthetic = FALSE
                    AND fi.duplicate_of IS NULL
                    AND fa.is_relevant = TRUE
                    AND coalesce(fi.brand, fa.primary_brand) IS NOT NULL
                    AND fi.occurred_at IS NOT NULL
                    AND fi.occurred_at_quality IN ('exact', 'parsed')
                ), FALSE) AS metric_eligible
            FROM feedback_items fi
            LEFT JOIN feedback_analyses fa ON fa.feedback_id = fi.feedback_id
            WHERE fi.is_synthetic = FALSE
            ORDER BY fi.feedback_id
            """
        )
        output = Path(self.settings.voc_data_dir) / "live" / "analysis_ready.jsonl"
        _write_jsonl_atomic(output, rows)
        return {
            "rows": len(rows),
            "analyzed_rows": sum(row.get("analyzed_at") is not None for row in rows),
            "metric_eligible_rows": sum(bool(row.get("metric_eligible")) for row in rows),
            "output": str(output.resolve()),
        }

    def export_audit_snapshots(self) -> dict[str, Any]:
        """Rewrite cumulative discovery/fetch/extraction audits from DuckDB."""

        self.initialize()
        live_dir = Path(self.settings.voc_data_dir) / "live"
        discovery = self.database.query(
            "SELECT * FROM discovery_results ORDER BY source_id, canonical_url"
        )
        fetches = self.database.query(
            """
            SELECT fetch_id, discovery_id, source_id, canonical_url, final_url,
                reader, status, error_code, content_hash, content_chars,
                customer_voice_units, fetched_at, metadata
            FROM fetch_attempts ORDER BY source_id, canonical_url, fetched_at
            """
        )
        extractions = self.database.query(
            """
            SELECT extraction_id, fetch_id, discovery_id, source_id,
                canonical_url, page_state, status, error_code, unit_count,
                model_version, prompt_version, extracted_at, metadata
            FROM page_extractions ORDER BY source_id, canonical_url, extracted_at
            """
        )
        paths = {
            "discovery": live_dir / "discovery.jsonl",
            "fetches": live_dir / "fetches.jsonl",
            "extractions": live_dir / "extractions.jsonl",
        }
        _write_jsonl_atomic(paths["discovery"], discovery)
        _write_jsonl_atomic(paths["fetches"], fetches)
        _write_jsonl_atomic(paths["extractions"], extractions)
        return {
            "discovery_rows": len(discovery),
            "fetch_attempt_rows": len(fetches),
            "extraction_attempt_rows": len(extractions),
            "outputs": {key: str(path.resolve()) for key, path in paths.items()},
        }

    def build_manifest(self, *, stages: Mapping[str, Any] | None = None) -> dict[str, Any]:
        self.initialize()
        source_rows = self.database.query(
            """
            SELECT sr.source_id, sr.source_platform, sr.acquisition_mode,
                sr.permission_status, sr.tinyfish_policy,
                count(DISTINCT dr.discovery_id) AS discovery_results_total,
                count(DISTINCT CASE
                    WHEN dr.rejection_reason IS NULL
                      OR dr.rejection_reason <> 'off_domain'
                    THEN dr.discovery_id END) AS discovered,
                count(DISTINCT CASE WHEN dr.eligible_for_fetch THEN dr.discovery_id END) AS fetch_eligible,
                count(DISTINCT CASE WHEN fa.status = 'usable' THEN fa.fetch_id END) AS usable_fetches,
                count(DISTINCT CASE WHEN fa.status <> 'usable' THEN fa.fetch_id END) AS failed_fetches,
                count(DISTINCT CASE WHEN pe.status = 'completed' THEN pe.extraction_id END) AS completed_extractions,
                coalesce(sum(CASE WHEN pe.status = 'completed' THEN pe.unit_count ELSE 0 END), 0) AS extracted_customer_units
            FROM source_registry sr
            LEFT JOIN discovery_results dr ON dr.source_id = sr.source_id
            LEFT JOIN fetch_attempts fa ON fa.discovery_id = dr.discovery_id
            LEFT JOIN page_extractions pe ON pe.fetch_id = fa.fetch_id
            GROUP BY ALL ORDER BY sr.source_id
            """
        )
        checkpoint_rows = self.database.query(
            """
            SELECT source_id, checkpoint_value FROM source_checkpoints
            WHERE checkpoint_key = 'review_reconciliation'
            """
        )
        completion_by_source: dict[str, bool] = {}
        for checkpoint in checkpoint_rows:
            value = checkpoint.get("checkpoint_value")
            if isinstance(value, str):
                try:
                    value = json.loads(value)
                except json.JSONDecodeError:
                    value = {}
            completion_by_source[str(checkpoint["source_id"])] = bool(
                value.get("source_complete") if isinstance(value, Mapping) else False
            )
        for source_row in source_rows:
            source_id = str(source_row["source_id"])
            source_row["review_complete"] = (
                completion_by_source.get(source_id, False)
                if source_id in REQUIRED_COMPLETE_REVIEW_SOURCES
                else None
            )
        required_source_completion = {
            source_id: completion_by_source.get(source_id, False)
            for source_id in REQUIRED_COMPLETE_REVIEW_SOURCES
        }
        public_platform_coverage: dict[str, dict[str, int]] = {
            platform: {
                "discovered_urls": 0,
                "usable_fetches": 0,
                "extracted_units": 0,
                "feedback_items": 0,
            }
            for platform in (
                "facebook",
                "instagram",
                "threads",
                "tiktok",
                "youtube",
                "reddit",
            )
        }
        public_discoveries = self.database.query(
            """
            SELECT DISTINCT canonical_url FROM discovery_results
            WHERE source_id IN (
                'guardian_public_social',
                'hasaki_public_social',
                'watsons_public_social'
            )
              AND (rejection_reason IS NULL OR rejection_reason <> 'off_domain')
            """
        )
        for item in public_discoveries:
            platform = _social_platform(str(item["canonical_url"]))
            if platform is not None:
                public_platform_coverage[platform]["discovered_urls"] += 1
        usable_public = self.database.query(
            """
            SELECT DISTINCT canonical_url FROM fetch_attempts
            WHERE source_id IN (
                'guardian_public_social',
                'hasaki_public_social',
                'watsons_public_social'
            ) AND status = 'usable'
            """
        )
        for item in usable_public:
            platform = _social_platform(str(item["canonical_url"]))
            if platform is not None:
                public_platform_coverage[platform]["usable_fetches"] += 1
        extracted_public = self.database.query(
            """
            SELECT canonical_url, max(unit_count) AS units FROM page_extractions
            WHERE source_id IN (
                'guardian_public_social',
                'hasaki_public_social',
                'watsons_public_social'
            ) AND status = 'completed'
            GROUP BY canonical_url
            """
        )
        for item in extracted_public:
            platform = _social_platform(str(item["canonical_url"]))
            if platform is not None:
                public_platform_coverage[platform]["extracted_units"] += int(
                    item["units"] or 0
                )
        public_feedback = self.database.query(
            """
            SELECT source_platform, count(*) AS total FROM feedback_items
            WHERE source_group = 'social' AND is_synthetic = FALSE
            GROUP BY source_platform
            """
        )
        for item in public_feedback:
            platform = str(item["source_platform"])
            if platform in public_platform_coverage:
                public_platform_coverage[platform]["feedback_items"] = int(
                    item["total"]
                )
        feedback = self.database.query_one(
            """
            SELECT count(*) AS total,
                count(CASE WHEN is_synthetic = FALSE THEN 1 END) AS real_records,
                count(CASE
                    WHEN is_synthetic = FALSE
                      AND occurred_at IS NOT NULL
                      AND occurred_at_quality IN ('exact', 'parsed')
                      AND CAST(occurred_at AS DATE) BETWEEN ? AND ?
                    THEN 1 END) AS time_eligible_real_records,
                count(CASE WHEN analysis_status = 'completed' THEN 1 END) AS analyzed
            FROM feedback_items
            """,
            [self.period_start, self.period_end],
        ) or {
            "total": 0,
            "real_records": 0,
            "time_eligible_real_records": 0,
            "analyzed": 0,
        }
        analyses = self.database.query_one(
            """
            SELECT count(*) AS total,
                count(CASE WHEN fa.is_relevant THEN 1 END) AS relevant,
                count(CASE
                    WHEN fa.is_relevant AND fa.primary_brand = 'guardian'
                    THEN 1 END) AS guardian_relevant,
                count(CASE WHEN fi.is_synthetic = FALSE THEN 1 END) AS real_feedback
            FROM feedback_analyses fa
            LEFT JOIN feedback_items fi ON fi.feedback_id = fa.feedback_id
            """
        ) or {
            "total": 0,
            "relevant": 0,
            "guardian_relevant": 0,
            "real_feedback": 0,
        }
        extractions = self.database.query_one(
            """
            SELECT count(*) AS total,
                count(CASE WHEN status = 'completed' THEN 1 END) AS completed,
                coalesce(sum(unit_count), 0) AS accepted_units
            FROM page_extractions
            """
        ) or {"total": 0, "completed": 0, "accepted_units": 0}
        classification_failures = self.database.query_one(
            """
            SELECT count(*) AS total,
                count(CASE WHEN fa.feedback_id IS NULL THEN 1 END) AS unresolved
            FROM classification_failures cf
            LEFT JOIN feedback_analyses fa ON fa.feedback_id = cf.feedback_id
            """
        ) or {"total": 0, "unresolved": 0}
        real_analyzed = int(analyses["real_feedback"])
        analysis_export = self.export_analysis_dataset()
        audit_exports = self.export_audit_snapshots()
        manifest = {
            "schema_version": 1,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "registry_version": self.registry.version,
            "period_start": self.period_start.isoformat(),
            "period_end": self.period_end.isoformat(),
            "locale": "vi-VN",
            "discovery_provider": "serpapi_google",
            "page_reader": "tinyfish_fetch",
            "classification_model": self.settings.ai_model,
            "extraction_model": self.settings.ai_model,
            "extraction_prompt_version": PAGE_FEEDBACK_EXTRACTOR_PROMPT_VERSION,
            "extraction_executed": int(extractions["total"]) > 0,
            "classification_executed": int(analyses["total"]) > 0,
            "analysis_pipeline_operational": real_analyzed > 0,
            "target_unique_feedback_items": TARGET_UNIQUE_FEEDBACK_ITEMS,
            "analysis_dataset": analysis_export,
            "audit_datasets": audit_exports,
            "active_default_sources": [
                source.source_id for source in self.registry.sources
            ],
            "explicitly_excluded_sources": [
                source.source_id for source in self.registry.excluded_sources
            ],
            "required_review_source_completion": required_source_completion,
            "public_social_platform_coverage": public_platform_coverage,
            "sources": source_rows,
            "counts": {
                "feedback_items": int(feedback["total"]),
                "real_feedback_items": int(feedback["real_records"]),
                "time_eligible_real_feedback_items": int(
                    feedback["time_eligible_real_records"]
                ),
                "analyzed_feedback_items": int(feedback["analyzed"]),
                "analysis_rows": int(analyses["total"]),
                "relevant_analysis_rows": int(analyses["relevant"]),
                "guardian_relevant_analysis_rows": int(
                    analyses["guardian_relevant"]
                ),
                "real_feedback_analysis_rows": int(analyses["real_feedback"]),
                "page_extraction_attempts": int(extractions["total"]),
                "completed_page_extractions": int(extractions["completed"]),
                "extracted_customer_units": int(extractions["accepted_units"]),
                "classification_failures": int(classification_failures["total"]),
                "unresolved_classification_failures": int(
                    classification_failures["unresolved"]
                ),
            },
            "ready_for_analysis": bool(
                int(feedback["real_records"]) >= TARGET_UNIQUE_FEEDBACK_ITEMS
                and real_analyzed >= TARGET_UNIQUE_FEEDBACK_ITEMS
                and int(feedback["time_eligible_real_records"])
                >= TARGET_UNIQUE_FEEDBACK_ITEMS
                and int(classification_failures["unresolved"]) == 0
                and all(required_source_completion.values())
            ),
            "readiness_gates": {
                "target_unique_feedback_items": TARGET_UNIQUE_FEEDBACK_ITEMS,
                "real_feedback_items": int(feedback["real_records"]),
                "real_analyzed_feedback_items": real_analyzed,
                "time_eligible_real_feedback_items": int(
                    feedback["time_eligible_real_records"]
                ),
                "unresolved_classification_failures": int(
                    classification_failures["unresolved"]
                ),
                "target_met": (
                    int(feedback["real_records"]) >= TARGET_UNIQUE_FEEDBACK_ITEMS
                    and real_analyzed >= TARGET_UNIQUE_FEEDBACK_ITEMS
                    and int(feedback["time_eligible_real_records"])
                    >= TARGET_UNIQUE_FEEDBACK_ITEMS
                ),
                "all_required_review_sources_complete": all(
                    required_source_completion.values()
                ),
            },
            "stages": dict(stages or {}),
            "completion_rule": (
                "This run is public best-effort and does not claim source exhaustiveness. "
                "Readiness requires 2,000 unique, analyzed, Vietnamese, date-eligible records."
            ),
            "limitations": [
                "SERP titles and snippets are discovery evidence only and never feedback.",
                "TinyFish Fetch content is page enrichment, not proof of exhaustive review coverage.",
                "Public social extraction is limited to atomic post URLs; comments hidden behind login or interaction walls are not claimed complete.",
                "Guardian product pages blocked in Fetch may use the credit-bearing TinyFish Agent public-UI fallback without login or access-control bypass.",
                "Shopee, Lazada, and TikTok Shop are explicitly excluded from this run.",
                "GrabMart remains authorized-export-only and is not represented as review-complete.",
            ],
        }
        output = Path(self.settings.voc_data_dir) / "live_data_manifest.json"
        manifest["output"] = str(output.resolve())
        _write_json_atomic(output, manifest)
        return manifest

    async def run(
        self,
        *,
        source_ids: Iterable[str] | None = None,
        pages_per_query: int = 1,
        fetch_limit: int | None = None,
        extraction_limit: int | None = None,
        extract_public: bool = True,
        refresh: bool = False,
        guardian_catalog_path: str | Path | None = None,
        tinyfish_agent: bool = False,
        tinyfish_agent_limit: int | None = None,
        tinyfish_agent_concurrency: int = 3,
        discover_enabled: bool = True,
        fetch_enabled: bool = True,
    ) -> dict[str, Any]:
        stages: dict[str, Any] = {}
        if guardian_catalog_path is not None:
            stages["guardian_catalog_seed"] = self.seed_guardian_catalog(
                guardian_catalog_path
            )
        if discover_enabled:
            stages["discover"] = await self.discover(
                source_ids=source_ids,
                pages_per_query=pages_per_query,
            )
        if fetch_enabled:
            stages["fetch"] = await self.fetch(
                source_ids=source_ids,
                refresh=refresh,
                limit=fetch_limit,
            )
        selected = set(source_ids or ())
        if tinyfish_agent and (not selected or "guardian_web" in selected):
            stages["tinyfish_agent"] = (
                await self.fetch_guardian_reviews_with_agent(
                    refresh=refresh,
                    limit=tinyfish_agent_limit,
                    concurrency=tinyfish_agent_concurrency,
                )
            )
        if extract_public:
            stages["extract"] = await self.extract_public_feedback(
                source_ids=source_ids,
                refresh=refresh,
                limit=extraction_limit,
            )
        return self.build_manifest(stages=stages)


__all__ = [
    "DEFAULT_PERIOD_END",
    "DEFAULT_PERIOD_START",
    "LiveDataLayer",
    "PUBLIC_SOCIAL_SOURCE_IDS",
    "REQUIRED_COMPLETE_REVIEW_SOURCES",
    "TARGET_UNIQUE_FEEDBACK_ITEMS",
]
