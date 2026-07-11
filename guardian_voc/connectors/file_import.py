"""CSV/JSON/JSONL import with checked mappings and PII-safe previews."""

from __future__ import annotations

import csv
import hashlib
import json
import re
import zipfile
from xml.etree import ElementTree
from collections import OrderedDict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from guardian_voc.config import Settings, get_settings
from guardian_voc.connectors.base import ImportIssue, ImportPreview
from guardian_voc.connectors.mapping_profiles import MappingProfile, get_profile
from guardian_voc.pipeline.language import resolve_language
from guardian_voc.pipeline.normalize import parse_timestamp
from guardian_voc.pipeline.pii import mask_preview_mapping
from guardian_voc.schemas.feedback import (
    Brand,
    IngestionRun,
    OccurredAtQuality,
    RawFeedback,
    SourceGroup,
    Visibility,
)


SUPPORTED_IMPORT_SUFFIXES = {".csv", ".xlsx", ".json", ".jsonl", ".ndjson"}

# Canonical Guardian VOC acquisition window.  Filtering remains opt-in so
# existing generic/customer-service imports retain their prior behavior.
GUARDIAN_VOC_PERIOD_START = date(2025, 7, 12)
GUARDIAN_VOC_PERIOD_END = date(2026, 7, 11)
FilterDate = date | datetime | str | None


@dataclass(frozen=True)
class SourceRow:
    row_number: int
    data: dict[str, Any]
    row_numbers: tuple[int, ...] = ()

    @property
    def all_row_numbers(self) -> tuple[int, ...]:
        return self.row_numbers or (self.row_number,)


@dataclass(frozen=True)
class QuarantinedRow:
    row_number: int
    code: str
    message: str
    field: str | None
    masked_sample: dict[str, Any]
    source_row_numbers: tuple[int, ...] = ()

    def as_issue(self) -> ImportIssue:
        return ImportIssue(
            row_number=self.row_number,
            code=self.code,
            message=self.message,
            field=self.field,
            masked_sample=self.masked_sample,
        )


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_path(path: Path, settings: Settings) -> Path:
    if "\x00" in str(path):
        raise ValueError("filename contains a NUL character")
    path = path.expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    if path.suffix.lower() not in SUPPORTED_IMPORT_SUFFIXES:
        supported = ", ".join(sorted(SUPPORTED_IMPORT_SUFFIXES))
        raise ValueError(f"unsupported import type {path.suffix!r}; expected {supported}")
    size = path.stat().st_size
    if size > settings.voc_max_import_bytes:
        raise ValueError(
            f"import exceeds {settings.voc_max_import_bytes} byte size limit"
        )
    return path


def _object_row(value: object, row_number: int) -> SourceRow:
    if not isinstance(value, Mapping):
        raise ValueError(f"row {row_number} must be a JSON object")
    return SourceRow(row_number, {str(key): item for key, item in value.items()})


