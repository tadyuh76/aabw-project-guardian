"""Opt-in paid-provider smoke test.

Run only with explicitly configured ``AI_BASE_URL``, ``AI_API_KEY``, and
``AI_MODEL``::

    python -m guardian_voc.ai.live_smoke --confirm-live

The command sends one synthetic, already-redacted item and prints only the
validated application schema. It is never invoked by CI or demo startup.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
from collections.abc import Sequence

from guardian_voc.ai.openai_compatible import OpenAICompatibleProvider
from guardian_voc.schemas.analysis import (
    Brand,
    ClassificationRequest,
    SourceGroup,
    TrustedSourceMetadata,
    Visibility,
)


async def _run() -> None:
    text = "Guardian voucher failed at checkout in this synthetic live smoke test."
    request = ClassificationRequest(
        content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        text_redacted=text,
        trusted_metadata=TrustedSourceMetadata(
            source_group=SourceGroup.MARKETPLACE,
            source_platform="synthetic_smoke",
            visibility=Visibility.PUBLIC,
            source_fixed_brand=Brand.GUARDIAN,
            language="en",
        ),
        brand_candidates=(Brand.GUARDIAN,),
    )
    async with OpenAICompatibleProvider.from_env() as provider:
        result = await provider.classify(request)
    print(result.model_dump_json(indent=2))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one opt-in live AI classification")
    parser.add_argument(
        "--confirm-live",
        action="store_true",
        help="acknowledge that this may call a paid external model",
    )
    args = parser.parse_args(argv)
    if not args.confirm_live:
        parser.error("--confirm-live is required; CI and the offline demo must not call live AI")
    asyncio.run(_run())
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised manually with credentials
    raise SystemExit(main())
