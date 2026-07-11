# Guardian — AI Voice of Customer Intelligence

## Product and implementation plan

**Status:** First functional Command Center prototype implemented and verified with deterministic mock data.

**Project state:** Greenfield repository with no existing source code or legacy constraints.

**Initial mode:** Deterministic synthetic data first; ingestion and production AI pipeline later.

## 1. Decisions locked for the hackathon

- Primary user: **CX/Category Manager**. Executives are a secondary audience through the Executive Brief.
- Core job: move from an abnormal signal to evidence, a root-cause hypothesis, competitor context, and an owned action.
- Main visual direction: dark decision cockpit with Guardian yellow `#FFE500` as the brand/action accent.
- The implemented dashboard defaults to Light mode and exposes a persistent Light/Dark toggle; Dark mode preserves the selected cockpit visual direction.
- `#FFE500` is used for primary actions and the current focus/selection. It must not represent warning or negative sentiment.
- Graphs are intentionally deferred in the current prototype so the product-filter and evidence workflow can be validated first.
- When graph work begins, the 2D Brand Protection graph will use `d3-force` for physics and native HTML `<canvas>` for rendering.
- The future 3D graph will use `3d-force-graph`, derive from the same immutable canonical graph IDs, and load only on demand.
- The product always says **root-cause hypothesis**, displays confidence and evidence, and never presents association as proven causality.
- Every screen displays a subtle `Synthetic demo data` disclosure until real data sources are connected.
- No generic chatbot and no oversized grid of vanity KPIs in the hackathon scope.

## 2. Product outcome and success measures

Guardian is a **Voice of Customer decision workspace**, not a sentiment dashboard.

The core journey is:

`Emerging signal → inspect change → inspect evidence → understand likely drivers → compare competitors → create action → monitor outcome`

The demo succeeds when:

- A user can identify and explain the main emerging issue in under 90 seconds.
- From the default Command Center, a user can create the recommended action in exactly three activations: open the top signal, open the prefilled action, and confirm assignment.
- Every AI claim can be traced to the review records behind it.
- Every action has an owner, deadline, expected outcome, and monitoring signal.
- Every competitor comparison uses the same time range, category, and channel cohort.

## 3. Critical path

### User flow

1. The user opens the Morning Brief on the Command Center.
2. The user selects the highest-priority signal.
3. The Investigation Workspace explains what changed, where it is concentrated, and what customers are saying.
4. The current prototype exposes associations through structured evidence breakdowns; a later 2D relationship graph will extend the same investigation path.
5. The user checks a cohort-matched competitor comparison.
6. The user creates an action and assigns an owner.
7. Signal status and Executive Brief update immediately.

### Data flow

1. Deterministic mock source events simulate marketplace, owned-channel, service, and social inputs.
2. Normalization and deduplication produce canonical `feedback_event` records while retaining source provenance.
3. Mock AI enrichment produces sentiment, topics, intents, entities, and issue tags.
4. Transparent rules aggregate records into signals and root-cause hypotheses.
5. A repository/data-adapter layer exposes typed query methods to the UI.
6. Global filters produce one shared cohort for metrics, charts, graph, evidence, and benchmark.
7. Action mutations update local demo state without modifying the source dataset.
8. A later HTTP/streaming repository can replace the mock repository without rewriting the feature screens.

### Main failure cases to design against

- Root cause is described as fact even though only associations exist.
- Benchmark compares different product/category/channel mixes.
- “Real-time” is implied even though the current data is synthetic.
- A metric or graph node cannot be traced back to evidence.
- Severity and confidence are collapsed into one opaque score.
- A graph is visually impressive but does not help the user make a decision.

## 4. Information architecture

### Primary navigation

| Route | Surface | Primary question |
| --- | --- | --- |
| `/` | Command Center | What changed today and what needs my attention? |
| `/signals` | Signal Inbox | Which issues or opportunities should I prioritize? |
| `/signals/:signalId` | Investigation Workspace | What changed, where, why might it be happening, and what should we do? |
| `/network` | Brand Protection Network | How are issues, products, stores, channels, and competitors connected? |
| `/benchmark` | Competitive Benchmark | Where is Guardian winning or losing within comparable cohorts? |
| `/brief` | Executive Brief | What decisions, owners, and outcomes need leadership attention? |
| `/coverage` | Data Coverage | Which synthetic or future real sources are represented? |

