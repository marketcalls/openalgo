# Reference layout startup implementation plan

> **For agentic workers:** Use superpowers:executing-plans for the authorized continuous native implementation. One whole-branch review remains near release.

**Goal:** Restore the primary reference chart's saved request, chart type and timezone before its first history request, as a prerequisite for complete named layouts.

**Architecture:** Extend the existing additive schema-2 wrapper with explicit primary selection fields. Validate them in the existing persistence boundary, recover unambiguous legacy dataset keys, and initialize host controls before loading. Keep the existing engine-state and secondary restoration paths.

**Tech Stack:** Reference JavaScript modules, current interval/type catalogs, Vitest and three-engine Playwright coverage.

**Spec:** `../specs/2026-09-19-production-workspace-design.md`, F1. This prerequisite does not replace named catalog controls, transactional workspace switching, F2 templates or the remaining production requirements.

## Global constraints

- Preserve original worktrees, OI edits and the isolated consumer.
- No comparison product names, new icons or long dash characters in additions.
- Workspace snapshots contain configuration, not credentials, orders or positions.
- Existing schema-1/2 documents remain readable. Optional fields do not require a schema bump.
- Charts2.4.5 publishes before remaining /trading work and final broker validation.

## Review focus

1. A saved primary request must be the first network request after reload.
2. Calendar folding must use the saved timezone on that first request.
3. Invalid explicit fields must be rejected before changing controls or making requests.
4. Old dataset strings may be recovered only when their three fields are unambiguous and supported.
5. Transformed chart selection and its box mode must survive independently of the renderer's series type.

## Task 1: Complete primary selection persistence

Files: modify `examples/yfinance/src/persist.js`, `main.js`, reference README and
`examples/yfinance/tests/persist.test.js`; add focused browser coverage in
`tests/e2e/yfinance-mobile.spec.ts`.

Interfaces:

```js
// Pure selection reader; throws LayoutError for invalid explicit metadata.
// Legacy documents without recoverable request metadata return request:null.
primaryLayoutSelection(doc); // { request, chartType, pfmode, timezone }
// Validate first, then initialize the host's controls and timezone.
restorePrimarySelection(doc = readLayout()); // boolean
// layoutSnapshot adds request:{symbol,interval,period}, chartType and pfmode.
```

- [x] Add regressions for explicit snapshot fields, legacy recovery, unsupported
  request/type/zone rejection and no partial control writes.

```js
const before = { symbol: 'AAPL', interval: '1d', period: '1y' };
const saved = { version: 1, schema: 2, request: { symbol: 'TSLA', interval: '15m', period: '1mo' },
  chartType: 't:point-figure', pfmode: 'percent', timezone: 'America/New_York' };
expect(primaryLayoutSelection(saved).request.symbol).toBe('TSLA');
expect(() => primaryLayoutSelection({ ...saved, chartType: 'unknown' })).toThrow();
```

- [x] Run the affected persistence suite and observe missing behavior. Add a
  browser reload case changing primary symbol/interval/type and verify the first
  request and restored chart; add a calendar-zone first-load case.
- [x] Implement the selection reader using existing interval/type catalogs.
  Explicit metadata is authoritative; invalid explicit metadata cannot fall
  through to a legacy key. Keep legacy state-only documents usable.
- [x] Add selection fields to snapshots, validate them through upgradeLayout,
  and call restorePrimarySelection after fillIntervalSelect but before load.
  Preserve the engine's later drawing-before-alert and secondary restore order.
- [x] Run all example tests, affected three-engine browser checks and lint/types.
  Inspect rendered evidence, update example documentation and the main ledger,
  then commit locally. No library bundle changes are expected.

## Validation evidence

Five persistence cases failed before the fix, with 25 existing cases passing.
Both browser regressions fetched AAPL/1d/1y instead of the saved primary source.
After the fix, all 30 persistence cases and all 302 reference tests in 24 files
pass. Lint and typecheck pass. The full reference browser sweep passes 97 cases
across Chromium, Firefox and WebKit. Restored TSLA, 15-minute selection, point
and figure rendering and timezone screenshots were inspected in all three.

The first focused browser run passed five cases but one Chromium page timed out
during initial startup, before the tested restore action. Its trace-enabled
isolated rerun passed both cases without code changes; the complete browser sweep
also passed without retry. The original failure is retained, with no confirmed
cause inferred from the retry. Logs are under artifacts/candidate/layout-startup-*
and are not shipped. No library source, bundle size or consumer dependency changed.

## Following work

Named catalogs still need create/save/open/rename/duplicate/delete/recent,
autosave and import/export controls with staged history and failed-write handling.
F2 templates still need a focused-owner picker with replace/append semantics,
repeated/custom studies and style/grouping preservation. Continue those phases
after this independently verifiable restoration prerequisite.
