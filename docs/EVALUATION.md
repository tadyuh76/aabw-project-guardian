# Evaluation

The automated suite covers crawler regression, canonical import and idempotency,
PII redaction, exact repost grouping, deterministic language handling, provider
HTTP/timeout/retry behavior, stratified trend math, source-health suppression,
common-weight competitor cohorts, fact grounding, API authorization, locale-key
parity, and the seed-to-Today/demo-increment paths.

Production evaluation should use a balanced, manually reviewed holdout set and
report relevance precision, topic/intent macro-F1, sentiment macro-F1, alert
precision, percentage of claims with resolvable evidence, pipeline runtime, and
human review time. Reporting reduction and customer-satisfaction improvement
remain measurable goals, not fixture-derived claims.

