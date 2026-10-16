/**
 * The built-ins' `calcTail` against their own full `calc`.
 *
 * A live chart shows the spliced tail; a reload shows the full calculation. The
 * two have to agree to the last bit, NaN and signed zero included, or the same
 * chart reads differently before and after a refresh. So every property here
 * compares with Object.is, bar by bar, after every tick and every appended bar,
 * over random histories with session breaks, weekends, outages, missing prices,
 * missing or unusable volume, ties, zeros and overflowing values.
 *
 * Ticks are spliced with the runtime's own `spliceTail`, as a live chart
 * splices them.
 */
import { describe, expect, it } from 'vitest';
import '../src/indicators/index';
import { getIndicator, indicatorDefaults, registerIndicator } from '../src/model/indicator-registry';
import { Chart } from '../src/core/chart';
import { fakeDocument } from './helpers/fake-dom';
import type {
  IndicatorCalcContext, IndicatorDescriptor, IndicatorSettings, IndicatorStore, IndicatorValues,
} from '../src/model/indicator-registry';
import type { Bar } from '../src/model/bar';
import { spliceTail } from '../src/model/indicator-tail-splice';
import { sma as smaKernel, rma, smaSeededEma } from '../src/indicators/calc';
import { rsi } from '../src/indicators/rsi';
import { atr, trueRange } from '../src/indicators/atr';
import { supertrend } from '../src/indicators/supertrend';
import {
  seeded, smooth, rsiState, rsiStep, wilder, atrStep, trueRangeAt, supertrendState, supertrendStep, meanAt,
} from '../src/indicators/steppers';

// ── random streams ────────────────────────────────────────────────────────────

