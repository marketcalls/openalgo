/**
 * A higher timeframe on a built-in study (`withTimeframe`, issue 22).
 *
 * The timeframe input is opt-in per built-in. Empty, which is the default, the
 * study is exactly what it was: the same calc, the same live tail. Set, the
 * chart's bars are folded to the timeframe, anchored to the session open, and
 * each bucket's value appears once the bucket has completed, so a live tick
 * never changes a value already shown.
 *
 * The bars are a seeded random walk over NSE sessions, 09:15 to 15:29 IST.
 */
import { afterEach, describe, expect, it } from 'vitest';
import '../src/indicators/index';
import { withTimeframe } from '../src/indicators/timeframe';
import { bucketKeys, keyOf, securityExpression } from '../src/indicators/security';
import { Chart } from '../src/core/chart';
import { CHART_STATE_VERSION } from '../src/model/chart-state';
import { registerInterval, resolveInterval } from '../src/feed/intervals';
import {
  getIndicator, indicatorDefaults, registerIndicator, registeredIndicators, IndicatorInputError,
} from '../src/model/indicator-registry';
import type {
  IndicatorCalcContext, IndicatorDescriptor, IndicatorSettings, IndicatorStore, IndicatorValues,
} from '../src/model/indicator-registry';
import type { Bar } from '../src/model/bar';
import { fakeDocument } from './helpers/fake-dom';
import { registerTransformChartTypes, RenkoTransform } from '../src/transform/index';

registerTransformChartTypes();

// ── data ──────────────────────────────────────────────────────────────────────

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

const DAY = 86400;
/** 09:15 IST, as seconds after UTC midnight. */
const NSE_OPEN = 3 * 3600 + 45 * 60;
/** Monday 2026-09-07, UTC midnight. */
const MONDAY = Date.UTC(2026, 8, 7) / 1000;

/** The next bar of a random walk from `prev`, at `time`. */
function step(rnd: () => number, time: number, prev: Bar | undefined): Bar {
  const open = prev?.close ?? 1000;
  const close = Math.round(open * (1 + (rnd() - 0.5) * 0.004) * 20) / 20;
  const high = Math.round(Math.max(open, close) * (1 + rnd() * 0.001) * 20) / 20;
  const low = Math.round(Math.min(open, close) * (1 - rnd() * 0.001) * 20) / 20;
  return { time, open, high, low, close, volume: 100 + Math.floor(rnd() * 900) };
}

/** Weekday session opens, UTC seconds, from MONDAY. */
function opens(days: number, first = MONDAY): number[] {
  const out: number[] = [];
  for (let day = first; out.length < days; day += DAY) {
    const weekday = new Date(day * 1000).getUTCDay();
    if (weekday !== 0 && weekday !== 6) out.push(day + NSE_OPEN);
  }
  return out;
}

/** One-minute NSE bars over `days` sessions, each `minutes` long from 09:15. */
function nseMinutes(days: number, seed: number, minutes = 375): Bar[] {
  const rnd = prng(seed);
  const out: Bar[] = [];
  for (const open of opens(days)) {
    for (let m = 0; m < minutes; m++) out.push(step(rnd, open + m * 60, out[out.length - 1]));
  }
  return out;
}

/**
 * The fold written out by hand, for NSE bars in IST: a sub-day bucket counts
 * `size` seconds from that day's 09:15, the way the exchange cuts its own
 * hourly bars. Returns the folded bars and each source bar's bucket number.
 */
function handFold(bars: readonly Bar[], size: number): { folded: Bar[]; bucket: number[] } {
  const folded: Bar[] = [];
  const bucket: number[] = [];
  let key = NaN;
  for (const bar of bars) {
    const day = Math.floor((bar.time - NSE_OPEN) / DAY);
    const k = day * 1e6 + Math.floor((bar.time - (day * DAY + NSE_OPEN)) / size);
    if (k !== key) folded.push({ ...bar });
    else {
      const last = folded[folded.length - 1];
      last.high = Math.max(last.high, bar.high);
      last.low = Math.min(last.low, bar.low);
      last.close = bar.close;
      last.volume = (last.volume ?? 0) + (bar.volume ?? 0);
    }
    key = k;
    bucket.push(folded.length - 1);
  }
  return { folded, bucket };
}

function context(interval: string | undefined, bars: readonly Bar[], timezone = 'Asia/Kolkata'): IndicatorCalcContext {
  return {
    barState: { isNew: false, isConfirmed: true, isRealtime: false, lastIndex: bars.length - 1 },
    ...(interval === undefined ? {} : { interval }),
    timezone,
    now: () => (bars[bars.length - 1]?.time ?? 0) + 60,
  };
}

const settingsFor = (d: IndicatorDescriptor, patch: IndicatorSettings = {}): IndicatorSettings =>
  ({ ...indicatorDefaults(d), ...patch });

