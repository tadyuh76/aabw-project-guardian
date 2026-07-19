"""Guardian Signal HTTP API and production static-file host."""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Annotated, Literal

from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from guardian_voc.application import GuardianService, get_service
from guardian_voc.config import Settings, get_settings
from guardian_voc.runtime import PipelineScheduler
from guardian_voc.schemas.api import (
    DashboardResponse,
    DashboardProblemDetailView,
    EvidenceResponse,
    FeedbackListResponse,
    InsightCardView,
    InsightPatchRequest,
    LiveCollectionRequest,
    Role,
    RunResponse,
    TodayResponse,
)


logger = logging.getLogger(__name__)

REVIEW_CSV_PROFILES = (
    "guardian_ecommerce",
    "tiktok_shop",
    "shopee",
    "lazada",
    "grabmart",
)

MARKETPLACE_SELLER_URLS = {
    "shopee": "https://seller.shopee.vn/",
    "lazada": "https://sellercenter.lazada.vn/",
    "tiktok_shop": "https://seller-vn.tiktok.com/",
    "grabmart": "https://merchant.grab.com/",
    "guardian_ecommerce": "https://www.guardian.com.vn/",
}


def _mapping_json(value: str | None) -> dict[str, str | None] | None:
    if not value:
        return None
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError("mapping must be a JSON object")
    return {str(key): None if item is None else str(item) for key, item in parsed.items()}


@asynccontextmanager
async def lifespan(app: FastAPI):
    service = get_service()
    await asyncio.to_thread(
        service.initialize,
        seed_demo=service.settings.voc_demo_mode,
        process_existing=service.settings.voc_process_existing_on_startup,
    )
    scheduler = PipelineScheduler(service, service.settings)
    scheduler.start()
    app.state.service = service
    app.state.scheduler = scheduler
    yield
    stopped = await asyncio.to_thread(scheduler.stop)
    if stopped:
        service.close()
    else:
        # The daemon thread will exit with the process. Do not close its active
        # DuckDB connection underneath an in-flight network pipeline.
        logger.error("pipeline scheduler did not stop within the shutdown timeout")


settings = get_settings()
app = FastAPI(
    title="Guardian Signal API",
    version="0.1.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.voc_cors_origins),
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
    allow_headers=["Content-Type", "X-Admin-Token"],
)


def service_from_request(request: Request) -> GuardianService:
    return getattr(request.app.state, "service", get_service())


def scheduler_from_request(request: Request) -> PipelineScheduler | None:
    return getattr(request.app.state, "scheduler", None)


def _latest_run(service: GuardianService) -> RunResponse | None:
    row = service.database.query_one(
        "SELECT id FROM pipeline_runs ORDER BY started_at DESC, id DESC LIMIT 1"
    )
    return service.get_run(str(row["id"])) if row is not None else None


def require_admin(
    request: Request,
    x_admin_token: Annotated[str | None, Header(alias="X-Admin-Token")] = None,
) -> None:
    current: Settings = service_from_request(request).settings
    if not current.voc_write_api_enabled:
        raise HTTPException(status_code=403, detail="Write APIs are disabled")
    if not current.voc_admin_token or not x_admin_token:
        raise HTTPException(status_code=401, detail="A valid admin token is required")
    if not hmac.compare_digest(x_admin_token, current.voc_admin_token):
        raise HTTPException(status_code=401, detail="A valid admin token is required")


def require_import_api(
    request: Request,
) -> None:
    current: Settings = service_from_request(request).settings
    if not current.review_imports_enabled:
        raise HTTPException(status_code=403, detail="Review imports are disabled")


@app.get("/api/v1/health")
def health(
    request: Request,
    service: Annotated[GuardianService, Depends(service_from_request)],
) -> dict:
    payload = service.health()
    scheduler = scheduler_from_request(request)
    payload["scheduler"] = scheduler.snapshot() if scheduler is not None else {
        "enabled": False,
        "state": "unavailable",
    }
    latest = _latest_run(service)
    payload["last_pipeline_run"] = (
        latest.model_dump(mode="json") if latest is not None else None
    )
    return payload


@app.get("/api/v1/live")
def live() -> dict[str, str]:
    """Process liveness probe that does not depend on external providers."""

    return {"status": "alive"}


