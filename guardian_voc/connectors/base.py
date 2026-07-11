"""Connector protocol and import-preview contracts."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from guardian_voc.schemas.feedback import IngestionRun, RawFeedback


@runtime_checkable
class FeedbackConnector(Protocol):
    """Every source adapter emits the same ephemeral canonical contract."""

    async def collect(self, run: IngestionRun) -> AsyncIterator[RawFeedback]: ...


class ImportIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    row_number: int = Field(ge=1)
    code: str
    message: str
    field: str | None = None
    masked_sample: dict[str, Any] = Field(default_factory=dict)


class ImportPreview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile: str
    source_name: str
    filename: str
    file_sha256: str
    columns: list[str] = Field(default_factory=list)
    resolved_mapping: dict[str, str] = Field(default_factory=dict)
    total_rows: int = Field(ge=0)
    valid_rows: int = Field(ge=0)
    invalid_rows: int = Field(ge=0)
    samples: list[dict[str, Any]] = Field(default_factory=list)
    issues: list[ImportIssue] = Field(default_factory=list)


__all__ = ["FeedbackConnector", "ImportIssue", "ImportPreview"]
