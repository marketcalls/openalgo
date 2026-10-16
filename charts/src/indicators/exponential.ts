/**
 * Built-ins that rest on the seeded exponential average: two averages that
 * take back the lag an EMA carries (ZLEMA by extrapolating the source, VIDYA
 * by letting momentum set its weight), Elder-Ray's reach of the high and the
 * low from one, and the Schaff Trend Cycle, a double stochastic of the spread
 * between two. Part of the lazy `openalgo-charts/indicators` tier.
 *
 * Every EMA here opens where the standard definition opens it, on the simple
 * mean of its first `length` values (`smaSeededEma` in the batch form, `smooth`
 * in ./steppers for a tail). Each study resumes from its state on a live tick
 * (see ./tail), so a tick costs a step, not a pass over the history.
 */
import { sourceValues, sourceValue } from 'openalgo-charts';
import type { Bar, IndicatorDescriptor } from 'openalgo-charts';
import { nulls, smaSeededEma } from './calc';
import { withTail, machineTail, stepAll, cell, type Machine } from './tail';
import { seeded, smooth, type Seeded } from './steppers';
import { withTimeframe } from './timeframe';
import { type Settings, num, int, src } from './settings';
import { zip } from './series';

/** ZLEMA's lag: half the length, rounded down. */
const lagOf = (length: number): number => Math.floor((length - 1) / 2);

/**
 * Zero Lag Exponential Moving Average: an EMA of the source pushed ahead by its
 * own change over half the length, so most of the lag an EMA carries on a trend
 * is taken back out.
 *
 *   lag   = floor((length - 1) / 2)
 *   data  = source + (source - source[lag])
 *   zlema = ema(data, length)
 *
 * `data` has no value for the first `lag` bars, so the EMA's first full window
 * ends at `lag + length - 1`: bar 28 at the default length of 20. On a straight
 * ramp with an odd length the line sits on the source exactly, which is the lag
 * it exists to remove.
 */
export const ZLEMA: IndicatorDescriptor = withTimeframe(withTail({
  id: 'zlema',
  name: 'Zero Lag EMA',
  category: 'Trend',
  placement: 'onchart',
  inputs: [
    { key: 'length', type: 'number', label: 'Length', default: 20, min: 1, max: 1000, step: 1 },
    { key: 'source', type: 'source', label: 'Source', default: 'close' },
    { key: 'color', type: 'color', label: 'ZLEMA', default: '#00bcd4' },
  ],
  plots: [{ key: 'zlema', type: 'line', title: 'ZLEMA', colorKey: 'color', style: { color: '#00bcd4', lineWidth: 1.5 } }],
  calc: (bars, s) => {
    const length = int(s, 'length', 20);
    const lag = lagOf(length);
    const values = sourceValues(bars, src(s));
    // `lag` is a whole number of bars, read only once `i` has passed it.
    const data = values.map((x, i) => (i >= lag ? x + (x - values[i - lag]!) : NaN));
    return { zlema: nulls(smaSeededEma(data, length)) };
  },
}, (calc) => (bars, s, from, previous, store) => {
  const length = int(s, 'length', 20);
  const lag = lagOf(length);
  const source = src(s);
  return machineTail(calc, `${length}|${source}`, {
    keys: ['zlema'],
    start: seeded,
    step: (st, i, row) => {
      const x = sourceValue(bars[i]!, source);
      row[0] = cell(smooth(st, i >= lag ? x + (x - sourceValue(bars[i - lag]!, source)) : NaN, length, true));
    },
  }, bars, from, previous, store);
}));

/**
 * The share of the last `length` one-bar changes that went one way, the
 * Chande momentum oscillator's magnitude as a fraction:
 * `|up - down| / (up + down)`. A window that did not move at all has no
 * momentum, 0, rather than the 0/0 the ratio would give. A missing change, or
 * a sum that overflows, has no reading.
 */
function momentumShare(at: (j: number) => number, i: number, length: number): number {
  let up = 0;
  let down = 0;
  for (let j = i - length + 1; j <= i; j++) {
    const move = at(j) - at(j - 1);
    if (!Number.isFinite(move)) return NaN;
    if (move >= 0) up += move;
    else down -= move;
  }
  const total = up + down;
  return total === 0 ? 0 : Math.abs(up - down) / total;
}

function vidyaMachine(bars: readonly Bar[], s: Settings): Machine<{ value: number }> {
  const alpha = 2 / (int(s, 'length', 9) + 1);
  const cmoLength = int(s, 'cmoLength', 9);
  const source = src(s);
  // Read at `i` and, once `i` reaches `cmoLength`, back to `i - cmoLength`.
  const at = (j: number): number => sourceValue(bars[j]!, source);
  return {
    keys: ['vidya'],
    start: () => ({ value: NaN }),
    step: (st, i, row) => {
      const x = at(i);
      const weight = i >= cmoLength ? alpha * momentumShare(at, i, cmoLength) : NaN;
      const next = Number.isNaN(st.value) ? x : weight * x + (1 - weight) * st.value;
      // A bar with no reading keeps the average where it stood, so the next
      // complete window resumes from it rather than from a fresh seed.
      if (!Number.isFinite(x) || !Number.isFinite(weight) || !Number.isFinite(next)) { row[0] = null; return; }
      st.value = next;
      row[0] = next;
    },
  };
}

