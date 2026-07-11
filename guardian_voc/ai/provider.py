"""Provider protocol shared by cached and live structured-output adapters."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from guardian_voc.schemas.analysis import ClassificationRequest, ClassificationResult
from guardian_voc.schemas.insights import InsightDraft, InsightWritingRequest


class AIProviderError(RuntimeError):
    """Base class for sanitized provider failures."""


class CacheMissError(AIProviderError):
    pass


class ProviderTransportError(AIProviderError):
    pass


class ProviderTimeoutError(ProviderTransportError):
    pass


class ProviderHTTPError(AIProviderError):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"AI provider returned HTTP {status_code}")
        self.status_code = status_code


class MalformedProviderResponse(AIProviderError):
    pass


@runtime_checkable
class AIProvider(Protocol):
    """Small service boundary: classify items and write from sealed facts."""

    @property
    def model_version(self) -> str:
        ...

    async def classify(self, request: ClassificationRequest) -> ClassificationResult:
        ...

    async def write_insight(self, request: InsightWritingRequest) -> InsightDraft:
        ...