/** The first place two results disagree, compared with Object.is, or null. */
function firstDifference(a: IndicatorValues, b: IndicatorValues): string | null {
  const keys = new Set([...Object.keys(a), ...Object.keys(b)]);
  for (const key of keys) {
    const x = a[key];
    const y = b[key];
    if (x === undefined || y === undefined) return `${key}: present in one result only`;
    if (x.length !== y.length) return `${key}: length ${x.length} vs ${y.length}`;
    for (let i = 0; i < x.length; i++) {
      if (!Object.is(x[i] ?? null, y[i] ?? null)) return `${key}[${i}]: ${x[i]} vs ${y[i]}`;
    }
  }
  return null;
}

function splice(prev: IndicatorValues, tail: IndicatorValues, from: number, n: number): IndicatorValues {
  const out: Record<string, (number | null)[]> = {};
  for (const key of Object.keys(tail)) {
    const col = (prev[key] ?? []).slice(0, from);
    while (col.length < from) col.push(null);
    out[key] = col.concat(tail[key] as (number | null)[]).slice(0, n);
  }
  return out;
}

const cleanups: (() => void)[] = [];
afterEach(() => { while (cleanups.length > 0) cleanups.pop()!(); });

function makeChart(timezone?: string): Chart {
  const doc = fakeDocument();
  const chart = new Chart(doc.createElement('div'), {
    document: doc, pixelRatio: () => 1, shortcuts: false,
    ...(timezone === undefined ? {} : { timezone }),
    raf: { schedule: (cb: () => void) => { cb(); return 1; }, cancel: () => {} },
  });
  chart.applySize(800, 600);
  cleanups.push(() => chart.destroy());
  return chart;
}

// ── which built-ins take it ───────────────────────────────────────────────────

/** Studies where a higher timeframe changes the line. */
const OPTED_IN = [
  'sma', 'ema', 'wma', 'vwma', 'hma', 'dema', 'tema', 'alma', 'smma', 't3', 'lsma', 'kama', 'mcginley-dynamic',
  'zlema', 'vidya',
  'bollinger', 'keltner-channel', 'donchian', 'envelope',
  'supertrend', 'parabolic-sar', 'atr',
  'rsi', 'macd', 'stochastic', 'stochastic-rsi', 'williams-percent-r', 'cci', 'adx',
].sort();

describe('which built-ins take a timeframe', () => {
  it('exactly the opted-in list declares the input, as an empty interval', () => {
    const declared = registeredIndicators()
      .filter((d) => d.inputs.some((input) => input.key === 'timeframe'))
      .map((d) => d.id)
      .sort();
    expect(declared).toEqual(OPTED_IN);
    for (const id of OPTED_IN) {
      const input = getIndicator(id).inputs.find((i) => i.key === 'timeframe');
      expect(input, id).toMatchObject({ type: 'interval', default: '', label: 'Timeframe' });
    }
  });

  it('indicatorDefaults gains the key for the opted-in studies only', () => {
    for (const d of registeredIndicators()) {
      const defaults = indicatorDefaults(d);
      if (OPTED_IN.includes(d.id)) expect(defaults.timeframe, d.id).toBe('');
      else expect(Object.prototype.hasOwnProperty.call(defaults, 'timeframe'), d.id).toBe(false);
    }
  });

  it('keeps an input in its ungrouped section, ahead of a grouped one', () => {
    const cci = getIndicator('cci');
    const at = cci.inputs.findIndex((i) => i.key === 'timeframe');
    expect(cci.inputs[at + 1]?.group).toBe('Smoothing');
    expect(cci.inputs.slice(0, at).every((i) => i.group === undefined)).toBe(true);
  });

  it('refuses a descriptor that already has the key, or brings its own data', () => {
    const base: IndicatorDescriptor = {
      id: 'tf-own', name: 'Own', placement: 'pane', inputs: [], plots: [{ key: 'v', type: 'line', title: 'V' }],
      calc: (bars) => ({ v: bars.map((b) => b.close) }),
    };
    expect(() => withTimeframe(withTimeframe(base))).toThrow(/timeframe/);
    expect(() => withTimeframe({ ...base, attach: () => {} })).toThrow(/own data/);
  });
});

// ── empty is exactly today ────────────────────────────────────────────────────

