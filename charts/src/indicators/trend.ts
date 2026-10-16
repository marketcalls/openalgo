/**
 * Tier-1 trend indicators: computed from the chart's own OHLCV, no extra data.
 * Part of the lazy `openalgo-charts/indicators` tier.
 *
 * `supertrend`, `atr` and the `sourceValues` helper come from the base bundle
 * through the `'openalgo-charts'` specifier, not relative paths; see the note
 * in `src/indicators/index.ts`.
 */
import {
  supertrend, atr, sourceValues, sourceValue,
  sessionStartFlags, calendarPeriodFlags, isNewIstDay, isNewZonedDay, DEFAULT_TIMEZONE,
} from 'openalgo-charts';
import type { Bar, IndicatorDescriptor, IndicatorSource, IndicatorStudySource } from 'openalgo-charts';
import { sma, wma, stdev, highest, lowest, nulls, smaSeededEma } from './calc';
import type { NumericalWindowOptions } from './statistics';
import { withTail, whole, cell, claimOf, settle, windowTail, machineTail, type Tail } from './tail';
import { seeded, smooth, observed, observedStep, supertrendState, supertrendStep, sarState, sarStep } from './steppers';
import { withTimeframe } from './timeframe';
import { num, int, offsetOf, str, src, zoneOf } from './settings';
import { shift, zip } from './series';
import { periodBoundary } from './calendar';

type Calc = IndicatorDescriptor['calc'];

type Kernel = (values: readonly number[], period: number, options?: NumericalWindowOptions) => number[];

/**
 * A moving-average descriptor. The three MAs differ only in their kernel, and
 * in their tail: a window average reads its window again, the exponential one
 * resumes its running value.
 */
function movingAverage(id: string, name: string, color: string, kernel: Kernel, recursive: boolean): IndicatorDescriptor {
  const calc: Calc = (bars, s, _store, context) => {
    const source = src(s) as IndicatorSource | IndicatorStudySource;
    const values = typeof source === 'string' ? sourceValues(bars, source)
      : sourceValues(bars, source, context).map(value => value ?? NaN);
    return { ma: nulls(kernel(values, int(s, 'length', 9),
      typeof source === 'string' ? undefined : { missing: 'propagate' })) };
  };
  return withTail({
    id,
    name,
    category: 'Trend',
    placement: 'onchart',
    inputs: [
      { key: 'length', type: 'number', label: 'Length', default: 9, min: 1, max: 1000, step: 1 },
      { key: 'source', type: 'source', label: 'Source', default: 'close', allowStudyOutputs: true },
      { key: 'color', type: 'color', label: 'Color', default: color },
    ],
    plots: [{ key: 'ma', type: 'line', title: name, colorKey: 'color', style: { color, lineWidth: 1.5 } }],
    calc,
  }, (own) => (recursive ? emaTail(own) : windowAverageTail(own, kernel)));
}

/**
 * A price source reruns `calc` over the last window. A study output cannot go
 * through `calc` on a slice, since its resolver hands back the whole column,
 * so the kernel reruns over that column's last window instead.
 */
function windowAverageTail(calc: Calc, kernel: Kernel): Tail {
  const byBars = windowTail(calc, (s) => {
    const length = int(s, 'length', 9);
    return whole(length) ? length - 1 : null;
  });
  return (bars, s, from, previous, store, ctx) => {
    const source = src(s) as IndicatorSource | IndicatorStudySource;
    if (typeof source === 'string') return byBars(bars, s, from, previous, store, ctx);
    const length = int(s, 'length', 9);
    const claim = claimOf(store, calc, bars, from);
    const column = claim === undefined ? undefined : ctx?.resolveSource?.(source);
    if (claim === undefined || !whole(length) || !Array.isArray(column) || column.length !== bars.length) return null;
    const start = Math.max(0, from - length);
    const values = column.slice(start).map(value => value ?? NaN);
    return settle(claim, { ma: nulls(kernel(values, length, { missing: 'propagate' })) }, from - start, previous, from);
  };
}

/** The exponential average resumes its running value, over a price or over a study output. */
function emaTail(calc: Calc): Tail {
  return (bars, s, from, previous, store, ctx) => {
    const length = int(s, 'length', 9);
    if (!whole(length)) return null;
    const source = src(s) as IndicatorSource | IndicatorStudySource;
    if (typeof source === 'string') {
      return machineTail(calc, `${length}|${source}`, {
        keys: ['ma'],
        start: seeded,
        step: (st, i, row) => { row[0] = cell(smooth(st, sourceValue(bars[i]!, source), length, true)); },
      }, bars, from, previous, store);
    }
    if (claimOf(store, calc, bars, from) === undefined) return null;
    const column = ctx?.resolveSource?.(source);
    if (!Array.isArray(column) || column.length !== bars.length) return null;
    return machineTail(calc, `${length}|${source.instanceId}|${source.plotKey}`, {
      keys: ['ma'],
      start: observed,
      step: (st, i, row) => { row[0] = cell(observedStep(st, column[i] ?? NaN, length)); },
    }, bars, from, previous, store);
  };
}

