# Production workspace execution ledger

## Scope and baseline

Spec: `../specs/2026-09-19-production-workspace-design.md`.
All F1-F9 and P1-P6 requirements remain in scope until verified.

- Charts baseline: `1933d65`, worktree `D:/OpenAlgo-Voice/worktrees/charts-production`.
- Consumer baseline: `a4cc86f9d`, worktree `D:/OpenAlgo-Voice/worktrees/openalgo-production`.
- Both branches: `feat/production-chart-workspace`.
- Original main checkouts were clean and have not been edited.
- Issue 2078 and its comments read via the repository API. Three attached images inspected.
- Execution: native implementation with regression-first tests; independent final
  review as required by the execution skill. User authorized continuous execution.

## Baseline findings

- Crosshair magnet currently controls price only; no independent center-snap option.
- LinkGroup currently has crosshair, viewport and symbol channels, no interval channel.
- OpenAlgo's Trading page repeats ChartPane toolbars and has no named workspace model.
- Built-in terminal volume currently uses one theme colour.
- Existing persistence is per-pane local storage; the backend also has chart preferences.
- Existing replay is per terminal and already locks the workspace's trading routes.

## Rulings

- Ruling: raise the combined base/trade budget from 86 to 87 kB and all tiers
  from 218 to 219 kB. The new snap/link/volume APIs measure 86.09 and 218.12 kB;
  the increase is intentional feature cost. Final release facts must be measured
  again after all phases, rather than claiming these intermediate figures.
- Ruling: unpack the npm candidate into only the isolated consumer's existing
  `node_modules/openalgo-charts` during development. The final local delivery
  will vendor a versioned candidate tarball with a portable file dependency and
  lockfile; no unpublished version or absolute worktree path will be required.

- Preserve the main checkouts through linked worktrees; use independent copied
  dependencies for the consumer harness. This permits local candidate validation.
- Implement the requested enhancements and readiness contracts in phases without
  treating any phase as completion of the overall goal.
- Do not present deterministic transport tests as live broker evidence or turn a
  numeric assessment into an unverifiable completion claim.
- Crosshair snapping resolves at paint time, preserving raw pointer coordinates
  and immediate toggling. A standalone histogram/column uses its first series;
  when a primary price series exists it remains authoritative for snapping.
- The consumer dependency tree contains a junction back to the source repository.
  The first copy followed it; its owned process was stopped after inspection.
  Further copying uses `/XJ`. Cleanup of the generated ignored `node_modules/openalgo`
  folder was rejected by automatic policy, so it remains untouched. No source
  files were modified or deleted. Do not recursively copy local package junctions.

## Progress

- Requirements and first implementation plan committed as `70f2b19`.
- Baseline: 5250/5251 library tests passed; existing packaging ACL test timed out
  under dependency-copy load. Its isolated rerun passed all 20 tests unchanged.
- Crosshair: 7 regression tests and the 120-test affected settings/state/pointer
  sweep pass. Browser paint assertions pass in Chromium, Firefox and WebKit;
  saved Chromium pixels inspected. Snap is centered and horizontal price stays raw.
- Interval linking: 8 new regressions and 75 affected link tests pass. A callback
  may return false to refuse an unsupported interval without claiming acceptance.
- Volume descriptor: all 5 new tests failed against baseline and now pass,
  covering warmup, replacement/append, direction/doji colour, settings changes,
  shared scale, missing volume and replay-prefix isolation. The existing
  indicator/spine/precision sweep passes 235 tests.
- Typecheck, changed-file lint and public-reference coverage pass. The built
  foundation candidate includes snap, interval linking and the volume descriptor.
- Consumer baseline: 110 targeted terminal/history/replay-lock/settings tests pass.
- Foundation candidate: lint/typecheck, 5271 unit tests, build, 231 demo tests,
  declaration checks, size checks and tree-shaking checks pass. Size checks were
  rerun after the intentional budget changes; other checks were unchanged.
- Consumer interval wiring: all 6 regressions failed with the packed candidate
  before migration; now 116 affected consumer tests and `tsc -b` pass. The sync
  menu includes interval and keeps the option off for existing saved preferences.
- Three browser crosshair screenshots inspected; the vertical line crosses the
  candle center in each. The horizontal crosshair stays at the pointer price.
- Library foundation implementation committed locally as `d417532`.
- Consumer built-in volume now follows displayed candle colours (including
  previous-close colour rules), supports a configurable MA on the same scale,
  and follows transformed/live/replayed data without reading future bars.
- Actual StrictMode browser execution exposed a destroyed LinkGroup reused by
  an effect restart. The Trading page now creates and destroys each group in
  the same effect lifecycle; interval convergence survives reloads.
- Firefox exposed page visibility notifications arriving during the outgoing
  page's render. A regression first reproduced the React warning; the hook now
  queues captured event snapshots, with an unmount guard. Related option-chain
  tests await the notifications before simulating a return to the page.
- Consumer verification: 514 tests across 38 affected files pass with
  `--maxWorkers=2`; changed-file lint, typecheck and production build pass.
  An earlier unrestricted-worker run exhausted this machine's available memory;
  it is not counted as a successful run. Use bounded workers for this workspace.
- Consumer foundation implementation committed locally as `3e9cfaaa8`.
- The consumer vendors `frontend/vendor/openalgo-charts-2.4.0-d417532.tgz`
  (1,128,048 bytes) with a portable file dependency. Its computed SHA-512 matches
  the lockfile. Generated tracked frontend assets were restored after the build;
  the source and package candidate are the reviewable local delivery.
- Browser harness now supports Chromium, Firefox and WebKit, includes settings,
  interval persistence, replay-prefix MA and both volume palettes, and records
  actual console Error messages, error stacks and failed network requests.
- WebKit can report caught fetches on a departing document as access-control
  page errors. Reports retain these notices separately only during reload and
  only for the fixture's own API/Socket.IO URLs. Window errors and unhandled
  promise rejections are asserted separately and must remain empty. These are
  synthetic transport checks, not evidence of real broker connectivity.
- Final foundation run: all 24 checks pass in each of Chromium, Firefox and
  WebKit. Light and dark screenshots were visually inspected in all three.
  WebKit wraps the first pane's narrow OHLC legend; the shared-toolbar and
  responsive-workspace phase still owns the remaining presentation work.

### Reproduce the current checks

From the consumer's `frontend` directory:

```text
npm run test:run -- src/lib/trading src/components/trading src/hooks/usePageVisibility.test.tsx src/hooks/useOptionChainLive.test.tsx --maxWorkers=2
npm run build
```

From the chart library, repeat for `chromium`, `firefox` and `webkit`:

```text
node scripts/check-openalgo-compat.mjs --frontend D:/OpenAlgo-Voice/worktrees/openalgo-production/frontend --objects true --navigation true --branding true --foundations true --browser chromium --label foundations-chromium --output artifacts/candidate/foundations-chromium.json --screenshot artifacts/candidate/foundations-chromium.png
```

Reports and screenshots are generated local artifacts. The portable consumer
package source commit and lockfile integrity are recorded above; no release has
been published and the main checkouts remain unchanged.

## Remaining

### Workspace documents and persistence foundation

The optional `openalgo-charts/workspace` tier now provides validated full-grid
documents, indicator templates, an async catalog repository and an IndexedDB
adapter with atomic revision checks. Document imports create fresh identities.
Namespaces are immutable per repository, rejected saves remain rejected, and
corrupt stored catalogs are not overwritten. Hosts still own controls, restoration
and autosave orchestration; this does not complete F1, F2 or P4.

Evidence: document/repository RED runs observed before implementation; an actual
`Chart.getState()` test caught zero auto precision and additional settings slices.
The 36 new unit tests pass. All 5,307 library tests (220 files), 231 demo tests
(16 files), lint, typecheck, build, declaration guard, public-reference coverage
(901/901), size and tree-shaking checks pass. Four new IndexedDB browser tests
failed against the missing factory, then all 12 executions passed across Chromium,
Firefox and WebKit: reload/account separation, simultaneous tab writes, stale or
corrupt storage preservation, and close/version-change lifecycle.

