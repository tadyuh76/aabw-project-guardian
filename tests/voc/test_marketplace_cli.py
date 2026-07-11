from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import pytest

import guardian_voc.cli as cli
from guardian_voc.application import GuardianService
from guardian_voc.config import Settings
from guardian_voc.connectors.marketplace_api import (
    ItemReconciliation,
    MarketplaceReconciliationManifest,
)
from guardian_voc.schemas.api import RunResponse
from guardian_voc.schemas.feedback import (
    Brand,
    IngestionRun,
    IngestionRunStatus,
    RawFeedback,
    SourceGroup,
    Visibility,
)


NOW = datetime(2026, 7, 11, 12, tzinfo=timezone.utc)


def result(platform: str) -> dict[str, Any]:
    return {
        "run": {
            "pipeline_run_id": f"pipeline-{platform}",
            "status": "completed",
            "records_seen": 2,
            "records_inserted": 2,
            "records_skipped": 0,
            "records_failed": 0,
        },
        "reconciliation": {
            "platform": platform,
            "vietnamese_only": True,
            "totals": {"records_emitted": 2, "records_language_filtered": 1},
        },
    }


def test_cli_requires_explicit_owned_shop_confirmation() -> None:
    parser = cli.build_parser()
    with pytest.raises(SystemExit) as captured:
        parser.parse_args(["ingest-shopee-reviews", "--item-id", "100"])
    assert captured.value.code == 2
    with pytest.raises(SystemExit) as captured:
        parser.parse_args(["ingest-lazada-reviews", "--item-id", "100"])
    assert captured.value.code == 2