`/coverage` is secondary navigation. It prepares the UI contract for the future pipeline without pretending that live connectors exist today. In mock mode it shows synthetic source mix, last simulated ingestion time, and deduplication counts rather than fake connector-health claims.

### Command Center

The page answers one question: **“What changed and what should I do?”**

- AI Morning Brief with three to five evidence-linked statements.
- Priority signal queue: Critical, Watch, Positive opportunity, Resolved.
- Four core metrics only:
  - Negative mention share.
  - Issue velocity versus baseline.
  - Affected products/stores/channels.
  - Competitor experience gap.
- Active actions with owner, deadline, status, and monitoring signal.
- Global filters: period, retailer, category, channel, region/store, severity, and action status.

Every metric includes its baseline, delta, sample size, and evidence drill-down.

### Signal Inbox

Each signal is written as an actionable story, for example:

> Packaging leakage mentions for sunscreen orders increased 3.4× over the last 72 hours.

A signal card contains:

- Severity and confidence as separate attributes.
- Start time and current velocity.
- Related review count and affected entities.
- Comparison with baseline.
- Competitor gap for the same cohort.
- Owner and workflow status when an action exists.

### Investigation Workspace

The reading order remains fixed:

1. **What changed?** Trend line with spike annotations.
2. **Where and for whom?** Contribution by product, SKU, store, region, and channel.
3. **What are customers saying?** Highlighted raw reviews with source and timestamp.
4. **What may be causing it?** Root-cause hypotheses and the 2D evidence graph.
5. **How are competitors performing?** Same cohort with visible sample size.
6. **What should we do now?** Suggested action, owner, deadline, and success signal.

Action lifecycle:

`Open → Investigating → Acting → Monitoring → Resolved`

### Brand Protection Network

- Full-screen 2D network is the default analytical view.
- A visible toggle offers `Investigate in 2D` and `Explore network in 3D`.
- Filters and selected node persist while switching modes.
- Selecting a node or edge opens an evidence panel rather than a decorative tooltip only.
- The Investigation Workspace embeds a signal-scoped subset of this same graph.

### Competitive Benchmark

Avoid one opaque “CX score.” Compare Guardian, Hasaki, and Watsons using explainable metrics:

- Negative mention share.
- Average rating.
- Topic complaint share.
- Issue velocity.
- Positive recommendation intent.
- Resolution satisfaction only when post-service feedback exists.

The comparison cohort always locks:

- Time range.
- Category.
- Channel.
- Region when relevant.
- Minimum sample size.

When a cohort has fewer than 30 records for a retailer, show `Insufficient sample` instead of a misleading ranking.

### Executive Brief

The brief is structured, not a long AI paragraph:

1. What changed.
2. Why it matters.
3. Top three drivers.
4. Competitive movement.
5. Decisions required.
6. Actions, owners, deadlines, and monitoring status.
7. Evidence appendix.

Daily and weekly briefs store an immutable metric/evidence snapshot with `asOf`, exact cohort filters, and included `signalId` values. The current Brief joins live actions by `signalId`; a newly created action appears without mutating the snapshot. Updating an action never rewrites historical figures or evidence. A regenerated brief creates a new version instead of silently mutating an older snapshot.

## 5. Mock-data strategy

### Dataset shape

- Six to eight weeks of review-level events.
- Guardian, Hasaki, and Watsons as retailers.
- Guardian web/app, marketplaces, customer service, stores, and social/community channels.
- Mostly natural Vietnamese with typos, slang, mixed sentiment, and a smaller English subset.
- Normal baseline noise plus intentional incidents; never random chart numbers.
- Fixed seed so refreshes and demo resets reproduce the same result.
- No real customer PII.

### Source and canonical feedback

The mock generator first produces `source_event` items with source-specific IDs, timestamps, content, and metadata. A normalization step maps them into canonical `feedback_event` records. Product screens query canonical records; the evidence panel can still reveal every retained source reference.

Canonical `feedback_event` minimum fields:

