"""Fail-closed validation shared by cached and live AI paths."""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping
from typing import Any

from pydantic import BaseModel

from guardian_voc.schemas.analysis import (
    ClassificationRequest,
    ClassificationResult,
    PrimaryTopic,
    Sentiment,
    SourceGroup,
)
from guardian_voc.schemas.insights import FactPacket, InsightDraft, Team


class ClassificationValidationError(ValueError):
    pass


class InsightValidationError(ValueError):
    pass


def validate_classification(
    result: ClassificationResult,
    request: ClassificationRequest,
) -> ClassificationResult:
    """Validate semantic constraints that require the sanitized source text."""

    text = request.text_redacted
    if result.evidence_span not in text:
        raise ClassificationValidationError("evidence_span is not an exact source substring")

    fixed_brand = request.trusted_metadata.source_fixed_brand
    if fixed_brand is not None and result.primary_brand != fixed_brand:
        raise ClassificationValidationError("classification conflicts with source-fixed brand")

    if result.primary_brand is None:
        if result.brand_evidence_span:
            raise ClassificationValidationError(
                "brand_evidence_span must be null when primary_brand is null"
            )
    else:
        if fixed_brand is not None and result.brand_evidence_span is None:
            # Structured source metadata, rather than free text, fixes this
            # attribution. A fabricated brand span would be worse than null.
            pass
        elif not result.brand_evidence_span or result.brand_evidence_span not in text:
            raise ClassificationValidationError(
                "brand_evidence_span is not an exact source substring"
            )
        if (
            request.trusted_metadata.source_group is SourceGroup.SOCIAL
            and fixed_brand is None
            and result.primary_brand not in request.brand_candidates
        ):
            raise ClassificationValidationError(
                "public social primary_brand is outside trusted candidates"
            )

    if result.sentiment is Sentiment.NEGATIVE and result.sentiment_score > 0.25:
        raise ClassificationValidationError("negative sentiment has a positive score")
    if result.sentiment is Sentiment.POSITIVE and result.sentiment_score < -0.25:
        raise ClassificationValidationError("positive sentiment has a negative score")
    if not result.is_relevant and result.primary_topic is not PrimaryTopic.OTHER:
        raise ClassificationValidationError("irrelevant feedback must map to topic other")
    return result


def apply_low_confidence_policy(
    result: ClassificationResult,
    *,
    minimum_confidence: float = 0.70,
) -> tuple[ClassificationResult, bool]:
    """Map uncertain taxonomy labels to ``other`` and flag human review."""

    if result.confidence >= minimum_confidence:
        return result, False
    return result.model_copy(update={"primary_topic": PrimaryTopic.OTHER, "subtopic": "other"}), True


_CAUSAL_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\broot cause(?:d)?\b",
        r"\bconfirm(?:ed|s)? (?:the )?cause\b",
        r"\b(?:this|that|campaign|event|change) caused\b",
        r"\bresulted in\b",
        r"\bdue to\b",
        r"\bbecause of\b",
        r"\bproves? that\b",
        r"\bnguy[eê]n nh[aâ]n (?:g[oố]c|[dđ][aã] [dđ][uư][oợ]c x[aá]c nh[aậ]n)\b",
        r"\bg[aâ]y ra\b",
    )
)
_NUMBER_RE = re.compile(r"(?<![\w])[-+]?\d+(?:\.\d+)?\s*%?")
_WORD_RE = re.compile(r"\b[\wÀ-ỹ]+(?:[’'-][\wÀ-ỹ]+)*\b", re.UNICODE)
_UNSET = object()


def _walk_numbers(value: Any) -> Iterable[float]:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="python")
    if isinstance(value, bool):
        return
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        yield float(value)
    elif isinstance(value, Mapping):
        for child in value.values():
            yield from _walk_numbers(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from _walk_numbers(child)


def _number_is_grounded(token: str, allowed: tuple[float, ...]) -> bool:
    stripped = token.strip()
    percent = stripped.endswith("%")
    raw = stripped[:-1].strip() if percent else stripped
    value = float(raw)
    decimal_places = len(raw.partition(".")[2])
    rounding = 0.5 * (10 ** -decimal_places)
    if percent:
        target = value / 100.0
        tolerance = rounding / 100.0 + 1e-12
        return any(0.0 <= item <= 1.0 and abs(item - target) <= tolerance for item in allowed)
    tolerance = rounding + 1e-12 if decimal_places else 1e-12
    return any(abs(item - value) <= tolerance for item in allowed)


def insight_copy_word_count(draft: InsightDraft) -> int:
    values = [draft.title, draft.what_changed, draft.likely_driver]
    if draft.market_context:
        values.append(draft.market_context)
    values.extend(draft.recommended_actions)
    return len(_WORD_RE.findall(" ".join(values)))


def validate_insight_draft(
    draft: InsightDraft,
    fact_packet: FactPacket,
    *,
    expected_primary_owner: Team | object = _UNSET,
    expected_supporting_owner: Team | None | object = _UNSET,
    allowed_actions: Iterable[str] | None = None,
    maximum_words: int = 80,
) -> InsightDraft:
    """Reject any narrative that is not fully supported by sealed facts."""

    if len(draft.recommended_actions) > 2:
        raise InsightValidationError("an insight may contain at most two actions")
    if expected_primary_owner is not _UNSET and draft.primary_owner != expected_primary_owner:
        raise InsightValidationError("primary owner differs from the approved playbook")
    if (
        expected_supporting_owner is not _UNSET
        and draft.supporting_owner != expected_supporting_owner
    ):
        raise InsightValidationError("supporting owner differs from the approved playbook")
    if draft.supporting_owner == draft.primary_owner:
        raise InsightValidationError("supporting_owner must differ from primary_owner")

    if allowed_actions is not None:
        approved = {action.strip() for action in allowed_actions}
        unsupported = [
            action for action in draft.recommended_actions if action.strip() not in approved
        ]
        if unsupported:
            raise InsightValidationError("recommended action is outside the approved playbook")

    if len(set(draft.evidence_ids)) != len(draft.evidence_ids):
        raise InsightValidationError("evidence IDs must be unique")
    unknown_evidence = set(draft.evidence_ids) - set(fact_packet.allowed_evidence_ids)
    if unknown_evidence:
        raise InsightValidationError("insight references evidence outside the fact packet")

    copy_fields = [draft.title, draft.what_changed, draft.likely_driver]
    if draft.market_context:
        copy_fields.append(draft.market_context)
    copy_fields.extend(draft.recommended_actions)
    copy_text = " ".join(copy_fields)
    if any(pattern.search(copy_text) for pattern in _CAUSAL_PATTERNS):
        raise InsightValidationError("insight uses unsupported confirmed-causal language")
    if insight_copy_word_count(draft) > maximum_words:
        raise InsightValidationError(f"insight copy exceeds {maximum_words} words")

    allowed_numbers = tuple(_walk_numbers(fact_packet))
    for match in _NUMBER_RE.finditer(copy_text):
        if not _number_is_grounded(match.group(0), allowed_numbers):
            raise InsightValidationError(
                f"number {match.group(0).strip()!r} is not grounded in the fact packet"
            )
    return draft
