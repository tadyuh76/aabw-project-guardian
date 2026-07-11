from __future__ import annotations

import json
import sys
from pathlib import Path

from social_crawler.engine import CrawlResult


def serialize_result(result: CrawlResult, output_format: str) -> str:
    if output_format == "json":
        return json.dumps(result.as_dict(), ensure_ascii=False, indent=2) + "\n"
    if output_format == "jsonl":
        return "".join(
            json.dumps(mention.as_dict(), ensure_ascii=False) + "\n"
            for mention in result.mentions
        )
    raise ValueError(f"Unsupported output format: {output_format}")


def infer_output_format(path: str, requested: str | None = None) -> str:
    if requested:
        return requested
    return "jsonl" if path.lower().endswith(".jsonl") else "json"


def partial_output_path(path: str) -> str:
    return path if path == "-" else path + ".partial"


def write_result(result: CrawlResult, path: str, output_format: str) -> None:
    content = serialize_result(result, output_format)
    if path == "-":
        sys.stdout.write(content)
        return

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(target)
