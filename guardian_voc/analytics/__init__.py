"""Deterministic analytics; no narrative generation and no provider calls."""

from guardian_voc.analytics.competitors import build_matched_public_benchmark
from guardian_voc.analytics.drivers import rank_likely_drivers
from guardian_voc.analytics.metrics import aggregate_daily_metrics, build_analysis_windows
from guardian_voc.analytics.trends import compute_stratified_trend

__all__ = [
    "aggregate_daily_metrics",
    "build_analysis_windows",
    "build_matched_public_benchmark",
    "compute_stratified_trend",
    "rank_likely_drivers",
]