export const SMA: IndicatorDescriptor = withTimeframe(movingAverage('sma', 'SMA', '#4f8cff', sma, false));
export const WMA: IndicatorDescriptor = withTimeframe(movingAverage('wma', 'WMA', '#ab47bc', wma, false));
// `smaSeededEma`, not the base bundle's `ema`: the plotted EMA has to open where
// the standard definition opens, on the simple mean of the first `length` values
// at index `length - 1`. The base `ema` seeds from bar 0 to match `openalgo.ta`
// and is public API in its own right, so it keeps that behaviour and this
// descriptor stops using it. Every other EMA in the tier already reads this way.
export const EMA: IndicatorDescriptor = withTimeframe(movingAverage('ema', 'EMA', '#f5a623', smaSeededEma, true));

function bollinger(bars: readonly Bar[], s: Readonly<Record<string, unknown>>): Record<string, (number | null)[]> {
  const values = sourceValues(bars, src(s));
  const length = int(s, 'length', 20);
  const mult = num(s, 'stdDev', 2);
  const basis = sma(values, length);
  const dev = stdev(values, length);
  // Both kernels return one value per input, as `zip` needs.
  const upper = zip(basis, dev, (b, d) => b + mult * d);
  const lower = zip(basis, dev, (b, d) => b - mult * d);
  return { upper: nulls(upper), basis: nulls(basis), lower: nulls(lower) };
}

export const BOLLINGER: IndicatorDescriptor = withTimeframe(withTail({
  id: 'bollinger',
  name: 'Bollinger Bands',
  category: 'Volatility',
  placement: 'onchart',
  inputs: [
    { key: 'length', type: 'number', label: 'Length', default: 20, min: 2, max: 1000, step: 1 },
    { key: 'stdDev', type: 'number', label: 'StdDev', default: 2, min: 0.1, max: 10, step: 0.1 },
    { key: 'source', type: 'source', label: 'Source', default: 'close' },
    { key: 'basisColor', type: 'color', label: 'Basis', default: '#f5a623' },
    { key: 'bandColor', type: 'color', label: 'Bands', default: '#4f8cff' },
  ],
  plots: [
    { key: 'upper', type: 'line', title: 'BB Upper', colorKey: 'bandColor', style: { lineWidth: 1 } },
    { key: 'basis', type: 'line', title: 'BB Basis', colorKey: 'basisColor', style: { lineWidth: 1.5 } },
    { key: 'lower', type: 'line', title: 'BB Lower', colorKey: 'bandColor', style: { lineWidth: 1 } },
  ],
  calc: bollinger,
}, (calc) => windowTail(calc, (s) => {
  // The basis and the deviation both read one window of the source.
  const length = int(s, 'length', 20);
  return whole(length) ? length - 1 : null;
})));

/**
 * Which calendar boundary restarts the accumulation. The reference also offers
 * Earnings, Dividends and Splits, which need a corporate-actions feed this
 * layer has no access to, so they are not offered rather than silently wrong.
 */
type VwapAnchor = 'session' | 'week' | 'month' | 'quarter' | 'year' | 'continuous';


/**
 * Per-bar flags for the first bar of each anchor period, on the calendar of
 * `zone`.
 *
 * The week, month, quarter and year tests used to be IST unconditionally, which
 * put a New York month boundary at 18:30 UTC on the last day and restarted the
 * accumulation ninety minutes before the month-end session closed. They follow
 * the chart now, and IST is one zone among them rather than the assumption.
 */
function anchorRestarts(bars: readonly Bar[], anchor: VwapAnchor, zone: string): boolean[] {
  if (anchor === 'continuous') return new Array<boolean>(bars.length).fill(false);
  const times = bars.map((b) => b.time);
  if (anchor === 'session') return sessionStartFlags(times, zone);
  return calendarPeriodFlags(times, periodBoundary(anchor, zone));
}

const HOUR = 3600;
const DAY = 86400;

/**
 * Where the session reading of a history stands (`sessionStartIndices` in the
 * base bundle), summarised so that one appended bar can be judged without
 * reading the history again: the median bar gap and how many gaps sit below and
 * at it, then the session opens and how many of the spans between them are
 * short. Plus the time and restart flag of the last bar.
 */
interface Reading {
  gaps: number; median: number; below: number; equal: number;
  opens: number; short: number; open: number; last: number; flag: boolean;
}

const readable = (r: Reading): boolean => r.median > 0 && r.median < DAY;
const breakGap = (r: Reading): number => Math.max(4 * r.median, 4 * HOUR);
/** Sessions are read from the gaps; otherwise every bar is tested against the calendar. */
const bySession = (r: Reading): boolean => readable(r) && r.opens > 0 && r.short > r.opens >> 1;

/** `times` holds at least one bar: the tail's head always ends at bar `from`. */
function readingOf(times: readonly number[], flag: boolean): Reading {
  const gaps: number[] = [];
  for (let i = 1; i < times.length; i++) if (times[i]! > times[i - 1]!) gaps.push(times[i]! - times[i - 1]!);
  gaps.sort((a, b) => a - b);
  const median = gaps.length === 0 ? 0 : gaps[gaps.length >> 1]!;
  const r: Reading = {
    gaps: gaps.length, median, below: 0, equal: 0, opens: 0, short: 0, open: times[0]!, last: times[times.length - 1]!, flag,
  };
  for (const g of gaps) if (g < median) r.below++; else if (g === median) r.equal++;
  if (readable(r)) {
    for (let i = 1; i < times.length; i++) {
      if (times[i]! - times[i - 1]! < breakGap(r)) continue;
      r.opens++;
      if (times[i]! - r.open <= 36 * HOUR) r.short++;
      r.open = times[i]!;
    }
  }
  return r;
}

