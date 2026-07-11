"""Deterministic no-network provider for fixtures and offline demos."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from guardian_voc.ai.provider import CacheMissError
from guardian_voc.ai.validator import validate_classification, validate_insight_draft
from guardian_voc.schemas.analysis import ClassificationRequest, ClassificationResult
from guardian_voc.schemas.insights import InsightDraft, InsightWritingRequest


class CachedProvider:
    """Serve precomputed outputs keyed by content/prompt/model versions.

    The mapping keys are produced by ``request.cache_key(model_version)``;
    using only a content hash would silently reuse labels after a prompt or
    taxonomy change and is intentionally unsupported.
    """

    def __init__(
        self,
        *,
        classifications: Mapping[str, ClassificationResult | Mapping[str, Any]] | None = None,
        insights: Mapping[str, InsightDraft | Mapping[str, Any]] | None = None,
        model_version: str = "cached-v1",
    ) -> None:
        self._model_version = model_version
        self._classifications = dict(classifications or {})
        self._insights = dict(insights or {})

    @property
    def model_version(self) -> str:
        return self._model_version

    @classmethod
    def from_json(cls, path: str | Path) -> CachedProvider:
        with Path(path).open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return cls(
            classifications=payload.get("classifications", {}),
            insights=payload.get("insights", {}),
            model_version=payload.get("model_version", "cached-v1"),
        )

    async def classify(self, request: ClassificationRequest) -> ClassificationResult:
        key = request.cache_key(self.model_version)
        if key not in self._classifications:
            raise CacheMissError(f"no cached classification for key {key}")
        raw = self._classifications[key]
        result = raw if isinstance(raw, ClassificationResult) else ClassificationResult.model_validate(raw)
        return validate_classification(result, request)

    async def write_insight(self, request: InsightWritingRequest) -> InsightDraft:
        key = request.cache_key(self.model_version)
        if key not in self._insights:
            raise CacheMissError(f"no cached insight for key {key}")
        raw = self._insights[key]
        result = raw if isinstance(raw, InsightDraft) else InsightDraft.model_validate(raw)
        return validate_insight_draft(
            result,
            request.fact_packet,
            expected_primary_owner=request.approved_primary_owner,
            expected_supporting_owner=request.approved_supporting_owner,
            allowed_actions=request.approved_actions,
        )