/**
 * Variable Index Dynamic Average: an exponential average whose weight each bar
 * is scaled by how one-sided the recent movement was, so it follows a trend
 * and stands still in a range.
 *
 *   k     = |CMO(source, cmoLength)| / 100
 *   vidya = alpha * k * source + (1 - alpha * k) * vidya[1],  alpha = 2 / (length + 1)
 *
 * The seed is pinned: the line opens on the source itself at bar `cmoLength`,
 * the first bar with `cmoLength` changes behind it, because there is no prior
 * average to carry and starting from zero would drag the line up from the
 * floor of the chart. A window that did not move reads k = 0 and holds the
 * line, and a bar whose window holds a missing value is absent, with the line
 * resuming afterwards from the value it held.
 */
export const VIDYA: IndicatorDescriptor = withTimeframe(withTail({
  id: 'vidya',
  name: 'Variable Index Dynamic Average',
  category: 'Trend',
  placement: 'onchart',
  inputs: [
    { key: 'length', type: 'number', label: 'Length', default: 9, min: 1, max: 1000, step: 1 },
    { key: 'cmoLength', type: 'number', label: 'CMO Length', default: 9, min: 1, max: 1000, step: 1 },
    { key: 'source', type: 'source', label: 'Source', default: 'close' },
    { key: 'color', type: 'color', label: 'VIDYA', default: '#ff9800' },
  ],
  plots: [{ key: 'vidya', type: 'line', title: 'VIDYA', colorKey: 'color', style: { color: '#ff9800', lineWidth: 1.5 } }],
  calc: (bars, s) => stepAll(vidyaMachine(bars, s), bars.length),
}, (calc) => (bars, s, from, previous, store) => machineTail(
  calc, `${int(s, 'length', 9)}|${int(s, 'cmoLength', 9)}|${src(s)}`, vidyaMachine(bars, s), bars, from, previous, store,
)));

/**
 * Elder-Ray: how far buyers pushed the high above the consensus value, and how
 * far sellers pushed the low below it, the consensus being an EMA of the close.
 *
 *   bull = high - ema(close, length)
 *   bear = low  - ema(close, length)
 *
 * Both print from the EMA's first bar, `length - 1`. Bear power never exceeds
 * bull power, since a bar's low never tops its high, so where both are above
 * zero the bull column is the taller and where both are below the bear column
 * is the deeper.
 */
export const ELDER_RAY: IndicatorDescriptor = withTail({
  id: 'elder-ray',
  name: 'Elder-Ray Index',
  category: 'Momentum',
  placement: 'pane',
  inputs: [
    { key: 'length', type: 'number', label: 'Length', default: 13, min: 1, max: 500, step: 1 },
    { key: 'bullColor', type: 'color', label: 'Bull Power', default: '#26a69a' },
    { key: 'bearColor', type: 'color', label: 'Bear Power', default: '#ef5350' },
  ],
  plots: [
    { key: 'bull', type: 'histogram', title: 'Bull Power', colorKey: 'bullColor', style: { color: '#26a69a', base: 0 } },
    { key: 'bear', type: 'histogram', title: 'Bear Power', colorKey: 'bearColor', style: { color: '#ef5350', base: 0 } },
  ],
  calc: (bars, s) => {
    const ema = smaSeededEma(sourceValues(bars, 'close'), int(s, 'length', 13));
    // `ema` holds one value per bar.
    return {
      bull: nulls(zip(bars, ema, (b, e) => b.high - e)),
      bear: nulls(zip(bars, ema, (b, e) => b.low - e)),
    };
  },
  levels: () => [{ price: 0, color: '#787b86', title: 'Zero', dashed: true }],
}, (calc) => (bars, s, from, previous, store) => {
  const length = int(s, 'length', 13);
  return machineTail(calc, `${length}`, {
    keys: ['bull', 'bear'],
    start: seeded,
    step: (st, i, row) => {
      const b = bars[i]!;
      const ema = smooth(st, b.close, length, true);
      row[0] = cell(b.high - ema);
      row[1] = cell(b.low - ema);
    },
  }, bars, from, previous, store);
});

/**
 * One bar of a cycle stochastic: where `x` sits in the range of the last
 * `length` values, 0 to 100. A window holding a missing value has no reading.
 * A window with no range repeats `previous`, the published rule, which is
 * itself absent until a first reading exists; an overflowing range has none.
 */