/**
 * Take one appended bar into the reading and return its restart flag, or null
 * when the bar would move the reading of the bars before it: a new median gap
 * moves the session threshold for every bar, and a switch between session
 * reading and calendar fallback recasts every flag.
 */
function advance(r: Reading, time: number, anchor: Exclude<VwapAnchor, 'continuous'>, zone: string): boolean | null {
  const before = bySession(r);
  const gap = time - r.last;
  if (gap > 0) {
    if (r.gaps === 0) return null;
    const mid = (r.gaps + 1) >> 1;
    const below = r.below + (gap < r.median ? 1 : 0);
    const equal = r.equal + (gap === r.median ? 1 : 0);
    if (below > mid || mid >= below + equal) return null;
    r.gaps++;
    r.below = below;
    r.equal = equal;
  }
  const opens = readable(r) && gap >= breakGap(r);
  const prevOpen = r.open;
  const prevLast = r.last;
  if (opens) {
    r.opens++;
    if (time - r.open <= 36 * HOUR) r.short++;
    r.open = time;
  }
  if (bySession(r) !== before) return null;
  r.last = time;
  if (anchor === 'session') {
    r.flag = before ? opens : zone === DEFAULT_TIMEZONE ? isNewIstDay(prevLast, time) : isNewZonedDay(prevLast, time, zone);
  } else r.flag = before ? opens && periodBoundary(anchor, zone)(prevOpen, time) : periodBoundary(anchor, zone)(prevLast, time);
  return r.flag;
}

interface VwapState { pv: number; vol: number; pv2: number; reading: Reading | null }

/**
 * VWAP's tail resumes its three running totals. A restart flag depends on the
 * whole history's gaps, so a replaced last bar keeps the flag it had and an
 * appended one is judged against the reading summary; a bar that would recast
 * the history's flags goes back to a full `calc`, as does any offset, which
 * moves the forming bar's value onto an earlier slot.
 */
function vwapTail(calc: Calc): Tail {
  return (bars, s, from, previous, store) => {
    const n = bars.length;
    if (offsetOf(s, 'offset', 0) !== 0 || n - from > 2) return null;
    const source = src(s, 'source', 'hlc3');
    const anchor = str(s, 'anchor', 'session') as VwapAnchor;
    const zone = zoneOf(s);
    const percent = s.calcMode === 'percent';
    const shows = [s.showBand1 !== false, s.showBand2 === true, s.showBand3 === true];
    const mults = [num(s, 'bandMult1', 1), num(s, 'bandMult2', 2), num(s, 'bandMult3', 3)];
    // Restart flags: for a replay, those of the history the held result was
    // computed on, which ends at bar `from`; for the tail, `ready` sets them.
    let flags: boolean[] = [];
    let ahead: boolean[] = [];
    return machineTail(calc, `${anchor}|${source}|${zone}|${percent}|${shows.join()}|${mults.join()}`, {
      keys: ['vwap', 'upper1', 'lower1', 'upper2', 'lower2', 'upper3', 'lower3'],
      // `machineTail` runs these only once `from` indexes a bar, so the head
      // and its flags run through bar `from`.
      start: (): VwapState => {
        const head = from + 1 === n ? bars : bars.slice(0, from + 1);
        flags = anchorRestarts(head, anchor, zone);
        return {
          pv: 0, vol: 0, pv2: 0,
          reading: anchor === 'continuous' ? null : readingOf(head.map((b) => b.time), flags[from]!),
        };
      },
      ready: (st) => {
        const r = st.reading;
        if (r === null || anchor === 'continuous') {
          ahead = [false, false];
          return true;
        }
        if (r.last !== bars[from]!.time) return false;
        // Read before `advance`, which moves the reading on to the appended bar.
        const current = r.flag;
        const appended = n === from + 2 ? advance(r, bars[n - 1]!.time, anchor, zone) : false;
        ahead = [current, appended === true];
        return appended !== null;
      },
      step: (st, i, row) => {
        if (i < from ? flags[i] : ahead[i - from]) { st.pv = 0; st.vol = 0; st.pv2 = 0; }
        const bar = bars[i]!;
        const v = bar.volume ?? 0;
        const x = sourceValue(bar, source);
        let mean = NaN;
        let basis = NaN;
        if (Number.isFinite(x) && Number.isFinite(v)) {
          st.pv += x * v;
          st.pv2 += x * x * v;
          st.vol += v;
          if (st.vol > 0) {
            mean = st.pv / st.vol;
            const variance = Math.max(0, st.pv2 / st.vol - mean * mean);
            basis = percent ? mean * 0.01 : Math.sqrt(variance);
          }
        }
        row[0] = cell(mean);
        const live = Number.isFinite(mean) && Number.isFinite(basis);
        for (let b = 0; b < 3; b++) {
          row[1 + 2 * b] = shows[b] && live ? cell(mean + basis * mults[b]!) : null;
          row[2 + 2 * b] = shows[b] && live ? cell(mean - basis * mults[b]!) : null;
        }
      },
    }, bars, from, previous, store);
  };
}