def _read_rows(path: Path, settings: Settings) -> list[SourceRow]:
    suffix = path.suffix.lower()
    rows: list[SourceRow] = []
    if suffix == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None:
                return []
            for row_number, row in enumerate(reader, start=2):
                rows.append(
                    SourceRow(
                        row_number,
                        {
                            str(key): value
                            for key, value in row.items()
                            if key is not None
                        },
                    )
                )
                if len(rows) > settings.voc_max_import_rows:
                    raise ValueError(
                        f"import exceeds {settings.voc_max_import_rows} row limit"
                    )
        return rows

    if suffix == ".xlsx":
        return _read_xlsx_rows(path, settings)

    if suffix in {".jsonl", ".ndjson"}:
        with path.open("r", encoding="utf-8-sig") as handle:
            for row_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                except json.JSONDecodeError as exc:
                    # Keep malformed lines as sentinel rows so they can be
                    # quarantined without losing valid neighbors.
                    rows.append(
                        SourceRow(
                            row_number,
                            {"__parse_error__": f"invalid JSON: {exc.msg}"},
                        )
                    )
                else:
                    try:
                        rows.append(_object_row(value, row_number))
                    except ValueError as exc:
                        rows.append(SourceRow(row_number, {"__parse_error__": str(exc)}))
                if len(rows) > settings.voc_max_import_rows:
                    raise ValueError(
                        f"import exceeds {settings.voc_max_import_rows} row limit"
                    )
        return rows

    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON document: {exc.msg}") from exc
    if isinstance(payload, Mapping):
        for key in ("records", "items", "feedback", "mentions"):
            if isinstance(payload.get(key), list):
                payload = payload[key]
                break
        else:
            payload = [payload]
    if not isinstance(payload, list):
        raise ValueError("JSON import must contain an object or a list of objects")
    if len(payload) > settings.voc_max_import_rows:
        raise ValueError(f"import exceeds {settings.voc_max_import_rows} row limit")
    for row_number, item in enumerate(payload, start=1):
        try:
            rows.append(_object_row(item, row_number))
        except ValueError as exc:
            rows.append(SourceRow(row_number, {"__parse_error__": str(exc)}))
    return rows


def _read_xlsx_rows(path: Path, settings: Settings) -> list[SourceRow]:
    """Read the first worksheet of a normal XLSX without executing macros."""

    ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    rel_ns = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
    pkg_ns = "{http://schemas.openxmlformats.org/package/2006/relationships}"
    with zipfile.ZipFile(path) as archive:
        relevant_size = sum(
            item.file_size
            for item in archive.infolist()
            if item.filename.startswith("xl/")
        )
        if relevant_size > settings.voc_max_import_bytes * 6:
            raise ValueError("XLSX expands beyond the configured safe size limit")
        shared: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
            shared = ["".join(node.itertext()) for node in root.findall(f"{ns}si")]

        date_styles: set[int] = set()
        if "xl/styles.xml" in archive.namelist():
            styles = ElementTree.fromstring(archive.read("xl/styles.xml"))
            custom_formats = {
                int(node.attrib["numFmtId"]): node.attrib.get("formatCode", "")
                for node in styles.findall(f"{ns}numFmts/{ns}numFmt")
            }
            for index, node in enumerate(styles.findall(f"{ns}cellXfs/{ns}xf")):
                format_id = int(node.attrib.get("numFmtId", "0"))
                format_code = custom_formats.get(format_id, "").lower()
                if format_id in range(14, 23) or any(token in format_code for token in ("yy", "dd", "mm")):
                    date_styles.add(index)

        workbook = ElementTree.fromstring(archive.read("xl/workbook.xml"))
        sheet = workbook.find(f"{ns}sheets/{ns}sheet")
        if sheet is None:
            return []
        relation_id = sheet.attrib.get(f"{rel_ns}id")
        relations = ElementTree.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        target = next(
            (
                node.attrib.get("Target")
                for node in relations.findall(f"{pkg_ns}Relationship")
                if node.attrib.get("Id") == relation_id
            ),
            None,
        )
        if not target:
            return []
        sheet_path = target.lstrip("/")
        if not sheet_path.startswith("xl/"):
            sheet_path = f"xl/{sheet_path}"
        sheet_root = ElementTree.fromstring(archive.read(sheet_path))

        table: list[tuple[int, dict[int, Any]]] = []
        for row_node in sheet_root.findall(f".//{ns}sheetData/{ns}row"):
            row_number = int(row_node.attrib.get("r", len(table) + 1))
            values: dict[int, Any] = {}
            for cell in row_node.findall(f"{ns}c"):
                reference = cell.attrib.get("r", "A1")
                letters = re.match(r"[A-Z]+", reference.upper())
                if letters is None:
                    continue
                column_index = 0
                for char in letters.group(0):
                    column_index = column_index * 26 + ord(char) - 64
                kind = cell.attrib.get("t")
                value_node = cell.find(f"{ns}v")
                inline = cell.find(f"{ns}is")
                raw = value_node.text if value_node is not None else None
                if kind == "s" and raw is not None:
                    index = int(raw)
                    value: Any = shared[index] if 0 <= index < len(shared) else ""
                elif kind == "inlineStr" and inline is not None:
                    value = "".join(inline.itertext())
                elif kind == "b":
                    value = raw == "1"
                elif raw is not None and int(cell.attrib.get("s", "0")) in date_styles:
                    value = (datetime(1899, 12, 30) + timedelta(days=float(raw))).isoformat()
                else:
                    value = raw
                values[column_index] = value
            if values:
                table.append((row_number, values))

    if not table:
        return []
    _, header_values = table[0]
    headers = {index: str(value).strip() for index, value in header_values.items() if str(value).strip()}
    rows: list[SourceRow] = []
    for row_number, values in table[1:]:
        rows.append(SourceRow(row_number, {header: values.get(index) for index, header in headers.items()}))
        if len(rows) > settings.voc_max_import_rows:
            raise ValueError(f"import exceeds {settings.voc_max_import_rows} row limit")
    return rows