describe('an empty timeframe is the study as it was', () => {
  it('hands calc and calcTail their exact arguments and returns their exact results', () => {
    const calls: unknown[][] = [];
    const result = { v: [1, 2, 3] };
    const tailResult = { v: [3] };
    const base: IndicatorDescriptor = {
      id: 'tf-forward', name: 'Forward', placement: 'pane', inputs: [], plots: [{ key: 'v', type: 'line', title: 'V' }],
      calc: (...args) => { calls.push(['calc', ...args]); return result; },
      calcTail: (...args) => { calls.push(['tail', ...args]); return tailResult; },
    };
    const d = withTimeframe(base);
    const bars = nseMinutes(1, 5).slice(0, 3);
    const store: IndicatorStore = {};
    const ctx = context('1m', bars);
    for (const timeframe of [undefined, '', '  ']) {
      calls.length = 0;
      const settings: IndicatorSettings = timeframe === undefined ? {} : { timeframe };
      expect(d.calc(bars, settings, store, ctx)).toBe(result);
      expect(d.calcTail!(bars, settings, 2, result, store, ctx)).toBe(tailResult);
      expect(calls).toEqual([['calc', bars, settings, store, ctx], ['tail', bars, settings, 2, result, store, ctx]]);
      expect(calls[0][1]).toBe(bars);
      expect(calls[0][2]).toBe(settings);
      expect(calls[0][3]).toBe(store);
      expect(calls[0][4]).toBe(ctx);
    }
    // A spread carries no tail, as with every built-in.
    expect({ ...d }.calcTail).toBeUndefined();
    expect(Object.keys(d)).not.toContain('calcTail');
  });

  it('every opted-in built-in computes what it did, value for value', () => {
    const bars = nseMinutes(2, 11);
    for (const id of OPTED_IN) {
      const d = getIndicator(id);
      const plain = d.calc(bars, settingsFor(d), {}, context('1m', bars));
      // With no key at all, as a caller that predates it passes.
      const { timeframe: _timeframe, ...older } = settingsFor(d);
      expect(firstDifference(d.calc(bars, older, {}, context('1m', bars)), plain), id).toBeNull();
    }
  });

  it('a live chart still takes the built-in tail on every tick', () => {
    const chart = makeChart();
    chart.setDataContext({ interval: '1m' });
    const rnd = prng(7);
    const data = nseMinutes(2, 3);
    const series = chart.addSeries('candlestick');
    series.setData(data);
    const probes = ['ema', 'rsi', 'supertrend', 'macd', 'bollinger'].map((id) => {
      const d = getIndicator(id);
      const counts = { tails: 0, fulls: 0 };
      const probe: IndicatorDescriptor = {
        ...d, id: `tf-probe-${id}`,
        calc: (...args) => { counts.fulls++; return d.calc(...args); },
        calcTail: (...args) => { const out = d.calcTail!(...args); if (out !== null) counts.tails++; return out; },
      };
      registerIndicator(probe);
      return { d, counts, api: chart.addIndicator(probe.id) };
    });
    for (let e = 0; e < 60; e++) {
      const last = data[data.length - 1];
      const bar = e % 5 === 4 ? step(rnd, last.time + 60, last) : { ...step(rnd, last.time, last), open: last.open };
      if (bar.time === last.time) data[data.length - 1] = bar; else data.push(bar);
      series.update(bar);
      for (const p of probes) {
        expect(firstDifference(p.api.values(), p.d.calc(data, settingsFor(p.d), {})), `${p.d.id} event ${e}`).toBeNull();
      }
    }
    for (const p of probes) {
      expect(p.counts.tails, p.d.id).toBeGreaterThanOrEqual(58);
      expect(p.counts.fulls, p.d.id).toBeLessThanOrEqual(3);
    }
  });
});

// ── the fold ─────────────────────────────────────────────────────────────────

