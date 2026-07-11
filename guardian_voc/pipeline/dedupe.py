"""Stable feedback identity, URL canonicalization, and public repost grouping."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

from guardian_voc.schemas.feedback import RawFeedback, SourceGroup, Visibility


_WHITESPACE_RE = re.compile(r"\s+")
_MULTI_SLASH_RE = re.compile(r"/{2,}")
_TRACKING_QUERY_KEYS = {
    "_ga",
    "_gl",
    "dclid",
    "fbclid",
    "gclid",
    "igshid",
    "mc_cid",
    "mc_eid",
    "ref_src",
    "ref_url",
    "s_cid",
    "spm",
    "vero_conv",
    "vero_id",
}
_TRACKING_PREFIXES = ("utm_", "ga_", "pk_")


class IdentityKind(StrEnum):
    CANONICAL_URL = "canonical_url"
    SOURCE_EXTERNAL_ID = "source_external_id"
    CONVERSATION_ID = "conversation_id"
    CONTENT_FALLBACK = "content_fallback"


@dataclass(frozen=True)
class FeedbackIdentity:
    feedback_id: str
    kind: IdentityKind
    identity_digest: str


def normalize_hash_text(value: str | None) -> str:
    """Normalize text while retaining meaningful punctuation."""

    normalized = unicodedata.normalize("NFKC", str(value or "")).lower()
    return _WHITESPACE_RE.sub(" ", normalized).strip()


def _is_tracking_parameter(name: str) -> bool:
    normalized = name.strip().lower()
    return normalized in _TRACKING_QUERY_KEYS or normalized.startswith(
        _TRACKING_PREFIXES
    )


def canonicalize_url(value: str | None) -> str | None:
    """Canonicalize a public URL without fetching it.

    Fragments and known tracking parameters are removed.  Remaining query
    parameters are retained and sorted because they may identify the record.
    """

    if value is None or not str(value).strip():
        return None
    raw = str(value).strip()
    try:
        parsed = urlsplit(raw)
        scheme = parsed.scheme.lower()
        if scheme not in {"http", "https"}:
            return None
        if parsed.username or parsed.password:
            return None
        host = (parsed.hostname or "").lower().rstrip(".")
        if not host:
            return None
        try:
            host = host.encode("idna").decode("ascii")
            port = parsed.port
        except (UnicodeError, ValueError):
            return None
        if host.startswith("www."):
            host = host[4:]
        default_port = 80 if scheme == "http" else 443
        netloc = host if port in {None, default_port} else f"{host}:{port}"

        path = _MULTI_SLASH_RE.sub("/", parsed.path or "/")
        # Quote unsafe Unicode/control characters while preserving URL path
        # delimiters and existing percent escapes.
        path = quote(path, safe="/%:@-._~!$&'()*+,;=")
        if path != "/":
            path = path.rstrip("/") or "/"
        query_pairs = [
            (key, val)
            for key, val in parse_qsl(parsed.query, keep_blank_values=True)
            if not _is_tracking_parameter(key)
        ]
        query_pairs.sort(key=lambda pair: (pair[0].lower(), pair[0], pair[1]))
        query = urlencode(query_pairs, doseq=True)
        return urlunsplit((scheme, netloc, path, query, ""))
    except (TypeError, ValueError):
        return None


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def content_hash(*, title: str | None, text: str) -> str:
    """Hash the normalized stored content, preserving punctuation semantics."""

    payload = f"{normalize_hash_text(title)}\n{normalize_hash_text(text)}"
    return sha256_hex(payload)


def content_fingerprint(
    text: str,
    *,
    visibility: Visibility,
    min_chars: int = 40,
) -> str | None:
    """Return an exact text-only fingerprint only for substantive public text."""

    if visibility is not Visibility.PUBLIC:
        return None
    normalized = normalize_hash_text(text)
    if len(normalized) < min_chars or len(normalized.split()) < 6:
        return None
    return sha256_hex(normalized)


def repost_group_id(fingerprint: str | None) -> str | None:
    return None if fingerprint is None else f"repost_{fingerprint[:32]}"


def _public_web_identity_applies(raw: RawFeedback, canonical_url: str | None) -> bool:
    if raw.visibility is not Visibility.PUBLIC or canonical_url is None:
        return False
    # A marketplace export often carries a product URL shared by thousands of
    # independent reviews.  Use the URL only for crawler/web records, never in
    # place of a documented durable review ID.
    return (
        raw.source_group is SourceGroup.SOCIAL
        or bool(raw.metadata.get("crawler_record_id"))
        or raw.metadata.get("identity_type") == "canonical_url"
    )


def build_feedback_identity(
    raw: RawFeedback,
    *,
    source_name: str,
    canonical_url: str | None,
    normalized_text: str,
) -> FeedbackIdentity:
    """Apply connector identity precedence exactly once at ingestion."""

    # A trusted page extractor can emit multiple independently grounded units
    # from one public page.  Its durable unit ID must therefore win over the
    # otherwise-canonical public-social URL identity.  Keep this opt-in exact:
    # ordinary social rows, including rows that merely happen to carry an
    # external ID, remain URL-addressed.
    extracted_unit_identity = (
        bool(raw.source_external_id)
        and raw.metadata.get("identity_type") == "extracted_unit"
    )
    if extracted_unit_identity:
        kind = IdentityKind.SOURCE_EXTERNAL_ID
        key = (
            f"source\0{normalize_hash_text(source_name)}\0"
            f"{raw.source_external_id.strip()}"
        )
    elif _public_web_identity_applies(raw, canonical_url):
        kind = IdentityKind.CANONICAL_URL
        key = f"url\0{canonical_url}"
    elif raw.source_external_id:
        kind = IdentityKind.SOURCE_EXTERNAL_ID
        key = f"source\0{normalize_hash_text(source_name)}\0{raw.source_external_id.strip()}"
    elif raw.visibility is Visibility.OWNED and raw.conversation_id:
        kind = IdentityKind.CONVERSATION_ID
        key = (
            f"conversation\0{normalize_hash_text(source_name)}\0"
            f"{raw.conversation_id.strip()}"
        )
    else:
        kind = IdentityKind.CONTENT_FALLBACK
        date_value: datetime = raw.occurred_at or raw.observed_at
        date_bucket = date_value.date().isoformat()
        brand_key = (
            raw.brand.value
            if raw.brand is not None
            else ",".join(sorted(candidate.value for candidate in raw.brand_candidates))
        )
        key = "\0".join(
            (
                "fallback",
                normalize_hash_text(brand_key),
                normalize_hash_text(raw.source_platform),
                date_bucket,
                normalize_hash_text(normalized_text),
            )
        )
    digest = sha256_hex(key)
    return FeedbackIdentity(
        feedback_id=f"feedback_{digest[:32]}", kind=kind, identity_digest=digest
    )


__all__ = [
    "FeedbackIdentity",
    "IdentityKind",
    "build_feedback_identity",
    "canonicalize_url",
    "content_fingerprint",
    "content_hash",
    "normalize_hash_text",
    "repost_group_id",
    "sha256_hex",
]
