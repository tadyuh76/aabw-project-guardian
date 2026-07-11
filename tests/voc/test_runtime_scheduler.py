from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from guardian_voc.application import GuardianService
from guardian_voc.config import Settings
from guardian_voc.connectors.page_reader import PageContent
from guardian_voc.pipeline.dedupe import canonicalize_url, content_hash, sha256_hex
from guardian_voc.runtime import CollectorOutputWatcher, PipelineScheduler
from guardian_voc.schemas.api import RunResponse
from guardian_voc.schemas.feedback import RawFeedback


NOW = datetime(2026, 7, 11, 12, tzinfo=timezone.utc)


def _verified_export_row(
    *,
    url: str = "https://threads.com/@customer/post/verified-1",
    text: str = "Guardian giao hàng trễ và bộ phận hỗ trợ chưa phản hồi.",
    **changes: Any,
) -> dict[str, Any]:
    canonical_url = canonicalize_url(url)
    assert canonical_url is not None
    title = "Verified customer feedback"
    identity_digest = sha256_hex("url\0" + canonical_url)
    row: dict[str, Any] = {
        "feedback_id": f"feedback_{identity_digest[:32]}",
        "source_group": "social",
        "source_platform": "threads",
        "visibility": "public",
        "source_fixed_brand": None,
        # These historical classifier outputs must never become source truth.
        "primary_brand": "guardian",
        "resolved_brand": "guardian",
        "brand_candidates": ["guardian"],
        "source_experience_subject": "retailer",
        "analyzed_experience_subject": "unknown",
        "occurred_at": "2026-07-10T10:00:00+07:00",
        "occurred_at_quality": "exact",
        "observed_at": NOW.isoformat(),
        "language": "vi",
        "language_confidence": 0.99,
        "title": title,
        "text_redacted": text,
        "rating": None,
        "product_name": None,
        "product_category": None,
        "region": None,
        "store": None,
        "source_url": canonical_url,
        "canonical_url": canonical_url,
        "content_hash": content_hash(title=title, text=text),
        "analysis_status": "completed",
        "sentiment": "negative",
        "model_version": "stale-model-must-not-be-trusted",
        "evidence_span": text,
        "metric_eligible": True,
    }
    row.update(changes)
    return row


def _result(run_id: str, status: str = "completed") -> RunResponse:
    return RunResponse(
        pipeline_run_id=run_id,
        status=status,
        started_at=NOW,
        completed_at=NOW if status != "running" else None,
    )


class FakeService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.imports: list[tuple[str, bytes, str]] = []
        self.run_results: list[RunResponse] = [_result("scheduled-1")]
        self.crawls: list[str] = []
        self.live_collections: list[str] = []

    def import_bytes(self, *, filename: str, content: bytes, profile: str) -> RunResponse:
        self.imports.append((filename, content, profile))
        return _result(f"import-{len(self.imports)}")

    def run_all(self) -> RunResponse:
        return self.run_results.pop(0)

    def crawl(self, *, keyword: str) -> RunResponse:
        self.crawls.append(keyword)
        return _result(f"crawl-{keyword}")

    def run_live_collection(self) -> RunResponse:
        self.live_collections.append("strict-full-flow")
        return _result(f"live-collection-{len(self.live_collections)}")


class FakePageReader:
    def __init__(self, *, failing_suffixes: tuple[str, ...] = ()) -> None:
        self.failing_suffixes = failing_suffixes
        self.calls: list[str] = []
        self.active = 0
        self.maximum_active = 0

    async def read(self, url: str, *, platform: str | None = None) -> PageContent:
        import asyncio

        self.calls.append(url)
        self.active += 1
        self.maximum_active = max(self.maximum_active, self.active)
        try:
            await asyncio.sleep(0.01)
            if url.endswith(self.failing_suffixes):
                raise RuntimeError(
                    f"provider failed for {url}; key=do-not-log; body=do-not-log"
                )
            return PageContent(
                url=url,
                title="Verified page title",
                text=f"Verified Guardian customer page content from {platform}.",
                reader="fake_page_reader",
            )
        finally:
            self.active -= 1


