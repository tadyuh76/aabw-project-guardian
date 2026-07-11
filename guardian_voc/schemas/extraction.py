"""Strict trust-boundary schemas for page-level customer-feedback extraction."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import Field, field_validator, model_validator

from guardian_voc.schemas.analysis import FrozenModel, StrictModel
from guardian_voc.schemas.feedback import Brand


class BlockRole(StrEnum):
    CUSTOMER = "customer"
    SELLER = "seller"
    METADATA = "metadata"
    UNKNOWN = "unknown"


class PageState(StrEnum):
    USABLE = "usable"
    NO_CUSTOMER_VOICE = "no_customer_voice"
    BLOCKED_OR_EMPTY = "blocked_or_empty"
    EXTRACTION_UNCERTAIN = "extraction_uncertain"


class PageBlock(FrozenModel):
    block_id: str = Field(min_length=1, max_length=120)
    container_id: str = Field(min_length=1, max_length=200)
    parent_block_id: str | None = Field(default=None, max_length=120)
    role_hint: BlockRole = BlockRole.UNKNOWN
    text: str = Field(min_length=1, max_length=8_000)


class ExtractionSpan(StrictModel):
    block_id: str = Field(min_length=1, max_length=120)
    quote: str = Field(min_length=1, max_length=4_000)
    occurrence_index: int = Field(ge=0, le=10_000)


class ExtractedFeedbackUnit(StrictModel):
    container_id: str = Field(min_length=1, max_length=200)
    customer_text_spans: tuple[ExtractionSpan, ...] = Field(
        min_length=1, max_length=50
    )
    seller_response_spans: tuple[ExtractionSpan, ...] = Field(
        default=(), max_length=20
    )
    occurred_at_span: ExtractionSpan | None = None
    rating_span: ExtractionSpan | None = None
    product_name_span: ExtractionSpan | None = None
    extraction_confidence: float = Field(ge=0.0, le=1.0)


class PageExtractionResult(StrictModel):
    schema_version: Literal["voc-feedback-extractor.v1"]
    page_state: PageState
    units: tuple[ExtractedFeedbackUnit, ...] = Field(default=(), max_length=50)

    @model_validator(mode="after")
    def validate_page_state(self) -> "PageExtractionResult":
        if self.page_state is PageState.USABLE and not self.units:
            raise ValueError("usable page_state requires at least one extracted unit")
        if self.page_state is not PageState.USABLE and self.units:
            raise ValueError("only usable page_state may contain extracted units")
        return self


class PageExtractionRequest(FrozenModel):
    page_id: str = Field(min_length=1, max_length=200)
    source_platform: str = Field(min_length=1, max_length=80)
    source_owner_brand: Brand | None = None
    brand_candidates: tuple[Brand, ...] = ()
    max_units: int = Field(default=50, ge=1, le=50)
    title_redacted: str = Field(default="", max_length=2_000)
    blocks: tuple[PageBlock, ...] = Field(min_length=1, max_length=200)
    prompt_version: Literal["page-feedback-extractor-v1"] = (
        "page-feedback-extractor-v1"
    )

    @field_validator("brand_candidates")
    @classmethod
    def validate_candidates(cls, value: tuple[Brand, ...]) -> tuple[Brand, ...]:
        if len(set(value)) != len(value):
            raise ValueError("brand_candidates must be unique")
        return value

    @model_validator(mode="after")
    def validate_block_identity(self) -> "PageExtractionRequest":
        block_ids = [block.block_id for block in self.blocks]
        if len(set(block_ids)) != len(block_ids):
            raise ValueError("page block IDs must be unique")
        known = set(block_ids)
        for block in self.blocks:
            if block.parent_block_id is not None and block.parent_block_id not in known:
                raise ValueError("parent_block_id must identify an input block")
        return self


__all__ = [
    "BlockRole",
    "ExtractedFeedbackUnit",
    "ExtractionSpan",
    "PageBlock",
    "PageExtractionRequest",
    "PageExtractionResult",
    "PageState",
]
