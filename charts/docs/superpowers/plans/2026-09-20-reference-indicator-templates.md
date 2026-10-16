# Reference indicator templates implementation plan

> **For agentic workers:** Use superpowers:executing-plans with the user's authorized continuous native execution. Validate each task and commit locally. No implementer subagents.

**Goal:** Make named indicator templates usable from the reference toolbar, preserving repeated studies, parameters, plot styles, visibility and pane grouping on the captured selected chart.

**Architecture:** Promote the consumer's pure template planning policy to the optional DOM-free workspace tier, and add repository updates for existing templates. The reference host uses that shared planner and its existing revision-aware catalog. A separate template dialog captures a chart owner and applies only study state, retaining that chart's drawings and alerts. Consumer migration to the shared helper follows Charts publication.

**Tech Stack:** TypeScript workspace tier; JavaScript reference modules; existing dialog, overlay and toolbar helpers; Vitest; fixture-mode browser tests in Chromium, Firefox and WebKit.

**Spec:** `docs/superpowers/specs/2026-09-19-production-workspace-design.md`, F2 and the shared F1/P4 storage boundary. The consumer implementation in `2026-09-19-indicator-template-host.md` provides the existing policy, not completion evidence for the reference host.

## Global constraints

- No comparison product names, new icons, emoji or em/en dashes in changes.
- Engine tiers remain free of host DOM. Keep the established bundle boundaries.
- Existing library options retain their defaults. New APIs are additive.
- Workspace files never contain credentials, orders, positions, account balances or the armed flag.
- Broker state remains authoritative for orders and positions.
- Replay cannot expose future bars; templates must not reload data or unlock trading.
- Charts 2.4.5 publishes before remaining consumer integration and final broker validation.
- Preserve the original eight OI edits and the consumer worktree; no live orders.

## Review focus

- Missing custom descriptors or invalid pane counts must reject before current studies are removed.
- Equal repeated studies must stay separate; append must preserve existing instance identities and keep incoming pane groups separate from existing panes.
- A chart replaced or retargeted while the dialog or file picker is open must not receive a stale template action.
- Applying studies must retain drawings, fired alerts and anchors of retained studies; failures must restore the previous study state and report rollback failure.
- Saving templates shares the named-layout catalog revision and lock; a stale tab or quota failure must not silently overwrite storage or clear a failed layout-save warning.

## Task 1: Shared planning and template updates

Files: create `src/workspace/templates.ts`, `tests/workspace-templates.test.ts`;
modify `src/workspace/index.ts`, `src/workspace/repository.ts`, its tests and the
workspace API documentation/coverage surface discovered from the repository.

- [x] Add failing planner cases for replace/append, equal and unequal repeated
  studies, detached settings/styles/visibility, incoming identity removal,
  retained identities, shared and sparse panes, empty input, missing IDs, invalid
  mode and the 256-study/31-pane limits. Reject an append boundary that overlaps
  existing study panes. Observe RED before implementation.
- [x] Export `IndicatorTemplateMode` and `planIndicatorTemplate(current, incoming,
  mode, available, nextPaneIndex)` from the workspace tier. Reuse its JSON and
  indicator validators. Match the consumer's existing policy with explicit
  boundary validation; do not copy host UI or terminal code into the engine.
- [x] Add `WorkspaceRepository.saveTemplate(id, indicators)` regressions and
  implementation. Preserve ID/name/createdAt, update timestamp monotonically,
  strip reusable instance identities, validate before write, retain other entries
  and keep revision-checked atomic storage failures visible.
- [x] Run workspace tests and full package checks (lint/types/unit/build/demo/
  declarations/size/tree-shaking). Update affected API docs, record exact outcomes
  and commit. Measure any bundle change; do not invent new release facts.

