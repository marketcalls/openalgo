/**
 * Indicator performance benchmark.
 *
 * Two things are measured, because they fail in different ways:
 *
 *   A. calc cost      what one full recompute of a realistic indicator set
 *                     costs at several history lengths. Catches an algorithmic
 *                     regression in a single indicator, which is otherwise
 *                     invisible: the test suite proves the numbers, never the
 *                     cost of producing them.
 *
 *   B. tick path      how many recomputes a burst of live ticks actually
 *                     triggers. This is the one that decides whether a busy
 *                     symbol is usable, and it is a property of the chart's
 *                     scheduling rather than of any indicator.
 *
 * Budgets are deliberately loose. This exists to catch a tenfold regression, not
 * to police normal variation between machines, so a failure means something
 * structural changed. The tick path is not a budget but a count, and an exact
 * one: a burst between two frames costs every indicator one pass, never more
 * (recompute has gone back to running per tick) and never fewer (the harness
 * is no longer driving the chart, and every number it prints is fiction).
 * Run with --json for a machine-readable dump.
 *
 *   npm run bench
 */

import { performance } from 'node:perf_hooks';

const JSON_OUT = process.argv.includes('--json');
const ROOT = new URL('../', import.meta.url);
const base = await import(new URL('dist/openalgo-charts.mjs', ROOT).href);
await import(new URL('dist/openalgo-charts.indicators.mjs', ROOT).href);

const byId = new Map(base.registeredIndicators().map((d) => [d.id, d]));

// ── fixtures ────────────────────────────────────────────────────────────────

// Deterministic, so a number is comparable between runs and between machines.
function bars(count) {
  let s = 20260831 >>> 0;
  const rnd = () => ((s = (Math.imul(s, 1664525) + 1013904223) >>> 0), s / 4294967296);
  const out = [];
  let price = 1000;
  for (let i = 0; i < count; i++) {
    const open = price;
    const close = 1000 + Math.sin(i / 47) * 18 + (rnd() - 0.5) * 6;
    out.push({
      time: 1735689600 + i * 900,
      open,
      high: Math.max(open, close) + rnd() * 3,
      low: Math.min(open, close) - rnd() * 3,
      close,
      volume: Math.floor(1000 + rnd() * 9000),
    });
    price = close;
  }
  return out;
}

const settingsFor = (d) => {
  const s = {};
  for (const i of d.inputs || []) s[i.key] = i.default;
  return s;
};

// A plausible terminal layout, not a synthetic worst case.
const TYPICAL = ['ema', 'bollinger', 'rsi', 'macd', 'volume'];
const HEAVY = [...TYPICAL, 'supertrend', 'adx', 'stochastic', 'vwap', 'atr'];

// ── A. calc cost ────────────────────────────────────────────────────────────

function calcCost(ids, n, iterations) {
  const data = bars(n);
  const prepared = ids.map((id) => [byId.get(id), settingsFor(byId.get(id))]);
  for (let w = 0; w < 3; w++) for (const [d, s] of prepared) d.calc(data, s, {}, undefined);
  const t0 = performance.now();
  for (let i = 0; i < iterations; i++) for (const [d, s] of prepared) d.calc(data, s, {}, undefined);
  return (performance.now() - t0) / iterations;
}

// ── B. tick path ────────────────────────────────────────────────────────────