@app.get("/api/v1/runtime")
def runtime(request: Request) -> dict:
    """Non-blocking scheduler state for operators and deployment scripts."""

    scheduler = scheduler_from_request(request)
    return scheduler.snapshot() if scheduler is not None else {
        "enabled": False,
        "state": "unavailable",
    }


@app.get("/api/v1/ready")
def ready(
    request: Request,
    service: Annotated[GuardianService, Depends(service_from_request)],
) -> dict:
    # Do not acquire GuardianService's pipeline lock here: a healthy scheduled
    # classification may be long-running and must not make the container fail
    # readiness. The Database wrapper serializes this short connection check.
    service.database.query_one("SELECT 1 AS ready")
    schema_version = service.database.schema_version()
    scheduler = scheduler_from_request(request)
    scheduler_status = scheduler.snapshot() if scheduler is not None else None
    if (
        scheduler_status
        and scheduler_status["enabled"]
        and not scheduler_status["thread_alive"]
        and scheduler_status["state"] not in {"starting", "stopping"}
    ):
        raise HTTPException(status_code=503, detail="Pipeline scheduler is not running")
    return {
        "status": "ready",
        "database": "ready",
        "schema_version": schema_version,
        "scheduler": scheduler_status,
    }


@app.get("/api/v1/today", response_model=TodayResponse)
def today(
    service: Annotated[GuardianService, Depends(service_from_request)],
    role: Role = "leadership",
    locale: str | None = Query(default=None, pattern="^(en|vi)$"),
) -> TodayResponse:
    return service.today(role=role, locale=locale)


