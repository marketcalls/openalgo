# Shared workspace toolbar implementation plan

> **For agentic workers:** Use superpowers:executing-plans for native implementation and regression-first verification.

**Goal:** Complete F9 with one toolbar acting on the selected chart in the OpenAlgo consumer and reference example.

**Architecture:** Chart panes retain terminal, dialog and control state. The consumer renders the selected pane's controls into a shared toolbar host using a React portal. Unselected and staging panes render no toolbar. Fullscreen returns the selected controls to their owning pane. Existing standalone ChartPane behavior and the published chart/widget APIs keep their defaults. The reference example already has one toolbar; its actions must resolve the focused chart consistently.

**Tech stack:** React, TypeScript, the existing terminal and grid ownership model, Vitest, Playwright.

**Spec:** `../specs/2026-09-19-production-workspace-design.md`, F9. User authorization covers continuing implementation and local validation without another design approval round. Shared replay remains F8 and will be opt-in for library consumers.

## Global constraints

- Preserve terminal identity, independent pane settings, drawing/study/alert state and feed ownership across focus changes.
- Preparing grids must never publish controls into the visible toolbar.
- Workspace transitions and replay continue to guard trading actions.
- No comparison product names in additions; use plain labels.
- Work only in the two isolated production worktrees. No live orders.
- The release target is 2.4.5; this phase does not publish a partial release.

## Review focus

1. Removing a focused pane must select a surviving pane without a stale terminal reference.
2. Portals must not allow staging grids or locked panes to publish interactive controls.
3. Keyboard selection and actual pointer focus must route actions to the same chart.
4. Fullscreen menus and screenshots must retain the selected chart's ownership.
5. A compact viewport must keep the toolbar reachable without overflowing the page.

## Task 1: Consumer toolbar ownership

Files: consumer `frontend/src/components/trading/ChartPane.tsx`, `ChartPane.test.tsx`, `WorkspaceGrid.tsx`, `WorkspaceGrid.test.tsx`, new `ChartToolbar.tsx`, `frontend/src/pages/Trading.tsx`; chart repository `scripts/check-openalgo-compat.mjs`, new `scripts/check-openalgo-toolbar.mjs`; consumer terminal user guide.

Interfaces: optional `toolbarHost?: HTMLElement | null`, `focused?: boolean`, `paneLabel?: string`, `chartSelector?: React.ReactNode` on ChartPane. Undefined host preserves the local toolbar; null means the shared host is not mounted yet. WorkspaceGrid accepts `focusedPaneId?: string` and publishes only from the active grid. Chart selection uses the existing `onFocusPane(terminal, paneId)` callback.

- [x] Add regression tests that render two real ChartPane components with one external host. Assert one toolbar, second-pane action routing after focus, unchanged terminal count, keyboard focus callbacks, no staging controls and fullscreen relocation.
- [x] Run `npm run test:run -- src/components/trading/ChartPane.test.tsx src/components/trading/WorkspaceGrid.test.tsx --maxWorkers=2`; observe failures for missing behavior.
- [x] Add the portal outlet, active-pane attributes and keyboard focus. Wire one toolbar host in Trading and active-only controls in WorkspaceGrid. Preserve or fall back focus on layout changes. Keep replay transport behavior unchanged until F8.
- [x] Run the two suites, affected trading/grid tests, typecheck/build and lint. Fix regressions before browser validation.
- [x] Add actual-browser checks for unique controls, chart-specific symbol/interval/type/studies/alerts/snapshot/replay, keyboard selection, layout reduction, named-grid preparation, fullscreen and compact layout. Run Chromium, Firefox and WebKit sequentially with D: temporary storage, inspect screenshots, retain reports.
- [x] Update the user guide and ledger, then commit the verified consumer implementation and browser checks locally.

## Task 2: Reference focused-chart controls

Files: discover the existing toolbar, split, indicator, snapshot and replay modules under `examples/yfinance/src`, and their unit/browser tests before editing.

- [x] Audit every shared toolbar action against the focused chart; record primary-only behavior as failing regressions.
- [x] Route symbol/interval/type/studies/snapshot/replay and relevant readouts through the selected pane while retaining independent state and source restoration.
- [x] Verify focus changes, pane removal, interval/symbol sync, OI absence, volume styles/MA, alerts and replay guards with example tests and actual pointer/keyboard browser tests.
- [x] Run the complete example/browser suites and update example documentation, ledger and local commit.

