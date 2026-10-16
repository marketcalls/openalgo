# Release 2.5.2 implementation plan

Design: ../specs/2026-09-23-chart-analysis-252-design.md

1. Analysis drawings: write failing math/registry/rendering tests, implement pure
   calculations and tool descriptors, add bounded settings, verify drag and restore.
2. Linked views: write failing controller/group contract tests, implement safe drawing
   replication and appearance adapters, verify undo, cancellation, context and teardown.
3. Timeline events: write failing filtering/clustering/detail tests, implement the
   headless primitive and widget popup, preserve old event marker behavior.
4. Integrate tier exports and Chart methods, reference host controls and sample
   events, widget rail entries, public documentation and live website examples.
5. Run focused browser regressions in three engines and inspect rendered pixels.
   Review feature changes independently and resolve findings.
6. Bump package, lockfile and runtime to 2.5.2; update changelog, release notes,
   skill coverage and measured counts/sizes. Run full verify, browser suite,
   TypeDoc and website build. Validate the packed candidate in an isolated consumer.
7. Review final diff, commit and push, wait for CI, merge and tag the tested tree.
   Dispatch npm and website workflows, create the GitHub release after npm succeeds,
   compare registry contents/provenance and inspect the deployed website.

## Ownership

- Analysis agent: new draw analysis modules, tools registry, draw schema, dedicated tests.
- Linking agent: link modules, drawing controller and new drawing-link module, dedicated tests.
- Events agent: event primitive modules and new widget event popup module, dedicated tests.
- Root: core Chart and Pane, tier entry points, host/widget integration, browser fixtures,
  documentation, versions, final verification and publication. Agents request ownership
  before editing any other existing file. No agent commits while concurrent work runs.

## Decisions

- Same symbol and exchange is the drawing-sync default; absent identity is ineligible.
- Existing integrations retain their current defaults.
- Work occurs in the isolated charts-production worktree; active OpenAlgo stays untouched.

## Pre-publication validation

- Implemented all three feature groups and resolved independent review findings,
  including linked restore/undo, partial history, duplicate event IDs and CSP styles.
  CodeQL also prompted cryptographic lineage IDs in environments without randomUUID.
- Full package verification passed: 6,023 engine tests in 256 files, 416 reference-host
  tests, endurance-harness tests, declarations, bundle limits and tree shaking.
- Public reference coverage is 941/941. Built registries report 105 indicators,
  87 drawing tools and 15 chart types. TypeDoc generated without warnings.
- The 575-case browser suite completed with 574 passes and one local server connection
  failure; that case passed on rerun. All new interactions ran in Chromium, Firefox
  and WebKit. Inspected chart, popup, mobile and architecture pixels.
- Website build and real-browser linked-analysis, drawing-gallery and alert-lifecycle
  checks passed. The new example also checks mobile chart bounds and popup typography.
- The isolated packed-package consumer passed typecheck, production build and 114
  mocked browser checks. Its trading suite passed 564/566; the two remaining checks
  require entries for the new tools in the host's fixed catalogue. An external copy
  passes both with the companion patch. Consumer source remains unchanged.
- Final archive contains 33 files. README line endings are normalized to match CI;
  every file hash is recorded externally for the registry comparison. The ID fallback
  correction also passed all 16 focused browser cases on the rebuilt package.
- Live-broker and physical-device acceptance are not claimed. Registry publication,
  provenance verification and deployed website checks follow the commit and CI gates.