- `id`, `canonicalPublishedAt`, `canonicalFeedbackId`, and `dedupeGroupId`.
- `sourceRefs[]`, each containing `sourceRefId`, `sourcePublishedAt`, `ingestedAt`, `sourceType`, `sourceName`, `sourceRecordId`, `channel`, and source provenance/reference.
- `primarySourceRefId` and `primaryChannel` for deterministic cohort attribution.
- `retailer`, `language`, `rawText`, `rating`.
- `productId`, `sku`, `productName`, `category`, `productBrand`.
- `storeId`, `storeName`, `region` when applicable.
- `contentType`, `interactionType`, and optional service/transcript-resolution fields.
- `scenarioId` and `synthetic: true`.

### Derived entities

- `analysis_result`: sentiment, topic, intent, entities, issue tags, and confidence.
- `signal`: change versus baseline, severity, confidence, affected entities, and evidence IDs.
- `root_cause_hypothesis`: explanation, supporting evidence, contradicting evidence, and confidence factors.
- `graph_node` and `graph_link`: the immutable canonical relationship model from which separate 2D/3D renderer payloads are cloned.
- `action`: `id`, `signalId`, owner, priority, deadline, status, expected outcome, `monitoringSignal`, `createdAt`, and `updatedAt`.
- `monitoringSignal`: metric, cohort, target, window start/end, minimum sample, observed value, and evaluation state.
- `executive_brief_snapshot`: immutable evidence/metric summary for a fixed `asOf` and filter cohort, plus included signal IDs used to join live actions.

Raw fields and AI-derived fields must remain separate so the later pipeline can replace enrichment without changing original feedback records. Reposted or duplicated content collapses into one canonical feedback record for counting, while every original source reference remains available for provenance and evidence review.

Deduplication never crosses the reviewed retailer boundary. Within one retailer/product or service context, the earliest published matching source becomes `primarySourceRefId`; `canonicalPublishedAt` and `primaryChannel` come from that reference. Overall and channel-specific metrics count the canonical record once using its primary channel. Secondary source references contribute to provenance and source coverage, not a second mention count.

### Seeded demo scenarios

1. **Emerging critical issue — packaging leakage**
   - Sunscreen packaging complaints rise after a campaign.
   - Concentrated in two pump-bottle SKUs and Guardian app/marketplace orders.
   - Terms such as “leaking,” “loose cap,” and “wet box” co-occur.
   - Competitor cohort remains closer to its baseline.

2. **Recurring issue — voucher application failure**
   - Customers see a promotion but cannot apply it at checkout.
   - Appears in app reviews and customer-service conversations.
   - Recurs after earlier partial resolution.

3. **Positive opportunity — click and collect**
   - Customers praise pickup speed in selected regions.
   - Guardian outperforms comparable competitor cohorts.
   - The recommended action is to replicate the operating pattern elsewhere.

Include contradictory/noisy reviews in every scenario. A root-cause hypothesis should not have artificially perfect evidence.

### Transparent mock detection rules

All calculations use canonical deduplicated feedback and a fixed virtual clock. Issue and benchmark windows use `canonicalPublishedAt`; `ingestedAt` is reserved for coverage and ingestion-latency views. The primary fixture uses `asOf = 2026-07-11T09:00:00+07:00`.

- Current window: `[asOf - 72 hours, asOf)`.
- Baseline window: the preceding 28 full days, `[asOf - 31 days, asOf - 72 hours)`.
- Issue mention share: matching canonical feedback divided by all canonical feedback in the same cohort/window.
- Issue velocity: current mention share divided by baseline mention share.
- Two-proportion z-score: `(pCurrent - pBaseline) / sqrt(pPool × (1 - pPool) × (1/nCurrent + 1/nBaseline))`, where `pPool = (xCurrent + xBaseline) / (nCurrent + nBaseline)`.

An emerging signal requires:

- At least 15 matching mentions.
- Current issue mention share at least 2× baseline.
- Z-score at least 2.
- Evidence across at least two channels, or at least 60% of matching evidence concentrated in an entity whose share is at least 2× its baseline.

Edge handling is deterministic:

- A zero baseline with a nonzero baseline cohort is labeled `New`, not `∞×`; count and z-score gates still apply.
- An empty or incomplete baseline cohort is labeled `Insufficient baseline` and is not ranked as emerging.
- Benchmark requires an explicit time range, category, and channel. Region may be `All`, but the same region filter applies to every retailer.
- Any retailer cohort below 30 canonical records displays `Insufficient sample`, receives no rank, and explains the missing cohort requirement. There is no “warn but rank anyway” path.

