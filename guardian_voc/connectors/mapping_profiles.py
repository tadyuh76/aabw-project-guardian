"""Checked field mappings for supported file-export families."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field, replace
from typing import Mapping

from guardian_voc.schemas.feedback import (
    Brand,
    ExperienceSubject,
    OccurredAtQuality,
    SourceGroup,
    Visibility,
)


def normalize_column_name(value: object) -> str:
    # Marketplace exports commonly alternate between Vietnamese headers with
    # diacritics and ASCII/transliterated headers.  Resolve both forms to the
    # same key (for example ``Mã đánh giá`` and ``ma_danh_gia``).
    text = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", str(value).strip())
    text = text.lower().translate(str.maketrans({"đ": "d"}))
    text = "".join(
        char
        for char in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(char)
    )
    return re.sub(r"[^a-z0-9]+", "_", text).strip("_")


COMMON_FIELDS: dict[str, tuple[str, ...]] = {
    "source_external_id": (
        "source_external_id",
        "review_id",
        "rating_id",
        "comment_id",
        "cmtid",
        "review_no",
        "id",
        "feedback_id",
        "ticket_id",
        "call_id",
        "chat_id",
        "ma_danh_gia",
    ),
    "title": ("title", "subject", "review_title", "tieu_de"),
    "text": (
        "text",
        "review",
        "review_text",
        "review_content",
        "comment",
        "comments",
        "content",
        "body",
        "message",
        "transcript",
        "description",
        "feedback",
        "noi_dung",
        "noi_dung_danh_gia",
        "binh_luan",
        "danh_gia",
    ),
    "occurred_at": (
        "occurred_at",
        "created_at",
        "create_time",
        "ctime",
        "review_date",
        "date",
        "timestamp",
        "submitted_at",
        "submit_time",
        "published_at",
        "ngay_danh_gia",
        "thoi_gian_danh_gia",
        "thoi_gian",
    ),
    "observed_at": (
        "observed_at",
        "collected_at",
        "exported_at",
        "crawled_at",
    ),
    "language": ("language", "lang", "locale", "ngon_ngu"),
    "language_confidence": ("language_confidence", "lang_confidence"),
    "rating": (
        "rating",
        "rating_star",
        "star",
        "stars",
        "star_rating",
        "score",
        "product_rating",
        "sao",
        "so_sao",
    ),
    "product_id": (
        "product_id",
        "item_id",
        "sku_id",
        "product_sku",
        "sku",
        "ma_san_pham",
    ),
    "product_name": (
        "product_name",
        "product",
        "item_name",
        "sku_name",
        "product_title",
        "item_title",
        "ten_san_pham",
    ),
    "product_category": (
        "product_category",
        "category",
        "category_name",
        "nganh_hang",
    ),
    "region": ("region", "province", "city", "khu_vuc", "tinh_thanh"),
    "shop_id": ("shop_id", "seller_id", "merchant_id", "store_id"),
    "store": (
        "store",
        "store_name",
        "shop_name",
        "seller_name",
        "merchant_name",
        "branch",
        "location",
        "cua_hang",
        "chi_nhanh",
    ),
    "source_url": (
        "source_url",
        "review_url",
        "permalink",
        "product_url",
        "item_url",
        "url",
        "link",
        "duong_dan",
    ),
    "author_id": (
        "author_id", "user_id", "customer_id", "reviewer_id", "buyer_id",
        "reviewer_name", "reviewer", "buyer_name", "customer_name", "user_name",
        "ten_nguoi_danh_gia", "ten_nguoi_mua",
    ),
    "conversation_id": (
        "conversation_id",
        "thread_id",
        "chat_id",
        "ticket_id",
        "call_id",
        "case_id",
    ),
    "message_count": ("message_count", "messages", "num_messages"),
    "media_urls": (
        "media_urls",
        "attachments",
        "attachment_urls",
        "image_urls",
        "images",
        "video_urls",
        "videos",
    ),
    # Seller/shop responses are contextual evidence for the customer review,
    # not independent customer feedback units.
    "seller_reply": (
        "seller_reply",
        "seller_response",
        "shop_reply",
        "reply",
        "reply_content",
        "merchant_reply",
        "phan_hoi_cua_shop",
        "phan_hoi_nguoi_ban",
    ),
    "seller_reply_at": (
        "seller_reply_at",
        "seller_response_at",
        "shop_reply_at",
        "reply_time",
        "reply_date",
        "thoi_gian_phan_hoi",
    ),
    "seller_reply_id": ("seller_reply_id", "shop_reply_id", "reply_id"),
    "sender": ("sender", "role", "speaker", "from", "nguoi_gui"),
    "message_at": ("message_at", "sent_at", "message_time", "timestamp", "thoi_gian"),
    "brand": ("brand", "retailer", "merchant", "thuong_hieu"),
    "visibility": ("visibility", "scope"),
    "source_platform": ("source_platform", "platform", "channel"),
    "source_group": ("source_group",),
    "brand_candidates": ("brand_candidates", "candidate_brands"),
    "original_timezone": ("original_timezone", "timezone", "time_zone"),
    "occurred_at_quality": ("occurred_at_quality", "date_quality"),
    "is_synthetic": ("is_synthetic", "synthetic"),
    "metadata": ("metadata",),
}


@dataclass(frozen=True)
class MappingProfile:
    name: str
    source_group: SourceGroup
    source_platform: str
    visibility: Visibility
    fixed_brand: Brand | None
    brand_candidates: tuple[Brand, ...]
    source_name: str
    fields: Mapping[str, tuple[str, ...]] = field(default_factory=lambda: COMMON_FIELDS)
    timezone: str = "Asia/Ho_Chi_Minh"
    occurred_at_quality: OccurredAtQuality = OccurredAtQuality.PARSED
    trusted_language: bool = False
    experience_subject: ExperienceSubject = ExperienceSubject.RETAILER
    group_by_conversation: bool = False

    def resolve_columns(self, columns: list[str] | tuple[str, ...]) -> dict[str, str]:
        normalized = {normalize_column_name(column): column for column in columns}
        resolved: dict[str, str] = {}
        for canonical, candidates in self.fields.items():
            for candidate in candidates:
                match = normalized.get(normalize_column_name(candidate))
                if match is not None:
                    resolved[canonical] = match
                    break
        return resolved

    def with_overrides(self, **changes: object) -> "MappingProfile":
        return replace(self, **changes)

    @classmethod
    def generic(
        cls,
        *,
        name: str,
        source_name: str,
        source_group: SourceGroup,
        source_platform: str,
        visibility: Visibility,
        mapping: Mapping[str, str | tuple[str, ...]],
        fixed_brand: Brand | None = None,
        brand_candidates: tuple[Brand, ...] = (),
        timezone: str = "Asia/Ho_Chi_Minh",
        trusted_language: bool = False,
        group_by_conversation: bool = False,
    ) -> "MappingProfile":
        fields = {
            key: (value,) if isinstance(value, str) else tuple(value)
            for key, value in mapping.items()
        }
        return cls(
            name=name,
            source_name=source_name,
            source_group=source_group,
            source_platform=source_platform,
            visibility=visibility,
            fixed_brand=fixed_brand,
            brand_candidates=brand_candidates,
            fields=fields,
            timezone=timezone,
            trusted_language=trusted_language,
            group_by_conversation=group_by_conversation,
        )


def _profile(
    name: str,
    platform: str,
    *,
    brand: Brand = Brand.GUARDIAN,
    source_group: SourceGroup = SourceGroup.MARKETPLACE,
    visibility: Visibility = Visibility.PUBLIC,
    group_by_conversation: bool = False,
) -> MappingProfile:
    return MappingProfile(
        name=name,
        source_name=name,
        source_group=source_group,
        source_platform=platform,
        visibility=visibility,
        fixed_brand=brand,
        brand_candidates=(brand,),
        group_by_conversation=group_by_conversation,
    )


_PROFILES = {
    profile.name: profile
    for profile in (
        MappingProfile(
            name="generic",
            source_name="generic",
            source_group=SourceGroup.MARKETPLACE,
            source_platform="generic",
            visibility=Visibility.PUBLIC,
            fixed_brand=None,
            brand_candidates=(),
            experience_subject=ExperienceSubject.UNKNOWN,
        ),
        _profile("shopee", "shopee"),
        _profile("lazada", "lazada"),
        _profile("tiktok_shop", "tiktok_shop"),
        _profile("grabmart", "grabmart"),
        _profile(
            "guardian_ecommerce",
            "guardian_ecommerce",
            source_group=SourceGroup.OWNED,
            visibility=Visibility.OWNED,
        ),
        _profile(
            "hasaki_owned",
            "hasaki_ecommerce",
            brand=Brand.HASAKI,
            source_group=SourceGroup.OWNED,
            visibility=Visibility.OWNED,
        ),
        _profile(
            "watsons_owned",
            "watsons_ecommerce",
            brand=Brand.WATSONS,
            source_group=SourceGroup.OWNED,
            visibility=Visibility.OWNED,
        ),
        _profile(
            "customer_service_ticket",
            "ticket",
            source_group=SourceGroup.CUSTOMER_SERVICE,
            visibility=Visibility.OWNED,
        ),
        _profile(
            "live_chat",
            "live_chat",
            source_group=SourceGroup.CUSTOMER_SERVICE,
            visibility=Visibility.OWNED,
            group_by_conversation=True,
        ),
        _profile(
            "call_transcript",
            "call_center",
            source_group=SourceGroup.CUSTOMER_SERVICE,
            visibility=Visibility.OWNED,
            group_by_conversation=True,
        ),
        _profile("hasaki", "marketplace", brand=Brand.HASAKI),
        _profile("hasaki_shopee", "shopee", brand=Brand.HASAKI),
        _profile("hasaki_lazada", "lazada", brand=Brand.HASAKI),
        _profile("hasaki_tiktok_shop", "tiktok_shop", brand=Brand.HASAKI),
        _profile("watsons", "marketplace", brand=Brand.WATSONS),
        _profile("watsons_shopee", "shopee", brand=Brand.WATSONS),
        _profile("watsons_lazada", "lazada", brand=Brand.WATSONS),
        _profile("watsons_tiktok_shop", "tiktok_shop", brand=Brand.WATSONS),
    )
}

_ALIASES = {
    "tiktok": "tiktok_shop",
    "guardian_owned": "guardian_ecommerce",
    "guardian_official": "guardian_ecommerce",
    "guardian_official_page": "guardian_ecommerce",
    "ticket": "customer_service_ticket",
    "chat": "live_chat",
    "call": "call_transcript",
}


def get_profile(name: str) -> MappingProfile:
    key = normalize_column_name(name)
    key = _ALIASES.get(key, key)
    try:
        return _PROFILES[key]
    except KeyError as exc:
        available = ", ".join(sorted(_PROFILES))
        raise KeyError(f"unknown mapping profile {name!r}; choose one of: {available}") from exc


def list_profiles() -> tuple[str, ...]:
    return tuple(sorted(_PROFILES))


__all__ = [
    "COMMON_FIELDS",
    "MappingProfile",
    "get_profile",
    "list_profiles",
    "normalize_column_name",
]