export const VWAP: IndicatorDescriptor = withTail({
  id: 'vwap',
  name: 'VWAP',
  category: 'Volume',
  placement: 'onchart',
  inputs: [
    {
      key: 'anchor', type: 'select', label: 'Anchor Period', default: 'session',
      options: [
        { label: 'Session', value: 'session' },
        { label: 'Week', value: 'week' },
        { label: 'Month', value: 'month' },
        { label: 'Quarter', value: 'quarter' },
        { label: 'Year', value: 'year' },
        { label: 'Continuous', value: 'continuous' },
      ],
    },
    { key: 'source', type: 'source', label: 'Source', default: 'hlc3' },
    { key: 'offset', type: 'number', label: 'Offset', default: 0, min: -500, max: 500, step: 1 },
    {
      key: 'calcMode', type: 'select', label: 'Bands Calculation Mode', default: 'stdev',
      options: [
        { label: 'Standard Deviation', value: 'stdev' },
        { label: 'Percentage', value: 'percent' },
      ],
      group: 'Bands',
    },
    { key: 'showBand1', type: 'boolean', label: 'Band #1', default: true, group: 'Bands' },
    { key: 'bandMult1', type: 'number', label: 'Bands Multiplier #1', default: 1, min: 0, step: 0.5, group: 'Bands' },
    { key: 'showBand2', type: 'boolean', label: 'Band #2', default: false, group: 'Bands' },
    { key: 'bandMult2', type: 'number', label: 'Bands Multiplier #2', default: 2, min: 0, step: 0.5, group: 'Bands' },
    { key: 'showBand3', type: 'boolean', label: 'Band #3', default: false, group: 'Bands' },
    { key: 'bandMult3', type: 'number', label: 'Bands Multiplier #3', default: 3, min: 0, step: 0.5, group: 'Bands' },
    { key: 'color', type: 'color', label: 'VWAP', default: '#2962ff' },
    { key: 'band1Color', type: 'color', label: 'Band #1', default: '#4caf50', group: 'Bands' },
    { key: 'band2Color', type: 'color', label: 'Band #2', default: '#808000', group: 'Bands' },
    { key: 'band3Color', type: 'color', label: 'Band #3', default: '#00bcd4', group: 'Bands' },
  ],
  plots: [
    { key: 'vwap', type: 'line', title: 'VWAP', colorKey: 'color', style: { lineWidth: 1.5 } },
    { key: 'upper1', type: 'line', title: 'Upper Band #1', colorKey: 'band1Color', style: { lineWidth: 1 } },
    { key: 'lower1', type: 'line', title: 'Lower Band #1', colorKey: 'band1Color', style: { lineWidth: 1 } },
    { key: 'upper2', type: 'line', title: 'Upper Band #2', colorKey: 'band2Color', style: { lineWidth: 1 } },
    { key: 'lower2', type: 'line', title: 'Lower Band #2', colorKey: 'band2Color', style: { lineWidth: 1 } },
    { key: 'upper3', type: 'line', title: 'Upper Band #3', colorKey: 'band3Color', style: { lineWidth: 1 } },
    { key: 'lower3', type: 'line', title: 'Lower Band #3', colorKey: 'band3Color', style: { lineWidth: 1 } },
  ],
  // Each band pair shades between its own two edges. A hidden band's columns are
  // all null, so its fill resolves to nothing without needing a second switch.
  fills: [
    { between: ['upper1', 'lower1'], colorUpKey: 'band1Color', colorDownKey: 'band1Color', opacity: 0.05 },
    { between: ['upper2', 'lower2'], colorUpKey: 'band2Color', colorDownKey: 'band2Color', opacity: 0.05 },
    { between: ['upper3', 'lower3'], colorUpKey: 'band3Color', colorDownKey: 'band3Color', opacity: 0.05 },
  ],
  calc: (bars, s) => {
    const n = bars.length;
    const values = sourceValues(bars, src(s, 'source', 'hlc3'));
    const anchor = str(s, 'anchor', 'session') as VwapAnchor;
    const percentMode = s.calcMode === 'percent';
    const offset = offsetOf(s, 'offset', 0);

    const vwap = new Array<number>(n).fill(NaN);
    // The band half-width in price terms, before the multiplier. Kept as its own
    // column so all three bands share one accumulation pass.
    const basis = new Array<number>(n).fill(NaN);

    // Where the accumulation restarts. A session anchor comes from the bar
    // gaps, not from a calendar: the reference's "session" is the exchange's
    // trading day, and a fixed midnight lands inside it for every exchange but
    // one, restarting VWAP partway through the afternoon. The coarser anchors
    // are calendar tests on the chart's own zone, and they are applied to
    // session opens for the same reason: a New York Friday runs into Saturday
    // on a clock five and a half hours ahead of it.
    const restarts = anchorRestarts(bars, anchor, zoneOf(s));

    let pv = 0;
    let vol = 0;
    let pv2 = 0;
    // `values`, `vwap` and `basis` hold one value per bar.
    for (let i = 0; i < n; i++) {
      if (restarts[i]) { pv = 0; vol = 0; pv2 = 0; }
      const v = bars[i]!.volume ?? 0;
      const x = values[i]!;
      // A missing price or an unusable volume leaves this bar absent and the
      // totals as they were. Adding it in would blank the line and every band
      // until the next restart, which on the continuous anchor is never. An
      // undefined volume is still a bar that traded nothing.
      if (!Number.isFinite(x) || !Number.isFinite(v)) continue;
      pv += x * v;
      pv2 += x * x * v;
      vol += v;
      if (vol <= 0) continue;
      const mean = pv / vol;
      vwap[i] = mean;
      // Volume-weighted variance. Clamped at zero because accumulated rounding
      // can drive an all-but-flat window a hair negative.
      const variance = Math.max(0, pv2 / vol - mean * mean);
      basis[i] = percentMode ? mean * 0.01 : Math.sqrt(variance);
    }

    const band = (show: boolean, mult: number, sign: number): number[] => {
      const out = new Array<number>(n).fill(NaN);
      if (!show) return out;
      for (let i = 0; i < n; i++) {
        if (Number.isFinite(vwap[i]) && Number.isFinite(basis[i])) {
          out[i] = vwap[i]! + sign * basis[i]! * mult;
        }
      }
      return out;
    };
    const b1 = s.showBand1 !== false;
    const b2 = s.showBand2 === true;
    const b3 = s.showBand3 === true;
    const m1 = num(s, 'bandMult1', 1);
    const m2 = num(s, 'bandMult2', 2);
    const m3 = num(s, 'bandMult3', 3);

    return {
      vwap: nulls(shift(vwap, offset)),
      upper1: nulls(shift(band(b1, m1, 1), offset)),
      lower1: nulls(shift(band(b1, m1, -1), offset)),
      upper2: nulls(shift(band(b2, m2, 1), offset)),
      lower2: nulls(shift(band(b2, m2, -1), offset)),
      upper3: nulls(shift(band(b3, m3, 1), offset)),
      lower3: nulls(shift(band(b3, m3, -1), offset)),
    };
  },
}, vwapTail);

