# Shared replay implementation plan

> **For agentic workers:** Use superpowers:executing-plans for native implementation with regression-first verification and one final whole-branch review.

**Goal:** Complete F8 with an opt-in shared clock, focused/all-chart scope and time-aligned histories without future candle disclosure.

**Architecture:** Extend ReplayController with explicit availability-time projection while preserving its existing index-based defaults. ReplayGroup will prepare independent controllers and drive them from one clock; the reference host owns asynchronous history, scope controls and the existing workspace-wide trading/alert guards.

**Tech Stack:** TypeScript, existing chart events and replay primitives, Vitest and Playwright.

**Spec:** `../specs/2026-09-19-production-workspace-design.md`, F8 and its replay invariants. Continuous native execution is already authorized. Charts 2.4.5 publishes before remaining consumer implementation and final broker/deployment validation.

## Global constraints

- No future bars may be disclosed by synchronized replay or comparison overlays.
- Sync between charts uses time, never another chart's logical index.
- Existing library options retain their defaults. New APIs are additive.
- Replay and replay selection lock every order-entry route across the workspace.
- Engine tiers remain free of host DOM. Keep the established bundle boundaries.
- Keep comparison product names, new icons and long dash characters out of additions.
- Preserve both original worktrees and the eight original OI edits.

## Review focus

1. A later-starting instrument must stay empty before its first observation.
2. A coarse candle must not disclose final OHLC/volume/OI at its opening time.
3. Missing finer bars, holidays and unequal history lengths must not invent data.
4. Validation/loading failure or destruction must restore surviving charts and release the clock.
5. Switching scope while playing must retain one clock and a coherent common time.

## Rulings

Use host-supplied availability timestamps rather than inferring candle closure
from the next recorded opening. The next bar may follow a holiday; exchange
calendars belong to the host metadata contract. A callback can also represent
close-stamped data explicitly. Each end must be finite, at or after its opening,
and no later than the next opening. Finer bars that cross a displayed bucket are
not folded into it. Without finer data, a candle appears only when complete.

At a partial observation, fold only available finer bars; OI retains the last
reading and is never summed. The exact displayed candle replaces the partial
aggregate at its declared end. Before any available observation the chart is
empty and the replay state has index -1 and bar null. Publish the replay boundary
before primary data writes so comparison owners cannot disclose a future close.
Require a contiguous finer prefix beginning at the primary opening; after a gap
or straddle keep the last known prefix until the declared close. Otherwise the
partial high/low would omit unobserved history.

Prepare all members before group mutation. Group membership is captured for the
session; changing an active participant's source or destroying it ends the group
and restores survivors. Focused replay retains its captured member through toolbar
focus changes. Explicit scope changes retain the UTC playhead. A single timer
advances the union of active members' observation times, with bounded catch-up.
The host loads all required history before entering and stays guarded throughout.

## Task 1: Availability-time projection

Files: new `src/replay/timeline.ts`, `tests/replay-time.test.ts`; modify
`src/replay/controller.ts`, `src/index.ts`, the replay public references.

Interfaces:

```ts
type ReplayBarEndTime = (bar: Bar, index: number) => number;
interface ReplayTiming {
  barEndTime: ReplayBarEndTime;
  subBarEndTime?: ReplayBarEndTime;
}
// Add to ReplayOptions: timing?: ReplayTiming; startTime?: number; autoStart?: boolean.
// Add to ReplayController:
// seekTime(utcSeconds: number): void;
// time(): number | null;
// timePoints(): readonly number[];
```

- [x] Write failing tests for an empty prefix, one-minute versus five-minute
  availability, partial candles, exact final replacement, OI level folding,
  missing/straddling finer history, prepared controllers, seek/step/play/stop,
  malformed timing before mutation and comparison isolation.

```ts
const replay = new ReplayController(chart, {
  timing: { barEndTime: bar => bar.time + 300 }, startTime: 120,
});
expect(chart.primaryBars()).toEqual([]);
replay.seekTime(300);
expect(chart.primaryBars()).toEqual([data[0]]);
```

- [x] Run `npx vitest run tests/replay-time.test.ts`; observe missing behavior.
- [x] Build the validated observation timeline and connect it to the existing
  controller transitions. Keep legacy seek/index/intrabar tests unchanged.