def read_import_sample(
    path: str | Path, *, settings: Settings | None = None, limit: int = 5
) -> tuple[list[str], list[dict[str, Any]]]:
    """Return headers and a bounded sample for schema detection."""

    active_settings = settings or get_settings()
    rows = _read_rows(_validate_path(Path(path), active_settings), active_settings)
    return _columns(rows), [dict(row.data) for row in rows[:limit]]


def _columns(rows: Iterable[SourceRow]) -> list[str]:
    seen: OrderedDict[str, None] = OrderedDict()
    for row in rows:
        for column in row.data:
            if not column.startswith("__"):
                seen.setdefault(column, None)
    return list(seen)


def _cell(row: Mapping[str, Any], resolved: Mapping[str, str], field: str) -> Any:
    column = resolved.get(field)
    return None if column is None else row.get(column)


def _not_blank(value: object) -> bool:
    return value is not None and (not isinstance(value, str) or bool(value.strip()))


def _parse_brand(value: object) -> Brand | None:
    if not _not_blank(value):
        return None
    normalized = re.sub(r"[^a-z]", "", str(value).lower())
    aliases = {
        "guardian": Brand.GUARDIAN,
        "guardianvietnam": Brand.GUARDIAN,
        "hasaki": Brand.HASAKI,
        "hasakibeautyhealth": Brand.HASAKI,
        "watsons": Brand.WATSONS,
        "watson": Brand.WATSONS,
        "other": Brand.OTHER,
    }
    return aliases.get(normalized, Brand.OTHER)


def _parse_visibility(value: object, default: Visibility) -> Visibility:
    if not _not_blank(value):
        return default
    normalized = str(value).strip().lower()
    aliases = {"private": "owned", "internal": "owned", "external": "public"}
    return Visibility(aliases.get(normalized, normalized))


def _parse_brand_candidates(value: object) -> list[Brand]:
    if not _not_blank(value):
        return []
    values: list[object]
    if isinstance(value, list):
        values = value
    elif isinstance(value, str) and value.strip().startswith("["):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            values = re.split(r"[|,;]", value)
        else:
            values = parsed if isinstance(parsed, list) else [parsed]
    else:
        values = re.split(r"[|,;]", str(value))
    return list(
        dict.fromkeys(
            brand
            for item in values
            if (brand := _parse_brand(item)) is not None
        )
    )


def _parse_float(value: object) -> float | None:
    if not _not_blank(value):
        return None
    return float(value)


def _parse_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if not _not_blank(value):
        return False
    normalized = str(value).strip().lower()
    if normalized in {"true", "1", "yes", "y"}:
        return True
    if normalized in {"false", "0", "no", "n"}:
        return False
    raise ValueError("boolean value must be true or false")


def _parse_metadata(value: object) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    if not _not_blank(value):
        return {}
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError:
        return {"source_metadata": str(value)}
    return (
        {str(key): item for key, item in parsed.items()}
        if isinstance(parsed, Mapping)
        else {"source_metadata": parsed}
    )


