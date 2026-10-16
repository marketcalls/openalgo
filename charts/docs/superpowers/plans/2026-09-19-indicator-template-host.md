# Indicator templates in the trading host

> **For agentic workers:** Use superpowers:executing-plans with the user's authorized continuous native execution. Validate each task and commit locally.

**Goal:** Make named indicator templates usable in the actual `/trading` workspace, preserving study instances, settings, visibility and grouping across symbols and reloads.

**Architecture:** The packed workspace tier owns portable documents and catalog transactions. Small consumer helpers prepare study lists and migrate pane-local records; `TradingTerminal` applies them to its current chart with ownership guards. A page-level template dialog uses an account-bound repository and targets the focused terminal. Named workspace controls will reuse this catalog hook in the next phase.

**Tech Stack:** TypeScript, React, existing Dialog/Input/Button components, Vitest, actual-chart browser compatibility harness, IndexedDB adapter from chart source `566858e`.

**Spec:** `docs/superpowers/specs/2026-09-19-production-workspace-design.md` (F2 and the shared F1/P4 persistence boundary).

## Global constraints

- No comparison product names in changes, commit messages or PR material.
- UTC seconds for engine data; catalog metadata uses epoch milliseconds.
- Workspace files never contain credentials, orders, positions, account balances or the armed flag.
- Replay remains isolated from the live feed. Templates operate on the displayed prefix and cannot refill future bars.
- Keep host DOM out of engine tiers. Preserve existing library defaults and broker execution authority.
- Validate the packed candidate in the isolated OpenAlgo worktree. Local commits only; no publishing or live orders.

## Review focus

- A template contains an unavailable custom descriptor: report all missing IDs before removing any current study.
- The focused chart is destroyed or replaced while the custom indicator module loads: abandon the stale operation without mutating its successor.
- Two identical studies or two oscillators sharing a pane: retain each instance and grouping after template apply, interval rebuild and browser reload.
- An account changes during a pending save: the old namespace retains its write and the new account receives no stale success notification or document list.
- Storage rejects a save or the user imports malformed input: leave the old catalog intact and show the error; never report a successful save.

## Task 1: Study planning, persistence migration and terminal application

Consumer files:

- Create `frontend/src/lib/trading/indicatorTemplates.ts` and `.test.ts`.
- Modify `frontend/src/lib/trading/terminal.ts` and `terminal.test.ts`.

Interfaces:

```ts
type IndicatorTemplateMode = 'replace' | 'append';
type StoredIndicatorRecord = {
  indicatorId: string; settings: Record<string, unknown>;
  visible?: boolean; paneIndex?: number;
};
function readStoredIndicators(input: unknown): StoredIndicatorRecord[];
function planIndicatorTemplate(
  current: IndicatorState[], incoming: IndicatorState[],
  mode: IndicatorTemplateMode, available: ReadonlySet<string>,
  nextPaneIndex: number,
): IndicatorState[];

// Public methods on TradingTerminal:
captureIndicatorTemplate(): IndicatorState[];
applyIndicatorTemplate(input: IndicatorState[], mode: IndicatorTemplateMode): Promise<void>;
```

`readStoredIndicators` accepts the legacy array or `{ version: 2, indicators }`.
Legacy arrays retain the old exact-duplicate healing policy, but modern version-2
records preserve repeated instances and pane indices. Malformed envelopes reject;
the existing terminal restore catch handles unreadable old local preferences.
Modern record writes contain no credentials and use the workspace parser.

`planIndicatorTemplate` validates and detaches both arrays, rejects unsupported
modes and missing descriptor IDs before returning. Replace returns incoming
instances. Append keeps current instances and moves each positive incoming pane
index to a new pane beginning at `nextPaneIndex`; equal incoming indices remain
together. Pane zero remains the primary chart. Limit the combined list to 256
instances and the target pane indices to the document limit (31). Do not merge
instances because their parameters happen to match.

- [x] Add pure regressions with two equal EMA instances, two different EMA periods,
  shared oscillator panes, empty replace/append, unknown IDs, invalid mode, size
  bounds, detached settings and legacy/version-2 persistence:

```ts
const duplicate = { indicatorId: 'ema', settings: { period: 9 }, paneIndex: 0 };
const result = planIndicatorTemplate([], [duplicate, duplicate], 'replace', new Set(['ema']), 1);
expect(result).toHaveLength(2);
expect(result[0]).not.toBe(result[1]);
expect(() => planIndicatorTemplate([duplicate], [{ ...duplicate, indicatorId: 'missing' }],
  'replace', new Set(['ema']), 1)).toThrow(/missing/);
```

- [x] Run `npm run test:run -- src/lib/trading/indicatorTemplates.test.ts --maxWorkers=2` in the consumer frontend. Expected RED: helper module absent.
- [x] Implement the planner and migration helper. Preserve the existing public `dedupeIndicators` helper for legacy migration callers/tests; remove its use from modern automatic restoration.
- [x] Extend tracked indicator records with optional paneIndex. Read versioned records in `restoreChartTools`; include actual `IndicatorApi.paneIndex` in synchronization and write the version-2 envelope. `applyIndicators` passes paneIndex when present and retains all modern records. Existing saved arrays still load.
- [x] Add terminal regression tests for captured pane placement and visibility, missing custom IDs preserving current instances, stale chart ownership after deferred module loading, and suppression of intermediate `syncIndicators` while replacing.
- [x] Implement capture by parsing `chart.getState().indicators ?? []`. Apply snapshots the current chart before `await loadIndicators()`, rejects if it is destroyed/replaced afterward, plans against registered descriptors and current panes, and calls `chart.restoreState({ version: 1, indicators: planned })` under `applyingIndicators`. On a thrown restore, restore the previous indicator list and surface the failure. Always release the guard and sync the final current chart. No price-series, viewport, drawings or order state is restored here.
- [x] Run both files and the existing trading suite. Expected GREEN; no duplicate study after an async rebuild. Commit locally.

