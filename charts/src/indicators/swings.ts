/**
 * Built-ins that read where price turned and how far it has ranged: the
 * percent-reversal ZigZag and the 52 week high and low. Part of the lazy
 * `openalgo-charts/indicators` tier.
 *
 * Neither is a value per bar in the usual sense. A ZigZag swing point is only
 * known once price has turned away from it, so the study writes it back onto
 * the bar where it happened, and a 52 week extreme is a calendar window whose
 * length in bars depends on the calendar. Both keep their live tick to the
 * bars that changed (see ./tail): the ZigZag by resuming its walk, the 52 week
 * range by rerunning its window from the bar before the tick.
 */
import { plotStyleKeys, withAlpha, zonedDayIndex } from 'openalgo-charts';
import type {
  Bar, DrawAnchor, IndicatorDescriptor, IndicatorDrawing, IndicatorLineStyle, IndicatorPlot,
} from 'openalgo-charts';
import { withTail, claimOf, resumable, settle, type Cell, type Tail } from './tail';
import { type Settings, num, str, zoneOf } from './settings';

type Calc = IndicatorDescriptor['calc'];

/** A reversal size in percent, positive by construction whatever a settings blob carries. */
const deviationOf = (s: Settings): number => Math.max(0.01, num(s, 'deviation', 5));

/**
 * The walk's state after a bar. While the swing rises its running end is
 * `high` at `highAt`; while it falls, `low` at `lowAt`. Before the first
 * reversal both are open: the highest high and the lowest low so far.
 */
interface Swing { dir: number; high: number; highAt: number; low: number; lowAt: number }

const swingStart = (): Swing => ({ dir: 0, high: NaN, highAt: -1, low: NaN, lowAt: -1 });

/**
 * A move of at least `deviation` percent of `from`, compared as products so
 * that a move of exactly the deviation reverses: 90 * 0.1 is not 9 in binary.
 * A move of nothing never reverses, even from a zero extreme.
 */
const reverses = (move: number, from: number, deviation: number): boolean =>
  move > 0 && 100 * move >= Math.abs(from) * deviation;

/** Advance the walk over one bar, writing each swing point it places or clears. */
function swingStep(st: Swing, bar: Bar, i: number, deviation: number, write: (index: number, value: Cell) => void): void {
  const h = bar.high;
  const l = bar.low;
  if (!Number.isFinite(h) || !Number.isFinite(l)) return;
  if (st.dir === 0) {
    if (!(h <= st.high)) { st.high = h; st.highAt = i; }
    if (!(l >= st.low)) { st.low = l; st.lowAt = i; }
    // One bar holding both extremes says nothing about which came first.
    if (st.highAt === st.lowAt) return;
    const rising = st.lowAt < st.highAt;
    if (!reverses(st.high - st.low, rising ? st.low : st.high, deviation)) return;
    st.dir = rising ? 1 : -1;
    write(st.lowAt, st.low);
    write(st.highAt, st.high);
  } else if (st.dir > 0) {
    // A new extreme wins over a reversal on the same bar: its high came with it.
    if (h > st.high) {
      write(st.highAt, null);
      st.high = h; st.highAt = i;
      write(i, h);
    } else if (reverses(st.high - l, st.high, deviation)) {
      st.dir = -1; st.low = l; st.lowAt = i;
      write(i, l);
    }
  } else if (l < st.low) {
    write(st.lowAt, null);
    st.low = l; st.lowAt = i;
    write(i, l);
  } else if (reverses(h - st.low, st.low, deviation)) {
    st.dir = 1; st.high = h; st.highAt = i;
    write(i, h);
  }
}

const ZIGZAG_PLOT: IndicatorPlot = {
  key: 'zigzag', type: 'line', title: 'ZigZag', colorKey: 'color', style: { color: '#2962ff', lineWidth: 2 },
};

const zigzagCalc: Calc = (bars, s) => {
  const out = new Array<Cell>(bars.length).fill(null);
  const deviation = deviationOf(s);
  const st = swingStart();
  const write = (j: number, v: Cell): void => { out[j] = v; };
  for (let i = 0; i < bars.length; i++) swingStep(st, bars[i]!, i, deviation, write);
  return { zigzag: out };
};

const skip = (): void => {};

/**
 * The walk resumed at the bar before `from`. The only bars before the tail it
 * can still rewrite are the ones its state leaves open: the running end of the
 * last leg, or both running extremes before the first reversal. When a tick
 * leaves one of those different from what the held result shows (the first
 * tick of a bar that extends the leg clears the bar the leg used to end on, and
 * a correction can put it back), the tail declines and the full `calc` runs.
 * That is not a disagreement: the study revised its own past, as it does.
 */