### Replay and fullscreen ownership ruling

Continue Task 2 from 12b547e. Capture chart, pane, primary series, request and
timezone when replay selection begins. One reference transport owns that captured
session even when toolbar focus changes. Keep the existing global replay activity
flags so every order-entry route remains locked. Pause alert evaluation throughout
selection/loading/playback; restore each chart's loading/failure pause on exit.
Moving focus must not redirect the playhead, finer-history request or exit.
Changing or closing the owner cancels pending work and restores its data before
teardown. Unrelated chart changes must not cancel the captured session.

Attach picker and replay-event subscriptions to each chart with chart-owned
cleanup. Replay controls and the exit dialog live inside the captured chart's
container so they remain usable in fullscreen. Fullscreen must select its captured
chart and retain access to the shared controls and dialogs; cancellation and owner
removal restore the ordinary workspace. This implements focused ownership only;
F8 still requires an opt-in shared clock with focused/all-chart modes.

Verify deferred loads, focus changes, chart replacement/closure, timezone cache
keys, cross-chart alert/order guards, data restoration and actual pointer picking
before the complete reference unit/browser sweep. No public replay default or
consumer source changes are needed for this host ownership step.

## Execution record

Pre-flight: consumer toolbar controls and dialogs already share ChartPane state; lifting that state would duplicate ownership. Portalling only the active control subtree preserves existing actions. Grid preparation already exposes an `active` flag, which must gate the portal in addition to CSS visibility. The original phase spec excluded publication; subsequent user instructions explicitly authorize the final release after the complete scope is verified.

Previous goal turn was a status response with preview verification, not implementation progress. Resume with consumer regression tests from charts `7079f46` and consumer `5846d7ae9`.

## Task 1 checkpoint

Consumer commit `3972843f7` implements one workspace toolbar with independent
pane state, keyboard focus, a visible selected-chart marker, fullscreen ownership,
inert transition controls and selection preservation/fallback on layout changes.
The chart selector stays visible while the other controls scroll. Original
standalone ChartPane defaults are retained. The chart package and public API have
not changed in this task, so this host UI change requires no library migration.

Six new unit regressions failed before implementation. The browser first exposed
the duplicated toolbar and later the selector scrolling out of view. The final
consumer suite passes 2299 tests in 142 files; the affected sweep passes 677.
Build/types pass. Changed-file lint is clean; full lint exits 0 with the existing
two warnings and two informational notices. The canvas test stub and large build
chunk warnings are retained. Generated tracked frontend assets were restored.

The combined consumer harness passes 59 checks per browser in Chromium, Firefox
and WebKit, 177 total, including Objects, foundation controls, OI, alerts,
templates, persistence, staging refusal/cancellation and named selection changes.
After pinning the selector, the toolbar and baseline checks pass 21 per browser,
63 total, and the full consumer suite/build were rerun. Selected desktop/mobile
screenshots were inspected. Fullscreen checks run when supported. The final
WebKit toolbar report retains one expected fixture reload cancellation notice;
no unexpected runtime errors or external HTTP were accepted. No real orders
were sent, and toolbar checks add no mocked orders.

Artifacts: `artifacts/candidate/toolbar-consumer-red.log`, `toolbar-browser-red.log`,
`toolbar-selector-red.log`, `toolbar-all-tests.log`, `toolbar-build.log`,
`toolbar-full-lint.log`, `toolbar-harness-lint.log`,
`toolbar-final-{chromium,firefox,webkit}.{json,log,png}`, and
`toolbar-selector-{chromium,firefox,webkit}.{json,log,png}` plus the toolbar
desktop/mobile images. Two animation frames after viewport restoration are
required before screenshots. Firefox may leave native fullscreen on Escape;
the harness exits it only if still active. The Objects identity assertion now
checks the stable study id required by alert restoration and a completed new
interval, replacing an obsolete expectation that rebuilding changes the id.

Static resource audit: the portal host is owned by the page; portal children
unmount with their pane. No transport, timer or subscription was added. A removed
unnamed pane clears a matching active terminal reference. This is not measured
endurance evidence. Narrow multi-column readouts remain crowded and are still
part of the broader responsive review before release.

Task 2 and the full F1-F9/P1-P6, live-broker, endurance and release scope remain
open. The package is still the local 2.4.0 candidate; final target is 2.4.5.

