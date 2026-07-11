"""Strict schema for AI-assisted review-export column detection."""

from pydantic import BaseModel, ConfigDict


class ImportColumnMapping(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reviewer_name: str | None
    review_body: str
    star_rating: str | None
    product_url: str | None
    product_name: str | None
    review_id: str | None
    review_date: str | None


__all__ = ["ImportColumnMapping"]
