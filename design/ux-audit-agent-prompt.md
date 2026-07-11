# Independent UX and requirement audit prompt

You are a strict Principal Product Designer and Voice-of-Customer product lead. Audit the current Guardian Command Center independently. Do not modify code, do not propose implementation details unless they clarify a recommendation, and do not trust earlier QA conclusions.

## Product intent

This is meant to be a Guardian Voice of Customer intelligence platform, not a generic analytics dashboard.

The requirement screenshot is:

`/Users/bao/Library/Metadata/CoreSpotlight/PasteboardHistory/2026-07-11_14-32-34.png`

It describes these requirements:

- Feedback arrives continuously from marketplaces, Guardian e-commerce, customer service, and social/community channels.
- Data is fragmented; Guardian needs one centralized, holistic view.
- Reporting is manual and reactive; the product should expose sentiment, recurring issues, and emerging trends quickly.
- Guardian needs competitor benchmarking against Hasaki and Watsons.
- AI capabilities include ingestion, structured/unstructured consolidation, sentiment analysis, topic and intent classification, trend analysis, root-cause identification, automated insights, real-time dashboards, executive summaries, proactive alerts, and competitive benchmarking.
- Visible expected outcomes include reducing manual analysis by 70–80%, a single real-time cross-channel view, proactive identification of issues/root causes, faster data-driven CX improvement, competitor benchmarking, and improved customer satisfaction. If text is cropped in the screenshot, mark it unverifiable rather than inventing it.

## Current product evidence

Inspect all of these current-run screenshots:

1. `/Users/bao/GitHub/aabw-project-guardian/design/audit-2026-07-11-voc/01-overview.png`
2. `/Users/bao/GitHub/aabw-project-guardian/design/audit-2026-07-11-voc/02-product-breakdown.png`
3. `/Users/bao/GitHub/aabw-project-guardian/design/audit-2026-07-11-voc/03-constellation.png`

Inspect the real implementation and data derivation:

- `/Users/bao/GitHub/aabw-project-guardian/src/App.tsx`
- `/Users/bao/GitHub/aabw-project-guardian/src/components/VisualDashboard.tsx`
- `/Users/bao/GitHub/aabw-project-guardian/src/data/dashboard.ts`
- `/Users/bao/GitHub/aabw-project-guardian/src/styles.css`

Current route: `http://127.0.0.1:4173/?products=all`

## Core audit questions

1. Five-second test: without prior context, can a Guardian operator immediately answer:
   - What product or product family is this about?
   - What exactly is wrong?
   - How severe and recent is it?
   - Which customer channels support the conclusion?
   - What should I do next?
2. Is `All products` a useful executive default, or does it hide the two sunscreen SKUs driving the alert?
3. Does the above-the-fold hierarchy prioritize the most decision-relevant information, or does it lead with an abstract diagnosis before product identity and evidence scope?
4. For every chart, state the exact user question it answers. Flag charts that are decorative, redundant, lack denominators, use unclear labels, or cannot support the implied conclusion.
5. Does the 2D/3D constellation improve an investigation? Can users identify nodes and relationships without hovering? Is 3D useful or mainly spectacle?
6. Are “84% confidence”, “Spike crossed baseline at 36h”, “real-time”, and competitor comparisons sufficiently explained and trustworthy based on the real data code?
7. Does the dashboard cover the requirement screenshot, not merely resemble a reference dashboard?
8. What is missing for an executive summary, proactive alert workflow, sentiment, topic/intent classification, root-cause evidence, and outcome measurement?
9. Identify visible accessibility risks, but do not claim full WCAG compliance from screenshots.

## Required output

Use a blocker-first review. Findings must be ordered P0 → P3 and cite screenshot step plus exact source file/line where code evidence matters.

Return:

1. **Direct verdict**: `ready`, `promising but not ready`, or `not ready`, with two sentences maximum.
2. **Top findings**: severity, evidence, user impact, concrete recommendation.
3. **Five-second test scorecard**: each of the five questions above as Pass / Partial / Fail.
4. **Requirement coverage matrix** with `Met / Partial / Missing / Not measurable`, evidence, and gap for every requirement listed above.
5. **Chart usefulness review**: keep / change / remove for each visible chart and both 2D/3D modes.
6. **Recommended above-the-fold information architecture**: exact reading order and content, not a visual mock.
7. **What not to prioritize yet** so the team does not polish secondary visuals before product clarity is fixed.
8. **Evidence limits**.

Be critical and specific. A polished visual is not proof of useful UX or requirement coverage. Do not write code and do not edit any files.