The headline fixture is locked for tests:

- Guardian current: 34 packaging mentions / 200 canonical reviews = 17.0%.
- Guardian baseline: 140 / 2,800 = 5.0%.
- Guardian issue velocity: 3.4×.
- Watsons current comparable cohort: 12 / 180 = 6.7%.
- Guardian versus Watsons gap: +10.3 percentage points after one-decimal rounding.

Root-cause confidence is derived from visible factors:

- Temporal alignment.
- Entity lift versus baseline.
- Evidence breadth across channels.
- Supporting versus contradicting evidence.

### Data-adapter boundary

The UI depends on shared typed repository contracts, not direct JSON imports.

`FeedbackRepository` capabilities:

- Query overview and filtered feedback.
- Query signals and signal details.
- Query cohort-matched benchmarks.
- Query shared graph data.
- Subscribe to new signals later.

`ActionRepository` capabilities:

- Query actions by ID and `signalId`.
- Create/update an action.
- Expose one uniform `subscribe(listener)` contract; mock emits after local mutations, while HTTP can bridge mutation responses plus future SSE/poll events.

`DemoControlRepository` is mock-only and owns reset, virtual-clock advance, and incident replay. Product features do not depend on it; demo controls render only when that provider is available.

The first implementations are `MockFeedbackRepository` and `MockActionRepository`. Production later supplies `HttpFeedbackRepository`, `HttpActionRepository`, and an optional stream/SSE adapter without changing feature components.

Action state uses one app-scoped mock repository persisted in local storage. It exposes mutation notifications to subscribed feature hooks so Signal, Command Center, and the current Brief read the same action record after navigation and refresh. A one-click reset clears the action store and restores the seeded starting state.

For the packaging scenario, applying the action starts a seeded 48-hour post-action monitoring window. Success means packaging complaint share is no more than 1.2× its baseline with at least 30 canonical records. The action remains `Monitoring`; a derived evaluation becomes `passing` and offers a user-confirmed transition to `Resolved`. A sufficient sample that misses the target becomes `failing`. Fewer than 30 post-action records becomes `insufficient_sample` and remains neutral in `Monitoring` rather than being treated as failure.

## 6. Brand Protection graph specification

### Graph semantics

Node types:

- Issue/topic.
- Product/SKU.
- Product brand or retailer.
- Store/region.
- Channel/source.
- Customer intent.
- Evidence cluster or individual review at deep zoom.

Links represent **association or co-occurrence**, not causality. Each link includes:

- Relationship type and human-readable label.
- Weight and mention volume.
- Lift versus baseline.
- Confidence.
- Supporting evidence IDs.

The graph domain model is immutable:

- Canonical nodes have stable `id` values and no simulation coordinates.
- Canonical links store `sourceId` and `targetId`, never renderer-mutated object references.
- `to2DGraph()` and `to3DGraph()` deep-clone nodes and links into separate mutable renderer inputs.
- Filters and selection synchronize by stable ID, never by object identity or `x/y/z` values.
- Switching renderers must not mutate the canonical graph or leak coordinates between modes.

Visual encodings:

- Node size: affected review volume.
- Node fill: entity type.
- Risk halo: severity.
- Ring `#FFE500`: current selection only.
- Guardian identity: labeled shield icon/shape plus text, so it remains distinct even when a competitor node is selected.
- Edge width: relationship strength.
- Edge opacity: confidence.
- Cluster regions: product/category/channel groupings behind the graph.

### 2D architecture

Use `d3-force` for:

- `forceLink` relationships.
- `forceManyBody` separation.
- `forceCollide` node/icon collision.
- Centering and `forceX`/`forceY` cluster attraction.
- Pinning and simulation reheating after drag.

Use native HTML `<canvas>` for all visible drawing layers:

1. Cluster regions.
2. Edges.
3. Nodes.
4. Icons and labels.
5. Hover, selection, and path highlight.

React owns filters, selected entities, panel state, and lifecycle. The simulation and draw loop stay imperative in refs; React state must not update on every simulation tick.

Implementation rules:

