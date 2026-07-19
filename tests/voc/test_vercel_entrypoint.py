from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


COLLECTION_SWITCHES = (
    "VOC_WRITE_API_ENABLED",
    "VOC_SCHEDULER_ENABLED",
    "VOC_SCHEDULER_CRAWL_ENABLED",
    "VOC_SCHEDULER_FULL_FLOW_ENABLED",
    "VOC_COLLECTOR_ENRICHMENT_ENABLED",
    "VOC_LIVE_COLLECTION_REFRESH",
    "TINYFISH_ENABLED",
)


def test_vercel_entrypoint_hard_disables_collection() -> None:
    environment = os.environ.copy()
    for name in COLLECTION_SWITCHES:
        environment[name] = "true"
    environment.pop("VOC_IMPORT_API_ENABLED", None)
    environment["AI_PROVIDER"] = "openai_compatible"

    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import os; import api.index; from guardian_voc.api.main import settings; "
            "print(' '.join("
            f"[os.environ[name] for name in {COLLECTION_SWITCHES!r}]))"
            "; print(os.environ['AI_PROVIDER'])"
            "; print(os.environ['VOC_IMPORT_API_ENABLED'])"
            "; print(settings.review_imports_enabled)",
        ],
        cwd=root,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    values, provider, import_environment, imports_enabled = (
        result.stdout.strip().splitlines()
    )

    assert values.split() == ["false"] * len(COLLECTION_SWITCHES)
    assert provider == "cached"
    assert import_environment == "true"
    assert imports_enabled == "True"


def test_vercel_entrypoint_respects_explicit_import_disable() -> None:
    environment = os.environ.copy()
    environment["VOC_IMPORT_API_ENABLED"] = "false"

    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import api.index; from guardian_voc.api.main import settings; "
            "print(settings.review_imports_enabled)",
        ],
        cwd=root,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.strip() == "False"
