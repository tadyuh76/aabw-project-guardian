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
    environment["AI_PROVIDER"] = "openai_compatible"

    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import os; import api.index; print(' '.join("
            f"[os.environ[name] for name in {COLLECTION_SWITCHES!r}]))"
            "; print(os.environ['AI_PROVIDER'])",
        ],
        cwd=root,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    values, provider = result.stdout.strip().splitlines()

    assert values.split() == ["false"] * len(COLLECTION_SWITCHES)
    assert provider == "cached"
