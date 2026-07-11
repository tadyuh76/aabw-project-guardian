"""Deterministic PII redaction and identifier hashing.

Redaction is deliberately performed before truncation so a preview can never
leak a value that happened to fall beyond the visible prefix.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Mapping


_EMAIL_RE = re.compile(
    r"(?<![\w.+-])[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}(?![\w.-])",
    re.IGNORECASE,
)
_PHONE_RE = re.compile(
    r"(?<![\w\d])(?:\+?84|0)(?:[\s().-]*\d){8,10}(?![\w\d])"
)
_ORDER_RE = re.compile(
    r"(?P<label>\b(?:order\s*(?:id|number|no\.?)|ticket\s*(?:id|number|no\.?)|"
    r"mã\s*(?:đơn\s*hàng|đơn|dh)|ma\s*(?:don\s*hang|don)|"
    r"(?:order|ticket|đơn\s*hàng)\s*#)\s*(?::|=|-)?\s*)"
    r"(?P<value>(?=[A-Z0-9_./-]{5,40}\b)[A-Z0-9_./-]*\d[A-Z0-9_./-]*)",
    re.IGNORECASE,
)
_LOYALTY_RE = re.compile(
    r"(?P<label>\b(?:loyalty\s*(?:card|id|number)|membership\s*(?:card|id|number)|"
    r"member\s*(?:card|id|number)|rewards?\s*(?:card|id|number)|"
    r"card\s*(?:id|number|no\.?)|thẻ\s*(?:thành\s*viên|tv)|"
    r"the\s*(?:thanh\s*vien|tv))\b\s*(?:#|:|=|-)?\s*)"
    r"(?P<value>(?:[A-Z]{1,5}\d[A-Z0-9-]{4,30}|\d(?:[ -]?\d){5,19}))",
    re.IGNORECASE,
)
_LONG_NUMBER_RE = re.compile(r"(?<!\d)\d(?:[ -]?\d){11,19}(?!\d)")
_LABELED_ADDRESS_RE = re.compile(
    r"(?P<label>\b(?:địa\s*chỉ|dia\s*chi|address|shipping\s*address|ship\s*to)\b"
    r"\s*(?::|=|-)\s*)(?P<value>[^\n;|]{5,180})",
    re.IGNORECASE,
)
_STREET_ADDRESS_RE = re.compile(
    r"(?<!\w)\d{1,5}[A-Za-z]?\s+(?:[\wÀ-ỹ.'-]+\s+){0,8}"
    r"(?:street|st\.?|road|rd\.?|avenue|ave\.?|lane|ln\.?|"
    r"đường|duong|phường|phuong|quận|quan)\b"
    r"(?:[\s,]+[\wÀ-ỹ.'-]+){0,8}",
    re.IGNORECASE,
)

_SENSITIVE_KEY_PARTS = {
    "address",
    "author",
    "customer",
    "email",
    "loyalty",
    "member_id",
    "mobile",
    "customer_name",
    "full_name",
    "recipient_name",
    "sender_name",
    "author_name",
    "order_id",
    "phone",
    "recipient",
    "sender",
}


@dataclass(frozen=True)
class RedactionResult:
    text: str
    counts: dict[str, int] = field(default_factory=dict)

    @property
    def changed(self) -> bool:
        return bool(self.counts)


def _replace(
    pattern: re.Pattern[str],
    value: str,
    placeholder: str,
    counts: Counter[str],
    kind: str,
    *,
    keep_label: bool = False,
) -> str:
    def repl(match: re.Match[str]) -> str:
        counts[kind] += 1
        if keep_label and "label" in match.groupdict():
            return f"{match.group('label')}{placeholder}"
        return placeholder

    return pattern.sub(repl, value)


def redact_text(value: str | None, *, max_chars: int | None = 100_000) -> str:
    """Return privacy-safe text with stable, human-readable placeholders."""

    return redact_text_with_report(value, max_chars=max_chars).text


def redact_text_with_report(
    value: str | None, *, max_chars: int | None = 100_000
) -> RedactionResult:
    text = str(value or "")
    counts: Counter[str] = Counter()
    text = _replace(_EMAIL_RE, text, "[EMAIL]", counts, "email")
    text = _replace(_PHONE_RE, text, "[PHONE]", counts, "phone")
    text = _replace(
        _ORDER_RE, text, "[ORDER_ID]", counts, "order_id", keep_label=True
    )
    text = _replace(
        _LOYALTY_RE, text, "[LOYALTY_ID]", counts, "loyalty_id", keep_label=True
    )
    text = _replace(_LONG_NUMBER_RE, text, "[LOYALTY_ID]", counts, "loyalty_id")
    text = _replace(
        _LABELED_ADDRESS_RE,
        text,
        "[ADDRESS]",
        counts,
        "address",
        keep_label=True,
    )
    text = _replace(_STREET_ADDRESS_RE, text, "[ADDRESS]", counts, "address")
    if max_chars is not None and len(text) > max_chars:
        text = text[:max_chars].rstrip() + "…"
        counts["truncated"] += 1
    return RedactionResult(text=text, counts=dict(counts))


def hash_identifier(
    value: str | None,
    *,
    namespace: str,
    salt: str = "",
) -> str | None:
    """Hash a direct identifier using a purpose-specific namespace.

    HMAC is used when an installation salt is configured.  A deterministic
    SHA-256 fallback keeps local fixtures and migrations reproducible.
    """

    if value is None or not str(value).strip():
        return None
    payload = f"{namespace}\0{str(value).strip()}".encode("utf-8")
    if salt:
        digest = hmac.new(salt.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    else:
        digest = hashlib.sha256(payload).hexdigest()
    return f"sha256:{digest}"


def _sensitive_key(key: object) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", "_", str(key).strip().lower()).strip("_")
    return any(
        normalized == part
        or normalized.startswith(part + "_")
        or normalized.endswith("_" + part)
        for part in _SENSITIVE_KEY_PARTS
    )


def sanitize_metadata(value: Any, *, max_depth: int = 5) -> Any:
    """Recursively redact text and remove direct-identifier metadata values."""

    def walk(item: Any, depth: int) -> Any:
        if depth > max_depth:
            return "[TRUNCATED]"
        if isinstance(item, Mapping):
            clean: dict[str, Any] = {}
            for key, child in item.items():
                key_text = str(key)[:200]
                clean[key_text] = (
                    "[REDACTED]" if _sensitive_key(key) else walk(child, depth + 1)
                )
            return clean
        if isinstance(item, (list, tuple, set)):
            return [walk(child, depth + 1) for child in list(item)[:100]]
        if isinstance(item, str):
            return redact_text(item, max_chars=2_000)
        if item is None or isinstance(item, (bool, int, float)):
            return item
        return redact_text(str(item), max_chars=2_000)

    return walk(value, 0)


def preview_text(value: str | None, *, limit: int = 240) -> str:
    """Mask first and then return a short import-preview value."""

    redacted = redact_text(value, max_chars=None)
    if len(redacted) <= limit:
        return redacted
    return redacted[:limit].rstrip() + "…"


def mask_preview_mapping(
    row: Mapping[str, Any], *, text_limit: int = 240
) -> dict[str, Any]:
    """Produce a PII-safe, size-bounded representation of an import row."""

    masked: dict[str, Any] = {}
    for key, value in row.items():
        key_text = str(key)[:200]
        if _sensitive_key(key):
            masked[key_text] = "[REDACTED]"
        elif isinstance(value, str):
            masked[key_text] = preview_text(value, limit=text_limit)
        elif isinstance(value, (bool, int, float)) or value is None:
            masked[key_text] = value
        else:
            masked[key_text] = preview_text(str(value), limit=text_limit)
    return masked


__all__ = [
    "RedactionResult",
    "hash_identifier",
    "mask_preview_mapping",
    "preview_text",
    "redact_text",
    "redact_text_with_report",
    "sanitize_metadata",
]
