# Chart interaction foundations implementation plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task by task. The user authorized continuous native execution and local commits.

**Goal:** Supply independently configurable candle-center crosshairs, interval linking and richer volume rendering for the production workspace.

**Architecture:** Extend existing options and descriptors additively. Keep link callbacks host-owned and keep vertical snapping independent of OHLC magnet. Consumer wiring follows the packed library candidate.

**Tech Stack:** TypeScript, Vitest, Playwright, React and the existing library build.

**Spec:** `docs/superpowers/specs/2026-09-19-production-workspace-design.md`

## Global constraints

- No comparison product names in changes, commit messages or PR material.
- UTC seconds for engine data; preserve the default Asia/Kolkata behaviour.
- Sync between charts uses time, never another chart's logical index.
- Existing library options retain defaults. Engine tiers remain free of host DOM.
- Local commits only. No publishing, pushing or live orders.

## Review focus

- Empty data and future-space hover must not invent a candle or move the pointer hit target.
- An interval echo from a follower must not replace the group's agreed interval.
- Removed/destroyed charts must receive no callback, including removal during broadcast.
- The first volume average appears only after a full window; live replacement must correct it.
- Theme/style changes must recolour existing volume without changing volume scale or prices.

## Task 1: Independent crosshair center snapping

Files: `src/core/chart.ts`, `src/model/chart-state.ts`, `src/model/chart-settings.ts`,
`tests/crosshair-snap.test.ts`, corresponding public docs and widget browser tests.

Produces: `ChartOptions.crosshairSnapToBar?: boolean`,
`chart.crosshairSnapToBar(): boolean`, the matching `applyOptions` field and
`canvas.crosshairSnapToBar` settings key. Default false.

- [x] Add measured Chart pointer tests. Hover at `center + spacing * 0.3` and
  assert that the painted cursor x is the center when enabled and the actual
  pointer when disabled; pointer events keep their original position.
- [x] Assert horizontal price remains pointer-driven in normal mode, magnet still
  snaps OHLC when selected, empty/future positions remain unsnapped, and settings
  and state restore both true and false reversibly.
- [x] Run `npm test -- tests/crosshair-snap.test.ts` and inspect the failure.
- [x] Thread the option through construction, getter, mutation, state and schema.
  In the cursor update use `timeScale.indexToX(index)` only if an actual primary
  bar exists at the hovered index; retain the raw pointer for all hit tests.
- [x] Run affected crosshair, pointer, settings and state tests; add browser paint
  evidence before completing the phase. Commit the verified change locally.

## Task 2: Interval linking

Files: `src/link/group.ts`, `tests/link-interval.test.ts`, linking API guide.

Produces: `LinkOptions.interval?: boolean`, `LinkMemberOptions.interval?: string`,
`onInterval?: (interval: string, chart: LinkChart) => boolean | void`,
`LinkGroup.interval(): string | null`, and `setInterval(chart, interval): void`.
The chart's `interval` event accepts a token or `{ interval }`. Default sync off.

- [x] Test independent channel defaults, event and imperative delivery, enabling
  sync after separate changes, late joins, removal, invalid tokens and callback
  echoes. In a follower callback, echo a different token and verify it cannot
  overwrite the leader token or fan out recursively.
- [x] Run `npm test -- tests/link-interval.test.ts` and inspect failures.
- [x] Track member/current interval in LinkGroup and use the existing broadcast
  guard. Validate nonempty strings; interval support remains the host's decision.
  Ignore reentrant changes before mutating agreed state. Reset on destroy.
- [x] Run all link tests and typecheck; update documentation and commit locally.

## Task 3: Volume average and candle direction

Files: `src/indicators/volume.ts`, `tests/volume-study.test.ts`,
`examples/yfinance/src/indicators.js` where appropriate; consumer
`frontend/src/lib/trading/terminal.ts` and a focused helper/test.

Produces: backward-compatible volume settings for direction colouring and an
optional simple moving average, with period and line styling. Existing colour
defaults remain unchanged unless the host opts into candle direction.

- [x] Add a fixture with volumes `[10, 20, 30, 60]`, period 3; expect no line at
  indices 0 and 1, then 20 and `110/3`. Replace the last volume with 90 and assert
  the last average becomes `140/3`. Assert candle-direction colours and dojis.
- [x] Run the tests before implementation. Add descriptor settings/plot and reuse
  the existing SMA helper, preserving the histogram's volume scale.
- [x] Connect OpenAlgo's built-in volume to candle colours and configurable
  average without duplicating a scale or revealing future replay data.
- [x] Verify normal/transformed/live/replayed series and theme changes. Commit
  only after library and targeted consumer checks pass.

## Phase gate

- [x] Build and pack the candidate; install it in the isolated consumer with a
  portable dependency strategy recorded in the broader workspace plan.
- [x] Wire center snapping through the schema-backed settings dialog and interval
  sync through the existing terminal/link group; test supported interval refusal.
- [x] Run the actual `/trading` browser harness and inspect changed interactions.
- [x] Record commands, results and remaining F/P requirements in the ledger.
- [ ] Continue with workspace documents/storage and shared controls plans.