def test_environment_aliases_and_secret_files_do_not_leak(
    tmp_path: Path, monkeypatch: Any
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", " openai-test-key ")
    monkeypatch.setenv("TINY_FISH_API_KEY", " tinyfish-test-key ")
    configured = Settings(_env_file=None, tinyfish_enabled=True)

    assert configured.ai_api_key == "openai-test-key"
    assert configured.tinyfish_resolved_api_key == "tinyfish-test-key"
    assert "openai-test-key" not in repr(configured)
    assert "tinyfish-test-key" not in repr(configured)
    dumped = configured.model_dump()
    assert "ai_api_key" not in dumped
    assert "tinyfish_api_key" not in dumped

    monkeypatch.delenv("OPENAI_API_KEY")
    monkeypatch.delenv("TINY_FISH_API_KEY")
    admin_file = tmp_path / "admin"
    openai_file = tmp_path / "openai"
    serp_file = tmp_path / "serp"
    admin_file.write_text("file-admin-token\n", encoding="utf-8")
    openai_file.write_text("file-openai-key\n", encoding="utf-8")
    serp_file.write_text("file-serp-key\n", encoding="utf-8")
    from_files = Settings(
        _env_file=None,
        voc_write_api_enabled=True,
        voc_admin_token_file=admin_file,
        ai_api_key_file=openai_file,
        serp_api_key_file=serp_file,
    )
    assert from_files.ai_api_key == "file-openai-key"
    assert from_files.serp_api_key == "file-serp-key"
    assert from_files.voc_admin_token == "file-admin-token"
    assert "file-openai-key" not in repr(from_files)
    assert "file-serp-key" not in repr(from_files)
    assert "file-admin-token" not in repr(from_files)
    assert "voc_admin_token" not in from_files.model_dump()

    empty_admin_file = tmp_path / "empty-admin"
    empty_admin_file.touch()
    with pytest.raises(ValidationError, match="VOC_ADMIN_TOKEN_FILE"):
        Settings(
            _env_file=None,
            voc_write_api_enabled=True,
            voc_admin_token_file=empty_admin_file,
        )

    with pytest.raises(ValidationError) as error:
        Settings(
            _env_file=None,
            voc_demo_mode=True,
            voc_scheduler_enabled=True,
            voc_scheduler_crawl_enabled=False,
            ai_provider="openai_compatible",
            ai_api_key="validation-secret-key",
        )
    assert "validation-secret-key" not in str(error.value)

    with pytest.raises(ValidationError, match="cannot be used in demo mode"):
        Settings(
            _env_file=None,
            voc_collector_enrichment_enabled=True,
            tinyfish_enabled=True,
            tinyfish_api_key="test-key",
        )

    with pytest.raises(ValidationError, match="TinyFish must be enabled"):
        Settings(
            _env_file=None,
            voc_demo_mode=False,
            voc_collector_enrichment_enabled=True,
        )

    with pytest.raises(ValidationError, match="SERP_API_KEY"):
        Settings(
            _env_file=None,
            voc_demo_mode=False,
            voc_scheduler_enabled=True,
            voc_scheduler_full_flow_enabled=True,
            ai_provider="openai_compatible",
            ai_api_key="test-openai-key",
            tinyfish_enabled=True,
            tinyfish_api_key="test-tinyfish-key",
        )


def test_collector_watcher_is_stable_idempotent_and_preserves_provenance(
    tmp_path: Path,
) -> None:
    source = tmp_path / "guardian.customer-candidates.vi.jsonl"
    source.write_text(
        json.dumps(
            {
                "record_id": "crawler-record",
                "canonical_url": "https://facebook.com/customer/posts/42",
                "platform": "facebook",
                "title": "Guardian review",
                "description": "Search snippet is discovery evidence only.",
                "page_reader_result": {
                    "title": "Guardian review",
                    "text": "Guardian giao hàng trễ và hỗ trợ chưa phản hồi.",
                    "reader": "tinyfish",
                },
                "published_date": "2026-07-10",
                "observed_at": NOW.isoformat(),
                "brand_candidates": ["guardian"],
                "query_brand_candidates": ["guardian", "hasaki", "watsons"],
                "matched_query_ids": ["delivery-all-brands"],
                "matched_query_labels_vi": ["Giao hàng nhà thuốc"],
                "topics": ["delivery_fulfilment"],
                "has_brand_evidence": True,
                "eligible_for_time_analytics": True,
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    settings = Settings(
        _env_file=None,
        voc_data_dir=tmp_path / "data",
        voc_collector_files=(source,),
        voc_collector_checkpoint_path=tmp_path / "data" / "checkpoint.json",
    )
    service = FakeService(settings)
    watcher = CollectorOutputWatcher(service, settings)  # type: ignore[arg-type]

    first = watcher.poll()
    second = watcher.poll()

    assert len(first) == 1
    assert second == []
    assert len(service.imports) == 1
    filename, payload, profile = service.imports[0]
    assert filename.endswith(".jsonl")
    assert profile == "generic"
    raw = RawFeedback.model_validate_json(payload.decode("utf-8").strip())
    assert [item.value for item in raw.brand_candidates] == ["guardian"]
    assert raw.source_url == "https://facebook.com/customer/posts/42"
    assert raw.metadata["query_brand_candidates"] == ["guardian", "hasaki", "watsons"]
    assert raw.metadata["matched_query_ids"] == ["delivery-all-brands"]
    assert raw.metadata["eligible_for_time_analytics"] is True
    assert raw.metadata["content_provenance"]["source"] == "tinyfish"
    assert watcher.snapshot()["mapped_rows"] == 1
    assert watcher.snapshot()["discovery_only_rows"] == 0
    assert settings.voc_collector_checkpoint_path is not None
    assert settings.voc_collector_checkpoint_path.stat().st_mode & 0o777 == 0o600


def test_verified_export_is_reclassified_without_trusting_old_analysis(
    tmp_path: Path,
) -> None:
    source = tmp_path / "analysis_ready.jsonl"
    first_row = _verified_export_row()
    source.write_text(
        json.dumps(first_row, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    settings = Settings(
        _env_file=None,
        voc_data_dir=tmp_path / "data",
        voc_verified_feedback_files=(source,),
        voc_collector_checkpoint_path=tmp_path / "data" / "checkpoint.json",
    )
    service = FakeService(settings)
    watcher = CollectorOutputWatcher(service, settings)  # type: ignore[arg-type]

    assert len(watcher.poll()) == 1
    assert watcher.poll() == []
    assert len(service.imports) == 1
    filename, payload, profile = service.imports[0]
    assert filename == "verified-analysis_ready.jsonl"
    assert profile == "generic"
    raw = RawFeedback.model_validate_json(payload.decode("utf-8").strip())
    assert raw.source_external_id == first_row["feedback_id"]
    assert raw.text == first_row["text_redacted"]
    assert raw.brand is None
    assert [candidate.value for candidate in raw.brand_candidates] == ["guardian"]
    assert raw.metadata["strict_extraction_verified"] is True
    assert raw.metadata["content_provenance"] == {
        "kind": "strict_page_extraction",
        "source": "verified_feedback_export",
    }
    assert "model_version" not in payload.decode("utf-8")
    assert "sentiment" not in raw.metadata
    assert "evidence_span" not in raw.metadata

    snapshot = watcher.snapshot()
    assert snapshot["status"] == "unchanged"
    assert snapshot["watched_files"] == 1
    assert snapshot["raw_discovery_files"] == 0
    assert snapshot["verified_feedback_files"] == 1
    assert snapshot["verified_rows"] == 1
    assert snapshot["verified_mapped_rows"] == 1
    assert snapshot["verified_rejected_rows"] == 0

    # The producer rewrites a cumulative export. Its new fingerprint triggers
    # another canonical import; the real repository skips old IDs and inserts
    # only newly verified feedback before current-model classification.
    second_row = _verified_export_row(
        url="https://threads.com/@customer/post/verified-2",
        text="Guardian xử lý đổi trả rất nhanh và nhân viên hỗ trợ rõ ràng.",
    )
    source.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False) + "\n"
            for row in (first_row, second_row)
        ),
        encoding="utf-8",
    )
    assert len(watcher.poll()) == 1
    assert len(service.imports) == 2
    imported_rows = [
        RawFeedback.model_validate_json(line)
        for line in service.imports[-1][1].decode("utf-8").splitlines()
    ]
    assert [row.source_external_id for row in imported_rows] == [
        first_row["feedback_id"],
        second_row["feedback_id"],
    ]
    assert watcher.snapshot()["verified_mapped_rows"] == 2


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        ("feedback_id", "feedback_invalid"),
        ("content_hash", "0" * 64),
        ("text_redacted", "   "),
        ("source_group", "unknown"),
        ("source_platform", "threads\nforged"),
        ("source_url", "javascript:alert(1)"),
        ("is_synthetic", True),
    ],
    ids=(
        "feedback-id",
        "content-hash",
        "text",
        "source-group",
        "source-platform",
        "source-url",
        "synthetic",
    ),
)
def test_verified_export_rejects_the_whole_malformed_snapshot_for_retry(
    tmp_path: Path,
    field: str,
    bad_value: Any,
) -> None:
    source = tmp_path / "analysis_ready.jsonl"
    row = _verified_export_row()
    row[field] = bad_value
    source.write_text(json.dumps(row) + "\n", encoding="utf-8")
    settings = Settings(
        _env_file=None,
        voc_data_dir=tmp_path / "data",
        voc_verified_feedback_files=(source,),
    )
    service = FakeService(settings)
    watcher = CollectorOutputWatcher(service, settings)  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="failed strict validation"):
        watcher.poll()
    assert service.imports == []
    assert watcher.snapshot()["status"] == "failed"
    assert watcher.snapshot()["verified_rows"] == 1
    assert watcher.snapshot()["verified_rejected_rows"] == 1
    assert not watcher.checkpoint_path.exists()

    # Rejected fingerprints are never checkpointed or silently discarded.
    with pytest.raises(RuntimeError, match="failed strict validation"):
        watcher.poll()
    assert service.imports == []


