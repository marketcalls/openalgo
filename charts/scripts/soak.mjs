/**
 * Long-session and teardown soak.
 *
 * Answers the two questions a unit suite cannot: does a chart leak when it is
 * destroyed, and does a chart left open for a trading session grow without
 * bound. Both are asked of an operator before an engine goes into a terminal,
 * and neither is answerable from `npm test`.
 *
 * Run:  node --expose-gc scripts/soak.mjs
 *
 * Needs --expose-gc. Heap numbers without a forced collection measure when the
 * collector last happened to run, which is noise, not evidence.
 *
 *   A. teardown     create and destroy N charts, then report bytes retained per
 *                   chart. A leak here compounds on every symbol switch.
 *
 *   B. live session  hold one chart open and drive a session's worth of ticks
 *                   through the forming bar. The bar count never changes, so
 *                   the heap must be flat: any slope is a leak, and separating
 *                   it from the legitimate growth of appending bars is exactly
 *                   why this drives the forming bar and nothing else.
 */

import { performance } from 'node:perf_hooks';

if (typeof global.gc !== 'function') {
  console.error('run with --expose-gc:  node --expose-gc scripts/soak.mjs');
  process.exit(2);
}

const ROOT = new URL('../', import.meta.url);
const base = await import(new URL('dist/openalgo-charts.mjs', ROOT).href);
await import(new URL('dist/openalgo-charts.indicators.mjs', ROOT).href);

const INDICATORS = ['ema', 'bollinger', 'rsi', 'macd', 'volume'];

// ── headless chart ──────────────────────────────────────────────────────────

function noopCtx() {
  const fn = () => {};
  const target = {
    canvas: { width: 800, height: 600 },
    measureText: () => ({ width: 8 }),
    createLinearGradient: () => ({ addColorStop: fn }),
    getImageData: () => ({ data: new Uint8ClampedArray(4) }),
    setLineDash: fn,
  };
  return new Proxy(target, { get: (t, k) => (k in t ? t[k] : fn), set: () => true });
}

function fakeDocument() {
  const make = (tag) => {
    const el = {
      tagName: String(tag).toUpperCase(),
      style: {},
      children: [],
      appendChild(c) { this.children.push(c); return c; },
      remove() {},
      getBoundingClientRect: () => ({ left: 0, top: 0, width: 800, height: 600 }),
      addEventListener() {}, removeEventListener() {},
      setPointerCapture() {}, releasePointerCapture() {},
      setAttribute() {}, getAttribute: () => null, hasAttribute: () => false,
    };
    if (tag === 'canvas') { el.width = 0; el.height = 0; el.getContext = () => noopCtx(); }
    return el;
  };
  return { createElement: make };
}

/** A queue, not a single slot: a chart runs more than one frame loop. */
function makeChart() {
  const doc = fakeDocument();
  let next = 1;
  const pending = new Map();
  const chart = new base.Chart(doc.createElement('div'), {
    document: doc,
    pixelRatio: () => 1,
    shortcuts: false,
    raf: {
      schedule: (cb) => { const h = next++; pending.set(h, cb); return h; },
      cancel: (h) => { pending.delete(h); },
    },
  });
  chart.applySize(800, 600);
  const flush = () => {
    const batch = [...pending.values()];
    pending.clear();
    for (const cb of batch) cb();
    return batch.length;
  };
  return { chart, flush };
}

function bars(n) {
  let s = 20260831 >>> 0;
  const rnd = () => ((s = (Math.imul(s, 1664525) + 1013904223) >>> 0), s / 4294967296);
  const out = [];
  for (let i = 0; i < n; i++) {
    const close = 1000 + Math.sin(i / 47) * 18 + (rnd() - 0.5) * 6;
    out.push({
      time: 1735689600 + i * 60,
      open: close, high: close + 1, low: close - 1, close,
      volume: Math.floor(1000 + rnd() * 9000),
    });
  }
  return out;
}

/**
 * Heap after a settled collection.
 *
 * The yield is not decoration and removing it invalidates every number below.
 * Objects allocated inside a synchronous loop stay reachable until the stack
 * unwinds and the event loop turns, so collecting without yielding reclaims
 * nothing: an earlier version of this script measured a flat 65 KB "leak" per
 * chart across 2000 cycles, and a WeakRef check proved all 400 charts died the
 * moment a timer fired. Yield first, then collect, then read.
 */
async function heap() {
  await new Promise((r) => setTimeout(r, 20));
  for (let i = 0; i < 6; i++) global.gc();
  await new Promise((r) => setTimeout(r, 20));
  for (let i = 0; i < 6; i++) global.gc();
  return process.memoryUsage().heapUsed;
}

const mb = (b) => (b / 1024 / 1024).toFixed(2);

// ── A. teardown ─────────────────────────────────────────────────────────────

