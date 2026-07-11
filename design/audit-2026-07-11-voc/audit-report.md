# Independent Guardian Command Center UX and requirement audit

Date: 11 Jul 2026  
Reviewer: independent agent  
Mode: read-only, blocker-first

## Direct verdict

**Not ready.** The dashboard is polished, but the default scope hides the two sunscreen SKUs driving the alert, while several high-trust claims conflict with or are unsupported by the implemented data logic.

## Top findings

### P1 — The first viewport does not identify the affected products

- Screenshot 1 shows `All products` and “Inspect pump-neck seal and cap fit,” but neither sunscreen SKU. Names appear only after scrolling in Screenshot 2.
- The route defaults to every product (`src/data/dashboard.ts:498-503`).
- The pump hypothesis support is limited to `P-UV01` and `P-UV02` (`src/data/dashboard.ts:308-321`), but the card says “across 5 products” from selected cohort length (`src/components/VisualDashboard.tsx:177-182`).
- Impact: a two-SKU sunscreen incident looks portfolio-wide.
- Recommendation: default the alert to the detected cohort and lead with “Leakage spike in SunShield SPF 50 and UV Defense SPF 50+.”

### P1 — Timing and evidence-scope claims are unsupported

- “Spike crossed baseline at 36h” is static (`src/components/VisualDashboard.tsx:195-199`).
- The curve is synthesized from a fixed shape, not timestamped observations (`src/components/VisualDashboard.tsx:56-65`).
- For the all-products fixture, the generated curve crosses the 5% baseline around 18h, not 36h.
- All 20 hypothesis supports belong to two sunscreen products, not five.
- Recommendation: use real time buckets and say “20 supporting signals across 2 products and 4 channels.”

### P1 — “Real-time” and “same cohort” are not substantiated

- Product, evidence and competitor values are hardcoded fixtures (`src/data/dashboard.ts:38-223`).
- Data is derived in memory (`src/App.tsx:112-120`).
- Competitor counts are fixtures (`src/data/dashboard.ts:445-450`), while the chart omits matching method, source, sample period and freshness (`src/components/VisualDashboard.tsx:273-286`).
- Actions persist only to `localStorage` (`src/App.tsx:78-101,137-143`).
- Recommendation: visibly label source, period, n/N, freshness and cohort method. Do not claim real-time until live ingestion exists.

### P1 — The hierarchy prescribes action before explaining the incident

- Recommended action is first (`src/components/VisualDashboard.tsx:165-193`).
- Affected products and supporting channels appear later (`src/components/VisualDashboard.tsx:239-271`).
- Recommendation: scope → alert → severity/recency → channel evidence → cause/confidence → action.

### P2 — `All products` dilutes and mis-scopes the incident

- All products: 34/200 versus 140/2800 baseline = 17% versus 5% = 3.4×.
- Two sunscreen SKUs: 27/90 versus 50/1260 baseline ≈ 30% versus 4.0% = 7.6×.
- Recommendation: detected cohort by default; portfolio view as an explicit comparison.

### P2 — The constellation is spectacle rather than investigation support

- Nodes are anonymous circles until hover/click (`src/components/VisualDashboard.tsx:340-381`).
- Edges have no relationship label or strength (`src/components/VisualDashboard.tsx:68-116`).
- The panel says context is highlighted, but adjacency highlighting is not implemented.
- Recommendation: remove 3D; keep 2D only in a dedicated investigation surface after adding persistent labels, relationship semantics, adjacency highlighting and a keyboard-accessible list.

### P2 — VoC requirements are charts rather than an operating workflow

- Executive brief, evidence, alert and actions are collapsed (`src/App.tsx:247-255`).
- Alert lifecycle is seeded status, not detect → notify → acknowledge → resolve (`src/App.tsx:159-165,497-515`).
- Intent classification is absent.
- Sentiment is fixture data and buried in the collapsed workspace (`src/App.tsx:303-308`).
- Recommendation: center alert lifecycle, evidence provenance, owner, due date, decision, resolution and measured outcome.

### P2 — Visible accessibility risks

- Canvas nodes have no keyboard-equivalent list.
- Donut and bars lack accessible text summaries/data-table equivalents.
- Important annotation text is often 10–12px.
- Categories rely strongly on color.
- Full WCAG compliance cannot be determined from screenshots.

### P3 — Navigation implies unavailable functionality

Most sidebar destinations are inactive (`src/App.tsx:48-59,174-190`). Show working destinations only or label the surface as a prototype.

## Five-second test

