from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).parents[2]


def test_demo_up_resets_the_persistent_volume_before_starting() -> None:
    """Every demo launch must begin from the deterministic seed dataset."""

    script = (ROOT / "scripts/demo-up").read_text(encoding="utf-8")
    reset_enabled_by_default = re.search(
        r'if\s+\[\[\s+"\$\{VOC_DEMO_RESET:-true\}"\s+==\s+"true"\s+\]\];\s+then',
        script,
    )
    volume_reset = re.search(
        r'^\s*"\$\{COMPOSE\[@\]\}"\s+down\s+[^\n]*(?:--volumes|-v)(?:\s|$)',
        script,
        flags=re.MULTILINE,
    )
    startup = re.search(
        r'^\s*"\$\{COMPOSE\[@\]\}"\s+up\s+',
        script,
        flags=re.MULTILINE,
    )

    assert reset_enabled_by_default is not None, (
        "scripts/demo-up must reset persisted demo state unless the operator "
        "explicitly opts out"
    )
    assert volume_reset is not None, (
        "scripts/demo-up must remove the named data volume so a previous "
        "demo increment cannot leak into the next launch"
    )
    assert startup is not None
    assert reset_enabled_by_default.start() < volume_reset.start() < startup.start()
