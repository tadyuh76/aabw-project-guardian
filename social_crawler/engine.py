from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from social_crawler.config import (
    SOCIAL_PLATFORMS,
    TELEGRAM_DOMAINS,
    VIETNAM_PLATFORMS,
    resolve_platform_domains,
)
from social_crawler.scrapers import ScrapedMention, scrape_social_description
from social_crawler.serpapi import (
    SerpApiClient,
    filter_organic_results_by_domains,
    has_valid_organic_results,
)


logger = logging.getLogger(__name__)

_AND_SPLIT_RE = re.compile(r"\s+(?:and|&)\s+", re.IGNORECASE)
_QUOTED_TOKEN_RE = re.compile(r'"([^"]+)"')
_MAX_KEYWORDS = 20
_MAX_KEYWORD_LENGTH = 500


class SearchClient(Protocol):
    async def google_search(
        self,
        *,
        query: str,
        tbs: str | None = None,
        start: int = 0,
        no_cache: bool = False,
    ) -> dict[str, Any]: ...


class PageReader(Protocol):
    async def read(self, url: str, *, platform: str | None = None) -> Any: ...


PLATFORM_DOMAINS_MAP: dict[str, str] = {}
for _name, _domains in SOCIAL_PLATFORMS.items():
    for _domain in _domains:
        PLATFORM_DOMAINS_MAP[_domain] = _name.capitalize()
for _domain in TELEGRAM_DOMAINS:
    PLATFORM_DOMAINS_MAP[_domain] = "Telegram"
for _name, _domains in VIETNAM_PLATFORMS.items():
    for _domain in _domains:
        PLATFORM_DOMAINS_MAP[_domain] = _name.capitalize()


@dataclass(frozen=True)
class QueryPlan:
    keyword: str
    pool: str
    domains: list[str]
    query: str
    tbs: str | None
    start: int = 0

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Mention:
    record_id: str
    keywords: list[str]
    platform: str
    title: str
    description: str
    link: str
    published_date: str | None
    scraper_source: str
    bucket_start: str
    bucket_end: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CrawlResult:
    bucket_start: str
    bucket_end: str
    keywords: list[str]
    platforms: list[str]
    requests_made: int
    mentions: list[Mention] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "bucket_start": self.bucket_start,
            "bucket_end": self.bucket_end,
            "keywords": self.keywords,
            "platforms": self.platforms,
            "requests_made": self.requests_made,
            "mentions_found": len(self.mentions),
            "errors": self.errors,
            "mentions": [mention.as_dict() for mention in self.mentions],
        }


def normalize_keyword_value(raw: str) -> str:
    """Match the API's stored keyword form, including AND-style authoring."""
    value = raw.strip().lower()
    quoted = [part.strip() for part in _QUOTED_TOKEN_RE.findall(value) if part.strip()]
    if len(quoted) > 1 and _QUOTED_TOKEN_RE.sub("", value).strip() == "":
        return " ".join(f'"{part}"' for part in quoted)

    parts = [part.strip() for part in _AND_SPLIT_RE.split(value) if part.strip()]
    if len(parts) <= 1:
        return value
    return " ".join(f'"{part}"' for part in parts)


def normalize_keywords(keywords: list[str] | tuple[str, ...]) -> list[str]:
    normalized = [normalize_keyword_value(keyword) for keyword in keywords]
    unique = list(dict.fromkeys(keyword for keyword in normalized if keyword))
    if len(unique) > _MAX_KEYWORDS:
        raise ValueError(f"A maximum of {_MAX_KEYWORDS} keywords is allowed per run")
    if any(len(keyword) > _MAX_KEYWORD_LENGTH for keyword in unique):
        raise ValueError(f"Keywords must be {_MAX_KEYWORD_LENGTH} characters or fewer")
    return unique


def detect_platform(link: str) -> str:
    lower = link.lower()
    for domain, name in PLATFORM_DOMAINS_MAP.items():
        if domain in lower:
            return name
    return "Other"


