from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone

from social_crawler.config import SUPPORTED_PLATFORMS, Settings


def _add_common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "-k",
        "--keyword",
        action="append",
        help="Keyword to crawl. Repeat for multiple keywords.",
    )
    parser.add_argument(
        "-p",
        "--platform",
        action="append",
        choices=SUPPORTED_PLATFORMS,
        help="Platform to crawl. Repeat as needed; default: all.",
    )
    parser.add_argument(
        "--days",
        type=int,
        help="Calendar-date search window; default: CRAWLER_LOOKBACK_DAYS or 1.",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="social-crawler",
        description="Standalone CyPeace social-listening crawler.",
    )
    parser.add_argument("--log-level", default="INFO", choices=("DEBUG", "INFO", "WARNING", "ERROR"))
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan_parser = subparsers.add_parser("plan", help="Print requests without calling SerpAPI.")
    _add_common_arguments(plan_parser)

    crawl_parser = subparsers.add_parser("crawl", help="Run the crawler.")
    _add_common_arguments(crawl_parser)
    crawl_parser.add_argument("-o", "--output", help="Output .json/.jsonl path, or - for stdout.")
    crawl_parser.add_argument("--format", choices=("json", "jsonl"), help="Override output format.")
    crawl_parser.add_argument(
        "--browser",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Enable Chromium fallback scraping.",
    )
    crawl_parser.add_argument(
        "--serp-cache",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Allow SerpAPI cached responses.",
    )
    return parser


def _resolved_inputs(args: argparse.Namespace, settings: Settings) -> tuple[list[str], list[str], int]:
    keywords = args.keyword or list(settings.keywords)
    platforms = args.platform or list(settings.platforms)
    days = args.days if args.days is not None else settings.lookback_days
    if not keywords:
        raise ValueError("Add --keyword or set CRAWLER_KEYWORDS in .env")
    if days <= 0:
        raise ValueError("--days must be greater than zero")
    if settings.search_concurrency <= 0:
        raise ValueError("CRAWLER_SEARCH_CONCURRENCY must be greater than zero")
    return keywords, platforms, days


def _set_browser_override(enabled: bool | None) -> None:
    if enabled is not None:
        os.environ["SOCIAL_SCRAPER_BROWSER_ENABLED"] = "true" if enabled else "false"


def _run_plan(keywords: list[str], platforms: list[str], days: int) -> int:
    from social_crawler.engine import build_crawl_plan

    bucket_end = datetime.now(timezone.utc)
    bucket_start = bucket_end - timedelta(days=days)
    plans = build_crawl_plan(
        keywords,
        platforms,
        bucket_start=bucket_start,
        bucket_end=bucket_end,
    )
    print(
        json.dumps(
            {
                "bucket_start": bucket_start.isoformat(),
                "bucket_end": bucket_end.isoformat(),
                "requests": [plan.as_dict() for plan in plans],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


async def _run_crawl(
    args: argparse.Namespace,
    settings: Settings,
    keywords: list[str],
    platforms: list[str],
    days: int,
) -> int:
    from social_crawler.engine import crawl
    from social_crawler.output import infer_output_format, partial_output_path, write_result

    if not settings.serp_api_key or settings.serp_api_key.lower().startswith("your_"):
        raise ValueError("Set SERP_API_KEY in .env before crawling")

    output_path = args.output or settings.output_path
    output_format = infer_output_format(output_path, args.format)
    no_cache = settings.no_cache if args.serp_cache is None else not args.serp_cache
    result = await crawl(
        api_key=settings.serp_api_key,
        api_base_url=settings.serp_api_base_url,
        keywords=keywords,
        platforms=platforms,
        lookback_hours=days * 24,
        no_cache=no_cache,
        use_browser=os.environ.get("SOCIAL_SCRAPER_BROWSER_ENABLED", "false").lower() == "true",
        search_concurrency=settings.search_concurrency,
    )
    actual_output_path = partial_output_path(output_path) if result.errors else output_path
    write_result(result, actual_output_path, output_format)
    print(
        f"Crawled {len(result.keywords)} keyword(s): "
        f"{len(result.mentions)} mention(s), {len(result.errors)} request error(s). "
        f"Output: {actual_output_path}",
        file=sys.stderr,
    )
    return 1 if result.errors else 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    )
    try:
        settings = Settings.from_env()
        keywords, platforms, days = _resolved_inputs(args, settings)
        if args.command == "plan":
            return _run_plan(keywords, platforms, days)
        _set_browser_override(args.browser)
        return asyncio.run(
            _run_crawl(args, settings, keywords, platforms, days)
        )
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    return 2