Ruling: the new tier has its own 6 kB Brotli budget (4.80 kB measured). The all-tier
budget rises from 219 to 223 kB for the added optional module (222.92 kB measured).
Base 78.48 kB, widget terminal 184.71 kB and tree-shaken chart-only 49.92 KiB are
unchanged. Ruling: document magnet modes retain off/weak/strong; snapshots retain
the full settings/timezone contract and minMove 0. These preserve existing state.

Ruling: document, repository, browser adapter and package wiring are committed as
one verified foundation because they form the usable public entry point. The
tracked plan and this ledger carry the native Windows execution record rather
than introducing a second shell-specific task ledger. Host work remains a
separate phase.

User started the real OpenAlgo backend on port 5000. A dedicated read-only browser
is open for their login; its private profile and control script are ignored local
artifacts. No authenticated live-market result is claimed yet.

Foundation source commit: `566858e`. Packed candidate:
`openalgo-charts-2.4.0-566858e.tgz`, 1,141,884 bytes,
SHA-512 `bNXJPmaAxViYOWdWvx3mxPWxFgMwXHwCVvIrWKc0d6BO9Wc75I4pcS2bztLySIannUru3Ux7wadrOuzYhV5yOg==`.
A separate consumer package directory successfully typechecked shared Chart/state
types against the extracted tarball and executed a workspace storage round trip.
Consumer commit `3c1a90a8f` vendors this candidate and matches its integrity.
All 514 affected consumer tests (38 files) and `npm run build` pass; the build
retains its existing oversized visualization-chunk warning. Generated frontend
assets were restored. The actual consumer with this package passes all 24 Chromium
fixture checks, with zero page errors/runtime events; deliberately injected
network failures and the expected analyzer refusal remain in the console report.
Artifacts: `artifacts/candidate/workspace-package-chromium.{json,png}` and
`workspace-consumer-{tests,build}.log`. Other rendering engines retain the prior
foundation evidence; the new storage functionality has current three-browser
coverage as recorded above.

Live-session handoff initially reached a different browser. The user subsequently
logged into the dedicated window; `/auth/session-status` then confirmed the
authenticated broker session. Never copy another browser's cookies.

### Real backend observation and priority correction

The development frontend on port 5176 uses the actual backend on port 5000 with
the dedicated authenticated browser. History returned 1,512 BHEL/NSE 5-minute
candles with sorted times and valid OHLC. Exact symbol search, supported intervals,
an authenticated socket and a market-data frame were observed. The 1-minute
history subsequently loaded; the immediate post-switch snapshot still contained
old bars, so readiness assertions must use `chart.getDataContext().interval`.
No live orders were sent; the browser blocks execution routes.

This is read-only adapter evidence, not an endurance run or proof of fresh exchange
trades. A cached mode-3 snapshot carried `ltt: 1789732772` and a delivery
`timestamp: 1789833463417`. The parser used the newer delivery time and created a
new delivery-day candle. Ruling: address timestamp provenance before proceeding
with the next template UI task. Prefer valid explicit trade/market event times,
then delivery time for legacy payloads; retain seconds/milliseconds/ISO support
and add numeric-string support. Seven parser regressions reproduced the defect
before the correction. Calendar/unknown-time policies remain required under P1;
this fix alone does not establish session correctness.

Ignored sanitized evidence: `live-openalgo-candidate.json`,
`live-openalgo-timestamp-probe.json`, and `live-indicator-template-methods.json`
under `artifacts/candidate`. The terminal template methods were also exercised
against actual loaded bars: four instances including exact repeats and a shared
oscillator pane survived an interval rebuild, with price data and viewport
preserved; the previous studies were restored afterward. The template picker and
account-bound catalog hook are not yet implemented.

The full consumer suite initially exposed two visibility-transition test failures
in `StrategyBuilder.test.tsx`. Both dispatched hidden/visible in one synchronous
turn while the shared hook deliberately defers state to a microtask. The tests
now flush each real-world event boundary; all 33 tests in that file pass and the
full suite passes 2,134 tests across 126 files. Existing simulated-DOM canvas
warnings remain in its log. Modern study persistence also rejects an explicit
null pane index; a regression reproduced its previous accidental coercion to zero.

The market-time correction passes all 5,314 library tests, 231 demo tests and the
complete `npm run verify` gate (lint, types, build, declarations, size, tree
shaking). Negative numeric strings no longer pass through permissive date parsing.
Public reference coverage is 901/901. The final all-tier bundle is 222.95 kB,
widget terminal 184.75 kB and chart-only tree-shaken import 49.92 KiB, within the
existing budgets. The new packed candidate still needs live backend verification.

The user reiterated the naming restriction. Added-line and commit-message scans
against both branch baselines found zero restricted comparison-name matches.

F3 and F5 have library and consumer implementations and regression evidence.
F4/F6 also have consumer coverage; the reference host's built-in volume controls
still need integration. The whole goal remains open: complete the reference
host, named workspace documents/storage and templates, shared controls,
comparison/replay coordination, and every P1-P6 readiness requirement.

Keep the replay-loading lock gap in scope: `beginReplayAt` clears picking before
awaiting sub-bars, while the replay controller is still absent. Coordinated
replay must hold the workspace lock through that await and handle cancellation.

### Indicator templates in the consumer

Task 1 is committed as consumer `1de1c37dd`: modern version-2 preferences
retain exact repeated studies and pane placement, while legacy arrays retain
their previous duplicate-healing policy. The terminal validates every descriptor
before replacing studies, checks chart ownership after module loading and rolls
back a thrown restore. Price bars and viewport are preserved.

Task 2 is committed as consumer `744c18d12`: the catalog hook creates an adapter
in the account effect, counts pending operations, closes on cleanup and rejects
obsolete account completions. Nine tests use the real repository, including
failed writes/retry, account switch, unmount, reload and StrictMode.

The consumer now vendors source `7e27c3c` in commit `679f8b7a4`:
`openalgo-charts-2.4.0-7e27c3c.tgz`, 1,142,277 bytes, SHA-512
`WdGF1RtEKi0RUqS/JYkpfkFrXUM2jgJqU8MztI8rZXFihg/Ui0nyfSzlxMgWBxs7doFKhxrLths3nCJ9+2KWFQ==`.
The lockfile and extracted package match. Real authenticated market evidence in
`live-market-time.json` confirms that `ltt: 1789732772` is retained despite a
later delivery timestamp; the resulting 5-minute last bar is 1789732500, with
1,513 sorted valid-OHLC bars and no delivery-day candle. Session-calendar
validation remains open because that reported event time is after cash hours.

The dialog is committed as consumer `92e55c173`. Eight component tests and all
539 affected consumer tests pass. The initial full UI suite passed 2,151 tests
across 128 files. Browser regressions exposed focus stealing by the first pane
when its shared control opened; workspace controls now preserve the selected
pane. Firefox also exposed a visibility notification whose microtask still ran
inside a render. A failing unit regression now requires the next browser task;
pending timers are cancelled on unmount. Visibility tests must flush that task
before sending the opposite transition. The correction is committed as
`4a02be54e`; all 2,152 consumer tests across 128 files now pass. Full consumer
lint, type build and production build pass; the existing large visualization
chunk warning and simulated-DOM canvas notices remain. Generated tracked assets
were restored after the build.

Mobile assertions now finish the dialog resize transition before measuring its
width. The dialog is constrained to a 16-pixel viewport margin; screenshots
disable finite animations so they show the settled surface. All 26 compatibility
checks now pass in each of Chromium, Firefox and WebKit. Current reports have zero
page errors and runtime events; console counts 28/1/30 include only injected
resource failures and the expected mode-mismatch refusal. An earlier WebKit
reload also reported a caught custom-index fetch as a page error; the narrowly
scoped departing-document diagnostic classifier now covers that exact local
index URL, retaining the notice separately. Window errors/rejections still fail.
Desktop and narrow screenshots were visually inspected. Reports and images:
`artifacts/candidate/templates-{chromium,firefox,webkit}*`.