def _parse_rating(value: object) -> float | None:
    if not _not_blank(value):
        return None
    if isinstance(value, str):
        normalized = value.strip().lower().replace(",", ".")
        match = re.fullmatch(
            r"\s*([0-9]+(?:\.[0-9]+)?)\s*(?:/\s*5)?\s*(?:sao|stars?)?\s*",
            normalized,
        )
        if not match:
            raise ValueError("rating must be a number from 0 to 5")
        value = match.group(1)
    rating = float(value)
    if not 0 <= rating <= 5:
        raise ValueError("rating must be between 0 and 5")
    return rating


def _timestamp_input(value: object) -> object:
    """Turn epoch-looking CSV cells into numbers understood by parse_timestamp."""

    if isinstance(value, str) and re.fullmatch(r"\s*\d{10,13}\s*", value):
        return int(value.strip())
    return value


def _filter_date(value: FilterDate, *, field: str, timezone_name: str) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is not None and value.utcoffset() is not None:
            return value.astimezone(ZoneInfo(timezone_name)).date()
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value).strip())
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO date (YYYY-MM-DD)") from exc


def _filter_bounds(
    *,
    profile: MappingProfile,
    start: FilterDate,
    end: FilterDate,
    period_start: FilterDate,
    period_end: FilterDate,
) -> tuple[date | None, date | None]:
    start_alias = _filter_date(
        start, field="start", timezone_name=profile.timezone
    )
    period_start_date = _filter_date(
        period_start, field="period_start", timezone_name=profile.timezone
    )
    end_alias = _filter_date(end, field="end", timezone_name=profile.timezone)
    period_end_date = _filter_date(
        period_end, field="period_end", timezone_name=profile.timezone
    )
    if (
        start_alias is not None
        and period_start_date is not None
        and start_alias != period_start_date
    ):
        raise ValueError("start and period_start cannot specify different dates")
    if (
        end_alias is not None
        and period_end_date is not None
        and end_alias != period_end_date
    ):
        raise ValueError("end and period_end cannot specify different dates")
    start_date = period_start_date or start_alias
    end_date = period_end_date or end_alias
    if start_date is not None and end_date is not None and end_date < start_date:
        raise ValueError("period_end must be on or after period_start")
    return start_date, end_date


def _rating_label(rating: float) -> str:
    return str(int(rating)) if rating.is_integer() else str(rating)


def _parse_positive_int(value: object) -> int | None:
    if not _not_blank(value):
        return None
    result = int(value)
    if result < 1:
        raise ValueError("message_count must be at least one")
    return result


def _media_urls(value: object) -> list[str]:
    if not _not_blank(value):
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    if text.startswith("["):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            pass
        else:
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if str(item).strip()]
    return [part.strip() for part in re.split(r"[|;,]\s*", text) if part.strip()]