def test_shopee_cli_reads_secrets_from_env_and_emits_safe_reconciliation(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    captured: dict[str, Any] = {}
    partner_secret = "private-shopee-partner-key"
    seller_token = "private-shopee-token"

    class FakeService:
        def ingest_shopee_reviews(self, **kwargs: Any) -> dict[str, Any]:
            captured.update(kwargs)
            return result("shopee")

    monkeypatch.setenv("SHOPEE_PARTNER_KEY", partner_secret)
    monkeypatch.setenv("SHOPEE_ACCESS_TOKEN", seller_token)
    monkeypatch.setattr(cli, "_service", lambda: FakeService())
    args = cli.build_parser().parse_args(
        [
            "ingest-shopee-reviews",
            "--item-id",
            "101",
            "--item-id",
            "102",
            "--partner-id",
            "11",
            "--shop-id",
            "22",
            "--owned-shop-authorized",
        ]
    )
    assert args.func(args) == 0

    assert captured == {
        "partner_id": 11,
        "partner_key": partner_secret,
        "access_token": seller_token,
        "shop_id": 22,
        "item_ids": [101, 102],
        "discover_all_items": False,
        "owned_shop_authorized": True,
        "page_size": 100,
        "max_pages_per_item": 10_000,
        "lookback_days": 365,
        "vietnamese_only": True,
    }
    output = capsys.readouterr().out
    assert json.loads(output)["reconciliation"]["vietnamese_only"] is True
    assert partner_secret not in output
    assert seller_token not in output


def test_lazada_cli_uses_env_fallback_for_app_key_and_never_prints_secrets(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    captured: dict[str, Any] = {}
    app_secret = "private-lazada-secret"
    seller_token = "private-lazada-token"

    class FakeService:
        def ingest_lazada_reviews(self, **kwargs: Any) -> dict[str, Any]:
            captured.update(kwargs)
            return result("lazada")

    monkeypatch.setenv("LAZADA_APP_KEY", "public-app-key")
    monkeypatch.setenv("LAZADA_APP_SECRET", app_secret)
    monkeypatch.setenv("LAZADA_ACCESS_TOKEN", seller_token)
    monkeypatch.setattr(cli, "_service", lambda: FakeService())
    args = cli.build_parser().parse_args(
        [
            "ingest-lazada-reviews",
            "--item-id",
            "201",
            "--owned-shop-authorized",
            "--page-size",
            "50",
        ]
    )
    assert args.func(args) == 0

    assert captured["app_key"] == "public-app-key"
    assert captured["app_secret"] == app_secret
    assert captured["access_token"] == seller_token
    assert captured["item_ids"] == [201]
    assert captured["discover_all_items"] is False
    assert captured["owned_shop_authorized"] is True
    assert captured["vietnamese_only"] is True
    assert captured["page_size"] == 50
    output = capsys.readouterr().out
    assert app_secret not in output
    assert seller_token not in output


def test_cli_fails_closed_when_secret_environment_is_missing(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("SHOPEE_PARTNER_KEY", raising=False)
    monkeypatch.setenv("SHOPEE_ACCESS_TOKEN", "token-that-must-not-print")
    args = cli.build_parser().parse_args(
        [
            "ingest-shopee-reviews",
            "--item-id",
            "101",
            "--partner-id",
            "11",
            "--shop-id",
            "22",
            "--owned-shop-authorized",
        ]
    )
    assert args.func(args) == 2
    streams = capsys.readouterr()
    assert streams.out == ""
    assert "SHOPEE_PARTNER_KEY" in streams.err
    assert "token-that-must-not-print" not in streams.err


def test_service_marketplace_path_uses_repository_and_pipeline(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        voc_db_path=tmp_path / "guardian.duckdb",
        voc_data_dir=tmp_path,
        voc_inbox_dir=tmp_path / "inbox",
        ai_provider="cached",
    )
    service = GuardianService(settings)
    manifest = MarketplaceReconciliationManifest(
        platform="shopee",
        item_ids=("101",),
        lookback_days=365,
        vietnamese_only=True,
    )

    class StubConnector:
        def __init__(self) -> None:
            self.manifest = manifest

    connector = StubConnector()
    captured: dict[str, Any] = {}

    async def fake_ingest_connector(connector_arg: object, **kwargs: Any) -> IngestionRun:
        captured["connector"] = connector_arg
        captured["repository_kwargs"] = kwargs
        manifest.items["101"] = ItemReconciliation(
            item_id="101",
            pages_requested=1,
            rows_received=3,
            unique_rows_received=3,
            records_emitted=2,
            records_language_filtered=1,
            reported_total=3,
            pagination_complete=True,
            reconciliation="matched",
        )
        return IngestionRun(
            id="ingestion-shopee",
            connector="marketplace_api",
            source_name="guardian_shopee_api",
            status=IngestionRunStatus.COMPLETED,
            started_at=NOW,
            completed_at=NOW,
            records_seen=2,
            records_inserted=2,
        )

    def fake_execute(*, trigger: str, ingest: Any) -> RunResponse:
        captured["trigger"] = trigger
        captured["ingest_result"] = dict(ingest())
        return RunResponse(
            pipeline_run_id="pipeline-shopee",
            status="completed",
            stage="published",
            started_at=NOW,
            completed_at=NOW,
            records_seen=2,
            records_inserted=2,
        )

    monkeypatch.setattr(service.repository, "ingest_connector", fake_ingest_connector)
    monkeypatch.setattr(service, "_execute_pipeline", fake_execute)
    try:
        output = service._ingest_marketplace_connector(  # type: ignore[arg-type]
            connector, platform="shopee"
        )
    finally:
        service.close()

    assert captured["trigger"] == "marketplace_shopee"
    assert captured["connector"] is connector
    assert captured["repository_kwargs"] == {
        "connector_name": "marketplace_api",
        "source_name": "guardian_shopee_api",
        "source_group": SourceGroup.MARKETPLACE,
        "metadata": {
            "platform": "shopee",
            "authorization_scope": "guardian_owned_shop",
        },
        "raise_on_error": False,
    }
    assert captured["ingest_result"]["reconciliation"]["vietnamese_only"] is True
    assert output["run"]["status"] == "completed"
    assert output["reconciliation"]["totals"] == {
        "pages_requested": 1,
        "rows_received": 3,
        "unique_rows_received": 3,
        "records_emitted": 2,
        "records_before_window": 0,
        "records_after_window": 0,
        "records_missing_date": 0,
        "records_language_filtered": 1,
        "records_invalid": 0,
        "duplicates_removed": 0,
    }


def test_service_marketplace_path_persists_through_canonical_normalization(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        voc_db_path=tmp_path / "normalized.duckdb",
        voc_data_dir=tmp_path,
        voc_inbox_dir=tmp_path / "inbox",
        voc_demo_mode=False,
        voc_demo_as_of=None,
        ai_provider="cached",
    )
    service = GuardianService(settings)
    manifest = MarketplaceReconciliationManifest(
        platform="lazada",
        item_ids=("201",),
        lookback_days=365,
        vietnamese_only=True,
    )

    class StubConnector:
        def __init__(self) -> None:
            self.manifest = manifest

        async def collect(self, ingestion_run: IngestionRun):
            manifest.window_start = "2025-07-12T00:00:00+00:00"
            manifest.window_end = ingestion_run.started_at.isoformat()
            manifest.items["201"] = ItemReconciliation(
                item_id="201",
                pages_requested=1,
                rows_received=1,
                unique_rows_received=1,
                records_emitted=1,
                reported_total=1,
                pagination_complete=True,
                reconciliation="matched",
            )
            yield RawFeedback(
                source_external_id="lazada-review-201",
                source_group=SourceGroup.MARKETPLACE,
                source_platform="lazada",
                visibility=Visibility.PUBLIC,
                brand=Brand.GUARDIAN,
                brand_candidates=[Brand.GUARDIAN],
                occurred_at=NOW,
                observed_at=ingestion_run.started_at,
                text="Nhân viên tư vấn rất tốt và giao hàng nhanh",
                rating=5,
                product_name="Sữa rửa mặt",
                store="Guardian Official Store",
                metadata={"experience_subject": "retailer"},
            )

    monkeypatch.setattr(service, "_classify_pending", lambda: {"classified": 0})
    monkeypatch.setattr(
        service,
        "_rebuild_insights",
        lambda *, pipeline_run_id: {"pipeline_run_id": pipeline_run_id, "cards": 0},
    )
    try:
        output = service._ingest_marketplace_connector(  # type: ignore[arg-type]
            StubConnector(), platform="lazada"
        )
        stored = service.database.query_one(
            """
            SELECT source_external_id, source_group, source_platform, brand,
                   language, text_redacted
            FROM feedback_items WHERE source_external_id = ?
            """,
            ["lazada-review-201"],
        )
    finally:
        service.close()

    assert output["run"]["status"] == "completed"
    assert output["run"]["records_inserted"] == 1
    assert output["reconciliation"]["items"]["201"]["reconciliation"] == "matched"
    assert stored is not None
    assert stored["source_group"] == "marketplace"
    assert stored["source_platform"] == "lazada"
    assert stored["brand"] == "guardian"
    assert stored["language"] == "vi"
    assert "giao hàng nhanh" in stored["text_redacted"]