The live dialog also saved, reapplied and deleted a temporary empty template in
the authenticated account, preserving the actual market context and 1,513 bars.
Its final apply measured 1,968 ms; a preceding live wait exceeded 10 seconds but
was later observed complete. These are individual checks, not a performance
guarantee or fresh-trade evidence. Both temporary validation entries were removed.
The earlier live method probe covers four study instances and interval restoration.
Sanitized live dialog report: `artifacts/candidate/live-template-dialog.json`.

The focused-chart template consumer phase is complete. F1 full-grid layouts,
reference-host controls, comparisons, shared replay/toolbar and P1-P6 remain
required. The score remains an assessment; these checks do not establish a
90-point production claim. Added-line, untracked-file and local commit-message
scans still contain no excluded comparison names.

### Named-grid preparation

Plan: `2026-09-19-named-grid-workspaces.md`. Optional row/column weights now
preserve unequal grid tracks in portable documents. Eight new regressions failed
against the previous parser; all ten new cases and the 46 document/repository
tests now pass. The full library gate passes lint, types, 5,324 unit tests, build,
231 demo tests and eight declaration entry checks. Public references remain
901/901. The initial aggregate size check exceeded its old 223 kB limit by 42 B.
Ruling: weighted-grid validation is intentional optional-tier cost, so the all-tier
budget becomes 224 kB (223.04 measured); the workspace tier remains below its 6 kB
budget at 4.89 kB. Base 78.51 kB, widget terminal 184.75 kB and tree-shaken
chart-only 49.92 KiB are unchanged by these document fields. Size and shake
checks pass after that budget adjustment. Packing and consumer validation remain.

Weighted-grid source is committed as `117fb9d`; consumer `e9a2b4c47` vendors
`openalgo-charts-2.4.0-117fb9d.tgz`, 1,142,510 bytes, SHA-512
`tagbi0XKqdt1t7TwKaNMiQ0qOUcIT3LDIFtqtNGkZdZX4kkvj3lTA/XWKC7sWfZW/5yZSIt0sgrGH5BhqCFuqg==`.
Consumer build/types and 544 affected tests across 40 files pass; the installed
candidate passes all 26 Chromium compatibility checks. No additional engine
interaction changed; the prior three-browser template evidence remains separate.

Consumer `c558093a0` introduces pane capture and injectable preferences. Four
preference regressions reproduced ignored adapters and blocked-storage crashes;
five now pass. Capture regressions were observed against the absent method; ten
cases now cover detached settings/studies/drawings and rejecting stale history,
replay, pending study/drawing loads and unavailable charts. All 83 tests in the
two terminal files pass, formatting/lint and TypeScript build pass. A real
authenticated chart capture retained its symbol/interval, viewport, volume and
drawings envelope without forbidden execution keys (`live-workspace-capture.json`).
The live Vite dependency cache still owns the earlier market-time package; the
weighted package was tested in the fresh compatibility server. Prepared initial
restoration and atomic grid publication remain unimplemented.

Consumer `fa14464a8` completes the prepared-pane boundary. Initial documents are
validated and detached before terminal listeners, and their preferences use a
private map. Startup rejects missing metadata/history, unsupported type/interval,
missing studies, incomplete drawing restoration and cancellation. It awaits
settings, restores studies once, applies host series styles, and preserves weak
snapping. Volume visibility stays authoritative for both histogram and average.
Preparation holds the terminal trading lock, and failed initialization destroys
its resources idempotently. Ordinary unnamed startup retains its fallback.

Ten initial startup cases failed before implementation; drawing pane lookup,
the loading refusal message and volume-average visibility also have observed
RED regressions. All 417 affected consumer tests in 27 files pass, as do changed
file lint/formatting and the TypeScript build. The scoped resource audit verifies
data-owner destruction, socket close, visibility listener removal and zero
remaining fake timers on failure, with static checks of the other exits. This
is not a long-running process resource measurement.

The authenticated browser restored two identical averages and two oscillators
sharing a pane (one hidden, lengths 14 and 7), a trend line, weak snapping,
hidden volume and the exact viewport. The original chart retained its 1,513 bars
and zero studies, and the prepared chart read 1,512 history bars; no browser
preferences were written and One-Click remained off. Final preparation measured
148 ms with cached responses, not a latency guarantee or fresh-trade evidence.
Report: `artifacts/candidate/live-workspace-startup.json`. The live browser still
uses its prior cached engine tier; this change is consumer orchestration.
Grid publication, its menu, autosave and three-browser grid acceptance remain.

Grid conversion is consumer `5eede30c0`: 14 tests preserve every preset, unequal
tracks/spans, explicit imported geometry, focus/sync and all 16 allowed panes.
Imported pane IDs never become CSS. Consumer `a7f0f7bbd` adds the coordinator:
eight tests cover readiness order, failed history/storage, supersession, account
teardown, prompt cancellation and reentrant factory cancellation. This owner is
not yet connected to the page; the rendering and menu work remains.

Library `2f6b54c` adds cancellable activation and an optional expected catalog
revision. Four repository regressions and a real-browser pending-write regression
failed before implementation. Cancellation aborts the pending browser transaction
and removes its listener at completion/abort. A committed transaction cannot be
undone by cancellation. A changed prepared revision rejects before activation.
The full library gate passes 5,328 tests in 220 files, 231 demo tests in 16 files,
lint/types/build, eight declaration checks, size and tree-shaking. Workspace is
5.02 kB Brotli and aggregate 223.17 kB; base 78.51, widget terminal 184.75 and
chart-only 49.92 KiB remain unchanged. References cover 901/901 runtime names.
All 15 storage tests pass across Chromium, Firefox and WebKit.

Consumer `72b2280c2` vendors `openalgo-charts-2.4.0-2f6b54c.tgz`, 1,142,991 bytes,
SHA-512 `a/2h5Gwkh6GG7Aran/D/V11Qv9GJ9ZAIcN8s1boIVWq3UmTW42htGa+hzak7cURafGw0rtGhXwq3QRNeOlbzNg==`.
The installed candidate passes the consumer build/types, 596 affected tests in
44 files and all 26 Chromium compatibility checks. The screenshot was inspected;
the already-scoped shared-toolbar work remains necessary for narrow grid panes.
The existing large visualization chunk warning remains. Generated tracked assets
were restored. Reports: `workspace-activation-*` and `activation-candidate.*` under
`artifacts/candidate/`.

### Final release version

Consumer `0be0a0a49` added explicit workspace transition locks and destroyed-owner
execution refusal. Two observed failures now pass with the 106-test affected
suite. These locks still need to be connected to grid publication in the page.

Issue 2077 is implemented in library `deb6de3` and consumer `9860b3b69`: selected
OHLC/study values survive live updates, linked readouts follow the follower's own
bar, zero volume is readable, built-in index volume is hidden, mouse plot pan
preserves automatic fitting by default, and expression adapters expose combined
leg activity. See `2026-09-19-chart-correctness-2077.md` for reproduction, package
integrity, test/browser evidence, bundle cost and the connected-session limit.
Full consumer suite: 2,221 tests in 133 files. Full library suite: 5,339 tests in
221 files plus 232 reference-host tests. All 34 compatibility checks pass in each
of Chromium, Firefox and WebKit after the documented fixture timing corrections.
The development candidate is still version 2.4.0; nothing has been published.

The user also added issue 2077 and explicitly requested validation before fixes.
Plan `2026-09-19-chart-correctness-2077.md` covers its six chart correctness reports.
These are now validated and corrected. Resume the pending named-grid UI and every remaining
production requirement. This extends the scope; it does not replace the release
or earlier feature requirements.

