"""Application configuration with safe, offline-first defaults.

Secrets are intentionally optional at configuration load time.  The adapters
that need them fail closed when invoked, which keeps imports, migrations, and
the deterministic demo usable without external credentials.
"""

from __future__ import annotations

from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """Guardian Signal settings loaded from environment variables or ``.env``."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        hide_input_in_errors=True,
    )

    database_url: str = Field(
        default="",
        validation_alias=AliasChoices("database_url", "DATABASE_URL"),
        repr=False,
        exclude=True,
    )
    voc_db_path: Path = Path("data/guardian_voc.duckdb")
    voc_data_dir: Path = Path("data")
    voc_inbox_dir: Path = Path("data/inbox")
    voc_demo_mode: bool = True
    voc_process_existing_on_startup: bool = True
    voc_demo_as_of: datetime | None = datetime.fromisoformat(
        "2026-07-11T23:59:59+07:00"
    )
    voc_business_timezone: str = "Asia/Ho_Chi_Minh"
    voc_allow_inferred_dates: bool = False
    # Review uploads can be enabled without opening the admin-only write APIs.
    # When unset, preserve the original single-switch behavior for self-hosted
    # deployments.
    voc_import_api_enabled: bool | None = None
    voc_write_api_enabled: bool = False
    voc_admin_token: str = Field(default="", repr=False, exclude=True)
    voc_admin_token_file: Path | None = None
    voc_hash_salt: str = Field(default="", repr=False, exclude=True)
    voc_current_window_days: int = Field(default=7, ge=1, le=90)
    voc_baseline_window_days: int = Field(default=28, ge=7, le=365)
    voc_alert_min_support: int = Field(default=8, ge=1)
    voc_alert_min_excess: int = Field(default=5, ge=0)
    voc_alert_min_growth: float = Field(default=1.8, ge=1)
    voc_alert_min_rate_delta: float = Field(default=0.05, ge=0, le=1)
    voc_classifier_min_confidence: float = Field(default=0.70, ge=0, le=1)
    voc_competitor_min_sample: int = Field(default=10, ge=1)
    voc_default_locale: Literal["en", "vi"] = "en"
    voc_cors_origins: Annotated[tuple[str, ...], NoDecode] = ("http://localhost:5173",)
    voc_log_level: str = "INFO"
    voc_preview_text_limit: int = Field(default=240, ge=40, le=2_000)
    voc_max_import_bytes: int = Field(default=25 * 1024 * 1024, ge=1_024)
    voc_max_import_rows: int = Field(default=100_000, ge=1)
    voc_repost_min_chars: int = Field(default=40, ge=20, le=500)
    voc_source_stale_hours: int = Field(default=48, ge=1)
    voc_scheduler_enabled: bool = False
    voc_scheduler_crawl_enabled: bool = False
    # The strict scheduled path runs SerpAPI discovery, TinyFish page reading,
    # OpenAI page extraction/classification, deduplication, and publication on
    # the service's single DuckDB writer. It is separate from the preserved
    # generic crawler path above.
    voc_scheduler_full_flow_enabled: bool = False
    voc_scheduler_interval_seconds: int = Field(default=1_800, ge=1, le=86_400)
    voc_scheduler_initial_delay_seconds: int = Field(default=15, ge=0, le=3_600)
    voc_scheduler_max_backoff_seconds: int = Field(default=14_400, ge=1, le=604_800)
    voc_scheduler_shutdown_timeout_seconds: float = Field(default=15, ge=1, le=300)
    voc_collector_files: Annotated[tuple[Path, ...], NoDecode] = ()
    # This separate allowlist is the only filesystem trust boundary for the
    # PII-redacted strict feedback export. Generic collector files remain
    # discovery-only unless page content has explicit reader provenance.
    voc_verified_feedback_files: Annotated[tuple[Path, ...], NoDecode] = ()
    voc_collector_checkpoint_path: Path | None = None
    # Mounted search results remain discovery-only unless this explicitly
    # enabled live-mode enrichment obtains the underlying public page.
    voc_collector_enrichment_enabled: bool = False
    voc_collector_enrichment_max_rows: int = Field(default=25, ge=1, le=500)
    voc_collector_enrichment_concurrency: int = Field(default=3, ge=1, le=25)
    voc_live_collection_source_ids: Annotated[tuple[str, ...], NoDecode] = (
        "guardian_public_social",
        "hasaki_public_social",
        "watsons_public_social",
    )
    voc_live_collection_pages_per_query: int = Field(default=1, ge=1, le=10)
    voc_live_collection_fetch_limit: int = Field(default=25, ge=1, le=500)
    voc_live_collection_extraction_limit: int = Field(default=25, ge=1, le=500)
    # Two calendar days avoids a midnight boundary gap. Stable source and
    # content identities make the overlap idempotent.
    voc_live_collection_lookback_days: int = Field(default=2, ge=1, le=365)
    voc_live_collection_refresh: bool = False

    ai_provider: Literal["cached", "openai_compatible"] = "cached"
    ai_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("ai_api_key", "AI_API_KEY", "OPENAI_API_KEY"),
        repr=False,
        exclude=True,
    )
    ai_api_key_file: Path | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "ai_api_key_file", "AI_API_KEY_FILE", "OPENAI_API_KEY_FILE"
        ),
    )
    ai_base_url: str = "https://api.openai.com/v1"
    ai_model: str = "gpt-5.4-mini"
    ai_batch_size: int = Field(default=20, ge=1, le=500)
    ai_request_timeout_seconds: float = Field(default=30, gt=0, le=300)

    serp_api_key: str = Field(default="", repr=False, exclude=True)
    serp_api_key_file: Path | None = None
    serp_api_base_url: str = "https://serpapi.com"
    crawler_keywords: Annotated[tuple[str, ...], NoDecode] = (
        "guardian vietnam",
        "hasaki vietnam",
        "watsons vietnam",
    )
    crawler_platforms: Annotated[tuple[str, ...], NoDecode] = (
        "facebook",
        "tiktok",
        "youtube",
        "reddit",
        "threads",
    )
    crawler_lookback_days: int = Field(default=1, ge=1, le=365)

    tinyfish_enabled: bool = False
    tinyfish_api_key: str = Field(
        default="",
        validation_alias=AliasChoices(
            "tinyfish_api_key", "TINYFISH_API_KEY", "TINY_FISH_API_KEY"
        ),
        repr=False,
        exclude=True,
    )
    tinyfish_api_key_file: Path | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "tinyfish_api_key_file", "TINYFISH_API_KEY_FILE", "TINY_FISH_API_KEY_FILE"
        ),
    )
    tinyfish_search_base_url: str = "https://api.search.tinyfish.ai"
    tinyfish_fetch_base_url: str = "https://api.fetch.tinyfish.ai"
    tinyfish_timeout_seconds: float = Field(default=150, gt=0, le=300)
    tinyfish_useful_text_chars: int = Field(default=80, ge=30, le=10_000)
    tinyfish_location: str = Field(default="VN", min_length=2, max_length=64)
    tinyfish_language: str = Field(default="vi", min_length=2, max_length=16)

    @field_validator(
        "crawler_keywords",
        "crawler_platforms",
        "voc_cors_origins",
        "voc_collector_files",
        "voc_verified_feedback_files",
        "voc_live_collection_source_ids",
        mode="before",
    )
    @classmethod
    def _parse_csv_tuple(cls, value: object) -> object:
        if isinstance(value, str):
            return tuple(part.strip() for part in value.split(",") if part.strip())
        return value

    @field_validator("voc_business_timezone")
    @classmethod
    def _validate_timezone(cls, value: str) -> str:
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"unknown IANA timezone: {value}") from exc
        return value

    @field_validator(
        "voc_admin_token",
        "voc_hash_salt",
        "database_url",
        "ai_api_key",
        "serp_api_key",
        "tinyfish_api_key",
    )
    @classmethod
    def _strip_secrets(cls, value: str) -> str:
        return value.strip()

    @field_validator("tinyfish_location", "tinyfish_language")
    @classmethod
    def _strip_tinyfish_locale(cls, value: str) -> str:
        return value.strip()

    @field_validator("tinyfish_search_base_url", "tinyfish_fetch_base_url")
    @classmethod
    def _validate_tinyfish_endpoint(cls, value: str) -> str:
        raw = value.strip()
        try:
            parsed = urlsplit(raw)
            _ = parsed.port
        except (TypeError, ValueError) as exc:
            raise ValueError("TinyFish base URLs must be valid HTTPS endpoints") from exc
        if (
            parsed.scheme.lower() != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(
                "TinyFish base URLs must use HTTPS without credentials, query, or fragment"
            )
        return raw.rstrip("/")

    @model_validator(mode="after")
    def _resolve_secret_files(self) -> "Settings":
        """Load mounted secrets without requiring credentials in container env."""

        if not self.voc_admin_token:
            self.voc_admin_token = self._read_secret(self.voc_admin_token_file)
        if not self.ai_api_key:
            self.ai_api_key = self._read_secret(self.ai_api_key_file)
        if not self.serp_api_key:
            self.serp_api_key = self._read_secret(self.serp_api_key_file)
        return self

    @model_validator(mode="after")
    def _validate_write_configuration(self) -> "Settings":
        if self.voc_write_api_enabled and not self.voc_admin_token:
            raise ValueError(
                "VOC_ADMIN_TOKEN or a non-empty VOC_ADMIN_TOKEN_FILE is required "
                "when VOC_WRITE_API_ENABLED is true"
            )
        return self

    @model_validator(mode="after")
    def _validate_tinyfish_configuration(self) -> "Settings":
        if self.tinyfish_enabled and not self.tinyfish_resolved_api_key:
            raise ValueError(
                "TINYFISH_API_KEY or a non-empty TINYFISH_API_KEY_FILE is required "
                "when TINYFISH_ENABLED is true"
            )
        return self

    @model_validator(mode="after")
    def _validate_live_scheduler_configuration(self) -> "Settings":
        if not self.voc_scheduler_enabled:
            return self
        if self.voc_demo_mode:
            raise ValueError("VOC_SCHEDULER_ENABLED cannot be used in demo mode")
        if self.ai_provider != "openai_compatible":
            raise ValueError(
                "AI_PROVIDER=openai_compatible is required for scheduled live publishing"
            )
        if not self.ai_api_key:
            raise ValueError(
                "OPENAI_API_KEY, AI_API_KEY, or a mounted AI_API_KEY_FILE is required"
            )
        if self.voc_scheduler_crawl_enabled and not (
            self.tinyfish_enabled or self.serp_api_key
        ):
            raise ValueError(
                "TinyFish or SerpAPI credentials are required when scheduled crawling is enabled"
            )
        if self.voc_scheduler_full_flow_enabled:
            if not self.serp_api_key:
                raise ValueError(
                    "SERP_API_KEY or a non-empty SERP_API_KEY_FILE is required "
                    "when VOC_SCHEDULER_FULL_FLOW_ENABLED is true"
                )
            if not self.tinyfish_enabled or not self.tinyfish_resolved_api_key:
                raise ValueError(
                    "TinyFish must be enabled with a mounted key when "
                    "VOC_SCHEDULER_FULL_FLOW_ENABLED is true"
                )
        return self

    @model_validator(mode="after")
    def _validate_collector_enrichment_configuration(self) -> "Settings":
        if not self.voc_collector_enrichment_enabled:
            return self
        if self.voc_demo_mode:
            raise ValueError(
                "VOC_COLLECTOR_ENRICHMENT_ENABLED cannot be used in demo mode"
            )
        if not self.tinyfish_enabled or not self.tinyfish_resolved_api_key:
            raise ValueError(
                "TinyFish must be enabled with a mounted key for collector enrichment"
            )
        return self

    # Short aliases make the settings pleasant to consume without losing the
    # one-to-one relationship between fields and documented environment names.
    @property
    def db_path(self) -> Path:
        return self.voc_db_path

    @property
    def data_dir(self) -> Path:
        return self.voc_data_dir

    @property
    def inbox_dir(self) -> Path:
        return self.voc_inbox_dir

    @property
    def business_timezone(self) -> str:
        return self.voc_business_timezone

    @property
    def demo_as_of(self) -> datetime | None:
        return self.voc_demo_as_of

    @property
    def review_imports_enabled(self) -> bool:
        if self.voc_import_api_enabled is not None:
            return self.voc_import_api_enabled
        return self.voc_write_api_enabled

    @property
    def tinyfish_resolved_api_key(self) -> str:
        """Resolve the key from an environment value or a mounted secret file."""

        if self.tinyfish_api_key:
            return self.tinyfish_api_key
        return self._read_secret(self.tinyfish_api_key_file)

    @staticmethod
    def _read_secret(path: Path | None) -> str:
        if path is None:
            return ""
        try:
            if path.stat().st_size > 16_384:
                return ""
            return path.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError):
            return ""


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide immutable-by-convention settings object."""

    return Settings()


def clear_settings_cache() -> None:
    """Test helper for re-reading environment configuration."""

    get_settings.cache_clear()


__all__ = ["Settings", "clear_settings_cache", "get_settings"]