export const SUPERTREND: IndicatorDescriptor = withTimeframe(withTail({
  id: 'supertrend',
  name: 'Supertrend',
  category: 'Trend',
  placement: 'onchart',
  inputs: [
    { key: 'period', type: 'number', label: 'ATR Period', default: 10, min: 1, max: 200, step: 1 },
    { key: 'multiplier', type: 'number', label: 'Multiplier', default: 3, min: 0.1, max: 20, step: 0.1 },
    { key: 'upColor', type: 'color', label: 'Uptrend', default: '#26a69a' },
    { key: 'downColor', type: 'color', label: 'Downtrend', default: '#ef5350' },
  ],
  // Two plots so the band changes color at a flip: each carries null while the
  // other is active, and the line renderer breaks across the gap.
  plots: [
    { key: 'up', type: 'line', title: 'Supertrend Up', colorKey: 'upColor', style: { lineWidth: 2 } },
    { key: 'down', type: 'line', title: 'Supertrend Down', colorKey: 'downColor', style: { lineWidth: 2 } },
  ],
  /**
   * The reference shades the gap between the stop and the candle bodies, using a
   * hidden body-middle plot as the far edge. `bodyMid` is that edge: a value
   * column with no plot of its own, so the band has something to fill against
   * without drawing a second line through the candles.
   *
   * Only one side is live at a time, so the inactive side's fill resolves to
   * nothing and the shading recolours at the flip along with the stop.
   */
  fills: [
    { between: ['bodyMid', 'up'], colorUpKey: 'upColor', colorDownKey: 'upColor', opacity: 0.1 },
    { between: ['bodyMid', 'down'], colorUpKey: 'downColor', colorDownKey: 'downColor', opacity: 0.1 },
  ],
  calc: (bars, s) => {
    const st = supertrend(bars, int(s, 'period', 10), num(s, 'multiplier', 3));
    const up: (number | null)[] = [];
    const down: (number | null)[] = [];
    const bodyMid: (number | null)[] = [];
    for (let i = 0; i < st.length; i++) {
      const p = st[i]!;
      const live = Number.isFinite(p.value);
      up.push(live && p.direction === -1 ? p.value : null);
      down.push(live && p.direction === 1 ? p.value : null);
      // Null wherever the stop is, so the shaded region starts where the line
      // does rather than running back through the warmup.
      const bar = bars[i];
      bodyMid.push(live && bar !== undefined ? (bar.open + bar.close) / 2 : null);
    }
    return { up, down, bodyMid };
  },
}, (calc) => (bars, s, from, previous, store) => {
  const period = int(s, 'period', 10);
  const multiplier = num(s, 'multiplier', 3);
  if (!whole(period)) return null;
  const turn: { direction: -1 | 1 } = { direction: 1 };
  return machineTail(calc, `${period}|${multiplier}`, {
    keys: ['up', 'down', 'bodyMid'],
    start: supertrendState,
    step: (st, i, row) => {
      const value = supertrendStep(st, bars, i, period, multiplier, turn);
      const live = Number.isFinite(value);
      const bar = bars[i];
      row[0] = live && turn.direction === -1 ? value : null;
      row[1] = live && turn.direction === 1 ? value : null;
      row[2] = live && bar !== undefined ? (bar.open + bar.close) / 2 : null;
    },
  }, bars, from, previous, store);
}));