The user selected **2.4.5** for the final validated chart package and its OpenAlgo
`/trading` integration. After completing the remaining implementation and gates,
update library release metadata, build and pack that exact revision, and update
the consumer's vendored dependency, lockfile integrity and integration guide.
Re-run compatibility against the final archive. The current 2.4.0 candidates are
development checkpoints; a version change alone is not readiness evidence.
The user's subsequent instruction authorizes the final commit and push, npm
publication, website deployment and GitHub release. This supersedes the earlier
local-only restriction for the final validated release and companion integration.
Read `CLAUDE.md` before release and follow its complete measured-facts checklist,
including all repeated website, README, diagram, example and API facts. Push and
wait for CI; push the immutable tag and manually dispatch the Release workflow
for trusted npm publishing. Create the GitHub release after npm succeeds, deploy
Pages with its workflow, compare registry contents with the tested archive and
verify the deployed site in a real browser. Finally install the published package
in the consumer, rerun its checks, commit and push the integration. No additional
publication confirmation is required by the existing authorization.


### Named-grid consumer checkpoint

Consumer `a297af9f8` completes the prepared grid, workspace menu and autosave
integration with the verified `87f1589` engine candidate. The full suite passes
2,253 tests across 139 files; types/build and changed-file checks pass. Full lint
has the existing two warnings and two style notices recorded in the named-grid
plan. All 21 workspace checks pass in each of Chromium, Firefox and WebKit,
including storage refusal, stale catalog recovery, history failure, cancellation,
imports and locked execution. The corrected template fixture passes 15 Chromium
checks. Screenshots were inspected; generated tracked build files were restored.

Observed cleanup errors cannot release an already published grid or prevent
other owners from being released. Save as retains changes made during the write;
unchanged gestures settle back to Saved even with autosave off. Resource checking
covers owner maps/sets, links, timers, abort listeners and export URLs through
static review and regressions. Prolonged process/memory measurements remain P3.

### Additional open-interest and alert scope

On September 20 the user explicitly added
`D:/OpenAlgo-Voice/codex instruction/openalgo-charts-oi-and-alerts.md`.
Its complete requirements are preserved in
`../specs/2026-09-20-open-interest-and-alerts-requirements.md`.
They extend F1-F9/P1-P6 and the 2.4.5 release; they do not replace any prior row.
The eight initial open-interest edits exist uncommitted in the original charts
checkout. Keep that checkout intact; port its diff into this isolated branch,
then validate and finish the data paths, indicators, availability and status line.
Implement alerts as the requested base-engine controller with drawing/indicator
anchors, policies, lifecycle, rendering, events and versioned persistence, plus
schema-driven widget controls and compatible consumer integration. No alert sends
an order or delivers a webhook itself. No release is complete until this added
scope and the previous scope have evidence.


Open-interest plan: `2026-09-20-open-interest.md`. The supplied eight-file patch
is incorporated without changing the original main checkout. Data-path tests now
cover latest-level folding, absent/zero, live quote gaps, history reconciliation,
partial replay, cold-cache validation and transform omissions. The engine gate
passes 5,363 tests in 222 files plus 232 reference-host tests, lint/types/build,
declarations, size/shake and 901/901 reference coverage. Ruling: the optional
field's measured aggregate cost raises the widget-terminal budget from 185 to
186 kB (185.13 measured). Studies, capability/status UI, alerts, packed consumer
migration and all earlier unfinished scope remain required. The separate
OpenScript workflow is not being modified; document its `oi` and
`hasOpenInterest` integration contract when Task 4 is implemented.


## Studies and capability checkpoint

All nine new study tests failed before registration, then passed. Additional
regressions exposed the histogram appearance control and interval capability
reset; both were observed failing and corrected. Capability, status-line and
widget settings tests cover unknown, false, true, zero, missing, restore and a
capability-only context change. The no-dead-controls suite needed an actual OI
reading in its shared legend fixture; all thirteen chart types then passed.

Verification: lint, types, 5,382 tests in 223 files, build, 232 reference-host
tests and eight declaration checks passed. All three browser projects passed
rendered candle-color, raw-line gap, change gap, hovered zero and capability
control assertions. Chromium and Firefox study screenshots and the WebKit
unavailable-control screenshot were visually inspected.

Ruling: instrument capability is a separate legend option, not a destructive
rewrite of its saved readout switch. This preserves per-legend and chart
preferences through unsupported instruments. A standalone legend may receive
the same optional flag. Unknown capability permits a supplied observation.
If metadata is wrong, a host could suppress a valid reading; hosts own its truth.

Ruling: check the study and capability pixels together in one fixture to cover
the complete readout interaction. All three browser engines execute it.

Ruling: increase the all-tier budget from 224 to 225 kB for the three studies
and capability/readout integration. It measures 224.46 kB. Base is 78.92 kB,
indicators 29.84 kB, widget 42.68 kB and widget terminal 185.98 kB. Size and
shake pass after the budget change; chart-only is 50.25 KiB within 50.25.
Runtime counts are 105 studies: Trend 36, Momentum 29, Volatility 22, Volume 18.
Skills coverage is 907/907. Repeated public counts and final release sizes
remain part of the release documentation gate.

Task 3 is complete. Task 4's engine and widget behavior is implemented and
validated; full metadata threading is retained with Task 5. Reference-host and
OpenAlgo consumer migration, packed-candidate installation and consumer checks
are next. Alerts and the remaining production plan remain required.

The user explicitly froze the readiness score at 82 overall / 85 engine,
confirmed full remaining scope for 2.4.5 and renewed publication authorization.
Do not raise the score or publish a partial candidate.

Reference OI host/adapter checkpoint: request-scoped metadata removes unsupported
history OI before cache; the example preserves capability through rebuilds and
supports the optional readout. See the OI plan for red/green evidence, 5,383
library tests, 235 reference-host tests, six browser cases, API/skills validation
and the measured 186.1 kB terminal-budget ruling. Consumer migration and alerts
are still unfinished; this is not the final release candidate.

OpenAlgo OI checkpoint: consumer bcd334203 installs byte-verified b26d6d5 and
implements instrument capability, history placeholder suppression, the optional
selected-bar readout and disabled controls. All 2,259 consumer tests and the
production build pass. Each of three browser engines passes 17 actual /trading
checks including futures gaps/zero, crypto metadata and workspace restoration.
See the OI plan for artifacts, static resource review, warnings and limitations.
OI live-broker validation, reference secondary shared controls and final release
facts remain; alerts are entirely unimplemented and remain the next major feature.

Alert widget checkpoint, 2026-09-20: alert Tasks 1-5 are now implemented and
validated, including the engine, source bridges, drawing visuals, persistence,
widget editor/list and context menus. Full library suite 5508/5508; reference
suite 235/235; eighteen alert browser cases across three engines. Actual desktop
and narrow screenshots were inspected. API, declarations, skills, size/shake
and website build pass. The alert plan records regressions and measured limits.
Reference/yfinance and OpenAlgo /trading alert controls are not integrated yet.
Task 6 must migrate those hosts and install/test the exact packed candidate.
Connected-broker validation, remaining F/P production scope and final release
facts/publication remain required. The frozen readiness score is unchanged.

Reference alert checkpoint, 2026-09-20: yfinance now owns alert evaluators and
the shared editor/list for both charts. It persists their source identities,
drawing anchors and lifecycle records across rebuild and reload. Its replay
loading/cancellation and history-cache identity gaps are fixed; simulated
order/bracket execution is guarded throughout replay and data loading.
Full library 5511/5511; reference modules 244/244; reference browser suite
28/28, including twelve alert cases across all three engines. API, types,
lint, build, declarations, skills 917/917, size/shake and website build pass.
Real yfinance history and the editor were checked on the running 8125 server,
with 251 bars and no orders/fills. This does not prove connected-broker behavior.
Alert Task 6 remains open for the exact packed OpenAlgo consumer migration.
The remaining F/P requirements, final review, release facts and publication
remain required; version 2.4.5 is unpublished and the frozen score is unchanged.

