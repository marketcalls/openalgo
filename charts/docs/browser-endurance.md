# Browser performance and endurance

`scripts/browser-endurance.mjs` measures actual Chromium Canvas2D charts through
Playwright. It complements `scripts/soak.mjs`, whose fake document and no-op canvas
are useful for engine lifecycle checks but cannot establish rendering performance.

The result is **current-candidate synthetic workload evidence**. It is not a
live-feed test, a connected-broker test, a full trading-day result, or a performance
promise for another device. The runner does not connect to feeds or send orders.

## Run it

Use Node 20 or later, the project's installed dependencies, and its Chromium
binary. Prepare the candidate with `npm run build` before starting the harness.
If Chromium is missing, install it with `npx playwright install chromium`.

```sh
node --test scripts/browser-endurance.test.mjs

# One-minute smoke, including the same rendering and memory gates.
node scripts/browser-endurance.mjs --duration-seconds 60 --sample-seconds 15 --cycles 5 --output /absolute/artifacts/p3-smoke

# Thirty minutes of measured wall time after warmup and teardown checks.
node scripts/browser-endurance.mjs --duration-seconds 1800 --sample-seconds 30 --output /absolute/artifacts/p3-candidate

# A separately declared, longer workload. It only counts after it finishes.
node scripts/browser-endurance.mjs --duration-seconds 22500 --sample-seconds 60 --output /absolute/artifacts/p3-session
```

On Windows, an output such as `D:/OpenAlgo-Voice/artifacts/p3-candidate` works. The
directory must be new and its final component must begin with `p3-`. If omitted,
the runner creates a unique `p3-browser-endurance-*` directory in the OS temporary
directory. Put artifacts outside the repository. Keep failed reports as well as
passing reports.

The runner serves only an immutable copy of `dist` and its dedicated fixture on an
ephemeral loopback port. It never calls the build or uses the shared Playwright
configuration, server, or `test-results` directory. A before/copy/after SHA-256
check refuses a snapshot if bundle bytes change while it is being copied. Later
builds cannot alter that run. External browser requests are rejected and recorded
as failures.

Use `--help` for all options. Defaults are two charts, 2,000 historical bars per
chart, ten forming-bar replacements per second per chart, five indicators per
chart (EMA, Bollinger Bands, RSI, MACD, volume), five seconds of live warmup,
30 measured create/destroy cycles, a 1440 by 900 viewport and DPR 1. `--headed`
opens a visible browser and records that choice. The renderer remains Canvas2D.

For a heap investigation, add `--heap-snapshot`. It writes
`live-end.heapsnapshot` after stopping live timing and before chart destruction,
with explicit start/end timestamps in the report. Snapshot collection is excluded
from the measured frame intervals. It can change the heap subsequently observed
by the final destruction check, so compare that diagnostic field accordingly.
Use `--dist-directory /absolute/earlier-run/snapshot/dist` to reproduce an earlier
run's exact bundle bytes. The new manifest identifies that input and rechecks its
hashes. Do not infer a leak solely from a single growth excursion; inspect retained
objects and compare the complete sample history.

## What is measured

The report records source commit, working-tree status, exact bundle hashes,
harness hashes, runtime package version, executable arguments, host CPU model and
logical processor count, RAM, OS, Node version, Chromium version, user agent,
graphics renderer, viewport and DPR. Commit identity alone does not establish
which build was used; the copied bundle hashes and runtime version do that.

The browser first warms shared chart state with five painted create/destroy
cycles. It then measures the declared number of cycles, awaiting real animation
frames before destroying every chart. Each cycle must contain at least 100 pixels
matching the configured candle body colors in the price plot. Collected heap,
DOM node and event-listener counters are compared before and after the measured
cycles. No chart canvas may remain.

The live phase creates the declared chart grid and warms it for the declared
period. Updates always use each original last bar's timestamp. Every memory sample
reads the actual length through `SeriesApi.getData()`, so an accidental append
fails the fixed-length gate. Every chart is expected to keep exactly the declared
bar count.

Retained-memory samples default to `--memory-mode quiescent`: pause only synthetic tick
delivery, await two animation frames for pending chart work, run CDP
`HeapProfiler.collectGarbage` twice with a delay between collections, then read
`Runtime.getHeapUsage` and `Memory.getDOMCounters` before resuming the interval.
The report asserts zero delivered updates during every collection. No missed
ticks are replayed. Sampling pause milliseconds are recorded per sample and in
total, and remain included in the requested wall time and animation timing. The
tick-delivery gate therefore measures the actual resulting cadence.