def format_keyword(keyword: str) -> str:
    if '"' in keyword:
        return keyword
    return f'"{keyword}"'


def build_site_query(keywords: list[str], domains: list[str]) -> str:
    formatted = [format_keyword(keyword) for keyword in keywords]
    if not formatted:
        raise ValueError("At least one keyword is required")
    if not domains:
        raise ValueError("At least one domain is required")
    keyword_part = (
        formatted[0]
        if len(formatted) == 1
        else "(" + " OR ".join(f"({item})" if item.count('"') > 2 else item for item in formatted) + ")"
    )
    site_part = "(" + " | ".join(f"site:{domain}" for domain in domains) + ")"
    return f"{keyword_part} {site_part}"


def _format_serpapi_date(value: datetime) -> str:
    return f"{value.month}/{value.day}/{value.year}"


def build_bucket_tbs(bucket_start: datetime, bucket_end: datetime) -> str:
    return (
        "cdr:1,"
        f"cd_min:{_format_serpapi_date(bucket_start)},"
        f"cd_max:{_format_serpapi_date(bucket_end)},"
        "sbd:1"
    )


def mention_record_id(platform: str | None, link: str | None, title: str | None) -> str:
    joined = "|".join(["mention", platform or "", link or "", title or ""])
    hash_value = 2166136261
    encoded = joined.encode("utf-16-le")
    for index in range(0, len(encoded), 2):
        code = encoded[index] | (encoded[index + 1] << 8)
        hash_value ^= code
        hash_value = (hash_value * 16777619) & 0xFFFFFFFF
    if hash_value == 0:
        return "0"
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    output = ""
    while hash_value > 0:
        output = digits[hash_value % 36] + output
        hash_value //= 36
    return output


def build_crawl_plan(
    keywords: list[str] | tuple[str, ...],
    platforms: list[str] | tuple[str, ...],
    *,
    bucket_start: datetime,
    bucket_end: datetime,
) -> list[QueryPlan]:
    normalized_keywords = normalize_keywords(keywords)
    timed_domains, untimed_domains = resolve_platform_domains(platforms)
    tbs = build_bucket_tbs(bucket_start, bucket_end)
    plans: list[QueryPlan] = []
    for keyword in normalized_keywords:
        if timed_domains:
            plans.append(
                QueryPlan(
                    keyword=keyword,
                    pool="timed",
                    domains=timed_domains,
                    query=build_site_query([keyword], timed_domains),
                    tbs=tbs,
                )
            )
        if untimed_domains:
            plans.append(
                QueryPlan(
                    keyword=keyword,
                    pool="untimed",
                    domains=untimed_domains,
                    query=build_site_query([keyword], untimed_domains),
                    tbs=None,
                )
            )
    return plans


async def _fetch_plan(
    client: SearchClient,
    plan: QueryPlan,
    *,
    no_cache: bool,
    semaphore: asyncio.Semaphore,
) -> tuple[QueryPlan, dict[str, Any] | None, str | None]:
    try:
        async with semaphore:
            response = await client.google_search(
                query=plan.query,
                tbs=plan.tbs,
                start=plan.start,
                no_cache=no_cache,
            )
        return plan, response, None
    except Exception as exc:
        # HTTP client exceptions can contain the full request URL, including
        # SerpAPI's query-string API key. Keep logs and output secret-free.
        error_name = type(exc).__name__
        logger.warning(
            "SerpAPI request failed for %r (%s): %s",
            plan.keyword,
            plan.pool,
            error_name,
        )
        return plan, None, f"{plan.keyword} ({plan.pool}): {error_name}"