## Task 2 selection and snapshot checkpoint

The reference example now selects a chart by pointer press or keyboard focus.
Hovering another plot does not change ownership. Drawing controls and snapshots
use that selection. A captured snapshot menu keeps its original chart and request;
chart replacement or a changed request invalidates it. The image filename also
retains its original symbol and interval while asynchronous conversion finishes.
Closing the second chart selects the surviving chart through the same owner.

Four snapshot regressions and two selection failures were observed before the
implementation. The browser exposed a duplicate hover listener in drawing.js,
which was removed. Screenshot inspection then found the canvas covering the
selected-chart outline. A failing pixel assertion reproduced this; a transparent,
non-interactive border overlay now paints above the canvas in all three engines.
Selected-chart screenshots from Chromium, Firefox and WebKit were inspected.

Final checks pass: 255 example tests in 21 files, 40 reference browser tests,
repository typecheck and lint. Example JavaScript is excluded by the repository's
lint configuration; it is exercised by module, unit and actual browser tests.
The runner's existing NO_COLOR/FORCE_COLOR warning remains. Artifacts are
`reference-focus-final-{demo,browser,types,lint}.log` and the screenshots under
`artifacts/candidate/reference-focus-final-browser/`. Earlier failing runs are
retained as `reference-snapshot-red.log`, `reference-focus-red.log` and
`reference-selection-ring-red.log`.

Task 2 remains in progress: symbol, interval, chart type, studies, grid/readout,
settings, comparisons and replay still need consistent reference-pane routing.
This checkpoint changes no published library API or installed consumer package.

## Task 2 request, study and restoration checkpoint

Shared symbol, interval, history range, chart type, P&F mode, studies, grid and
reset controls now capture the selected chart and reject stale chart/request
owners. A chart selector uses the same explicit focus owner as pointer/keyboard
selection. Secondary chart requests include expression support and use their own
AbortController; replacement or closure cancels all legs without claiming the
primary expression slots. Pending/failed history pauses alerts and blocks
autosave. The reference Buy/Sell simulation is explicitly available on chart 1.

Secondary chart type, box mode, studies with stable instance ids/settings, grid,
focus and link preferences survive rebuild/reload. Interval linking is optional
and off by default. Study settings capture their chart and dispose their destroy
listener on close. Secondary OHLC/volume/OI readings use the canvas legend and
appear in exports without overlapping the study legend; absent OI stays absent.

Screenshot review reproduced a reload viewport defect: restoring the second
chart broadcast its viewport, and opening the split resized the primary after
its own restore. Restoration now preserves the saved pane width, waits for the
chart boxes to settle, suppresses viewport broadcasts and restores the primary
logical window with chart/request guards. The browser regression checks that
logical range across reload in all three engines.

Final checks pass: 261 example tests in 21 files, 49 reference browser tests,
repository types and lint. All three final shared-control screenshots were
inspected. Logs: `reference-controls-final-{demo,browser,types,lint}.log`; images
are under `artifacts/candidate/reference-controls-final-browser/`. Focused red
runs cover requests/types, caller-owned expression cancellation, studies/settings,
grid ownership, simulation ownership, loading/autosave, interval sync, exported
readout and viewport restoration. The intermediate interval diagnostic was a
checked-menu accessible-label assertion; the final test accepts the checkmark.
The existing NO_COLOR/FORCE_COLOR runner warning remains. Example JavaScript is
excluded by repository lint and is exercised by module/unit/browser checks.

Static resource review: pane history has one abort owner, closing a settings
dialog removes its destroy listener, chart destruction owns its canvas legend,
and rebuilt charts close their popup menus. This is not sustained endurance
evidence. No engine/package/consumer source changed, so the installed consumer
candidate remains unchanged. No real orders were sent.

Task 2 remains in progress for chart settings/readout parity, volume controls,
comparisons, replay and fullscreen ownership. Full reference workspace/template
work, F8 shared replay, broader production gates, endurance, final authenticated
broker checks and release/publication remain open. Version 2.4.5 is unpublished.

## Task 2 settings, readout and volume checkpoint