An uncollected heap observation before each pause records ordinary allocation
pressure separately from retained memory. `--memory-mode uninterrupted` keeps
synthetic ticks running during collection for diagnostic comparison. Because a
new tick can allocate between separate CDP collection and heap-read calls, that
mode cannot establish steady retained heap even though GC was requested. Keep
the mode attached to any cited result.

The report preserves every sample. The growth gate uses
the maximum collected heap above the initial live sample; a later recovery cannot
hide a previous excursion. The trend gate fits collected heap against measured
elapsed seconds by least squares and reports bytes per minute. It uses all live
samples, including the initial one, after the declared warmup.

An independent `requestAnimationFrame` loop records frame intervals in a bounded
histogram. Each sample also moves the real Playwright pointer over a chart and
measures two browser animation frames from receipt of the pointer event. This
checks event delivery and main-thread responsiveness. It does not measure physical
display latency, nor prove that every animation callback painted a new chart.
Long-task counts and durations are included as diagnostic evidence.

Initial and final price canvases must contain candle-colored pixels, and the
pixel hash of each live chart's price plot must change. Both are read from the
plot rectangle of the price-pane base canvas only. That canvas also carries the
price-axis strip, whose last-price tag moves with every tick in the candle
colours, so a probe over the whole canvas could pass both gates on the axis
alone; reports produced before the probe was narrowed to the plot stand for
their screenshots, not for those two gates. The crosshair is on the separate
overlay canvas and is not read. `start.png` and `end.png` preserve full
rendered charts for visual inspection. Inspect both images before citing a report
as release evidence. The run finally destroys the live charts and requires zero
remaining canvas elements.

## Gates

These fixed budgets are intentionally visible in
`scripts/browser-endurance-metrics.mjs`. A changed budget is a reviewed policy
change, not a way to relabel a failed run.

| Measurement | Pass requirement |
| --- | --- |
| Measured duration | At least the requested wall-clock duration |
| Memory evidence | At least three finite samples with distinct elapsed times |
| Quiescent collection | Zero delivered updates during every retained-memory sample |
| Actual series length | Exactly the declared bar count in every chart at every sample |
| Tick delivery | At least 85% of the requested timer cadence |
| Animation evidence | At least ten observed animation frames per requested second |
| Frame interval p95 / p99 | At most 50 ms / 100 ms |
| Largest frame gap | At most 1,000 ms |
| Frames above 50 ms | At most 5% |
| Pointer evidence | At least two observations |
| Pointer latency p95 / maximum | At most 200 ms / 1,000 ms |
| Rendered candles | At least 100 matching pixels per chart at both endpoints and every teardown cycle |
| Canvas change | Different initial/final price-plot hash for every chart |
| Maximum collected live heap growth | At most 8 MiB above the initial collected sample |
| Collected heap slope | At most 256 KiB per minute |
| Teardown retention | At most 64 KiB of collected heap per destroyed chart |
| Retained DOM nodes / listeners | At most ten nodes / zero additional listeners after collection |
| Remaining canvases | Zero after teardown and final destruction |
| Browser errors | Zero uncaught page errors, console errors, crashes or external requests |

Garbage collection during the live phase is included in frame timing. Fixed-size
browser histograms keep observation memory bounded; the Node runner stores the
small sample history outside the measured browser heap.

A very short run can fail the per-minute heap slope because shared browser/JIT
and measurement structures are still settling. The initial 15-second development
smoke exhibited this: approximately 202 KB of collected growth, with about 157 KB
arriving in its first five seconds, exceeded the unchanged slope budget. The
follow-up used the documented 60-second smoke with the default five-second
warmup. The failed report was retained. A short result must not be called an
endurance result, and a warmup or duration change must be recorded explicitly.

## Recorded results

### Bar count, 2.5.5

Three runs of the default live workload, changing only the bar count, on the
2.5.5 build on 2026-09-26:

```sh
node scripts/browser-endurance.mjs --bars 2000 --duration-seconds 120 --sample-seconds 30 --cycles 5 --output /absolute/p3-2k-bars
node scripts/browser-endurance.mjs --bars 10000 --duration-seconds 120 --sample-seconds 30 --cycles 5 --output /absolute/p3-10k-bars
node scripts/browser-endurance.mjs --bars 50000 --duration-seconds 120 --sample-seconds 30 --cycles 5 --output /absolute/p3-50k-bars
```

