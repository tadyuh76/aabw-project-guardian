from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import guardian_voc.data_layer as data_layer
from guardian_voc.application import GuardianService
from guardian_voc.config import Settings


def test_strict_live_collection_uses_shared_database_and_publishes(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    captured: dict[str, Any] = {}

    class FakeLiveDataLayer:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

        async def run(self, **kwargs: Any) -> dict[str, Any]:
            captured["run"] = kwargs
            return {
                "stages": {
                    "discover": {"searches": 6, "unique_results": 8},
                    "fetch": {"attempted": 4},
                    "extract": {
                        "attempted": 3,
                        "accepted_units": 2,
                        "inserted": 0,
                        "skipped": 2,
                        "failed": 0,
                        "ingestion_run_id": "strict-ingestion",
                    },
                }
            }

        def apply_verified_source_ownership(self) -> dict[str, int]:
            return {"updated": 1, "analyses_invalidated": 1}

        def build_manifest(self, **kwargs: Any) -> dict[str, Any]:
            captured["manifest"] = kwargs
            return {
                "counts": {
                    "feedback_items": 6,
                    "analyzed_feedback_items": 6,
                    "guardian_relevant_analysis_rows": 2,
                    "time_eligible_real_feedback_items": 0,
                }
            }

    monkeypatch.setattr(data_layer, "LiveDataLayer", FakeLiveDataLayer)
    settings = Settings(
        _env_file=None,
        voc_db_path=tmp_path / "live-flow.duckdb",
        voc_data_dir=tmp_path / "data",
        voc_demo_mode=False,
        ai_provider="openai_compatible",
        ai_api_key="test-openai",
        serp_api_key="test-serp",
        tinyfish_enabled=True,
        tinyfish_api_key="test-tinyfish",
        voc_live_collection_source_ids=("guardian_public_social",),
        voc_live_collection_fetch_limit=17,
        voc_live_collection_extraction_limit=13,
    )
    service = GuardianService(settings)
    try:
        result = service.run_live_collection()

        assert result.status == "completed"
        assert captured["database"] is service.database
        assert captured["run"]["source_ids"] == ("guardian_public_social",)
        assert captured["run"]["fetch_limit"] == 17
        assert captured["run"]["extraction_limit"] == 13
        assert captured["run"]["refresh"] is False
        row = service.database.query_one(
            "SELECT trigger, stage_results FROM pipeline_runs WHERE id = ?",
            [result.pipeline_run_id],
        )
        assert row is not None
        assert row["trigger"] == "scheduled_full_flow"
        stages = json.loads(str(row["stage_results"]))
        assert stages["ingest"]["collection"]["searches"] == 6
        assert stages["ingest"]["collection"]["fetch_attempted"] == 4
        assert stages["post_classify"]["feedback_items"] == 6
    finally:
        service.close()
