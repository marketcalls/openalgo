# Chart data export implementation plan

> **For agentic workers:** Use superpowers:executing-plans with authorized continuous native execution. No implementer subagents. Validate and commit locally.

**Goal:** Complete the chart-data download shown in the supplied workspace image, with a reusable CSV API and working reference/widget controls.

**Architecture:** Add a DOM-free base export helper that reads the chart's current primary bars, declared study plots and aligned comparison handles. Hosts capture chart ownership before opening controls and download the returned text through their existing browser file patterns. No history fetch or replay-source access is needed.

**Tech Stack:** TypeScript base helper, JavaScript reference host, widget capture menu, Vitest and three-engine Playwright checks.

**Spec:** `docs/superpowers/specs/2026-09-19-production-workspace-design.md`, the image-described data download and F9 selected-chart ownership.

## Global constraints

- No comparison product names, new icons, emoji or em/en dashes in changes.
- Preserve original OI edits and consumer work; Charts publishes before remaining consumer integration.
- Export UTC seconds and unrounded numeric values. Missing/nonfinite observations are blank; zero OI remains zero. Do not aggregate bars.
- Export only currently installed primary rows, including the revealed replay prefix. Do not export credentials, trading state or future bars.
- Keep engine tiers DOM-free and existing defaults unchanged. Measure additive bundle cost.

## Rulings and review focus

- Export all loaded primary bars, not just the visible viewport. Include hidden study plots because visibility does not remove the configured study. A caller can omit studies explicitly.
- Declared plot columns include stable instance identity and plot key, so repeated studies remain distinguishable. Export computed values at their input row, before visual plot offsets.
- Comparisons export eligible aligned closes in their original price units, with missing baselines/calendar/replay observations blank. Default handles come from the existing chart comparison registry without creating a controller; explicitly constructed controllers can supply their handles.
- Fixed numeric row fields and prefixed, CSV-escaped headers prevent spreadsheet formulas through custom plot/symbol text. Finite numbers stay numeric.
- A menu must retain its original chart/source when focus changes and reject after source replacement/loading. Download failures must be visible.

## Task 1: Reusable numeric CSV snapshot

Files: add `src/model/chart-data-export.ts`, `tests/chart-data-export.test.ts`;
modify `src/index.ts`, `src/compare/controller.ts`, core skill reference and a
focused export guide. Export `exportChartDataCsv` and `ChartDataCsvOptions`.

- [x] Add failing cases for OHLC/volume/OI, blanks versus zero, precision,
  repeated/hidden/custom plots, quoted/newline headers, same-turn live updates,
  transformed primary rows, empty charts, comparison gaps and replay prefixes.
- [x] Implement the serializer using current chart data and declared plots.
  Read existing comparison handles without changing chart/controller lifecycle.
  Permit explicitly supplied comparison handles and optional study omission.
- [x] Run focused tests and package verification. Update API/skill docs, measure
  bundle cost, and record results before committing.

Task 1 evidence: nine CSV cases initially fail before the module exists. The
focused CSV/comparison sweep passes all 44 cases after implementation. Full
`npm run verify` passes 5600 engine tests/235 files, 379 reference tests/29 files,
lint/types/build/declarations/size/tree-shaking. Base is 89.40 kB, base/trade 97.01,
terminal 201.25 and all tiers 240.25 kB Brotli, within existing budgets. Chart-only
tree-shaking stays 52.30 KiB. API generation is warning-free; after rebuilding,
skills coverage passes 920/920. No budget increases were required.

Initial validation corrected test fixture calls to the actual comparison options
and replay stop API. A nonexistent docs script was replaced with `npm run docs`.
Only terminal successful runs count above. Task 2 remains unimplemented at this
checkpoint; the export helper alone is not the user-facing download.

## Task 2: Captured-chart downloads in the reference and widget

Files: add `examples/yfinance/src/chart-data.js` and its tests; update reference
snapshot/workspace controls, module inventory and README. Update widget topbar
capture controls and docs. Add browser cases using actual downloaded CSV files.

- [x] Add failing owner/loading/failure cases and UI download cases.
- [x] Connect a plain Download chart data control in the reference Layouts
  dialog and snapshot menu, retaining the selected chart at menu open. Reject
  changed or unavailable sources; permit the active replay prefix.
- [x] Add the widget CSV capture item with current-source checks and visible
  download errors. Use the same library serializer.
- [x] Verify selected chart, OI, studies, comparisons, replay, stale ownership,
  fullscreen/narrow controls and downloaded contents across three browsers.
  Run full affected suites, inspect screenshots, update ledger/handover and commit.

The overall goal remains open after this plan: P1-P6, endurance, whole-branch
review, Charts release and remaining consumer integration still require evidence.

Task 2 evidence: owner/loading/failure fixtures and actual browser downloads failed
before the controls existed. The final package run passes lint/types, 5601 engine
tests/235 files, 387 reference tests/30 files, build and declarations. It stops at
the combined size gate, exceeding its old budget by four bytes. After the recorded
budget adjustment, size, tree-shaking and skills coverage (920/920) all pass.
The prior affected browser sweep passes 175 cases. The final CSV sweep passes 12
cases in Chromium, Firefox and WebKit, including transformed data, captured chart
ownership, OI zero, studies, comparisons, replay prefixes and failed downloads.
Wide/narrow reference controls and all three widget screenshots were inspected.

Initial browser widget selectors incorrectly requested menuitem instead of the
existing menuitemradio role. A transform filename regression exposed the host's
renderer name instead of the selected transform; the corrected name passes its
unit and browser cases. Screenshot review caught a truncated CSV action label;
removing its redundant subtitle makes the full label readable in all engines.

Ruling: increase the widget budget from 46.75 to 47 kB and the combined budget
from 240.5 to 241 kB for the measured CSV controls. Current widget is 46.83 kB,
terminal 201.51 kB and combined 240.504 kB. Base 89.40 kB, workspace 5.53 kB and
chart-only 52.30 KiB remain unchanged. The full verify command did not exit zero;
its completed checks plus the successful resumed size/shake gates are the evidence.
API generation is warning-free. Publication and final release facts remain P6.

Task 2 committed as 977fbd1. The website production build also passes.
