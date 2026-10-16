# Named grid workspaces in the trading host

> Use superpowers:executing-plans with the user's continuous native execution authorization. Validate each boundary and commit locally.

**Goal:** Save, reopen and share the complete chart grid, including each chart's studies, drawings, view settings and instrument, without capturing execution state.

**Scope:** F1 and the account/persistence part of P4 from the production-workspace spec. The template catalog and account hook already exist. Comparison restoration will use the same pane boundary when F7 adds that controller; do not silently discard unsupported comparison documents in the interim. Reference-host controls, coordinated replay, the shared toolbar and every remaining production requirement remain in scope after this consumer phase.

## Architecture and invariants

- Use the packed `openalgo-charts/workspace` document and repository APIs, with `useChartWorkspaceCatalog` as the single account owner.
- Preserve unequal grid tracks as optional numeric row/column weights. Older documents omit them and retain equal tracks; recognized preset IDs alone must not override explicit geometry.
- Capture chart configuration through the engine state API and the terminal's host settings. Never serialize credentials, execution books, quantity/product preferences or One-Click state into a workspace.
- Prepare replacement panes separately while retaining the current grid. A hidden staging grid has measurable geometry, isolated temporary preferences, no user input and disabled link channels while loading. Publish it only after every pane has restored successfully. On failure, destroy staging resources and leave the old grid available.
- A workspace operation belongs to its account and generation. Closing the page, changing account, or starting a newer open aborts stale completion. All timers, listeners, data owners and links have explicit teardown.
- Keep order entry locked during a grid transition. A successful open disarms One-Click before unlocking; imported state can never arm it. Retain the existing authoritative execution adapter and replay guards.
- Only a successful open updates the recent/active catalog entry. A catalog write failure rolls back the visual selection. Autosave applies to the current named workspace only and reports storage failures without inventing a saved state.
- No comparison product names in new source, comments, documentation or commit messages. Local commits only; no publishing or live orders.

## Task 1: Portable weighted grids

Library files: `src/workspace/documents.ts`, `tests/workspace-documents.test.ts`, `docs/workspaces.md`, `.github/skills/openalgo-charts/references/workspaces.md`.

Add optional `rowWeights: number[]` and `columnWeights: number[]` to the layout contract. Each supplied list must match its track count, have positive finite values no greater than 1,000, and be detached from input. Preserve them in document/repository import/export. Missing weights remain absent for compatibility.

- [x] Add RED tests for asymmetric track round trips, detached arrays, mismatched lengths, zero/negative/nonfinite/oversized weights, and existing documents without weights.
- [x] Implement validation at the document boundary. Run the document and repository suites, then package lint/types/unit/build/demo/declaration/size/tree-shaking checks and reference coverage.
- [x] Document the optional fields. Pack a verified source commit and update the isolated consumer's relative vendor dependency and integrity, preserving its unrelated dependency junction.

## Task 2: Terminal configuration capture and prepared restoration

Consumer files: extend `frontend/src/lib/trading/terminal.ts` and `terminal.test.ts`; create `frontend/src/lib/trading/workspaceState.ts` and its tests. Reuse the template study planner.

Boundary:

```ts
captureWorkspacePane(id: string): WorkspacePane;
// Initial configuration and an isolated preference adapter are optional terminal
// constructor inputs. A prepared terminal reports when history, studies and
// drawing restoration have completed, or why preparation failed.
```

- [x] Test complete capture from a real chart snapshot: current symbol/exchange/interval/type, engine settings/viewport/panes, host profile and volume settings, drawings, study instances, volume visibility and drawing preferences. Verify execution fields cannot escape.
- [x] Add an injectable preference adapter with the existing browser default. Staging uses an in-memory adapter and cannot rewrite the active grid's local keys while preparation is incomplete. Blocked legacy preference storage must not crash chart startup.
- [x] Test initial prepared configuration before implementing it: malformed state, unknown study/type/interval, missing symbol/history, and cancellation must fail explicitly rather than load an unrelated default symbol. The ordinary terminal keeps its existing fallback behavior.
- [x] Await study and drawing restoration, then restore the engine configuration against the ready primary series. Preserve pane grouping and settings without duplicating indicators or restoring trading primitives. Unsupported comparison data rejects before publication until its adapter is available.
- [x] Guard every async completion with terminal/generation ownership and release temporary resources on failure. Run terminal, history, profile, template and execution-guard suites.

## Task 3: Grid owner and transactional switching