def _group_rows(
    rows: list[SourceRow],
    *,
    profile: MappingProfile,
    resolved: Mapping[str, str],
) -> list[SourceRow]:
    if not profile.group_by_conversation:
        return rows
    groups: OrderedDict[str, list[SourceRow]] = OrderedDict()
    missing: list[SourceRow] = []
    conversation_column = resolved.get("conversation_id")
    for row in rows:
        conversation = (
            row.data.get(conversation_column) if conversation_column is not None else None
        )
        if not _not_blank(conversation):
            missing.append(row)
            continue
        groups.setdefault(str(conversation).strip(), []).append(row)

    combined: list[SourceRow] = []
    for conversation, members in groups.items():
        message_at_column = resolved.get("message_at") or resolved.get("occurred_at")

        def sort_key(member: SourceRow) -> tuple[int, str, int]:
            raw_value = (
                member.data.get(message_at_column) if message_at_column is not None else None
            )
            parsed = parse_timestamp(raw_value, timezone_hint=profile.timezone)
            return (
                0 if parsed.value is not None else 1,
                parsed.value.isoformat() if parsed.value is not None else str(raw_value or ""),
                member.row_number,
            )

        ordered = sorted(members, key=sort_key)
        first = dict(ordered[0].data)
        text_column = resolved.get("text")
        sender_column = resolved.get("sender")
        occurred_column = resolved.get("occurred_at")
        observed_column = resolved.get("observed_at")
        count_column = resolved.get("message_count")
        external_id_column = resolved.get("source_external_id")

        transcript: list[str] = []
        for member in ordered:
            text = member.data.get(text_column) if text_column is not None else None
            if not _not_blank(text):
                continue
            sender = member.data.get(sender_column) if sender_column is not None else None
            transcript.append(
                f"{str(sender).strip()}: {str(text).strip()}"
                if _not_blank(sender)
                else str(text).strip()
            )
        if text_column is not None:
            first[text_column] = "\n".join(transcript)
        if count_column is not None:
            first[count_column] = len(ordered)
        else:
            first["__message_count__"] = len(ordered)
        if external_id_column is not None and not _not_blank(first.get(external_id_column)):
            first[external_id_column] = conversation
        if occurred_column is not None:
            for member in ordered:
                candidate = member.data.get(occurred_column)
                if _not_blank(candidate):
                    first[occurred_column] = candidate
                    break
        if observed_column is not None:
            for member in reversed(ordered):
                candidate = member.data.get(observed_column)
                if _not_blank(candidate):
                    first[observed_column] = candidate
                    break
        combined.append(
            SourceRow(
                row_number=ordered[0].row_number,
                data=first,
                row_numbers=tuple(member.row_number for member in ordered),
            )
        )
    # Missing conversation IDs remain separate and will be quarantined with a
    # precise validation reason rather than silently collapsed.
    combined.extend(missing)
    combined.sort(key=lambda row: row.row_number)
    return combined


