# Charts 2.4.5 consumer implementation plan

> **For agentic workers:** Use superpowers:executing-plans for root integration and superpowers:dispatching-parallel-agents for the independent file owners below. Track verification before marking a task complete.

**Goal:** Complete the approved production workspace in `/trading` using published Charts 2.4.5.

**Architecture:** The terminal owns broker data, displayed series and execution guards. A workspace coordinator delegates replay transport to the published ReplayGroup; React owns one selected toolbar and one shared replay transport. ComparisonController and exportChartDataCsv supply alignment, common baselines and numeric export.

**Tech stack:** React, TypeScript, Vitest, Vite, openalgo-charts 2.4.5.

**Spec:** `D:/OpenAlgo-Voice/worktrees/charts-production/docs/superpowers/specs/2026-09-19-production-workspace-design.md`.

## Global constraints

- Charts publication comes first. Version 2.4.5 is published and verified; do not change its tag or package.
- Keep the score frozen. No new comparison product names, emoji or long dashes.
- Preserve original checkouts and concurrent work. Only this isolated consumer is edited.
- Broker orders remain authoritative. No live orders in validation; credentials stay in the browser.
- UTC seconds for chart data. Retain existing host timestamp boundaries and timezone behavior.
- Lock all workspace order routes during replay selection, loading and playback.
- Workspace files contain no execution state, credentials or balances.
- No future data in replay or comparison overlays. Sync by availability time.
- Runtime editors freeze before broad checks. Focused tests use at most two workers.

## Review focus

- A removed comparison whose history resolves late must never return or retain a subscription.
- A live inactive replay member entering all-chart scope must use its current displayed history.
- Cancellation during finer-history loading must release only its own generation and all resource guards.
- Cancelling replay selection must resume a dirty autosave without saving a replay prefix.
- Replacing a grid or source must stop the captured replay owner even if the selected toolbar moved.

## Ownership and interfaces

- Root: `terminal.ts`, terminal tests, comparison ownership helper/tests, `workspaceState.ts/tests`, shared template planner migration and this plan.
- adapter_conformance: package/lock, isolated installed package, vendor documentation, chart-indicator skill and dependency prose in terminal guide.
- browser_endurance: `workspaceReplay.ts/tests` and `replayTiming.ts/tests`.
- widget_contracts: `Trading.tsx`, `ChartPane.tsx`, `WorkspaceGrid.tsx`, comparison/replay React controls and React tests.

Ruling: the user's continuous implementation and explicit parallel-agent request supply the execution method and authority. The approved spec remains in force; no additional approval pause is needed. Independent agents must not edit another owner's files.

```ts
interface PreparedReplayMember {
  member: ReplayGroupMember
  isCurrent(): boolean
}
interface WorkspaceReplayTerminal {
  beginWorkspaceReplayPick(onPick: (time: number) => void, onCancel: () => void): boolean
  cancelReplayPick(): void
  prepareReplayMember(args: { id: string; sessionId: number; signal: AbortSignal }): Promise<PreparedReplayMember>
  setReplayParticipation(sessionId: number, active: boolean, state?: ReplayState): void
  restoreReplayMember(sessionId: number): void
  setWorkspaceReplayLocked(locked: boolean): void
  setReplayInvalidationHandler(handler: (() => void) | null): void
}
interface WorkspaceReplaySnapshot {
  phase: 'idle' | 'picking' | 'loading' | 'active'
  scope: ReplayScope
  ownerId: string | null
  state: ReplayGroupState | null
}
```

`WorkspaceReplayCoordinator` consumes visible `{id, terminal}` members. It exposes `setMembers`, `state`, `start(ownerId)`, `setScope`, `play(speed?)`, `pause`, `step`, `stepBack`, `seek`, `stop` and `destroy`; constructor callbacks are `onChange(snapshot)` and `onError(error)`.

The terminal exposes `comparisonState(): TerminalComparisonState`, `addComparison(symbol, exchange): Promise<void>`, `removeComparison(id)`, `setComparisonMode('price' | 'percentage')` and `exportDataCsv(): string`. `onComparisonsChange` publishes detached UI state. Items carry ID, symbol, exchange, label, color, loading/ready/error status and optional error text.

## Task 1: Published dependency and API references

