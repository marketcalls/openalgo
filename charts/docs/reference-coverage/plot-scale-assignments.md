# Per-plot scale assignments

Indicator templates need to represent studies whose plots use different scales, including plots explicitly drawn on the price pane. A whole-study override cannot express these bindings. This prerequisite adds native per-plot assignments; the subsequent [indicator template layouts](template-layouts.md) batch adds portable pane metadata and copy ownership.

## Contract

- `IndicatorApi.plotPriceScaleId(plotKey)` returns a declared plot's effective scale ID, or null for an unknown plot.
- `IndicatorApi.plotPriceScaleIds()` returns a detached map of explicit per-plot overrides.
- `IndicatorApi.setPlotPriceScales(assignments)` applies a partial map atomically. A null value clears that plot's override. Empty or unchanged patches return false. Unknown keys, invalid IDs, accessor properties and incompatible fill endpoints are rejected without changing resources.
- Effective precedence is per-plot override, local whole-study override, descriptor assignment, then `right`. Explicit price-pane plots ignore the whole-study override.
- A successful whole-study `setPriceScale` clears local per-plot overrides. It preserves explicit price-pane assignments. Passing null restores local descriptor assignments.
- Fill endpoints must use the same pane and scale. Related plots can be moved together in one patch. Levels and unbound price drawings follow the first local plot; series markers follow their bound plot.
- Untouched scales retain their formatting. Plots joining a destination apply explicit formats in descriptor order. An explicit price format replaces a previous percent or volume formatter with the chart's price formatter.
- `Chart.addIndicator` accepts optional `plotPriceScaleIds`. Invalid maps and conflicting fills fail before allocating chart resources.
- `IndicatorState.plotPriceScaleIds` persists explicit overrides. Chart restore validates known descriptors before mutation. Workspace and legacy template parsing retain structurally valid maps without requiring a loaded registry.
- Omitted maps retain existing behavior. The existing script adapter requires no upgrade. No feed adapter is introduced.

## Implementation and verification

1. Add failing real-chart tests for mixed scales, explicit overlays, atomic fill moves, invalid construction and state round trips.
2. Extend `src/model/indicator-instance.ts` with validated maps and one assignment transaction. Keep range ownership, primitive bindings, legend formatting and plot recreation synchronized.
3. Extend `src/core/chart.ts` and `src/model/chart-state.ts` for construction and preflight restore. Preserve the legacy whole-axis move restrictions until all primitive relationships can be represented safely.
4. Extend `src/workspace/documents.ts` and workspace/template regression tests to retain detached maps and reject malformed input.
5. Document public methods, add an executable website example, and test the built example in three browser engines with inspected screenshots.
6. Run package verification, public documentation generation, skills coverage and the pinned script-engine integration. Measure bundle changes before adjusting budgets. Review the diff before committing.

Review focuses on a fill whose endpoints are patched separately, explicit overlays from a study in another pane, first-local-plot range ownership, settings-driven plot recreation, and mutation of caller-owned state after validation.

## Completed verification

The implementation passes full package verification with 7,193 unit tests, 436 example-host tests and seven endurance-harness checks. Seventeen compiled-program checks pass with the existing adapter. Fifteen browser cases cover assignments, exact restored pixels, the documented controls and the original autofit regression in three engines. The built website passes 60 desktop/mobile states with its displayed units checked and screenshots inspected.

Review regressions cover malformed saved fields, empty maps, callback failures and reentry, unrelated formatter preservation and price formatting after a shared percent scale. API generation passes with warnings treated as errors. This batch measured 108.87 kB Brotli for the base bundle and 67.99 KiB for chart-only imports. Current measurements and subsequent template layout validation are recorded in [progress.json](progress.json).