describe('a timeframe folds the chart bars and reads each completed bucket', () => {
  it('is the study on bars folded by hand, one bucket late', () => {
    const bars = nseMinutes(3, 21);
    for (const [tf, size] of [['15m', 900], ['1h', 3600], ['30m', 1800]] as const) {
      const { folded, bucket } = handFold(bars, size);
      for (const id of ['ema', 'rsi', 'supertrend', 'macd', 'bollinger', 'atr', 'adx', 'stochastic', 'donchian']) {
        const d = getIndicator(id);
        const own = d.calc(folded, settingsFor(d), {});
        const got = d.calc(bars, settingsFor(d, { timeframe: tf }), {}, context('1m', bars));
        expect(Object.keys(got).sort(), id).toEqual(Object.keys(own).sort());
        for (const key of Object.keys(own)) {
          const expected = bucket.map((k) => (k === 0 ? null : (own[key][k - 1] ?? null)));
          expect(firstDifference({ [key]: got[key] }, { [key]: expected }), `${id} ${tf} ${key}`).toBeNull();
        }
      }
    }
  });

  it('anchors an hourly bucket to the 09:15 open in the chart zone, not to the half hour', () => {
    const bars = nseMinutes(2, 4);
    const d = getIndicator('sma');
    const got = d.calc(bars, settingsFor(d, { timeframe: '1h', length: 1 }), {}, context('1m', bars)).ma;
    // SMA(1) of an hourly bucket is its close: the value steps on the first
    // bar of each bucket, 10:15, 11:15 and so on, and holds between.
    const changes: string[] = [];
    for (let i = 1; i < bars.length; i++) {
      if (got[i] !== got[i - 1]) {
        const ist = new Date((bars[i].time + 19800) * 1000);
        changes.push(`${ist.getUTCHours()}:${String(ist.getUTCMinutes()).padStart(2, '0')}`);
      }
    }
    expect(changes).toEqual([
      '10:15', '11:15', '12:15', '13:15', '14:15', '15:15',
      '9:15', '10:15', '11:15', '12:15', '13:15', '14:15', '15:15',
    ]);
  });

  it('reads the open from most of the loaded days, whatever the first bar of one day is', () => {
    // An illiquid day that trades first at 09:17, and a history that starts
    // mid-session: neither moves the anchor off 09:15.
    const bars = nseMinutes(4, 9).filter((_, i) => !(i >= 375 && i < 377)).slice(100);
    const d = getIndicator('sma');
    const got = d.calc(bars, settingsFor(d, { timeframe: '1h', length: 1 }), {}, context('1m', bars)).ma;
    const at = (hhmm: string, day: number): number => {
      const [h, m] = hhmm.split(':').map(Number);
      return bars.findIndex((b) => b.time === opens(4)[day] + ((h * 60 + m) - 555) * 60);
    };
    for (const day of [1, 2, 3]) {
      expect(got[at('10:15', day)], `day ${day}`).not.toBe(got[at('10:14', day)]);
      expect(got[at('10:30', day)], `day ${day}`).toBe(got[at('10:15', day)]);
    }
    // One cut day and one whole one: a tie, and the earlier open is the real one.
    const two = nseMinutes(2, 9).slice(100);
    const hourly = d.calc(two, settingsFor(d, { timeframe: '1h', length: 1 }), {}, context('1m', two)).ma;
    const tenFifteen = two.findIndex((b) => b.time === opens(2)[1] + 60 * 60);
    expect(hourly[tenFifteen]).not.toBe(hourly[tenFifteen - 1]);
    expect(hourly[tenFifteen + 40]).toBe(hourly[tenFifteen]);
  });

  it('anchors a New York chart to its own 09:30 open', () => {
    const rnd = prng(12);
    const bars: Bar[] = [];
    // 09:30 New York in September is 13:30 UTC.
    for (const open of opens(3, MONDAY).map((t) => t - NSE_OPEN + 13 * 3600 + 30 * 60)) {
      for (let m = 0; m < 390; m++) bars.push(step(rnd, open + m * 60, bars[bars.length - 1]));
    }
    const d = getIndicator('sma');
    const got = d.calc(bars, settingsFor(d, { timeframe: '1h', length: 1 }), {}, context('1m', bars, 'America/New_York')).ma;
    const first = bars.findIndex((_, i) => i > 0 && got[i] !== got[i - 1]);
    expect(bars[first].time - bars[0].time).toBe(3600);
  });

  it('takes a timeframe no coarser than the chart as the chart own', () => {
    const bars = nseMinutes(1, 2);
    const fifteen = handFold(bars, 900).folded;
    for (const id of ['ema', 'supertrend']) {
      const d = getIndicator(id);
      for (const tf of ['5m', '15m', '1m']) {
        const got = d.calc(fifteen, settingsFor(d, { timeframe: tf }), {}, context('15m', fifteen));
        expect(firstDifference(got, d.calc(fifteen, settingsFor(d), {})), `${id} ${tf} on 15m`).toBeNull();
      }
    }
  });

  it('with no chart interval, a timeframe that puts no two bars together is the chart own', () => {
    const bars = nseMinutes(1, 2);
    const d = getIndicator('ema');
    const own = d.calc(bars, settingsFor(d), {});
    expect(firstDifference(d.calc(bars, settingsFor(d, { timeframe: '1m' }), {}), own)).toBeNull();
    const folded = d.calc(bars, settingsFor(d, { timeframe: '15m' }), {});
    expect(firstDifference(folded, own)).not.toBeNull();
  });

  it('never changes a value already shown: a prefix computes the values the full history does', () => {
    const bars = nseMinutes(3, 33);
    for (const id of ['ema', 'supertrend', 'parabolic-sar', 'kama', 'vidya']) {
      const d = getIndicator(id);
      const s = settingsFor(d, { timeframe: '15m' });
      const full = d.calc(bars, s, {}, context('1m', bars));
      for (const cut of [1, 14, 15, 16, 374, 375, 376, 700, 1124]) {
        const part = bars.slice(0, cut);
        const got = d.calc(part, s, {}, context('1m', part));
        const want: IndicatorValues = Object.fromEntries(Object.entries(full).map(([k, v]) => [k, v.slice(0, cut)]));
        expect(firstDifference(got, want), `${id} after ${cut} bars`).toBeNull();
      }
    }
  });
});

// ── live ──────────────────────────────────────────────────────────────────────

interface Run { events: number; tails: number; failure: string | null }

/** Ticks and appended bars, the way the runtime drives a study: tail from the last bar, else a full calc. */
function drive(d: IndicatorDescriptor, settings: IndicatorSettings, seed: number, events: number, initial: number): Run {
  const rnd = prng(seed);
  const bars = nseMinutes(3, seed);
  const history = bars.slice(0, initial);
  const store: IndicatorStore = {};
  let held = d.calc(history, settings, store, context('1m', history));
  let tails = 0;
  let next = initial;
  for (let e = 0; e < events; e++) {
    const n0 = history.length;
    if (rnd() < 0.3 && next < bars.length) history.push(bars[next++]);
    else history[n0 - 1] = { ...step(rnd, history[n0 - 1].time, history[n0 - 2]), open: history[n0 - 1].open };
    const ctx = context('1m', history);
    const tail = d.calcTail!(history, settings, n0 - 1, held, store, ctx);
    const expected = d.calc(history, settings, {}, ctx);
    if (tail !== null) {
      held = splice(held, tail, n0 - 1, history.length);
      tails++;
    } else held = d.calc(history, settings, store, ctx);
    const diff = firstDifference(held, expected);
    if (diff !== null) return { events: e + 1, tails, failure: `event ${e} (${tail === null ? 'full' : 'tail'}): ${diff}` };
  }
  return { events, tails, failure: null };
}