- [x] Install exact 2.4.5 with a lock-only registry update; replace only its installed directory using the verified tarball. Check safe paths, registry integrity and all archive files.
- [x] Run API generation and skill coverage; update recent changes, export teaching and built-in collision list together.
- [x] Confirm only intended dependency fields changed and the installed base/trade error constructor is shared.

## Task 2: Comparison data, persistence and CSV

- [x] Add failing regressions for multiple independent sources, late completion after removal, interval reload, source failure and teardown.
- [x] Bind ComparisonController to each chart generation with `baseline: 'common'`; route bars and live ticks through per-source loading ownership. Retain specifications across chart rebuilds, dispose old requests/subscriptions before replacement.
- [x] Replace the workspace comparison rejection with validated capture/restore. Validate every source before activating a staged grid and preserve rollback on failure.
- [x] Export the displayed chart through `exportChartDataCsv(chart, { comparisons: controller.list() })`; test OI blanks, study columns, common alignment and the replay prefix.
- [x] Run `npx vitest run src/lib/trading/terminalComparisons.test.ts src/lib/trading/workspaceState.test.ts src/lib/trading/terminalWorkspace.test.ts --maxWorkers=2`.

## Task 3: Shared replay and terminal bridge

- [x] Add failing coordinator cases for selection owner, abort races, partial preparation failure, scope transitions, stale captures and exhaustive cleanup. Add timezone/calendar cases to timing tests.
- [x] Delegate observation scheduling to ReplayGroup. Prepare all visible members with a session ticket, abort signal and current-identity predicate. Acquire guards before series writes and release departed members after engine restoration.
- [x] Omit fixed primary `options.bars` so inactive members are re-prepared from current series on scope entry. Do not feed raw finer bars into transformed primary candles.
- [x] Bridge terminal loading pause, preserved live buffers, frame followers, viewport/autoscale, watermark, alert pause and all order routes. Restore every survivor before releasing workspace guards.
- [x] Run coordinator/timing tests plus terminal history, alerts and replay trading-lock tests with at most two workers.

## Task 4: Selected controls and autosave

- [x] Add failing React tests for comparison add/remove/mode, selected CSV target, one replay transport, focused/all scope and cancellation during selection/loading.
- [x] Wire page-owned coordinator to visible terminals only; preserve standalone pane behavior. Invalidate before grid replacement and source changes.
- [x] Pause autosave throughout every non-idle replay phase; test dirty state resumes after cancellation.
- [x] Run changed React/hook tests with at most two workers (49 tests across seven files).
- [x] Inspect narrow controls in three browser engines after integration.

## Task 5: Contracts, review and consumer validation

- [x] Migrate local template planning to the published workspace helper while retaining legacy preference migration. Adopt instrument metadata only from known broker fields; do not invent capabilities or session calendars.
- [x] Run the required fd-audit after stream/subscription changes. Update the canonical terminal guide with actual resulting behavior.
- [x] Freeze runtime inputs, run complete consumer tests/build, then the existing three-engine consumer browser harness and inspect screenshots. Preserve failures and repair with regressions.
- [x] Obtain fresh independent integration review; address material findings and rerun affected checks.
- [ ] Validate authenticated read-only history/source/feed behavior against the connected broker using the isolated consumer; no execution requests.
- [ ] Commit and push the authorized consumer change while preserving the original checkout; update the handover reply and release ledger with actual evidence and remaining limits.

## Execution record

- Base: 3972843f7, clean isolated consumer before migration.
- Charts release source: db8bcce; release facts commit: 383a0c1.
- Package owner reported exact registry integrity, all 33 installed files and shared-error identity verified. Full skill migration is still in progress.
- Package and skill migration completed: index 387 exports; coverage 64/64 named examples, 387/387 exports and 66/66 capabilities. The registry audit reports zero vulnerabilities. Root updated the remaining 105-study prose in CLAUDE and custom-indicator documentation/comments.
- Shared replay terminal bridge regressions observed missing methods, an execution-guard omission and wrong exit restoration before fixes. The combined engine/coordinator/terminal checks pass after destroying the group before restoring current live data. Finer unordered history falls back to complete candles; raw intrabar history is excluded from transformed charts.
- Root's latest focused checkpoint passes 101 tests across terminal history, workspace capture, workspace validation and template planning. The workspace planner now comes from the published package and rejects an append into an occupied pane.
- Comparison capture now uses captureBaseState to preserve the underlying linear/logarithmic scale. The terminal regression reproduced percentage leaking into saved base state before the fix. Configuration callbacks fire for comparison additions/removals/mode changes, while refreshes leave the workspace clean.
- Resource review reproduced a comparison-removal exception that stranded another socket/timer. Helper cleanup now attempts all releases and preserves the original error; 23 focused regressions pass, including 100 binding cycles with zero retained sockets/timers/handles. Root reproduced and fixed the terminal cleanup boundary and a queued bind/source-generation race; all 63 terminal-history tests pass. Independent review also reproduced replay restoration stopping after a chart callback failure; cleanup now resumes data and restores live buffers before reporting the first error (16 startup/restoration tests pass).
- The dedicated browser on port 9227 still reports loggedIn=true and brokerConnected=true against port 5000. This is session readiness only; the new consumer build has not yet been validated against that broker.