export const PARABOLIC_SAR: IndicatorDescriptor = withTimeframe(withTail({
  id: 'parabolic-sar',
  name: 'Parabolic SAR',
  category: 'Trend',
  placement: 'onchart',
  inputs: [
    { key: 'start', type: 'number', label: 'Start', default: 0.02, min: 0.001, max: 1, step: 0.001 },
    { key: 'increment', type: 'number', label: 'Increment', default: 0.02, min: 0.001, max: 1, step: 0.001 },
    { key: 'maximum', type: 'number', label: 'Maximum', default: 0.2, min: 0.01, max: 1, step: 0.01 },
    { key: 'color', type: 'color', label: 'Color', default: '#e0b020' },
  ],
  plots: [{
    key: 'sar', type: 'line', title: 'SAR', colorKey: 'color',
    style: { markersOnly: true, markerRadius: 1.5 },
  }],
  calc: (bars, s) => {
    const n = bars.length;
    const out = new Array<number>(n).fill(NaN);
    const step = num(s, 'start', 0.02);
    const inc = num(s, 'increment', 0.02);
    const max = num(s, 'maximum', 0.2);

    // Only complete bars take part. A bar missing its high, low or close is a
    // gap that leaves the stop, trend and acceleration as they were: it cannot
    // seed, and the clamp reads the two complete bars before this one, so one
    // hole cannot turn the stop NaN for the rest of the history.
    let prev: Bar | undefined;
    let prev2: Bar | undefined;
    let rising = false;
    let sar = NaN;
    let ep = NaN;
    let af = step;

    for (let i = 0; i < n; i++) {
      const bar = bars[i]!;
      if (!Number.isFinite(bar.high) || !Number.isFinite(bar.low) || !Number.isFinite(bar.close)) continue;
      if (prev === undefined) { prev = bar; continue; }
      if (prev2 === undefined) {
        rising = bar.close >= prev.close;
        sar = rising ? prev.low : prev.high;
        ep = rising ? bar.high : bar.low;
        // The seed bar carries the seed itself. Accelerating and testing for a
        // reversal on it uses an extreme point taken from that same bar, which can
        // flip the trend before a single step has been walked.
        out[i] = sar;
        prev2 = prev;
        prev = bar;
        continue;
      }

      sar += af * (ep - sar);

      // The reversal is decided on the propagated stop, before the clamp below:
      // a stop pulled back inside the prior two bars can no longer be breached,
      // so clamping first swallows flips the definition does fire. On a reversal
      // the stop is the ending trend's extreme, and that extreme includes this
      // bar: a stop left inside the bar that triggered it is already breached
      // the moment it is plotted.
      if (rising && bar.low < sar) {
        rising = false; sar = Math.max(ep, bar.high); ep = bar.low; af = step;
      } else if (!rising && bar.high > sar) {
        rising = true; sar = Math.min(ep, bar.low); ep = bar.high; af = step;
      } else if (rising && bar.high > ep) {
        ep = bar.high; af = Math.min(max, af + inc);
      } else if (!rising && bar.low < ep) {
        ep = bar.low; af = Math.min(max, af + inc);
      }

      // SAR may not penetrate the prior two bars' range, on whichever side the
      // trend now runs. Applied last so a reversal stop is contained too.
      if (rising) sar = Math.min(sar, prev.low, prev2.low);
      else sar = Math.max(sar, prev.high, prev2.high);

      out[i] = sar;
      prev2 = prev;
      prev = bar;
    }
    return { sar: nulls(out) };
  },
}, (calc) => (bars, s, from, previous, store) => {
  const start = num(s, 'start', 0.02);
  const inc = num(s, 'increment', 0.02);
  const max = num(s, 'maximum', 0.2);
  return machineTail(calc, `${start}|${inc}|${max}`, {
    keys: ['sar'],
    start: () => sarState(start),
    step: (st, i, row) => { row[0] = cell(sarStep(st, bars[i]!, start, inc, max)); },
  }, bars, from, previous, store);
}));

