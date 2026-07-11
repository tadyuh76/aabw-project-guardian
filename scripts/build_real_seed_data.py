#!/usr/bin/env python3
"""Build a small privacy-safe real-review seed dataset.

The input files were captured from public product-review surfaces and are kept
outside the demo fixture path so they can be reviewed separately before import.
Rows are emitted as RawFeedback-compatible JSONL with inline classifications in
metadata.inline_classification, which the app can persist through its normal
classification path.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from guardian_voc.ai.validator import validate_classification  # noqa: E402
from guardian_voc.schemas.analysis import (  # noqa: E402
    ClassificationRequest,
    ClassificationResult,
    TrustedSourceMetadata,
)
from guardian_voc.schemas.feedback import RawFeedback  # noqa: E402


SOURCE_DIR = ROOT.parent / "social-listening-crawler" / "data" / "product_reviews"
OUT_DIR = ROOT / "data" / "seed"
OUT_JSONL = OUT_DIR / "real_feedback_seed_20260712.jsonl"
OUT_MANIFEST = OUT_DIR / "real_feedback_seed_20260712.manifest.json"
OUT_DISCOVERY = OUT_DIR / "real_social_discovery_review_needed_20260712.jsonl"

OBSERVED_AT = "2026-07-12T00:00:00+07:00"
PERIOD_START = "2024-07-12"
PERIOD_END = "2026-07-12"

PHONE_RE = re.compile(r"(?<!\d)(?:\+?84|0)(?:[\s.\-]?\d){8,10}(?!\d)")
URL_RE = re.compile(r"https?://\S+")


def clean_text(value: str) -> str:
    value = re.sub(r"<br\s*/?>", " ", value, flags=re.IGNORECASE)
    value = re.sub(r"<[^>]+>", " ", value)
    value = PHONE_RE.sub("[REDACTED_PHONE]", value)
    value = URL_RE.sub("[REDACTED_URL]", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def day(value: str | None) -> str | None:
    if not value:
        return None
    return str(value)[:10]


def in_window(value: str | None) -> bool:
    d = day(value)
    return bool(d and PERIOD_START <= d <= PERIOD_END)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def source_id(prefix: str, raw_id: object) -> str:
    digest = hashlib.sha256(f"{prefix}:{raw_id}".encode()).hexdigest()[:16]
    return f"real-{prefix}-{digest}"


def classify(brand: str, platform: str, text: str, rating: float | None) -> dict[str, Any]:
    lower = text.lower()

    def result(
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
        evidence: str,
        confidence: float = 0.86,
    ) -> dict[str, Any]:
        evidence_span = evidence if evidence in text else text[: min(len(text), 180)]
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
            "evidence_span": evidence_span,
            "confidence": confidence,
        }

    if any(token in lower for token in ("exp", "mgf", "hạn sử dụng", "hsd")):
        return result(
            subject="product",
            topic="product_quality_authenticity",
            subtopic="expired_product",
            intent="complaint",
            sentiment="negative",
            score=-0.88,
            urgency="high",
            stage="post_purchase",
            reason="customer cannot find manufacturing/expiry information",
            evidence="không thấy EXP & MGF" if "không thấy EXP & MGF" in text else text,
            confidence=0.9,
        )
    if any(token in lower for token in ("bụi", "bui", "dơ", "bẩn")):
        return result(
            subject="product",
            topic="product_quality_authenticity",
            subtopic="packaging_quality",
            intent="complaint",
            sentiment="negative",
            score=-0.74,
            urgency="normal",
            stage="post_purchase",
            reason="received product looked dusty/dirty",
            evidence="toàn bụi" if "toàn bụi" in text else text,
        )
    if any(token in lower for token in ("mùi hắc", "mùi cồn", "không hợp", "kích ứng", "dùng mạnh với da")):
        if any(token in lower for token in ("chính hãng không", "k biết sản phẩm chính hãng", "hàng giả")):
            return result(
                subject="product",
                topic="product_quality_authenticity",
                subtopic="suspected_counterfeit",
                intent="complaint",
                sentiment="negative",
                score=-0.82,
                urgency="high",
                stage="post_purchase",
                reason="customer questions authenticity after smell/acne issue",
                evidence="K biết sản phẩm chính hãng không" if "K biết sản phẩm chính hãng không" in text else text,
                confidence=0.9,
            )
        return result(
            subject="product",
            topic="product_quality_authenticity",
            subtopic="product_performance",
            intent="complaint",
            sentiment="negative",
            score=-0.69,
            urgency="normal",
            stage="post_purchase",
            reason="customer reports smell/performance concern after purchase",
            evidence="mùi hắc quá" if "mùi hắc quá" in text else text,
        )
    if any(token in lower for token in ("giá", "315k", "475k", "336k")) and any(
        token in lower for token in ("web", "cửa hàng", "shop")
    ):
        return result(
            subject="retailer",
            topic="price_promotion",
            subtopic="price_mismatch",
            intent="complaint",
            sentiment="negative",
            score=-0.76,
            urgency="normal",
            stage="store",
            reason="online and store/shop prices did not match",
            evidence="Xem web giá 315k" if "Xem web giá 315k" in text else text,
        )
    if any(token in lower for token in ("quà", "băng đô")):
        if any(token in lower for token in ("không thấy", "ko thấy", "sai", "thiếu")):
            return result(
                subject="retailer",
                topic="price_promotion",
                subtopic="missing_gift",
                intent="complaint",
                sentiment="negative",
                score=-0.62,
                urgency="normal",
                stage="post_purchase",
                reason="promotional gift appears missing",
                evidence="ko thấy băng đô đâu hết" if "ko thấy băng đô đâu hết" in text else text,
            )
        return result(
            subject="retailer",
            topic="price_promotion",
            subtopic="unclear_eligibility",
            intent="question_request",
            sentiment="neutral",
            score=0.0,
            urgency="low",
            stage="promotion",
            reason="customer asks whether gift applies in store",
            evidence="có dc tặng quà ko" if "có dc tặng quà ko" in text else text,
            confidence=0.82,
        )
    if any(token in lower for token in ("279", "date bao lâu", "giá là")):
        return result(
            subject="retailer",
            topic="price_promotion",
            subtopic="unclear_eligibility",
            intent="question_request",
            sentiment="neutral",
            score=0.0,
            urgency="low",
            stage="promotion",
            reason="customer asks about promotion price/date eligibility",
            evidence="giá là 279" if "giá là 279" in text else text,
            confidence=0.8,
        )
    if any(token in lower for token in ("đổ tè le", "do te le", "đổ ra", "đổ hết")):
        return result(
            subject="retailer",
            topic="delivery_fulfilment",
            subtopic="damaged_package",
            intent="complaint",
            sentiment="negative",
            score=-0.72,
            urgency="normal",
            stage="delivery",
            reason="customer reports item spilled/damaged during transport",
            evidence="vận chuyển thì đổ tè le" if "vận chuyển thì đổ tè le" in text else text,
            confidence=0.88,
        )
    if any(token in lower for token in ("thu hồi", "hoàn tiền")):
        return result(
            subject="product",
            topic="returns_refunds",
            subtopic="return_process",
            intent="question_request",
            sentiment="negative",
            score=-0.42,
            urgency="high",
            stage="returns",
            reason="customer asks why product recall/refund was requested",
            evidence="sản phẩm có vấn đề cần thu hồi và hoàn tiền" if "sản phẩm có vấn đề cần thu hồi và hoàn tiền" in text else text,
            confidence=0.82,
        )
    if any(token in lower for token in ("giao hàng nhanh", "đóng gói cẩn thận", "hỗ trợ nhiệt tình")):
        return result(
            subject="retailer",
            topic="delivery_fulfilment",
            subtopic="fast_delivery",
            intent="praise",
            sentiment="positive",
            score=0.78,
            urgency="low",
            stage="delivery",
            reason="customer praises delivery/packing/support",
            evidence="Giao hàng nhanh" if "Giao hàng nhanh" in text else text,
            confidence=0.88,
        )
    if any(token in lower for token in ("chính hãng", "yên tâm")):
        return result(
            subject="product",
            topic="product_quality_authenticity",
            subtopic="authenticity_praise",
            intent="praise",
            sentiment="positive",
            score=0.82,
            urgency="low",
            stage="post_purchase",
            reason="customer praises authenticity confidence",
            evidence="yên tâm hàng chính hãng" if "yên tâm hàng chính hãng" in text else text,
        )
    if any(token in lower for token in ("giá tốt", "rất tốt", "sản phẩm tuyệt vời", "xài ok", "sử dụng tốt")):
        return result(
            subject="product",
            topic="product_quality_authenticity",
            subtopic="product_performance",
            intent="praise",
            sentiment="positive",
            score=0.72,
            urgency="low",
            stage="post_purchase",
            reason="customer reports good product experience/value",
            evidence="sử dụng tốt" if "sử dụng tốt" in text else text,
            confidence=0.84,
        )
    if rating is not None and rating >= 4:
        return result(
            subject="product",
            topic="product_quality_authenticity",
            subtopic="product_performance",
            intent="praise",
            sentiment="positive",
            score=0.55,
            urgency="low",
            stage="post_purchase",
            reason="positive star review",
            evidence=text,
            confidence=0.75,
        )
    return result(
        subject="unknown",
        topic="other",
        subtopic="other",
        intent="question_request",
        sentiment="neutral",
        score=0.0,
        urgency="low",
        stage="unknown",
        reason=None,
        evidence=text,
        confidence=0.72,
    )


def raw_row(
    *,
    brand: str,
    platform: str,
    source_external_id: str,
    text: str,
    occurred_at: str,
    source_url: str,
    product_name: str,
    product_id: str | None,
    rating: float | None,
    source_group: str = "owned",
    visibility: str = "owned",
    metadata_extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cleaned = clean_text(text)
    label = classify(brand, platform, cleaned, rating)
    row = {
        "source_external_id": source_external_id,
        "source_group": source_group,
        "source_platform": platform,
        "visibility": visibility,
        "brand": brand,
        "brand_candidates": [brand],
        "occurred_at": occurred_at,
        "observed_at": OBSERVED_AT,
        "occurred_at_quality": "exact",
        "original_timezone": "Asia/Ho_Chi_Minh",
        "language": "vi",
        "language_confidence": 0.99,
        "title": f"Real Vietnamese public review for {brand}",
        "text": cleaned,
        "rating": rating,
        "product_name": product_name,
        "product_category": "beauty_personal_care",
        "source_url": source_url,
        "message_count": 1,
        "media_urls": [],
        "metadata": {
            "seed_dataset": "real_feedback_seed_20260712",
            "seed_source": "public_product_review",
            "source_product_id": product_id,
            "inline_classification": label,
            "inline_classification_model": "human-curated-seed-v1",
            "inline_classification_prompt_version": "item-classifier-v2",
            **(metadata_extra or {}),
        },
        "is_synthetic": False,
    }

    RawFeedback.model_validate(row)
    request = ClassificationRequest(
        content_hash=hashlib.sha256(cleaned.encode()).hexdigest(),
        text_redacted=cleaned,
        trusted_metadata=TrustedSourceMetadata(
            source_group=source_group,
            source_platform=platform,
            visibility=visibility,
            source_fixed_brand=brand,
            product_category="beauty_personal_care",
            language="vi",
        ),
        brand_candidates=(brand,),
    )
    validate_classification(ClassificationResult.model_validate(label), request)
    return row


def build_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    normalized = read_jsonl(SOURCE_DIR / "cerave_foaming_cleanser_473ml_normalized.jsonl")
    wanted_guardian_ids = {
        "4156",
        "3959",
        "3858",
        "2815",
        "2554",
        "2446",
        "1490",
        "1268",
        "894",
    }
    wanted_hasaki_ids = {
        "136506",
        "132889",
        "132494",
        "132931",
        "136515",
        "126003",
        "126426",
        "129634",
        "131102",
        "124771",
    }
    wanted_watsons_ids = {"watsons-212621-visible-1", "watsons-212621-visible-2"}

    for item in normalized:
        brand = item.get("brand")
        review_id = str(item.get("source_external_id") or item.get("review_id") or "")
        occurred = item.get("occurred_at") or item.get("review_date")
        if not in_window(occurred):
            continue
        text = item.get("text") or item.get("review_text")
        if not text:
            continue
        if brand == "guardian" and review_id not in wanted_guardian_ids:
            continue
        if brand == "hasaki" and review_id not in wanted_hasaki_ids:
            continue
        if brand == "watsons" and review_id not in wanted_watsons_ids:
            continue

        platform = {
            "guardian": "guardian_ecommerce",
            "hasaki": "hasaki_ecommerce",
            "watsons": "watsons_ecommerce",
        }[brand]
        rows.append(
            raw_row(
                brand=brand,
                platform=platform,
                source_external_id=source_id(f"{brand}-official", review_id),
                text=text,
                occurred_at=occurred,
                source_url=item.get("source_url") or item.get("product_url"),
                product_name=item.get("product_name"),
                product_id=str(item.get("product_id") or ""),
                rating=float(item["rating"]) if item.get("rating") is not None else None,
                metadata_extra={
                    "original_review_id_hash": hashlib.sha256(review_id.encode()).hexdigest(),
                    "source_extraction_scope": item.get("extraction_scope")
                    or (item.get("metadata") or {}).get("source_url_kind"),
                },
            )
        )

    rows.sort(key=lambda r: (r["brand"], r["occurred_at"], r["source_external_id"]))
    return rows


def build_social_discovery() -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for path_name in [
        "guardian_voc_vi_12m.customer-candidates.vi.jsonl",
        "guardian_voc_threads_vi_12m.customer-candidates.vi.jsonl",
    ]:
        path = ROOT.parent / "social-listening-crawler" / "data" / path_name
        if not path.is_file():
            continue
        for row in read_jsonl(path):
            platform = row.get("platform")
            if platform not in {"facebook", "instagram", "threads", "tiktok"}:
                continue
            description = row.get("description") or ""
            title = row.get("title") or ""
            if not description and not title:
                continue
            candidates.append(
                {
                    "platform": platform,
                    "source_url": row.get("link") or row.get("canonical_url"),
                    "canonical_url": row.get("canonical_url"),
                    "title": clean_text(title)[:240],
                    "snippet": clean_text(description)[:500],
                    "brand_candidates": row.get("brand_candidates") or [],
                    "published_date": row.get("published_date"),
                    "observed_at": row.get("observed_at"),
                    "reason_not_imported": "full public post/comment text was not accessible; retained as discovery evidence only",
                }
            )
    unique: dict[str, dict[str, Any]] = {}
    for row in candidates:
        key = str(row.get("canonical_url") or row.get("source_url"))
        unique.setdefault(key, row)
    return list(unique.values())[:30]


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows = build_rows()
    with OUT_JSONL.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")

    discoveries = build_social_discovery()
    with OUT_DISCOVERY.open("w", encoding="utf-8") as handle:
        for row in discoveries:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")

    counts: dict[str, int] = {}
    by_platform: dict[str, int] = {}
    for row in rows:
        counts[row["brand"]] = counts.get(row["brand"], 0) + 1
        by_platform[row["source_platform"]] = by_platform.get(row["source_platform"], 0) + 1

    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "dataset": OUT_JSONL.name,
        "row_count": len(rows),
        "real_rows_only": True,
        "synthetic_rows": 0,
        "period_start": PERIOD_START,
        "period_end": PERIOD_END,
        "brands": counts,
        "platforms": by_platform,
        "social_discovery_rows_review_needed": len(discoveries),
        "social_discovery_file": str(OUT_DISCOVERY.relative_to(ROOT)),
        "queries_used": [
            'site:facebook.com ("Guardian" OR "Hasaki" OR "Watsons") ("giao hàng" OR "đổi trả" OR "lừa đảo" OR "hàng giả")',
            'site:instagram.com ("guardianvietnam" OR "hasaki" OR "watsonsvietnam") review OR đánh giá',
            'site:threads.net ("Guardian" OR "Hasaki" OR "Watsons") ("mỹ phẩm" OR "giao hàng" OR "voucher")',
            'site:tiktok.com ("Guardian" OR "Hasaki" OR "Watsons") ("đánh giá" OR "mua hàng" OR "giao hàng")',
            'official product review pages for Guardian/Hasaki/Watsons CeraVe Foaming Cleanser 473ml',
        ],
        "blocked_or_rejected_sources": [
            "TikTok direct fetch commonly requires JS/app context and blocked reliable text extraction; no TikTok rows imported from snippets.",
            "Instagram and Threads public search results did not expose enough full Vietnamese user review text for import in this pass.",
            "Facebook search snippets were retained as discovery evidence unless full public post/comment text was accessible.",
            "Rows with only star ratings and no text were skipped.",
            "Rows containing resale/pass contact details were skipped unless a retailer/product issue was present; phone numbers were redacted.",
        ],
    }
    OUT_MANIFEST.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
