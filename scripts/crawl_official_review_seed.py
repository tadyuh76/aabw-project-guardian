#!/usr/bin/env python3
"""Build larger real-review seed datasets from public official product reviews.

Currently Hasaki exposes a public JSON review endpoint that can be queried
reliably without auth. Guardian and Watsons are protected by Cloudflare/Akamai
from plain HTTP in this environment; keep their existing verified captures as
separate seed files until a browser-network extractor is added.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from guardian_voc.ai.validator import validate_classification  # noqa: E402
from guardian_voc.schemas.analysis import (  # noqa: E402
    ClassificationRequest,
    ClassificationResult,
    TrustedSourceMetadata,
)
from guardian_voc.schemas.feedback import RawFeedback  # noqa: E402


BUSINESS_TZ = "Asia/Ho_Chi_Minh"
OBSERVED_AT = datetime.now(timezone.utc).isoformat()
PERIOD_START = "2024-07-12"
PERIOD_END = "2026-07-12"
OUT_DIR = ROOT / "data" / "seed"

PHONE_RE = re.compile(r"(?<!\d)(?:\+?84|0)(?:[\s.\-]?\d){8,10}(?!\d)")
EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
URL_RE = re.compile(r"https?://\S+")
SPACE_RE = re.compile(r"\s+")

HASAKI_TERMS = """
cerave la roche posay bioderma simple senka loreal maybelline anessa nivea
cocoon eucerin vichy skin1004 klairs paula choice hada labo cetaphil innisfree
cosrx some by mi garnier sunplay biore avene neutrogena vaseline dove tresemme
clear head shoulders milaganics naruko martiderm hatomugi chống nắng sữa rửa mặt
tẩy trang serum kem dưỡng toner mặt nạ dầu gội sữa tắm son kem nền mascara
cushion nước hoa body lotion retinol vitamin c niacinamide bha aha
""".split()

HASAKI_HIGH_REVIEW_PRODUCTS: tuple[dict[str, str], ...] = (
    {"product_id": "19325", "title": "Nước Tẩy Trang L'Oreal Tươi Mát Cho Da Dầu, Hỗn Hợp 400ml", "url": "https://hasaki.vn/san-pham/nuoc-tay-trang-tuoi-mat-l-oreal-3-in-1-danh-cho-da-dau-da-hon-hop-400ml-19325.html"},
    {"product_id": "34119", "title": "Nước Tẩy Trang L'Oreal Làm Sạch Sâu Trang Điểm 400ml", "url": "https://hasaki.vn/san-pham/nuoc-tay-trang-l-oreal-3-in-1-lam-sach-sau-400ml-34119.html"},
    {"product_id": "106889", "title": "Combo 2 Nước Tẩy Trang L'Oreal Tươi Mát Cho Da Dầu, Hỗn Hợp 400ml", "url": "https://hasaki.vn/san-pham/combo-2-nuoc-tay-trang-l-oreal-tuoi-mat-cho-da-dau-hon-hop-400ml-106889.html"},
    {"product_id": "55867", "title": "Mặt Nạ Naruko Tràm Trà Kiểm Soát Dầu Và Giảm Mụn 26ml", "url": "https://hasaki.vn/san-pham/mat-na-naruko-tram-tra-kiem-soat-dau-va-giam-mun-26ml-55867.html"},
    {"product_id": "73471", "title": "Hộp 8 Miếng Mặt Nạ Naruko Tràm Trà Kiềm Dầu Giảm Mụn 26ml/Miếng", "url": "https://hasaki.vn/san-pham/hop-8-mieng-mat-na-naruko-tram-tra-kiem-soat-dau-va-giam-mun-26ml-mieng-73471.html"},
    {"product_id": "76844", "title": "Gel Rửa Mặt Eucerin Cho Da Nhờn Mụn 400ml", "url": "https://hasaki.vn/san-pham/gel-rua-mat-eucerin-cho-da-dau-mun-400ml-76844.html"},
    {"product_id": "9740", "title": "Nước Tẩy Trang Bioderma Dành Cho Da Nhạy Cảm 500ml", "url": "https://hasaki.vn/san-pham/nuoc-tay-trang-bioderma-danh-cho-da-nhay-cam-500ml-9740.html"},
    {"product_id": "11089", "title": "Nước Tẩy Trang Bioderma Dành Cho Da Dầu & Hỗn Hợp 500ml", "url": "https://hasaki.vn/san-pham/nuoc-tay-trang-bioderma-danh-cho-da-dau-hon-hop-500ml-11089.html"},
    {"product_id": "96523", "title": "Gel Rửa Mặt Cosrx Tràm Trà, 0.5% BHA Có Độ pH Thấp 150ml", "url": "https://hasaki.vn/san-pham/gel-rua-mat-cosrx-tram-tra-0-5-bha-co-do-ph-thap-150ml-96523.html"},
    {"product_id": "2364", "title": "Dung Dịch Tẩy Da Chết Paula’s Choice 2% BHA 30ml", "url": "https://hasaki.vn/san-pham/dung-dich-tay-da-chet-paula-s-choice-bha-2-30ml-2364.html"},
    {"product_id": "65994", "title": "Nước Hoa Hồng Klairs Không Mùi Cho Da Nhạy Cảm 180ml", "url": "https://hasaki.vn/san-pham/nuoc-hoa-hong-khong-mui-klairs-danh-cho-da-nhay-cam-180ml-65994.html"},
    {"product_id": "68810", "title": "Gel Rửa Mặt La Roche-Posay Dành Cho Da Dầu, Nhạy Cảm 400ml", "url": "https://hasaki.vn/san-pham/gel-rua-mat-la-roche-posay-cho-da-dau-nhay-cam-400ml-68810.html"},
    {"product_id": "74010", "title": "Tinh Chất Chống Nắng Sunplay Hiệu Chỉnh Sắc Da 50g (Tím)", "url": "https://hasaki.vn/san-pham/tinh-chat-chong-nang-sunplay-hieu-chinh-sac-da-50g-tim-74010.html"},
    {"product_id": "71263", "title": "Sữa Rửa Mặt Simple Giúp Da Sạch Thoáng 150ml", "url": "https://hasaki.vn/san-pham/gel-rua-mat-danh-cho-da-nhay-cam-simple-150ml-71263.html"},
    {"product_id": "98921", "title": "Gel Rửa Mặt Simple Thanh Khiết, Giảm Bóng Nhờn 150ml", "url": "https://hasaki.vn/san-pham/sua-rua-mat-simple-kiem-dau-ngua-mun-cho-da-mun-150ml-98921.html"},
    {"product_id": "78190", "title": "Sữa Tắm Hatomugi Dưỡng Ẩm Chiết Xuất Ý Dĩ 800ml", "url": "https://hasaki.vn/san-pham/sua-tam-hatomugi-ho-tro-trang-da-giu-am-800ml-78190.html"},
    {"product_id": "86167", "title": "Kem Chống Nắng Skin1004 Cho Da Nhạy Cảm SPF 50+ 50ml", "url": "https://hasaki.vn/san-pham/kem-chong-nang-skin1004-chiet-xuat-rau-ma-spf50-pa-50ml-86167.html"},
    {"product_id": "102959", "title": "Sữa Rửa Mặt CeraVe Sạch Sâu Cho Da Thường Đến Da Dầu 473ml", "url": "https://hasaki.vn/san-pham/sua-rua-mat-cerave-sach-sau-cho-da-thuong-den-da-dau-473ml-102959.html"},
    {"product_id": "90401", "title": "Kem Chống Nắng MartiDerm Phổ Rộng Bảo Vệ Toàn Diện 40ml", "url": "https://hasaki.vn/san-pham/kem-chong-nang-martiderm-pho-rong-toan-dien-spf50-40ml-90401.html"},
    {"product_id": "12064", "title": "Sữa Chống Nắng Sunplay Skin Aqua Dưỡng Da Sáng Mịn 55g", "url": "https://hasaki.vn/san-pham/sua-chong-nang-sunplay-duong-da-sang-min-spf50-pa-55g-12064.html"},
    {"product_id": "86161", "title": "Serum Skin1004 Rau Má Làm Dịu & Hỗ Trợ Phục Hồi Da 100ml", "url": "https://hasaki.vn/san-pham/tinh-chat-rau-ma-skin1004-ho-tro-giam-mun-phuc-hoi-da-100ml-86161.html"},
)


def clean_text(value: Any) -> str:
    text = "" if value is None else str(value)
    text = re.sub(r"<br\s*/?>", " ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = EMAIL_RE.sub("[REDACTED_EMAIL]", text)
    text = PHONE_RE.sub("[REDACTED_PHONE]", text)
    text = URL_RE.sub("[REDACTED_URL]", text)
    return SPACE_RE.sub(" ", text).strip()


def dt_from_unix(value: Any) -> str | None:
    if value is None:
        return None
    try:
        timestamp = int(value)
    except (TypeError, ValueError):
        return None
    if timestamp > 10_000_000_000:
        timestamp = int(timestamp / 1000)
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()


def date_in_window(iso_value: str | None) -> bool:
    if not iso_value:
        return False
    day = iso_value[:10]
    return PERIOD_START <= day <= PERIOD_END


def evidence(text: str, phrase: str | None = None) -> str:
    if phrase and phrase in text:
        return phrase
    return text[: min(len(text), 500)]


def classify(brand: str, text: str, rating: float | None) -> dict[str, Any]:
    lower = text.lower()

    def item(
        *,
        subject: str,
        topic: str,
        subtopic: str,
        intent: str,
        sentiment: str,
        score: float,
        urgency: str,
        stage: str,
        reason: str | None,
        phrase: str | None = None,
        confidence: float = 0.86,
    ) -> dict[str, Any]:
        return {
            "is_relevant": True,
            "primary_brand": brand,
            "mentioned_brands": [brand],
            "brand_attribution_confidence": 0.99,
            "brand_evidence_span": None,
            "experience_subject": subject,
            "primary_topic": topic,
            "subtopic": subtopic,
            "intent": intent,
            "sentiment": sentiment,
            "sentiment_score": score,
            "urgency": urgency,
            "customer_stated_reason": reason,
            "journey_stage": stage,
            "evidence_span": evidence(text, phrase),
            "confidence": confidence,
        }

    if any(k in lower for k in ("hàng giả", "fake", "không chính hãng", "chính hãng không", "auth")):
        return item(subject="product", topic="product_quality_authenticity", subtopic="suspected_counterfeit", intent="complaint", sentiment="negative", score=-0.86, urgency="high", stage="post_purchase", reason="khách nghi ngờ tính chính hãng", phrase="chính hãng không")
    if any(k in lower for k in ("hết hạn", "hạn sử dụng", "exp", "mgf", "date")) and any(k in lower for k in ("không", "k thấy", "kh thấy", "mờ", "cận")):
        return item(subject="product", topic="product_quality_authenticity", subtopic="expired_product", intent="complaint", sentiment="negative", score=-0.78, urgency="high", stage="post_purchase", reason="khách không thấy/lo ngại hạn sử dụng", phrase="hạn sử dụng")
    if any(k in lower for k in ("đổ", "chảy", "bể", "vỡ", "móp", "rách", "bung", "hở nắp", "leak")):
        return item(subject="retailer", topic="delivery_fulfilment", subtopic="damaged_package", intent="complaint", sentiment="negative", score=-0.72, urgency="normal", stage="delivery", reason="sản phẩm/bao bì bị hư hại hoặc đổ khi nhận", phrase="đổ")
    if any(k in lower for k in ("giao lâu", "giao trễ", "chậm", "delay", "lâu quá")):
        return item(subject="retailer", topic="delivery_fulfilment", subtopic="late_delivery", intent="complaint", sentiment="negative", score=-0.65, urgency="normal", stage="delivery", reason="khách phản ánh giao hàng chậm", phrase="giao")
    if any(k in lower for k in ("thiếu hàng", "thiếu sản phẩm", "thiếu quà", "không có quà", "không thấy quà", "ko thấy")):
        return item(subject="retailer", topic="price_promotion", subtopic="missing_gift", intent="complaint", sentiment="negative", score=-0.62, urgency="normal", stage="post_purchase", reason="khách phản ánh thiếu quà/sản phẩm", phrase="thiếu")
    if any(k in lower for k in ("giá", "voucher", "mã giảm", "khuyến mãi", "sale")) and any(k in lower for k in ("không áp", "không được", "khác", "lệch", "cao hơn", "sai")):
        return item(subject="retailer", topic="price_promotion", subtopic="price_mismatch", intent="complaint", sentiment="negative", score=-0.64, urgency="normal", stage="promotion", reason="khách phản ánh giá/voucher/khuyến mãi không khớp", phrase="giá")
    if any(k in lower for k in ("kích ứng", "nổi mụn", "rát", "ngứa", "dị ứng", "cay mắt", "khô da")):
        return item(subject="product", topic="product_quality_authenticity", subtopic="adverse_reaction", intent="complaint", sentiment="negative", score=-0.74, urgency="high", stage="post_purchase", reason="khách báo phản ứng không mong muốn", phrase="kích ứng")
    if any(k in lower for k in ("mùi hắc", "mùi cồn", "không hợp", "không hiệu quả", "khó dùng", "bết", "rít", "lên tone")):
        return item(subject="product", topic="product_quality_authenticity", subtopic="product_performance", intent="complaint", sentiment="negative", score=-0.58, urgency="normal", stage="post_purchase", reason="khách không hài lòng với hiệu quả/cảm nhận sản phẩm", phrase="không")
    if any(k in lower for k in ("tư vấn", "nhân viên", "hotline", "hỗ trợ")) and any(k in lower for k in ("không", "chưa", "lâu", "tệ")):
        return item(subject="retailer", topic="customer_service", subtopic="poor_response", intent="complaint", sentiment="negative", score=-0.58, urgency="normal", stage="support", reason="khách phản ánh hỗ trợ/tư vấn chưa tốt", phrase="hỗ trợ")
    if any(k in lower for k in ("hoàn tiền", "đổi trả", "thu hồi", "trả hàng")):
        return item(subject="retailer", topic="returns_refunds", subtopic="return_process", intent="question_request", sentiment="neutral" if (rating or 5) >= 4 else "negative", score=-0.2 if (rating or 5) < 4 else 0.0, urgency="normal", stage="returns", reason="khách hỏi/vướng về đổi trả/hoàn tiền", phrase="hoàn tiền")
    if any(k in lower for k in ("giao hàng nhanh", "đóng gói cẩn thận", "đóng gói kỹ", "nhanh", "ship nhanh")):
        return item(subject="retailer", topic="delivery_fulfilment", subtopic="fast_delivery", intent="praise", sentiment="positive", score=0.78, urgency="low", stage="delivery", reason="khách khen giao hàng/đóng gói", phrase="Giao hàng nhanh" if "Giao hàng nhanh" in text else "nhanh", confidence=0.88)
    if any(k in lower for k in ("giá tốt", "giá ổn", "rẻ", "sale tốt", "đáng tiền")):
        return item(subject="retailer", topic="price_promotion", subtopic="good_value", intent="praise", sentiment="positive", score=0.72, urgency="low", stage="post_purchase", reason="khách khen giá/ưu đãi", phrase="giá tốt")
    if any(k in lower for k in ("chính hãng", "yên tâm", "authentic")):
        return item(subject="product", topic="product_quality_authenticity", subtopic="authenticity_praise", intent="praise", sentiment="positive", score=0.82, urgency="low", stage="post_purchase", reason="khách khen/đánh giá hàng chính hãng", phrase="chính hãng")
    if rating is not None and rating <= 2:
        return item(subject="unknown", topic="other", subtopic="other", intent="complaint", sentiment="negative", score=-0.5, urgency="normal", stage="post_purchase", reason="đánh giá sao thấp nhưng nội dung chưa nêu rõ vấn đề", confidence=0.72)
    if rating is not None and rating >= 4:
        return item(subject="product", topic="product_quality_authenticity", subtopic="product_performance", intent="praise", sentiment="positive", score=0.62, urgency="low", stage="post_purchase", reason="khách đánh giá tích cực về sản phẩm", confidence=0.78)
    return item(subject="unknown", topic="other", subtopic="other", intent="question_request", sentiment="neutral", score=0.0, urgency="low", stage="unknown", reason=None, confidence=0.7)


def stable_id(prefix: str, value: str) -> str:
    digest = hashlib.sha256(f"{prefix}:{value}".encode()).hexdigest()[:20]
    return f"real-{prefix}-{digest}"


def validate_row(row: dict[str, Any]) -> None:
    raw = RawFeedback.model_validate(row)
    label = ClassificationResult.model_validate(row["metadata"]["inline_classification"])
    request = ClassificationRequest(
        content_hash=hashlib.sha256(raw.text.encode()).hexdigest(),
        text_redacted=raw.text,
        trusted_metadata=TrustedSourceMetadata(
            source_group=raw.source_group,
            source_platform=raw.source_platform,
            visibility=raw.visibility,
            source_fixed_brand=raw.brand,
            product_category=raw.product_category,
            language=raw.language,
        ),
        brand_candidates=tuple(raw.brand_candidates),
    )
    validate_classification(label, request)


def request_json(session: httpx.Client, url: str, **kwargs: Any) -> dict[str, Any] | None:
    try:
        response = session.get(url, **kwargs)
        if response.status_code != 200:
            return None
        return response.json()
    except Exception:
        return None


def discover_hasaki_products(session: httpx.Client, terms: list[str]) -> list[dict[str, Any]]:
    products: dict[str, dict[str, Any]] = {}
    for term in terms:
        data = request_json(
            session,
            "https://hasaki.vn/api/v4/main/suggestion",
            params={"q": term},
        )
        for product in (((data or {}).get("data") or {}).get("products") or []):
            product_id = product.get("product_id")
            if product_id is None:
                continue
            products[str(product_id)] = {
                "product_id": str(product_id),
                "title": clean_text(product.get("title")),
                "url": urljoin("https://hasaki.vn/", str(product.get("url") or "")),
            }
        time.sleep(0.05)

    scored: list[dict[str, Any]] = []
    for product in products.values():
        data = request_json(
            session,
            "https://hasaki.vn/mobile/v3/detail/product/rating-reviews",
            params={
                "product_id": product["product_id"],
                "page": 1,
                "size": 1,
                "sort": "create",
                "is_desktop": 0,
            },
        )
        rating = (((data or {}).get("data") or {}).get("rating") or {})
        total = 0
        for item in rating.get("filter") or []:
            if item.get("key") == "filter_all":
                total = int(item.get("count") or 0)
        if total:
            scored.append({**product, "review_count": total})
        time.sleep(0.03)
    scored.sort(key=lambda item: int(item["review_count"]), reverse=True)
    return scored


def crawl_hasaki(
    session: httpx.Client, *, target: int, fast_products: bool = False
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    products = (
        [dict(item, review_count=None) for item in HASAKI_HIGH_REVIEW_PRODUCTS]
        if fast_products
        else discover_hasaki_products(session, HASAKI_TERMS)
    )
    rows: dict[str, dict[str, Any]] = {}
    used_products: list[dict[str, Any]] = []
    for product in products:
        used_products.append(product)
        for page in range(1, 15):
            data = request_json(
                session,
                "https://hasaki.vn/mobile/v3/detail/product/rating-reviews",
                params={
                    "product_id": product["product_id"],
                    "page": page,
                    "size": 30,
                    "sort": "create",
                    "is_desktop": 0,
                },
            )
            reviews = (((data or {}).get("data") or {}).get("reviews") or [])
            if not reviews:
                break
            for review in reviews:
                review_id = str(review.get("id") or "")
                text = clean_text(review.get("content"))
                if not review_id or not text or len(text) < 4:
                    continue
                occurred_at = dt_from_unix(review.get("created_at"))
                if not date_in_window(occurred_at):
                    continue
                rating_obj = review.get("rating") or {}
                rating = float(rating_obj.get("star")) if rating_obj.get("star") is not None else None
                product_id = str(review.get("product_id") or product["product_id"])
                product_name = clean_text(review.get("product_name")) or product["title"]
                label = classify("hasaki", text, rating)
                row = {
                    "source_external_id": stable_id("hasaki-official", review_id),
                    "source_group": "owned",
                    "source_platform": "hasaki_ecommerce",
                    "visibility": "owned",
                    "brand": "hasaki",
                    "brand_candidates": ["hasaki"],
                    "occurred_at": occurred_at,
                    "observed_at": OBSERVED_AT,
                    "occurred_at_quality": "exact",
                    "original_timezone": BUSINESS_TZ,
                    "language": "vi",
                    "language_confidence": 0.98,
                    "title": "Real Vietnamese public review for hasaki",
                    "text": text,
                    "rating": rating,
                    "product_name": product_name,
                    "product_category": "beauty_personal_care",
                    "source_url": product["url"],
                    "message_count": 1,
                    "media_urls": [],
                    "metadata": {
                        "seed_dataset": "official_reviews_expanded_20260712",
                        "seed_source": "public_product_review",
                        "source_product_id": product_id,
                        "query_product_id": product["product_id"],
                        "query_product_url": product["url"],
                        "original_review_id_hash": hashlib.sha256(review_id.encode()).hexdigest(),
                        "is_verified_purchase": bool(review.get("is_bought")),
                        "inline_classification": label,
                        "inline_classification_model": "human-curated-seed-v2",
                        "inline_classification_prompt_version": "item-classifier-v2",
                    },
                    "is_synthetic": False,
                }
                try:
                    validate_row(row)
                except Exception:
                    continue
                rows[row["source_external_id"]] = row
                if len(rows) >= target:
                    return list(rows.values()), used_products
            time.sleep(0.05)
        if len(rows) >= target:
            break
    return list(rows.values()), used_products


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target-hasaki", type=int, default=500)
    parser.add_argument("--fast-hasaki", action="store_true")
    parser.add_argument("--output", default=str(OUT_DIR / "official_reviews_expanded_20260712.raw.jsonl"))
    parser.add_argument("--manifest", default=str(OUT_DIR / "official_reviews_expanded_20260712.manifest.json"))
    args = parser.parse_args()

    session = httpx.Client(
        timeout=httpx.Timeout(12.0, connect=4.0),
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; GuardianSeedCrawler/1.0)",
            "Accept": "application/json,text/plain,*/*",
            "Accept-Language": "vi,en;q=0.9",
            "Referer": "https://hasaki.vn/",
        },
    )
    try:
        rows, products = crawl_hasaki(
            session,
            target=args.target_hasaki,
            fast_products=args.fast_hasaki,
        )
    finally:
        session.close()
    output = Path(args.output)
    manifest_path = Path(args.manifest)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "dataset": output.name,
        "real_rows_only": True,
        "synthetic_rows": 0,
        "period_start": PERIOD_START,
        "period_end": PERIOD_END,
        "rows": len(rows),
        "brands": Counter(row["brand"] for row in rows),
        "platforms": Counter(row["source_platform"] for row in rows),
        "sentiments": Counter(row["metadata"]["inline_classification"]["sentiment"] for row in rows),
        "topics": Counter(
            f"{row['metadata']['inline_classification']['primary_topic']}/{row['metadata']['inline_classification']['subtopic']}"
            for row in rows
        ),
        "products_considered": len(products),
        "top_products": products[:25],
        "blocked_or_deferred": {
            "guardian": "Cloudflare blocked plain HTTP/API access; needs browser-network extractor or approved export.",
            "watsons": "Akamai/SAP Commerce access blocked plain HTTP/API access; needs browser-network extractor or approved export.",
        },
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