function zigzagTail(calc: Calc): Tail {
  return (bars, s, from, previous, store) => {
    const claim = claimOf(store, calc, bars, from);
    const held = previous.zigzag;
    if (claim === undefined || held === undefined || held.length < from) return null;
    const deviation = deviationOf(s);
    const key = `${deviation}`;
    const at = resumable(claim, key, bars, from);
    const st = at !== undefined ? { ...(at.state as Swing) } : swingStart();
    // `from` has passed `claimOf`, so every index walked here is a bar.
    if (at === undefined) for (let i = 0; i < from; i++) swingStep(st, bars[i]!, i, deviation, skip);
    // What each open bar holds now: the running end is drawn, the extremes
    // before the first reversal are not yet.
    const open = new Map<number, Cell>();
    if (st.dir >= 0 && st.highAt >= 0) open.set(st.highAt, st.dir === 0 ? null : st.high);
    if (st.dir <= 0 && st.lowAt >= 0) open.set(st.lowAt, st.dir === 0 ? null : st.low);
    const n = bars.length;
    const out = new Array<Cell>(n - from).fill(null);
    const write = (j: number, v: Cell): void => {
      if (j >= from) out[j - from] = v;
      else open.set(j, v);
    };
    for (let i = from; i < n; i++) {
      if (i === n - 1) claim.at = { key, index: i - 1, time: i > 0 ? bars[i - 1]!.time : NaN, state: { ...st }, row: [] };
      swingStep(st, bars[i]!, i, deviation, write);
    }
    for (const [j, v] of open) if (!Object.is(held[j] ?? null, v)) return null;
    claim.misses = 0;
    return { zigzag: out };
  };
}

const LINE_STYLES: readonly IndicatorLineStyle[] = ['solid', 'dashed', 'dotted'];

/**
 * ZigZag: the swings that are left once every move smaller than `deviation`
 * percent is filtered out. The percent-reversal definition:
 *
 * - While a swing rises, its end is the highest high since it began. A bar
 *   whose low is at least `deviation` percent below that high confirms the high
 *   as a swing point and starts a falling swing at the bar's low. A falling
 *   swing is the mirror image. A bar that makes a new extreme extends the swing
 *   even when its other end would also have reversed it, and a tie keeps the
 *   earlier bar.
 * - Before the first reversal the highest high and the lowest low since the
 *   first bar are both open, and the first time they lie `deviation` percent
 *   apart, the earlier of the two becomes the first swing point.
 *
 * `zigzag` holds each swing point's price on its own bar, the running end of
 * the last leg included, and nothing elsewhere; the legs are drawn between
 * them, the last one dashed. Only the last leg ever repaints. On a live tick
 * that makes a new extreme its end moves onto the forming bar and the bar it
 * left reads empty again; a tick that retraces by `deviation` confirms the end
 * and starts a new last leg on the forming bar; a corrected bar can move the
 * end back. Confirmed swing points never move, and `calcTail` returns exactly
 * what a full `calc` of the same bars does (see `zigzagTail`).
 *
 * The legs are shapes, not a plot, so a leg is straight on a logarithmic scale
 * too, and they take their colour, opacity, thickness and line style from the
 * plot's own style settings.
 */
export const ZIGZAG: IndicatorDescriptor = withTail({
  id: 'zigzag',
  name: 'ZigZag',
  category: 'Trend',
  placement: 'onchart',
  inputs: [
    { key: 'deviation', type: 'number', label: 'Deviation (%)', default: 5, min: 0.01, max: 100, step: 0.1 },
    { key: 'color', type: 'color', label: 'ZigZag', default: '#2962ff' },
  ],
  plots: [ZIGZAG_PLOT],
  calc: zigzagCalc,
  draws: ({ bars, values, settings }) => {
    const col = values.zigzag ?? [];
    const points: DrawAnchor[] = [];
    for (let i = 0; i < bars.length; i++) {
      const v = col[i];
      if (typeof v === 'number' && Number.isFinite(v)) points.push({ time: bars[i]!.time, price: v });
    }
    const keys = plotStyleKeys(ZIGZAG_PLOT);
    const color = str(settings, keys.color, '#2962ff');
    const opacity = num(settings, keys.opacity, 100);
    const width = num(settings, keys.width, 2);
    const chosen = settings[keys.lineStyle];
    const style = LINE_STYLES.includes(chosen as IndicatorLineStyle) ? chosen as IndicatorLineStyle : 'solid';
    const legs: IndicatorDrawing[] = [];
    for (let j = 1; j < points.length; j++) {
      legs.push({
        kind: 'line', from: points[j - 1]!, to: points[j]!,
        color: opacity >= 100 ? color : withAlpha(color, Math.max(0, opacity) / 100),
        lineWidth: width > 0 ? width : 2,
        // The last leg is provisional, so it never shares the style of the
        // confirmed ones.
        lineStyle: j < points.length - 1 ? style : style === 'dashed' ? 'dotted' : 'dashed',
      });
    }
    return legs;
  },
}, zigzagTail);