function cycleStochastic(window: number[], x: number, length: number, previous: number): number {
  window.push(x);
  if (window.length > length) window.shift();
  if (window.length < length) return NaN;
  let lo = Infinity;
  let hi = -Infinity;
  for (const v of window) {
    if (!Number.isFinite(v)) return NaN;
    if (v < lo) lo = v;
    if (v > hi) hi = v;
  }
  const span = hi - lo;
  if (span === 0) return previous;
  return span < Infinity ? (100 * (x - lo)) / span : NaN;
}

interface Stc {
  fast: Seeded; slow: Seeded;
  /** The last `cycle` MACD values and smoothed first stochastics, gaps kept as NaN. */
  macd: number[]; pfs: number[];
  f1: number; pf: number; f2: number; stc: number;
}

function stcMachine(bars: readonly Bar[], s: Settings): Machine<Stc> {
  const fast = int(s, 'fastLength', 23);
  const slow = int(s, 'slowLength', 50);
  const cycle = int(s, 'cycleLength', 10);
  const factor = num(s, 'factor', 0.5);
  const source = src(s);
  return {
    keys: ['stc'],
    start: () => ({ fast: seeded(), slow: seeded(), macd: [], pfs: [], f1: NaN, pf: NaN, f2: NaN, stc: NaN }),
    step: (st, i, row) => {
      const x = sourceValue(bars[i]!, source);
      const macd = smooth(st.fast, x, fast, true) - smooth(st.slow, x, slow, true);
      const f1 = cycleStochastic(st.macd, macd, cycle, st.f1);
      // A bar with no first stochastic leaves pf as it was and puts a gap in
      // the second window, so the gap costs the bars whose windows hold it.
      let pf = NaN;
      if (Number.isFinite(f1)) {
        st.f1 = f1;
        pf = Number.isNaN(st.pf) ? f1 : st.pf + factor * (f1 - st.pf);
        st.pf = pf;
      }
      const f2 = cycleStochastic(st.pfs, pf, cycle, st.f2);
      let stc = NaN;
      if (Number.isFinite(f2)) {
        st.f2 = f2;
        stc = Number.isNaN(st.stc) ? f2 : st.stc + factor * (f2 - st.stc);
        st.stc = stc;
      }
      row[0] = cell(stc);
    },
  };
}

/**
 * Schaff Trend Cycle: the MACD run through a stochastic twice, each pass
 * smoothed, so the trend the MACD measures turns into a cycle that spends its
 * time pinned near 0 or 100 and moves between them quickly.
 *
 *   macd = ema(source, fast) - ema(source, slow)
 *   f1   = 100 * (macd - lowest(macd, cycle)) / (highest(macd, cycle) - lowest(macd, cycle))
 *   pf   = pf[1] + factor * (f1 - pf[1]), seeded on the first f1
 *   f2   = the same stochastic of pf over cycle
 *   stc  = stc[1] + factor * (f2 - stc[1]), seeded on the first f2
 *
 * A window with no range repeats the stochastic's previous reading, and before
 * there is one the bar is absent, so a series that never moves prints nothing.
 * The first value lands at `slow + 2 * cycle - 3`: the MACD's warmup, then one
 * full window for each stochastic, bar 67 at the defaults.
 */
export const SCHAFF_TREND_CYCLE: IndicatorDescriptor = withTail({
  id: 'schaff-trend-cycle',
  name: 'Schaff Trend Cycle',
  category: 'Momentum',
  placement: 'pane',
  inputs: [
    { key: 'fastLength', type: 'number', label: 'Fast Length', default: 23, min: 1, max: 500, step: 1 },
    { key: 'slowLength', type: 'number', label: 'Slow Length', default: 50, min: 1, max: 500, step: 1 },
    { key: 'cycleLength', type: 'number', label: 'Cycle Length', default: 10, min: 1, max: 500, step: 1 },
    { key: 'factor', type: 'number', label: 'Smoothing Factor', default: 0.5, min: 0.01, max: 1, step: 0.01 },
    { key: 'source', type: 'source', label: 'Source', default: 'close' },
    { key: 'color', type: 'color', label: 'STC', default: '#2962ff' },
  ],
  plots: [{ key: 'stc', type: 'line', title: 'STC', colorKey: 'color', style: { color: '#2962ff', lineWidth: 1.5 } }],
  calc: (bars, s) => stepAll(stcMachine(bars, s), bars.length),
  levels: () => [
    { price: 75, color: '#ef5350', title: 'Upper', dashed: true },
    { price: 25, color: '#26a69a', title: 'Lower', dashed: true },
  ],
  range: () => ({ min: 0, max: 100 }),
}, (calc) => (bars, s, from, previous, store) => machineTail(
  calc,
  `${int(s, 'fastLength', 23)}|${int(s, 'slowLength', 50)}|${int(s, 'cycleLength', 10)}|${num(s, 'factor', 0.5)}|${src(s)}`,
  stcMachine(bars, s), bars, from, previous, store,
));

export const EXPONENTIAL_INDICATORS: readonly IndicatorDescriptor[] = [ZLEMA, VIDYA, ELDER_RAY, SCHAFF_TREND_CYCLE];
