# Mock marketplace review exports

These five files contain synthetic reviews for testing the agentic import flow. Import each file with its matching source profile where possible:

- `shopee_reviews_mock.csv` → Shopee
- `lazada_reviews_mock.csv` → Lazada
- `tiktok_shop_reviews_mock.csv` → TikTok Shop
- `grabmart_reviews_mock.csv` → GrabMart
- `unusual_vendor_reviews_mock.csv` → any marketplace profile; this is the hardest header-mapping test

Every file has a distinct SHA-256 digest and unique review content. Re-uploading the same file should trigger the duplicate-file warning.

Additional AI column-detection stress samples:

- `ai_stress_shopee_mall_export.csv` → Shopee, Vietnamese seller export with conversational headers and rating text
- `ai_stress_lazada_crossborder_export.csv` → Lazada, nested/dot-path style headers and epoch-millisecond dates
- `ai_stress_tiktok_live_export.csv` → TikTok Shop, live-commerce export with uppercase headers and creator/session metadata
- `ai_stress_grabmart_branch_export.csv` → GrabMart, branch operations export with delivery and picker columns
- `ai_stress_guardian_ecommerce_export.csv` → Guardian Ecommerce, owned-site export with web/member metadata and PII redaction coverage
