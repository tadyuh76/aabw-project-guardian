# Deterministic demo fixtures

Every record in this directory is synthetic and is labelled as demo data in the
application. Run `python fixtures/generate_demo.py` to regenerate it. The
generator is seeded and anchored to `VOC_DEMO_AS_OF=2026-07-11T23:59:59+07:00`.

`raw/` contains canonical JSONL exports for each source family. `labels/`
contains cached structured classifier results. `expected/hero_metrics.json`
contains aggregates asserted by the backend tests. `demo_increment/` contains a
separate stock-cancellation batch used by the proactive update demonstration.

No external link in these fixtures is presented as real evidence; all URLs use
`example.com`, and the UI suppresses outbound links for synthetic records.