- Clone nodes before giving them to D3 because force simulation mutates positions.
- Give 2D and 3D separate cloned coordinate objects; they share domain IDs and attributes, not mutable simulation coordinates.
- Draw through `requestAnimationFrame` and stop the simulation on unmount.
- Use `ResizeObserver`; scale for device pixel ratio but cap DPR at 2.
- Use seeded initial positions so the demo layout is repeatable.
- Recompute cluster hulls periodically or after settling, not on every frame.
- Reduce labels at low zoom and reveal detail progressively.
- Draw icons from a cached icon atlas or `ImageBitmap`; do not use emoji or text glyphs as substitute icons.
- Use spatial hit testing for nodes and a generous interaction corridor for links.
- Keep a stable mental map when filters change by preserving positions for surviving nodes.

2D interactions:

- Pan and zoom.
- Hover preview.
- Click to select and open evidence.
- Drag to reposition; click a lock control to pin permanently.
- Search and center on an entity.
- Filter by node type, severity, category, channel, and time.
- Highlight one-hop and shortest relevant evidence paths.
- Reset layout and reset demo state.

### 3D architecture

- Use `3d-force-graph` with a dedicated adapter derived from the same immutable canonical graph used by 2D.
- Dynamically import the module only when 3D mode is selected.
- Synchronize filters and selected node between 2D and 3D.
- Preserve the same color and size semantics.
- Focus the camera on selection and expose an obvious return to 2D.
- Treat 3D as exploration and presentation, not the only way to inspect evidence.
- Fall back to 2D when WebGL is unavailable or reduced-motion constraints make 3D unsuitable.

### Performance and accessibility guardrails

- Aggregate individual reviews into evidence clusters for the default view.
- Cap the performance fixture at 400 visible nodes and 1,000 links.
- On the presentation laptop, 2D becomes interactive within 1.5 seconds after its payload is available.
- On the same fixture, pan/zoom targets at least 45 FPS median over a five-second measurement and filtered updates complete within 500 ms.
- Pause physics after settling; reheat only after data or drag changes.
- Cull labels and low-value edges outside the current zoom/focus context.
- The 3D bundle is not requested before the user activates 3D mode.
- A failed dynamic import or unavailable WebGL leaves 2D active and preserves cohort and selected IDs.
- Keep the evidence side panel as semantic DOM with full text and controls.
- Provide a searchable table/list alternative containing the exact same filtered node IDs as the visual graph.
- Do not encode status by color alone.
- Respect reduced motion and provide keyboard access to search, filters, evidence, and actions.

## 7. Visual system

### Core tokens

- Background: `#0B0B0B`.
- Elevated surface: `#151515`.
- Secondary surface: `#1C1C1A`.
- Border: `#2A2A28`.
- Primary text: `#F5F5F2`.
- Muted text: `#A3A3A3`.
- Brand accent/primary action/current focus: `#FFE500`.
- Text on yellow: `#111100`.
- Critical: coral/red, separate from brand yellow.
- Positive: green.
- Informational: blue.

Use yellow on roughly 8–12% of the interface. Large yellow surfaces reduce hierarchy and make warning states ambiguous.

### Chart semantics

- Guardian series: `#FFE500`.
- Competitors: distinct cyan and lavender hues, always paired with text labels.
- Baseline/reference: neutral gray.
- Negative and positive states use separate status colors.
- Every chart has a visible cohort, sample size, and evidence entry point.

### Layout priority

- Desktop-first for the hackathon presentation.
- 1280–1440px is the primary demo width.
- Tablet remains functional.
- Mobile is a readable stacked summary, not the primary graph interaction surface.

## 8. Recommended technical foundation

### Stack

- Bun as package manager and task runner.
- Vite + React + TypeScript for a client-heavy mock-first dashboard.
- React Router for explicit feature routes.
- Tailwind CSS plus CSS custom-property design tokens.
- Accessible headless primitives and Lucide icons.
- Recharts for conventional trend and benchmark charts.
- `d3-force` plus small D3 modules for canvas graph interaction and geometry.
- `3d-force-graph` for the on-demand 3D mode.
- Zod for runtime validation of mock and future API payloads.
- Vitest + React Testing Library for behavior and data-contract tests.
- Playwright for the critical demo journey and visual regression checks.

Vite is preferred over an SSR framework because the current product is a client-heavy hackathon dashboard, the graph is browser-only, and no SEO or server rendering requirement exists. The repository boundary preserves a clean backend migration path.