Consumer alert checkpoint, 2026-09-20: OpenAlgo commit `834b582cc` installs the
exact packed chart build `2a7ca17` and integrates the alert toolbar, editor/list,
local delivery, preserved study/drawing anchors, workspace state and replay/data
loading guards. All 33 installed package files match. Full frontend suite is
2271 tests in 141 files; build/types and coverage pass. The combined browser
harness passes 43 cases each in Chromium, Firefox and WebKit, with inspected
desktop/mobile alert screenshots. No real orders were sent. The detailed alert
plan records warnings, resource review and remaining consumer gates. This is
another development checkpoint, not completion of Task 6 or the release.

Alert lifecycle/context checkpoint: charts `0939bcc` adds exact plotted-study
identity to the public context event and widget editor. Consumer `5846d7ae9`
installs that exact 33-file package, adds actual price/drawing/study context
actions, persists fired once-only alerts across named workspace reload with
autosave off, and aborts cancelled replay history without accepting late cache
results. Library 5513 tests and example 244 tests pass with full verification;
consumer 2293 tests, build/types, lint and API coverage pass. The consumer passes
46 combined browser checks per engine, 138 total, with inspected desktop/mobile
alert screenshots. Detailed evidence and warnings are in the alert plan. This
is progress toward the existing full scope; reference context parity, endurance,
connected broker and the remaining production/release gates remain open.

Reference context checkpoint: yfinance now offers price, exact study-plot,
drawing and alert-list actions for both charts, with chart/scope ownership
guards. The primary menu also excludes order actions from oscillator panes;
a regression exposed and corrected hidden menu rows being displayed by flex
styling. Five unit and nine cross-browser pointer regressions pass; complete
reference suites pass 249 unit tests and 37 browser tests. Selected editor
screenshots across all three engines were inspected. Repository lint/types and
website build pass, with the existing runner/root warning retained. This change
does not alter the packed library or consumer checkpoint. Sustained endurance,
connected broker, F1-F9/P1-P6 and final release requirements remain in scope.

### Shared consumer toolbar checkpoint

Consumer commit `3972843f7` replaces duplicated pane controls with one workspace
row following the selected chart. Panes retain their terminal and dialog state;
keyboard focus and the chart selector select the same owner. Staging grids never
publish controls, pending controls are inert, fullscreen relocates the selected
controls, and layout changes preserve surviving focus or select a surviving pane.
The selector stays visible during horizontal scrolling. The user guide is updated.

Six new unit regressions and duplicate-toolbar/hidden-selector browser failures
were observed first. Final consumer tests: 2299 in 142 files; build/types and lint
pass with existing notices. Combined browser validation: 59 checks per engine,
177 total. The final selector improvement passes 21 toolbar/baseline checks per
engine, 63 total, with another full consumer test/build run. Screenshots across
all engines were inspected. Detailed evidence and warnings are in the shared
toolbar plan at `2026-09-20-shared-toolbar.md`.

The installed chart package remains `0939bcc`; no published chart API or default
changed. The user confirmed concern for existing portal compatibility: keep shared
replay opt-in and preserve per-chart defaults. The source score remains frozen.
Reference-example toolbar parity is next. Sustained endurance, authenticated broker
checks and all remaining production/release requirements remain open. No release
was published. Original checkout edits were preserved.

### Reference selection and snapshot checkpoint

The reference example now uses explicit pointer/keyboard chart selection and
keeps snapshots bound to their captured chart, symbol and interval. Hover no
longer switches the owner; stale menus are rejected after a rebuild or request
change. The selected border paints above the canvas and is verified with actual
pixels. Snapshot conversion cannot rename an image after the request changes.

Final evidence: 255 example tests in 21 files and 40 reference browser tests pass,
with repository types and lint. Red/green regressions and artifact locations are
recorded in the shared toolbar plan. The existing runner color warning remains.
Remaining reference toolbar routing, F8 shared replay, broader production gates,
endurance, final broker validation and release work remain open. The library and
installed consumer package are unchanged. This is a local development checkpoint;
2.4.5 has not been published and the readiness score remains frozen.

### Reference shared controls and restoration checkpoint

The shared reference toolbar now routes symbol/expression, interval, range,
chart type, P&F mode, studies/settings, grid and reset to its captured selected
chart. Secondary history cancellation is independent, loading/failure cannot
autosave transient state, and alerts stay paused until valid history arrives.
The secondary chart retains its independent type, study identity/settings,
grid and selection through reload. Interval sync is optional and persisted.
Its canvas readout appears in exports and stacks above study legends. Chart 1
retains the reference trading simulation, with disabled Buy/Sell on chart 2.

Browser regressions also fixed secondary viewport broadcasts and primary resize
drift during saved split restoration. Final evidence: 261 example tests/21 files,
49 reference browser tests, types and lint pass. Final screenshots from Chromium,
Firefox and WebKit were inspected. The shared-toolbar plan records red/green
artifacts, resource review and the existing runner color warning. No library API,
packed consumer dependency or consumer source changed in this checkpoint.

Task 2 remains open for settings/readout parity, volume, comparison, replay and
fullscreen ownership. Remaining F/P scope, endurance, final read-only broker
validation and release work still apply. The release sequence is to validate
the packed candidate in /trading, publish 2.4.5, then pin /trading to the published
package and revalidate. Port 5000 has not been switched to the development
worktree. Nothing was published and the frozen score is unchanged.

### Reference settings, readout and volume checkpoint

Chart settings retain their selected owner through edits, Cancel, defaults,
context actions, rebuild and reload. Secondary timezone and calendar aggregation
are independent; confirmation refolds that chart and Cancel preserves its history.
Host-owned candle styles are reapplied on matching-type restore. Both charts now
have persisted volume visibility, candle-colour matching and configurable volume
MA on the same scale, including live tail replacement/append and replay-prefix
isolation. Heikin Ashi retains volume; unsupported price-bucket transforms explain
the unavailable controls. Missing volume and warmup remain gaps.

Additional regressions fixed a future daily-change reading during replay, the
primary transformed close showing raw candles, a fresh split displaying only its
first few bars, and a WebKit colour control displaying clipped hex text.

Final checks: 267 example tests/22 files, 64 reference browser tests, types and
lint pass. Three-engine settings and dark/light chart images were inspected;
browser pixels verify candle-direction colours and the colour swatch. The shared
toolbar plan records full artifacts, resource review and retained runner warning.
No library/package/consumer source changed, and no real orders were sent.

Task 2 still owns reference comparison/replay/fullscreen routing and compact
toolbar/readout polish. Reference F1/F2 restoration remains broader than the
secondary restore tested here, including primary request/type and initial calendar
timezone handling. F8, P1-P6, sustained endurance, final authenticated read-only
broker validation, whole-branch review and release/publication remain open.
The consumer stays at 3972843f7 with the 0939bcc candidate; 2.4.5 is unpublished.

## Release sequencing correction, 2026-09-20

The user explicitly requests publishing Charts 2.4.5 before completing the
remaining OpenAlgo /trading changes. This supersedes the earlier candidate-first
consumer release gate. Finish the chart package scope, reference example checks,
package/API compatibility checks, documentation and chart release review; then
publish npm, website and GitHub release. Complete and validate the remaining
/trading implementation against the published package afterwards. Do not make
new consumer feature work or its final connected-broker/deployment validation a
prerequisite for publishing Charts. Preserve the existing consumer worktree.
This changes sequencing, not an authorization to publish known chart defects or
a statement that the unfinished chart scope is complete. The previous 20-30
working-hour estimate covered both projects. No new release-time estimate has
been verified for the chart-only scope.

### Reference comparison checkpoint

Both reference charts retain their own comparison sources, hidden state and
scale modes through focus changes, type rebuilds and reload. Requests capture
their chart/interval/range/timezone and stale or removed results are discarded.
Source errors clear old prices and provide Retry. Removing the last comparison
restores the pre-comparison mode after rebuild. 278 example tests, 70 reference
browser cases, types and lint pass; a final style follow-up passes six focused
three-engine cases with a narrow error/retry layout. Screenshots were inspected.
Artifacts and remaining work are in the shared toolbar plan. F7 baseline/live/
replay engine work is still open; this checkpoint only completes host ownership.
No engine API or consumer dependency changed, and 2.4.5 remains unpublished.
The updated sequence is Charts publication first, remaining /trading work after.