def _row_to_raw(
    source_row: SourceRow,
    *,
    resolved: Mapping[str, str],
    profile: MappingProfile,
    observed_default: datetime,
    file_sha256: str,
) -> RawFeedback:
    row = source_row.data
    if "__parse_error__" in row:
        raise ValueError(str(row["__parse_error__"]))

    text = _cell(row, resolved, "text")
    title = _cell(row, resolved, "title")
    rating = _parse_rating(_cell(row, resolved, "rating"))
    rating_only = not _not_blank(text) and not _not_blank(title) and rating is not None
    if rating_only:
        # RawFeedback intentionally requires non-empty text.  Keep a plainly
        # marked, deterministic representation so a valid star-only review is
        # retained without pretending the seller response was customer text.
        text = f"Đánh giá {_rating_label(rating)} sao"
    elif not _not_blank(text):
        raise ValueError("text is required (unless a rating is present)")
    conversation = _cell(row, resolved, "conversation_id")
    if profile.group_by_conversation and not _not_blank(conversation):
        raise ValueError("conversation_id is required for conversation imports")

    timezone_value = _cell(row, resolved, "original_timezone")
    timezone_name = (
        str(timezone_value).strip() if _not_blank(timezone_value) else profile.timezone
    )
    quality_value = _cell(row, resolved, "occurred_at_quality")
    try:
        quality_hint = (
            OccurredAtQuality(str(quality_value).strip().lower())
            if _not_blank(quality_value)
            else profile.occurred_at_quality
        )
    except ValueError as exc:
        raise ValueError("invalid occurred_at_quality") from exc

    observed_raw = _cell(row, resolved, "observed_at")
    observed = parse_timestamp(
        _timestamp_input(observed_raw),
        timezone_hint=timezone_name,
        quality_hint=OccurredAtQuality.PARSED,
    )
    observed_at = observed.value or observed_default
    occurred = parse_timestamp(
        _timestamp_input(_cell(row, resolved, "occurred_at")),
        timezone_hint=timezone_name,
        observed_at=observed_at,
        quality_hint=quality_hint,
    )

    fixed_brand = profile.fixed_brand
    mapped_brand = _parse_brand(_cell(row, resolved, "brand"))
    brand = fixed_brand or mapped_brand
    candidates = list(profile.brand_candidates)
    for candidate in _parse_brand_candidates(
        _cell(row, resolved, "brand_candidates")
    ):
        if candidate not in candidates:
            candidates.append(candidate)
    if mapped_brand is not None and mapped_brand not in candidates:
        candidates.append(mapped_brand)
    if brand is None and not candidates:
        raise ValueError("brand is required by this mapping profile")

    dynamic_platform = _cell(row, resolved, "source_platform")
    source_platform = (
        str(dynamic_platform).strip()
        if _not_blank(dynamic_platform) and profile.source_platform in {"generic", "marketplace"}
        else profile.source_platform
    )
    metadata: dict[str, Any] = {
        **_parse_metadata(_cell(row, resolved, "metadata")),
        "import_profile": profile.name,
        "file_sha256": file_sha256,
        "source_row_numbers": list(source_row.all_row_numbers),
        "_language_trusted": profile.trusted_language,
        "experience_subject": profile.experience_subject.value,
    }
    for metadata_field in (
        "product_id",
        "shop_id",
        "seller_reply",
        "seller_reply_at",
        "seller_reply_id",
    ):
        metadata_value = _cell(row, resolved, metadata_field)
        if _not_blank(metadata_value):
            metadata[metadata_field] = metadata_value
    if rating_only:
        metadata["rating_only"] = True
        metadata["original_text_missing"] = True
    if occurred.error:
        metadata["occurred_at_parse_warning"] = occurred.error

    message_count = _parse_positive_int(_cell(row, resolved, "message_count"))
    if message_count is None and "__message_count__" in row:
        message_count = int(row["__message_count__"])

    dynamic_group = _cell(row, resolved, "source_group")
    source_group = (
        SourceGroup(str(dynamic_group).strip().lower())
        if _not_blank(dynamic_group) and profile.name == "generic"
        else profile.source_group
    )
    return RawFeedback(
        source_external_id=(
            str(_cell(row, resolved, "source_external_id")).strip()
            if _not_blank(_cell(row, resolved, "source_external_id"))
            else None
        ),
        source_group=source_group,
        source_platform=source_platform,
        visibility=_parse_visibility(
            _cell(row, resolved, "visibility"), profile.visibility
        ),
        brand=brand,
        brand_candidates=candidates,
        occurred_at=occurred.value,
        observed_at=observed_at,
        occurred_at_quality=occurred.quality,
        original_timezone=(
            str(timezone_value).strip()
            if _not_blank(timezone_value)
            else occurred.original_timezone
        ),
        language=(
            str(_cell(row, resolved, "language")).strip()
            if _not_blank(_cell(row, resolved, "language"))
            else None
        ),
        language_confidence=_parse_float(
            _cell(row, resolved, "language_confidence")
        ),
        title=(str(title).strip() if _not_blank(title) else None),
        text=str(text).strip(),
        rating=rating,
        product_name=(
            str(_cell(row, resolved, "product_name")).strip()
            if _not_blank(_cell(row, resolved, "product_name"))
            else None
        ),
        product_category=(
            str(_cell(row, resolved, "product_category")).strip()
            if _not_blank(_cell(row, resolved, "product_category"))
            else None
        ),
        region=(
            str(_cell(row, resolved, "region")).strip()
            if _not_blank(_cell(row, resolved, "region"))
            else None
        ),
        store=(
            str(_cell(row, resolved, "store")).strip()
            if _not_blank(_cell(row, resolved, "store"))
            else None
        ),
        source_url=(
            str(_cell(row, resolved, "source_url")).strip()
            if _not_blank(_cell(row, resolved, "source_url"))
            else None
        ),
        author_id=(
            str(_cell(row, resolved, "author_id")).strip()
            if _not_blank(_cell(row, resolved, "author_id"))
            else None
        ),
        conversation_id=(str(conversation).strip() if _not_blank(conversation) else None),
        message_count=message_count,
        media_urls=_media_urls(_cell(row, resolved, "media_urls")),
        metadata=metadata,
        is_synthetic=_parse_bool(_cell(row, resolved, "is_synthetic")),
    )


