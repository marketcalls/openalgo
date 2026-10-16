# Browser endurance implementation plan

> **For agentic workers:** Use superpowers:executing-plans for this scoped task. The parent coordinates shared files, review and commits.

**Goal:** Provide repeatable P3 evidence from actual Chromium rendering, responsiveness, bounded replacement memory and chart teardown.

**Architecture:** A standalone Node runner snapshots the existing dist, serves an isolated fixture on an ephemeral loopback port, and drives Chromium through Playwright. The browser retains bounded timing histograms; the runner collects heap after CDP garbage collection and writes raw samples, screenshots and explicit gates to an external artifact directory.

**Tech Stack:** Node, existing Playwright dependency, Canvas2D, Chromium DevTools Protocol.

**Spec:** `docs/superpowers/specs/2026-09-19-production-workspace-design.md`, requirement P3.

## Global constraints

- Synthetic current-candidate evidence only. No credentials, network feeds, orders or consumer changes.
- No comparison brands, new icons, emoji, em dashes or en dashes.
- Own only the new harness, fixture, harness tests and scoped documentation.
- Do not rebuild, modify shared Playwright configuration, use shared test-results, stage or commit.
- Snapshot dist before serving so parallel builds cannot change an active run.
- Artifacts use an external `p3-` prefix. Preserve actual process handles and final exit status.

## Review focus

- Empty timing or memory samples must fail instead of becoming a false pass.
- A same-time update must replace one bar; accidental appends must fail.
- A chart with a valid API but no painted candle pixels must fail.
- Heap trends must be measured after collection, excluding warmup, and reported without full-day extrapolation.
- Destroyed charts must leave no canvases or retained event-loop measurements in the fixture.

## Task 1: Gate calculations and fixture

Files: `scripts/browser-endurance-metrics.mjs`, `scripts/browser-endurance.test.mjs`, `scripts/fixtures/browser-endurance.html`.

- [x] Write failing tests for slope, missing observations, threshold failures and passing bounded samples.
- [x] Run `node --test scripts/browser-endurance.test.mjs` and confirm failure.
- [x] Implement finite-sample calculations and explicit gate assessments.
- [x] Implement deterministic candles with five indicators, fixed-length live replacement, rendered pixel checks, requestAnimationFrame histograms and painted create/destroy cycles.
- [x] Run the focused tests and syntax checks.

## Task 2: Isolated runner and evidence

Files: `scripts/browser-endurance.mjs`, `docs/browser-endurance.md`.

- [x] Implement immutable dist and fixture snapshots with SHA-256 manifest and source identity.
- [x] Run Chromium with fixed viewport and DPR, record host/browser/device details and refuse external requests.
- [x] Measure before/after teardown memory, live heap samples, bar counts, frame gaps, long tasks and browser pointer latency.
- [x] Save PNG evidence, raw NDJSON samples, report JSON and summary Markdown. Fail on unmet gates or browser errors.
- [x] Run `node scripts/browser-endurance.mjs --duration-seconds 15 --sample-seconds 5 --warmup-seconds 2 --cycles 5 --output D:/OpenAlgo-Voice/artifacts/p3-smoke-20260920-a` and inspect the PNG.
- [x] Run the 30-minute current-candidate workload with a live session handle, poll until terminal, and report its exact result.
- [x] Document thresholds, reproduction, measurement limits and optional package script for parent integration.

## Execution decisions

Existing user authorization covers continuous implementation and browser runs. The task's exclusive ownership and no-commit instruction take precedence over generic skill handoff and commit steps. Full package verification and final-candidate endurance rerun remain parent-owned to avoid redundant concurrent load and shared build changes.

The initial 15-second smoke failed two gates and is preserved. Screenshot inspection showed that subtracting 100 pixels from the price canvas width removed the latest candle; the first canvas already excludes the axis, so the probe now uses its full width. Collected heap grew approximately 202 KB in that short window, of which approximately 157 KB occurred in the first five seconds. The heap budgets were not changed. A follow-up 60-second smoke with the documented five-second warmup passed all 23 gates at `D:/OpenAlgo-Voice/artifacts/p3-smoke-20260920-b`.

Seven focused tests pass, including separate observed red/green regressions for a collected heap spike followed by recovery and non-quiescent sampling. Scoped ESLint, Node syntax checking and diff whitespace checks pass. The initial 30-minute run started with session handle 97680 and PID 41916. Its snapshots and reports are at `D:/OpenAlgo-Voice/artifacts/p3-current-candidate-20260920`.

The uninterrupted collection protocol exposed a measurement race. CDP garbage collection and heap reads are separate operations; a new synthetic tick can allocate between them. The initial run recorded temporary approximately 9 MiB steps while actual bar counts stayed fixed. A separate six-minute diagnostic reproduced the step and retained a heap snapshot after updates stopped. A 120-second diagnostic using quiescent collection kept all 25 samples between 9,075,048 and 9,331,216 bytes, with 2,747.4 ms of declared sampling pauses and 1,164 actual delivered ticks. The uninterrupted and quiescent post-stop snapshots each contain 50,264 ordinary objects and 471 element arrays; summed self sizes differ by only 32,810 bytes. These results support allocation between measurement calls rather than a demonstrated retained-object leak.

The runner now defaults to quiescent collection: pause only synthetic ticks, settle pending rendering, collect twice, read heap/DOM counters, and resume in `finally` without replaying missed ticks. Animation timing and elapsed wall time continue. Each sample asserts zero updates during collection, records sampling pause time and separately records uncollected allocation pressure. The same numeric budgets are preserved; prior failed reports remain unchanged. Optional `--memory-mode uninterrupted`, `--heap-snapshot` and `--dist-directory` support explicit reproduction and diagnosis.