/** 52 weeks in days. */
const WINDOW_DAYS = 364;

/**
 * The 52 week high and low for bars `[start, n)`. A bar's window is the 364
 * calendar days, in `zone`, ending with its own day. Each extreme comes off a
 * monotonic queue, so the pass is linear in the bars however long the window,
 * and it starts at the first bar of `start`'s window, which is what lets a
 * live tick rerun only that window.
 */
function yearRange(bars: readonly Bar[], zone: string, start: number): { high: Cell[]; low: Cell[] } {
  const n = bars.length;
  const high = new Array<Cell>(n - start).fill(null);
  const low = new Array<Cell>(n - start).fill(null);
  if (n === 0) return { high, low };
  // Every read below is of a bar index: the scans stop at 0 and at n, the
  // queues hold bars from `first` on and are read behind their length, and
  // `days` holds one day for each bar from `first`.
  const dayOf = (j: number): number => zonedDayIndex(bars[j]!.time, zone);
  const opened = dayOf(0);
  // Days only rise, so the bars whose window the history covers are a suffix.
  let begin = n;
  while (begin > start && dayOf(begin - 1) - WINDOW_DAYS >= opened) begin--;
  if (begin === n) return { high, low };
  let first = begin;
  const edge = dayOf(begin) - WINDOW_DAYS;
  while (first > 0 && dayOf(first - 1) > edge) first--;
  const days: number[] = [];
  const highs: number[] = [];
  const lows: number[] = [];
  let hi = 0;
  let lo = 0;
  for (let i = first; i < n; i++) {
    const b = bars[i]!;
    days.push(dayOf(i));
    if (Number.isFinite(b.high)) {
      while (highs.length > hi && bars[highs[highs.length - 1]!]!.high <= b.high) highs.pop();
      highs.push(i);
    }
    if (Number.isFinite(b.low)) {
      while (lows.length > lo && bars[lows[lows.length - 1]!]!.low >= b.low) lows.pop();
      lows.push(i);
    }
    if (i < begin) continue;
    const cut = days[i - first]! - WINDOW_DAYS;
    while (hi < highs.length && days[highs[hi]! - first]! <= cut) hi++;
    while (lo < lows.length && days[lows[lo]! - first]! <= cut) lo++;
    if (hi < highs.length) high[i - start] = bars[highs[hi]!]!.high;
    if (lo < lows.length) low[i - start] = bars[lows[lo]!]!.low;
  }
  return { high, low };
}

/**
 * 52 Week High/Low: the highest high and the lowest low of the 52 weeks ending
 * with each bar, as two step lines.
 *
 * The window is calendar time, not a bar count: the 364 days, counted in the
 * chart's zone, that end on the bar's own day. On daily bars that is the bar
 * and the 52 weeks of sessions before it, so a high made on a Friday leaves the
 * window on the Friday 52 weeks later; on intraday bars it is every bar of
 * those days.
 *
 * The warmup is pinned to the history: a bar prints only once the loaded bars
 * begin before its window's first day, so no bar of the window can be missing.
 * A chart with less than a year loaded therefore draws nothing rather than a
 * shorter range under a 52 week name, and on an intraday chart the study needs
 * a year of that interval's history to start. A bar with no high or low is
 * skipped and costs the window nothing else.
 */
export const HIGH_LOW_52_WEEK: IndicatorDescriptor = withTail({
  id: 'high-low-52-week',
  name: '52 Week High/Low',
  category: 'Trend',
  placement: 'onchart',
  inputs: [
    { key: 'highColor', type: 'color', label: '52W High', default: '#26a69a' },
    { key: 'lowColor', type: 'color', label: '52W Low', default: '#ef5350' },
  ],
  plots: [
    { key: 'high', type: 'step', title: '52W High', colorKey: 'highColor', style: { color: '#26a69a', lineWidth: 1.5 } },
    { key: 'low', type: 'step', title: '52W Low', colorKey: 'lowColor', style: { color: '#ef5350', lineWidth: 1.5 } },
  ],
  calc: (bars, s) => yearRange(bars, zoneOf(s), 0),
}, (calc) => (bars, s, from, previous, store) => {
  const claim = claimOf(store, calc, bars, from);
  if (claim === undefined) return null;
  const start = Math.max(0, from - 1);
  return settle(claim, yearRange(bars, zoneOf(s), start), from - start, previous, from);
});

export const SWING_INDICATORS: readonly IndicatorDescriptor[] = [ZIGZAG, HIGH_LOW_52_WEEK];