def _filter_issue(
    raw: RawFeedback,
    *,
    profile: MappingProfile,
    vietnamese_only: bool,
    start: date | None,
    end: date | None,
) -> tuple[str, str, str] | None:
    if vietnamese_only and raw.metadata.get("rating_only") is not True:
        language = resolve_language(
            f"{raw.title or ''}\n{raw.text}",
            provided_language=raw.language,
            provided_confidence=raw.language_confidence,
            trusted=profile.trusted_language,
        )
        if language.language != "vi":
            return (
                "language_filtered",
                f"Vietnamese-only import rejected detected language {language.language!r}",
                "language",
            )
        # Record the exact decision made at the import boundary.  The normalizer
        # will independently apply the same deterministic detector downstream.
        raw.language = language.language
        raw.language_confidence = language.confidence
        raw.metadata["import_language_detection"] = {
            "language": language.language,
            "confidence": language.confidence,
        }

    if start is not None or end is not None:
        if raw.occurred_at is None:
            return (
                "period_filtered",
                "period-filtered import requires a parseable occurred_at value",
                "occurred_at",
            )
        local_date = raw.occurred_at.astimezone(ZoneInfo(profile.timezone)).date()
        if start is not None and local_date < start:
            return (
                "period_filtered",
                f"occurred_at date {local_date.isoformat()} is before {start.isoformat()}",
                "occurred_at",
            )
        if end is not None and local_date > end:
            return (
                "period_filtered",
                f"occurred_at date {local_date.isoformat()} is after {end.isoformat()}",
                "occurred_at",
            )
        raw.metadata["import_period"] = {
            "start": start.isoformat() if start is not None else None,
            "end": end.isoformat() if end is not None else None,
            "timezone": profile.timezone,
            "inclusive": True,
        }
    return None


def _parse_import(
    path: Path,
    *,
    profile: MappingProfile,
    settings: Settings,
    observed_default: datetime,
    vietnamese_only: bool = False,
    start: date | None = None,
    end: date | None = None,
) -> tuple[list[RawFeedback], list[QuarantinedRow], list[str], dict[str, str], str, int]:
    path = _validate_path(path, settings)
    file_sha256 = _file_digest(path)
    source_rows = _read_rows(path, settings)
    columns = _columns(source_rows)
    resolved = profile.resolve_columns(columns)
    grouped = _group_rows(source_rows, profile=profile, resolved=resolved)
    valid: list[RawFeedback] = []
    quarantined: list[QuarantinedRow] = []
    for source_row in grouped:
        try:
            raw = _row_to_raw(
                source_row,
                resolved=resolved,
                profile=profile,
                observed_default=observed_default,
                file_sha256=file_sha256,
            )
            issue = _filter_issue(
                raw,
                profile=profile,
                vietnamese_only=vietnamese_only,
                start=start,
                end=end,
            )
            if issue is not None:
                code, message, field = issue
                quarantined.append(
                    QuarantinedRow(
                        row_number=source_row.row_number,
                        code=code,
                        message=message,
                        field=field,
                        masked_sample=mask_preview_mapping(
                            source_row.data,
                            text_limit=settings.voc_preview_text_limit,
                        ),
                        source_row_numbers=source_row.all_row_numbers,
                    )
                )
                continue
            valid.append(raw)
        except (TypeError, ValueError, ValidationError) as exc:
            message = str(exc).splitlines()[0][:500]
            field = "text" if "text" in message else "conversation_id" if "conversation_id" in message else "rating" if "rating" in message else None
            quarantined.append(
                QuarantinedRow(
                    row_number=source_row.row_number,
                    code=(
                        "malformed_json"
                        if "__parse_error__" in source_row.data
                        else "validation_error"
                    ),
                    message=message,
                    field=field,
                    masked_sample=mask_preview_mapping(
                        source_row.data, text_limit=settings.voc_preview_text_limit
                    ),
                    source_row_numbers=source_row.all_row_numbers,
                )
            )
    return valid, quarantined, columns, resolved, file_sha256, len(grouped)