export const ICHIMOKU: IndicatorDescriptor = {
  id: 'ichimoku',
  name: 'Ichimoku Cloud',
  category: 'Trend',
  placement: 'onchart',
  inputs: [
    { key: 'conversionPeriod', type: 'number', label: 'Conversion', default: 9, min: 1, max: 200, step: 1 },
    { key: 'basePeriod', type: 'number', label: 'Base', default: 26, min: 1, max: 200, step: 1 },
    { key: 'laggingSpanPeriod', type: 'number', label: 'Lagging Span', default: 52, min: 1, max: 400, step: 1 },
    { key: 'displacement', type: 'number', label: 'Displacement', default: 26, min: 0, max: 200, step: 1 },
    { key: 'conversionColor', type: 'color', label: 'Conversion', default: '#4f8cff' },
    { key: 'baseColor', type: 'color', label: 'Base', default: '#ef5350' },
    { key: 'spanAColor', type: 'color', label: 'Span A', default: '#26a69a' },
    { key: 'spanBColor', type: 'color', label: 'Span B', default: '#ab47bc' },
    { key: 'laggingColor', type: 'color', label: 'Lagging', default: '#8892a6' },
    { key: 'cloudUpColor', type: 'color', label: 'Cloud up', default: '#26a69a' },
    { key: 'cloudDownColor', type: 'color', label: 'Cloud down', default: '#ef5350' },
  ],
  plots: [
    { key: 'conversion', type: 'line', title: 'Tenkan-sen', colorKey: 'conversionColor', style: { lineWidth: 1 } },
    { key: 'base', type: 'line', title: 'Kijun-sen', colorKey: 'baseColor', style: { lineWidth: 1 } },
    { key: 'spanA', type: 'line', title: 'Senkou Span A', colorKey: 'spanAColor', style: { lineWidth: 1 } },
    { key: 'spanB', type: 'line', title: 'Senkou Span B', colorKey: 'spanBColor', style: { lineWidth: 1 } },
    { key: 'lagging', type: 'line', title: 'Chikou Span', colorKey: 'laggingColor', style: { lineWidth: 1 } },
  ],
  // The Kumo. Two lines are not the same picture as a filled cloud: the shading
  // is what makes "price is above the cloud" and "the cloud flipped" readable,
  // and which span leads is itself the signal, hence the two colours.
  fills: [{
    between: ['spanA', 'spanB'],
    colorUpKey: 'cloudUpColor',
    colorDownKey: 'cloudDownColor',
    opacity: 0.14,
  }],
  calc: (bars, s) => {
    const n = bars.length;
    // Whole bars, the way every built-in reads a length (./settings): `mid` indexes
    // bars with the period, so a fractional one read a bar that does not exist
    // and threw, and a fractional displacement found nothing to copy.
    const conv = int(s, 'conversionPeriod', 9);
    const base = int(s, 'basePeriod', 26);
    const lag = int(s, 'laggingSpanPeriod', 52);
    const disp = offsetOf(s, 'displacement', 26);

    // Donchian midpoint over `p` bars, a whole period of one or more, so the
    // window [i - p + 1, i] lies inside the bars.
    const mid = (p: number): number[] => {
      const out = new Array<number>(n).fill(NaN);
      for (let i = p - 1; i < n; i++) {
        let hi = -Infinity;
        let lo = Infinity;
        for (let k = 0; k < p; k++) {
          const bar = bars[i - k]!;
          if (bar.high > hi) hi = bar.high;
          if (bar.low < lo) lo = bar.low;
        }
        out[i] = (hi + lo) / 2;
      }
      return out;
    };

    const conversion = mid(conv);
    const baseLine = mid(base);
    const spanA = zip(conversion, baseLine, (c, b) => (c + b) / 2);
    const spanB = mid(lag);
    const closes = bars.map((b) => b.close);
    return {
      conversion: nulls(conversion),
      base: nulls(baseLine),
      spanA: nulls(shift(spanA, disp)),
      spanB: nulls(shift(spanB, disp)),
      lagging: nulls(shift(closes, -disp)),
    };
  },
};

/**
 * HalfTrend: a trend-following level that only moves against the trend once
 * the opposing side of the range genuinely gives way, so it holds flat through
 * noise where a moving average would wobble.
 *
 * Two state machines run at once. `trend` is what is drawn; `nextTrend` is which
 * flip is currently *armed*. While a down-flip is armed the indicator tracks the
 * running maximum of the `amplitude`-bar low; the flip only fires when the mean
 * high drops under that maximum **and** the bar closes below the previous bar's
 * low. The up-flip is the mirror. Requiring both a mean crossing and a close
 * beyond the prior bar's extreme is what keeps the level still.
 *
 * On a flip the new level starts from the level the other side ended on, which
 * is why the line steps rather than jumping to price. `channelDeviation` half-ATR
 * bands ride the level as a channel, and the flip bar is marked half an ATR
 * inside the channel.
 *
 * Original implementation written from the algorithm's published behaviour, per
 * ARCHITECTURE.md §0.1, not ported from any third-party source.
 */
