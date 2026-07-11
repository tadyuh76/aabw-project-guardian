"""Authorized seller-API connectors for Guardian marketplace reviews.

These connectors deliberately do not discover or scrape marketplace pages.  A
caller must provide seller-scoped credentials and explicitly attest that the
shop is Guardian-owned.  The resulting records are fixed to ``Brand.GUARDIAN``;
there is no competitor mode.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlsplit

import httpx

from guardian_voc.pipeline.normalize import parse_timestamp
from guardian_voc.pipeline.language import resolve_language
from guardian_voc.schemas.feedback import (
    Brand,
    IngestionRun,
    OccurredAtQuality,
    RawFeedback,
    SourceGroup,
    Visibility,
)


SHOPEE_GET_COMMENT_PATH = "/api/v2/product/get_comment"
SHOPEE_GET_ITEM_LIST_PATH = "/api/v2/product/get_item_list"
LAZADA_REVIEW_LIST_PATH = "/review/seller/list"
LAZADA_GET_PRODUCTS_PATH = "/products/get"
_MAX_RESPONSE_BYTES = 10 * 1024 * 1024
_BUSINESS_TIMEZONE = "Asia/Ho_Chi_Minh"


class MarketplaceCredentialsError(ValueError):
    """Raised when required seller credentials are absent or malformed."""


class MarketplaceAuthorizationError(PermissionError):
    """Raised unless the caller confirms the seller account is Guardian-owned."""


class MarketplaceAPIError(RuntimeError):
    """Secret-safe marketplace transport or provider error."""


def _required_text(value: object, label: str) -> str:
    text = str(value).strip() if value is not None else ""
    if not text:
        raise MarketplaceCredentialsError(f"{label} is required")
    return text


def _positive_int(value: object, label: str) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise MarketplaceCredentialsError(f"{label} must be a positive integer") from exc
    if result <= 0:
        raise MarketplaceCredentialsError(f"{label} must be a positive integer")
    return result


@dataclass(frozen=True, repr=False)
class ShopeeCredentials:
    """Shopee seller credentials; repr intentionally masks both secrets."""

    partner_id: int
    partner_key: str
    access_token: str
    shop_id: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "partner_id", _positive_int(self.partner_id, "partner_id"))
        object.__setattr__(self, "shop_id", _positive_int(self.shop_id, "shop_id"))
        object.__setattr__(
            self, "partner_key", _required_text(self.partner_key, "partner_key")
        )
        object.__setattr__(
            self, "access_token", _required_text(self.access_token, "access_token")
        )

    def __repr__(self) -> str:
        return (
            "ShopeeCredentials("
            f"partner_id={self.partner_id}, shop_id={self.shop_id}, "
            "partner_key='[REDACTED]', access_token='[REDACTED]')"
        )


@dataclass(frozen=True, repr=False)
class LazadaCredentials:
    """Lazada seller credentials; repr intentionally masks both secrets."""

    app_key: str
    app_secret: str
    access_token: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "app_key", _required_text(self.app_key, "app_key"))
        object.__setattr__(
            self, "app_secret", _required_text(self.app_secret, "app_secret")
        )
        object.__setattr__(
            self, "access_token", _required_text(self.access_token, "access_token")
        )

    def __repr__(self) -> str:
        return (
            "LazadaCredentials(app_key='[REDACTED]', "
            "app_secret='[REDACTED]', access_token='[REDACTED]')"
        )


@dataclass
class ItemReconciliation:
    item_id: str
    pages_requested: int = 0
    rows_received: int = 0
    unique_rows_received: int = 0
    records_emitted: int = 0
    records_before_window: int = 0
    records_after_window: int = 0
    records_missing_date: int = 0
    records_language_filtered: int = 0
    records_invalid: int = 0
    duplicates_removed: int = 0
    reported_total: int | None = None
    pagination_complete: bool = False
    reconciliation: str = "pending"
    cursor_chain_sha256: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class MarketplaceReconciliationManifest:
    """Secret-free accounting for pages, cursors, totals, and date filtering."""

    platform: str
    item_ids: tuple[str, ...]
    lookback_days: int
    vietnamese_only: bool = True
    window_start: str | None = None
    window_end: str | None = None
    items: dict[str, ItemReconciliation] = field(default_factory=dict)
    item_discovery_requested: bool = False
    item_discovery_complete: bool = False
    item_discovery_pages: int = 0
    item_discovery_count: int = 0
    item_discovery_warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["item_ids"] = list(self.item_ids)
        payload["totals"] = {
            "pages_requested": sum(item.pages_requested for item in self.items.values()),
            "rows_received": sum(item.rows_received for item in self.items.values()),
            "unique_rows_received": sum(
                item.unique_rows_received for item in self.items.values()
            ),
            "records_emitted": sum(item.records_emitted for item in self.items.values()),
            "records_before_window": sum(
                item.records_before_window for item in self.items.values()
            ),
            "records_after_window": sum(
                item.records_after_window for item in self.items.values()
            ),
            "records_missing_date": sum(
                item.records_missing_date for item in self.items.values()
            ),
            "records_language_filtered": sum(
                item.records_language_filtered for item in self.items.values()
            ),
            "records_invalid": sum(
                item.records_invalid for item in self.items.values()
            ),
            "duplicates_removed": sum(
                item.duplicates_removed for item in self.items.values()
            ),
        }
        return payload

    def __getitem__(self, key: str) -> Any:
        return self.as_dict()[key]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _clock_timestamp(clock: Callable[[], datetime]) -> datetime:
    value = clock()
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("clock must return a timezone-aware datetime")
    return value.astimezone(timezone.utc)


def _validate_item_ids(item_ids: Sequence[int | str]) -> tuple[str, ...]:
    normalized = tuple(dict.fromkeys(str(value).strip() for value in item_ids))
    if not normalized or any(not value for value in normalized):
        raise ValueError("at least one non-empty item_id is required")
    if any(not value.isdigit() or int(value) <= 0 for value in normalized):
        raise ValueError("item_id values must be positive integers")
    return normalized


def _validate_official_base_url(
    value: str, *, allowed_hosts: frozenset[str], label: str
) -> str:
    parsed = urlsplit(value.strip())
    if (
        parsed.scheme != "https"
        or parsed.hostname not in allowed_hosts
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(f"{label} must use an approved official HTTPS endpoint")
    return value.rstrip("/")


def sign_shopee_request(
    *,
    partner_id: int,
    api_path: str,
    timestamp: int,
    access_token: str,
    shop_id: int,
    partner_key: str,
) -> str:
    """Return the Shopee v2 shop-level HMAC-SHA256 signature."""

    base = f"{partner_id}{api_path}{timestamp}{access_token}{shop_id}"
    return hmac.new(
        partner_key.encode("utf-8"), base.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def sign_lazada_request(
    *, api_path: str, parameters: Mapping[str, object], app_secret: str
) -> str:
    """Return the LazOP HMAC-SHA256 signature over sorted request parameters."""

    unsigned = {key: value for key, value in parameters.items() if key != "sign"}
    base = api_path + "".join(
        f"{key}{unsigned[key]}" for key in sorted(unsigned)
    )
    return hmac.new(
        app_secret.encode("utf-8"), base.encode("utf-8"), hashlib.sha256
    ).hexdigest().upper()


def _mapping(value: object) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    return {str(key): item for key, item in value.items()}


def _extract_product_item_ids(value: object) -> list[str]:
    """Read provider product-list shapes without trusting unrelated IDs."""

    found: list[str] = []

    def visit(node: object, *, in_product: bool = False, depth: int = 0) -> None:
        if depth > 8:
            return
        if isinstance(node, list):
            for child in node:
                visit(child, in_product=in_product, depth=depth + 1)
            return
        mapped = _mapping(node)
        if mapped is None:
            return
        product_context = in_product or any(
            key in mapped
            for key in (
                "item_id",
                "ItemId",
                "product_id",
                "item_name",
                "product_name",
                "attributes",
                "skus",
                "status",
            )
        )
        if product_context:
            direct = _first(mapped, "item_id", "ItemId", "product_id")
            parsed = _as_int(direct)
            if parsed is not None and parsed > 0:
                found.append(str(parsed))
        for key in ("item", "items", "products", "product", "data"):
            child = mapped.get(key)
            if isinstance(child, (list, Mapping)):
                visit(
                    child,
                    in_product=product_context or key in {"item", "items", "products", "product"},
                    depth=depth + 1,
                )

    visit(value)
    return list(dict.fromkeys(found))


def _first(row: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = row.get(key)
        if value is not None and (not isinstance(value, str) or value.strip()):
            return value
    return None


def _as_int(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _as_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes"}:
            return True
        if normalized in {"false", "0", "no"}:
            return False
    return None


def _as_rating(value: object) -> float | None:
    if isinstance(value, Mapping):
        value = _first(value, "overall", "overall_rating", "rating", "score")
    try:
        rating = float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
    return rating if rating is not None and 0 <= rating <= 5 else None


def _urls(value: object) -> list[str]:
    found: list[str] = []

    def visit(item: object, depth: int = 0) -> None:
        if depth > 4 or len(found) >= 100:
            return
        if isinstance(item, str):
            text = item.strip()
            if text.startswith(("https://", "http://")):
                found.append(text)
            return
        if isinstance(item, Mapping):
            direct = _first(item, "url", "image_url", "video_url", "file_url")
            if isinstance(direct, str):
                visit(direct, depth + 1)
            else:
                for child in item.values():
                    visit(child, depth + 1)
            return
        if isinstance(item, Sequence) and not isinstance(item, (str, bytes, bytearray)):
            for child in item:
                visit(child, depth + 1)

    visit(value)
    return list(dict.fromkeys(found))


def _seller_reply(value: object) -> dict[str, Any] | None:
    if value is None or value == "":
        return None
    if isinstance(value, str):
        return {"text": value.strip()} if value.strip() else None
    reply = _mapping(value)
    if reply is None:
        return None
    result: dict[str, Any] = {}
    text = _first(reply, "comment", "content", "reply", "text", "message")
    if text is not None:
        result["text"] = str(text).strip()
    created = _first(reply, "create_time", "created_at", "reply_time", "date")
    if created is not None:
        result["created_at"] = created
    reply_id = _first(reply, "reply_id", "id")
    if reply_id is not None:
        result["reply_id"] = str(reply_id)
    for source, target in (("editable", "editable"), ("hidden", "hidden")):
        parsed = _as_bool(reply.get(source))
        if parsed is not None:
            result[target] = parsed
    return result or None


def _review_identity(platform: str, item_id: str, row: Mapping[str, Any]) -> str:
    direct = _first(row, "comment_id", "review_id", "rating_id", "id")
    if direct is not None:
        return str(direct).strip()
    # Stable fallback for provider rows that unexpectedly omit an identifier.
    canonical = json.dumps(row, ensure_ascii=False, sort_keys=True, default=str)
    digest = hashlib.sha256(
        f"{platform}\0{item_id}\0{canonical}".encode("utf-8")
    ).hexdigest()
    return f"generated-{digest}"


def _review_text(row: Mapping[str, Any], rating: float | None) -> tuple[str, bool]:
    title = _first(row, "title", "review_title")
    body = _first(
        row,
        "comment",
        "content",
        "review_content",
        "review_text",
        "message",
        "text",
    )
    parts = [str(value).strip() for value in (title, body) if value is not None and str(value).strip()]
    if parts:
        return "\n".join(dict.fromkeys(parts)), False
    if rating is not None:
        return f"Đánh giá {rating:g}/5 không kèm nội dung.", True
    return "Đánh giá không kèm nội dung văn bản.", True


def _reported_total(value: Mapping[str, Any]) -> int | None:
    for key in ("total_count", "total", "total_reviews", "review_count"):
        parsed = _as_int(value.get(key))
        if parsed is not None and parsed >= 0:
            return parsed
    return None


def _hash_cursor(cursor: object) -> str:
    return hashlib.sha256(str(cursor).encode("utf-8")).hexdigest()


def _finalize_reconciliation(item: ItemReconciliation) -> None:
    if not item.pagination_complete:
        item.reconciliation = "incomplete"
    elif item.reported_total is None:
        item.reconciliation = "total_unavailable"
    elif item.unique_rows_received == item.reported_total:
        item.reconciliation = "matched"
    else:
        item.reconciliation = "total_mismatch"
        item.warnings.append(
            "reported total does not match unique rows received across completed pagination"
        )


def _safe_json(response: httpx.Response, platform: str) -> dict[str, Any]:
    if response.status_code < 200 or response.status_code >= 300:
        raise MarketplaceAPIError(
            f"{platform} API request failed with HTTP {response.status_code}"
        )
    if len(response.content) > _MAX_RESPONSE_BYTES:
        raise MarketplaceAPIError(f"{platform} API response exceeded the size limit")
    try:
        payload = response.json()
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
        raise MarketplaceAPIError(f"{platform} API returned invalid JSON") from None
    mapped = _mapping(payload)
    if mapped is None:
        raise MarketplaceAPIError(f"{platform} API response must be an object")
    return mapped


def _window(run: IngestionRun, lookback_days: int) -> tuple[datetime, datetime]:
    end = run.started_at.astimezone(timezone.utc)
    return end - timedelta(days=lookback_days), end


def _date_disposition(
    occurred_at: datetime | None, *, start: datetime, end: datetime
) -> str | None:
    if occurred_at is None:
        return "missing"
    if occurred_at < start:
        return "before"
    if occurred_at > end:
        return "after"
    return None


class ShopeeReviewConnector:
    """Collect Guardian reviews from Shopee's seller-scoped GetComment API."""

    def __init__(
        self,
        credentials: ShopeeCredentials,
        *,
        item_ids: Sequence[int | str] = (),
        discover_all_items: bool = False,
        owned_shop_authorized: bool = False,
        page_size: int = 100,
        max_pages_per_item: int = 10_000,
        lookback_days: int = 365,
        vietnamese_only: bool = True,
        base_url: str = "https://partner.shopeemobile.com",
        timeout_seconds: float = 30,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        if not isinstance(credentials, ShopeeCredentials):
            raise MarketplaceCredentialsError("ShopeeCredentials must be provided explicitly")
        if not owned_shop_authorized:
            raise MarketplaceAuthorizationError(
                "Guardian-owned Shopee shop authorization must be confirmed"
            )
        if not 1 <= page_size <= 100:
            raise ValueError("page_size must be between 1 and 100")
        if max_pages_per_item < 1:
            raise ValueError("max_pages_per_item must be at least one")
        if lookback_days < 1:
            raise ValueError("lookback_days must be at least one")
        self.credentials = credentials
        self.item_ids = _validate_item_ids(item_ids) if item_ids else ()
        if not self.item_ids and not discover_all_items:
            raise ValueError(
                "item_ids are required unless discover_all_items is enabled"
            )
        self.discover_all_items = discover_all_items
        self.page_size = page_size
        self.max_pages_per_item = max_pages_per_item
        self.lookback_days = lookback_days
        self.vietnamese_only = vietnamese_only
        self.base_url = _validate_official_base_url(
            base_url,
            allowed_hosts=frozenset(
                {"partner.shopeemobile.com", "partner.test-stable.shopeemobile.com"}
            ),
            label="Shopee base_url",
        )
        self.timeout_seconds = timeout_seconds
        self.transport = transport
        self.clock = clock
        self.manifest = MarketplaceReconciliationManifest(
            platform="shopee",
            item_ids=self.item_ids,
            lookback_days=lookback_days,
            vietnamese_only=vietnamese_only,
            item_discovery_requested=discover_all_items,
        )

    async def _request_item_list(
        self,
        client: httpx.AsyncClient,
        *,
        item_status: str,
        offset: int,
    ) -> dict[str, Any]:
        now = _clock_timestamp(self.clock)
        timestamp = int(now.timestamp())
        credentials = self.credentials
        params: dict[str, object] = {
            "partner_id": credentials.partner_id,
            "timestamp": timestamp,
            "access_token": credentials.access_token,
            "shop_id": credentials.shop_id,
            "item_status": item_status,
            "offset": offset,
            "page_size": self.page_size,
        }
        params["sign"] = sign_shopee_request(
            partner_id=credentials.partner_id,
            api_path=SHOPEE_GET_ITEM_LIST_PATH,
            timestamp=timestamp,
            access_token=credentials.access_token,
            shop_id=credentials.shop_id,
            partner_key=credentials.partner_key,
        )
        try:
            response = await client.get(
                f"{self.base_url}{SHOPEE_GET_ITEM_LIST_PATH}", params=params
            )
        except httpx.HTTPError:
            raise MarketplaceAPIError("Shopee item-list API request failed") from None
        payload = _safe_json(response, "Shopee")
        if payload.get("error") not in (None, "", 0, "0"):
            raise MarketplaceAPIError("Shopee item-list API returned an application error")
        return payload

    async def _discover_item_ids(self, client: httpx.AsyncClient) -> tuple[str, ...]:
        discovered: list[str] = []
        complete = True
        for item_status in ("NORMAL", "UNLIST", "BANNED", "DELETED"):
            offset = 0
            seen_offsets: set[int] = set()
            for _ in range(self.max_pages_per_item):
                payload = await self._request_item_list(
                    client, item_status=item_status, offset=offset
                )
                self.manifest.item_discovery_pages += 1
                response = _mapping(payload.get("response")) or {}
                discovered.extend(_extract_product_item_ids(response.get("item") or response))
                has_next = _as_bool(
                    _first(response, "has_next_page", "more", "has_more")
                )
                if has_next is False:
                    break
                next_offset = _as_int(_first(response, "next_offset", "offset"))
                if has_next is None and next_offset is None:
                    break
                if next_offset is None or next_offset <= offset or next_offset in seen_offsets:
                    complete = False
                    self.manifest.item_discovery_warnings.append(
                        f"{item_status}: invalid or repeated item-list offset"
                    )
                    break
                seen_offsets.add(next_offset)
                offset = next_offset
            else:
                complete = False
                self.manifest.item_discovery_warnings.append(
                    f"{item_status}: max item-list pages reached"
                )
        combined = tuple(dict.fromkeys([*self.item_ids, *discovered]))
        self.item_ids = combined
        self.manifest.item_ids = combined
        self.manifest.item_discovery_count = len(dict.fromkeys(discovered))
        self.manifest.item_discovery_complete = complete
        return combined

    async def _request(
        self, client: httpx.AsyncClient, *, item_id: str, cursor: str | None
    ) -> dict[str, Any]:
        now = _clock_timestamp(self.clock)
        timestamp = int(now.timestamp())
        credentials = self.credentials
        params: dict[str, object] = {
            "partner_id": credentials.partner_id,
            "timestamp": timestamp,
            "access_token": credentials.access_token,
            "shop_id": credentials.shop_id,
            "item_id": item_id,
            "page_size": self.page_size,
        }
        if cursor:
            params["cursor"] = cursor
        params["sign"] = sign_shopee_request(
            partner_id=credentials.partner_id,
            api_path=SHOPEE_GET_COMMENT_PATH,
            timestamp=timestamp,
            access_token=credentials.access_token,
            shop_id=credentials.shop_id,
            partner_key=credentials.partner_key,
        )
        try:
            response = await client.get(
                f"{self.base_url}{SHOPEE_GET_COMMENT_PATH}", params=params
            )
        except httpx.HTTPError:
            raise MarketplaceAPIError("Shopee API request failed") from None
        payload = _safe_json(response, "Shopee")
        if payload.get("error") not in (None, "", 0, "0"):
            raise MarketplaceAPIError("Shopee API returned an application error")
        return payload

    async def collect(self, run: IngestionRun) -> AsyncIterator[RawFeedback]:
        start, end = _window(run, self.lookback_days)
        self.manifest = MarketplaceReconciliationManifest(
            platform="shopee",
            item_ids=self.item_ids,
            lookback_days=self.lookback_days,
            vietnamese_only=self.vietnamese_only,
            window_start=start.isoformat(),
            window_end=end.isoformat(),
            item_discovery_requested=self.discover_all_items,
        )
        async with httpx.AsyncClient(
            timeout=self.timeout_seconds,
            transport=self.transport,
            follow_redirects=False,
            trust_env=False,
        ) as client:
            if self.discover_all_items:
                await self._discover_item_ids(client)
            for item_id in self.item_ids:
                state = ItemReconciliation(item_id=item_id)
                self.manifest.items[item_id] = state
                cursor: str | None = None
                seen_cursors: set[str] = set()
                seen_reviews: set[str] = set()
                for _ in range(self.max_pages_per_item):
                    payload = await self._request(client, item_id=item_id, cursor=cursor)
                    state.pages_requested += 1
                    response = _mapping(payload.get("response")) or {}
                    total = _reported_total(response)
                    if total is not None:
                        state.reported_total = max(state.reported_total or 0, total)
                    raw_rows = response.get("item_comment_list")
                    rows = raw_rows if isinstance(raw_rows, list) else []
                    state.rows_received += len(rows)
                    for raw_row in rows:
                        row = _mapping(raw_row)
                        if row is None:
                            state.records_invalid += 1
                            continue
                        review_id = _review_identity("shopee", item_id, row)
                        if review_id in seen_reviews:
                            state.duplicates_removed += 1
                            continue
                        seen_reviews.add(review_id)
                        state.unique_rows_received += 1
                        parsed = parse_timestamp(
                            _first(
                                row,
                                "create_time",
                                "ctime",
                                "created_at",
                                "review_date",
                            ),
                            timezone_hint=_BUSINESS_TIMEZONE,
                            observed_at=end,
                            quality_hint=OccurredAtQuality.EXACT,
                        )
                        disposition = _date_disposition(
                            parsed.value, start=start, end=end
                        )
                        if disposition == "missing":
                            state.records_missing_date += 1
                            continue
                        if disposition == "before":
                            state.records_before_window += 1
                            continue
                        if disposition == "after":
                            state.records_after_window += 1
                            continue
                        rating = _as_rating(
                            _first(row, "rating_star", "rating", "score")
                        )
                        text, generated_text = _review_text(row, rating)
                        title_value = _first(row, "title", "review_title")
                        rating_only = generated_text and rating is not None
                        language_input = (
                            f"{title_value or ''}\n{text}"
                            if not generated_text or rating_only
                            else ""
                        )
                        language = resolve_language(language_input)
                        if (
                            self.vietnamese_only
                            and not rating_only
                            and language.language != "vi"
                        ):
                            state.records_language_filtered += 1
                            continue
                        media = _urls(
                            [
                                row.get("images"),
                                row.get("image_urls"),
                                row.get("videos"),
                                row.get("media"),
                            ]
                        )
                        reply = _seller_reply(
                            _first(row, "seller_reply", "reply", "shop_reply")
                        )
                        metadata: dict[str, Any] = {
                            "api_path": SHOPEE_GET_COMMENT_PATH,
                            "item_id": item_id,
                            "shop_id": self.credentials.shop_id,
                            "api_page": state.pages_requested,
                            "experience_subject": "retailer",
                            "text_is_generated_rating_summary": generated_text,
                            "rating_only": rating_only,
                            "marketplace_language_detection": {
                                "language": language.language,
                                "confidence": language.confidence,
                            },
                        }
                        if reply is not None:
                            metadata["seller_reply"] = reply
                        product_items = row.get("product_items")
                        if isinstance(product_items, list):
                            metadata["product_items"] = product_items[:20]
                        state.records_emitted += 1
                        yield RawFeedback(
                            source_external_id=review_id,
                            source_group=SourceGroup.MARKETPLACE,
                            source_platform="shopee",
                            visibility=Visibility.PUBLIC,
                            brand=Brand.GUARDIAN,
                            brand_candidates=[Brand.GUARDIAN],
                            occurred_at=parsed.value,
                            observed_at=end,
                            occurred_at_quality=parsed.quality,
                            original_timezone=parsed.original_timezone,
                            language=language.language,
                            language_confidence=language.confidence,
                            title=(
                                str(title_value).strip()
                                if title_value is not None
                                else None
                            ),
                            text=text,
                            rating=rating,
                            product_name=(
                                str(_first(row, "product_name", "item_name")).strip()
                                if _first(row, "product_name", "item_name") is not None
                                else None
                            ),
                            store="Guardian Official Store",
                            source_url=(
                                str(_first(row, "review_url", "product_url", "url")).strip()
                                if _first(row, "review_url", "product_url", "url")
                                is not None
                                else None
                            ),
                            author_id=(
                                str(
                                    _first(
                                        row,
                                        "author_id",
                                        "user_id",
                                        "author_username",
                                        "username",
                                    )
                                ).strip()
                                if _first(
                                    row,
                                    "author_id",
                                    "user_id",
                                    "author_username",
                                    "username",
                                )
                                is not None
                                else None
                            ),
                            media_urls=media,
                            metadata=metadata,
                        )

                    more = _as_bool(_first(response, "more", "has_more"))
                    next_cursor_raw = _first(response, "next_cursor", "cursor")
                    if not more:
                        state.pagination_complete = True
                        break
                    if next_cursor_raw is None or not str(next_cursor_raw).strip():
                        state.warnings.append(
                            "provider indicated more rows but omitted next_cursor"
                        )
                        break
                    next_cursor = str(next_cursor_raw).strip()
                    if next_cursor in seen_cursors:
                        state.warnings.append("provider returned a repeated cursor")
                        break
                    seen_cursors.add(next_cursor)
                    state.cursor_chain_sha256.append(_hash_cursor(next_cursor))
                    cursor = next_cursor
                else:
                    state.warnings.append("max_pages_per_item reached")
                _finalize_reconciliation(state)


def _extract_lazada_reviews(
    data: object, *, default_item_id: str
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Flatten nested ``reviews[]`` arrays while retaining product context."""

    result: list[tuple[dict[str, Any], dict[str, Any]]] = []

    def visit(node: object, context: Mapping[str, Any] | None = None) -> None:
        if isinstance(node, list):
            for child in node:
                visit(child, context)
            return
        mapped = _mapping(node)
        if mapped is None:
            return
        local_context = dict(context or {})
        for key in (
            "item_id",
            "product_id",
            "product_name",
            "item_name",
            "sku_id",
            "seller_sku",
            "product_url",
        ):
            if mapped.get(key) is not None:
                local_context[key] = mapped[key]
        local_context.setdefault("item_id", default_item_id)

        for reviews_key in ("reviews", "review_list"):
            reviews = mapped.get(reviews_key)
            if isinstance(reviews, list):
                for review in reviews:
                    review_map = _mapping(review)
                    if review_map is not None:
                        result.append((review_map, dict(local_context)))
                return
        for key in ("products", "items", "review_info", "product_reviews", "list"):
            child = mapped.get(key)
            if isinstance(child, (list, Mapping)):
                visit(child, local_context)

    visit(data)
    return result


class LazadaReviewConnector:
    """Collect Guardian reviews from Lazada's seller-scoped review list API."""

    def __init__(
        self,
        credentials: LazadaCredentials,
        *,
        item_ids: Sequence[int | str] = (),
        discover_all_items: bool = False,
        owned_shop_authorized: bool = False,
        page_size: int = 100,
        max_pages_per_item: int = 10_000,
        lookback_days: int = 365,
        vietnamese_only: bool = True,
        base_url: str = "https://api.lazada.vn/rest",
        timeout_seconds: float = 30,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        if not isinstance(credentials, LazadaCredentials):
            raise MarketplaceCredentialsError("LazadaCredentials must be provided explicitly")
        if not owned_shop_authorized:
            raise MarketplaceAuthorizationError(
                "Guardian-owned Lazada seller authorization must be confirmed"
            )
        if not 1 <= page_size <= 100:
            raise ValueError("page_size must be between 1 and 100")
        if max_pages_per_item < 1:
            raise ValueError("max_pages_per_item must be at least one")
        if lookback_days < 1:
            raise ValueError("lookback_days must be at least one")
        self.credentials = credentials
        self.item_ids = _validate_item_ids(item_ids) if item_ids else ()
        if not self.item_ids and not discover_all_items:
            raise ValueError(
                "item_ids are required unless discover_all_items is enabled"
            )
        self.discover_all_items = discover_all_items
        self.page_size = page_size
        self.max_pages_per_item = max_pages_per_item
        self.lookback_days = lookback_days
        self.vietnamese_only = vietnamese_only
        self.base_url = _validate_official_base_url(
            base_url,
            allowed_hosts=frozenset({"api.lazada.vn"}),
            label="Lazada base_url",
        )
        self.timeout_seconds = timeout_seconds
        self.transport = transport
        self.clock = clock
        self.manifest = MarketplaceReconciliationManifest(
            platform="lazada",
            item_ids=self.item_ids,
            lookback_days=lookback_days,
            vietnamese_only=vietnamese_only,
            item_discovery_requested=discover_all_items,
        )

    async def _request_products(
        self, client: httpx.AsyncClient, *, offset: int
    ) -> dict[str, Any]:
        now = _clock_timestamp(self.clock)
        credentials = self.credentials
        params: dict[str, object] = {
            "app_key": credentials.app_key,
            "timestamp": int(now.timestamp() * 1_000),
            "sign_method": "sha256",
            "access_token": credentials.access_token,
            "filter": "all",
            "offset": offset,
            "limit": self.page_size,
        }
        params["sign"] = sign_lazada_request(
            api_path=LAZADA_GET_PRODUCTS_PATH,
            parameters=params,
            app_secret=credentials.app_secret,
        )
        try:
            response = await client.get(
                f"{self.base_url}{LAZADA_GET_PRODUCTS_PATH}", params=params
            )
        except httpx.HTTPError:
            raise MarketplaceAPIError("Lazada products API request failed") from None
        payload = _safe_json(response, "Lazada")
        code = payload.get("code")
        if code not in (None, "", 0, "0", "Success", "success"):
            raise MarketplaceAPIError("Lazada products API returned an application error")
        return payload

    async def _discover_item_ids(self, client: httpx.AsyncClient) -> tuple[str, ...]:
        discovered: list[str] = []
        offset = 0
        complete = False
        for _ in range(self.max_pages_per_item):
            payload = await self._request_products(client, offset=offset)
            self.manifest.item_discovery_pages += 1
            data = _mapping(payload.get("data")) or {}
            products = data.get("products")
            page_ids = _extract_product_item_ids(products or data)
            discovered.extend(page_ids)
            total = _as_int(
                _first(data, "total_products", "total_count", "total")
                or _first(payload, "total_products", "total_count", "total")
            )
            row_count = len(products) if isinstance(products, list) else len(page_ids)
            offset += row_count
            if row_count == 0 or row_count < self.page_size:
                complete = True
                break
            if total is not None and offset >= total:
                complete = True
                break
        else:
            self.manifest.item_discovery_warnings.append(
                "max products-list pages reached"
            )
        combined = tuple(dict.fromkeys([*self.item_ids, *discovered]))
        self.item_ids = combined
        self.manifest.item_ids = combined
        self.manifest.item_discovery_count = len(dict.fromkeys(discovered))
        self.manifest.item_discovery_complete = complete
        return combined

    async def _request(
        self, client: httpx.AsyncClient, *, item_id: str, current: int
    ) -> dict[str, Any]:
        now = _clock_timestamp(self.clock)
        credentials = self.credentials
        params: dict[str, object] = {
            "app_key": credentials.app_key,
            "timestamp": int(now.timestamp() * 1_000),
            "sign_method": "sha256",
            "access_token": credentials.access_token,
            "item_id": item_id,
            "current": current,
            "page_size": self.page_size,
        }
        params["sign"] = sign_lazada_request(
            api_path=LAZADA_REVIEW_LIST_PATH,
            parameters=params,
            app_secret=credentials.app_secret,
        )
        try:
            response = await client.get(
                f"{self.base_url}{LAZADA_REVIEW_LIST_PATH}", params=params
            )
        except httpx.HTTPError:
            raise MarketplaceAPIError("Lazada API request failed") from None
        payload = _safe_json(response, "Lazada")
        code = payload.get("code")
        if code not in (None, "", 0, "0", "Success", "success"):
            raise MarketplaceAPIError("Lazada API returned an application error")
        return payload

    async def collect(self, run: IngestionRun) -> AsyncIterator[RawFeedback]:
        start, end = _window(run, self.lookback_days)
        self.manifest = MarketplaceReconciliationManifest(
            platform="lazada",
            item_ids=self.item_ids,
            lookback_days=self.lookback_days,
            vietnamese_only=self.vietnamese_only,
            window_start=start.isoformat(),
            window_end=end.isoformat(),
            item_discovery_requested=self.discover_all_items,
        )
        async with httpx.AsyncClient(
            timeout=self.timeout_seconds,
            transport=self.transport,
            follow_redirects=False,
            trust_env=False,
        ) as client:
            if self.discover_all_items:
                await self._discover_item_ids(client)
            for item_id in self.item_ids:
                state = ItemReconciliation(item_id=item_id)
                self.manifest.items[item_id] = state
                seen_reviews: set[str] = set()
                current = 1
                for _ in range(self.max_pages_per_item):
                    payload = await self._request(
                        client, item_id=item_id, current=current
                    )
                    state.pages_requested += 1
                    data = payload.get("data")
                    data_map = _mapping(data) or {}
                    total = _reported_total(data_map)
                    if total is None:
                        total = _reported_total(payload)
                    if total is not None:
                        state.reported_total = max(state.reported_total or 0, total)
                    extracted = _extract_lazada_reviews(
                        data, default_item_id=item_id
                    )
                    state.rows_received += len(extracted)
                    for row, context in extracted:
                        row_item_id = str(
                            _first(row, "item_id", "product_id")
                            or _first(context, "item_id", "product_id")
                            or item_id
                        )
                        review_id = _review_identity("lazada", row_item_id, row)
                        dedupe_key = f"{row_item_id}\0{review_id}"
                        if dedupe_key in seen_reviews:
                            state.duplicates_removed += 1
                            continue
                        seen_reviews.add(dedupe_key)
                        state.unique_rows_received += 1
                        parsed = parse_timestamp(
                            _first(
                                row,
                                "create_time",
                                "created_at",
                                "review_date",
                                "date",
                            ),
                            timezone_hint=_BUSINESS_TIMEZONE,
                            observed_at=end,
                            quality_hint=OccurredAtQuality.EXACT,
                        )
                        disposition = _date_disposition(
                            parsed.value, start=start, end=end
                        )
                        if disposition == "missing":
                            state.records_missing_date += 1
                            continue
                        if disposition == "before":
                            state.records_before_window += 1
                            continue
                        if disposition == "after":
                            state.records_after_window += 1
                            continue
                        ratings = _first(row, "ratings", "rating_detail")
                        rating = _as_rating(
                            _first(row, "rating", "rating_star", "score", "ratings")
                        )
                        text, generated_text = _review_text(row, rating)
                        title_value = _first(row, "title", "review_title")
                        rating_only = generated_text and rating is not None
                        language_input = (
                            f"{title_value or ''}\n{text}"
                            if not generated_text or rating_only
                            else ""
                        )
                        language = resolve_language(language_input)
                        if (
                            self.vietnamese_only
                            and not rating_only
                            and language.language != "vi"
                        ):
                            state.records_language_filtered += 1
                            continue
                        media = _urls(
                            [
                                row.get("images"),
                                row.get("image_urls"),
                                row.get("videos"),
                                row.get("media"),
                                row.get("attachments"),
                            ]
                        )
                        reply = _seller_reply(
                            _first(row, "seller_reply", "reply", "shop_reply")
                        )
                        metadata: dict[str, Any] = {
                            "api_path": LAZADA_REVIEW_LIST_PATH,
                            "item_id": row_item_id,
                            "api_page": current,
                            "experience_subject": "retailer",
                            "text_is_generated_rating_summary": generated_text,
                            "rating_only": rating_only,
                            "marketplace_language_detection": {
                                "language": language.language,
                                "confidence": language.confidence,
                            },
                        }
                        if ratings is not None:
                            metadata["ratings"] = ratings
                        if reply is not None:
                            metadata["seller_reply"] = reply
                        for key in ("sku_id", "seller_sku", "variation"):
                            value = row.get(key, context.get(key))
                            if value is not None:
                                metadata[key] = value
                        state.records_emitted += 1
                        product_name = _first(row, "product_name", "item_name") or _first(
                            context, "product_name", "item_name"
                        )
                        source_url = _first(
                            row, "review_url", "product_url", "url"
                        ) or _first(context, "product_url")
                        author = _first(
                            row,
                            "author_id",
                            "user_id",
                            "buyer_id",
                            "reviewer_id",
                        )
                        yield RawFeedback(
                            source_external_id=review_id,
                            source_group=SourceGroup.MARKETPLACE,
                            source_platform="lazada",
                            visibility=Visibility.PUBLIC,
                            brand=Brand.GUARDIAN,
                            brand_candidates=[Brand.GUARDIAN],
                            occurred_at=parsed.value,
                            observed_at=end,
                            occurred_at_quality=parsed.quality,
                            original_timezone=parsed.original_timezone,
                            language=language.language,
                            language_confidence=language.confidence,
                            title=(
                                str(title_value).strip()
                                if title_value is not None
                                else None
                            ),
                            text=text,
                            rating=rating,
                            product_name=(
                                str(product_name).strip()
                                if product_name is not None
                                else None
                            ),
                            store="Guardian Official Store",
                            source_url=(
                                str(source_url).strip() if source_url is not None else None
                            ),
                            author_id=(str(author).strip() if author is not None else None),
                            media_urls=media,
                            metadata=metadata,
                        )

                    more = _as_bool(_first(data_map, "has_more", "more"))
                    if more is None and state.reported_total is not None:
                        more = state.unique_rows_received < state.reported_total
                    if more is None:
                        more = len(extracted) >= self.page_size
                    if not more:
                        state.pagination_complete = True
                        break
                    next_page = _as_int(_first(data_map, "next_page", "next_current"))
                    next_page = next_page if next_page is not None else current + 1
                    if next_page <= current:
                        state.warnings.append("provider returned a repeated page cursor")
                        break
                    state.cursor_chain_sha256.append(_hash_cursor(next_page))
                    current = next_page
                else:
                    state.warnings.append("max_pages_per_item reached")
                _finalize_reconciliation(state)


__all__ = [
    "LAZADA_GET_PRODUCTS_PATH",
    "LAZADA_REVIEW_LIST_PATH",
    "SHOPEE_GET_COMMENT_PATH",
    "SHOPEE_GET_ITEM_LIST_PATH",
    "ItemReconciliation",
    "LazadaCredentials",
    "LazadaReviewConnector",
    "MarketplaceAPIError",
    "MarketplaceAuthorizationError",
    "MarketplaceCredentialsError",
    "MarketplaceReconciliationManifest",
    "ShopeeCredentials",
    "ShopeeReviewConnector",
    "sign_lazada_request",
    "sign_shopee_request",
]