A fresh 30-minute run used session handle 19587 and PID 11260 at `D:/OpenAlgo-Voice/artifacts/p3-current-candidate-quiescent-20260920`, copied from the initial run's exact immutable dist. The initial uninterrupted run reached terminal exit code 1 after 1,800.18 measured seconds and 18,001 ticks. Its sole failed gate was maximum live heap growth (9,979,196 bytes versus the unchanged 8 MiB budget). Its start/end screenshots show rendered candles and indicator panes, and all other gates passed. The corrected prolonged run reached terminal exit code 0 with all 24 gates passing after 1,800.1689 seconds and 17,906 ticks. Across 61 samples, collected peak growth was 418,100 bytes and slope was 5,951.33 bytes/minute; all bar counts remained 2,000 and every collection recorded zero updates. Sampling pauses totaled 6,721.9 ms, included in measured wall and frame time. Frame p95/p99 were 17 ms, maximum frame gap was 33.5 ms and pointer p95 was 25 ms. Create/destroy retention was 10,133.6 bytes/chart with no node or listener growth and zero final canvases. The end screenshot was visually inspected. Root owns broader package verification.

Root subsequently delegated the final-version run after the complete package verification passed. The unchanged harness snapshotted runtime 2.4.5 and started a separate 30-minute run with session handle 16066, PID 740 and ephemeral port 54137. Its artifacts are at `D:/OpenAlgo-Voice/artifacts/p3-release-245`; the base bundle SHA-256 is `47ac581b9444512bdc95980cb0774e4986ba3a759d84df85d026c3a2afea53ec`. Root's browser/site checks may overlap this run, and the earlier candidate run also overlaps its beginning. Frame measurements therefore include actual concurrent host activity and must not be attributed solely to engine cost. The separate manifest, workload timestamps and final report preserve this distinction.

A subsequent bounded release review reproduced a comparison alignment correction issue: a later whitespace item at a repeated timestamp did not retract the earlier value. Root owns its runtime fix and regression test. The `p3-release-245` snapshot therefore represents the pre-review 2.4.5 candidate. It reached terminal exit code 0 with all 24 gates passing after 1,800.1555 seconds and 17,905 ticks. Its 61 samples recorded 406,972 bytes of peak collected growth, 5,779.15 bytes/minute slope, frame p95/p99 of 17 ms, maximum frame gap of 33.4 ms and pointer p95 of 27 ms. Create/destroy retention was 10,109.87 bytes/chart with zero node/listener growth and final canvases. Sampling pauses totaled 6,788.3 ms. Start/end screenshots were visually inspected. The exact pre-review bundle hash remains attached to that evidence.

After the reviewed runtime passed root's full verification, root supplied final base bundle SHA-256 `9415d9e48f37417c5e35c26fb0134643ccbe7a0ad47847e8e69e25eaef1b24ff`. The unchanged harness verified that hash and started `node scripts/browser-endurance.mjs --duration-seconds 1800 --sample-seconds 30 --output D:/OpenAlgo-Voice/artifacts/p3-release-245-reviewed` with session handle 38693, PID 21468 and ephemeral port 62552. The immutable snapshot reports runtime 2.4.5 and the exact supplied hash. Its live phase began at `2026-09-20T10:23:07.320Z`; root's 429-case browser sweep and planned website build are concurrent host activity. No numeric threshold or harness source changed between these runs.

The reviewed run reached terminal exit code 0 at `2026-09-20T10:53:07.688Z`, with all 24 gates passing after 1,800.1599 measured seconds and 17,905 ticks. Across 61 samples, peak collected growth was 403,280 bytes and slope was 6,181.40 bytes/minute. All series retained exactly 2,000 bars and every collection recorded zero updates. The 107,904 observed frames had p95/p99 of 17 ms, maximum gap of 50 ms and no intervals above 50 ms. Pointer p95 was 31 ms and maximum was 31.7 ms. One 56 ms long task was recorded as diagnostic evidence during concurrent host work. Sampling pauses totaled 6,565.2 ms, included in measured wall and frame time. Create/destroy retention was 10,147.33 bytes/chart, with no node or listener growth, zero final canvases and no browser errors. Both start/end images were visually inspected; candles and studies were painted and both price-plot hashes changed. The runner, metrics and fixture hashes still match their manifest. All prolonged-run handles are terminal.

Root subsequently identified an unused trade-module packaging correction. After root rebuilt, static module parsing confirmed that the fixture imports only `openalgo-charts.mjs` and `openalgo-charts.indicators.mjs`; indicators imports only the base module, the base has no imports, and none contains dynamic imports. The complete loaded dependency closure is byte-identical to the final dist: base SHA-256 is `9415d9e48f37417c5e35c26fb0134643ccbe7a0ad47847e8e69e25eaef1b24ff` and indicators SHA-256 is `1f51fd2cf579c8460c10021738f6d87317c4434c9621e8c3c13b2e8971baafa9`. The comparison at `2026-09-20T10:45:26.984Z` is saved as `p3-release-245-reviewed/final-artifact-comparison.json`. Changed unused files are `index.d.ts`, `openalgo-charts.all.mjs`, `openalgo-charts.trade.mjs`, `openalgo-charts.trade.mjs.map`, `openalgo-charts.workspace.mjs` and `trade/index.d.ts`; this chart/indicator workload makes no endurance claim for them. Root authorized retaining the run without restarting because every loaded runtime byte is unchanged.