describe('live ticks on a timeframe', () => {
  it('splice to what a full calc gives, taking the tail inside a bucket', () => {
    for (const id of OPTED_IN) {
      const d = getIndicator(id);
      let events = 0;
      let tails = 0;
      for (const [tf, initial] of [['15m', 200], ['1h', 370], ['1d', 800]] as const) {
        const run = drive(d, settingsFor(d, { timeframe: tf }), 90 + initial, 120, initial);
        expect(run.failure, `${id} ${tf}`).toBeNull();
        events += run.events;
        tails += run.tails;
      }
      expect(tails / events, id).toBeGreaterThan(0.85);
    }
  }, 60_000);

  it('recomputes in full on every tick for settings that read ahead of the bar', () => {
    // A negative displacement puts a later bucket's value on an earlier bar,
    // so the forming bucket changes what is already shown: no carry is exact.
    for (const [id, patch] of [['donchian', { length: 3, offset: -2 }], ['vwma', { length: 3, offset: -1 }]] as const) {
      const d = getIndicator(id);
      const run = drive(d, settingsFor(d, { timeframe: '15m', ...patch }), 5, 80, 200);
      expect(run.failure, id).toBeNull();
      expect(run.tails, id).toBe(0);
    }
  });

  it('holds on a live chart what a reload computes', () => {
    const chart = makeChart();
    chart.setDataContext({ interval: '1m' });
    const rnd = prng(19);
    const all = nseMinutes(2, 19);
    const data = all.slice(0, 500);
    const series = chart.addSeries('candlestick');
    series.setData(data);
    const ema = chart.addIndicator('ema', { timeframe: '15m', length: 5 });
    const st = chart.addIndicator('supertrend', { timeframe: '5m', period: 3 });
    const shown: (number | null)[] = [...ema.values().ma];
    let next = 500;
    for (let e = 0; e < 90; e++) {
      const last = data[data.length - 1];
      const bar = e % 6 === 5 ? all[next++] : { ...step(rnd, last.time, data[data.length - 2]), open: last.open };
      if (bar.time === last.time) data[data.length - 1] = bar; else data.push(bar);
      series.update(bar);
      for (const api of [ema, st]) {
        const d = getIndicator(api.indicatorId);
        const want = d.calc(data, api.settings(), {}, context('1m', data));
        expect(firstDifference(api.values(), want), `${api.indicatorId} event ${e}`).toBeNull();
      }
      // Nothing a user has already seen moves.
      const now = ema.values().ma;
      for (let i = 0; i < shown.length - 1; i++) expect(now[i], `bar ${i} at event ${e}`).toBe(shown[i]);
      shown.splice(0, shown.length, ...now);
    }
  });
});

// ── what it refuses ──────────────────────────────────────────────────────────

