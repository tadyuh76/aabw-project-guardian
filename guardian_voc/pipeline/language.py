"""Small deterministic Vietnamese/English language detector.

The MVP deliberately avoids a network model.  Conservative ``unknown``
results are preferable to contaminating language-matched competitor cohorts.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


_TOKEN_RE = re.compile(r"[^\W\d_]+", re.UNICODE)
_PLACEHOLDER_RE = re.compile(r"\[[A-Z_]+\]")
_URL_RE = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)

_VI_MARKERS = {
    "anh",
    "bên",
    "biết",
    "bị",
    "các",
    "cái",
    "cần",
    "có",
    "còn",
    "của",
    "cho",
    "chưa",
    "đã",
    "đang",
    "đến",
    "được",
    "em",
    "giao",
    "giá",
    "hàng",
    "không",
    "khi",
    "lại",
    "là",
    "mà",
    "mình",
    "mua",
    "này",
    "nhân",
    "nhưng",
    "phẩm",
    "quá",
    "rất",
    "sản",
    "sao",
    "shop",
    "thì",
    "tôi",
    "trong",
    "tốt",
    "và",
    "với",
    "voucher",
}
_VI_UNACCENTED_MARKERS = {
    "ben",
    "bi",
    "cua",
    "cho",
    "chua",
    "da",
    "dang",
    "den",
    "duoc",
    "giao",
    "gia",
    "hang",
    "khong",
    "lai",
    "minh",
    "mua",
    "nhung",
    "pham",
    "qua",
    "rat",
    "san",
    "sao",
    "thi",
    "toi",
    "tot",
    "va",
    "voi",
}
_EN_MARKERS = {
    "a",
    "and",
    "are",
    "at",
    "but",
    "checkout",
    "delivery",
    "discount",
    "for",
    "from",
    "good",
    "has",
    "have",
    "i",
    "in",
    "is",
    "item",
    "late",
    "my",
    "not",
    "of",
    "on",
    "order",
    "price",
    "product",
    "refund",
    "service",
    "staff",
    "the",
    "this",
    "to",
    "very",
    "was",
    "with",
}
_VI_DIACRITICS = set(
    "ăâđêôơư"
    "áàảãạấầẩẫậắằẳẵặéèẻẽẹếềểễệíìỉĩị"
    "óòỏõọốồổỗộớờởỡợúùủũụứừửữựýỳỷỹỵ"
)


@dataclass(frozen=True)
class LanguageDetection:
    language: str
    confidence: float


def normalize_language_code(value: str | None) -> str | None:
    if not value:
        return None
    code = value.strip().lower().replace("_", "-")
    aliases = {
        "english": "en",
        "eng": "en",
        "en-us": "en",
        "en-gb": "en",
        "vietnamese": "vi",
        "vie": "vi",
        "vi-vn": "vi",
        "und": "unknown",
    }
    code = aliases.get(code, code)
    return code if code in {"en", "vi", "unknown"} else None


def _without_accents(value: str) -> str:
    value = value.replace("đ", "d")
    return "".join(
        char
        for char in unicodedata.normalize("NFD", value)
        if unicodedata.category(char) != "Mn"
    )


def detect_language(text: str | None) -> LanguageDetection:
    """Detect ``vi``, ``en``, or conservatively fall back to ``unknown``."""

    cleaned = _URL_RE.sub(" ", _PLACEHOLDER_RE.sub(" ", str(text or ""))).lower()
    tokens = _TOKEN_RE.findall(cleaned)
    alpha_count = sum(len(token) for token in tokens)
    if len(tokens) < 2 or alpha_count < 8:
        return LanguageDetection("unknown", 0.0)

    token_set = set(tokens)
    ascii_tokens = {_without_accents(token) for token in tokens}
    diacritic_count = sum(char in _VI_DIACRITICS for char in cleaned)
    vi_hits = len(token_set & _VI_MARKERS)
    vi_ascii_hits = len(ascii_tokens & _VI_UNACCENTED_MARKERS)
    en_hits = len(token_set & _EN_MARKERS)

    vi_score = min(diacritic_count, 8) * 1.15 + vi_hits * 1.8 + vi_ascii_hits * 0.45
    en_score = en_hits * 1.55
    if vi_score < 2.4 and en_score < 2.4:
        return LanguageDetection("unknown", 0.25)

    if vi_score == en_score:
        return LanguageDetection("unknown", 0.4)
    language = "vi" if vi_score > en_score else "en"
    winner, loser = sorted((vi_score, en_score), reverse=True)
    margin = (winner - loser) / max(winner + loser, 1)
    confidence = min(0.99, 0.55 + 0.44 * margin + min(winner, 8) * 0.015)
    if confidence < 0.65 or winner < loser * 1.2:
        return LanguageDetection("unknown", round(confidence, 4))
    return LanguageDetection(language, round(confidence, 4))


def resolve_language(
    text: str,
    *,
    provided_language: str | None = None,
    provided_confidence: float | None = None,
    trusted: bool = False,
) -> LanguageDetection:
    """Use a documented connector language field or run local detection."""

    code = normalize_language_code(provided_language)
    if trusted and code in {"en", "vi"}:
        confidence = 1.0 if provided_confidence is None else provided_confidence
        return LanguageDetection(code, max(0.0, min(1.0, confidence)))
    return detect_language(text)


__all__ = [
    "LanguageDetection",
    "detect_language",
    "normalize_language_code",
    "resolve_language",
]