| Question | Result | Reason |
|---|---|---|
| What product/family is this about? | **Fail** | First viewport says `All products`; SKU names are below fold. |
| What exactly is wrong? | **Partial** | It shows a possible pump cause before plainly stating the observed leakage problem. |
| How severe and recent is it? | **Partial** | Urgency is visible, but time claim is inaccurate and denominators are absent above fold. |
| Which channels support it? | **Fail** | Channels appear only after scrolling. |
| What should I do next? | **Pass** | CTA, owner and timing are prominent, though their evidence basis needs correction. |

## Requirement coverage

| Requirement | Coverage | Primary gap |
|---|---|---|
| Four continuous feedback sources | Partial | Four fixture keys exist; no continuous ingestion. |
| Centralized holistic view | Partial | Unified UI exists; no actual platform integration. |
| Sentiment, recurring issues, emerging trends | Partial | Sentiment is buried; trend is synthesized. |
| Hasaki/Watsons benchmarking | Partial | No provenance or defensible cohort method. |
| Automatic ingestion | Missing | Hardcoded fixtures only. |
| Structured/unstructured consolidation | Missing | No lineage, deduplication or identity resolution. |
| Sentiment analysis | Partial | Delta field only; no method/distribution/confidence. |
| Topic classification | Partial | Hardcoded themes, no classifier evidence. |
| Intent classification | Missing | No field, model or UI. |
| Trend analysis | Partial | Chart uses a fixed synthetic curve. |
| Root-cause identification | Partial | Fixture-driven hypothesis score. |
| Automated insights | Partial | Derived headline/action, but claims are over-broad or inaccurate. |
| Real-time dashboard | Missing | No live connection, cadence or last refresh. |
| Executive summary | Partial | Morning Brief is collapsed and lacks product clarity. |
| Proactive alerts | Partial | Seeded alert, no notification/acknowledgement/SLA/resolution. |
| Competitive benchmarking | Partial | Visual exists; comparison trust is insufficient. |
| Reduce manual reporting 70–80% | Not measurable | No effort baseline or productivity measurement. |
| Single real-time cross-channel sentiment | Partial | Aggregated sources, but neither live nor channel sentiment. |
| Identify issues and root causes proactively | Partial | No detection audit trail or validated cause. |
| Accelerate CX improvement | Not measurable | No time-to-action or post-action result. |
| Improve customer satisfaction | Not measurable | No CSAT/NPS or intervention-linked outcome. |

## Chart usefulness

| Visual | Verdict | Required change |
|---|---|---|
| Complaint trend | Change | Real buckets, dates, n/N, baseline method and correct crossing time. |
| Issue donut | Change | Sorted bars/list with count, share, confidence and evidence. |
| Affected products | **Keep and promote** | Move above fold; separate count from rate encoding. |
| Signal sources | Change | Values, denominators, deduplication, time window and sentiment. |
| Competitor benchmark | Change | Source, period, n/N, product matching and uncertainty. |
| Product × issue heatmap | Keep below fold | Clarify whether cells are counts, rates or share of theme. |
| 2D constellation | Remove from executive view | Rebuild as a labeled, explainable, accessible investigation tool. |
| 3D constellation | Remove | Occlusion and interaction cost add no decision value. |

## Recommended above-the-fold order

1. **Scope and freshness:** `Sunscreen · 2 affected SKUs`, product names, 72h, last updated, channels, synthetic/live status.
2. **Plain-language alert:** “Leakage complaints spiked across SunShield SPF 50 and UV Defense SPF 50+.”
3. **Magnitude:** 27/90, 30% versus ~4% baseline, ~7.6×, real crossing time.
4. **Independent support:** channel counts/denominators, top customer quotes, top theme/share.
5. **Root-cause hypothesis:** support vs contradiction, two products, channel breadth and confidence method.
6. **Decision workflow:** recommended action, owner, due date, status, acknowledge/assign/investigate.
7. Supporting product ranking, real trend and defensible benchmark.
8. Below fold: full evidence, activity, heatmap, alternatives and relationship explorer.

## Do not prioritize yet

- 3D graph polish.
- Additional charts before scope and data truth are fixed.
- More confidence styling before confidence is explainable.
- Decorative sidebar destinations.
- Portfolio-level visual polish while the alert should default to two SKUs.

## Evidence limits

- Evidence: requirement screenshot, three current-run desktop screenshots and four implementation files.
- No full mobile, keyboard, screen-reader, zoom, loading, error or complete action-resolution run was supplied.
- Lower expected-outcome text in the requirement image is cropped and was not inferred.
- Missing capability findings are scoped to the inspected frontend; no external backend, classifier or ingestion contract was supplied.
