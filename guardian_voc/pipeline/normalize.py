"""Canonical normalization from connector records to privacy-safe storage rows."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Iterable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from guardian_voc.config import Settings, get_settings
from guardian_voc.pipeline.dedupe import (
    build_feedback_identity,
    canonicalize_url,
    content_fingerprint,
    content_hash,
    normalize_hash_text,
    repost_group_id,
)
from guardian_voc.pipeline.language import resolve_language
from guardian_voc.pipeline.pii import (
    hash_identifier,
    redact_text,
    redact_text_with_report,
    sanitize_metadata,
)
from guardian_voc.schemas.feedback import (
    BrandAttribution,
    ExperienceSubject,
    FeedbackItem,
    OccurredAtQuality,
    RawFeedback,
)


_RELATIVE_RE = re.compile(
    r"^\s*(?P<count>\d+)\s*(?P<unit>minutes?|mins?|hours?|hrs?|days?|weeks?|"
    r"phút|phut|giờ|gio|ngày|ngay|tuần|tuan)\s*(?:ago|trước|truoc)\s*$",
    re.IGNORECASE,
)
_VIETNAMESE_ABSOLUTE_RE = re.compile(
    r"^\s*(?P<day>\d{1,2})\s+(?:thg|tháng|thang)\s+(?P<month>\d{1,2}),?\s+"
    r"(?P<year>\d{4})(?:\s+(?:lúc\s+|luc\s+)?(?P<hour>\d{1,2}):(?P<minute>\d{2}))?\s*$",
    re.IGNORECASE,
)
_COMMON_DATE_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y %H:%M",
    "%d/%m/%Y",
    "%d-%m-%Y %H:%M:%S",
    "%d-%m-%Y %H:%M",
    "%d-%m-%Y",
    "%m/%d/%Y %H:%M:%S",
    "%m/%d/%Y %H:%M",
    "%b %d, %Y %H:%M",
    "%b %d, %Y",
    "%B %d, %Y %H:%M",
    "%B %d, %Y",
    "%d %b %Y %H:%M",
    "%d %b %Y",
    "%d %B %Y %H:%M",
    "%d %B %Y",
)


@dataclass(frozen=True)
class ParsedTimestamp:
    value: datetime | None
    quality: OccurredAtQuality
    original_timezone: str | None
    error: str | None = None


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"unknown IANA timezone: {name}") from exc


def _attach_timezone(value: datetime, timezone_name: str) -> datetime:
    return value.replace(tzinfo=_zone(timezone_name))


def _relative_delta(count: int, unit: str) -> timedelta:
    unit = unit.lower()
    if unit.startswith(("min", "phút", "phut")):
        return timedelta(minutes=count)
    if unit.startswith(("hour", "hr", "giờ", "gio")):
        return timedelta(hours=count)
    if unit.startswith(("week", "tuần", "tuan")):
        return timedelta(weeks=count)
    return timedelta(days=count)


def parse_timestamp(
    value: object,
    *,
    timezone_hint: str = "Asia/Ho_Chi_Minh",
    observed_at: datetime | None = None,
    quality_hint: OccurredAtQuality | None = None,
) -> ParsedTimestamp:
    """Parse a source timestamp without substituting observation time.

    Relative search-result dates are explicitly labelled ``inferred``.  An
    invalid or absent value stays missing so trend queries can exclude it.
    """

    if value is None or (isinstance(value, str) and not value.strip()):
        return ParsedTimestamp(None, OccurredAtQuality.MISSING, None)

    parsed: datetime | None = None
    quality = quality_hint
    original_timezone: str | None = None
    try:
        if isinstance(value, datetime):
            parsed = value
            quality = quality or (
                OccurredAtQuality.EXACT
                if value.tzinfo is not None and value.utcoffset() is not None
                else OccurredAtQuality.PARSED
            )
        elif isinstance(value, date):
            parsed = datetime.combine(value, time.min)
            quality = quality or OccurredAtQuality.PARSED
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            epoch = float(value)
            if abs(epoch) > 100_000_000_000:
                epoch /= 1_000
            parsed = datetime.fromtimestamp(epoch, tz=timezone.utc)
            quality = quality or OccurredAtQuality.PARSED
        else:
            text = str(value).strip()
            relative = _RELATIVE_RE.match(text)
            if relative:
                if observed_at is None:
                    return ParsedTimestamp(
                        None,
                        OccurredAtQuality.MISSING,
                        None,
                        "relative timestamp requires observed_at",
                    )
                reference = observed_at
                if reference.tzinfo is None or reference.utcoffset() is None:
                    reference = _attach_timezone(reference, timezone_hint)
                parsed = reference - _relative_delta(
                    int(relative.group("count")), relative.group("unit")
                )
                quality = OccurredAtQuality.INFERRED
            else:
                vietnamese_absolute = _VIETNAMESE_ABSOLUTE_RE.match(text)
                if vietnamese_absolute:
                    parsed = datetime(
                        int(vietnamese_absolute.group("year")),
                        int(vietnamese_absolute.group("month")),
                        int(vietnamese_absolute.group("day")),
                        int(vietnamese_absolute.group("hour") or 0),
                        int(vietnamese_absolute.group("minute") or 0),
                    )
                else:
                    iso_text = (
                        text[:-1] + "+00:00" if text.endswith(("Z", "z")) else text
                    )
                    try:
                        parsed = datetime.fromisoformat(iso_text)
                    except ValueError:
                        for fmt in _COMMON_DATE_FORMATS:
                            try:
                                parsed = datetime.strptime(text, fmt)
                                break
                            except ValueError:
                                continue
                quality = quality or OccurredAtQuality.PARSED
        if parsed is None:
            return ParsedTimestamp(
                None,
                OccurredAtQuality.MISSING,
                None,
                "unrecognized timestamp",
            )

        if parsed.tzinfo is None or parsed.utcoffset() is None:
            original_timezone = timezone_hint
            parsed = _attach_timezone(parsed, timezone_hint)
        else:
            original_timezone = getattr(parsed.tzinfo, "key", None) or str(parsed.tzinfo)
        return ParsedTimestamp(
            parsed.astimezone(timezone.utc),
            quality or OccurredAtQuality.PARSED,
            original_timezone,
        )
    except (OverflowError, OSError, TypeError, ValueError) as exc:
        return ParsedTimestamp(
            None,
            OccurredAtQuality.MISSING,
            None,
            f"{type(exc).__name__}: {exc}",
        )


def _experience_subject(raw: RawFeedback) -> ExperienceSubject:
    candidate = raw.metadata.get("experience_subject")
    try:
        return ExperienceSubject(str(candidate).strip().lower())
    except (TypeError, ValueError):
        return ExperienceSubject.UNKNOWN


def _safe_optional_text(value: str | None, *, limit: int) -> str | None:
    if value is None:
        return None
    clean = redact_text(value, max_chars=limit).strip()
    return clean or None


def normalize_raw_feedback(
    raw: RawFeedback,
    *,
    ingestion_run_id: str,
    source_name: str,
    settings: Settings | None = None,
    ingested_at: datetime | None = None,
) -> FeedbackItem:
    """Create the canonical, redacted, cross-run-stable feedback item."""

    settings = settings or get_settings()
    ingested_at = ingested_at or utc_now()
    if ingested_at.tzinfo is None or ingested_at.utcoffset() is None:
        raise ValueError("ingested_at must be timezone-aware")

    redaction = redact_text_with_report(raw.text, max_chars=100_000)
    text_redacted = redaction.text.strip()
    if not text_redacted:
        raise ValueError("feedback is empty after normalization")
    title = _safe_optional_text(raw.title, limit=2_000)
    canonical_url = canonicalize_url(raw.source_url)
    hash_text = "\n".join(
        value for value in (normalize_hash_text(title), normalize_hash_text(text_redacted)) if value
    )
    identity = build_feedback_identity(
        raw,
        source_name=source_name,
        canonical_url=canonical_url,
        normalized_text=hash_text,
    )

    trusted_language = raw.metadata.get("_language_trusted") is True
    language = resolve_language(
        f"{title or ''}\n{text_redacted}",
        provided_language=raw.language,
        provided_confidence=raw.language_confidence,
        trusted=trusted_language,
    )
    fingerprint = content_fingerprint(
        text_redacted,
        visibility=raw.visibility,
        min_chars=settings.voc_repost_min_chars,
    )

    sanitized = sanitize_metadata(raw.metadata)
    if isinstance(sanitized, dict):
        sanitized.pop("_language_trusted", None)
        sanitized["identity_kind"] = identity.kind.value
        if redaction.counts:
            sanitized["redactions"] = redaction.counts

    media_urls = list(
        dict.fromkeys(
            canonical
            for url in raw.media_urls[:100]
            if (canonical := canonicalize_url(url)) is not None
        )
    )
    brand_attribution = (
        BrandAttribution.SOURCE_FIXED
        if raw.brand is not None
        else BrandAttribution.AMBIGUOUS
        if len(raw.brand_candidates) > 1
        else BrandAttribution.UNKNOWN
    )

    return FeedbackItem(
        feedback_id=identity.feedback_id,
        ingestion_run_id=ingestion_run_id,
        source_external_id=raw.source_external_id,
        source_group=raw.source_group,
        source_platform=normalize_hash_text(raw.source_platform),
        visibility=raw.visibility,
        brand=raw.brand,
        brand_candidates=raw.brand_candidates,
        brand_attribution=brand_attribution,
        experience_subject=_experience_subject(raw),
        occurred_at=raw.occurred_at,
        observed_at=raw.observed_at,
        occurred_at_quality=raw.occurred_at_quality,
        ingested_at=ingested_at.astimezone(timezone.utc),
        original_timezone=raw.original_timezone,
        language=language.language,
        language_confidence=language.confidence,
        title=title,
        text_redacted=text_redacted,
        rating=raw.rating,
        product_name=_safe_optional_text(raw.product_name, limit=1_000),
        product_category=_safe_optional_text(raw.product_category, limit=500),
        region=_safe_optional_text(raw.region, limit=500),
        store=_safe_optional_text(raw.store, limit=500),
        source_url=canonical_url,
        canonical_url=canonical_url,
        author_hash=hash_identifier(
            raw.author_id, namespace="author", salt=settings.voc_hash_salt
        ),
        conversation_hash=hash_identifier(
            raw.conversation_id,
            namespace="conversation",
            salt=settings.voc_hash_salt,
        ),
        message_count=raw.message_count,
        media_urls=media_urls,
        content_hash=content_hash(title=title, text=text_redacted),
        content_fingerprint=fingerprint,
        repost_group_id=repost_group_id(fingerprint),
        crawler_record_id=(
            str(raw.metadata["crawler_record_id"])
            if raw.metadata.get("crawler_record_id") is not None
            else None
        ),
        sanitized_metadata=sanitized if isinstance(sanitized, dict) else {},
        is_synthetic=raw.is_synthetic,
    )


def normalize_feedback_batch(
    rows: Iterable[RawFeedback],
    *,
    ingestion_run_id: str,
    source_name: str,
    settings: Settings | None = None,
    ingested_at: datetime | None = None,
) -> list[FeedbackItem]:
    timestamp = ingested_at or utc_now()
    return [
        normalize_raw_feedback(
            row,
            ingestion_run_id=ingestion_run_id,
            source_name=source_name,
            settings=settings,
            ingested_at=timestamp,
        )
        for row in rows
    ]


__all__ = [
    "ParsedTimestamp",
    "normalize_feedback_batch",
    "normalize_raw_feedback",
    "parse_timestamp",
    "utc_now",
]