### Comparison engine and common-start checkpoint

Comparisons now own independent scales and an optional common visible timestamp.
The legacy first-visible default remains; the reference host opts into common
mode and clears lines and legend readings when no shared start exists. The new
barAt readout withholds forming replay closes. History replacement with a fixed
global axis, live updates, replay start/seek/stop, sources added during replay,
inversion, manual ranges and chart-first cleanup are covered. Named hidden scales
release after their last series. Public docs and examples describe the contracts.

Package verification passes: 5531 engine tests/230 files, 278 example tests/23
files, types, lint, build, declarations, size and shake. The final host correction
passes the 278 example tests and 73 reference browser cases. API generation,
917-entry skills coverage and website build pass. The comparison-scales plan
records regressions, screenshot review, bundle impact and resource limits.

This is a local chart checkpoint. Broader F/P scope, sustained endurance, final
review and publication remain open; remaining /trading implementation and final
broker/deployment validation follow Charts 2.4.5 publication. No consumer package
or source changed here, and the score remains frozen.

### Reference replay and fullscreen ownership checkpoint

Focused replay retains its captured chart across focus changes and unrelated
chart rebuilds. Finer history and time formatting use its captured request and
timezone. Picker/transport/exit UI stays with that chart, pending responses cannot
survive owner closure, and direct chart destruction stops the playback clock.
Both charts' alert evaluation and every order-entry route remain guarded.
Fullscreen shows the selected chart while retaining shared controls and dialogs;
switching its selected chart works, and removing that owner restores the workspace.
Narrow transport wraps, and the toolbar's chart selector stays visible while scrolling.

Final verification: 280 example tests/23 files, 85 reference browser cases in three
engines, types and lint pass. Three additional fullscreen geometry checks pass.
Screenshots were inspected and retained; the shared-toolbar plan records red/green
evidence, resource review and browser capture limits. Compact canvas-readout polish
remains, along with F8, reference F1/F2, remaining production gates, endurance,
whole-branch review and publication. No library or consumer source changed.
Charts 2.4.5 still publishes before the remaining /trading work and final broker
validation. Nothing was pushed or published and the score remains frozen.

### Compact readouts and F9 checkpoint

Canvas legends now fit whole readings and hover actions inside their plots.
Long titles shorten, optional priority retains useful readings first, and resize
restores all stored fields. The reference gives close prices priority. Clipped
rows cannot intercept axis clicks. Public and example docs describe the behavior.
The focused toolbar audit and compact browser evidence complete Task 2/F9;
shared-clock replay is still the separate F8 requirement.

Final package verification passes: 5538 engine tests/231 files, 280 example
tests/23 files, lint/types/build/declarations/size/shake. All 90 reference and SVG
browser cases pass; compact screenshots were inspected in three engines. API
generation, 917-entry skills coverage and the website build pass. The shared-toolbar plan records
regression evidence, corrected test assumptions, Firefox navigation limits,
resource review and the measured 0.39 KiB base-bundle increase.

Remaining chart work: F8, reference F1/F2, remaining production contracts,
endurance, whole-branch review and release facts/version/publication. Existing
consumer work remains preserved and its remaining implementation and final
connected-broker/deployment checks follow Charts 2.4.5 publication. Score frozen.

### Shared replay availability prerequisite

ReplayController now accepts explicit primary/finer candle availability times.
Time seeks leave a later history empty, withhold coarse final values until close,
and form only a contiguous observed prefix. OI stays a last reading, missing OI
stays absent, and the recorded final candle replaces the aggregate at its end.
Preparation without entry lets a coordinator validate every participant before
mutation. Existing replay defaults remain unchanged. This is Task 1 of the new
shared-replay plan, not completion of the F8 group clock or reference transport.

Fifteen new cases pass; the affected replay/comparison sweep passes 86 tests.
Package checks pass through declarations with 5553 engine tests/232 files and
280 example tests/23 files. The measured 0.94 KiB base increase required a budget
adjustment; size and shake then pass, with chart-only size unchanged. All 91
built/reference browser cases pass in three engines, and rendered evidence was
inspected. API generation, 917-entry skills coverage and the website build pass.
Detailed command outcomes, budgets and resource limits are in the shared-replay
plan. No new timer/listener or consumer change. F8 Tasks 2/3 and the remaining
release scope stay open; Charts publication still precedes /trading integration.

### Shared replay coordinator checkpoint

The opt-in ReplayGroup drives captured charts from one UTC observation clock.
Focused/all changes preserve time, inactive charts capture fresh data on entry,
and exit restores data and viewports. Preparation, validation rollback, callback
failure, reentrant stop, chart destruction and ownership cleanup have regression
coverage. Defaults of ordinary charts and standalone replay remain unchanged.

All 22 new group cases and 108 affected cases pass. Package checks pass through
declarations with 5575 engine tests/233 files and 280 reference tests/23 files.
Measured full-base cost is 1.81 KiB; revised size budgets pass, and chart-only
imports remain within the unchanged budget at 52.30 KiB. All 94 built/reference
browser cases pass in three engines, and the new screenshots were inspected.
API generation, 918-entry skills coverage and the static website build pass.
The shared-replay plan records exact command outcomes and resource limits.

This completes F8 Task 2, not its reference transport (Task 3). Reference F1/F2,
remaining production contracts, endurance, final review and publication stay
open. No consumer changes, push or publication. Charts 2.4.5 publishes first;
remaining /trading implementation and final broker/deployment checks follow.

### Reference shared replay and F8 chart checkpoint

The yfinance host now drives captured charts with ReplayGroup and one transport.
Focused/all controls preserve UTC time, appear during picking and playback, and
remain available across fullscreen and narrow layouts. Separate history slots
cancel independently; partial volume/OI and empty readouts stay chart-specific.
Source changes and active participant closure restore survivors. Invalid inactive
histories preserve focused replay; restoration errors release the UI with feedback.

Full package verification passes: 5575 engine tests/233 files and 297 example
tests/24 files, types/lint/build/declarations/size/shake. The final host placement
fix passes the 297 examples and all 91 reference browser cases. Three strengthened
legend/paint cases also pass. API generation,918-entry skills coverage and the
static website build pass. The site required a serial retry after heap allocation
failure during concurrent browser work. Screenshots and resource limits are recorded
in the shared-replay plan. No library size or consumer changes in this checkpoint.

Charts/reference F8 is complete. Reference F1/F2, remaining production contracts,
endurance, final whole-branch review and release facts/version/publication remain.
Charts2.4.5 publishes first; remaining /trading implementation and final broker/
deployment validation follow. Nothing pushed or published; score remains frozen.

### Reference primary layout startup checkpoint

The saved primary symbol, interval, history period, chart type, box mode and
timezone now initialize the reference host before its first history request.
Calendar folding therefore starts in the saved timezone. The schema-2 snapshot
contains an allowlisted request; unsupported explicit metadata is rejected before
control writes, while unambiguous legacy dataset keys remain recoverable. A live
chart cannot be redirected through this startup helper.

Five new persistence cases and two browser regressions failed before the fix.
All 302 reference tests in 24 files, lint, typecheck and the full 97-case reference
browser sweep pass. Restored chart screenshots were inspected in all three engines.
An initial Chromium startup timeout passed on a trace-enabled isolated rerun and
the complete sweep, without further changes; the original failure remains recorded
in the plan. No library runtime, size or consumer changes. Original OI edits remain.

This completes the primary restoration prerequisite. Reference F1 named catalogs
and transactional switching, F2 templates, production contracts, endurance, final
review and publication still remain. The user reconfirmed Charts 2.4.5 publication
before remaining /trading work; the design now states that authorized order.

### Reference portable workspace adapter

The reference snapshot now maps to and from the library's validated workspace
payload. Both source requests/types/timezones, study identities/styles/grouping,
drawings and fired anchored alerts, volume/comparison preferences, selected chart,
link options and horizontal split widths survive the round-trip. Slot ordering
owns chart placement. Unsupported geometry, source periods, exchange identifiers,
host settings and conflicting shared-rail preferences are rejected before restore.
Configuration is projected without runtime history or trading/account state.