def preview_import(
    path: str | Path,
    profile: str | MappingProfile,
    *,
    settings: Settings | None = None,
    max_samples: int = 5,
    max_issues: int = 100,
    observed_at: datetime | None = None,
    vietnamese_only: bool = False,
    start: FilterDate = None,
    end: FilterDate = None,
    period_start: FilterDate = None,
    period_end: FilterDate = None,
) -> ImportPreview:
    settings = settings or get_settings()
    profile_obj = get_profile(profile) if isinstance(profile, str) else profile
    start_date, end_date = _filter_bounds(
        profile=profile_obj,
        start=start,
        end=end,
        period_start=period_start,
        period_end=period_end,
    )
    timestamp = observed_at or datetime.now(timezone.utc)
    valid, quarantine, columns, resolved, digest, total = _parse_import(
        Path(path),
        profile=profile_obj,
        settings=settings,
        observed_default=timestamp,
        vietnamese_only=vietnamese_only,
        start=start_date,
        end=end_date,
    )
    samples = [
        mask_preview_mapping(
            {
                "source_platform": item.source_platform,
                "brand": item.brand.value if item.brand else None,
                "occurred_at": item.occurred_at.isoformat() if item.occurred_at else None,
                "title": item.title,
                "text": item.text,
                "rating": item.rating,
                "product_name": item.product_name,
            },
            text_limit=settings.voc_preview_text_limit,
        )
        for item in valid[:max_samples]
    ]
    return ImportPreview(
        profile=profile_obj.name,
        source_name=profile_obj.source_name,
        filename=Path(path).name,
        file_sha256=digest,
        columns=columns,
        resolved_mapping=resolved,
        total_rows=total,
        valid_rows=len(valid),
        invalid_rows=len(quarantine),
        samples=samples,
        issues=[item.as_issue() for item in quarantine[:max_issues]],
    )


class FileImportConnector:
    """Connector for a single checked import file."""

    def __init__(
        self,
        path: str | Path,
        profile: str | MappingProfile,
        *,
        settings: Settings | None = None,
        vietnamese_only: bool = False,
        start: FilterDate = None,
        end: FilterDate = None,
        period_start: FilterDate = None,
        period_end: FilterDate = None,
    ) -> None:
        self.path = Path(path)
        self.profile = get_profile(profile) if isinstance(profile, str) else profile
        self.settings = settings or get_settings()
        self.vietnamese_only = vietnamese_only
        self.period_start, self.period_end = _filter_bounds(
            profile=self.profile,
            start=start,
            end=end,
            period_start=period_start,
            period_end=period_end,
        )
        self.quarantined: list[QuarantinedRow] = []
        self.file_sha256: str | None = None

    def preview(self, *, max_samples: int = 5, max_issues: int = 100) -> ImportPreview:
        return preview_import(
            self.path,
            self.profile,
            settings=self.settings,
            max_samples=max_samples,
            max_issues=max_issues,
            vietnamese_only=self.vietnamese_only,
            start=self.period_start,
            end=self.period_end,
        )

    async def collect(self, run: IngestionRun):
        valid, quarantine, _, _, digest, _ = _parse_import(
            self.path,
            profile=self.profile,
            settings=self.settings,
            observed_default=run.started_at,
            vietnamese_only=self.vietnamese_only,
            start=self.period_start,
            end=self.period_end,
        )
        self.quarantined = quarantine
        self.file_sha256 = digest
        for item in valid:
            yield item


__all__ = [
    "FileImportConnector",
    "GUARDIAN_VOC_PERIOD_END",
    "GUARDIAN_VOC_PERIOD_START",
    "QuarantinedRow",
    "SUPPORTED_IMPORT_SUFFIXES",
    "preview_import",
    "read_import_sample",
]