describe('what a timeframe refuses', () => {
  const bars = nseMinutes(1, 8);

  it('an interval that closes on trade flow, an unknown code, or bars that do', () => {
    cleanups.push(registerInterval({ code: 'T100', bucketing: { mode: 'ticks', count: 100 } }));
    cleanups.push(registerInterval({ code: 'V5K', bucketing: { mode: 'volume', perBar: 5000 } }));
    const d = getIndicator('ema');
    const run = (timeframe: unknown, interval = '1m') => () => d.calc(bars, settingsFor(d, { timeframe }), {}, context(interval, bars));
    expect(run('T100')).toThrow(IndicatorInputError);
    expect(run('T100')).toThrow(/trade flow/);
    expect(run('V5K')).toThrow(/trade flow/);
    expect(run('7x')).toThrow(IndicatorInputError);
    expect(run('7x')).toThrow(/not a known timeframe/);
    expect(run(15)).toThrow(IndicatorInputError);
    expect(run('15m', 'T100')).toThrow(/chart's "T100" bars close on trade flow/);
    // The chart's own timeframe is no fold, so nothing is refused for it.
    expect(run('', 'T100')).not.toThrow();
  });

  it('another study output as the source, while it folds', () => {
    const d = getIndicator('ema');
    const source = { kind: 'indicator', instanceId: 'up', plotKey: 'ma' };
    const ctx = { ...context('1m', bars), resolveSource: () => bars.map((b) => b.close) };
    expect(() => d.calc(bars, settingsFor(d, { timeframe: '15m', source }), {}, ctx)).toThrow(/another study's output/);
    // Not folding, it reads the output as it always did.
    expect(() => d.calc(bars, settingsFor(d, { source }), {}, ctx)).not.toThrow();
  });

  it('through the chart: the add throws, a later setting reports an error status and recovers', () => {
    cleanups.push(registerInterval({ code: 'T100', bucketing: { mode: 'ticks', count: 100 } }));
    const chart = makeChart();
    chart.setDataContext({ interval: '1m' });
    chart.addSeries('candlestick').setData(bars);
    expect(() => chart.addIndicator('ema', { timeframe: 'T100' })).toThrow(/trade flow/);
    const ema = chart.addIndicator('ema', { timeframe: '15m' });
    expect(ema.dataStatus()).toBeNull();
    ema.setSettings({ timeframe: 'T100' });
    ema.values();
    const status = ema.dataStatus();
    expect(status?.state).toBe('error');
    expect(String((status as { error: unknown }).error)).toMatch(/trade flow/);
    ema.setSettings({ timeframe: '1h' });
    ema.values();
    expect(ema.dataStatus()?.state).toBe('ready');
  });
});

// ── on a transformed chart ────────────────────────────────────────────────────

/**
 * A chart that transforms its bars draws elements (bricks, Heikin Ashi
 * candles) whose times are not a clock, so a study on the chart's own bars
 * has nothing a timeframe could fold. On the underlying bars it folds as on
 * any chart, and its values are read at the bar each element completed on.
 */
describe('a timeframe on a transformed chart', () => {
  const bars = nseMinutes(2, 52);
  const BOX = 1;

  function transformed(type: 'renko' | 'heikin-ashi'): Chart {
    const chart = makeChart();
    chart.setDataContext({ interval: '1m' });
    const series = chart.addSeries('candlestick');
    series.setData(bars);
    chart.setSeriesTransform(series, type === 'renko' ? { type, options: { boxSize: BOX } } : { type });
    return chart;
  }

  /** The source bar each brick was completed on. */
  const completedOn = (): number[] => {
    const t = new RenkoTransform({ boxSize: BOX });
    return bars.flatMap((bar, i) => t.push(bar).map(() => i));
  };

  it('refuses the chart bars: the add throws, a later setting reports an error status and recovers', () => {
    const chart = transformed('renko');
    expect(() => chart.addIndicator('ema', { timeframe: '15m' })).toThrow(IndicatorInputError);
    expect(() => chart.addIndicator('ema', { timeframe: '15m' })).toThrow(/transformed bars.*underlying bars/);
    const ema = chart.addIndicator('ema', { length: 5 });
    expect(ema.dataStatus()).toBeNull();
    ema.setSettings({ timeframe: '15m' });
    ema.values();
    const status = ema.dataStatus();
    expect(status?.state).toBe('error');
    expect(String((status as { error: unknown }).error)).toMatch(/transformed bars.*underlying bars/);
    ema.setSettings({ timeframe: '' });
    ema.values();
    expect(ema.dataStatus()?.state).toBe('ready');
  });

  it('counts Heikin Ashi as transformed, since its prices are not the traded ones', () => {
    const chart = transformed('heikin-ashi');
    expect(() => chart.addIndicator('ema', { timeframe: '15m' })).toThrow(/transformed bars/);
  });

  it('takes a timeframe no coarser than the chart as the chart own there too', () => {
    const chart = transformed('renko');
    const ema = chart.addIndicator('ema', { timeframe: '1m', length: 5 });
    const d = getIndicator('ema');
    expect(firstDifference(ema.values(), d.calc(chart.primaryBars(), settingsFor(d, { length: 5 }), {}))).toBeNull();
  });

  it('folds the underlying bars, read at the bar each brick completed on', () => {
    const chart = transformed('renko');
    const d = getIndicator('ema');
    const folded = d.calc(bars, settingsFor(d, { timeframe: '15m', length: 5 }), {}, context('1m', bars));
    const expected = { ma: completedOn().map((i) => folded.ma[i] ?? null) };
    expect(expected.ma.some((v) => v !== null)).toBe(true);
    const direct = chart.addIndicator('ema', { timeframe: '15m', length: 5 }, { barSource: 'underlying' });
    expect(direct.dataStatus()).toBeNull();
    expect(firstDifference(direct.values(), expected)).toBeNull();
    // A study refused on the chart bars recovers by moving to the underlying ones.
    const moved = chart.addIndicator('ema', { length: 5 });
    moved.setSettings({ timeframe: '15m' });
    moved.values();
    expect(moved.dataStatus()?.state).toBe('error');
    expect(moved.setBarSource('underlying')).toBe(true);
    expect(firstDifference(moved.values(), expected)).toBeNull();
    expect(moved.dataStatus()?.state).toBe('ready');
  });

  it('a layout saved with the refusal restores it as saved, beside the studies around it', () => {
    const chart = transformed('renko');
    chart.addIndicator('sma', { length: 5 });
    chart.addIndicator('ema', { length: 5 }).setSettings({ timeframe: '15m' });
    chart.addIndicator('rsi');
    const state = JSON.parse(JSON.stringify(chart.getState()));
    const again = transformed('renko');
    again.addIndicator('macd');
    expect(again.restoreState(state).applied).toBe(true);
    expect(again.indicators().map((api) => api.indicatorId)).toEqual(['sma', 'ema', 'rsi']);
    const ema = again.indicators()[1];
    expect(ema.settings().timeframe).toBe('15m');
    expect(ema.dataStatus()?.state).toBe('error');
    expect(String((ema.dataStatus() as { error: unknown }).error)).toMatch(/underlying bars/);
    expect(again.indicators()[2].dataStatus()).toBeNull();
    expect(ema.setBarSource('underlying')).toBe(true);
    ema.values();
    expect(ema.dataStatus()?.state).toBe('ready');
  });

  it('marks only the chart bars of a transformed series as transformed in the calc context', () => {
    const seen: (boolean | undefined)[] = [];
    registerIndicator({
      id: 'transformed-probe', name: 'Transformed probe', placement: 'onchart', inputs: [],
      plots: [{ key: 'v', type: 'line', title: 'v' }],
      calc: (b, _s, _store, ctx) => { seen.push(ctx?.transformed); return { v: b.map((bar) => bar.close) }; },
    });
    const plain = makeChart();
    plain.addSeries('candlestick').setData(bars);
    plain.addIndicator('transformed-probe');
    expect(seen.pop()).toBeUndefined();
    const chart = transformed('renko');
    const probe = chart.addIndicator('transformed-probe');
    expect(seen.pop()).toBe(true);
    probe.setBarSource('underlying');
    probe.values();
    expect(seen.pop()).toBeUndefined();
  });
});

// ── saved state ───────────────────────────────────────────────────────────────

/** What 2.5.10 wrote for these studies: no timeframe key anywhere. */
const SAVED_2510 = [
  { indicatorId: 'ema', instanceId: 'ema-1', paneIndex: 0, visible: true, settings: {
    length: 9, source: 'close', color: '#f5a623', 'ma:opacity': 100, 'ma:width': 1.5, 'ma:lineStyle': 'solid', 'ma:type': 'line' } },
  { indicatorId: 'rsi', instanceId: 'rsi-2', paneIndex: 1, visible: true, settings: {
    length: 14, source: 'close', color: '#e0b020', overbought: 70, oversold: 30, bandColor: '#7e57c2',
    'rsi:opacity': 100, 'rsi:width': 1.5, 'rsi:lineStyle': 'solid', 'rsi:type': 'line' } },
  { indicatorId: 'supertrend', instanceId: 'supertrend-3', paneIndex: 0, visible: true, settings: {
    period: 7, multiplier: 3, upColor: '#26a69a', downColor: '#ef5350',
    'up:opacity': 100, 'up:width': 2, 'up:lineStyle': 'solid', 'up:type': 'line',
    'down:opacity': 100, 'down:width': 2, 'down:lineStyle': 'solid', 'down:type': 'line' } },
  { indicatorId: 'vwap', instanceId: 'vwap-4', paneIndex: 0, visible: true, settings: {
    anchor: 'session', source: 'hlc3', offset: 0, calcMode: 'stdev', showBand1: true, bandMult1: 1, showBand2: false,
    bandMult2: 2, showBand3: false, bandMult3: 3, color: '#2962ff', band1Color: '#4caf50', band2Color: '#808000',
    band3Color: '#00bcd4' } },
];

// ── what a fold costs ─────────────────────────────────────────────────────────

describe('the fold reads the zone once per day, not once per bar', () => {
  // A zone lookup costs about 25 times the arithmetic, and a one-minute
  // history has hundreds of bars a day: per bar, a 15-minute EMA on 7500 bars
  // took a quarter of a second.
  it('cuts every bar exactly as keyOf does, across offset changes and odd offsets', () => {
    const rnd = prng(99);
    const zones = ['Asia/Kolkata', 'America/New_York', 'Europe/London', 'Australia/Lord_Howe', 'Pacific/Chatham',
      'America/Sao_Paulo', 'Etc/UTC'];
    cleanups.push(registerInterval({ code: 'tf-month', bucketing: { mode: 'calendar', unit: 'month' } }));
    cleanups.push(registerInterval({ code: 'tf-ny-quarter', bucketing: { mode: 'calendar', unit: 'quarter', timezone: 'America/New_York' } }));
    const codes = ['1m', '15m', '1h', '4h', '75m', '1d', '2d', '1w', '2w', 'tf-month', 'tf-ny-quarter'];
    for (const zone of zones) {
      // Ascending instants through both 2018 clock changes of each zone, with
      // gaps from a minute to a few days.
      const times: number[] = [];
      for (let t = Date.UTC(2018, 1, 20) / 1000; t < Date.UTC(2018, 11, 10) / 1000; t += 60 * Math.ceil(rnd() ** 6 * 4000)) times.push(t);
      for (const code of codes) {
        const b = resolveInterval(code).bucketing;
        for (const session of [null, 555, 0, 1350]) {
          const fast = bucketKeys(b, zone, session);
          for (const t of times) {
            const want = keyOf(b, t, zone, session);
            const got = fast(t);
            if (got !== want) expect(got, `${zone} ${code} session ${session} at ${t}`).toBe(want);
          }
        }
      }
    }
  }, 60_000);

  it('asks the zone a few times a day on a long one-minute history', () => {
    const bars = nseMinutes(20, 3);
    const calls = { n: 0 };
    const original = Intl.DateTimeFormat.prototype.formatToParts;
    Intl.DateTimeFormat.prototype.formatToParts = function (this: Intl.DateTimeFormat, date?: Date | number) {
      calls.n++;
      return original.call(this, date);
    };
    cleanups.push(() => { Intl.DateTimeFormat.prototype.formatToParts = original; });
    const d = getIndicator('ema');
    d.calc(bars, settingsFor(d, { timeframe: '1h' }), {}, context('1m', bars));
    securityExpression(bars, '15m', (requested) => ({ c: requested.map((b) => b.close) }), { timezone: 'Asia/Kolkata', session: '0915-1530' });
    expect(calls.n).toBeLessThan(20 * 12);
  });
});

describe('saved state', () => {
  const bars = nseMinutes(2, 40);

  function loaded(): Chart {
    const chart = makeChart();
    chart.setDataContext({ interval: '1m' });
    chart.addSeries('candlestick').setData(bars);
    return chart;
  }

  it('a 2.5.10 layout loads, computes what it did, and round-trips with the same output', () => {
    const chart = loaded();
    const report = chart.restoreState({ version: CHART_STATE_VERSION, indicators: SAVED_2510.map((s) => ({ ...s, settings: { ...s.settings } })) });
    expect(report.applied).toBe(true);
    const first = chart.indicators().map((api) => api.values());
    for (const [i, api] of chart.indicators().entries()) {
      const d = getIndicator(api.indicatorId);
      const { timeframe: _t, ...saved } = SAVED_2510[i].settings as IndicatorSettings;
      // What the 2.5.10 calculation gave for those settings: the same calc,
      // since an empty timeframe is no fold.
      expect(firstDifference(first[i], d.calc(bars, { ...indicatorDefaults(d), ...saved }, {})), api.indicatorId).toBeNull();
    }
    const state = chart.getState();
    const settings = Object.fromEntries((state.indicators ?? []).map((s) => [s.indicatorId, s.settings]));
    expect(settings.ema.timeframe).toBe('');
    expect(settings.rsi.timeframe).toBe('');
    expect(settings.supertrend.timeframe).toBe('');
    expect(Object.prototype.hasOwnProperty.call(settings.vwap, 'timeframe')).toBe(false);
    const again = loaded();
    expect(again.restoreState(JSON.parse(JSON.stringify(state))).applied).toBe(true);
    const second = again.indicators().map((api) => api.values());
    first.forEach((values, i) => expect(firstDifference(second[i], values), `study ${i}`).toBeNull());
    expect(JSON.parse(JSON.stringify(again.getState().indicators))).toEqual(JSON.parse(JSON.stringify(state.indicators)));
  });

  it('a timeframe saves, restores and computes the same', () => {
    const chart = loaded();
    const ema = chart.addIndicator('ema', { timeframe: '15m', length: 5 });
    const values = ema.values();
    const state = JSON.parse(JSON.stringify(chart.getState()));
    expect(state.indicators[0].settings.timeframe).toBe('15m');
    const again = loaded();
    expect(again.restoreState(state).applied).toBe(true);
    expect(firstDifference(again.indicators()[0].values(), values)).toBeNull();
    // And it is not the chart-timeframe line.
    expect(firstDifference(values, getIndicator('ema').calc(bars, settingsFor(getIndicator('ema'), { length: 5 }), {}))).not.toBeNull();
  });

  it('a layout restores a study its timeframe is refused on here in its error status, not failing the restore', () => {
    cleanups.push(registerInterval({ code: 'T100', bucketing: { mode: 'ticks', count: 100 } }));
    const chart = loaded();
    chart.addIndicator('ema', { timeframe: '15m', length: 5 });
    chart.addIndicator('rsi');
    const state = JSON.parse(JSON.stringify(chart.getState()));
    const again = makeChart();
    again.setDataContext({ interval: 'T100' });
    again.addSeries('candlestick').setData(bars);
    expect(again.restoreState(state).applied).toBe(true);
    const [ema, rsi] = again.indicators();
    expect(ema.dataStatus()?.state).toBe('error');
    expect(String((ema.dataStatus() as { error: unknown }).error)).toMatch(/trade flow/);
    expect(rsi.dataStatus()).toBeNull();
    // Added by the host rather than restored, it is refused outright.
    expect(() => again.addIndicator('ema', { timeframe: '15m' })).toThrow(/trade flow/);
  });

  it('the legend names the timeframe once one is set, and only then', () => {
    const chart = loaded();
    const ema = chart.addIndicator('ema', { length: 5 });
    const params = (): string => ema.legend()?.options().params ?? '';
    expect(params()).not.toMatch(/15m/);
    ema.setSettings({ timeframe: '15m' });
    expect(params()).toMatch(/15m/);
  });
});