Task 1 of the reference-named-workspaces plan is validated by 21 adapter cases,
all 324 reference tests in 25 files, lint/typecheck and actual two-chart round-trips
in three browser engines. An observed legacy volume-visibility regression is fixed.
No user-facing named menu is claimed yet: staged live switching and catalog/UI
tasks remain, followed by F2 and the production/release scope. No consumer changes.

### Reference prepared workspace transitions

The reference host now prepares both raw histories before publishing a workspace.
Each source uses its own interval and timezone; expressions share cancellation
across their legs. Source changes, pan/zoom, destruction and superseding opens
cancel pending work. Unknown studies, invalid drawings and conflicting linked
source settings are rejected before requesting data. Failed persistence leaves
the original charts intact. Installation failure restores both previous charts
from raw bars and configuration, with an optional storage rollback receipt.

Alerts, autosave, replay entry and simulated order entry remain guarded during the
switch. Actual browser checks verify anchored/triggered alert restoration without
evaluating history, plus raw-history rollback of transformed charts. There are 17
transition cases; all 346 reference tests/26 files, lint/typecheck and 112 browser
cases pass. A final focused transition sweep covers the last receipt branch.
Rendered installation evidence inspected in all three engines. The plan records
an initial early-cancellation fixture failure and its final validation.

Reference F1 Task 2 is complete. Named catalog persistence and its create/save/
open/rename/duplicate/delete/recent/autosave/import/export controls remain Task 3.
F2 and all remaining production/release requirements stay in scope. No consumer
changes or publication; Charts 2.4.5 still publishes before remaining /trading work.

### Reference named catalog controller checkpoint

The named catalog controller now serializes repository operations, captures the
active chart owner for autosave, rejects another session's unacknowledged revision,
and restores catalog selection after a failed publication. Autosave coalesces
changes and cannot write into the fallback recent entry after deleting its owner.
Legacy recovery migrates once and does not overwrite a saved layout with autosave
off. Reopening a layout drops queued snapshots from the previous displayed state.
Failed-save feedback survives unrelated export actions.

Integration testing exposed a cancellation race after storage commit. Transition
publication now receives the committed receipt before handling cancellation, so
compensation cannot be skipped. The regression fails before that fix. The full
reference suite passes 366 tests/27 files; lint/typecheck and 18 relevant browser
cases across three engines pass. Browser cases include the real IndexedDB adapter
and prepared source publication. Tooling retries are recorded in the task plan.

Task 3 is still in progress: toolbar dialog, startup/autosave wiring and portable
file controls are not connected yet. F2, remaining production checks, endurance,
whole-branch review, version/docs updates and publication remain. No consumer
changes or publication; Charts 2.4.5 precedes remaining /trading integration.

### Reference named-layout controls and startup complete

The shared toolbar now opens a Layouts dialog with create/save/open/rename/
duplicate/delete, recent entries, autosave and portable import/export. The existing
quick-save button saves the displayed named layout. Startup initializes the catalog
before requesting history and restores its saved source and rail preferences.
Autosave off preserves the saved document across reloads; enabling it captures
already-edited chart state. Legacy recovery is retained and migrated once.

Browser storage failures and revision conflicts remain visible and support explicit
retry. Missing custom studies at startup preserve the stored document and block
automatic replacement. Import also accepts older reference files with unambiguous
source metadata. Closing a pending import cancels the switch; replay disables
source-changing actions. Keyboard focus, fullscreen and narrow layout are covered.

The named-workspaces plan is complete. Verification: 371 reference tests/28 files,
lint/typecheck, the full 136-case reference browser suite and a final 21-case
three-engine named-layout sweep after strengthening autosave-enable coverage.
Rendered wide/narrow dialogs inspected. Initial failures and fixes are recorded
in the task plan. No library bundle, consumer dependency or publication changes.

Reference F2 remains, followed by production contracts/endurance, whole-branch
review and release documentation/version/publication. The design also names chart
data download from the source images; no reference-host or widget data-download
handler was found in the current audit, so keep that explicit artifact open.
Charts 2.4.5 still publishes before remaining /trading integration and final broker
validation. Frozen score unchanged; no new release time commitment.

### Shared indicator-template planning and saved-template updates

The optional workspace tier now exports planIndicatorTemplate and its mode type.
Planning preserves existing identities on append, discards incoming identities,
retains repeated studies and pane grouping, rejects missing descriptors before
mutation and validates append boundaries/limits. WorkspaceRepository.saveTemplate
updates a saved template in place with detached settings and atomic revision checks.
The consumer's existing host-local policy informed this shared implementation;
consumer imports will migrate after Charts publication.

All 66 focused workspace cases and the complete package verification pass:
5591 engine tests/234 files, 371 reference tests/28 files, lint/types/build/dts/size/
tree-shaking. Workspace is 5.53 kB Brotli (6 kB budget); all tiers are 240.03 kB
(240.5 kB budget). Base, terminal and chart-only sizes are unchanged. API generation
is warning-free and skills coverage is 919/919. Documentation covers both APIs.

This is Task 1 of the reference-indicator-templates plan. Reference application,
dialog and browser validation remain Task 2. No consumer changes or publication.

### Reference indicator-template controls complete

The shared toolbar now opens Templates for its captured selected chart. Named
capture/update/rename/duplicate/delete and JSON import/export share the layout
catalog and revision guard. Import stores a new copy; explicit replace/append
applies its studies. Settings, plot styles, visibility, repeated studies and pane
groups survive chart rebuilds and reloads. Stale owners and missing descriptors
reject before mutation. Partial restore attempts recovery and reports failure.

Drawings and valid retained alert anchors survive append; replacing a study drops
its anchor through the normal lifecycle. Fired alerts remain and history fires
nothing. Replay application retains the displayed prefix. Primary mirrors retain
complete study records and skip intermediate restoration events. Storage failures
stay visible. Keyboard, fullscreen and narrow dialog behavior are covered.

Verification: 379 reference tests/29 files, lint/typecheck, all 151 reference browser
cases and a final 18-case dialog sweep in three engines after a hover-contrast fix.
Rendered wide/narrow screenshots inspected. Invalid initial fixture plot/settings
keys and native fullscreen Escape behavior are documented in the task plan. No
engine changes followed the already verified shared-planner commit 6f4ac1d.

Reference F2 is complete. Chart-data download, remaining P1-P6 contracts, endurance,
whole-branch review, version/docs/site updates and publication remain. Original
OI edits and consumer work are preserved. Charts 2.4.5 still publishes before the
remaining /trading implementation and final connected broker validation.

### Reusable chart-data CSV snapshot

The base package now exports exportChartDataCsv and ChartDataCsvOptions. It reads
installed primary rows with UTC seconds and unrounded OHLC/volume/OI, configured
study plots with instance identity, and eligible comparison closes in original
price units. Missing/nonfinite readings stay blank, zero stays zero, and replay
only exposes its installed prefix. Headers have safe fixed prefixes and CSV
escaping; no trading/account data is serialized. Reading comparisons does not
create a controller or subscribe to chart events. Explicit controllers can supply
their own handles. The helper initiates no browser download or history request.

Nine export cases and all 44 focused comparison/export cases pass. Full package
verification passes 5600 engine tests/235 files, 379 reference tests/29 files,
lint/types/build/declarations/size/tree-shaking. Base 89.40 kB, terminal 201.25 kB
and all tiers 240.25 kB remain within existing budgets; chart-only stays 52.30 KiB.
API generation is warning-free and skills coverage passes 920/920 after rebuilding.
Task 1 of chart-data-export is complete; reference/widget download controls are
still Task 2. P1-P6, endurance, final review and release work remain open.


### Reference and widget chart-data downloads complete