### Suggested feature structure

```text
src/
  app/                  # router, shell, providers, global filters
  domain/               # canonical entities and schemas
  data/
    repositories/       # interfaces and future HTTP implementation
    mock/               # seeded generator, scenarios, mock repository
  features/
    command-center/
    signals/
    investigation/
    network/
      graph-core/       # shared graph types and adapters
      graph-2d/         # force simulation and canvas renderer
      graph-3d/         # lazy 3d-force-graph adapter
    benchmark/
    executive-brief/
    actions/
  components/           # shared UI only
  styles/               # tokens and global styles
  test/                 # fixtures and critical-path helpers
```

Global filters live in URL search parameters so a cohort is shareable and refresh-safe. Canvas selection and hover remain local feature state. Avoid adding a global state library until cross-route action state proves it necessary.

## 9. Delivery phases

### Scope priority

**Critical path:** seeded canonical data, Command Center top signal, Investigation, evidence-linked 2D graph, cohort-safe benchmark, action workflow, current Executive Brief, and synthetic-data disclosure.

**Committed presentation layer:** 3D graph mode after the complete 2D investigation path works. It is part of the planned build but must not block the evidence-to-action workflow.

**First cuts if time compresses:** standalone Data Coverage route, export/print, elaborate 3D node assets, saved brief presets, and replay animation polish. Do not cut evidence traceability or benchmark guardrails.

### Phase 0 — visual direction gate

- Produce exactly three visual directions for the Command Center and Investigation Workspace.
- Select one direction before scaffolding UI.
- Lock typography, density, navigation, card hierarchy, and graph panel treatment.
- Timebox this to one decision round; visual exploration must not become an open-ended pre-build phase.

**Done when:** one visual target is selected and its design tokens are documented.

### Phase 1 — packaging evidence-to-action vertical slice

- Scaffold Vite/React/TypeScript and route shell.
- Add design tokens including `#FFE500`.
- Define canonical source/feedback schemas, immutable graph IDs, and repository interfaces.
- Build only the seeded packaging-leakage scenario first.
- Lock `asOf`, deduplication, signal math, benchmark cohorts, and fixed-fixture tests.
- Build the Command Center top signal and its Investigation Workspace.
- Add the raw evidence feed and a minimal evidence-linked 2D graph.
- Add the comparable Watsons benchmark.
- Add the prefilled action flow and current Executive Brief with live linked action state.
- Persist action state, then add the one-click demo reset.

**Done when:** the packaging evidence-to-action slice works from top signal to current Brief, the three-activation action test passes, and all headline figures match the locked fixture after refresh/reset. Outcome evaluation is added in Phase 3.

### Phase 2 — graph hardening and 3D mode

- Complete the 2D force simulation and layered canvas renderer.
- Add zoom, pan, hover, select, drag/pin, search, filters, path highlight, and evidence drill-down.
- Add the full Network route and semantic DOM entity list.
- Enforce the 400-node/1,000-link performance fixture.
- Add deep-cloned 2D/3D adapters over the immutable canonical graph.
- Add lazy `3d-force-graph`, synchronized IDs/filter state, and WebGL/import fallback.

**Done when:** 2D meets the performance/accessibility gates, 3D is not fetched before activation, and repeated 2D↔3D switches preserve identical filtered ID sets and selection without mutating canonical data.

### Phase 3 — product breadth and outcome monitoring

- Build the standalone Signal Inbox and remaining global filters.
- Add the voucher-failure and positive click-and-collect scenarios.
- Add action lifecycle details and the seeded 48-hour monitoring outcome.
- Add immutable Daily/Weekly Brief versions with live linked action state.
- Add Hasaki and broader cohort-safe competitor views.

**Done when:** each scenario has distinct evidence and decision logic, and advancing the demo clock evaluates the monitoring target without rewriting historical Brief metrics.

### Phase 4 — demo polish and QA

- Add deterministic incident replay rather than fake live ingestion.
- Add empty, error, no-evidence, insufficient-baseline, and insufficient-sample states.
- Test responsive behavior, reduced motion, keyboard workflow, and contrast.
- Verify graph timing/FPS on the actual presentation laptop.
- Prepare a four-minute scripted run and a fallback static route.
- Repeat the demo three times from reset.

