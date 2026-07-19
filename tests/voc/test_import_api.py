from __future__ import annotations

import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi.testclient import TestClient

import guardian_voc.api.main as api_main
from guardian_voc.application import GuardianService
from guardian_voc.config import Settings
from guardian_voc.connectors.file_import import read_import_sample


def test_review_csv_config_preview_commit_and_dedup(
    tmp_path: Path,
    monkeypatch,
) -> None:
    settings = Settings(
        _env_file=None,
        voc_db_path=tmp_path / "imports.duckdb",
        voc_data_dir=tmp_path / "data",
        voc_inbox_dir=tmp_path / "inbox",
        voc_demo_mode=False,
        voc_import_api_enabled=True,
        voc_write_api_enabled=False,
        ai_provider="cached",
    )
    service = GuardianService(settings)
    service.initialize(seed_demo=False, process_existing=False)
    monkeypatch.setattr(api_main, "get_service", lambda: service)
    monkeypatch.setattr(
        service,
        "_classify_pending",
        lambda: {"analyzed": 0, "failed": 0, "review_required": 0},
    )
    monkeypatch.setattr(
        service,
        "_rebuild_insights",
        lambda *, pipeline_run_id: {"published": 0, "pipeline_run_id": pipeline_run_id},
    )
    csv_bytes = (
        "review_id,review_text,rating,review_date,product_name,store_name\n"
        'guardian-review-1,"Guardian đóng gói kỹ, email a@example.com",5,2026-07-11,"Serum A","Guardian Official"\n'
    ).encode("utf-8")
    with TestClient(api_main.app) as client:
        config = client.get("/api/v1/imports/config")
        assert config.status_code == 200
        assert config.json()["enabled"] is True
        assert set(config.json()["profiles"]) == {
            "guardian_ecommerce",
            "tiktok_shop",
            "shopee",
            "lazada",
            "grabmart",
        }

        admin_history = client.get("/api/v1/imports/history")
        assert admin_history.status_code == 403

        tokenless_preview = client.post(
            "/api/v1/imports/preview",
            data={"profile": "shopee"},
            files={"file": ("reviews.csv", csv_bytes, "text/csv")},
        )
        assert tokenless_preview.status_code == 200

        preview = client.post(
            "/api/v1/imports/preview",
            data={"profile": "shopee", "vietnamese_only": "true"},
            files={"file": ("reviews.csv", csv_bytes, "text/csv")},
        )
        assert preview.status_code == 200
        assert preview.json()["valid_rows"] == 1
        assert preview.json()["filename"] == "reviews.csv"
        assert "a@example.com" not in preview.text
        assert "[EMAIL]" in preview.text

        first = client.post(
            "/api/v1/imports",
            data={"profile": "shopee", "vietnamese_only": "true"},
            files={"file": ("reviews.csv", csv_bytes, "text/csv")},
        )
        assert first.status_code == 202
        first_queued = first.json()
        assert first_queued["status"] == "queued"
        assert first_queued["stage"] == "queued"
        assert first_queued["records_inserted"] == 0
        first_run_id = first_queued["pipeline_run_id"]
        first_terminal = client.get(f"/api/v1/runs/{first_run_id}")
        assert first_terminal.status_code == 200
        assert first_terminal.json()["status"] == "completed"
        assert first_terminal.json()["records_inserted"] == 1

        # A retried background callback adopts only queued runs. Once terminal,
        # it returns the durable result without importing the bytes again.
        repeated_worker = service.execute_queued_import(
            pipeline_run_id=first_run_id,
            filename="reviews.csv",
            content=csv_bytes,
            profile="shopee",
            vietnamese_only=True,
        )
        assert repeated_worker.status == "completed"
        assert repeated_worker.records_inserted == 1

        replay = client.post(
            "/api/v1/imports",
            data={"profile": "shopee", "vietnamese_only": "true"},
            files={"file": ("reviews.csv", csv_bytes, "text/csv")},
        )
        assert replay.status_code == 422
        assert "already been imported" in replay.json()["detail"]

    stored = service.database.query(
        "SELECT source_platform, brand, text_redacted FROM feedback_items"
    )
    assert len(stored) == 1
    assert stored[0]["source_platform"] == "shopee"
    assert stored[0]["brand"] == "guardian"
    assert "a@example.com" not in str(stored[0]["text_redacted"])
    service.close()


