from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import guardian_voc.data_layer as data_layer
from fastapi.testclient import TestClient

import guardian_voc.api.main as api_main
from guardian_voc.application import GuardianService
from guardian_voc.config import Settings
from guardian_voc.schemas.api import RunResponse


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
        result = service.run_live_collection(
            source_ids=(
                "guardian_public_social",
                "hasaki_public_social",
                "watsons_public_social",
            ),
            pages_per_query=3,
            fetch_limit=500,
            extraction_limit=500,
            lookback_days=30,
            refresh=False,
        )

        assert result.status == "completed"
        assert captured["database"] is service.database
        assert captured["run"]["source_ids"] == (
            "guardian_public_social",
            "hasaki_public_social",
            "watsons_public_social",
        )
        assert captured["run"]["pages_per_query"] == 3
        assert captured["run"]["fetch_limit"] == 500
        assert captured["run"]["extraction_limit"] == 500
        assert captured["run"]["refresh"] is False
        row = service.database.query_one(
            "SELECT trigger, stage_results FROM pipeline_runs WHERE id = ?",
            [result.pipeline_run_id],
        )
        assert row is not None
        assert row["trigger"] == "scheduled_full_flow"
        stages = json.loads(str(row["stage_results"]))
        assert stages["ingest"]["collection"]["searches"] == 6
        assert stages["ingest"]["collection"]["period_start"] == "2026-06-13"
        assert stages["ingest"]["collection"]["source_ids"] == [
            "guardian_public_social",
            "hasaki_public_social",
            "watsons_public_social",
        ]
        assert stages["ingest"]["collection"]["fetch_attempted"] == 4
        assert stages["post_classify"]["feedback_items"] == 6
    finally:
        service.close()


def test_live_collection_api_requires_admin_and_forwards_bounded_options(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    settings = Settings(
        _env_file=None,
        voc_db_path=tmp_path / "live-api.duckdb",
        voc_data_dir=tmp_path / "data",
        voc_demo_mode=False,
        voc_write_api_enabled=True,
        voc_admin_token="test-admin-token",
        ai_provider="cached",
    )
    service = GuardianService(settings)
    service.initialize(seed_demo=False, process_existing=False)
    captured: dict[str, Any] = {}

    def fake_collection(**kwargs: Any) -> RunResponse:
        captured.update(kwargs)
        return RunResponse(pipeline_run_id="collection-api-run", status="completed")

    monkeypatch.setattr(api_main, "get_service", lambda: service)
    monkeypatch.setattr(service, "run_live_collection", fake_collection)
    payload = {
        "source_ids": [
            "guardian_public_social",
            "hasaki_public_social",
            "watsons_public_social",
        ],
        "pages_per_query": 3,
        "fetch_limit": 500,
        "extraction_limit": 500,
        "lookback_days": 30,
        "refresh": False,
    }
    try:
        with TestClient(api_main.app) as client:
            assert client.post("/api/v1/live-collections", json=payload).status_code == 401
            response = client.post(
                "/api/v1/live-collections",
                json=payload,
                headers={"X-Admin-Token": "test-admin-token"},
            )
        assert response.status_code == 200
        assert response.json()["pipeline_run_id"] == "collection-api-run"
        assert captured == {
            "source_ids": payload["source_ids"],
            "pages_per_query": 3,
            "fetch_limit": 500,
            "extraction_limit": 500,
            "lookback_days": 30,
            "refresh": False,
        }
    finally:
        service.close()