**Done when:** the complete demo repeats with identical source figures, state transitions, and no manual repair.

### Phase 5 — stretch surfaces only

- Add standalone Data Coverage using synthetic provenance and deduplication metrics.
- Add saved Brief presets and export/print.
- Add richer 3D node assets only if they do not reduce clarity or performance.

**Done when:** each stretch surface passes the same evidence, provenance, and synthetic-data disclosure rules as the critical path.

## 10. Acceptance criteria

- Command Center answers “what changed and what needs action” without more than four primary KPI cards.
- Every insight displays time range, sample size, source coverage, confidence, and evidence count.
- Clicking a metric, chart point, graph node, graph edge, or brief claim opens the correct underlying evidence.
- Global filters yield the same cohort across trend, evidence, graph, and benchmark.
- The locked fixture computes Guardian packaging share at 17.0%, baseline at 5.0%, velocity at 3.4×, and the Watsons gap at +10.3 percentage points.
- Incomparable, incomplete-baseline, or under-30 competitor cohorts receive no rank and explain the exact missing requirement.
- Root cause is always labeled as a hypothesis and includes supporting and contradicting evidence.
- Severity and confidence are visibly separate.
- 2D graph supports zoom, pan, hover, select, drag/pin, search, type filter, and evidence drill-down.
- The 400-node/1,000-link 2D fixture is interactive within 1.5 seconds, maintains at least 45 FPS median pan/zoom over five seconds, and applies a filter within 500 ms on the presentation laptop.
- The DOM graph alternative exposes the exact same filtered node ID set as the canvas.
- Repeated 2D↔3D switches preserve filtered canonical IDs and selection while renderer coordinates remain isolated.
- The 3D chunk is not fetched before activation; import/WebGL failure leaves 2D usable without losing cohort or selection.
- 3D is not required to complete the investigation workflow.
- Starting from the default Command Center, the E2E path activates top signal → prefilled action → confirm; the resulting action is visible in Signal, Command Center, and the current Brief.
- The same action record persists across route navigation and refresh; reset removes it and restores the seeded state.
- Historical Brief metrics/evidence stay immutable while the current Brief joins live actions by included `signalId`, including actions created after the snapshot.
- Advancing the seeded 48-hour window evaluates the monitoring target: `passing` offers a Resolve action, `failing` shows the missed target, and `insufficient_sample` stays neutral; all remain `Monitoring` until user confirmation produces `Resolved`.
- Refresh and demo reset preserve deterministic source figures and the fixed `asOf` behavior.
- All routes display `Synthetic demo data` until the production adapter is active.
- Empty, no-evidence, insufficient-baseline, and insufficient-sample states are explicit.
- Guardian graph identity uses a labeled shield/shape while the yellow ring means selection only; no state or identity relies on color alone.
- Yellow brand accents and status colors meet contrast requirements and are not the only status cue.

## 11. Explicit non-goals for the first build

- Real marketplace, social, customer-service, or Guardian data ingestion.
- Production authentication, multitenancy, permissions, and audit logs.
- Training or evaluating a production sentiment/topic model.
- Claiming revenue impact without transaction/order data.
- A general-purpose AI chatbot.
- Automated external actions or messages to stores/customers.
- Perfect mobile graph interaction.

The stated 70–80% reporting-effort reduction remains a target from the challenge brief, not a validated product outcome from synthetic data.

## 12. Four-minute demo narrative

1. **0:00–0:30 — Morning Brief:** packaging complaints increased 3.4× over 72 hours.
2. **0:30–1:10 — Investigation:** spike starts after a campaign and concentrates in two SKUs and online channels.
3. **1:10–1:55 — Evidence graph:** “leaking,” “loose cap,” and “wet box” connect to the same product/channel cluster; raw reviews open from the graph.
4. **1:55–2:20 — 3D exploration:** switch to the shared network to show cross-channel relationships, then return to 2D.
5. **2:20–2:50 — Benchmark:** Guardian has a larger packaging complaint share than the same Watsons cohort, with sample sizes visible.
6. **2:50–3:30 — Action:** assign E-commerce Ops to audit sealing/protective wrap for the two SKUs and monitor for 48 hours.
7. **3:30–4:00 — Executive loop:** the Brief updates with the issue, decision, owner, deadline, and monitoring state.