async def crawl(
    *,
    api_key: str,
    api_base_url: str,
    keywords: list[str] | tuple[str, ...],
    platforms: list[str] | tuple[str, ...] = ("all",),
    lookback_hours: float = 24,
    no_cache: bool = True,
    use_browser: bool = True,
    search_concurrency: int = 4,
    bucket_end: datetime | None = None,
    search_client: SearchClient | None = None,
    page_reader: PageReader | None = None,
) -> CrawlResult:
    if lookback_hours <= 0:
        raise ValueError("lookback_hours must be greater than zero")
    if search_concurrency <= 0:
        raise ValueError("search_concurrency must be greater than zero")

    normalized_keywords = normalize_keywords(keywords)
    if not normalized_keywords:
        raise ValueError("At least one keyword is required")

    end = bucket_end or datetime.now(timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    else:
        end = end.astimezone(timezone.utc)
    start = end - timedelta(hours=lookback_hours)
    plans = build_crawl_plan(normalized_keywords, platforms, bucket_start=start, bucket_end=end)

    owned_client = (
        SerpApiClient(api_key=api_key, base_url=api_base_url)
        if search_client is None
        else None
    )
    client = search_client or owned_client
    assert client is not None
    semaphore = asyncio.Semaphore(search_concurrency)
    try:
        responses = await asyncio.gather(
            *(
                _fetch_plan(
                    client,
                    plan,
                    no_cache=no_cache,
                    semaphore=semaphore,
                )
                for plan in plans
            )
        )
    finally:
        if owned_client is not None:
            await owned_client.aclose()

    result = CrawlResult(
        bucket_start=start.isoformat(),
        bucket_end=end.isoformat(),
        keywords=normalized_keywords,
        platforms=list(platforms),
        requests_made=len(plans),
    )
    seen_by_record: dict[str, int] = {}
    seen_by_content: dict[tuple[str, str], int] = {}

    for plan, payload, error in responses:
        if error:
            result.errors.append(error)
            continue
        if payload is None or not has_valid_organic_results(payload):
            continue

        raw_organic = payload.get("organic_results", []) or []
        if not isinstance(raw_organic, list):
            result.errors.append(f"{plan.keyword} ({plan.pool}): invalid SerpAPI response")
            continue
        organic = filter_organic_results_by_domains(raw_organic, plan.domains)
        for item in organic:
            link = str(item.get("link") or "")
            if not link:
                continue
            platform = detect_platform(link)
            if page_reader is None:
                scraped = await scrape_social_description(
                    platform=platform,
                    link=link,
                    fallback_title=str(item.get("title") or link),
                    fallback_description=str(item.get("snippet") or ""),
                    use_browser=use_browser,
                )
            else:
                try:
                    page = await page_reader.read(link, platform=platform)
                    page_title = page.title if isinstance(page.title, str) else ""
                    page_text = page.text if isinstance(page.text, str) else ""
                    page_source = page.reader if isinstance(page.reader, str) else ""
                    scraped = ScrapedMention(
                        title=page_title,
                        description=page_text,
                        source=page_source or "page_reader",
                    )
                except Exception:
                    # Optional page enrichment must never discard a discovered
                    # canonical URL or expose provider exception details.
                    scraped = ScrapedMention()
            title = scraped.title or str(item.get("title") or link)
            description = scraped.description or str(item.get("snippet") or "")
            record_id = mention_record_id(platform, link, title)
            content_key = (title, description)
            existing_index = seen_by_record.get(record_id)
            if existing_index is None:
                existing_index = seen_by_content.get(content_key)
            if existing_index is not None:
                existing = result.mentions[existing_index]
                if plan.keyword not in existing.keywords:
                    existing.keywords.append(plan.keyword)
                continue

            mention = Mention(
                record_id=record_id,
                keywords=[plan.keyword],
                platform=platform,
                title=title,
                description=description,
                link=link,
                published_date=str(item.get("date")) if item.get("date") else None,
                scraper_source=scraped.source,
                bucket_start=start.isoformat(),
                bucket_end=end.isoformat(),
            )
            index = len(result.mentions)
            result.mentions.append(mention)
            seen_by_record[record_id] = index
            seen_by_content[content_key] = index

    return result