def test_strict_schema_is_trusted_only_on_the_explicit_verified_path(
    tmp_path: Path,
) -> None:
    source = tmp_path / "analysis_ready.jsonl"
    source.write_text(json.dumps(_verified_export_row()) + "\n", encoding="utf-8")
    settings = Settings(
        _env_file=None,
        voc_data_dir=tmp_path / "data",
        # Deliberately configure the strict-looking row as an ordinary search
        # discovery snapshot. It must not cross the content trust boundary.
        voc_collector_files=(source,),
    )
    service = FakeService(settings)
    watcher = CollectorOutputWatcher(service, settings)  # type: ignore[arg-type]

    assert watcher.poll() == []
    assert service.imports == []
    snapshot = watcher.snapshot()
    assert snapshot["status"] == "discovery_only"
    assert snapshot["discovered_rows"] == 1
    assert snapshot["mapped_rows"] == 0
    assert snapshot["verified_rows"] == 0


def test_watcher_aggregates_search_discovery_and_verified_export_health(
    tmp_path: Path,
) -> None:
    discovery = tmp_path / "search.jsonl"
    discovery.write_text(
        json.dumps(
            {
                "canonical_url": "https://threads.com/@customer/post/discovery",
                "platform": "threads",
                "title": "Search result title",
                "description": "Search snippet must remain discovery evidence.",
                "scraper_source": "serpapi_google",
                "observed_at": NOW.isoformat(),
                "brand_candidates": ["guardian"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    verified = tmp_path / "analysis_ready.jsonl"
    verified.write_text(json.dumps(_verified_export_row()) + "\n", encoding="utf-8")
    settings = Settings(
        _env_file=None,
        voc_data_dir=tmp_path / "data",
        voc_collector_files=(discovery,),
        voc_verified_feedback_files=(verified,),
    )
    service = FakeService(settings)
    watcher = CollectorOutputWatcher(service, settings)  # type: ignore[arg-type]

    assert len(watcher.poll()) == 1
    assert len(service.imports) == 1
    assert watcher.poll() == []
    snapshot = watcher.snapshot()
    assert snapshot["status"] == "partial"
    assert snapshot["watched_files"] == 2
    assert snapshot["discovered_rows"] == 1
    assert snapshot["discovery_only_rows"] == 1
    assert snapshot["mapped_rows"] == 0
    assert snapshot["verified_rows"] == 1
    assert snapshot["verified_mapped_rows"] == 1
    assert "Search titles and snippets were excluded" in snapshot["source_note"]
    assert "1 accepted for normal classification" in snapshot["source_note"]


def test_collector_watcher_checkpoints_discovery_only_rows_without_importing(
    tmp_path: Path,
) -> None:
    source = tmp_path / "guardian.customer-candidates.vi.jsonl"
    source.write_text(
        json.dumps(
            {
                "record_id": "search-result-only",
                "canonical_url": "https://facebook.com/customer/posts/99",
                "platform": "facebook",
                "title": "Search result title",
                "description": "Search snippet must not become a customer quote.",
                "scraper_source": "serpapi_google",
                "observed_at": NOW.isoformat(),
                "brand_candidates": ["guardian"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    settings = Settings(
        _env_file=None,
        voc_data_dir=tmp_path / "data",
        voc_collector_files=(source,),
        voc_collector_checkpoint_path=tmp_path / "data" / "checkpoint.json",
    )
    service = FakeService(settings)
    watcher = CollectorOutputWatcher(service, settings)  # type: ignore[arg-type]

    assert watcher.poll() == []
    assert watcher.poll() == []
    assert service.imports == []
    snapshot = watcher.snapshot()
    assert snapshot["status"] == "discovery_only"
    assert snapshot["watched_files"] == 1
    assert snapshot["last_file"] == source.name
    assert snapshot["last_checked_at"] is not None
    assert snapshot["last_imported_at"] is None
    assert snapshot["discovered_rows"] == 1
    assert snapshot["mapped_rows"] == 0
    assert snapshot["discovery_only_rows"] == 1
    checkpoint = json.loads(
        settings.voc_collector_checkpoint_path.read_text(encoding="utf-8")
    )
    stored = next(iter(checkpoint["files"].values()))
    assert stored["mapped_rows"] == 0
    assert stored["discovery_only_rows"] == 1
    restarted = CollectorOutputWatcher(FakeService(settings), settings)  # type: ignore[arg-type]
    assert restarted.poll() == []
    assert restarted.snapshot()["status"] == "discovery_only"
    assert restarted.snapshot()["last_checked_at"] is not None
    assert restarted.snapshot()["discovered_rows"] == 1


def test_collector_enrichment_is_guardian_only_bounded_and_aggregate_safe(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    source = tmp_path / "guardian.customer-candidates.vi.jsonl"
    rows = [
        {
            "record_id": "guardian-success",
            "canonical_url": "https://facebook.com/customer/posts/success",
            "platform": "facebook",
            "title": "SEARCH TITLE MUST NOT ENTER FEEDBACK",
            "description": "SEARCH SNIPPET MUST NOT ENTER FEEDBACK",
            "scraper_source": "serpapi_google",
            "observed_at": NOW.isoformat(),
            "brand_candidates": ["guardian"],
        },
        {
            "record_id": "hasaki-skip",
            "canonical_url": "https://facebook.com/customer/posts/hasaki",
            "platform": "facebook",
            "description": "HASAKI SEARCH SNIPPET",
            "scraper_source": "serpapi_google",
            "observed_at": NOW.isoformat(),
            "brand_candidates": ["hasaki"],
            "query_brand_candidates": ["guardian"],
        },
        {
            "record_id": "guardian-fail",
            "canonical_url": "https://facebook.com/customer/posts/fail",
            "platform": "facebook",
            "description": "FAILED SEARCH SNIPPET",
            "scraper_source": "serpapi_google",
            "observed_at": NOW.isoformat(),
            "brand_candidates": ["guardian"],
        },
        {
            "record_id": "guardian-over-budget",
            "canonical_url": "https://facebook.com/customer/posts/over-budget",
            "platform": "facebook",
            "description": "OVER BUDGET SEARCH SNIPPET",
            "scraper_source": "serpapi_google",
            "observed_at": NOW.isoformat(),
            "brand_candidates": ["guardian"],
        },
    ]
    source.write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
    )
    settings = Settings(
        _env_file=None,
        voc_demo_mode=False,
        voc_data_dir=tmp_path / "data",
        voc_collector_files=(source,),
        voc_collector_enrichment_enabled=True,
        voc_collector_enrichment_max_rows=2,
        voc_collector_enrichment_concurrency=2,
        tinyfish_enabled=True,
        tinyfish_api_key="test-key",
    )
    service = FakeService(settings)
    reader = FakePageReader(failing_suffixes=("/fail",))
    watcher = CollectorOutputWatcher(
        service, settings, page_reader=reader  # type: ignore[arg-type]
    )

    caplog.set_level("WARNING", logger="guardian_voc.runtime")
    assert len(watcher.poll()) == 1
    assert watcher.poll() == []

    assert len(reader.calls) == 2
    assert reader.maximum_active == 2
    assert all("hasaki" not in url and "over-budget" not in url for url in reader.calls)
    _, payload, _ = service.imports[0]
    imported = RawFeedback.model_validate_json(payload.decode("utf-8").strip())
    assert "Verified Guardian customer page content" in imported.text
    assert imported.title == "Verified page title"
    assert "SEARCH TITLE" not in (imported.title or "")
    assert "SEARCH SNIPPET" not in imported.text
    # Discovery copy remains isolated audit provenance, never feedback text.
    assert imported.metadata["discovery_description"] == (
        "SEARCH SNIPPET MUST NOT ENTER FEEDBACK"
    )
    snapshot = watcher.snapshot()
    assert snapshot["discovered_rows"] == 4
    assert snapshot["mapped_rows"] == 1
    assert snapshot["discovery_only_rows"] == 3
    assert snapshot["enrichment_attempted_rows"] == 2
    assert snapshot["enrichment_succeeded_rows"] == 1
    assert snapshot["enrichment_failed_rows"] == 1
    assert "Guardian-only page enrichment attempted 2; 1 failed" in snapshot[
        "source_note"
    ]
    public_diagnostics = snapshot["source_note"] + caplog.text
    assert "do-not-log" not in public_diagnostics
    assert "/customer/posts/" not in public_diagnostics


def test_failed_page_enrichment_is_checkpointed_once_per_snapshot(
    tmp_path: Path,
) -> None:
    source = tmp_path / "guardian.customer-candidates.vi.jsonl"
    source.write_text(
        json.dumps(
            {
                "record_id": "guardian-fail",
                "canonical_url": "https://facebook.com/customer/posts/fail",
                "platform": "facebook",
                "description": "Search snippet",
                "scraper_source": "serpapi_google",
                "observed_at": NOW.isoformat(),
                "brand_candidates": ["guardian"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    settings = Settings(
        _env_file=None,
        voc_demo_mode=False,
        voc_data_dir=tmp_path / "data",
        voc_collector_files=(source,),
        voc_collector_enrichment_enabled=True,
        tinyfish_enabled=True,
        tinyfish_api_key="test-key",
    )
    reader = FakePageReader(failing_suffixes=("/fail",))
    watcher = CollectorOutputWatcher(
        FakeService(settings), settings, page_reader=reader  # type: ignore[arg-type]
    )

    assert watcher.poll() == []
    assert watcher.poll() == []
    assert len(reader.calls) == 1
    assert watcher.snapshot()["enrichment_failed_rows"] == 1

    restarted_reader = FakePageReader(failing_suffixes=("/fail",))
    restarted = CollectorOutputWatcher(
        FakeService(settings),
        settings,
        page_reader=restarted_reader,  # type: ignore[arg-type]
    )
    assert restarted.poll() == []
    assert restarted_reader.calls == []
    restarted_snapshot = restarted.snapshot()
    assert restarted_snapshot["enrichment_attempted_rows"] == 1
    assert restarted_snapshot["enrichment_failed_rows"] == 1


def test_successful_page_read_is_reused_in_memory_when_import_retries(
    tmp_path: Path,
) -> None:
    source = tmp_path / "guardian.customer-candidates.vi.jsonl"
    source.write_text(
        json.dumps(
            {
                "record_id": "guardian-success",
                "canonical_url": "https://facebook.com/customer/posts/success",
                "platform": "facebook",
                "description": "Search snippet",
                "scraper_source": "serpapi_google",
                "observed_at": NOW.isoformat(),
                "brand_candidates": ["guardian"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    settings = Settings(
        _env_file=None,
        voc_demo_mode=False,
        voc_data_dir=tmp_path / "data",
        voc_collector_files=(source,),
        voc_collector_enrichment_enabled=True,
        tinyfish_enabled=True,
        tinyfish_api_key="test-key",
    )

    class FailOnceService(FakeService):
        def import_bytes(
            self, *, filename: str, content: bytes, profile: str
        ) -> RunResponse:
            self.imports.append((filename, content, profile))
            return _result(
                f"import-{len(self.imports)}",
                "failed" if len(self.imports) == 1 else "completed",
            )

    service = FailOnceService(settings)
    reader = FakePageReader()
    watcher = CollectorOutputWatcher(
        service, settings, page_reader=reader  # type: ignore[arg-type]
    )

    with pytest.raises(RuntimeError, match="collector import pipeline failed"):
        watcher.poll()
    assert len(reader.calls) == 1
    assert not watcher.checkpoint_path.exists()

    assert len(watcher.poll()) == 1
    assert len(reader.calls) == 1
    assert watcher.checkpoint_path.is_file()


def test_collector_does_not_checkpoint_a_failed_mapped_import(tmp_path: Path) -> None:
    source = tmp_path / "collector.jsonl"
    source.write_text(
        json.dumps(
            {
                "record_id": "extractable",
                "canonical_url": "https://facebook.com/customer/posts/7",
                "platform": "facebook",
                "observed_at": NOW.isoformat(),
                "brand_candidates": ["guardian"],
                "page_reader_result": {
                    "text": "Guardian giao hàng trễ.",
                    "reader": "tinyfish",
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    settings = Settings(
        _env_file=None,
        voc_data_dir=tmp_path / "data",
        voc_collector_files=(source,),
    )

    class FailOnceService(FakeService):
        def import_bytes(
            self, *, filename: str, content: bytes, profile: str
        ) -> RunResponse:
            self.imports.append((filename, content, profile))
            return _result(
                f"import-{len(self.imports)}",
                "failed" if len(self.imports) == 1 else "completed",
            )

    service = FailOnceService(settings)
    watcher = CollectorOutputWatcher(service, settings)  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="collector import pipeline failed"):
        watcher.poll()
    assert not watcher.checkpoint_path.exists()

    assert len(watcher.poll()) == 1
    assert len(service.imports) == 2
    assert watcher.checkpoint_path.is_file()


def test_discovery_only_snapshot_is_visible_as_partial_source_health(
    tmp_path: Path,
) -> None:
    source = tmp_path / "collector.jsonl"
    source.write_text(
        json.dumps(
            {
                "record_id": "discovery-only",
                "canonical_url": "https://facebook.com/customer/posts/8",
                "platform": "facebook",
                "title": "Search title",
                "description": "Search snippet",
                "scraper_source": "serpapi_google",
                "observed_at": NOW.isoformat(),
                "brand_candidates": ["guardian"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    settings = Settings(
        _env_file=None,
        voc_db_path=tmp_path / "guardian.duckdb",
        voc_data_dir=tmp_path / "data",
        voc_collector_files=(source,),
    )
    service = GuardianService(settings)
    try:
        service.initialize(seed_demo=False)
        watcher = CollectorOutputWatcher(service, settings)
        assert watcher.poll() == []
        status = service.repository.get_source_status("collector_public_social")
        assert status is not None
        assert status.status.value == "partial"
        assert status.last_success_at is not None
        assert status.recent_volume == 0
        assert "Watched search snapshot: 1 public candidates" in (status.notes or "")
        assert "not treated as customer feedback" in (status.notes or "")
        view = service._source_status_views("en")[0]
        assert view.status == "partial"
        assert "Watched search snapshot: 1 public candidates" in (view.note or "")
    finally:
        service.close()


def test_scheduler_processes_inbox_without_duplicate_paid_crawls_and_backs_off(
    tmp_path: Path,
) -> None:
    settings = Settings(
        _env_file=None,
        voc_demo_mode=False,
        voc_scheduler_enabled=True,
        voc_scheduler_crawl_enabled=False,
        voc_scheduler_interval_seconds=5,
        voc_scheduler_max_backoff_seconds=20,
        ai_provider="openai_compatible",
        ai_api_key="test-key",
        voc_data_dir=tmp_path,
    )
    service = FakeService(settings)
    service.run_results = [_result("failed-run", "failed"), _result("successful-run")]
    scheduler = PipelineScheduler(service, settings)  # type: ignore[arg-type]

    assert scheduler.run_once() is False
    failed = scheduler.snapshot()
    assert failed["state"] == "backoff"
    assert failed["consecutive_failures"] == 1
    assert failed["last_run_id"] == "failed-run"
    assert scheduler._delay_after_cycle() == 5

    assert scheduler.run_once() is True
    recovered = scheduler.snapshot()
    assert recovered["state"] == "idle"
    assert recovered["consecutive_failures"] == 0
    assert recovered["last_run_id"] == "successful-run"
    assert service.crawls == []


def test_scheduler_runs_one_strict_full_flow_per_cycle_before_waiting(
    tmp_path: Path,
) -> None:
    settings = Settings(
        _env_file=None,
        voc_demo_mode=False,
        voc_scheduler_enabled=True,
        voc_scheduler_full_flow_enabled=True,
        voc_scheduler_interval_seconds=1_800,
        ai_provider="openai_compatible",
        ai_api_key="test-openai-key",
        serp_api_key="test-serp-key",
        tinyfish_enabled=True,
        tinyfish_api_key="test-tinyfish-key",
        voc_live_collection_source_ids=("guardian_public_social",),
        voc_data_dir=tmp_path,
    )
    service = FakeService(settings)
    scheduler = PipelineScheduler(service, settings)  # type: ignore[arg-type]

    assert scheduler.run_once() is True

    snapshot = scheduler.snapshot()
    assert service.live_collections == ["strict-full-flow"]
    assert service.crawls == []
    assert snapshot["interval_seconds"] == 1_800
    assert snapshot["full_flow_enabled"] is True
    assert snapshot["full_flow_source_ids"] == ["guardian_public_social"]
    assert snapshot["last_run_id"] == "live-collection-1"


def test_invalid_optional_collector_snapshot_does_not_block_strict_full_flow(
    tmp_path: Path,
) -> None:
    settings = Settings(
        _env_file=None,
        voc_demo_mode=False,
        voc_scheduler_enabled=True,
        voc_scheduler_full_flow_enabled=True,
        ai_provider="openai_compatible",
        ai_api_key="test-openai-key",
        serp_api_key="test-serp-key",
        tinyfish_enabled=True,
        tinyfish_api_key="test-tinyfish-key",
        voc_data_dir=tmp_path,
    )
    service = FakeService(settings)
    scheduler = PipelineScheduler(service, settings)  # type: ignore[arg-type]

    class InvalidCollector:
        def poll(self) -> list[RunResponse]:
            raise RuntimeError("invalid optional snapshot")

        def snapshot(self) -> dict[str, Any]:
            return {"status": "failed"}

    scheduler.collector = InvalidCollector()  # type: ignore[assignment]

    assert scheduler.run_once() is False
    assert service.live_collections == ["strict-full-flow"]
    assert scheduler.snapshot()["state"] == "backoff"
