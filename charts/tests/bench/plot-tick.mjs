/**
 * Live tick cost with ten studies on a long history.
 *
 * A tick here is one `series.update` on the price series followed by the frame
 * it schedules: every study recomputes and writes its plots, then the chart
 * paints into a canvas that draws nothing. Two kinds are timed apart, because
 * they take different paths through the data layer:
 *
 *   forming   the last bar's close moves, its time does not
 *   append    a new bar opens one interval after the last
 *
 * Alongside the times it counts how often the shared time index was rebuilt,
 * which is the cost this measures: every plot write used to re-merge every
 * series on the chart, so ten studies paid for the whole index a dozen times
 * per tick.
 *
 * Run against a build directory, so the published build and a candidate can be
 * compared on the same machine:
 *
 *   node tests/bench/plot-tick.mjs dist-baseline
 *   node tests/bench/plot-tick.mjs dist
 *
 * Options: --bars N (default 50000), --ticks N per kind (default 60), --json.
 */

import { performance } from 'node:perf_hooks';
import { pathToFileURL } from 'node:url';
import { resolve } from 'node:path';

const args = process.argv.slice(2);
const flag = (name, fallback) => {
  const i = args.indexOf(name);
  return i >= 0 ? Number(args[i + 1]) : fallback;
};
const VALUED = new Set(['--bars', '--ticks']);
const dir = args.find((a, i) => !a.startsWith('--') && !VALUED.has(args[i - 1])) ?? 'dist';
const BARS = flag('--bars', 50000);
const TICKS = flag('--ticks', 60);
const JSON_OUT = args.includes('--json');

const root = pathToFileURL(resolve(dir) + '/').href;
const base = await import(new URL('openalgo-charts.mjs', root).href);
await import(new URL('openalgo-charts.indicators.mjs', root).href);

// The heavy set of scripts/bench-indicators.mjs: ten studies a busy terminal
// really runs, on the price pane and in panes of their own.
const STUDIES = ['ema', 'bollinger', 'rsi', 'macd', 'volume', 'supertrend', 'adx', 'stochastic', 'vwap', 'atr'];

// Deterministic, so a number is comparable between runs and between builds.
function makeBars(count) {
  let s = 20260926 >>> 0;
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

/** A canvas context that draws nothing, so the numbers are compute alone. */
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

const doc = fakeDocument();
// A queue, not one slot: the chart runs more than one frame loop (see
// scripts/bench-indicators.mjs for what a one-slot fake does to the numbers).
let nextHandle = 1;
const pending = new Map();
const flushFrames = () => {
  let frames = 0;
  for (let guard = 0; guard < 8 && pending.size > 0; guard++) {
    const batch = [...pending.values()];
    pending.clear();
    for (const cb of batch) cb();
    frames++;
  }
  return frames;
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
chart.applySize(1200, 800);

const data = makeBars(BARS);
const series = chart.addSeries('candlestick');
series.setData(data);
for (const id of STUDIES) chart.addIndicator(id);
flushFrames();

// Counted on the instance, which both builds keep under the same name: the
// data layer is private and not exported as a value, so this is the one hook
// that reads the same in the published build and in a candidate.
let rebuilds = 0;
const layer = chart._dataLayer;
if (layer && typeof layer._rebuild === 'function') {
  const rebuild = layer._rebuild;
  layer._rebuild = function counted(...a) { rebuilds++; return rebuild.apply(this, a); };
}

let last = { ...data[data.length - 1] };
const forming = () => {
  last = { ...last, close: last.close + 0.05, high: Math.max(last.high, last.close + 0.05) };
  series.update(last);
};
const append = () => {
  const close = last.close + 0.1;
  last = { time: last.time + 900, open: last.close, high: close + 0.2, low: last.close - 0.2, close, volume: 1200 };
  series.update(last);
};

function timeTick(tick) {
  const before = rebuilds;
  const t0 = performance.now();
  tick();
  flushFrames();
  return { ms: performance.now() - t0, rebuilds: rebuilds - before };
}

// Warm the JIT on both paths before anything is recorded.
for (let i = 0; i < 8; i++) { timeTick(forming); if (i % 4 === 3) timeTick(append); }

const samples = { forming: [], append: [] };
const rebuildsBy = { forming: 0, append: 0 };
for (let i = 0; i < TICKS; i++) {
  for (const kind of ['forming', 'append']) {
    const r = timeTick(kind === 'forming' ? forming : append);
    samples[kind].push(r.ms);
    rebuildsBy[kind] += r.rebuilds;
  }
}

const pct = (xs, p) => {
  const s = xs.slice().sort((a, b) => a - b);
  return s[Math.min(s.length - 1, Math.ceil((p / 100) * s.length) - 1)];
};
const summary = Object.fromEntries(Object.entries(samples).map(([kind, xs]) => [kind, {
  p50: +pct(xs, 50).toFixed(2),
  p95: +pct(xs, 95).toFixed(2),
  max: +Math.max(...xs).toFixed(2),
  rebuildsPerTick: +(rebuildsBy[kind] / xs.length).toFixed(2),
}]));

const result = { build: dir, version: base.VERSION ?? base.version, bars: BARS, studies: STUDIES.length, ticks: TICKS, ...summary };
chart.destroy();

if (JSON_OUT) {
  console.log(JSON.stringify(result, null, 2));
} else {
  console.log(`tick cost, ${STUDIES.length} studies on ${BARS} bars, ${TICKS} ticks per kind, build ${dir}\n`);
  console.log('   kind     |   p50 ms |   p95 ms |   max ms | index rebuilds per tick');
  for (const [kind, r] of Object.entries(summary)) {
    console.log(`   ${kind.padEnd(8)} | ${r.p50.toFixed(2).padStart(8)} | ${r.p95.toFixed(2).padStart(8)} | ${r.max.toFixed(2).padStart(8)} | ${String(r.rebuildsPerTick).padStart(6)}`);
  }
}