Task 1 evidence: missing planner and repository method fail before implementation
(`reference-template-api-red.log`); 66 workspace cases pass afterward. Full
`npm run verify` passes 5591 engine tests/234 files and 371 reference tests/28 files,
lint, types, build, declarations, size and tree-shaking. Workspace measures 5.53 kB
Brotli under 6 kB; all tiers measure 240.03 kB under 240.5 kB. Base/terminal/chart-only
sizes are unchanged. TypeDoc completes without warnings and skills coverage passes
919/919. Integration guide and workspace skill reference document the new APIs.
No browser chrome or consumer changes in this task. Task 2 remains.

## Task 2: Captured-chart template actions and dialog

Files: add `examples/yfinance/src/indicator-templates.js` and focused reference
tests; modify `main.js`, `indicators.js`, `persist.js`, `toolbar.js`, `ui.js`,
`workspaces.js`, `index.html`, `styles.css`, module inventory, README and browser
tests. Reuse the existing `ReferenceWorkspaceCatalog.run` for template writes.

- [x] Add failing host cases for captured owner, repeated instances/grouping,
  empty replace/append, unsupported descriptors, partial restore and rollback,
  preserved drawings/alerts and source/viewport isolation. Observe RED.
- [x] Capture complete study records from the actual chart. Apply the shared
  plan to the captured current chart using restoreState with retained drawings
  and alerts. Verify restored count, recover prior studies on failure and surface
  recovery failures. Keep source/history/series settings out of the template.
- [x] Preserve complete primary indicator records wherever the reference mirrors
  chart state. Synchronize after template application; suppress intermediate
  persistence so rebuild/reload cannot retain a partially applied study list.
- [x] Add a plain-label Templates toolbar control and dialog using the existing
  overlay/focus/fullscreen patterns. Show its captured chart owner. Provide saved
  selection, create from current, overwrite selected, rename, duplicate, delete
  with confirmation, import/export and explicit Replace/Append actions. Import
  stores a fresh template; applying is a separate action with owner validation.
- [x] Reuse the existing catalog namespace and revision guard. Show failures and
  an explicit reload action; do not silently substitute storage. Metadata actions
  must not clear a failed named-layout save warning. File-picker completion does
  not retarget a changed chart.
- [x] Browser-test both charts, repeated/custom/empty templates, append/replace,
  style/visibility/grouping retention through symbol/type changes and reload,
  drawing/alert retention, history silence, stale owners, storage errors and
  narrow/fullscreen/keyboard flows. Inspect rendered screenshots.
- [x] Run complete reference tests, affected three-engine browser coverage and
  required package checks after any additional engine changes. Update README,
  main ledger and external handover, then commit. Continue chart-data download,
  P1-P6 and release work; this plan does not redefine goal completion.

Task 2 evidence: the new host tests failed before the module existed, then all six
passed. The first UI test failed before the Templates control existed. The complete
reference suite now passes 379 tests/29 files, and lint/typecheck pass. All 151
reference browser cases pass. A final 18-case template/layout sweep passes in
Chromium, Firefox and WebKit after correcting primary-button hover contrast found
in screenshot review. Wide and narrow rendered dialogs inspected.

The first expanded run had five browser failures: an invalid EMA plot key in a
fixture caused its alert to be dropped correctly in all three engines; Firefox
and WebKit consume Escape to exit fullscreen before sending another Escape to the
page. A standalone event probe confirmed that behavior. Fixtures now use actual
descriptor input/style keys and exercise keyboard dismissal both outside and after
fullscreen. One older unit assertion was updated to require the complete mirrored
study record, including pane placement and detached settings. These initial failed
runs remain recorded in the candidate artifacts.

Drawings and valid study/drawing/price alerts survive append; an empty replacement
drops removed-study anchors without firing history. Browser cases cover custom
descriptor availability, write failures, CRUD/files, stale owners, replay prefixes,
second-chart rebuild/reload, shared panes and visibility. No engine changes were
needed after Task 1, whose full package verification remains the library evidence.
Original eight OI edits and the consumer checkout are preserved. The plan is
complete; chart-data download, remaining production contracts/endurance, final
review and release publication remain in the overall scope.