def test_unique_queued_imports_wait_behind_an_active_writer(
    tmp_path: Path,
    monkeypatch,
) -> None:
    settings = Settings(
        _env_file=None,
        voc_db_path=tmp_path / "queued-imports.duckdb",
        voc_data_dir=tmp_path / "data",
        voc_inbox_dir=tmp_path / "inbox",
        voc_demo_mode=False,
        ai_provider="cached",
    )
    service = GuardianService(settings)
    service.initialize(seed_demo=False, process_existing=False)
    monkeypatch.setattr(
        service,
        "_classify_pending",
        lambda: {"analyzed": 0, "failed": 0, "review_required": 0},
    )
    monkeypatch.setattr(
        service,
        "_rebuild_insights",
        lambda *, pipeline_run_id: {"published": 0, "pipeline_run_id": pipeline_run_id},
    )
    header = "review_id,review_text,rating,review_date,product_name,store_name\n"
    first_bytes = (
        header
        + 'queued-review-1,"Guardian serum one is good",5,2026-07-11,"Serum One","Guardian"\n'
    ).encode("utf-8")
    second_bytes = (
        header
        + 'queued-review-2,"Guardian serum two is good",5,2026-07-11,"Serum Two","Guardian"\n'
    ).encode("utf-8")
    first = service.queue_import_bytes(
        filename="first.csv", content=first_bytes, profile="shopee"
    )
    second = service.queue_import_bytes(
        filename="second.csv", content=second_bytes, profile="shopee"
    )
    assert first.pipeline_run_id != second.pipeline_run_id

    active_started = threading.Event()
    release_active = threading.Event()

    def blocking_ingest() -> dict[str, int]:
        active_started.set()
        assert release_active.wait(timeout=5)
        return {"seen": 0, "inserted": 0, "skipped": 0, "failed": 0}

    try:
        with ThreadPoolExecutor(max_workers=3) as executor:
            active = executor.submit(
                service._execute_pipeline,
                trigger="test-active-writer",
                ingest=blocking_ingest,
            )
            assert active_started.wait(timeout=5)
            first_worker = executor.submit(
                service.execute_queued_import,
                pipeline_run_id=first.pipeline_run_id,
                filename="first.csv",
                content=first_bytes,
                profile="shopee",
            )
            second_worker = executor.submit(
                service.execute_queued_import,
                pipeline_run_id=second.pipeline_run_id,
                filename="second.csv",
                content=second_bytes,
                profile="shopee",
            )
            assert service.get_run(first.pipeline_run_id).status == "queued"  # type: ignore[union-attr]
            assert service.get_run(second.pipeline_run_id).status == "queued"  # type: ignore[union-attr]
            release_active.set()
            assert active.result(timeout=10).status == "completed"
            first_terminal = first_worker.result(timeout=10)
            second_terminal = second_worker.result(timeout=10)

        assert first_terminal.status == "completed"
        assert second_terminal.status == "completed"
        assert first_terminal.records_inserted == 1
        assert second_terminal.records_inserted == 1
        assert service.repository.feedback_count() == 2
    finally:
        release_active.set()
        service.close()


def test_custom_agent_mapping_is_constrained_and_used_for_import(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        voc_db_path=tmp_path / "agent-import.duckdb",
        voc_data_dir=tmp_path / "data",
        voc_inbox_dir=tmp_path / "inbox",
        voc_demo_mode=False,
        ai_provider="cached",
    )
    service = GuardianService(settings)
    service.initialize(seed_demo=False, process_existing=False)
    content = (
        "Customer Alias,Words from buyer,Score given,Listing link,Listing title\n"
        'Lan,"Sản phẩm rất tốt",5,https://shopee.vn/product/1,"Serum A"\n'
    ).encode()
    mapping = {
        "reviewer_name": "Customer Alias",
        "review_body": "Words from buyer",
        "star_rating": "Score given",
        "product_url": "Listing link",
        "product_name": "Listing title",
        "review_id": None,
        "review_date": None,
    }
    try:
        preview = service.preview_import(
            filename="unfamiliar.csv",
            content=content,
            profile="shopee",
            mapping=mapping,
        )
        assert preview["valid_rows"] == 1
        assert preview["resolved_mapping"]["text"] == "Words from buyer"
        assert preview["resolved_mapping"]["author_id"] == "Customer Alias"

        result = service.import_bytes(
            filename="unfamiliar.csv", content=content, profile="shopee", mapping=mapping
        )
        assert result.records_inserted == 1
        stored = service.database.query_one("SELECT product_name, source_url, rating, author_hash FROM feedback_items")
        assert stored is not None
        assert stored["product_name"] == "Serum A"
        assert stored["source_url"] == "https://shopee.vn/product/1"
        assert stored["rating"] == 5
        assert stored["author_hash"]
    finally:
        service.close()


def test_xlsx_first_sheet_can_be_sampled_without_macros(tmp_path: Path) -> None:
    path = tmp_path / "reviews.xlsx"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("xl/workbook.xml", '''<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Reviews" sheetId="1" r:id="rId1"/></sheets></workbook>''')
        archive.writestr("xl/_rels/workbook.xml.rels", '''<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>''')
        archive.writestr("xl/worksheets/sheet1.xml", '''<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>Buyer</t></is></c><c r="B1" t="inlineStr"><is><t>Review</t></is></c></row><row r="2"><c r="A2" t="inlineStr"><is><t>Lan</t></is></c><c r="B2" t="inlineStr"><is><t>Rất tốt</t></is></c></row></sheetData></worksheet>''')
    columns, rows = read_import_sample(path, settings=Settings(_env_file=None))
    assert columns == ["Buyer", "Review"]
    assert rows == [{"Buyer": "Lan", "Review": "Rất tốt"}]
