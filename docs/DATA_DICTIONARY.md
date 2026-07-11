# Data dictionary

`ingestion_runs` and `source_status` preserve source-level history and health.
`feedback_items` stores only canonical, redacted feedback plus hashed customer
or conversation identifiers. `feedback_analyses` stores the versioned structured
classification. `pipeline_runs` records ingest-to-publish state. Insight series,
observations, status history, cards, and evidence keep current narrative separate
from immutable facts and monitoring references.

The analytical unit is one non-duplicate structured interaction or one exact
public repost group. `raw_record_count` is reach only. Records without a reliable
occurrence date remain searchable evidence but stay out of time-window metrics.
Ambiguous brand attribution and unknown language stay out of brand-rate and
language-matched benchmark calculations respectively.

