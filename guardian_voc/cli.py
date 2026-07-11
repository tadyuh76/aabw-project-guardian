"""Command-line interface for local operations and the deterministic demo."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from datetime import date
from pathlib import Path


def _service():
    from guardian_voc.application import GuardianService
    from guardian_voc.config import get_settings

    return GuardianService(get_settings())


def _print(value: object) -> None:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def _init_db(_: argparse.Namespace) -> int:
    service = _service()
    service.initialize(seed_demo=False)
    _print({"status": "ok", "database": str(service.settings.db_path)})
    return 0


def _seed_demo(args: argparse.Namespace) -> int:
    result = _service().seed_demo(reset=args.reset)
    _print(result)
    return 0


def _import_file(args: argparse.Namespace) -> int:
    result = _service().import_file(
        Path(args.path),
        profile=args.profile,
        vietnamese_only=args.vietnamese_only,
        period_start=args.period_start,
        period_end=args.period_end,
    )
    _print(result)
    return 0 if result.status in {"completed", "partial"} else 1


def _crawl(args: argparse.Namespace) -> int:
    result = _service().crawl(keyword=args.keyword)
    _print(result)
    return 0 if result.status in {"completed", "partial"} else 1


def _iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected an ISO date (YYYY-MM-DD)") from exc


def _prefetch_data(args: argparse.Namespace) -> int:
    from guardian_voc.application import GuardianService
    from guardian_voc.config import get_settings
    from guardian_voc.data_layer import LiveDataLayer

    settings = get_settings()
    if not args.skip_classification and settings.ai_provider != "openai_compatible":
        print(
            "AI_PROVIDER=openai_compatible is required unless --skip-classification is set",
            file=sys.stderr,
        )
        return 2
    layer = LiveDataLayer(
        settings=settings,
        period_start=args.period_start,
        period_end=args.period_end,
    )
    try:
        manifest = asyncio.run(
            layer.run(
                source_ids=args.sources,
                pages_per_query=args.pages_per_query,
                fetch_limit=args.fetch_limit,
                extraction_limit=args.extraction_limit,
                extract_public=not args.skip_extraction,
                refresh=args.refresh,
                guardian_catalog_path=args.guardian_catalog,
                tinyfish_agent=args.tinyfish_agent,
                tinyfish_agent_limit=args.tinyfish_agent_limit,
                tinyfish_agent_concurrency=args.tinyfish_agent_concurrency,
                discover_enabled=not args.skip_discovery,
                fetch_enabled=not args.skip_fetch,
            )
        )
        stages = dict(manifest.get("stages") or {})
        stages["verified_source_ownership"] = (
            layer.apply_verified_source_ownership()
        )
    except (ValueError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except Exception as exc:
        # Provider exception strings can embed request URLs or opaque upstream
        # payloads. Keep CLI failure output credential-safe.
        print(f"prefetch failed: {type(exc).__name__}", file=sys.stderr)
        return 1
    finally:
        layer.database.close()

    if not args.skip_classification:
        service = GuardianService(settings)
        try:
            stages["classify"] = service.rebuild(stage="analyze")
        finally:
            service.close()
        final_layer = LiveDataLayer(
            settings=settings,
            period_start=args.period_start,
            period_end=args.period_end,
        )
        try:
            manifest = final_layer.build_manifest(stages=stages)
        finally:
            final_layer.database.close()
    _print(manifest)
    return 0


def _data_manifest(args: argparse.Namespace) -> int:
    from guardian_voc.config import get_settings
    from guardian_voc.data_layer import LiveDataLayer

    layer = LiveDataLayer(
        settings=get_settings(),
        period_start=args.period_start,
        period_end=args.period_end,
    )
    try:
        _print(layer.build_manifest())
    finally:
        layer.database.close()
    return 0


_ENV_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


def _required_env(name: str, label: str) -> str:
    if not _ENV_NAME_RE.fullmatch(name):
        raise ValueError(f"invalid environment variable name for {label}")
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(f"{label} is required in environment variable {name}")
    return value


def _integer_option_or_env(
    value: int | None,
    *,
    env_name: str,
    label: str,
) -> int:
    if value is not None:
        result = value
    else:
        raw = _required_env(env_name, label)
        try:
            result = int(raw)
        except ValueError:
            raise ValueError(f"{label} must be a positive integer") from None
    if result <= 0:
        raise ValueError(f"{label} must be a positive integer")
    return result


def _text_option_or_env(
    value: str | None,
    *,
    env_name: str,
    label: str,
) -> str:
    resolved = value.strip() if value is not None else _required_env(env_name, label)
    if not resolved:
        raise ValueError(f"{label} is required")
    return resolved


def _marketplace_exit(result: dict[str, object]) -> int:
    _print(result)
    run = result.get("run")
    status = run.get("status") if isinstance(run, dict) else None
    return 0 if status in {"completed", "partial"} else 1


def _ingest_shopee_reviews(args: argparse.Namespace) -> int:
    try:
        result = _service().ingest_shopee_reviews(
            partner_id=_integer_option_or_env(
                args.partner_id,
                env_name="SHOPEE_PARTNER_ID",
                label="Shopee partner_id",
            ),
            partner_key=_required_env(args.partner_key_env, "Shopee partner_key"),
            access_token=_required_env(
                args.access_token_env, "Shopee access_token"
            ),
            shop_id=_integer_option_or_env(
                args.shop_id,
                env_name="SHOPEE_SHOP_ID",
                label="Shopee shop_id",
            ),
            item_ids=args.item_ids or (),
            discover_all_items=args.all_items,
            owned_shop_authorized=args.owned_shop_authorized,
            page_size=args.page_size,
            max_pages_per_item=args.max_pages_per_item,
            lookback_days=args.lookback_days,
            vietnamese_only=True,
        )
    except (PermissionError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return _marketplace_exit(result)


def _ingest_lazada_reviews(args: argparse.Namespace) -> int:
    try:
        result = _service().ingest_lazada_reviews(
            app_key=_text_option_or_env(
                args.app_key,
                env_name="LAZADA_APP_KEY",
                label="Lazada app_key",
            ),
            app_secret=_required_env(args.app_secret_env, "Lazada app_secret"),
            access_token=_required_env(
                args.access_token_env, "Lazada access_token"
            ),
            item_ids=args.item_ids or (),
            discover_all_items=args.all_items,
            owned_shop_authorized=args.owned_shop_authorized,
            page_size=args.page_size,
            max_pages_per_item=args.max_pages_per_item,
            lookback_days=args.lookback_days,
            vietnamese_only=True,
        )
    except (PermissionError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return _marketplace_exit(result)


def _rebuild(args: argparse.Namespace) -> int:
    result = _service().rebuild(stage=args.command)
    _print(result)
    return 0


def _run_all(_: argparse.Namespace) -> int:
    result = _service().run_all()
    _print(result)
    return 0 if result.status in {"completed", "partial"} else 1


def _serve(args: argparse.Namespace) -> int:
    import uvicorn

    uvicorn.run(
        "guardian_voc.api.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        workers=1,
        log_level=args.log_level.lower(),
    )
    return 0


def _demo_increment(args: argparse.Namespace) -> int:
    import httpx

    root = Path(__file__).resolve().parents[1]
    token_path = root / ".runtime" / "admin-token"
    fixture_path = root / "fixtures" / "demo_increment" / "stock_cancellation.jsonl"
    if not token_path.is_file():
        print("Local demo token not found. Run ./scripts/demo-up first.", file=sys.stderr)
        return 2
    token = token_path.read_text(encoding="utf-8").strip()
    if not token:
        print("Local demo token is empty.", file=sys.stderr)
        return 2

    url = args.api.rstrip("/")
    headers = {"X-Admin-Token": token}
    with fixture_path.open("rb") as handle, httpx.Client(timeout=30) as client:
        response = client.post(
            f"{url}/api/v1/imports",
            headers=headers,
            data={"profile": "generic"},
            files={"file": (fixture_path.name, handle, "application/x-ndjson")},
        )
        response.raise_for_status()
        payload = response.json()
        run_id = payload["pipeline_run_id"]
        print(f"Pipeline run {run_id} accepted; waiting for publication…")
        deadline = time.monotonic() + args.timeout
        while time.monotonic() < deadline:
            run_response = client.get(f"{url}/api/v1/runs/{run_id}")
            run_response.raise_for_status()
            run = run_response.json()
            if run["status"] in {"completed", "partial"}:
                print("The stock-cancellation update is published. Refresh Today.")
                return 0
            if run["status"] == "failed":
                print(run.get("error_summary") or "Pipeline failed.", file=sys.stderr)
                return 1
            time.sleep(0.5)
    print("Timed out waiting for the demo increment.", file=sys.stderr)
    return 1


def _live_smoke(_: argparse.Namespace) -> int:
    result = _service().live_ai_smoke()
    _print(result)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="guardian-voc", description="Guardian Signal operations")
    subparsers = parser.add_subparsers(dest="command", required=True)

    command = subparsers.add_parser("init-db", help="create or migrate the DuckDB store")
    command.set_defaults(func=_init_db)

    command = subparsers.add_parser("seed-demo", help="load deterministic demo fixtures")
    command.add_argument("--reset", action="store_true", help="replace existing local demo data")
    command.set_defaults(func=_seed_demo)

    command = subparsers.add_parser("import-file", help="import one CSV or JSONL file")
    command.add_argument("path")
    command.add_argument("--profile", default="generic")
    command.add_argument(
        "--vietnamese-only",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    command.add_argument("--period-start", type=_iso_date, default=date(2025, 7, 12))
    command.add_argument("--period-end", type=_iso_date, default=date(2026, 7, 11))
    command.set_defaults(func=_import_file)

    command = subparsers.add_parser("crawl", help="collect public feedback with the preserved crawler")
    command.add_argument("--keyword", default="guardian vietnam")
    command.set_defaults(func=_crawl)

    command = subparsers.add_parser(
        "prefetch-data",
        help="run SerpAPI discovery, TinyFish reading, extraction, and classification",
    )
    command.add_argument(
        "--source",
        dest="sources",
        action="append",
        help="registry source ID; repeat to restrict scope (default: all)",
    )
    command.add_argument("--pages-per-query", type=int, default=1)
    command.add_argument("--fetch-limit", type=int)
    command.add_argument("--extraction-limit", type=int)
    command.add_argument(
        "--guardian-catalog",
        help="seed a verified Guardian public catalog checkpoint JSON before fetch",
    )
    command.add_argument(
        "--tinyfish-agent",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="use TinyFish Agent public-UI fallback for Guardian review pages",
    )
    command.add_argument("--tinyfish-agent-limit", type=int)
    command.add_argument("--tinyfish-agent-concurrency", type=int, default=3)
    command.add_argument(
        "--skip-discovery",
        action="store_true",
        help="reuse the persisted SerpAPI discovery snapshot",
    )
    command.add_argument(
        "--skip-fetch",
        action="store_true",
        help="reuse persisted TinyFish page-reader results",
    )
    command.add_argument("--period-start", type=_iso_date, default=date(2025, 7, 12))
    command.add_argument("--period-end", type=_iso_date, default=date(2026, 7, 11))
    command.add_argument("--refresh", action="store_true")
    command.add_argument(
        "--skip-extraction",
        action="store_true",
        help="store fetched pages as enrichment only",
    )
    command.add_argument(
        "--skip-classification",
        action="store_true",
        help="leave newly extracted feedback pending",
    )
    command.set_defaults(func=_prefetch_data)

    command = subparsers.add_parser(
        "data-manifest", help="rebuild and print the live data readiness manifest"
    )
    command.add_argument("--period-start", type=_iso_date, default=date(2025, 7, 12))
    command.add_argument("--period-end", type=_iso_date, default=date(2026, 7, 11))
    command.set_defaults(func=_data_manifest)

    command = subparsers.add_parser(
        "ingest-shopee-reviews",
        help="ingest Guardian-owned Shopee reviews through the seller API",
    )
    item_scope = command.add_mutually_exclusive_group(required=True)
    item_scope.add_argument(
        "--item-id",
        dest="item_ids",
        action="append",
        type=int,
        help="Guardian seller item ID; repeat for each item",
    )
    item_scope.add_argument(
        "--all-items",
        action="store_true",
        help="enumerate every seller item through the authorized product API",
    )
    command.add_argument(
        "--owned-shop-authorized",
        action="store_true",
        required=True,
        help="confirm the seller credentials belong to a Guardian-owned shop",
    )
    command.add_argument("--partner-id", type=int, help="or set SHOPEE_PARTNER_ID")
    command.add_argument("--shop-id", type=int, help="or set SHOPEE_SHOP_ID")
    command.add_argument(
        "--partner-key-env",
        default="SHOPEE_PARTNER_KEY",
        metavar="NAME",
        help="environment variable containing the partner key",
    )
    command.add_argument(
        "--access-token-env",
        default="SHOPEE_ACCESS_TOKEN",
        metavar="NAME",
        help="environment variable containing the seller access token",
    )
    command.add_argument("--page-size", type=int, default=100)
    command.add_argument("--max-pages-per-item", type=int, default=10_000)
    command.add_argument("--lookback-days", type=int, default=365)
    command.set_defaults(func=_ingest_shopee_reviews)

    command = subparsers.add_parser(
        "ingest-lazada-reviews",
        help="ingest Guardian-owned Lazada reviews through the seller API",
    )
    item_scope = command.add_mutually_exclusive_group(required=True)
    item_scope.add_argument(
        "--item-id",
        dest="item_ids",
        action="append",
        type=int,
        help="Guardian seller item ID; repeat for each item",
    )
    item_scope.add_argument(
        "--all-items",
        action="store_true",
        help="enumerate every seller item through the authorized product API",
    )
    command.add_argument(
        "--owned-shop-authorized",
        action="store_true",
        required=True,
        help="confirm the seller credentials belong to a Guardian-owned shop",
    )
    command.add_argument("--app-key", help="or set LAZADA_APP_KEY")
    command.add_argument(
        "--app-secret-env",
        default="LAZADA_APP_SECRET",
        metavar="NAME",
        help="environment variable containing the app secret",
    )
    command.add_argument(
        "--access-token-env",
        default="LAZADA_ACCESS_TOKEN",
        metavar="NAME",
        help="environment variable containing the seller access token",
    )
    command.add_argument("--page-size", type=int, default=100)
    command.add_argument("--max-pages-per-item", type=int, default=10_000)
    command.add_argument("--lookback-days", type=int, default=365)
    command.set_defaults(func=_ingest_lazada_reviews)

    for name in ("analyze", "build-metrics", "build-insights"):
        command = subparsers.add_parser(name)
        command.set_defaults(func=_rebuild)

    command = subparsers.add_parser("run-all", help="run idempotent inbox-to-publish processing")
    command.set_defaults(func=_run_all)

    command = subparsers.add_parser("demo-increment", help="submit and poll the proactive fixture")
    command.add_argument("--api", default="http://127.0.0.1:8000")
    command.add_argument("--timeout", type=float, default=60)
    command.set_defaults(func=_demo_increment)

    command = subparsers.add_parser("live-ai-smoke", help="opt-in one-item live provider check")
    command.set_defaults(func=_live_smoke)

    command = subparsers.add_parser("serve", help="serve the API and built web application")
    command.add_argument("--host", default="127.0.0.1")
    command.add_argument("--port", type=int, default=8000)
    command.add_argument("--reload", action="store_true")
    command.add_argument("--log-level", default="info")
    command.set_defaults(func=_serve)
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    raise SystemExit(args.func(args))


__all__ = ["build_parser", "main"]