Each run had two charts, 150 bars in view, ten requested forming-bar replacements
per second per chart, five studies per chart (EMA, Bollinger Bands, RSI, MACD,
volume), Canvas2D, a 1440 by 900 viewport and DPR 1. The machine was an 8-core
desktop CPU (16 logical processors, 31.2 GiB RAM) running headless Chromium
149.0.7827.55; each `report.json` records the CPU model and operating system.
Other builds and test runs were active on the machine; the harness does not
control concurrent host activity.

| Bars per chart | Result | Frame p95 | Frame p99 | Frames over 50 ms | Pointer p95 | Updates delivered |
| --- | --- | --- | --- | --- | --- | --- |
| 2,000 | passed | 17 ms | 17 ms | 0% | 28 ms | 1,195 of 1,200 requested |
| 10,000 | failed | 134 ms | 150 ms | 49% | 137 ms | 958 of 1,200 |
| 50,000 | failed | 717 ms | 734 ms | 44% | 738 ms | 194 of 1,200 |

At 2,000 bars every gate passed. At 10,000 the frame-interval, slow-frame and
update-delivery gates failed; at 50,000 the pointer-latency and frame-count gates
failed as well. The memory, teardown, painted-candle and browser-error gates
passed in all three, and the screenshots show both charts drawn. The view
is the same 150 bars throughout, so the growth is work over the whole history
rather than drawing. Treat these as the recorded state of 2.5.5 on this machine,
not as a guarantee for another device. Frame budgets per bar count belong to the
render bench, which times the pan, zoom-out and tick paths directly;
[performance notes](performance-notes.md) records its measurements and budgets.

## Nightly run

`.github/workflows/nightly.yml` runs the thirty-minute workload every night on
the day's `master`, on a hosted Linux runner, with the defaults above:

```sh
node scripts/browser-endurance.mjs --duration-seconds 1800 --sample-seconds 30 --output "$RUNNER_TEMP/p3-nightly-endurance"
```

A failed gate fails the run, and the output directory is uploaded as the
`browser-endurance` artifact whether it passed or not, screenshots included. The
same workflow runs `scripts/soak.mjs` with `SOAK_TICKS=90000` (a 6.25-hour
session at four ticks a second) and `SOAK_CYCLES=1000`, and the render bench.
A nightly result is evidence for that runner: a shared virtual machine with a
software GL device, not the reference desktop the recorded results above came
from.

## Artifacts and completion

| Artifact | Purpose |
| --- | --- |
| `manifest.json` | Commit, dirty state, bundle and harness SHA-256 hashes |
| `snapshot/` | The candidate bundles and fixture actually served |
| `samples.ndjson` | Append-only collected heap, DOM and timing observations |
| `report.json` | Structured workload, environment, samples, thresholds, gates and terminal result |
| `summary.md` | Human-readable result and limitations |
| `start.png`, `end.png` | Real-browser pixel evidence |
| `live-end.heapsnapshot` | Optional retained-object diagnostic, collected after timing stops |

The process prints its PID, loopback address, output directory and each sample's
elapsed time. When starting a prolonged run through an agent or CI, preserve its
real process/session handle and poll it to terminal completion. A `running`
report, partial sample log, started process or requested duration is not a pass.
Completion requires exit code 0, `status: "passed"`, a finished timestamp, every
gate passing and screenshot inspection. Browser or harness errors produce a
failed report and exit code 1. Invalid arguments fail before a browser is started.

The heap measurement covers collected JavaScript objects, with additional CDP
embedder/backing-store fields preserved when available. It does not cover total
browser RSS, all native Canvas2D resources, the GPU process, or physical-device
thermals. CDP DOM counters and zero-canvas checks narrow teardown risks but do not
prove the absence of every native leak. A headless browser may draw with a software
renderer instead of the graphics device; the report declares which one it used.

Only the selected Chromium build is covered. Firefox, WebKit, WebGL, other DPRs,
mobile devices, appends, backfills, reconnects and actual host/broker behavior
need their own evidence. A final release must rerun against its final built
candidate. Earlier working-candidate runs remain useful diagnostic evidence but
must not be relabeled as validation of newer bundle bytes.

Optional package aliases for the integrating maintainer:

```json
{
  "endurance:browser": "node scripts/browser-endurance.mjs",
  "test:endurance": "node --test scripts/browser-endurance.test.mjs"
}
```
