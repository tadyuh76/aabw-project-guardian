"""Transparent source-health qualification used before signal detection."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterable

from pydantic import Field

from guardian_voc.schemas.analysis import (
    FrozenModel,
    HealthStatus,
    SourceHealthSnapshot,
    SourceStratum,
)


class HealthPolicy(FrozenModel):
    stale_after: timedelta = timedelta(hours=30)
    minimum_timestamp_coverage: float = Field(default=0.80, ge=0.0, le=1.0)
    maximum_duplicate_share: float = Field(default=0.50, ge=0.0, le=1.0)
    minimum_classification_coverage: float = Field(default=0.80, ge=0.0, le=1.0)
    minimum_classification_confidence: float = Field(default=0.70, ge=0.0, le=1.0)


class HealthAssessment(FrozenModel):
    stratum: SourceStratum
    healthy: bool
    reasons: tuple[str, ...]


def assess_source_health(
    snapshot: SourceHealthSnapshot,
    *,
    as_of: datetime,
    policy: HealthPolicy | None = None,
) -> HealthAssessment:
    policy = policy or HealthPolicy()
    reasons: list[str] = []
    if snapshot.status is not HealthStatus.HEALTHY:
        reasons.append(f"source_status_{snapshot.status.value}")
    if snapshot.last_success_at is None:
        reasons.append("no_success_timestamp")
    elif as_of.tzinfo is None or snapshot.last_success_at.tzinfo is None:
        reasons.append("naive_freshness_timestamp")
    elif as_of - snapshot.last_success_at > policy.stale_after:
        reasons.append("source_stale")

    if (
        snapshot.expected_volume_min is not None
        and snapshot.recent_volume < snapshot.expected_volume_min
    ):
        reasons.append("source_volume_below_expected")
    if (
        snapshot.expected_volume_max is not None
        and snapshot.recent_volume > snapshot.expected_volume_max
    ):
        reasons.append("source_volume_above_expected")
    if snapshot.timestamp_coverage < policy.minimum_timestamp_coverage:
        reasons.append("timestamp_coverage_low")
    if snapshot.duplicate_share > policy.maximum_duplicate_share:
        reasons.append("duplicate_share_high")
    if snapshot.classification_coverage < policy.minimum_classification_coverage:
        reasons.append("classification_coverage_low")
    if (
        snapshot.mean_classification_confidence
        < policy.minimum_classification_confidence
    ):
        reasons.append("classification_confidence_low")
    return HealthAssessment(
        stratum=snapshot.stratum,
        healthy=not reasons,
        reasons=tuple(reasons),
    )


def assess_all_sources(
    snapshots: Iterable[SourceHealthSnapshot],
    *,
    as_of: datetime,
    policy: HealthPolicy | None = None,
) -> dict[str, HealthAssessment]:
    return {
        snapshot.stratum.stable_key(): assess_source_health(
            snapshot, as_of=as_of, policy=policy
        )
        for snapshot in snapshots
    }