- [x] Run replay, comparison and OI suites; then package verification, API/skills
  checks and affected built-browser tests. Document measured bundle impact and
  commit the reusable prerequisite.

## Task 2: One group clock

Execution rulings: require at least one uniquely named chart and explicit timing
per member. Default scope is focused, on the first member unless focusedId is
provided. Group ownership lasts until destroy, including while stopped; reject
overlapping group/active standalone replay before mutation. Member options carry
only series, bars, subBars, timing and onFrame; timing/transport options belong to
the group. Add ReplayGroupChartHost with optional destroy subscription and
isDestroyed flag, leaving the existing ReplayChartHost contract untouched.

Prepare every controller before entry. Child playback state reflects the group,
but only the group starts a timer. Deliver member onFrame callbacks and group
onChange after every active chart has reached the frame. Stop/destroy may cancel
an in-flight notification; stale work must not resume afterwards. Invalid user
arguments preserve the session. A runtime projection/callback failure terminates
it, cancels the timer, releases ownership/listeners and restores surviving charts.
Destroying an inactive member removes it; destroying an active member ends the
group. Empty histories are legal, with a null clock when no timestamp exists.
Ruling: inactive members can receive live bars. Revalidate and capture current
data before entry or re-entry, preserving the captured UTC start time. A failed
new snapshot leaves the existing session intact. This prevents restoration from
discarding bars received while another chart was the focused replay participant.

Files: new `src/replay/group.ts`, `tests/replay-group.test.ts`; modify
`src/index.ts`, `scripts/check-shake.mjs`, replay references and browser coverage.

Interfaces:

```ts
type ReplayScope = 'focused' | 'all';
interface ReplayGroupMember {
  id: string;
  chart: ReplayGroupChartHost;
  options: Pick<ReplayOptions, 'series' | 'bars' | 'subBars' | 'onFrame'> & { timing: ReplayTiming };
}
interface ReplayGroupOptions {
  scope?: ReplayScope;
  focusedId?: string;
  startTime?: number;
  speed?: number;
  barMs?: number;
  now?: () => number;
  scheduler?: ReplayScheduler;
  onChange?: (state: ReplayGroupState) => void;
}
// ReplayGroupState: scope, focusedId, active, time, index, total, playing,
// speed, and members: { id, active, state: ReplayState }[].
// ReplayGroup(members, options) owns prepared ReplayControllers.
// Methods: state(), seek(index), seekTime(time), step(n?), stepBack(n?),
// play({speed?}?), pause(), setScope(scope, focusedId?), stop(), destroy().
```

- [x] Pin unequal histories/intervals, empty members, scope changes, one timer,
  bounded catch-up, speed changes, validation rollback and destruction in tests.

```ts
const group = new ReplayGroup(members, { scope: 'all', now: clock.now, scheduler: clock.schedule });
group.play();
expect(clock.timers).toBe(1);
group.pause();
expect(clock.timers).toBe(0);
```

- [x] Run the new suite and observe failures before implementing group ownership.
- [x] Drive each active controller with seekTime; restore members leaving scope;
  emit the group change only after the frame has reached all active members.
- [x] Verify chart destruction and callback failure cleanup, public exports,
  tree-shaking, built browser behavior and the package suite before committing.

## Task 3: Reference shared transport

Execution rulings: capture each chart's loaded primary history and request/zone
identity, with separate finer-history request slots. Begin at the selected
candle's close; the transport addresses observation indices. Daily/weekly ends
use the captured local calendar, including daylight changes. Finer history must
not replace already transformed OHLC; such charts use completed values, and
unordered/overlapping primary times cannot join. An ineligible inactive chart
does not block focused replay. Controls live at workspace level in both scopes:
keeping them inside their captured chart hid them when another chart occupied
fullscreen. The label, not DOM placement, retains the captured focused owner.

Files: `examples/yfinance/src/replay.js`, `main.js`, `split.js`, `index.html`,
`styles.css`, `README.md`; example unit tests and `tests/e2e/yfinance-mobile.spec.ts`.

- [x] Add failing example/browser cases for all-chart selection, different
  intervals, focus changes, delayed/failed history, cancellation, scope changes,
  participant closure, reload guards and data/viewport restoration.
