# Guardian VoC Figma redesign handoff

## Target file

- File: https://www.figma.com/design/PeUjIeBfM2FplWrBho6Sm4
- File key: `PeUjIeBfM2FplWrBho6Sm4`
- Run ID: `guardian-voc-figma-2026-07-11`
- State ledger: `/tmp/dsb-state-guardian-voc-figma-2026-07-11.json`

## Completed

- Phase 0 discovery and gap analysis.
- Three Starter-plan-safe pages:
  - `Cover` — page ID `0:1`
  - `Foundations + Components` — page ID `4:4`
  - `Screens` — page ID `4:5`
- Guardian Light-mode foundations:
  - `Guardian Color` — collection ID `VariableCollectionId:2:2`
  - `Guardian Size` — collection ID `VariableCollectionId:2:3`
  - 15 semantic color variables.
  - 13 spacing/radius variables.
  - 7 Inter text styles.
  - 1 `Shadow/Card` effect style.
- Cover frame ID `5:2` with decision-first narrative.

## Validation completed

- 28 total variables.
- No variables use `ALL_SCOPES`.
- No variables are missing WEB code syntax.
- All text styles resolve to Inter with available Figma font styles.

## Blocker

Figma MCP returned: `You've reached the Figma MCP tool call limit on the Starter plan.`

The failed screenshot call did not mutate the file. Do not claim the Cover or future screens are visually validated until screenshot calls succeed.

## Resume order

1. Screenshot and validate Cover frame `5:2`.
2. Build Foundations documentation on page `4:4`.
3. Build the minimal reusable dashboard components on page `4:4`.
4. Build three 1440px Light-mode screens on page `4:5`:
   - Overview
   - Review Detail
   - Product Detail
5. Screenshot each screen and inspect typography, wrapping, hierarchy, contrast, and overlap.
6. Add audit screenshots and redesign notes beside the three screen frames.

## Locked screen flow

`Overall health → important changes → raw negative reviews → next actions → product drill-down`

Graphs remain out of scope.