Chart settings now capture their selected chart. Live edits, Cancel, defaults,
context-menu entry and owner destruction use that target; incomplete history
cannot open the editor, and autosave skips unconfirmed edits. Secondary settings
retain their own timezone. History captures its folding timezone before awaiting
the feed. Accepting a changed calendar timezone refolds only its owner; Cancel
does not start a new request. A saved secondary timezone is read before history
is folded on reload. Host-owned primary series styles are now reapplied when the
saved and live series types match, fixing lost candle colours on reload.

Both charts have independent Volume controls for visibility, matching candle
colours, and moving-average period, colour, thickness and style. The histogram
and average share a scale. Missing values and warmup remain gaps. Tail updates
recompute only the averaging window. Displayed primary data owns the derived
volume, so replay seek/step/back and forming updates never display a final-volume
snapshot ahead of the current price bars. Saved volume settings survive rebuild,
reload and switching through an unsupported transform. Heikin Ashi retains its
volume and follows its displayed candle direction; other price-bucket transforms
disable the controls with a reason.

Readouts use each chart's instrument, displayed bars and zone. Regressions caught
the primary daily-change status reading future history during replay and the
primary transformed close displaying the original candle. Both now use displayed
bars. Screenshot review also found a fresh split keeping the empty chart's
viewport, which showed only its first few bars. Initial history now fits its own
content; saved non-empty windows remain preserved. A WebKit colour-input fallback
showed clipped text instead of a swatch; the input now paints its current colour
in every tested engine.

Final evidence: 267 example tests in 22 files, 64 reference browser tests,
repository types and lint pass. Screenshots of settings and dark/light volume
charts were inspected across engines, including the corrected WebKit swatch.
Browser tests assert actual candle-direction pixels and colour-control pixels,
average warmup/replacement/append/shared-scale, Heikin Ashi direction, hidden
volume, transformed unavailability, independent settings/Cancel, calendar
confirmation/reload, viewport restore and replay-prefix data/readout isolation.
The first whole-suite run after adding the transformed readout used an outdated
OI chart double; its public primaryBars method was added. One browser reload wait
ran before the page test handle existed; it now waits for that handle safely.
Neither was a reason to weaken the OI or browser assertions.

Artifacts: `reference-settings-volume-final-{demo,browser,types,lint}.log` and
`artifacts/candidate/reference-settings-volume-final-browser/`. Failing regressions
are recorded in `reference-settings-red-{unit,browser}.log`,
`reference-volume-red-{unit,browser}.log`, `reference-volume-replay-red.log`,
`reference-style-restore-red.log`, `reference-initial-split-view-red.log`,
`reference-color-control-red.log`, `reference-ha-volume-red.log` and
`reference-transform-readout-red.log`. The existing runner colour warning remains.
Example JavaScript is excluded by root lint; module, unit and browser checks
exercise it. No library/package/consumer changes or real orders in this phase.

Static resource review: derived-volume subscriptions and legends belong to their
chart, secondary reading caches are cleared on closure, the theme listener belongs
to the page, the session memo is weakly held, and closing settings removes its
destroy listener. This is not measured endurance evidence.

Task 2 remains open for comparison, replay and fullscreen ownership and compact
toolbar/readout polish. Reference primary request/type and named workspace/template
restoration, including the initial folded-timezone path, still need the broader
F1/F2 work. Shared replay is still F8 and opt-in. Full production gates, endurance,
final authenticated read-only broker validation and 2.4.5 publication remain open.

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

## Reference comparison ownership checkpoint

Comparisons now retain separate per-chart symbols, colours, hidden state and scale
modes through focus changes, type rebuilds and saved split reloads. The dialog
captures chart/request/timezone. Pending loads are deduplicated and aborted on
destruction or invalidation; removed or superseded sources cannot reappear.
Changing interval clears old prices before fetching, and failed or empty history
leaves a visible error with Retry. Additions/removals update the selected toolbar.
The original price-scale mode is carried through chart rebuilds so removing the
last source restores it. Saved colours accept the legacy three-digit hex form.

Red/green evidence: eight original ownership regressions, two stale-data cases
for empty/failed history, and the mode restoration failure after a type rebuild.
Final checks: 278 example tests in 23 files; 70 reference browser tests across the
four configured reference projects; types and lint pass. The final control-style
follow-up passed six focused browser cases in Chromium, Firefox and WebKit,
including a narrow error/retry layout. Final logs are reference-compare-final-
{demo,browser,types,lint,controls}.log under artifacts/candidate. Owned-dialog
images from all three engines and final WebKit wide/narrow retry images were
inspected. The reload test now waits for layout restoration to settle before
selecting a chart, avoiding a test action racing the saved focus restoration.
Existing runner colour warning remains. Root lint excludes example JavaScript;
imports, example unit tests and browser execution validate those modules.