@app.get("/api/v1/dashboard", response_model=DashboardResponse)
def dashboard(
    service: Annotated[GuardianService, Depends(service_from_request)],
    dashboard_range: Literal["7d", "30d", "1y", "all", "custom"] = Query(
        default="all",
        alias="range",
    ),
    date_from: date | None = None,
    date_to: date | None = None,
) -> DashboardResponse:
    try:
        return service.dashboard(
            dashboard_range=dashboard_range,
            date_from=date_from,
            date_to=date_to,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get(
    "/api/v1/dashboard/problems/{problem}",
    response_model=DashboardProblemDetailView,
)
async def dashboard_problem_detail(
    problem: str,
    service: Annotated[GuardianService, Depends(service_from_request)],
    preset: str = Query(default="all", pattern="^(7d|30d|1y|all|custom)$"),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
) -> DashboardProblemDetailView:
    try:
        return await service.problem_detail(
            problem=problem,
            preset=preset,
            start_date=start_date,
            end_date=end_date,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/v1/insights", response_model=list[InsightCardView])
def insights(service: Annotated[GuardianService, Depends(service_from_request)]) -> list[InsightCardView]:
    return service.insights()


@app.get("/api/v1/insights/{insight_id}", response_model=InsightCardView)
def insight(
    insight_id: str,
    service: Annotated[GuardianService, Depends(service_from_request)],
) -> InsightCardView:
    value = service.insight(insight_id)
    if value is None:
        raise HTTPException(status_code=404, detail="Insight not found")
    return value


@app.get("/api/v1/insights/{insight_id}/evidence", response_model=EvidenceResponse)
def evidence(
    insight_id: str,
    service: Annotated[GuardianService, Depends(service_from_request)],
) -> EvidenceResponse:
    value = service.evidence(insight_id)
    if value is None:
        raise HTTPException(status_code=404, detail="Insight not found")
    return value


@app.patch(
    "/api/v1/insights/{insight_id}",
    response_model=InsightCardView,
    dependencies=[Depends(require_admin)],
)
def patch_insight(
    insight_id: str,
    payload: InsightPatchRequest,
    service: Annotated[GuardianService, Depends(service_from_request)],
) -> InsightCardView:
    value = service.patch_insight(insight_id, payload)
    if value is None:
        raise HTTPException(status_code=404, detail="Insight not found")
    return value


@app.get("/api/v1/feedback", response_model=FeedbackListResponse)
def feedback(
    service: Annotated[GuardianService, Depends(service_from_request)],
    source_group: str | None = None,
    source_platform: str | None = None,
    brand: str | None = None,
    topic: str | None = None,
    sentiment: str | None = None,
    insight_id: str | None = None,
    q: str | None = Query(default=None, max_length=200),
    date_from: date | None = None,
    date_to: date | None = None,
    min_confidence: float | None = Query(default=None, ge=0, le=1),
    max_confidence: float | None = Query(default=None, ge=0, le=1),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> FeedbackListResponse:
    try:
        return service.feedback(
            source_group=source_group,
            source_platform=source_platform,
            brand=brand,
            topic=topic,
            sentiment=sentiment,
            insight_id=insight_id,
            query=q,
            date_from=date_from,
            date_to=date_to,
            min_confidence=min_confidence,
            max_confidence=max_confidence,
            limit=limit,
            offset=offset,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/v1/benchmarks")
def benchmarks(service: Annotated[GuardianService, Depends(service_from_request)]) -> dict:
    return service.benchmarks()


@app.get("/api/v1/data-health")
def data_health(service: Annotated[GuardianService, Depends(service_from_request)]) -> dict:
    return service.data_health()


@app.get("/api/v1/imports/config")
def import_config(
    service: Annotated[GuardianService, Depends(service_from_request)],
) -> dict:
    """Expose safe upload capabilities without exposing the admin token."""

    latest = service.database.query_one(
        """
        SELECT max(files.first_imported_at) AS last_import_at
        FROM imported_files files
        JOIN ingestion_runs runs ON runs.id = files.last_ingestion_run_id
        WHERE runs.status IN ('completed', 'partial')
        """
    )
    latest_by_profile = service.database.query(
        """
        SELECT files.source_name AS profile, max(files.first_imported_at) AS last_import_at
        FROM imported_files files
        JOIN ingestion_runs runs ON runs.id = files.last_ingestion_run_id
        WHERE runs.status IN ('completed', 'partial')
          AND files.source_name IN (?, ?, ?, ?, ?)
        GROUP BY files.source_name
        """,
        list(REVIEW_CSV_PROFILES),
    )
    return {
        "enabled": service.settings.review_imports_enabled,
        "max_bytes": service.settings.voc_max_import_bytes,
        "profiles": list(REVIEW_CSV_PROFILES),
        "accepted_extensions": [".csv", ".xlsx"],
        "agentic_detection_enabled": bool(service.settings.ai_api_key),
        "seller_urls": MARKETPLACE_SELLER_URLS,
        "last_import_at": latest.get("last_import_at") if latest else None,
        "last_import_by_profile": {
            row["profile"]: row.get("last_import_at") for row in latest_by_profile
        },
    }


@app.get("/api/v1/imports/history", dependencies=[Depends(require_admin)])
def import_history(
    service: Annotated[GuardianService, Depends(service_from_request)],
) -> list[dict]:
    return service.import_history()


@app.post("/api/v1/imports/detect", dependencies=[Depends(require_import_api)])
async def detect_import_columns(
    service: Annotated[GuardianService, Depends(service_from_request)],
    file: Annotated[UploadFile, File()],
    profile: Annotated[str, Form()],
) -> dict:
    payload = await file.read(service.settings.voc_max_import_bytes + 1)
    if len(payload) > service.settings.voc_max_import_bytes:
        raise HTTPException(status_code=413, detail="Import exceeds the configured size limit")
    try:
        return await asyncio.to_thread(
            service.detect_import_mapping,
            filename=file.filename or "upload",
            content=payload,
            profile=profile,
        )
    except (KeyError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/v1/imports/preview", dependencies=[Depends(require_import_api)])
async def preview_import(
    service: Annotated[GuardianService, Depends(service_from_request)],
    file: Annotated[UploadFile, File()],
    profile: Annotated[str, Form()] = "generic",
    vietnamese_only: Annotated[bool, Form()] = True,
    mapping: Annotated[str | None, Form()] = None,
) -> dict:
    payload = await file.read(service.settings.voc_max_import_bytes + 1)
    if len(payload) > service.settings.voc_max_import_bytes:
        raise HTTPException(status_code=413, detail="Import exceeds the configured size limit")
    try:
        return await asyncio.to_thread(
            service.preview_import,
            filename=file.filename or "upload",
            content=payload,
            profile=profile,
            vietnamese_only=vietnamese_only,
            mapping=_mapping_json(mapping),
        )
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post(
    "/api/v1/imports",
    response_model=RunResponse,
    status_code=202,
    dependencies=[Depends(require_import_api)],
)
async def commit_import(
    background_tasks: BackgroundTasks,
    service: Annotated[GuardianService, Depends(service_from_request)],
    file: Annotated[UploadFile, File()],
    profile: Annotated[str, Form()] = "generic",
    vietnamese_only: Annotated[bool, Form()] = True,
    mapping: Annotated[str | None, Form()] = None,
) -> RunResponse:
    payload = await file.read(service.settings.voc_max_import_bytes + 1)
    if len(payload) > service.settings.voc_max_import_bytes:
        raise HTTPException(status_code=413, detail="Import exceeds the configured size limit")
    try:
        filename = file.filename or "upload"
        parsed_mapping = _mapping_json(mapping)
        queued = await asyncio.to_thread(
            service.queue_import_bytes,
            filename=filename,
            content=payload,
            profile=profile,
            vietnamese_only=vietnamese_only,
            mapping=parsed_mapping,
        )
        background_tasks.add_task(
            service.execute_queued_import,
            pipeline_run_id=queued.pipeline_run_id,
            filename=filename,
            content=payload,
            profile=profile,
            vietnamese_only=vietnamese_only,
            mapping=parsed_mapping,
        )
        return queued
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/v1/crawls", response_model=RunResponse, dependencies=[Depends(require_admin)])
def start_crawl(
    service: Annotated[GuardianService, Depends(service_from_request)],
    keyword: str = Form(default="guardian vietnam", max_length=500),
) -> RunResponse:
    return service.crawl(keyword=keyword)


@app.post(
    "/api/v1/live-collections",
    response_model=RunResponse,
    dependencies=[Depends(require_admin)],
)
def start_live_collection(
    payload: LiveCollectionRequest,
    service: Annotated[GuardianService, Depends(service_from_request)],
) -> RunResponse:
    """Run one bounded, auditable SERP → TinyFish → OpenAI collection."""

    return service.run_live_collection(
        source_ids=payload.source_ids,
        pages_per_query=payload.pages_per_query,
        fetch_limit=payload.fetch_limit,
        extraction_limit=payload.extraction_limit,
        lookback_days=payload.lookback_days,
        refresh=payload.refresh,
    )


@app.post("/api/v1/pipeline/run", response_model=RunResponse, dependencies=[Depends(require_admin)])
def pipeline_run(service: Annotated[GuardianService, Depends(service_from_request)]) -> RunResponse:
    return service.run_all()


@app.get("/api/v1/runs/latest", response_model=RunResponse)
def latest_run(
    service: Annotated[GuardianService, Depends(service_from_request)],
) -> RunResponse:
    value = _latest_run(service)
    if value is None:
        raise HTTPException(status_code=404, detail="No pipeline run has completed yet")
    return value


@app.get("/api/v1/runs/{run_id}", response_model=RunResponse)
def get_run(
    run_id: str,
    service: Annotated[GuardianService, Depends(service_from_request)],
) -> RunResponse:
    value = service.get_run(run_id)
    if value is None:
        raise HTTPException(status_code=404, detail="Pipeline run not found")
    return value


@app.get("/api", include_in_schema=False)
@app.get("/api/{full_path:path}", include_in_schema=False)
def unknown_api_route(full_path: str = "") -> None:
    """Keep API failures JSON even when the frontend bundle is absent."""

    raise HTTPException(status_code=404, detail="API route not found")


WEB_DIST = Path(__file__).resolve().parents[2] / "web" / "dist"
if WEB_DIST.is_dir():
    assets = WEB_DIST / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="web-assets")

    @app.get("/{full_path:path}", response_class=FileResponse, include_in_schema=False)
    def web_application(full_path: str):
        requested = (WEB_DIST / full_path).resolve()
        if (
            full_path
            and WEB_DIST.resolve() in requested.parents
            and requested.is_file()
        ):
            return FileResponse(requested)
        return FileResponse(WEB_DIST / "index.html")
else:
    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def placeholder() -> str:
        return """<!doctype html><meta charset='utf-8'><title>Guardian Signal</title>
        <main style='font:16px system-ui;max-width:48rem;margin:10vh auto;padding:2rem'>
        <h1>Guardian Signal API is ready</h1><p>Build <code>web/</code> to serve the executive experience.</p></main>"""


__all__ = ["app", "require_admin"]