/** A canvas context that draws nothing, so the benchmark measures compute. */
function noopCtx() {
  const fn = () => {};
  const target = {
    canvas: { width: 800, height: 600 },
    measureText: () => ({ width: 8 }),
    createLinearGradient: () => ({ addColorStop: fn }),
    getImageData: () => ({ data: new Uint8ClampedArray(4) }),
    setLineDash: fn,
  };
  return new Proxy(target, {
    get: (t, k) => (k in t ? t[k] : fn),
    set: () => true,
  });
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

/**
 * Feed `ticks` updates to the forming bar, flushing one frame at the end, and
 * report how many times each indicator actually recomputed.
 *
 * The count is the whole point. Recompute driven straight from the data update
 * gives one per tick; recompute scheduled with the frame gives one per frame no
 * matter how the ticks bunch up.
 */
function tickPath(ids, n, ticks) {
  const doc = fakeDocument();
  // A queue, not a single slot. A chart runs more than one frame loop, so a
  // one-callback fake lets the second loop overwrite the first one's callback:
  // the loop still believes a frame is pending, every later requestFrame
  // short-circuits, and nothing recomputes again. That reads as a spectacular
  // optimisation rather than as the broken harness it is. Drain by taking the
  // batch and clearing before invoking, since running a frame schedules the next.
  let nextHandle = 1;
  const pending = new Map();
  const flushFrames = () => {
    const batch = [...pending.values()];
    pending.clear();
    for (const cb of batch) cb();
    return batch.length;
  };
  const chart = new base.Chart(doc.createElement('div'), {
    document: doc,
    pixelRatio: () => 1,
    shortcuts: false,
    raf: {
      schedule: (cb) => { const h = nextHandle++; pending.set(h, cb); return h; },
      cancel: (h) => { pending.delete(h); },
    },
  });
  chart.applySize(800, 600);

  const data = bars(n);
  const series = chart.addSeries('candlestick');
  series.setData(data);

  // Passes per indicator, counted through wrappers rather than by
  // instrumenting the engine. A `calcTail` that answers is a pass; one that
  // declines falls through to `calc`, which is then the pass, so an indicator
  // that gains a tail path still counts one per recompute.
  const passes = new Map(ids.map((id) => [id, 0]));
  const pass = (id) => passes.set(id, passes.get(id) + 1);
  for (const id of ids) {
    const d = byId.get(id);
    const counted = { ...d, calc: (...a) => { pass(id); return d.calc(...a); } };
    if (typeof d.calcTail === 'function') {
      counted.calcTail = (...a) => {
        const out = d.calcTail(...a);
        if (out !== null) pass(id);
        return out;
      };
    }
    base.registerIndicator(counted);
    chart.addIndicator(id);
  }
  for (let g = 0; g < 12 && flushFrames(); g++);

  for (const id of ids) passes.set(id, 0);
  const last = data[data.length - 1];
  const t0 = performance.now();
  for (let i = 0; i < ticks; i++) {
    series.update({ ...last, close: last.close + i * 0.01 });
  }
  flushFrames(); // exactly one frame for the whole burst
  const ms = performance.now() - t0;

  chart.remove?.();
  // Restore the real descriptors so a later benchmark is not measuring wrappers.
  for (const id of ids) base.registerIndicator(byId.get(id));
  const calls = [...passes.values()].reduce((a, b) => a + b, 0);
  return { calls, ms, perIndicator: calls / ids.length, passes: Object.fromEntries(passes), ticks };
}

// ── C. a higher timeframe ───────────────────────────────────────────────────

/**
 * A study on a folded timeframe, on one-minute bars: what a full recompute
 * costs (the fold, the study on the folded bars, the check that the forming
 * bucket changes nothing shown), and what a tick inside a bucket costs, which
 * is the carry of the held value and should not grow with the history.
 */
function timeframeCost(n, timeframe) {
  const data = bars(n).map((b, i) => ({ ...b, time: 1735702200 + i * 60 }));
  const ctx = { interval: '1m', timezone: 'Asia/Kolkata', now: () => 0, barState: { isNew: false, isConfirmed: false, isRealtime: true, lastIndex: n - 1 } };
  const prepared = TIMEFRAME.map((id) => [byId.get(id), { ...settingsFor(byId.get(id)), timeframe }]);
  const stores = prepared.map(() => ({}));
  const held = prepared.map(([d, s], k) => d.calc(data, s, stores[k], ctx));
  const iterations = n > 5000 ? 30 : 100;
  let t0 = performance.now();
  for (let i = 0; i < iterations; i++) prepared.forEach(([d, s], k) => d.calc(data, s, stores[k], ctx));
  const full = (performance.now() - t0) / iterations;
  prepared.forEach(([d, s], k) => { held[k] = d.calc(data, s, stores[k], ctx); });
  const last = data[n - 1];
  t0 = performance.now();
  let carried = 0;
  for (let i = 0; i < iterations; i++) {
    data[n - 1] = { ...last, close: last.close + i * 0.01 };
    prepared.forEach(([d, s], k) => { if (d.calcTail(data, s, n - 1, held[k], stores[k], ctx) !== null) carried++; });
  }
  const tick = (performance.now() - t0) / iterations;
  data[n - 1] = last;
  return { timeframe, bars: n, fullMs: +full.toFixed(3), tickMs: +tick.toFixed(4), carried: carried / (iterations * prepared.length) };
}

const TIMEFRAME = ['ema', 'supertrend', 'rsi', 'bollinger'];

// ── run ─────────────────────────────────────────────────────────────────────

const results = { calc: [], tick: [], timeframe: [] };

for (const [label, ids] of [['typical', TYPICAL], ['heavy', HEAVY]]) {
  for (const n of [375, 1875, 7500]) {
    const ms = calcCost(ids, n, n > 5000 ? 60 : 200);
    results.calc.push({ set: label, bars: n, ms: +ms.toFixed(3) });
  }
}

for (const [label, ids] of [['typical', TYPICAL], ['heavy', HEAVY]]) {
  results.tick.push({ set: label, ...tickPath(ids, 1875, 50) });
}

for (const n of [7500, 30000]) for (const tf of ['', '15m', '1h']) results.timeframe.push(timeframeCost(n, tf));

// Budgets: a tenfold guard, not a tight bound.
const BUDGET_MS = { 'typical:7500': 12, 'heavy:7500': 60 };
// A folded recompute of the timeframe set on one-minute bars. It was 272 ms at
// 7500 bars while the fold read the zone once per bar.
const TIMEFRAME_BUDGET_MS = { 7500: 40, 30000: 160 };
// A burst of ticks between two frames costs each indicator exactly one pass.
// At the tick count, recompute is running straight off the data update; above
// one, some ticks escaped the frame; at zero, the frame never recomputed.
const TICKS_IN_BURST = 50;
const PASSES_PER_FRAME = 1;

const failures = [];
for (const r of results.calc) {
  const limit = BUDGET_MS[`${r.set}:${r.bars}`];
  if (limit && r.ms > limit) failures.push(`calc ${r.set} @ ${r.bars} bars: ${r.ms} ms exceeds ${limit} ms`);
}
for (const r of results.timeframe) {
  const limit = TIMEFRAME_BUDGET_MS[r.bars];
  if (r.timeframe !== '' && limit && r.fullMs > limit) failures.push(`timeframe ${r.timeframe} @ ${r.bars} bars: ${r.fullMs} ms exceeds ${limit} ms`);
  if (r.carried < 1) failures.push(`timeframe '${r.timeframe}' @ ${r.bars} bars: a tick inside a bucket did not take the tail`);
}
for (const r of results.tick) {
  for (const [id, n] of Object.entries(r.passes)) {
    if (n === PASSES_PER_FRAME) continue;
    failures.push(n > PASSES_PER_FRAME
      ? `tick ${r.set}: ${id} recomputed ${n} times for ${r.ticks} ticks in one frame; recompute is not coalesced to the frame`
      : `tick ${r.set}: ${id} never recomputed for ${r.ticks} ticks; the frame did not run its studies, so the harness proves nothing`);
  }
}

if (JSON_OUT) {
  console.log(JSON.stringify(results, null, 2));
} else {
  console.log('A. calc cost, one full recompute of the set\n');
  console.log('   set      |  bars |   ms');
  for (const r of results.calc) {
    console.log(`   ${r.set.padEnd(8)} | ${String(r.bars).padStart(5)} | ${r.ms.toFixed(3).padStart(6)}`);
  }
  console.log('\nB. tick path, 50 ticks arriving between two frames, 1875 bars\n');
  console.log('   set      | recomputes/indicator | total ms');
  for (const r of results.tick) {
    console.log(`   ${r.set.padEnd(8)} | ${String(r.perIndicator).padStart(20)} | ${r.ms.toFixed(2).padStart(8)}`);
  }
  console.log(
    `\n   ${results.tick.some((r) => r.perIndicator >= TICKS_IN_BURST)
      ? 'recompute runs per tick: a burst costs one full pass per tick per indicator'
      : results.tick.every((r) => r.perIndicator === PASSES_PER_FRAME)
        ? 'recompute is coalesced: a burst costs one pass per frame'
        : 'recompute is not one pass per indicator per frame'}`,
  );
  console.log(`\nC. a higher timeframe on one-minute bars: ${TIMEFRAME.join(', ')}\n`);
  console.log('   timeframe |  bars | full ms | tick ms');
  for (const r of results.timeframe) {
    console.log(`   ${(r.timeframe || 'chart').padEnd(9)} | ${String(r.bars).padStart(5)} | ${r.fullMs.toFixed(3).padStart(7)} | ${r.tickMs.toFixed(4).padStart(7)}`);
  }
}

if (failures.length) {
  console.error('\nBENCH FAILED');
  for (const f of failures) console.error('  ' + f);
  process.exitCode = 1;
}
