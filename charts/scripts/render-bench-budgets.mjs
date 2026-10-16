/**
 * The render bench's budgets (tests/e2e/render-bench.perf.ts), as one table.
 *
 * Each cell of `measuredP95Ms` is the p95 step cost, in milliseconds, that the
 * bench measured on the reference machine for one renderer, one bar count and
 * one scenario: the lowest of five full runs. Other work can share the machine
 * while it measures, and load only ever adds time, so the lowest run is the
 * closest to what the machine itself costs. The budget that fails the run is
 * that figure times `margin`, never below `floorMs`:
 *
 *   budget = max(ceil(measured * margin), floorMs)
 *
 * The table holds measurements rather than budgets so that tightening one is a
 * measurement, not a judgement: after a cheaper path lands, run
 * `npm run bench:render` five times on the reference machine, put each cell's
 * lowest p95 here, then run `node scripts/check-render-bench-docs.mjs --write`
 * so docs/performance-notes.md quotes the same figures (CI fails until it
 * does). The margin is a separate policy and changes on its own, with its
 * reason in the commit.
 *
 * Why these two constants:
 *
 *   margin   The reference machine is a desktop CPU; a hosted CI runner has
 *            fewer and older cores, shares them, and gives the software GL
 *            device and the collector fewer threads. Four times the desktop
 *            p95 leaves room for a runner core half as quick and a busy run on
 *            top of that, and still fails a change that makes a path several
 *            times costlier, which is the regression this exists to catch.
 *   floorMs  One frame at 60 Hz. A frame that costs less is on time whatever it
 *            costs, so a budget below that line would police timer and
 *            collector noise rather than anything a user sees.
 */

const DESKTOP = {
  reference: 'the merged Release 3 build before its 2.5.8 version bump, lowest p95 of five runs on an 8-core desktop CPU (16 logical) in headless Chromium 149, 2026-09-26',
  margin: 4,
  floorMs: 17,
  measuredP95Ms: {
    canvas2d: {
      10000: { pan: 2.2, zoomOut: 5.3, tick: 20.1 },
      50000: { pan: 2.2, zoomOut: 19.8, tick: 49.2 },
      200000: { pan: 2.1, zoomOut: 53, tick: 152.2 },
    },
    webgl2: {
      10000: { pan: 11.1, zoomOut: 13.1, tick: 28.4 },
      50000: { pan: 10.8, zoomOut: 21.3, tick: 56.6 },
      200000: { pan: 11.1, zoomOut: 58.3, tick: 167.5 },
    },
  },
};

/**
 * The same table measured where the budgets are enforced: a GitHub-hosted
 * ubuntu-latest runner, in the CI bench job. Its first run (2.5.8's release
 * candidate) measured up to about five times the desktop figures, most in the
 * cells that lean on the software GL device (a webgl2 pan, 47 against 11 ms) and
 * in the smallest zoom-out (26 against 5 ms), so the desktop table times its
 * margin failed there while the code was unchanged. On a runner the budgets come
 * from the runner's own figures, with a smaller margin. Scaled by the desktop
 * ratios between 2.5.7 and this build, that margin would still fail 2.5.7's
 * tick cost and a lost level of detail at every bar count; neither has been
 * run on a runner, so that is an estimate, not a measurement. It is one run,
 * not the lowest of five: replace it with the lowest of the nightly
 * render-bench artifacts once a few exist.
 */
const HOSTED_RUNNER = {
  reference: 'a GitHub-hosted ubuntu-latest runner (4 vCPU) in the CI bench job, the 2.5.8 release candidate, one run, 2026-09-26',
  margin: 2.5,
  floorMs: 17,
  measuredP95Ms: {
    canvas2d: {
      10000: { pan: 10.8, zoomOut: 25.8, tick: 51 },
      50000: { pan: 11.2, zoomOut: 58.5, tick: 132.4 },
      200000: { pan: 10.6, zoomOut: 137.7, tick: 289.1 },
    },
    webgl2: {
      10000: { pan: 46.5, zoomOut: 57.2, tick: 113.2 },
      50000: { pan: 47.3, zoomOut: 69.5, tick: 172.3 },
      200000: { pan: 47, zoomOut: 147.9, tick: 383.6 },
    },
  },
};

/** Both tables, by where they apply. The docs quote both. */
export const RENDER_BENCH_PROFILES = { desktop: DESKTOP, runner: HOSTED_RUNNER };

/**
 * The runner table on GitHub Actions, the desktop one elsewhere.
 * OAC_RENDER_BENCH_PROFILE=desktop or =runner picks one explicitly.
 *
 * @param {Record<string, string | undefined>} env
 * @returns {'desktop' | 'runner'}
 */
export function renderBenchProfileName(env = process.env) {
  const asked = env.OAC_RENDER_BENCH_PROFILE;
  if (asked === 'desktop' || asked === 'runner') return asked;
  return env.GITHUB_ACTIONS === 'true' ? 'runner' : 'desktop';
}

/** The table this run is held to. */
export const RENDER_BENCH_BUDGETS = RENDER_BENCH_PROFILES[renderBenchProfileName()];

export const BENCH_RENDERERS = /** @type {const} */ (['canvas2d', 'webgl2']);
export const BENCH_BAR_COUNTS = /** @type {const} */ ([10000, 50000, 200000]);
export const BENCH_METRICS = /** @type {const} */ (['pan', 'zoomOut', 'tick']);

/** What each metric times, for reports and the docs table. */
export const BENCH_METRIC_LABELS = {
  pan: 'pan frame p95',
  zoomOut: 'full zoom-out frame p95',
  tick: 'tick p95, 10 studies',
};

/**
 * The budget in milliseconds for one cell of the table.
 *
 * @param {'canvas2d' | 'webgl2'} renderer
 * @param {number} bars
 * @param {'pan' | 'zoomOut' | 'tick'} metric
 * @param {typeof RENDER_BENCH_BUDGETS} [profile] the table to read; the active one by default
 * @returns {number}
 */
export function renderBenchBudgetMs(renderer, bars, metric, profile = RENDER_BENCH_BUDGETS) {
  const row = profile.measuredP95Ms[renderer]?.[bars];
  const measured = row?.[metric];
  if (typeof measured !== 'number' || !(measured > 0)) {
    throw new Error(`render bench: no measured p95 for ${renderer} at ${bars} bars (${metric})`);
  }
  return Math.max(Math.ceil(measured * profile.margin), profile.floorMs);
}