Resource audit: each chart owns one comparison listener group in a WeakMap;
chart destroy clears requests and handles, and closing the split releases its
source list. No global focus swap or new window listener. No measured endurance
claim. No engine/package or consumer change, so no new engine sweep or consumer
repack was needed. No active validation jobs remain.

Task 2 still needs explicit replay/fullscreen ownership and compact selector/
readout work. F7 is NOT complete: the engine currently shares one baseline among
comparisons in a pane. The multi-source scale/common-time baseline, full live and
replay isolation audit, and their engine tests remain chart release requirements.
Reference F1/F2, F8 and remaining chart production gates also remain open. Follow
the revised release sequence above: publish the validated Charts 2.4.5 package
first; complete remaining /trading integration and its final broker/deployment
checks afterwards. Preserve existing consumer work. Score remains frozen.

## Reference replay and fullscreen ownership checkpoint

Replay now captures its selected chart, series, request and timezone. Its picker,
shades, watermark, transport and exit dialog belong to that chart. Focus changes
do not redirect it; an unrelated chart rebuild preserves it. Changing/closing
the owner cancels finer-history requests and restores data before teardown.
Chart-first destruction stops the playback clock and releases the transport.
Native chart click/hover listeners replace the accumulating main-container click
listener; linked hover does not choose a replay bar. Both charts' alerts and all
order-entry routes remain paused through selection/loading/playback, including
when the other chart is rebuilt. Replay time formatting and cache keys use the
captured timezone. The chart 1 last-price helper never returns chart 2's replay bar.

Fullscreen keeps the shared toolbar, drawing controls and dialogs in its subtree
and shows the selected chart. Explicit chart selection switches the fullscreen
owner; closing chart 2 exits fullscreen. Reparented rail/mobile controls return
to their original container. The chart selector remains visible while the toolbar
scrolls. The replay transport wraps inside a narrow pane with grouped navigation
buttons, and retains an explicit chart label and accessible button labels.

Evidence under artifacts/candidate:

- reference-replay-owner-red.log: two regressions for selected request ownership
  and timezone cache isolation failed before implementation.
- reference-replay-owner-red-browser.log and reference-fullscreen-red-browser.log:
  the old primary-only behavior failed actual-browser assertions.
- reference-replay-compact-red-browser.log: transport overflow reproduced at 390px.
- reference-replay-final-demo.log: 280 example tests in 23 files pass.
- reference-replay-final-browser.log: 85 reference cases pass across Chromium,
  Firefox and WebKit. Pointer picking, both-chart alert/order guards, owner load
  cancellation, unrelated rebuild, direct destruction, data restoration,
  fullscreen owner switching/closure and sticky selection are covered.
- reference-fullscreen-final-geometry.log: three final browser checks verify the
  fullscreen body fills the browser-reported viewport. Firefox's virtual screen
  can be shorter than the requested screenshot; that capture difference is not
  an unfilled browser viewport.
- reference-replay-fullscreen-types.log and reference-replay-fullscreen-lint.log:
  types and lint pass. Root lint excludes example JavaScript; import, unit and
  browser execution validate it. The existing runner colour warning remains.

Final screenshots are retained under reference-replay-final-browser/ and
reference-fullscreen-final-geometry/. Fullscreen dialogs and narrow transport
images were inspected in all three engines. The narrow split still needs compact
canvas-readout polish; this checkpoint does not claim that remaining F9 work done.

Resource review: one replay listener group per chart, removed on destruction;
owned primitives removed on exit; one existing playback clock stopped on exit or
destruction; one bounded finer-history cache; no added window listener. Fullscreen
moves existing controls instead of recreating their state. No sustained endurance
claim. No library, package or consumer source changed, so no repack was required.

Remaining chart work includes compact readouts, shared-clock replay (F8), reference
workspace/template restoration (F1/F2), remaining production gates, endurance,
whole-branch review and release/publication. The 12b547e comparison engine checkpoint
supersedes the earlier F7 baseline-gap note above. Publish Charts 2.4.5 before the
remaining /trading implementation and final connected-broker/deployment tests.
No push or publication occurred here; the score remains frozen.