The yfinance Layouts dialog and snapshot menu now download CSV from the captured
selected chart. The widget Capture menu uses the same serializer and rejects
loading, changed sources and browser file failures. The file includes loaded
bars, OI, studies and aligned comparisons, with a transform/replay-aware reference
filename and no future replay rows. Download resources are released on failures.

Validation: 5601 engine tests/235 files, 387 reference tests/30 files, lint/types,
build/declarations, warning-free API generation, skills 920/920 and tree-shaking.
The full affected browser sweep passes 175 cases; final CSV tests pass all 12 in
three engines after fixing the transform filename and clipped widget label.
Screenshots inspected. Widget budget is now 47 kB (actual 46.83), combined budget
241 kB (actual 240.504); size checks pass after recording the feature cost. The
verify pipeline stopped at the former size limit; its remaining gates passed
separately. See the chart-data-export plan for initial failures and corrections.

The dedicated browser on CDP 9227 confirms an authenticated broker-connected
session at /trading. That server's checkout still declares Charts 2.4.0; this is
access evidence, not candidate validation. No orders or consumer changes were
made. Original eight OI edits remain. P1-P6, endurance, final whole-branch review
and release work remain; Charts 2.4.5 precedes remaining consumer integration.

### Parallel production-contract and release checkpoint

The user explicitly requested parallel agents. Exclusive ownership separated
instrument integration, adapter/trading contracts, widget translation and browser
endurance. P1, P2, P4 and P5 implementation is complete in the Charts candidate;
P6 policy, upgrade guidance, API/skill docs, changelog and website are prepared.
P3 has a reusable real-browser harness and completed diagnostic runs; its reviewed
30-minute candidate run is still active. The production-release plan records
terminal checks and owns the publication gates.

The reviewed package passed 5734 engine tests in 242 files, 389 reference tests
in 30 files and seven harness tests, plus lint, types, build, declarations, sizes
and tree-shaking. Public coverage is 930/930 and API generation is warning-free.
The website build and all six existing website interaction checks pass. OI,
instrument, release and upgrade pages also run in three actual browser engines.
Runtime dependency audit is clean. Original eight OI edits remain preserved.

Independent review corrected alternate primary-scale ticks, large quantity-grid
tolerance, mutable trading requests, superseded broker completions, comparison
whitespace retractions and replay-selection autosave. The final package review
also found duplicated capability-error identity across the base/trade bundles;
its minimal shared-import fix is undergoing complete package verification.
Browser startup diagnostics distinguish a missing module caused by local network
buffer exhaustion from an autosave failure; no runtime fix is claimed for that
resource error. Failed reports remain available beside targeted passing reruns.

All Charts F1-F9 reference functionality, OI and alerts are implemented. Named
layouts, templates, shared controls/replay, comparison and CSV are usable in the
reference host. Publication is still pending. Remaining OpenAlgo /trading
integration and final connected-feed validation follow Charts 2.4.5 publication;
the logged-in original server still uses 2.4.0. No live orders were placed and
the score remains frozen. See the current production-release plan for the exact
next gates rather than treating older checkpoint lists as current status.

Final local release gates now pass. The corrected complete package verification
retains 5734 engine/389 reference/seven harness passes. All 429 browser cases pass
without skips, the website and generated API rebuild successfully, and the final
30-minute endurance process exits 0 with all 24 declared gates passing. Its actual
loaded base/indicator bytes match the final package. The corrected package and
33-file archive are recorded in the production-release plan. Charts publication
and the subsequent consumer work remain open; no new rating is assigned.

### Charts 2.4.5 published

Source db8bcce was pushed to master, passed all GitHub CI jobs and is tagged
v2.4.5. npm trusted publication succeeded with verified signature and provenance;
latest is 2.4.5. All 33 registry archive files and its full SHA-512 match the
tested package. GitHub release and Pages deployment are public and verified.
The deployed runtime files match the build and its OI/instrument examples pass
three-engine browser checks. Full evidence is in the production-release plan.

The Charts release is complete. Remaining work continues in the isolated OpenAlgo
consumer after installing the published package: comparison capture/restoration,
shared replay and autosave recovery, selected-chart CSV, applicable shared-contract
wiring, updated integration documentation/skills and final connected-feed checks.
Existing OI, alert, named-layout, template and shared-toolbar implementations are
preserved. Original main-checkout edits remain untouched. Score remains frozen.


### OpenAlgo consumer acceptance and delivery

The published-package consumer is committed as 6e914b354 on
feat/production-chart-workspace and is under CI in
https://github.com/marketcalls/openalgo/pull/2083. It adds comparison persistence,
shared replay with workspace execution guards, selected-chart CSV and the final
OI/alert/workspace integration. The canonical guide, changelog and indicator
references describe the resulting controls.

The frozen consumer passes 2403 frontend tests across 150 files, TypeScript,
production build, lint and metadata/skill checks. Browser acceptance passes all
201 checks, 67 each in Chromium, Firefox and WebKit. Screenshots were inspected;
there are no unexpected console errors, runtime events or external HTTP. All 649
recorded source/configuration/harness hashes remain unchanged. Reports are in
D:/OpenAlgo-Voice/artifacts/consumer-245-final-browser-summary.json and the
consumer-245-final-{engine}-acceptance files.

The compatibility harness now supports consumer-owned acceptance modules,
subscription-aware LTP delivery, shared replay controls and OI-unavailable text.
A paint boundary before automated reload resolves the observed departing-document
visibility warning; failed reports remain preserved and assertions are unchanged.
No Charts engine, package, version or immutable release tag changed.

Authenticated cash-history validation passes on the final production build with
1440 historical bars plus one forming bar, blank OI and no invented study values.
The interface reports the cash instrument's unavailable OI explicitly. Futures
OI equality and final GitHub/actual-checkout rollout are still pending. The test
session uses real broker history and the installation's 502 custom indicators;
routed browser timings are not uninstrumented host performance evidence. No live
orders were placed, saved chart state is preserved and the score remains frozen.


### Consumer rollout complete

OpenAlgo PR https://github.com/marketcalls/openalgo/pull/2083 passed all CI jobs
(run 35517952000) and merged as 621eaab62. Its tree matches verified consumer
commit 6e914b354. Main CI run 35518540216 passed all jobs, including the frontend
matrix, browser checks, production assets and both container architectures.
The generated-assets commit is 1c3d11cbd. Issue 2077 closed with the merge.

The final broker check matches every one of 1309 futures OI readings by timestamp
against fresh broker history; plotted and exported readings agree, while three
forming/live gaps remain blank. Cash instruments retain blank OI and their explicit
unavailable message. Comparisons, alert bar-close defaults and shared replay/live
restoration pass. The corrected runner captures CSV in memory with no downloads.
The market was closed, so this is historical-data/UI evidence, not full-day
open-market endurance. No live orders were placed.

The original OpenAlgo checkout fast-forwarded cleanly to 1c3d11cbd, installed
registry Charts 2.4.5 and refreshed asset compression. Actual served-page checks,
without any asset overlay, pass with zero page/module errors, execution attempts
or browser downloads. Chart storage is preserved and validation databases/pages
are removed. Served HTML matches tracked dist exactly. Broker evidence is in
D:/OpenAlgo-Voice/artifacts/consumer-245-broker-recovered-2026-09-20T15-01-10-800Z
and consumer-245-broker-2026-09-20T15-16-28-877Z.

The user's refreshed /trading page now shows candle-colored volume. The reported
screen-width issue came from the test browser's fixed viewport. Relaunching that
browser with viewport=null preserved authentication and restored 1920-pixel width
through reload and new-tab creation, with 1822-pixel chart canvases. No application
patch was needed. Screenshots and dimensions are preserved as
consumer-245-original-final-colored-volume.png and
consumer-245-original-final-viewport.json under the artifacts directory.

Charts follow-up harness commit c54626d also passed its complete CI run
35518044292. Package source/tag db8bcce and the published 2.4.5 archive are unchanged.
The original Charts checkout's eight OI edits remain preserved. User guide,
changelog, indicator references and the consumer verification plan are updated.
All requested release and /trading delivery work is complete; the score stays frozen.