- [x] Add a plain scope control to picking and transport. Capture all participants
  and request/timezone identities; allocate a request slot per participant and
  abort all slots on cancellation. Load required primary history before group
  creation; unavailable finer history visibly falls back to completed candles.
- [x] Supply explicit interval/calendar end times from the reference feed. Route
  each chart's legend and volume from its own replay frame. Mark every active
  chart and retain the global order and alert guards through all transitions.
- [x] Run complete example and three-engine browser suites with four workers;
  inspect wide/narrow/fullscreen screenshots and verify keyboard controls.
- [x] Update example docs and ledger, run package/API/skills/site checks and commit.
  Defer remaining /trading implementation until after Charts publication.

## Completion evidence

F8 requires all three tasks, not just a new API. Keep F1/F2, remaining P contracts,
endurance, final review and release gates in the production ledger. Final npm,
website and GitHub publication require the complete chart release scope.

## Task 1 verification checkpoint

Availability-time replay is implemented and documented. It preserves legacy
index/formation defaults, allows preparation before entry, and exposes a copy of
the observation timeline for coordination. Validation precedes mutation. Empty
prefixes, missing/straddling finer data, OI absence/levels, exact final replacement,
backward/zero steps, playback, viewport restore, independent followers and
comparison boundaries have regression coverage. No shared group or host scope
control is claimed complete by this prerequisite.

Evidence in artifacts/candidate:

- replay-time-red.log: the initial twelve cases failed before implementation.
- replay-time-boundary-red.log: backward stepping from an empty prefix wrongly
  revealed the first candle before correction. The final targeted suite has
  86 tests in five files, including fifteen new timed-replay cases.
- replay-time-verify.log: lint, types, 5553 engine tests/232 files, build,
  280 example tests/23 files and declarations pass. The command then stopped on
  the measured bundle increase. Revised budgets pass in replay-time-size.log;
  replay-time-shake.log passes with additional controller/timeline exclusion
  assertions. Runtime source was unchanged after that build.
- replay-time-browser.log: 91 cases pass with four workers, including 88
  reference cases and the new built time-alignment case in three engines.
  All six before/after screenshots under replay-time-browser/ were inspected.
- replay-time-api.log: API generation has no warnings. replay-time-skills.log:
  all 917 coverage entries pass. replay-time-website.log: static site build passes.
  Existing runner colour and website workspace/lint configuration warnings remain.

Ruling: the optional controller's availability timeline costs 0.94 KiB in the
base bundle (86.44 to 87.38 KiB), while the chart-only import remains 52.32 KiB.
Base plus trade is 94.99 KiB, terminal 199.23 KiB and all tiers 237.97 KiB.
Increase those four budgets by 1 KiB, retain unrelated tier/chart-only budgets,
and assert that both replay controller and timeline disappear from chart-only
imports. Final release facts must be measured again on the versioned candidate.

Resource review: one linear observation index and partial snapshots per controller,
with binary-search time projection. The existing playback clock is reused; no new
timer, listener, host DOM or retained global history. No sustained performance
claim. The first typecheck caught array.at requiring a newer library target;
indexed access preserves the existing target. Consumer and original OI edits
remain untouched. Continue Tasks 2 and 3 before declaring F8 complete.

## Task 2 verification checkpoint

ReplayGroup now owns one clock over captured members, with explicit focused/all
scope and UTC projection. It prepares every member before mutation, snapshots
fresh data when an inactive member enters, and restores data/viewports on exit.
Callbacks run after the group frame; invalid controls retain the session, while
runtime failures terminate it and attempt cleanup on every surviving member.
Active chart destruction ends the group; inactive destruction removes that member.
The new host interface keeps lifecycle hooks optional for existing custom hosts.

Evidence in artifacts/candidate:

- replay-group-red.log: missing group before implementation. Scope and lifecycle
  regression logs then caught stale restoration, late history validation,
  unrepresentable clock intervals and inactive destruction interrupting a frame.
- replay-group-unit.log: 108 affected tests in six files, including 22 new group
  cases. replay-group-verify.log: lint/types, 5575 engine tests/233 files, build,
  280 example tests/23 files and declarations pass. The command stopped at size;
  revised budgets pass separately in replay-group-size.log. Do not describe this
  invocation of the full pipeline as an exit-zero result.
- replay-group-shake.log: chart-only import is 52.30 KiB, within its unchanged
  52.50 KiB budget. New group and existing replay/timeline exclusion checks pass.
