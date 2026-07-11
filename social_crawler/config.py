from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


load_dotenv()

SOCIAL_PLATFORMS: dict[str, list[str]] = {
    "facebook": ["facebook.com"],
    "twitter": ["x.com", "twitter.com"],
    "instagram": ["instagram.com"],
    "youtube": ["youtube.com"],
    "tiktok": ["tiktok.com"],
    "linkedin": ["linkedin.com"],
    "reddit": ["reddit.com"],
    "threads": ["threads.net"],
}

TELEGRAM_DOMAINS: list[str] = [
    "t.me",
    "telegram.org",
    "telegram.me",
    "tgstat.com",
    "telemetr.io",
    "telemetryapp.io",
    "tgstat.ru",
    "telemetr.me",
    "telegra.ph",
    "storebot.me",
    "tlgrm.eu",
    "telegramchannels.me",
    "telegram-group.com",
]

VIETNAM_PLATFORMS: dict[str, list[str]] = {
    "zalo": ["zalo.me", "zaloapp.com"],
    "lotus": ["lotus.vn"],
}

SUPPORTED_PLATFORMS = (
    "all",
    *SOCIAL_PLATFORMS.keys(),
    "telegram",
    *VIETNAM_PLATFORMS.keys(),
    "vietnam",
)


def _csv(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


@dataclass(frozen=True)
class Settings:
    serp_api_key: str
    serp_api_base_url: str
    keywords: tuple[str, ...]
    platforms: tuple[str, ...]
    lookback_days: int
    output_path: str
    no_cache: bool
    search_concurrency: int

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            serp_api_key=os.environ.get("SERP_API_KEY", "").strip(),
            serp_api_base_url=os.environ.get("SERP_API_BASE_URL", "https://serpapi.com").rstrip("/"),
            keywords=_csv(os.environ.get("CRAWLER_KEYWORDS")),
            platforms=_csv(os.environ.get("CRAWLER_PLATFORMS")) or ("all",),
            lookback_days=int(os.environ.get("CRAWLER_LOOKBACK_DAYS", "1")),
            output_path=os.environ.get("CRAWLER_OUTPUT_PATH", "data/mentions.json").strip(),
            no_cache=_env_bool("CRAWLER_SERP_NO_CACHE", True),
            search_concurrency=int(os.environ.get("CRAWLER_SEARCH_CONCURRENCY", "4")),
        )


def _unique(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


def resolve_platform_domains(platforms: tuple[str, ...] | list[str]) -> tuple[list[str], list[str]]:
    """Return (timed domains, untimed domains) for the requested platforms."""
    normalized = [item.strip().lower() for item in platforms if item.strip()]
    if not normalized or "all" in normalized:
        timed = [domain for domains in SOCIAL_PLATFORMS.values() for domain in domains]
        untimed = [
            *TELEGRAM_DOMAINS,
            *(domain for domains in VIETNAM_PLATFORMS.values() for domain in domains),
        ]
        return _unique(timed), _unique(untimed)

    unknown = sorted(set(normalized) - set(SUPPORTED_PLATFORMS))
    if unknown:
        raise ValueError(f"Unsupported platform: {', '.join(unknown)}")

    timed: list[str] = []
    untimed: list[str] = []
    for platform in normalized:
        if platform in SOCIAL_PLATFORMS:
            timed.extend(SOCIAL_PLATFORMS[platform])
        elif platform == "telegram":
            untimed.extend(TELEGRAM_DOMAINS)
        elif platform == "vietnam":
            for domains in VIETNAM_PLATFORMS.values():
                untimed.extend(domains)
        elif platform in VIETNAM_PLATFORMS:
            untimed.extend(VIETNAM_PLATFORMS[platform])
    return _unique(timed), _unique(untimed)
