"""Adapter from the preserved ``social_crawler`` package to RawFeedback."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from guardian_voc.config import Settings, get_settings
from guardian_voc.connectors.page_reader import (
    CachedPageReader,
    FallbackPageReader,
    MetadataPageReader,
    PageContent,
    PageReader,
    TinyFishPageReader,
)
from guardian_voc.pipeline.dedupe import canonicalize_url, content_hash, sha256_hex
from guardian_voc.pipeline.normalize import parse_timestamp
from guardian_voc.schemas.feedback import (
    Brand,
    ExperienceSubject,
    IngestionRun,
    OccurredAtQuality,
    RawFeedback,
    SourceGroup,
    Visibility,
)


_BRAND_PATTERNS: dict[Brand, re.Pattern[str]] = {
    Brand.GUARDIAN: re.compile(r"(?<!\w)guardian(?!\w)", re.IGNORECASE),
    Brand.HASAKI: re.compile(r"(?<!\w)hasaki(?!\w)", re.IGNORECASE),
    Brand.WATSONS: re.compile(r"(?<!\w)watsons?(?!\w)", re.IGNORECASE),
}

# ``description`` is overloaded by the preserved crawler: it can be content
# read from the canonical page or a SerpAPI snippet used as a final fallback.
# Only explicit reader sources may promote it to customer feedback.
_PAGE_READER_SOURCE_PREFIXES = (
    "browser",
    "facebook_",
    "metadata",
    "page_reader",
    "reddit_",
    "telegram_",
    "telemetr",
    "tiktok_",
    "tinyfish",
)
_DISCOVERY_SOURCE_PREFIXES = (
    "discovery",
    "google_search",
    "search_result",
    "serpapi",
    "tinyfish_search",
)
_FEEDBACK_ID_RE = re.compile(r"^feedback_[0-9a-f]{32}$")
_CONTENT_HASH_RE = re.compile(r"^[0-9a-f]{64}$")


def _mapping(value: object) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    if hasattr(value, "as_dict"):
        result = value.as_dict()
        if isinstance(result, Mapping):
            return {str(key): item for key, item in result.items()}
    if is_dataclass(value):
        return asdict(value)
    raise TypeError(f"crawler record must be a mapping, got {type(value).__name__}")


def _keywords(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        # Do not split multi-word queries, only common serialized list forms.
        if value.startswith("["):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                pass
            else:
                if isinstance(parsed, list):
                    return [str(item).strip() for item in parsed if str(item).strip()]
        return [value.strip()] if value.strip() else []
    if isinstance(value, Iterable):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()]


def brand_candidates_from_keywords(keywords: Iterable[str]) -> list[Brand]:
    """Retain every brand matched by discovery, never only the first query."""

    combined = "\n".join(str(keyword) for keyword in keywords)
    candidates = [
        brand for brand, pattern in _BRAND_PATTERNS.items() if pattern.search(combined)
    ]
    return candidates or [Brand.OTHER]


def _record_brand_candidates(raw: Mapping[str, Any], keywords: Iterable[str]) -> list[Brand]:
    """Prefer evidence-derived crawler candidates over discovery-query hints."""

    allowed = {brand.value: brand for brand in Brand}
    values = raw.get("brand_candidates")
    if isinstance(values, list):
        candidates = list(
            dict.fromkeys(
                allowed[str(item).strip().lower()]
                for item in values
                if str(item).strip().lower() in allowed
            )
        )
        if candidates:
            return candidates
    return brand_candidates_from_keywords(keywords)


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _reader_mapping(value: object) -> dict[str, Any] | None:
    if value is None:
        return None
    try:
        return _mapping(value)
    except TypeError:
        return None


def _content_from_reader(
    raw: Mapping[str, Any],
) -> tuple[str, str | None, str, dict[str, Any] | None] | None:
    """Return page-extracted content, never search-result copy.

    SerpAPI backfills put result titles/snippets in ``title`` and
    ``description``.  Those fields are discovery evidence, not the underlying
    post.  An explicit extraction field or allowlisted page-reader provenance
    is required before content can cross the RawFeedback boundary.
    """

    explicit_text = _text(raw.get("extracted_text")) or _text(
        raw.get("page_reader_text")
    )
    if explicit_text:
        title = _text(raw.get("extracted_title")) or _text(
            raw.get("page_reader_title")
        )
        source = (
            _text(raw.get("extraction_source"))
            or _text(raw.get("page_reader_source"))
            or "extracted_text"
        )
        metadata = _reader_mapping(raw.get("page_reader_metadata"))
        return explicit_text, title or None, source, metadata

    for key in ("page_reader_result", "page_reader"):
        reader = _reader_mapping(raw.get(key))
        if reader is None:
            continue
        reader_text = _text(reader.get("text")) or _text(
            reader.get("extracted_text")
        )
        if not reader_text:
            continue
        title = _text(reader.get("title")) or _text(reader.get("extracted_title"))
        source = _text(reader.get("reader")) or _text(reader.get("source")) or key
        metadata = _reader_mapping(reader.get("metadata"))
        return reader_text, title or None, source, metadata

    scraper_source = _text(raw.get("scraper_source")).lower()
    if scraper_source.startswith(_DISCOVERY_SOURCE_PREFIXES):
        return None
    if scraper_source.startswith(_PAGE_READER_SOURCE_PREFIXES):
        reader_text = _text(raw.get("description"))
        if reader_text:
            return reader_text, _text(raw.get("title")) or None, scraper_source, None
    return None


def _discovery_provenance(
    raw: Mapping[str, Any],
    *,
    top_level: Mapping[str, Any],
) -> dict[str, Any]:
    """Keep search evidence auditable without treating it as customer voice."""

    return {
        "crawler_record_id": (
            str(raw["record_id"]) if raw.get("record_id") is not None else None
        ),
        "source_url": _text(raw.get("canonical_url") or raw.get("link")) or None,
        "platform": _text(raw.get("platform")).lower() or "other",
        "discovery_title": _text(raw.get("title")) or None,
        "discovery_description": _text(raw.get("description")) or None,
        "discovery_keywords": _keywords(
            raw.get("keywords") or top_level.get("keywords")
        ),
        "scraper_source": raw.get("scraper_source"),
        "reason": "no_explicit_page_content",
    }


def map_social_record(
    record: Mapping[str, Any] | object,
    *,
    observed_default: datetime,
    business_timezone: str = "Asia/Ho_Chi_Minh",
    top_level: Mapping[str, Any] | None = None,
) -> RawFeedback | None:
    raw = _mapping(record)
    top_level = top_level or {}
    observed_raw = (
        raw.get("observed_at")
        or raw.get("bucket_end")
        or top_level.get("bucket_end")
    )
    observed = parse_timestamp(observed_raw, timezone_hint=business_timezone)
    observed_at = observed.value or observed_default
    occurred = parse_timestamp(
        raw.get("published_date"),
        timezone_hint=business_timezone,
        observed_at=observed_at,
    )
    keywords = _keywords(raw.get("keywords") or top_level.get("keywords"))
    brand_candidates = _record_brand_candidates(raw, keywords)
    content = _content_from_reader(raw)
    if content is None:
        return None
    text, title, content_source, reader_metadata = content
    metadata = {
        "crawler_record_id": (
            str(raw["record_id"]) if raw.get("record_id") is not None else None
        ),
        "discovery_keywords": keywords,
        "scraper_source": raw.get("scraper_source"),
        "bucket_start": raw.get("bucket_start") or top_level.get("bucket_start"),
        "bucket_end": raw.get("bucket_end") or top_level.get("bucket_end"),
        "experience_subject": "retailer",
        # Query candidates are discovery provenance, never attribution proof.
        "query_brand_candidates": _keywords(raw.get("query_brand_candidates")),
        "matched_query_ids": _keywords(raw.get("matched_query_ids")),
        "matched_query_labels_vi": _keywords(raw.get("matched_query_labels_vi")),
        "topics": _keywords(raw.get("topics")),
        "has_brand_evidence": bool(raw.get("has_brand_evidence", False)),
        "source_author_type": raw.get("source_author_type"),
        "search_stages": _keywords(raw.get("search_stages")),
        "search_buckets": _keywords(raw.get("search_buckets")),
        "eligible_for_time_analytics": bool(
            raw.get("eligible_for_time_analytics", occurred.value is not None)
        ),
        "content_provenance": {
            "kind": "page_reader",
            "source": content_source,
        },
        # Search-result copy remains discovery provenance and is never joined
        # into feedback text.  ``title`` above is reader-supplied only.
        "discovery_title": _text(raw.get("title")) or None,
        "discovery_description": _text(raw.get("description")) or None,
    }
    if reader_metadata is not None:
        metadata["page_reader_metadata"] = reader_metadata
    if occurred.error:
        metadata["occurred_at_parse_warning"] = occurred.error

    return RawFeedback(
        # Crawler record_id is title-dependent and must never outrank URL.
        source_external_id=None,
        source_group=SourceGroup.SOCIAL,
        source_platform=str(raw.get("platform") or "other").strip().lower(),
        visibility=Visibility.PUBLIC,
        brand=None,
        brand_candidates=brand_candidates,
        occurred_at=occurred.value,
        observed_at=observed_at,
        occurred_at_quality=occurred.quality,
        original_timezone=occurred.original_timezone,
        title=title,
        text=text,
        source_url=str(raw.get("canonical_url") or raw.get("link") or "").strip()
        or None,
        media_urls=[str(item) for item in raw.get("media_urls", [])]
        if isinstance(raw.get("media_urls"), list)
        else [],
        metadata=metadata,
        is_synthetic=bool(raw.get("is_synthetic", False)),
    )


def _export_optional_text(
    raw: Mapping[str, Any], key: str, *, limit: int
) -> str | None:
    value = raw.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"verified export field {key} must be text or null")
    value = value.strip()
    if len(value) > limit:
        raise ValueError(f"verified export field {key} exceeds its size limit")
    return value or None


def map_verified_feedback_export(
    record: Mapping[str, Any] | object,
    *,
    business_timezone: str = "Asia/Ho_Chi_Minh",
) -> RawFeedback:
    """Validate the PII-redacted analysis export and rebuild ``RawFeedback``.

    This is intentionally separate from :func:`map_social_record`. Search
    result titles and snippets therefore cannot gain trust merely by matching
    some of these field names. Only the explicitly configured verified-export
    watcher calls this adapter.

    Previously generated classifier fields are deliberately ignored. The
    returned canonical row crosses the normal ingestion boundary with
    ``analysis_status=pending`` and is classified by the currently configured
    model as part of the ordinary import pipeline.
    """

    raw = _mapping(record)
    feedback_id = _export_optional_text(raw, "feedback_id", limit=100)
    if feedback_id is None or _FEEDBACK_ID_RE.fullmatch(feedback_id) is None:
        raise ValueError("verified export feedback_id is invalid")

    supplied_hash = _export_optional_text(raw, "content_hash", limit=64)
    if supplied_hash is None or _CONTENT_HASH_RE.fullmatch(supplied_hash) is None:
        raise ValueError("verified export content_hash is invalid")

    if "text_redacted" not in raw:
        raise ValueError("verified export text_redacted is required")
    text = _export_optional_text(raw, "text_redacted", limit=100_000)
    if text is None:
        raise ValueError("verified export text_redacted must not be empty")
    title = _export_optional_text(raw, "title", limit=2_000)
    if content_hash(title=title, text=text) != supplied_hash:
        raise ValueError("verified export content_hash does not match redacted content")

    synthetic_value = raw.get("is_synthetic")
    if synthetic_value is not None and synthetic_value is not False:
        raise ValueError("synthetic rows are not accepted from verified exports")

    try:
        source_group = SourceGroup(str(raw["source_group"]).strip().lower())
        visibility = Visibility(str(raw["visibility"]).strip().lower())
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("verified export source group or visibility is invalid") from exc

    source_platform = _export_optional_text(raw, "source_platform", limit=100)
    if source_platform is None or any(ord(char) < 32 for char in source_platform):
        raise ValueError("verified export source_platform is invalid")
    source_platform = source_platform.lower()

    source_url_value = _export_optional_text(raw, "source_url", limit=8_192)
    canonical_url_value = _export_optional_text(raw, "canonical_url", limit=8_192)
    source_url = canonicalize_url(source_url_value)
    exported_canonical_url = canonicalize_url(canonical_url_value)
    if source_url_value is not None and source_url is None:
        raise ValueError("verified export source_url is invalid")
    if canonical_url_value is not None and (
        exported_canonical_url is None
        or exported_canonical_url != canonical_url_value
    ):
        raise ValueError("verified export canonical_url is not canonical")
    if source_url and exported_canonical_url and source_url != exported_canonical_url:
        raise ValueError("verified export source URLs do not identify the same record")
    canonical_url = exported_canonical_url or source_url
    if source_group is SourceGroup.SOCIAL:
        if visibility is not Visibility.PUBLIC or canonical_url is None:
            raise ValueError("verified social feedback requires a public canonical URL")
        identity_digest = sha256_hex("url\0" + canonical_url)
        expected_feedback_id = f"feedback_{identity_digest[:32]}"
        if feedback_id != expected_feedback_id:
            raise ValueError("verified export feedback_id does not match its source URL")

    observed_raw = raw.get("observed_at")
    if not isinstance(observed_raw, (str, datetime)):
        raise ValueError("verified export observed_at is required")
    observed = parse_timestamp(observed_raw, timezone_hint=business_timezone)
    if observed.value is None:
        raise ValueError("verified export observed_at is invalid")

    occurred_raw = raw.get("occurred_at")
    occurred = parse_timestamp(
        occurred_raw,
        timezone_hint=business_timezone,
        observed_at=observed.value,
    )
    if occurred_raw is not None and occurred.value is None:
        raise ValueError("verified export occurred_at is invalid")
    try:
        occurred_quality = OccurredAtQuality(
            str(raw["occurred_at_quality"]).strip().lower()
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("verified export occurred_at_quality is invalid") from exc
    if (occurred.value is None) != (occurred_quality is OccurredAtQuality.MISSING):
        raise ValueError("verified export occurrence time and quality disagree")

    candidates_raw = raw.get("brand_candidates")
    if not isinstance(candidates_raw, list):
        raise ValueError("verified export brand_candidates must be a list")
    try:
        brand_candidates = list(
            dict.fromkeys(Brand(str(value).strip().lower()) for value in candidates_raw)
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("verified export brand_candidates contains an invalid brand") from exc
    fixed_brand_raw = raw.get("source_fixed_brand")
    try:
        fixed_brand = (
            None
            if fixed_brand_raw is None
            else Brand(str(fixed_brand_raw).strip().lower())
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("verified export source_fixed_brand is invalid") from exc
    if fixed_brand is None and not brand_candidates:
        raise ValueError("verified export requires source brand evidence")

    try:
        experience_subject = ExperienceSubject(
            str(raw["source_experience_subject"]).strip().lower()
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("verified export source_experience_subject is invalid") from exc

    language = _export_optional_text(raw, "language", limit=32)
    language_confidence = raw.get("language_confidence")
    if language_confidence is not None and (
        isinstance(language_confidence, bool)
        or not isinstance(language_confidence, (int, float))
    ):
        raise ValueError("verified export language_confidence is invalid")

    metadata = {
        "strict_export_feedback_id": feedback_id,
        "strict_export_content_hash": supplied_hash,
        "strict_extraction_verified": True,
        "content_provenance": {
            "kind": "strict_page_extraction",
            "source": "verified_feedback_export",
        },
        "experience_subject": experience_subject.value,
    }
    if canonical_url is not None:
        metadata["identity_type"] = "canonical_url"

    return RawFeedback(
        source_external_id=feedback_id,
        source_group=source_group,
        source_platform=source_platform,
        visibility=visibility,
        # Source-fixed attribution is trusted; historical classifier outputs
        # such as primary_brand/resolved_brand are never promoted here.
        brand=fixed_brand,
        brand_candidates=brand_candidates,
        occurred_at=occurred.value,
        observed_at=observed.value,
        occurred_at_quality=occurred_quality,
        original_timezone=occurred.original_timezone,
        language=language,
        language_confidence=(
            float(language_confidence) if language_confidence is not None else None
        ),
        title=title,
        text=text,
        rating=raw.get("rating"),
        product_name=_export_optional_text(raw, "product_name", limit=1_000),
        product_category=_export_optional_text(raw, "product_category", limit=500),
        region=_export_optional_text(raw, "region", limit=500),
        store=_export_optional_text(raw, "store", limit=500),
        source_url=canonical_url,
        metadata=metadata,
        is_synthetic=False,
    )


def load_crawler_records(
    path: str | Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    path = Path(path)
    if path.suffix.lower() in {".jsonl", ".ndjson"}:
        records: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8-sig") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    records.append(_mapping(json.loads(line)))
                except (json.JSONDecodeError, TypeError) as exc:
                    raise ValueError(f"invalid crawler JSONL at line {line_number}") from exc
        return records, {}

    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid crawler JSON: {exc.msg}") from exc
    if isinstance(payload, Mapping):
        top = {str(key): value for key, value in payload.items() if key != "mentions"}
        mentions = payload.get("mentions")
        if isinstance(mentions, list):
            return [_mapping(item) for item in mentions], top
        return [_mapping(payload)], {}
    if isinstance(payload, list):
        return [_mapping(item) for item in payload], {}
    raise ValueError("crawler JSON must contain an object or list")


class SocialCrawlerConnector:
    """Import a CrawlResult, crawler record iterable, or saved JSON/JSONL."""

    def __init__(
        self,
        source: object,
        *,
        settings: Settings | None = None,
    ) -> None:
        self.source = source
        self.settings = settings or get_settings()
        self.errors: list[str] = []
        self.discoveries: list[dict[str, Any]] = []

    def _preserve_errors(self, value: object) -> None:
        if isinstance(value, str):
            candidates: Iterable[object] = [value]
        elif isinstance(value, Iterable):
            candidates = value
        else:
            return
        for candidate in candidates:
            message = str(candidate).strip()
            if message and message not in self.errors:
                self.errors.append(message)

    def _records(self) -> tuple[list[object], dict[str, Any]]:
        if isinstance(self.source, (str, Path)):
            records, top = load_crawler_records(self.source)
            self._preserve_errors(top.get("errors"))
            return records, top
        if hasattr(self.source, "mentions"):
            mentions = list(getattr(self.source, "mentions"))
            top = {
                "bucket_start": getattr(self.source, "bucket_start", None),
                "bucket_end": getattr(self.source, "bucket_end", None),
                "keywords": getattr(self.source, "keywords", None),
            }
            self._preserve_errors(getattr(self.source, "errors", []) or [])
            return mentions, top
        if isinstance(self.source, Mapping):
            mapped = _mapping(self.source)
            mentions = mapped.get("mentions")
            if isinstance(mentions, list):
                self._preserve_errors(mapped.get("errors"))
                top = {key: value for key, value in mapped.items() if key != "mentions"}
                return mentions, top
            return [mapped], {}
        if isinstance(self.source, Iterable):
            return list(self.source), {}
        raise TypeError("unsupported social crawler source")

    async def collect(self, run: IngestionRun):
        records, top = self._records()
        for record in records:
            mapped = _mapping(record)
            self._preserve_errors(mapped.get("errors") or mapped.get("error"))
            item = map_social_record(
                mapped,
                observed_default=run.started_at,
                business_timezone=self.settings.voc_business_timezone,
                top_level=top,
            )
            if item is None:
                self.discoveries.append(
                    _discovery_provenance(mapped, top_level=top)
                )
                continue
            yield item


def _safe_reader_error(
    provider: str,
    url: str,
    exc: Exception,
    *,
    platform: str | None = None,
) -> str:
    """Return stable reader provenance without logging URLs or provider text."""

    canonical = canonicalize_url(url)
    target = canonical if canonical is not None else str(url)[:4_000]
    digest = hashlib.sha256(target.encode("utf-8", errors="replace")).hexdigest()[:12]
    safe_platform = re.sub(
        r"[^a-z0-9_-]+", "", str(platform or "unknown").strip().lower()
    )[:32] or "unknown"
    return f"{provider} {safe_platform} target-{digest}: {type(exc).__name__}"


class _TrackingMetadataPageReader(MetadataPageReader):
    def __init__(self) -> None:
        super().__init__(use_browser=False)
        self.errors: list[str] = []

    async def read(self, url: str, *, platform: str | None = None) -> PageContent:
        try:
            return await super().read(url, platform=platform)
        except Exception as exc:
            self.errors.append(
                _safe_reader_error(
                    "metadata_reader", url, exc, platform=platform
                )
            )
            raise


class _TrackingTinyFishPageReader(TinyFishPageReader):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.errors: list[str] = []

    async def read(self, url: str, *, platform: str | None = None) -> PageContent:
        try:
            return await super().read(url, platform=platform)
        except Exception as exc:
            self.errors.append(
                _safe_reader_error(
                    "tinyfish_reader", url, exc, platform=platform
                )
            )
            raise


class _TrackingCachedPageReader(CachedPageReader):
    """Cache page content and expose only reader results to the adapter."""

    def __init__(self, reader: PageReader) -> None:
        super().__init__(reader)
        self.results: dict[str, PageContent] = {}
        self.errors: list[str] = []

    async def read(self, url: str, *, platform: str | None = None) -> PageContent:
        canonical = canonicalize_url(url)
        try:
            result = await super().read(url, platform=platform)
        except Exception as exc:
            # Exception messages and request URLs may contain credentials.
            # Preserve only stable, secret-free error provenance.
            self.errors.append(
                _safe_reader_error("page_reader", url, exc, platform=platform)
            )
            raise
        key = canonical or canonicalize_url(result.url)
        if key is not None:
            self.results[key] = result
        result_key = canonicalize_url(result.url)
        if result_key is not None:
            self.results[result_key] = result
        return result

    def result_for(self, url: str | None) -> PageContent | None:
        canonical = canonicalize_url(url)
        return self.results.get(canonical) if canonical is not None else None


class LiveSocialCrawlerConnector:
    """Optional live adapter; the deterministic demo does not require it."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        keywords: tuple[str, ...] | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.keywords = keywords or self.settings.crawler_keywords
        self.errors: list[str] = []
        self.discoveries: list[dict[str, Any]] = []

    async def collect(self, run: IngestionRun):
        tinyfish_api_key = self.settings.tinyfish_resolved_api_key
        if not self.settings.tinyfish_enabled and not self.settings.serp_api_key:
            raise RuntimeError(
                "Enable TinyFish with an API key or configure SERP_API_KEY "
                "for a live social crawl"
            )
        if self.settings.tinyfish_enabled and not tinyfish_api_key:
            raise RuntimeError("TINYFISH_API_KEY is required when TinyFish is enabled")
        from social_crawler.engine import crawl
        from social_crawler.serpapi import SerpApiClient
        from social_crawler.tinyfish import FallbackSearchClient, TinyFishSearchClient

        metadata_reader = _TrackingMetadataPageReader()
        tinyfish_reader = (
            _TrackingTinyFishPageReader(
                endpoint=self.settings.tinyfish_fetch_base_url,
                api_key=tinyfish_api_key,
                timeout_seconds=self.settings.tinyfish_timeout_seconds,
            )
            if self.settings.tinyfish_enabled
            else None
        )
        page_reader = _TrackingCachedPageReader(
            FallbackPageReader(
                metadata_reader,
                tinyfish_reader,
                useful_text_chars=self.settings.tinyfish_useful_text_chars,
            )
        )

        search_client: FallbackSearchClient | None = None
        if self.settings.tinyfish_enabled:
            tinyfish_search = TinyFishSearchClient(
                api_key=tinyfish_api_key,
                base_url=self.settings.tinyfish_search_base_url,
                timeout_seconds=self.settings.tinyfish_timeout_seconds,
                location=self.settings.tinyfish_location,
                language=self.settings.tinyfish_language,
            )
            try:
                serp_fallback = (
                    SerpApiClient(
                        api_key=self.settings.serp_api_key,
                        base_url=self.settings.serp_api_base_url,
                    )
                    if self.settings.serp_api_key
                    else None
                )
            except BaseException:
                await tinyfish_search.aclose()
                raise
            search_client = FallbackSearchClient(tinyfish_search, serp_fallback)

        try:
            result = await crawl(
                # The preserved engine owns and closes SerpAPI only when no
                # search client is injected. TinyFish-enabled runs inject a
                # preferred TinyFish client with optional SerpAPI fallback.
                api_key="" if search_client is not None else self.settings.serp_api_key,
                api_base_url=self.settings.serp_api_base_url,
                keywords=list(self.keywords),
                platforms=list(self.settings.crawler_platforms),
                lookback_hours=self.settings.crawler_lookback_days * 24,
                bucket_end=run.started_at,
                search_client=search_client,
                page_reader=page_reader,
            )
        finally:
            if search_client is not None:
                await search_client.aclose()
        reader_errors = [*metadata_reader.errors, *page_reader.errors]
        if tinyfish_reader is not None:
            reader_errors.extend(tinyfish_reader.errors)
        self.errors = list(dict.fromkeys([*result.errors, *reader_errors]))

        enriched_records: list[dict[str, Any]] = []
        for mention in result.mentions:
            raw = _mapping(mention)
            page = page_reader.result_for(raw.get("link"))
            if page is not None and _text(page.text):
                raw["page_reader_result"] = {
                    "title": page.title,
                    "text": page.text,
                    "reader": page.reader or "page_reader",
                    "metadata": page.metadata,
                }
            enriched_records.append(raw)

        source = {
            "bucket_start": result.bucket_start,
            "bucket_end": result.bucket_end,
            "keywords": result.keywords,
            "errors": result.errors,
            "mentions": enriched_records,
        }
        adapter = SocialCrawlerConnector(source, settings=self.settings)
        async for item in adapter.collect(run):
            yield item
        for discovery in adapter.discoveries:
            if discovery not in self.discoveries:
                self.discoveries.append(discovery)


PublicSocialConnector = SocialCrawlerConnector


__all__ = [
    "LiveSocialCrawlerConnector",
    "PublicSocialConnector",
    "SocialCrawlerConnector",
    "brand_candidates_from_keywords",
    "load_crawler_records",
    "map_social_record",
    "map_verified_feedback_export",
]
