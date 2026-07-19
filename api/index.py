"""Vercel serverless entrypoint for the Guardian Palm application."""

from __future__ import annotations

import os


# Serverless instances have only ephemeral local storage. Application records
# use the Neon DATABASE_URL injected by the Vercel integration; these paths are
# reserved for temporary uploads and a harmless local fallback during builds.
os.environ.setdefault("VOC_DB_PATH", "/tmp/guardian-palm/guardian.duckdb")
os.environ.setdefault("VOC_DATA_DIR", "/tmp/guardian-palm")
os.environ.setdefault("VOC_INBOX_DIR", "/tmp/guardian-palm/inbox")
# PostgreSQL makes review uploads durable in the serverless deployment. Keep
# this independently configurable so enabling imports does not open admin-only
# writes or restart background collection.
os.environ.setdefault("VOC_IMPORT_API_ENABLED", "true")
# These are deliberate production safety controls, not defaults. Project-level
# environment variables must not be able to restart collection or paid AI work
# in a serverless instance.
os.environ.update(
    {
        "VOC_DEMO_MODE": "false",
        "VOC_PROCESS_EXISTING_ON_STARTUP": "false",
        "VOC_WRITE_API_ENABLED": "false",
        "VOC_SCHEDULER_ENABLED": "false",
        "VOC_SCHEDULER_CRAWL_ENABLED": "false",
        "VOC_SCHEDULER_FULL_FLOW_ENABLED": "false",
        "VOC_COLLECTOR_ENRICHMENT_ENABLED": "false",
        "VOC_LIVE_COLLECTION_REFRESH": "false",
        "TINYFISH_ENABLED": "false",
        "AI_PROVIDER": "cached",
    }
)
os.environ.setdefault("VOC_CORS_ORIGINS", "https://guardian-palm.vercel.app")

from guardian_voc.api.main import app  # noqa: E402


__all__ = ["app"]