async function teardownSoak(cycles) {
  const data = bars(1000);
  // Warm up, so the measurement excludes first-run allocation of shared state
  // (registries, prototype shapes, compiled code) that is not per-chart.
  for (let i = 0; i < 20; i++) {
    const { chart, flush } = makeChart();
    chart.addSeries('candlestick').setData(data);
    for (const id of INDICATORS) chart.addIndicator(id);
    flush();
    chart.destroy();
  }

  const before = await heap();
  const t0 = performance.now();
  for (let i = 0; i < cycles; i++) {
    const { chart, flush } = makeChart();
    chart.addSeries('candlestick').setData(data);
    for (const id of INDICATORS) chart.addIndicator(id);
    flush();
    chart.destroy();
  }
  const ms = performance.now() - t0;
  const after = await heap();

  return { before, after, retained: after - before, perChart: (after - before) / cycles, cycles, ms };
}

// ── B. live session ─────────────────────────────────────────────────────────

/**
 * Drive `ticks` updates through the forming bar, flushing a frame every
 * `perFrame` ticks, sampling the heap as it goes. The bar count is constant
 * throughout, so a rising trend is retention and not data.
 */
async function sessionSoak(ticks, perFrame) {
  const { chart, flush } = makeChart();
  const data = bars(1875);
  const series = chart.addSeries('candlestick');
  series.setData(data);
  for (const id of INDICATORS) chart.addIndicator(id);
  while (flush());

  const last = data[data.length - 1];
  const samples = [];
  const t0 = performance.now();

  for (let i = 1; i <= ticks; i++) {
    series.update({ ...last, close: last.close + Math.sin(i / 500) * 5 });
    if (i % perFrame === 0) flush();
    if (i % Math.floor(ticks / 12) === 0) samples.push({ tick: i, heap: await heap() });
  }
  const ms = performance.now() - t0;
  const barsAfter = chart.series?.().length;
  chart.destroy();

  // Least squares slope over the samples, in bytes per tick. Skip the first
  // sample: the earliest one still carries warm-up allocation.
  const pts = samples.slice(1);
  const n = pts.length;
  const mx = pts.reduce((a, p) => a + p.tick, 0) / n;
  const my = pts.reduce((a, p) => a + p.heap, 0) / n;
  let num = 0, den = 0;
  for (const p of pts) { num += (p.tick - mx) * (p.heap - my); den += (p.tick - mx) ** 2; }
  const slope = den === 0 ? 0 : num / den;

  return { samples, slope, ticks, ms, barsAfter };
}

// ── run ─────────────────────────────────────────────────────────────────────

const CYCLES = Number(process.env.SOAK_CYCLES || 300);
// 6.25 hours of a session at 4 ticks a second is ~90k. Default lower so the
// script stays runnable in CI; raise with SOAK_TICKS for a real soak.
const TICKS = Number(process.env.SOAK_TICKS || 60000);

console.log('A. teardown: create and destroy a chart with 1000 bars and 5 indicators\n');
const a = await teardownSoak(CYCLES);
console.log(`   cycles            ${a.cycles}`);
console.log(`   heap before       ${mb(a.before)} MB`);
console.log(`   heap after        ${mb(a.after)} MB`);
console.log(`   retained total    ${mb(a.retained)} MB`);
console.log(`   retained/chart    ${(a.perChart / 1024).toFixed(2)} KB`);
console.log(`   wall              ${a.ms.toFixed(0)} ms  (${(a.ms / a.cycles).toFixed(2)} ms per create+destroy)`);

console.log('\nB. live session: one chart, ticks through the forming bar, bar count constant\n');
const b = await sessionSoak(TICKS, 4);
console.log(`   ticks             ${b.ticks}`);
console.log(`   wall              ${(b.ms / 1000).toFixed(1)} s`);
console.log('   heap samples:');
for (const s of b.samples) console.log(`     tick ${String(s.tick).padStart(7)}  ${mb(s.heap).padStart(8)} MB`);
console.log(`\n   growth            ${b.slope >= 0 ? '+' : ''}${(b.slope).toFixed(2)} bytes/tick`);
console.log(`   extrapolated      ${((b.slope * 90000) / 1024 / 1024).toFixed(2)} MB over a 90k-tick session`);

// A leak shows as sustained positive slope. The threshold is deliberately loose:
// this is here to catch retention, not to police allocator noise.
const LEAK_BYTES_PER_TICK = 20;
const RETAIN_KB_PER_CHART = 40;

const problems = [];
if (b.slope > LEAK_BYTES_PER_TICK) {
  problems.push(`session heap grows ${b.slope.toFixed(1)} bytes/tick with a constant bar count`);
}
if (a.perChart / 1024 > RETAIN_KB_PER_CHART) {
  problems.push(`each destroyed chart retains ${(a.perChart / 1024).toFixed(1)} KB`);
}

console.log('');
if (problems.length) {
  console.error('SOAK FAILED');
  for (const p of problems) console.error('  ' + p);
  process.exitCode = 1;
} else {
  console.log('soak clean: no retention on destroy, no growth over the session');
}