Consumer files: create `frontend/src/lib/trading/workspaceGrid.ts` and tests; create `frontend/src/components/trading/WorkspaceGrid.tsx` and tests; adapt `frontend/src/components/trading/ChartPane.tsx` and `frontend/src/pages/Trading.tsx`.

- [x] Add pure preset/document conversion tests, including the unequal `1 + 2` layout, spans, imported geometry, focus and sync. Derive named CSS areas/track fractions from validated slots rather than trusting imported CSS strings.
- [x] Add coordinator tests with controllable pane promises: out-of-order readiness, one failure, account change, superseded open, page teardown and failed active-document write. Each failure preserves the prior workspace and destroys every staged owner exactly once.
- [x] Make active-document persistence cancellable before integrating the coordinator: accept an optional abort signal on repository open and storage writes, check it before queued/read work and abort the browser transaction while pending. Observe repository and actual-browser cancellation regressions, document the adapter obligation and revalidate the packed contract. A committed transaction remains a completed operation; cancellation cannot undo a committed write.
- [x] Implement the staged grid and page-level loading/error state. Each generation owns its terminals and link group; stale callbacks cannot alter the visible pane registry or focus. Disable input and trading routes through the transition, then restore focus and sync from the successful document.
- [x] Migrate the existing unnamed grid on the first explicit named save, keeping the original preferences until a successful save. Reopening a named workspace uses the complete saved configuration and cannot accidentally mix it with old pane keys.
- [x] Verify link-group setup does not collapse intentionally different intervals when interval sync is off. A refused interval remains visible as an explicit host limitation.

## Task 4: Workspace menu and autosave

Consumer files: create `frontend/src/components/trading/WorkspaceMenu.tsx` and tests; create `frontend/src/hooks/useWorkspaceAutosave.ts` and tests; extend `Trading.tsx` and the existing charting-terminal guide.

- [x] Write component regressions before implementation for New, Save, Save as, Open, Rename, Duplicate, Delete, recent entries, import/export and rejected writes. Include an empty catalog and account switch during an open/save.
- [x] Mount one menu alongside Templates. A new layout asks for a name and starts from an explicit default; Save captures the current complete grid. Open/import prepare before publishing. Export uses the validated portable document and releases its object URL.
- [x] Implement debounced autosave from configuration changes only, not every market tick. Snapshot the originating document/account ID, serialize writes, coalesce repeated changes, cancel queued work on switch/unmount, and keep errors visible. A stale save cannot overwrite the newly selected layout.
- [x] Show saved/unsaved/pending/error state with meaningful text. Allow recovery through explicit Save or Refresh. Recent entries come from successfully opened documents, with deletion and duplicate identities handled by the repository.

## Task 5: Actual chart acceptance

Library file: extend `scripts/check-openalgo-compat.mjs` with opt-in `--workspaces true`; update the master ledger. Consumer guide: `docs/userguide/32-charting-terminal/README.md`.

- [x] Observe the missing-menu RED run before wiring the UI. Add actual-chart assertions for a two-pane unequal grid with different instruments/intervals, repeated studies, grouped oscillators, drawings and volume settings.
- [x] Save, switch to another layout, reopen, reload and import/export; compare each chart's canonical state and geometry. Verify focus/sync, recent list, autosave on/off and cancellation. Reject malformed/unsupported documents without changing the current grid.
- [x] Inject quota/conflict/history failures and prove the old grid and catalog remain recoverable. No order mutation may be sent by any layout action. Check account isolation with separate catalog owners.
- [x] Run Chromium, Firefox and WebKit; inspect desktop and narrow screenshots. Run the full consumer suite, lint/type build and production build, restore generated tracked assets, scan added names, then commit locally.
- [x] Record exact source/package revisions, integrity and measured limitations. This phase completes the consumer F1 boundary; continue the reference host and all remaining spec rows before completing the overall goal.

## Preflight notes

The current `ChartPane` reports readiness after interval discovery, before history and asynchronous study/drawing restoration finish. That event is insufficient for atomic workspace publication. The current terminal also writes synchronous per-pane preferences during load and may fall back to a default instrument. Prepared restoration must address both behaviors explicitly.

The earlier live observation still requires calendar-aware event handling. A valid parsed timestamp alone cannot establish session membership. Preserve this and the replay-loading lock gap in the master ledger throughout workspace work.

## Implementation checkpoint, September 20

