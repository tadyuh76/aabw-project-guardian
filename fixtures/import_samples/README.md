# Mock marketplace review exports

These five files contain synthetic reviews for testing the agentic import flow. Import each file with its matching source profile where possible:

- `shopee_reviews_mock.csv` → Shopee
- `lazada_reviews_mock.csv` → Lazada
- `tiktok_shop_reviews_mock.csv` → TikTok Shop
- `grabmart_reviews_mock.csv` → GrabMart
- `unusual_vendor_reviews_mock.csv` → any marketplace profile; this is the hardest header-mapping test

Every file has a distinct SHA-256 digest and unique review content. Re-uploading the same file should trigger the duplicate-file warning.
