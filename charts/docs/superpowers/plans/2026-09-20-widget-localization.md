# P4 widget translation and persistence contract

Source: production workspace design, P4. Baseline: dfa42d5.

## Scope and rulings

The approved production scope requires host-owned asynchronous persistence and
translated widget controls while preserving existing callers. WorkspaceRepository
already supplies asynchronous storage, optimistic revisions, failure recovery,
validated migrations and immutable account namespaces. Keep that implementation
and cite its regression evidence. Do not create a competing persistence layer or
put credentials in widget options or workspace documents.

Add an optional synchronous translator to WidgetOptions and WidgetContext. English
source messages are typed keys. Parameterized messages pass named string/number
values separately, with typed required parameters. Generated schema labels use
scoped keys and their descriptor's English label as fallback. Undefined, null,
blank, malformed or throwing translations fall back to English. Each render site
chooses a message explicitly; never traverse and rewrite arbitrary DOM text.

Translate widget-owned chrome, dialogs, forms, accessibility labels, help text and
feedback, including late-mounted and refreshed controls. Preserve symbol/exchange
codes, numeric values, user drawing/alert text, host branding, search results,
filenames, keyboard chords and host/provider errors as literal data. Descriptor
labels are explicitly translatable metadata, separate from user values. No new
locale package, backend, persistence format, icons or dependencies.

## Execution

1. Add failing widget regressions for a translator passed through createWidget:
   visible/accessibility labels, settings opened later, theme refresh, mobile
   controls, interpolation, fallback and literal host/user content.
2. Implement the typed contract and thread it through the shell and all widget
   rendering entry points. Keep shared primitive options additive for custom
   hosts that construct WidgetContext themselves.
3. Translate schema metadata at its render boundary and parameterize dynamic
   widget messages. Audit all text/attribute writes and string-based branches.
4. Run focused widget suites and workspace persistence/document suites using
   p4-prefixed logs. Run source type/lint checks without emitting shared dist.
5. Document the exact contract and boundaries in docs/widget-localization.md,
   the widget skill reference and website widget docs. Ask root to coordinate
   integrated builds, browser validation, size measurement and public API checks.

## Verification ownership

This task owns src/widget, widget tests, this scoped plan and widget documentation.
Do not touch src/index.ts, package metadata, shared ledger or other checkouts. Do
not stage or commit. Root coordinates shared build and browser artifacts.

## Coordinated P5 addition

Root also assigned the widget side of the shared trading capability contract.
The adapter agent owns the pure base helper and trade engine enforcement. Add
tradingCapabilities and tradingLocked to the widget and context-menu options.
Hide unsupported placement/types; disable replay-locked routes. Recheck account
capabilities, replay, host selection locks and instrument context immediately
before invoking an existing onOrder callback. Throwing capability/lock callbacks
must refuse placement. Record its regressions separately from P4 translations.

## Focused verification

- P4 baseline regressions failed on untranslated toolbar/mobile labels and the
  absent resolver. Final translation suite: 10 cases passed, covering fallback,
  literal rendering, separate widget catalogs, generated controls and edits,
  drawing/level dialogs, shortcuts, translated search and preserved alert/error data.
- P5 baseline regressions failed when unsupported, stale, replay-locked and
  context-changed order callbacks still reached the host. Final widget capability
  suite: 6 cases passed, including the actual shell-to-menu option wiring and
  a disabled diagnostic when a configured capability provider is unavailable.
- All widget source suites plus workspace repository/document suites: 299 cases
  in 17 files passed. Existing persistence evidence covers adapter rejection and
  recovery, immutable account namespaces, migration and credential stripping.
- Source typecheck and focused widget/test ESLint passed. `git diff --check` passed.
- After adding the unavailable-capability diagnostic, the affected localization,
  trading-capability and dialog suites passed 58 cases, with clean types and lint.
- Browser fixture/spec added with desktop, mobile and stale-order cases. Integrated
  build, three-engine browser execution, pixels, size and API checks are owned by
  root and were not run by this task during the shared artifact freeze.

Logs: `p4-localization-red.log`, `p4-p5-red.log`,
`p4-widget-persistence-final.log`, `p4-new-contracts-final.log`,
`p4-typecheck-final.log` and `p4-lint-final.log` in the host temporary directory.
The diagnostic addition also has `p4-p5-diagnostic-red.log` and
`p4-diagnostic-green.log`.

## Integrated release verification

Root's complete reviewed package verification passes all 5734 engine cases,
389 reference cases, seven harness cases, lint, types, build, declarations, size
and tree-shaking. The translated desktop, narrow mobile and callback-time
capability cases pass in Chromium, Firefox and WebKit (nine browser executions).
Actual desktop/mobile screenshots were inspected. The widget measures 48303
Brotli bytes, with a bounded 48.75 kB budget. API generation has no warnings and
skills coverage is 930/930. Final full-browser and publication status are recorded
in the production-release plan; synthetic order callbacks are not live orders.
