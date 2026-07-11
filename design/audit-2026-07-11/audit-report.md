# Guardian dashboard comprehension audit

## Verdict

The current dashboard is incident-first rather than overview-first. It immediately promotes one packaging alert, so a first-time user cannot quickly answer whether Guardian's overall customer experience is healthy, what themes matter across the portfolio, or what action should happen next.

Recommended decision path:

`Overall health → important changes → raw negative reviews → next actions → product drill-down`

## Captured flow

### Step 1 — All-product Command Center

Evidence: `01-overview.png`

Health: weak for first-time comprehension.

- Strength: the priority packaging incident and its scale are visually clear.
- Issue: the largest headline is one root-cause signal, not an overall portfolio summary.
- Issue: overall sentiment, average rating, review volume, and the distribution of positive/neutral/negative feedback are absent from the first scan.
- Issue: the reading order mixes signal activity, affected products, evidence, hypothesis, and actions before explaining the portfolio's general condition.

### Step 2 — Product filter

Evidence: `02-product-filter.png`

Health: functional but overloaded.

- Strength: search and multi-selection make cohort filtering flexible.
- Issue: filtering is treated as the only route to product intelligence. A user must already know which product they want to inspect.
- Issue: product rows show review counts but no health indicator, rating, negative share, trend, or top complaint, so the list does not help choose where to investigate.

### Step 3 — Single-product state

Evidence: `03-single-product.png`

Health: weak as a product-detail experience.

- Strength: the KPI calculations and URL cohort update correctly.
- Issue: the page retains the same incident-first layout and only changes the cohort numbers.
- Issue: it lacks a clearly labelled product profile, product health history, topic mix, raw review history, channel split, competitors, and product-specific action tracking.

## Recommended information architecture

### 1. Overview — default route

1. Plain-language portfolio summary: one sentence saying whether experience is stable, improving, or declining and why.
2. Four portfolio KPIs: average rating, sentiment mix, total review volume, and unresolved critical issues.
3. What changed: three ranked cross-product issues/opportunities with delta, affected products, and sample size.
4. Negative reviews requiring attention: raw excerpts with product, rating, source, time, topic, and a review-detail link.
5. Next actions: a standalone section with priority, proposed action, evidence count, owner, deadline, status, and monitoring metric.
6. Product health: sortable product table/card list with rating, negative share, review volume, trend, top issue, and status. Clicking a row opens the product page.

### 2. Product detail — dedicated route

Suggested route: `/products/:productId`.

1. Product identity and health summary.
2. Sentiment and rating over the selected period.
3. Top positive and negative topics.
4. Raw reviews with sentiment/source/topic filters and an internal review-detail view.
5. Root-cause hypotheses with supporting and contradicting evidence.
6. Product-specific next actions and monitoring status.
7. Category-matched competitor comparison.

The global product filter can remain on Overview for cohort comparison, but it should not replace the dedicated product page.

## Mock-data changes

- Make review records the source of truth and derive all dashboard totals from them.
- Add `reviewId`, `productId`, `rating`, `sentiment`, `topic`, `severity`, `source`, `channel`, `publishedAt`, `rawText`, and `sourceRef`.
- Use an internal `/reviews/:reviewId` detail route or drawer for mock reviews; do not invent live marketplace URLs.
- Seed multiple themes rather than one packaging story: product quality, delivery, availability, customer service, app experience, pricing, and positive recommendation intent.
- Give each product a visibly different health profile so the product table helps users choose where to drill down.
- Derive recommended actions from recurring issue thresholds and retain the evidence IDs used to justify each action.

## Success test

A first-time user should answer these questions within ten seconds:

1. Is the portfolio healthy overall?
2. What is the most important problem or opportunity?
3. Which products and reviews support that conclusion?
4. What should Guardian do next?

