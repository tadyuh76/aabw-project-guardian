# Limitations

- Demo values are synthetic and cannot be treated as Guardian production facts.
- Search discovery is sampled and delayed; protected pages may be unreadable.
- Mounted-candidate page enrichment is deliberately Guardian-only and capped
  per immutable snapshot. Over-budget or unreadable rows remain unverified
  discovery evidence and never enter customer-feedback metrics.
- TinyFish Search receives the crawler's calendar date bounds, but individual
  results may still omit publication dates. The pipeline keeps missing dates
  unknown instead of inventing them.
- Public feedback populations and rating behavior differ by platform.
- Feedback-item volume is not customer volume, sentiment is not NPS/CSAT, and
  customer-stated reasons are not confirmed operational causes.
- Competitor comparison is shown only for matched public cohorts with sufficient
  samples; owned Guardian data never enters it.
- DuckDB is deliberately single-process. External-model use for owned data needs
  privacy approval, retention controls, and human review before operational use.