export const HALFTREND: IndicatorDescriptor = {
  id: 'halftrend',
  name: 'HalfTrend',
  category: 'Trend',
  placement: 'onchart',
  inputs: [
    { key: 'amplitude', type: 'number', label: 'Amplitude', default: 2, min: 1, max: 100, step: 1 },
    { key: 'channelDeviation', type: 'number', label: 'Channel Deviation', default: 2, min: 0, max: 20, step: 0.1 },
    { key: 'atrPeriod', type: 'number', label: 'ATR Period', default: 100, min: 1, max: 500, step: 1 },
    { key: 'showChannels', type: 'boolean', label: 'Show Channels', default: true },
    { key: 'showSignals', type: 'boolean', label: 'Show Signals', default: true },
    { key: 'showLabels', type: 'boolean', label: 'Show Buy/Sell Labels', default: true },
    { key: 'upColor', type: 'color', label: 'Uptrend', default: '#2962ff' },
    { key: 'downColor', type: 'color', label: 'Downtrend', default: '#ef5350' },
  ],
  // The level is split across two plots so it recolours at a flip, exactly as
  // Supertrend does: each carries null while the other is active and the line
  // renderer breaks across the gap.
  plots: [
    { key: 'up', type: 'line', title: 'HalfTrend Up', colorKey: 'upColor', style: { lineWidth: 2 } },
    { key: 'down', type: 'line', title: 'HalfTrend Down', colorKey: 'downColor', style: { lineWidth: 2 } },
    {
      key: 'atrHigh', type: 'line', title: 'Channel High', colorKey: 'downColor',
      style: { markersOnly: true, markerRadius: 1 },
    },
    {
      key: 'atrLow', type: 'line', title: 'Channel Low', colorKey: 'upColor',
      style: { markersOnly: true, markerRadius: 1 },
    },
    {
      key: 'buySignal', type: 'line', title: 'Buy', colorKey: 'upColor',
      style: { markersOnly: true, markerRadius: 3.5 },
    },
    {
      key: 'sellSignal', type: 'line', title: 'Sell', colorKey: 'downColor',
      style: { markersOnly: true, markerRadius: 3.5 },
    },
  ],
  // One ribbon per side. Both endpoints must be non-null for a fill to appear,
  // and only the active side's level is non-null, so the tint follows the trend
  // without any per-bar colour logic.
  fills: [
    { between: ['up', 'atrLow'], colorUpKey: 'upColor', colorDownKey: 'upColor', opacity: 0.15 },
    { between: ['down', 'atrHigh'], colorUpKey: 'downColor', colorDownKey: 'downColor', opacity: 0.15 },
  ],
  // The flip is an event with a name, not a column of prices, so it is a
  // marker rather than a plot. The plate hangs off the channel edge it belongs
  // to, tail pointing at it, which is why buy is a labelUp and sell a labelDown.
  markers: ({ bars, values, settings }) => {
    if (settings.showLabels === false) return [];
    const buy = values.buySignal ?? [];
    const sell = values.sellSignal ?? [];
    const out = [];
    for (let i = 0; i < bars.length; i++) {
      const b = buy[i];
      if (b !== null && b !== undefined) {
        out.push({
          time: bars[i]!.time, position: 'atPrice' as const, price: b,
          shape: 'labelUp' as const, size: 'small' as const,
          color: str(settings, 'upColor', '#2962ff'), text: 'Buy',
        });
        continue;
      }
      const sg = sell[i];
      if (sg !== null && sg !== undefined) {
        out.push({
          time: bars[i]!.time, position: 'atPrice' as const, price: sg,
          shape: 'labelDown' as const, size: 'small' as const,
          color: str(settings, 'downColor', '#ef5350'), text: 'Sell',
        });
      }
    }
    return out;
  },
  calc: (bars, s) => {
    const n = bars.length;
    const up: (number | null)[] = new Array(n).fill(null);
    const down: (number | null)[] = new Array(n).fill(null);
    const chHigh: (number | null)[] = new Array(n).fill(null);
    const chLow: (number | null)[] = new Array(n).fill(null);
    const buy: (number | null)[] = new Array(n).fill(null);
    const sell: (number | null)[] = new Array(n).fill(null);
    const out = { up, down, atrHigh: chHigh, atrLow: chLow, buySignal: buy, sellSignal: sell };
    if (n === 0) return out;

    const amp = int(s, 'amplitude', 2);
    const chDev = num(s, 'channelDeviation', 2);
    const showChannels = s.showChannels !== false;
    const showSignals = s.showSignals !== false;

    const highs = bars.map((b) => b.high);
    const lows = bars.map((b) => b.low);
    const halfAtr = atr(highs, lows, bars.map((b) => b.close), int(s, 'atrPeriod', 100));
    const meanHigh = sma(highs, amp);
    const meanLow = sma(lows, amp);
    const rollHigh = highest(highs, amp);
    const rollLow = lowest(lows, amp);

    // 0 = uptrend, 1 = downtrend. `armed` is the flip currently being tracked.
    // Every series here has one value per bar, and there is at least one bar.
    let trend = 0;
    let armed = 0;
    let maxLow = lows[0]!;
    let minHigh = highs[0]!;
    let upLevel = 0;
    let downLevel = 0;
    let seeded = false;

    for (let i = 0; i < n; i++) {
      const half = halfAtr[i]! / 2;
      const dev = chDev * half;
      const barHigh = rollHigh[i]!;
      const barLow = rollLow[i]!;
      // Bar 0 has no predecessor; comparing against itself can never satisfy the
      // flip condition, which is the correct no-signal answer for a single bar.
      const prevHigh = i > 0 ? highs[i - 1]! : highs[0]!;
      const prevLow = i > 0 ? lows[i - 1]! : lows[0]!;
      const wasTrend = seeded ? trend : -1;

      if (armed === 1) {
        if (Number.isFinite(barLow)) maxLow = Math.max(barLow, maxLow);
        if (Number.isFinite(meanHigh[i]) && meanHigh[i]! < maxLow && bars[i]!.close < prevLow) {
          trend = 1;
          armed = 0;
          minHigh = barHigh;
        }
      } else {
        if (Number.isFinite(barHigh)) minHigh = Math.min(barHigh, minHigh);
        if (Number.isFinite(meanLow[i]) && meanLow[i]! > minHigh && bars[i]!.close > prevHigh) {
          trend = 0;
          armed = 1;
          maxLow = barLow;
        }
      }

      let level: number;
      if (trend === 0) {
        if (wasTrend === 1) {
          upLevel = downLevel; // step across from where the other side ended
          if (showSignals && Number.isFinite(half)) buy[i] = upLevel - half;
        } else {
          upLevel = wasTrend === -1 ? maxLow : Math.max(maxLow, upLevel);
        }
        level = upLevel;
      } else {
        if (wasTrend === 0) {
          downLevel = upLevel;
          if (showSignals && Number.isFinite(half)) sell[i] = downLevel + half;
        } else {
          downLevel = wasTrend === -1 ? minHigh : Math.min(minHigh, downLevel);
        }
        level = downLevel;
      }
      seeded = true;

      if (!Number.isFinite(level)) continue;
      if (trend === 0) up[i] = level;
      else down[i] = level;
      // The level needs no ATR, so it starts well before the channel does.
      if (showChannels && Number.isFinite(dev)) {
        chHigh[i] = level + dev;
        chLow[i] = level - dev;
      }
    }
    return out;
  },
};