function prng(seed: number): () => number {
  let s = seed >>> 0;
  return () => {
    s = (s + 0x6d2b79f5) >>> 0;
    let t = s;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

type Clock = 'nse' | 'nyse' | 'daily' | 'continuous' | 'irregular' | 'opening' | 'hourly' | 'threshold' | 'spans';

interface Flavour {
  clock: Clock;
  /** Chance a bar carries a missing price, one field or all four. */
  holes: number;
  /** Chance of an overflowing or near-overflowing price. */
  extremes: number;
  /** Chance of an exact zero or negative zero price. */
  zeros: number;
  /**
   * A tick size. Real prices sit on a grid, which is what makes ties common:
   * a close on a band, a flat window, an unchanged close. A branch taken only
   * on a tie is a branch random floats never reach.
   */
  grid?: number;
}

const DAY = 86400;
const weekday = (t: number): boolean => { const d = new Date(t * 1000).getUTCDay(); return d !== 0 && d !== 6; };

/** Successive bar times for a clock, starting on a Monday. */
function timeline(clock: Clock, rnd: () => number): () => number {
  let day = Date.UTC(2024, 2, 4) / 1000; // a Monday, a week before the US clock change
  let t = NaN;
  const session = (openUtc: number, step: number, bars: number) => (): number => {
    const open = day + openUtc;
    if (Number.isNaN(t)) { t = open; return t; }
    if (t + step < open + bars * step) { t += step; return t; }
    do { day += DAY; } while (!weekday(day) || rnd() < 0.04);
    t = day + openUtc;
    return t;
  };
  switch (clock) {
    case 'nse': return session(3 * 3600 + 45 * 60, 1800, 13);
    case 'nyse': return session(14 * 3600 + 30 * 60, 3600, 7);
    case 'opening': return session(3 * 3600 + 45 * 60, 300, 75);
    case 'daily': return () => {
      if (Number.isNaN(t)) { t = day + 13 * 3600; return t; }
      do { t += DAY; } while (!weekday(t) || rnd() < 0.03);
      return t;
    };
    case 'continuous': return () => {
      t = Number.isNaN(t) ? day : t + 60 * (rnd() < 0.02 ? 5 + Math.floor(rnd() * 300) : 1);
      return t;
    };
    // Gaps of hours, spread so the median gap keeps moving while a history
    // is short. The session threshold is four times that median once it
    // passes an hour, so an appended bar can recast every earlier flag.
    case 'hourly': return () => {
      const hours = [1, 1, 2, 2, 3, 3, 4, 6, 9, 14, 20, 30][Math.floor(rnd() * 12)];
      t = Number.isNaN(t) ? day : t + hours * 3600;
      return t;
    };
    // Minute bars whose breaks land exactly on the session threshold (four
    // hours, since four minute gaps are less), a minute short of it, or well
    // past it: the one gap length where "at least" and "more than" part.
    case 'threshold': return () => {
      const r = rnd();
      t = Number.isNaN(t) ? day : t + (r < 0.03 ? 4 * 3600 : r < 0.05 ? 4 * 3600 - 60 : r < 0.06 ? 3 * DAY : 60);
      return t;
    };
    // Minute sessions whose opens sit 24, 36 or 60 hours apart, some a minute
    // past: a span of at most 36 hours counts as a daily cadence, and only an
    // open exactly on it tells "at most" from "under". Opening at 18:00 UTC
    // or 06:00 UTC, a session can run across midnight in IST, which is where
    // reading sessions and falling back to the calendar part ways.
    case 'spans': {
      let open = NaN;
      let left = 0;
      return () => {
        if (Number.isNaN(t)) { open = day + 18 * 3600; t = open; left = 20 + Math.floor(rnd() * 40); return t; }
        if (left-- > 0) { t += 60; return t; }
        open += [24, 36, 36, 60][Math.floor(rnd() * 4)] * 3600 + (rnd() < 0.2 ? 60 : 0);
        t = open;
        left = 20 + Math.floor(rnd() * 40);
        return t;
      };
    }
    case 'irregular': return () => {
      const r = rnd();
      const gap = r < 0.55 ? 60 : r < 0.7 ? 120 : r < 0.8 ? 300 : r < 0.9 ? 3600 * (1 + Math.floor(rnd() * 20)) : DAY * (1 + Math.floor(rnd() * 3));
      t = Number.isNaN(t) ? day : t + gap;
      return t;
    };
  }
}

function price(rnd: () => number, f: Flavour, base: number): number {
  const r = rnd();
  if (r < f.extremes) return [1e308, 1.7e308, -1e308, 1e154, 5e-324, Infinity, -Infinity][Math.floor(rnd() * 7)];
  if (r < f.extremes + f.zeros) return rnd() < 0.5 ? 0 : -0;
  return base;
}

/** A bar at `time`, drifting from `prev`; `forming` keeps the open and extends the range. */
function makeBar(rnd: () => number, f: Flavour, time: number, prev: Bar | undefined, forming: boolean): Bar {
  const anchor = prev !== undefined && Number.isFinite(prev.close) && Math.abs(prev.close) < 1e6 && prev.close > 1 ? prev.close : 100;
  const g = f.grid;
  const steps = (k: number): number => (g === undefined ? 0 : g * Math.floor(rnd() * k));
  const tie = rnd() < 0.08;
  const moved = g === undefined ? anchor * (1 + (rnd() - 0.5) * 0.03) : anchor + steps(5) - 2 * g;
  const close = price(rnd, f, tie ? anchor : moved);
  const open = forming && prev !== undefined ? prev.open : anchor;
  let high = g === undefined ? Math.max(open, close) * (1 + rnd() * 0.01) : Math.max(open, close) + steps(3);
  let low = g === undefined ? Math.min(open, close) * (1 - rnd() * 0.01) : Math.min(open, close) - steps(3);
  if (forming && prev !== undefined && rnd() < 0.7) {
    high = Math.max(high, prev.high);
    low = Math.min(low, prev.low);
  }
  const bar: Bar = { time, open, high, low, close };
  const v = rnd();
  if (v < 0.08) { /* no volume at all */ } else if (v < 0.11) bar.volume = NaN;
  else if (v < 0.15) bar.volume = 0;
  // A feed can send what no exchange prints; VWAP's totals meet it all the same.
  else if (v < 0.17) bar.volume = [Infinity, -5, 0.5, 1e300][Math.floor(rnd() * 4)];
  else bar.volume = Math.floor(rnd() * 5000);
  const h = rnd();
  if (h < f.holes) {
    const fields = ['open', 'high', 'low', 'close'] as const;
    if (rnd() < 0.2) for (const k of fields) bar[k] = NaN;
    else bar[fields[Math.floor(rnd() * 4)]] = NaN;
  }
  return bar;
}

// ── the comparison ─────────────────────────────────────────────────────────────

/** The first difference between two results, or null when they agree to the bit. */
function firstDifference(actual: IndicatorValues, expected: IndicatorValues): string | null {
  const a = Object.keys(actual).sort().join();
  const e = Object.keys(expected).sort().join();
  if (a !== e) return `keys ${a} against ${e}`;
  for (const key of Object.keys(expected)) {
    const x = actual[key];
    const y = expected[key];
    if (x.length !== y.length) return `${key} length ${x.length} against ${y.length}`;
    for (let i = 0; i < y.length; i++) if (!Object.is(x[i] ?? null, y[i] ?? null)) return `${key}[${i}] ${String(x[i])} against ${String(y[i])}`;
  }
  return null;
}

interface Run { events: number; tails: number; failure: string | null }

/**
 * Drive a descriptor the way the runtime does: a full calc, then after each
 * tick or appended bar a tail from the previously-last bar, falling back to a
 * full calc on null. After every step the held result must equal a fresh full
 * calc on a store of its own.
 */
function drive(
  d: IndicatorDescriptor, settings: IndicatorSettings, seed: number, f: Flavour,
  opts: { initial: number; events: number; study?: boolean },
): Run {
  const rnd = prng(seed);
  const next = timeline(f.clock, rnd);
  const bars: Bar[] = [];
  for (let i = 0; i < opts.initial; i++) bars.push(makeBar(rnd, f, next(), bars[i - 1], false));
  // A study output to read from: an SMA of the closes, the kind of column a
  // dependent average is handed by the runtime.
  const ctx = (): IndicatorCalcContext | undefined => opts.study
    ? { resolveSource: () => smaKernel(bars.map((b) => b.close), 3).map((v) => (Number.isFinite(v) ? v : null)) } as never
    : undefined;
  const store: IndicatorStore = {};
  let held = d.calc(bars, settings, store, ctx());
  let tails = 0;
  for (let e = 0; e < opts.events; e++) {
    const n0 = bars.length;
    if (rnd() < 0.35) bars.push(makeBar(rnd, f, next(), bars[n0 - 1], false));
    else bars[n0 - 1] = makeBar(rnd, f, bars[n0 - 1].time, bars[n0 - 1], true);
    const from = n0 - 1;
    const tail = d.calcTail!(bars, settings, from, held, store, ctx());
    const spliced = tail === null ? null : spliceTail(held, tail, from, bars.length);
    if (tail !== null && spliced === null) return { events: e + 1, tails, failure: `event ${e}: the tail did not splice` };
    if (spliced !== null) tails++;
    const expected = d.calc(bars, settings, {}, ctx());
    held = spliced ?? d.calc(bars, settings, store, ctx());
    const diff = firstDifference(held, expected);
    if (diff !== null) return { events: e + 1, tails, failure: `event ${e} (${tail === null ? 'full' : 'tail'}, n=${bars.length}): ${diff}` };
  }
  return { events: opts.events, tails, failure: null };
}

// ── the parameter sets ───────────────────────────────────────────────────────

const FLAVOURS: Flavour[] = [
  { clock: 'nse', holes: 0.04, extremes: 0, zeros: 0 },
  { clock: 'nyse', holes: 0.02, extremes: 0.004, zeros: 0.01 },
  { clock: 'daily', holes: 0.05, extremes: 0, zeros: 0.02 },
  { clock: 'continuous', holes: 0.03, extremes: 0.003, zeros: 0 },
  { clock: 'irregular', holes: 0.06, extremes: 0.002, zeros: 0.01 },
  { clock: 'opening', holes: 0.01, extremes: 0, zeros: 0 },
  { clock: 'nse', holes: 0.02, extremes: 0, zeros: 0, grid: 0.5 },
  { clock: 'continuous', holes: 0.01, extremes: 0, zeros: 0.01, grid: 1 },
  { clock: 'hourly', holes: 0.02, extremes: 0, zeros: 0 },
  { clock: 'threshold', holes: 0.02, extremes: 0, zeros: 0 },
  { clock: 'spans', holes: 0.02, extremes: 0, zeros: 0 },
];

/** Settings for each built-in: defaults first, then the edges of its inputs. */
const CASES: Record<string, IndicatorSettings[]> = {
  // A fractional length reads as the nearest whole one, in calc and tail alike.
  sma: [{}, { length: 1 }, { length: 20, source: 'hl2' }, { length: 4, source: 'volume' }, { length: 2.5 }],
  wma: [{}, { length: 1 }, { length: 12, source: 'ohlc4' }],
  ema: [{}, { length: 1 }, { length: 21, source: 'hlc3' }, { length: 3, source: 'volume' }, { length: 1.5 }],
  rsi: [{}, { length: 1 }, { length: 2, source: 'open' }, { length: 30, overbought: 80, oversold: 20 }, { length: 7.5 }],
  atr: [{}, { period: 1 }, { period: 3 }],
  adx: [{}, { period: 5, adxPeriod: 3 }, { period: 1, adxPeriod: 1 }],
  macd: [{}, { fastPeriod: 3, slowPeriod: 7, signalPeriod: 2 }, { fastPeriod: 1, slowPeriod: 1, signalPeriod: 1, source: 'ohlc4' }],
  bollinger: [{}, { length: 5, stdDev: 1.5, source: 'hl2' }, { length: 2 }],
  vwap: [
    {}, { anchor: 'continuous' }, { anchor: 'week', calcMode: 'percent' }, { anchor: 'month', showBand2: true, showBand3: true },
    { anchor: 'quarter', source: 'close' }, { anchor: 'year', showBand1: false },
    { timezone: 'America/New_York' }, { anchor: 'week', timezone: 'America/New_York', showBand2: true },
    { anchor: 'month', timezone: 'Europe/London' },
  ],
  supertrend: [{}, { period: 3, multiplier: 1.5 }, { period: 1, multiplier: 0.5 }, { period: 2, multiplier: 0 }],
  stochastic: [{}, { kPeriod: 5, kSmoothing: 3, dPeriod: 3 }, { kPeriod: 1, kSmoothing: 1, dPeriod: 1 }],
  obv: [
    {}, { maType: 'SMA', maLength: 3 }, { maType: 'SMA + Bollinger Bands', maLength: 5, bbMult: 1.5 },
    { maType: 'EMA', maLength: 4 }, { maType: 'SMMA (RMA)', maLength: 1 }, { maType: 'WMA', maLength: 6 }, { maType: 'VWMA', maLength: 3 },
  ],
  cci: [
    {}, { maType: 'None', period: 5 }, { maType: 'EMA', maLength: 4, period: 7 }, { maType: 'SMMA (RMA)', maLength: 3 },
    { maType: 'WMA', maLength: 5, period: 3 }, { maType: 'VWMA', maLength: 4 }, { maType: 'SMA + Bollinger Bands', maLength: 6, period: 1 },
  ],
  'keltner-channel': [
    {}, { exp: false, length: 5 }, { bandsStyle: 'True Range', length: 3, mult: 1.5 }, { bandsStyle: 'Range', length: 4 },
    { atrlength: 1, length: 1, source: 'hl2' },
  ],
  donchian: [{}, { length: 5, offset: 3 }, { length: 1 }],
  'parabolic-sar': [{}, { start: 0.1, increment: 0.05, maximum: 0.5 }, { start: 0.2, increment: 0.2, maximum: 0.2 }],
  zlema: [{}, { length: 1 }, { length: 4, source: 'hl2' }, { length: 9, source: 'volume' }],
  vidya: [{}, { length: 1, cmoLength: 1 }, { length: 20, cmoLength: 5, source: 'ohlc4' }],
  'elder-ray': [{}, { length: 1 }, { length: 4 }],
  'schaff-trend-cycle': [{}, { fastLength: 3, slowLength: 7, cycleLength: 3, factor: 0.3 }, { fastLength: 1, slowLength: 2, cycleLength: 1, factor: 1 }],
  'volatility-squeeze': [{}, { length: 2, bbMult: 1, kcMult: 1 }, { length: 7, kcMult: 3 }],
  zigzag: [{}, { deviation: 0.5 }, { deviation: 1.5 }, { deviation: 30 }],
  'high-low-52-week': [{}, { timezone: 'America/New_York' }, { timezone: 'Europe/London' }],
};

/**
 * Settings a tail deliberately declines: the full calc must still be what the
 * runtime shows. A length past the safe integers is one the stepping kernels
 * cannot take, so the tail leaves it to the full calc.
 */
const DECLINED: Record<string, IndicatorSettings[]> = {
  sma: [{ length: 2 ** 53 }],
  ema: [{ length: 2 ** 53 }],
  vwap: [{ offset: 2 }, { offset: -1 }],
  donchian: [{ offset: -2 }],
  rsi: [{ length: 2 ** 53 }],
};

const settingsFor = (d: IndicatorDescriptor, patch: IndicatorSettings): IndicatorSettings => ({ ...indicatorDefaults(d), ...patch });

describe('calcTail equals a full calc, bar by bar', () => {
  for (const [id, cases] of Object.entries(CASES)) {
    it(`${id}: every tick and every appended bar`, () => {
      const d = getIndicator(id);
      expect(d.calcTail).toBeTypeOf('function');
      let events = 0;
      let tails = 0;
      cases.forEach((patch, c) => {
        FLAVOURS.forEach((f, k) => {
          for (const initial of [1, 3, 40, 160, 400]) {
            const run = drive(d, settingsFor(d, patch), 1000 * c + 100 * k + initial, f, { initial, events: 100 });
            expect(run.failure, `${id} ${JSON.stringify(patch)} ${f.clock} from ${initial} bars`).toBeNull();
            events += run.events;
            tails += run.tails;
          }
        });
      });
      // The point of a tail is to be taken. Warmups and a reading of the
      // sessions that moves may decline, but most steps must splice.
      expect(tails / events).toBeGreaterThan(0.75);
    }, 60_000);
  }

  for (const id of ['sma', 'wma', 'ema']) {
    it(`${id} over a study output resumes as the full calc does`, () => {
      const d = getIndicator(id);
      let events = 0;
      let tails = 0;
      for (const length of [1, 3, 9]) {
        FLAVOURS.forEach((f, k) => {
          const settings = settingsFor(d, { length, source: { kind: 'indicator', instanceId: 'upstream', plotKey: 'ma' } });
          const run = drive(d, settings, 77 * length + k, f, { initial: 30, events: 60, study: true });
          expect(run.failure, `${id} length ${length} ${f.clock}`).toBeNull();
          events += run.events;
          tails += run.tails;
        });
      }
      expect(tails / events).toBeGreaterThan(0.75);
    }, 60_000);
  }

  it('settings a tail declines still leave the full result', () => {
    for (const [id, cases] of Object.entries(DECLINED)) {
      const d = getIndicator(id);
      for (const patch of cases) {
        FLAVOURS.forEach((f, k) => {
          const run = drive(d, settingsFor(d, patch), 31 * k + 7, f, { initial: 50, events: 30 });
          expect(run.failure, `${id} ${JSON.stringify(patch)} ${f.clock}`).toBeNull();
          expect(run.tails, `${id} ${JSON.stringify(patch)} ${f.clock}`).toBe(0);
        });
      }
    }
  }, 60_000);
});

describe('VWAP restarts across sessions and anchors', () => {
  // A history that starts inside one session has no overnight gap to read
  // sessions from, so its first break switches the whole reading. Appends then
  // cross sessions, weeks, months and a quarter end.
  const anchors = ['session', 'week', 'month', 'quarter', 'year', 'continuous'];
  for (const anchor of anchors) {
    it(`${anchor}: ticks and appends through period boundaries`, () => {
      const d = getIndicator('vwap');
      let events = 0;
      let tails = 0;
      for (const timezone of ['Asia/Kolkata', 'America/New_York']) {
        for (const clock of ['nse', 'nyse', 'daily', 'opening', 'hourly', 'threshold', 'spans'] as const) {
          for (const initial of [1, 2, 12, 90]) {
            const f: Flavour = { clock, holes: 0.03, extremes: 0, zeros: 0 };
            const run = drive(d, settingsFor(d, { anchor, timezone, showBand2: true }), initial * 13 + clock.length, f, { initial, events: 150 });
            expect(run.failure, `${anchor} ${timezone} ${clock} from ${initial}`).toBeNull();
            events += run.events;
            tails += run.tails;
          }
        }
      }
      expect(tails / events).toBeGreaterThan(0.9);
    }, 60_000);
  }
});

describe('through the chart', () => {
  it('a live chart holds what a reload would compute, and takes the tail to get there', () => {
    const doc = fakeDocument();
    const chart = new Chart(doc.createElement('div'), {
      document: doc, pixelRatio: () => 1, shortcuts: false, raf: { schedule: () => 1, cancel: () => {} },
    });
    chart.applySize(800, 600);
    const rnd = prng(20260926);
    const f: Flavour = { clock: 'nse', holes: 0, extremes: 0, zeros: 0, grid: 0.05 };
    const next = timeline(f.clock, rnd);
    const data: Bar[] = [];
    for (let i = 0; i < 300; i++) data.push(makeBar(rnd, f, next(), data[i - 1], false));
    const price = chart.addSeries('candlestick');
    price.setData(data);
    const studies = Object.keys(CASES).map((id) => {
      const d = getIndicator(id);
      const counts = { tails: 0, fulls: 0 };
      // Counted under an id of its own, so the registry's built-in stays as it is.
      const probe: IndicatorDescriptor = {
        ...d, id: `tail-probe-${id}`,
        calc: (...args) => { counts.fulls++; return d.calc(...args); },
        calcTail: (...args) => { const out = d.calcTail!(...args); if (out !== null) counts.tails++; return out; },
      };
      registerIndicator(probe);
      const settings = settingsFor(d, CASES[id][1] ?? {});
      return { d, counts, settings, api: chart.addIndicator(probe.id, settings) };
    });
    for (let e = 0; e < 120; e++) {
      const last = data[data.length - 1];
      const bar = rnd() < 0.3 ? makeBar(rnd, f, next(), last, false) : makeBar(rnd, f, last.time, last, true);
      if (bar.time === last.time) data[data.length - 1] = bar; else data.push(bar);
      price.update(bar);
      for (const st of studies) {
        const diff = firstDifference(st.api.values(), st.d.calc(data, st.settings, {}));
        expect(diff, `${st.d.id} after event ${e}`).toBeNull();
      }
    }
    for (const st of studies) expect(st.counts.tails, st.d.id).toBeGreaterThan(110);
    chart.destroy();
  });
});

describe('a built-in over a built-in', () => {
  // A producer that takes its tail keeps its output's history revision, so a
  // dependent built-in is offered its own tail as well, reading the producer's
  // column through the resolver. Both must still read what a reload computes.
  for (const [up, key, down] of [['sma', 'ma', 'ema'], ['rsi', 'rsi', 'sma'], ['macd', 'macd', 'wma']] as const) {
    it(`${down} over ${up}.${key} on a live chart`, () => {
      const doc = fakeDocument();
      const chart = new Chart(doc.createElement('div'), {
        document: doc, timezone: 'Etc/UTC', pixelRatio: () => 1, shortcuts: false, raf: { schedule: () => 1, cancel: () => {} },
      });
      chart.applySize(800, 600);
      const rnd = prng(up.length * 101 + down.length);
      const f: Flavour = { clock: 'continuous', holes: 0.04, extremes: 0, zeros: 0, grid: 0.25 };
      const next = timeline(f.clock, rnd);
      const data: Bar[] = [];
      for (let i = 0; i < 200; i++) data.push(makeBar(rnd, f, next(), data[i - 1], false));
      const price = chart.addSeries('candlestick');
      price.setData(data);
      const consumerDescriptor = getIndicator(down);
      let fulls = 0;
      registerIndicator({
        ...consumerDescriptor, id: `tail-chain-${down}`,
        calc: (...args) => { fulls++; return consumerDescriptor.calc(...args); },
        calcTail: consumerDescriptor.calcTail,
      });
      const producer = chart.addIndicator(up, { length: 5 });
      const consumer = chart.addIndicator(`tail-chain-${down}`, { length: 4, source: { kind: 'indicator', instanceId: producer.id, plotKey: key } });
      const settled = fulls;
      for (let e = 0; e < 80; e++) {
        const last = data[data.length - 1];
        const bar = rnd() < 0.3 ? makeBar(rnd, f, next(), last, false) : makeBar(rnd, f, last.time, last, true);
        if (bar.time === last.time) data[data.length - 1] = bar; else data.push(bar);
        price.update(bar);
        const column = getIndicator(up).calc(data, producer.settings(), {})[key];
        expect(firstDifference(producer.values(), getIndicator(up).calc(data, producer.settings(), {})), `${up} after ${e}`).toBeNull();
        const expected = consumerDescriptor.calc(data, consumer.settings(), {}, { resolveSource: () => column } as never);
        expect(firstDifference(consumer.values(), expected), `${down} after ${e}`).toBeNull();
      }
      // The consumer ran its full calc on only a handful of the 80 events.
      expect(fulls - settled).toBeLessThan(8);
      chart.destroy();
    });
  }
});

describe('what a tail resumes from', () => {
  const bars = (n: number): Bar[] => Array.from({ length: n }, (_, i) => ({
    time: 1_700_000_000 + i * 60, open: 100 + i, high: 101 + i, low: 99 + i, close: 100 + Math.sin(i) * 3, volume: 10 + i,
  }));

  it('declines on a store its own calc never ran on', () => {
    const d = getIndicator('ema');
    const data = bars(50);
    const s = settingsFor(d, {});
    const held = d.calc(data, s, {});
    expect(d.calcTail!(data, s, 49, held, {})).toBeNull();
    // A descriptor that copies the built-in's tail and brings its own calc
    // must not have the tail splice onto someone else's numbers.
    const store: IndicatorStore = {};
    const doubled: IndicatorDescriptor = { ...d, calc: (b) => ({ ma: b.map((x) => x.close * 2) }), calcTail: d.calcTail };
    const own = doubled.calc(data, s, store);
    expect(doubled.calcTail!(data, s, 49, own, store)).toBeNull();
  });

  it('declines when the held result is not what it computed, and stops trying', () => {
    const d = getIndicator('rsi');
    const data = bars(60);
    const s = settingsFor(d, {});
    const store: IndicatorStore = {};
    const held = d.calc(data, s, store);
    const scaled: IndicatorValues = { ...held, rsi: held.rsi.map((v) => (v === null ? null : v * 2)) };
    for (let i = 0; i < 3; i++) expect(d.calcTail!(data, s, 59, scaled, store)).toBeNull();
    // Three in a row and the instance is not offered the tail again, even
    // with a correct held result: its full calc is always right.
    expect(d.calcTail!(data, s, 59, held, store)).toBeNull();
  });

  it('resumes a matching held result, and a wrapper that calls the built-in keeps a copied tail', () => {
    const d = getIndicator('macd');
    const data = bars(80);
    const s = settingsFor(d, {});
    const store: IndicatorStore = {};
    const wrapped: IndicatorDescriptor = { ...d, calc: (...args) => d.calc(...args), calcTail: d.calcTail };
    const held = wrapped.calc(data, s, store);
    data[79] = { ...data[79], close: data[79].close + 1 };
    const tail = wrapped.calcTail!(data, s, 79, held, store);
    expect(tail).not.toBeNull();
    const full = d.calc(data, s, {});
    expect(tail!.macd[0]).toBe(full.macd[79]);
    expect(tail!.histogram[0]).toBe(full.histogram[79]);
  });

  it('declines a copied tail when the held result has a column the tail does not write', () => {
    const d = getIndicator('sma');
    const data = bars(40);
    const s = settingsFor(d, { length: 3 });
    const store: IndicatorStore = {};
    const extended: IndicatorDescriptor = {
      ...d, calc: (...args) => ({ ...d.calc(...args), extra: args[0].map((b) => b.close) }), calcTail: d.calcTail,
    };
    const held = extended.calc(data, s, store);
    // Its `ma` is the built-in's to the bit, so only the extra column tells.
    expect(extended.calcTail!(data, s, 39, held, store)).toBeNull();
    // Its calc writes that column every time, so the tail is not tried again
    // for this instance, while another instance of the built-in keeps its own.
    const { extra: _extra, ...plain } = extended.calc(data, s, store);
    expect(extended.calcTail!(data, s, 39, plain, store)).toBeNull();
    const own: IndicatorStore = {};
    expect(d.calcTail!(data, s, 39, d.calc(data, s, own), own)).not.toBeNull();
  });

  it('rebuilds after a full calc rather than resuming a stale checkpoint', () => {
    const d = getIndicator('supertrend');
    const data = bars(80);
    const s = settingsFor(d, { period: 5 });
    const store: IndicatorStore = {};
    let held = d.calc(data, s, store);
    data[79] = { ...data[79], close: 90 };
    held = spliceTail(held, d.calcTail!(data, s, 79, held, store)!, 79, 80)!;
    // A history correction the runtime recomputes in full: every close moves.
    for (let i = 0; i < 80; i++) data[i] = { ...data[i], close: data[i].close + 7, high: data[i].high + 7 };
    held = d.calc(data, s, store);
    data[79] = { ...data[79], close: 95 };
    const tail = d.calcTail!(data, s, 79, held, store);
    expect(firstDifference(spliceTail(held, tail!, 79, 80)!, d.calc(data, s, {}))).toBeNull();
  });
});

/** A live chart of thirty one-minute bars, and a tick that moves the last close. */
const mount = () => {
  const doc = fakeDocument();
  const chart = new Chart(doc.createElement('div'), {
    document: doc, timezone: 'Etc/UTC', pixelRatio: () => 1, shortcuts: false, raf: { schedule: () => 1, cancel: () => {} },
  });
  chart.applySize(800, 600);
  const data: Bar[] = Array.from({ length: 30 }, (_, i) => ({
    time: i * 60, open: 10 + i, high: 11 + i, low: 9 + i, close: 10 + i, volume: 5,
  }));
  const series = chart.addSeries('candlestick');
  series.setData(data);
  const tick = (close: number): Bar[] => {
    data[29] = { ...data[29], high: Math.max(data[29].high, close), close };
    series.update(data[29]);
    return data;
  };
  return { chart, tick };
};

describe('a descriptor that spreads a built-in', () => {
  // Before the built-ins had tails, a spread of one recomputed in full on every
  // tick, through its own calc. It still does: the tail is not something a
  // spread copies, so each of these keeps the values its own calc gives.

  it('carries no calcTail, and the built-in keeps its own', () => {
    for (const id of Object.keys(CASES)) {
      const d = getIndicator(id);
      expect(d.calcTail, id).toBeTypeOf('function');
      expect({ ...d }.calcTail, id).toBeUndefined();
      expect(Object.keys(d), id).not.toContain('calcTail');
    }
  });

  it('keeps a column it adds to the output of the built-in through a tick', () => {
    const h = mount();
    const sma = getIndicator('sma');
    const d: IndicatorDescriptor = {
      ...sma, id: 'tail-spread-extra', name: 'extra',
      plots: [...sma.plots, { key: 'extra', type: 'line', title: 'extra' }],
      calc: (b, s, st, c) => ({ ...sma.calc(b, s, st, c), extra: b.map((x) => x.close * 2) }),
    };
    registerIndicator(d);
    const api = h.chart.addIndicator(d.id, { length: 3 });
    const data = h.tick(44);
    expect(firstDifference(api.values(), d.calc(data, api.settings(), {}))).toBeNull();
    h.chart.destroy();
  });

  it('keeps a forming bar it blanks blank through a tick', () => {
    const h = mount();
    const ema = getIndicator('ema');
    const d: IndicatorDescriptor = {
      ...ema, id: 'tail-spread-closed', name: 'closed',
      calc: (b, s, st, c) => { const ma = ema.calc(b, s, st, c).ma.slice(); ma[ma.length - 1] = null; return { ma }; },
    };
    registerIndicator(d);
    const api = h.chart.addIndicator(d.id, { length: 3 });
    h.tick(44);
    expect(api.values().ma[29]).toBeNull();
    expect(api.values().ma[28]).not.toBeNull();
    h.chart.destroy();
  });

  it('keeps the tail when it copies it by name and returns the built-in result', () => {
    const h = mount();
    const ema = getIndicator('ema');
    let fulls = 0;
    const d: IndicatorDescriptor = {
      ...ema, id: 'tail-spread-copied', name: 'copied',
      calc: (...args) => { fulls++; return ema.calc(...args); },
      calcTail: ema.calcTail,
    };
    registerIndicator(d);
    const api = h.chart.addIndicator(d.id, { length: 3 });
    expect(fulls).toBe(1);
    const data = h.tick(44);
    expect(fulls).toBe(1);
    expect(firstDifference(api.values(), ema.calc(data, api.settings(), {}))).toBeNull();
    h.chart.destroy();
  });

  it('keeps the settings it hands the built-in through a tick', () => {
    const h = mount();
    const rsi = getIndicator('rsi');
    const d: IndicatorDescriptor = {
      ...rsi, id: 'tail-spread-doubled', name: 'doubled',
      calc: (b, s, st, c) => rsi.calc(b, { ...s, length: Number(s.length) * 2 }, st, c),
    };
    registerIndicator(d);
    const api = h.chart.addIndicator(d.id, { length: 7 });
    const data = h.tick(40.5);
    expect(firstDifference(api.values(), d.calc(data, api.settings(), {}))).toBeNull();
    h.chart.destroy();
  });
});

describe('the runtime splice', () => {
  // A tail is laid over the result held for the bars before it. One that does
  // not answer for every column, or a held column that is not as long as the
  // bars it was computed for, cannot be spliced, so the chart computes in full.
  it('takes a tail that answers every column of a held result of the right length', () => {
    expect(spliceTail({ a: [1, 2, 3], b: [4, 5, 6] }, { a: [9], b: [7] }, 2, 3)).toEqual({ a: [1, 2, 9], b: [4, 5, 7] });
    expect(spliceTail({ a: [1, 2, 3] }, { a: [9, 8] }, 2, 4)).toEqual({ a: [1, 2, 9, 8] });
  });

  it('refuses a tail that leaves a column out, or a held column of the wrong length', () => {
    expect(spliceTail({ a: [1, 2, 3], b: [4, 5, 6] }, { a: [9] }, 2, 3)).toBeNull();
    expect(spliceTail({ a: [1, 2] }, { a: [9] }, 2, 3)).toBeNull();
    expect(spliceTail({ a: [1, 2, 3, 4] }, { a: [9] }, 2, 3)).toBeNull();
  });

  it('keeps a column a custom tail leaves out through a tick', () => {
    const h = mount();
    let tails = 0;
    const d: IndicatorDescriptor = {
      id: 'tail-partial', name: 'partial', placement: 'pane', inputs: [],
      plots: [{ key: 'close', type: 'line', title: 'close' }, { key: 'double', type: 'line', title: 'double' }],
      calc: (b) => ({ close: b.map((x) => x.close), double: b.map((x) => x.close * 2) }),
      // Answers for the first column only.
      calcTail: (b, _s, from) => { tails++; return { close: b.slice(from).map((x) => x.close) }; },
    };
    registerIndicator(d);
    const api = h.chart.addIndicator(d.id);
    const data = h.tick(44);
    // Reading the values runs the tick's recompute, which tries the tail first.
    expect(firstDifference(api.values(), d.calc(data, api.settings(), {}))).toBeNull();
    expect(tails).toBe(1);
    h.chart.destroy();
  });
});

describe('what a tick costs', () => {
  // The point of a tail. Once it has resumed, a tick or an appended bar reads a
  // window's or a step's worth of bars, not the history; a tail that quietly
  // rebuilt from bar 0 would still be right and would still pass every test
  // above. So the bars each tail reads are counted.
  it('each built-in reads a bounded number of bars per tick and per appended bar', () => {
    for (const id of Object.keys(CASES)) {
      const d = getIndicator(id);
      const settings = settingsFor(d, {});
      const rnd = prng(4242);
      const f: Flavour = { clock: 'nse', holes: 0, extremes: 0, zeros: 0, grid: 0.05 };
      const next = timeline(f.clock, rnd);
      const bars: Bar[] = [];
      for (let i = 0; i < 3000; i++) bars.push(makeBar(rnd, f, next(), bars[i - 1], false));
      const store: IndicatorStore = {};
      let held = d.calc(bars, settings, store);
      let reads = 0;
      const counted = new Proxy(bars, {
        get(target, key, receiver) {
          if (typeof key === 'string' && /^\d+$/.test(key)) reads++;
          return Reflect.get(target, key, receiver);
        },
      });
      const after: number[] = [];
      for (let e = 0; e < 40; e++) {
        const n0 = bars.length;
        if (e % 4 === 3) bars.push(makeBar(rnd, f, next(), bars[n0 - 1], false));
        else bars[n0 - 1] = makeBar(rnd, f, bars[n0 - 1].time, bars[n0 - 1], true);
        reads = 0;
        const tail = d.calcTail!(counted, settings, n0 - 1, held, store);
        expect(tail, `${id} event ${e}`).not.toBeNull();
        held = spliceTail(held, tail!, n0 - 1, bars.length)!;
        // The first tail after a full calc walks the history once to rebuild.
        if (e === 0) expect(reads, id).toBeGreaterThan(0);
        else after.push(reads);
      }
      expect(Math.max(...after), id).toBeLessThan(100);
    }
  });
});

describe('the resumable kernels are the batch kernels', () => {
  // Pinned directly as well as through the studies, so a drifted copy is named
  // by the kernel it drifted from.
  // From seed 60 on, a third of the values sit near the top of the range, so a
  // seed window overflows and is retried a bar later, a path ordinary data
  // almost never takes.
  const series = (seed: number, n: number): number[] => {
    const rnd = prng(seed);
    const heavy = seed >= 60;
    return Array.from({ length: n }, () => {
      const r = rnd();
      if (r < 0.06) return NaN;
      if (heavy && r < 0.4) return [1e308, 1.7e308, -1e308, 9e307][Math.floor(rnd() * 4)];
      if (r < 0.08) return [1e308, -1e308, 1.7e308, Infinity, 0, -0][Math.floor(rnd() * 6)];
      return (rnd() - 0.4) * 100;
    });
  };
  const same = (a: readonly number[], b: readonly number[]): boolean => a.length === b.length && a.every((v, i) => Object.is(v, b[i]));

  it('smooth is smaSeededEma and rma', () => {
    for (let seed = 1; seed < 120; seed++) {
      const values = series(seed, 120);
      for (const period of [1, 2, 3, 7, 20]) {
        for (const exponential of [true, false]) {
          const st = seeded();
          const stepped = values.map((x) => smooth(st, x, period, exponential));
          expect(same(stepped, exponential ? smaSeededEma(values, period) : rma(values, period)), `${seed} ${period} ${exponential}`).toBe(true);
        }
      }
    }
  });

  it('rsiStep is rsi, atrStep and trueRangeAt are atr and trueRange, meanAt is sma', () => {
    for (let seed = 1; seed < 120; seed++) {
      const closes = series(seed, 120);
      const data: Bar[] = closes.map((c, i) => ({ time: i, open: c, high: c + Math.abs(series(seed + 1, 120)[i]), low: c - 1, close: c }));
      const high = data.map((b) => b.high);
      const low = data.map((b) => b.low);
      for (const period of [1, 2, 5, 14]) {
        const r = rsiState();
        expect(same(closes.map((x) => rsiStep(r, x, period)), rsi(closes, period)), `rsi ${seed} ${period}`).toBe(true);
        const w = wilder();
        expect(same(data.map((_, i) => atrStep(w, trueRangeAt(data, i), period)), atr(high, low, closes, period)), `atr ${seed} ${period}`).toBe(true);
        expect(same(data.map((_, i) => meanAt((j) => closes[j], i, period)), smaKernel(closes, period)), `sma ${seed} ${period}`).toBe(true);
        const st = supertrendState();
        const turn: { direction: -1 | 1 } = { direction: 1 };
        const stepped = data.map((_, i) => { const v = supertrendStep(st, data, i, period, 2.5, turn); return { v, d: turn.direction }; });
        const batch = supertrend(data, period, 2.5);
        expect(stepped.every((p, i) => Object.is(p.v, batch[i].value) && (!Number.isFinite(p.v) || p.d === batch[i].direction)), `supertrend ${seed} ${period}`).toBe(true);
      }
      expect(same(data.map((_, i) => trueRangeAt(data, i)), trueRange(high, low, closes))).toBe(true);
    }
  });
});