The consumer working tree now contains `PreparedChartGrid`, `WorkspaceGrid`,
`useWorkspaceGridTransition`, `WorkspaceMenu` and `useWorkspaceAutosave`, connected
to the actual trading page. Account changes remount the page owner. Prepared panes
report completion after full initialization, ignore callbacks from old effect
lifetimes, retain their instances when published and preserve drawing preferences.
The page locks execution during loading and disarms One-Click on transitions.

Observed regressions before fixes: early readiness, stale StrictMode callbacks,
uncaught initialization failure, overwritten drawing preferences, a retained
StrictMode transition lock and drawing attachment requested before a prepared chart
existed. Component/owner/hook regressions now pass. The full consumer gate at this
checkpoint passes 2,246 tests in 139 files, type checking and production build.
The existing visualization chunk warning and unrelated canvas test diagnostics
remain. Generated tracked build output was restored.

Actual workspace capture found `title: undefined` in a profile series snapshot.
Library `87f1589` omits cleared optional series styles from `getState()` while the
portable document parser remains strict. The regression was observed before the
fix. Full verification passes 5,340 tests in 221 files and 232 reference-host tests
in 17 files. Chart-only is 50.16 KiB Brotli within 50.25; aggregate is 223.43 kB
within 224. The consumer now installs the 1,144,841-byte archive
`openalgo-charts-2.4.0-87f1589.tgz`, integrity
`sha512-oQn5dl07+xJSr1x8TMzPINFdOZIX4xTcQm9SfARyNOyWbSRjqEYLZO2Bi1TpFfmJyXFcfEsWX/ejbig0Jq60Rg==`.
Every one of its 33 packaged files was byte-compared with the installation.

Chromium has passed actual unequal-grid save, clean workspace creation, saved
grid reopening and reload. Repeated averages, grouped oscillators with distinct
effective lengths, hidden studies, drawings, preferences, focus and independent
intervals are retained. Canonical comparison normalizes default series visibility
and permits at most one canvas pixel of viewport/spacing rounding from fractional
CSS tracks. The restored screenshot was inspected; toolbar crowding remains F9.
The fixture was corrected to use the indicators' real `length` setting and verifies
that the two oscillator calculations differ, rather than only retaining an unused
setting key.

Autosave browser checks pass for configuration edits, autosave off, explicit Save
and a quiet catalog during live fixture ticks. A refused activation write preserves
the visible grid and catalog. Cancellation, import/error acceptance and all three
browser runs are still being completed; this checkpoint does not complete Task 5
or the overall production goal. Browser reports are under `artifacts/candidate/`
with the `workspace-roundtrip` and `workspace-acceptance` prefixes.


## Consumer acceptance complete, September 20

The final consumer suite passes 2,253 tests across 139 files, type checking and
production build. Full lint exits successfully with two existing warnings
(WatchlistPanel unused suppression and previousClose.test unused import) and two
existing style notices. Changed-file checks pass. Generated tracked assets were
restored. The candidate archive and all 33 installed files still match the
87f1589 integrity above.

All 21 workspace compatibility checks pass in Chromium, Firefox and WebKit.
They include catalog revision conflicts, Refresh recovery, unavailable history,
quota refusal, cancellation, execution locks and malformed/unsupported imports.
The prior readiness helper could count a partly loaded stage together with an
old grid; it now waits for zero staging roots and every live terminal to be ready.
Mobile screenshots finish finite dialog animations before capture. Desktop and
narrow dialog pixels were inspected. Crowded per-pane toolbars remain F9.
The separate corrected-template fixture passes 15 Chromium checks. Artifacts use
`workspace-final-{chromium,firefox,webkit}` and `templates-workspace` prefixes.

Four teardown regressions failed before correction: an old grid's cleanup error
could release its published replacement, prevent unlocking, or skip remaining
owners. Cleanup now attempts every terminal and link, releases registries and
reports aggregate failures without invalidating publication. Two save regressions
also failed first: Save as must compare against the actual persisted snapshot,
and unchanged gestures must return to Saved even with autosave disabled.

Resource audit: grid maps/sets and link groups, terminal ownership, preparation
abort listeners, autosave timers and export object URLs have matching cleanup.
Regression tests cover failure, cancellation, supersession and account changes.
This is static and automated lifecycle verification, not a prolonged memory or
process-descriptor measurement; P3 remains required.

This completes the current consumer grid/menu/autosave phase. F1 comparison
restoration follows F7; reference-host controls, coordinated replay, shared
controls and all remaining production requirements remain in scope.