## Compact canvas readout ruling

Continue from 7330cca. PaneLegend currently draws unbounded text and hit areas
across the price axis on narrow plots. Bound its drawing and hit testing to the
plot, preserve whole label/value groups, and reserve room for hover actions.
When the full row cannot fit, shorten the source title and omit lower-priority
groups instead of drawing partial numeric readings. Add an optional LegendValue
priority for hosts to retain the most useful reading; the reference gives its
close reading priority. Full-width rows retain their existing ordering and text.
Keep the original values so resize restores omitted fields. Verify canvas bounds,
atomic readings, action hits, resize, status switches, export and actual narrow
reference charts, then rebuild and measure package impact before committing.

## Compact readout and focused toolbar checkpoint

PaneLegend fits whole readings inside the plot and reserves room for hover
actions. Long titles shorten; lower-priority fields disappear without modifying
the stored readings. Resize restores them. Optional LegendValue.priority lets
the reference retain its close price first. Status switches apply before fitting.
Partial action rows preserve the end of the configured list. Both horizontal and
vertical hit bounds match the plot, including rows clipped below a short pane.
The engine, reference example, public reference and website docs describe this
behavior. Existing method signatures and host ownership remain compatible.

Final toolbar audit:

| Actions | Ownership |
| --- | --- |
| Symbol, interval, range, chart type, transform settings | Captured selected chart and request; stale menus refuse changes. |
| Studies, volume and MA, OI, comparisons, alerts, grid and chart settings | Per-chart state and scoped asynchronous work. |
| Snapshot and fullscreen | Captured chart; shared controls and dialogs remain reachable. |
| Replay | Captured selected chart; focus cannot redirect it; all-chart clock remains F8. |
| Drawing tools, magnet, reset | Selected chart through the existing rail and chart APIs. |
| Split, links, cache, theme and layout file controls | Workspace controls; named workspace/template expansion remains F1/F2. |
| Simulated Buy/Sell | Explicitly available on chart 1 only, guarded throughout replay. |

The preceding checkpoints plus the final compact checks complete Task 2/F9.
This is not completion of F8 or of the overall release.

Evidence under artifacts/candidate:

- legend-responsive-red-unit.log and legend-responsive-red-browser.log record
  unbounded canvas text and action hits before the fix. Seven focused regressions
  cover preferred whole readings, resize, status switches, both pixel ratios,
  action truncation and clipped-row hits. The vertical hit regression first failed
  in legend-responsive-height-red.log.
- legend-responsive-final-verify.log: lint, types, 5538 engine tests/231 files,
  build, 280 example tests/23 files, declarations, size and tree-shaking pass.
- legend-responsive-reviewed-browser.log: 90 cases pass with four workers,
  comprising 88 reference cases in three engines and two SVG raster comparisons
  at wide/narrow widths. Final compact screenshots in the matching output folder
  were inspected in Chromium, Firefox and WebKit.
- The first full browser run found an older assertion expecting every status
  field on a narrow plot. Its replay/day-change assertion now uses a wide viewport;
  dedicated compact tests verify omission and plot bounds. Two Firefox navigation
  timeouts under the default worker count did not recur in the complete four-worker
  run; no alert implementation or navigation timeout was changed.
- legend-responsive-final-api.log and legend-responsive-skills.log: API generation
  has no warnings and all 917 reference entries pass coverage.
- legend-responsive-website.log: static website build passes. Existing workspace
  root inference, build-tool lint configuration and runner colour warnings remain.

Measured base size is 86.44 KiB, up 0.39 KiB from 12b547e. Base plus trade is
94.05 KiB, terminal 198.29 KiB, all tiers 237.03 KiB and chart-only 52.32 KiB
(up 0.36 KiB). Whole-reading measurement and plot-bounded actions belong in raw
chart hosts; tier isolation still passes. The base/combined budgets increase by
0.5 KiB and chart-only to 52.50 KiB, with all unrelated budgets retained.
Measure release facts again after the remaining phases and version change.

Resource review: only per-frame text groups and measurements, with two stored
plot bounds. No new timer, event subscription, retained history or DOM tree.
No sustained performance claim. The consumer package is unchanged; remaining
/trading implementation and final broker/deployment checks follow Charts 2.4.5
publication. F8, reference F1/F2, remaining P scope, endurance, whole-branch review
and publication are still open. The score stays frozen.