## Task 2: Account-bound catalog hook

Consumer files: `frontend/src/hooks/useChartWorkspaceCatalog.ts` and `.test.tsx`.

Interface:

```ts
interface ChartWorkspaceCatalogState {
  catalog: WorkspaceCatalog | null;
  loading: boolean; pending: boolean; error: string | null;
  reload(): Promise<void>;
  run<T>(operation: (repository: WorkspaceRepository) => Promise<T>): Promise<T>;
}
function useChartWorkspaceCatalog(
  account: string | null,
  storageFactory?: () => IndexedDbWorkspaceStorage,
): ChartWorkspaceCatalogState;
```

The default factory injects `window.indexedDB` into the package adapter. The
namespace is `oa-trading:${account}`; it contains no API key. Instantiate in an
effect, not during render. Cleanup closes the owned adapter and invalidates UI
completion ownership. A null account creates no repository. `run` propagates
operation errors, reloads the catalog after a successful mutation, and updates UI
only for the current account. Reject a completion belonging to an obsolete
account so its caller cannot show a success message in the new session. Count
pending operations rather than allowing the first completion to clear another
operation's busy flag. StrictMode cleanup must not reuse a closed adapter.

- [x] Write hook tests with the real repository and an async in-memory CAS storage
  adapter: initial loading, saved template appears, failure leaves previous list,
  failed write followed by retry, two pending operations, account switch during a
  deferred write, unmount, absent IndexedDB, and StrictMode remount.
- [x] Run the new hook suite. Expected RED: hook absent.
- [x] Implement the hook with the ownership/cleanup behavior above, then run the
  hook suite and consumer lint/type build. Expected GREEN. Commit locally.

## Task 3: Focused-chart template dialog

Consumer files:

- Create `frontend/src/components/trading/IndicatorTemplates.tsx` and `.test.tsx`.
- Modify `frontend/src/pages/Trading.tsx` to supply account identity, the shared
  catalog hook and `panelTarget()`.

Props carry `catalog`, `loading`, `pending`, `error`, `run`, and
`target(): TradingTerminal | null`; the component does not read API keys or own
market-data transport. Place one `Templates` button alongside the workspace
layout/sync control, with text identifying that it acts on the selected chart.
Keep this control singular when a grid has several panes; F9 will relocate all
shared actions together.

- [x] Write component interaction tests for saving current studies with a name,
  applying to the currently focused target, replace versus append, empty replace,
  rename/duplicate/delete, file export/import, loading/no-chart states and a
  rejected save. Assert user-visible results through the actual component.
- [x] Run the new component tests. Expected RED: component absent.
- [x] Render saved templates in a labelled Dialog with native text inputs and
  explicit `Replace studies` / `Add studies` actions. Use repository operations
  for CRUD and portable JSON. Import only `indicator-template` documents in this
  dialog; parse before writing. File input accepts JSON and handles rejected or
  oversized files with visible feedback. Clear browser object URLs after export.
  Buttons follow pending/loading state; an error leaves the dialog open and keeps
  the user's entered name. Empty templates display `No studies` and remain usable.
- [x] Connect the one dialog to `useAuthStore`'s current username and focused
  terminal. Capture/apply errors use existing host feedback. Do not capture
  execution state or change the One-Click preference.
- [x] Run component/hook/trading suites and build. Expected GREEN. Commit locally.

## Task 4: Actual-chart browser gate and guide

Library files: `scripts/check-openalgo-compat.mjs` (opt-in `--templates true`) and
the master ledger. Consumer file: `docs/userguide/trading.md` (locate existing guide
before updating; use the existing trading guide if its path differs).

- [x] Before terminal/UI implementation is complete, add an actual `/trading`
  failing browser check that saves two identical studies and an oscillator
  template, switches the focused symbol, replaces its studies, reloads and asserts
  instance count/settings/visibility/pane placement from real engine snapshots.
  Add missing-custom/empty-template and storage-rejection checks. Expected RED
  against the prior consumer because the Templates control is absent.
- [x] After implementation, run the checks in Chromium, Firefox and WebKit with
  the packed candidate. Verify template actions preserve primary bar count and
  viewport, do not send order mutations, and operate only on the focused chart.
  Record screenshots and inspect desktop plus a narrow viewport. Expected GREEN.
- [x] Update the user guide with save/apply/append/replace, custom-study errors,
  private per-account browser storage and portable imports. Run affected checks,
  full consumer lint and build; record exact evidence and commit locally.

## Preflight and retained scope

Task 1 produces terminal capture/application and modern indicator persistence for
Task 3. Task 2 produces catalog state and transaction ownership for Task 3. Both
use the existing package document types and repository without new package APIs.
The host's legacy `SavedIndicatorRecord` lacks pane placement and currently
deduplicates every rebuild; Task 1 explicitly migrates this boundary.

This phase completes the consumer F2 flow, not the whole goal. F1 named full-grid
controls/restoration, the reference host's matching controls, F7 comparison,
F8 shared replay, F9 consolidated toolbar and P1-P6 remain required. Existing
real-session handoff work continues separately and cannot be replaced with fixture
claims. The complete spec remains the completion authority.