- replay-group-red-browser.log: the built group API was absent before the build.
  replay-group-browser.log: 94 cases pass with four workers, including the new
  group transport harness in three engines and all 88 reference cases. All three
  common-clock screenshots were inspected. The harness is not the reference UI.
- replay-group-api.log: API generation passes without warnings. All 918 skills
  entries pass. replay-group-website.log: the static website builds successfully.
  Existing runner colour and website workspace/lint configuration warnings remain.

The coordinator adds 1.81 KiB to the full base bundle: base 89.19 KiB, base plus
trade 96.80 KiB, terminal 201.04 KiB and all tiers 239.78 KiB. Raise those budgets
by 2 KiB to 89.75, 97.50, 201.75 and 240.50; retain unrelated budgets and measure
all release facts again on the versioned candidate. Chart-only cost did not grow.

Resource review: one union of observation times plus prepared member snapshots,
one active timer and one optional destroy listener per member. Stop clears the
clock and restores charts; destroy also releases listeners and ownership. Scope
entry replaces stale inactive snapshots. No DOM in the engine and no sustained
performance claim. Consumer work and original OI edits remain untouched. Task 3
and the remaining chart release scope are still open; Charts publication comes
before remaining /trading integration and final connected-broker validation.

## Task 3 verification checkpoint

The reference host now uses ReplayGroup for focused/all replay. It captures
already loaded primary histories and identities before finer-history loading;
each participant has its own cancellable slot. Daily/weekly ends respect local
daylight changes; calendar intervals use the registry. Playback starts at the
selected candle's close. The slider counts observations, not primary bar indices.
Each chart owns its volume, empty/partial readout and replay marker. Both scopes
share workspace-level controls, remaining usable in either fullscreen chart.
Scope changes preserve time; exit restores data and viewports. Source changes,
chart closure, invalid timing and restoration failure have defined cleanup.

Evidence in artifacts/candidate:

- reference-group-red.log: initial host cases fail before implementation.
  reference-group-cleanup-red.log catches an invalid inactive chart blocking
  focused replay and a restoration error leaving the host guarded. Sixteen new
  host/timing cases now pass, including finer volume/OI and absent readings.
- reference-group-scope-red.log and reference-group-fullscreen-red.log catch
  controls confined to a chart and disappearing on a fullscreen scope change.
  Controls now live at workspace level while retaining the captured owner label.
- reference-group-verify.log: full package verification exits zero, with 5575
  engine tests/233 files and 297 example tests/24 files, lint, types, build,
  declarations, size and shake. The final host-only placement correction then
  passes all 297 examples again in reference-group-demo-final.log. Library source
  and bundles did not change after the full package check.
- reference-group-browser-final.log: all 91 reference cases pass in three
  engines with four workers. The three shared cases pass again in
  reference-group-readout-final.log with direct legend-write observation, then
  reference-group-pixels-final.log waits for paint before screenshots. Wide,
  narrow and fullscreen evidence was inspected across all three engines.
  The old scrub test assumed bar indices; its fixture now explicitly tests
  completed-candle fallback. Another test verifies observation and member indices
  separately. A WebKit capture before paint was corrected with two animation frames.
- reference-group-api.log has no warnings; all 918 skill entries pass. Final
  lint passes. The concurrent website build failed with heap allocation exhaustion;
  the serial retry passes in reference-group-website-retry.log, without changing
  memory settings or source. Existing runner colour and website workspace/lint
  configuration warnings remain. Firefox fullscreen screenshots retain the
  existing headless viewport/capture-size limitation; controls remain usable.

No new library bundle cost: base89.19 KiB, base+trade96.80, terminal201.04,
all239.78, chart-only52.30. Host resources are bounded by captured members and
two cached finer histories; requests abort on cancellation, one group clock owns
playback, chart subscriptions leave on destruction, and replay primitives leave
on exit. Picker alignment uses binary search. No endurance claim.

This completes the Charts/reference F8 implementation. The remaining consumer
F8 migration and final connected-broker validation follow Charts2.4.5 publication.
Reference F1/F2, remaining P contracts/endurance, whole-branch review, measured
release facts/version and actual publication remain open. Original OI work and
the consumer checkout remain preserved. Score stays frozen.