- Final source freeze includes saved-comparison validation recovery (11 regressions pass) and upstream main through ad3cd54df, merged as 3fae220cb. The full frontend suite passes 2400 tests in 150 files, with project TypeScript and production build passing. Lint exits zero with two existing warnings and two informational diagnostics. All 105 generated study entries match the package. The drawing metadata check exposed Windows CRLF sensitivity; normalizing line endings in that check resolves the false mismatch without changing generated metadata.
- Runtime source snapshot: 642 files, SHA-256 4dcc4deb9fe6ffd1d50a7398dc9ead7f916bcd641edd39f10d4a02ec814e40de, recorded outside the checkout in consumer-245-inputs-run1.json. Production assets are isolated in consumer-245-production-dist-run1. No tracked dist output or original checkout was changed by the build.
- Chromium run1 passed all 61 existing acceptance checks and then failed a new comparison tick assertion. The browser owner is investigating the mocked depth/LTP routing; no application conclusion is claimed from that failure yet.


## Final consumer acceptance checkpoint

The final runtime remains frozen after the OI missing-data message correction.
The complete frontend suite passes 2403 tests in 150 files. TypeScript and the
production build pass; lint exits zero with two existing warnings and two
informational diagnostics. The 105 study entries and drawing metadata match the
published dependency. Chart-indicator coverage remains complete: 64/64 named
examples, 387/387 exports and 66/66 capabilities.

All 201 consumer browser checks pass: 67 each in Chromium, Firefox and WebKit,
with zero unexpected console errors, runtime events or external HTTP. Screenshots
of shared replay, separate OI panes, comparisons and narrow alert controls were
inspected. The final runs include live CSV with 184 rows and replay CSV restricted
to 13 revealed rows, including study and comparison values.

The harness now models subscription-specific LTP messages and shared replay
controls. Two Firefox failures were preserved: all functional assertions passed,
but a departing-document visibility callback triggered a console warning. Waiting
for the preceding interaction to paint before reload resolved that automation
race; assertions were not weakened. No application change was made for it.

Evidence is preserved outside the checkout under D:/OpenAlgo-Voice/artifacts:

- consumer-245-full-tests-run3.log and consumer-245-build-run3.log
- consumer-245-final-browser-summary.json
- consumer-245-final-{chromium,firefox,webkit}-acceptance.json and screenshots
- consumer-245-final-acceptance-source-hashes.json: 649 inputs unchanged
- consumer-245-inputs-final.json: 642 runtime/configuration inputs, aggregate
  SHA-256 5f92b57550dac23bbf0eeadc6179860369b08cb05b78d0361b421b78afaf50d4
- consumer-245-production-dist-run2: final isolated production assets

Authenticated cash-instrument validation of that final build passes: 1440 broker
history bars plus one forming bar retain blank OI, the study invents no values,
and the interface explicitly reports that OI is unavailable. No page errors,
failed module requests or execution attempts occurred. Chart storage was
preserved and the disposable validation database was removed. Evidence:
consumer-245-broker-2026-09-20T14-40-37-799Z.

Positive futures OI validation remains active. This installation has 502 real
custom indicator modules; the routed production-build browser must finish loading
that catalogue before adding a study. Earlier short observation deadlines and an
unkeyed history capture were corrected in the external validation runner. These
routed timings are not uninstrumented host performance measurements. Publication
of the consumer and actual original-checkout rollout remain pending; the isolated
build and browser checks alone do not establish deployment.
