/**
 * Built-in oscillators, ported from their published reference definitions.
 * Part of the lazy `openalgo-charts/indicators` tier.
 *
 * These are reproductions, not inspirations: a user who overlays one of these on
 * the same symbol in the reference platform has to see the same numbers, and the same
 * length of warmup gap in front of them. Three reference conventions do most of the
 * work:
 *   - `na` propagates through arithmetic and through every windowed function, so
 *     a study chained onto a warming-up series has nothing to draw until its own
 *     window is full of real values;
 *   - a comparison against `na` is false, which is why `change(src) <= 0` on
 *     bar 0 falls to the *other* branch of its ternary;
 *   - a plot's `offset` is a drawing displacement, not part of the maths.
 *
 * `ema` from the base bundle is deliberately absent from the imports: it seeds
 * from `values[0]`, where the reference `ema` seeds from an SMA of the first
 * `length` values and is `na` before that. `seededEma` below is the reference's
 * own definition, generalised to a source with holes in it, which is what the
 * Relative Volatility Index feeds its two averages.
 */
import { rsi, sourceValues } from 'openalgo-charts';
import type { IndicatorDescriptor } from 'openalgo-charts';
import {
  sma, stdev, highest, lowest, nulls,
  change, roc, rollingSum, swma, stoch, cci,
} from './calc';
import { fromFirstValue, smoothingBlock, smoothingInputs, smoothingPlots, smoothingFill } from './smoothing';
import { withTimeframe } from './timeframe';
import { int, offsetOf, str, src } from './settings';
import { shift, zip } from './series';

/**
 * the reference `ema`, written the way the reference manual defines it:
 *
 *   sum := na(sum[1]) ? sma(src, length) : alpha * src + (1 - alpha) * sum[1]
 *
 * The recursion only starts once an SMA seed exists. `smaSeededEma` in `./calc`
 * cannot stand in for it here: the Relative Volatility Index's
 * `change(src) <= 0 ? 0 : stddev` alternates real zeros with `na` for as long
 * as the standard deviation is still warming up, and before `holdFrom` (the
 * deviation's first reading) a hole knocks the average back to waiting for a
 * fresh seed, exactly as it always has. That is what fixes the first reading,
 * and every value after it, on a complete series at any length (K12 in the
 * numerical audit: the companion language holds a seed made in that warmup).
 *
 * From `holdFrom` on, a hole can only come from a missing close. The average
 * then holds: that bar has no value, and the next present one continues from
 * where the last left off, instead of blanking the study for another
 * `period` bars and printing a fresh-seed value.
 */
function seededEma(values: readonly number[], period: number, holdFrom: number): number[] {
  const n = values.length;
  const out = new Array<number>(n).fill(NaN);
  if (period <= 0) return out;
  // `sma` here is NaN-strict, so it is exactly the "is there a clean window yet"
  // question the reference seed asks.
  const seed = sma(values, period);
  const k = 2 / (period + 1);
  let prev = NaN;
  // `seed` holds one value per input.
  for (let i = 0; i < n; i++) {
    const v = values[i]!;
    if (!Number.isFinite(prev)) {
      prev = seed[i]!;
    } else if (Number.isFinite(v)) {
      prev = v * k + prev * (1 - k);
    } else if (i < holdFrom) {
      prev = NaN;
    } else {
      continue;
    }
    out[i] = prev;
  }
  return out;
}

/**
 * Stochastic RSI: where RSI sits inside its own recent range, which turns a
 * slow-moving oscillator into a fast one.
 *
 * The reference passes `rsi1` in as all three arguments of `stoch`, so the window
 * is the RSI's high and low rather than price's, and every warmup adds to the
 * one before it: 14 bars for the RSI, 14 more before the stochastic window is
 * full of real RSI values, then two SMAs. First `K` lands at index 29 on the
 * defaults and `D` two bars later.
 */
export const STOCHASTIC_RSI: IndicatorDescriptor = withTimeframe({
  id: 'stochastic-rsi',
  name: 'Stochastic RSI',
  category: 'Momentum',
  placement: 'pane',
  inputs: [
    { key: 'smoothK', type: 'number', label: 'K', default: 3, min: 1, max: 100, step: 1 },
    { key: 'smoothD', type: 'number', label: 'D', default: 3, min: 1, max: 100, step: 1 },
    { key: 'lengthRSI', type: 'number', label: 'RSI Length', default: 14, min: 1, max: 500, step: 1 },
    { key: 'lengthStoch', type: 'number', label: 'Stochastic Length', default: 14, min: 1, max: 500, step: 1 },
    { key: 'source', type: 'source', label: 'RSI Source', default: 'close' },
    { key: 'kColor', type: 'color', label: 'K', default: '#2962ff' },
    { key: 'dColor', type: 'color', label: 'D', default: '#ff6d00' },
    { key: 'fillColor', type: 'color', label: 'Background', default: '#2196f3' },
  ],
  plots: [
    { key: 'k', type: 'line', title: 'K', colorKey: 'kColor', style: { lineWidth: 1.5 } },
    { key: 'd', type: 'line', title: 'D', colorKey: 'dColor', style: { lineWidth: 1.5 } },
  ],
  // The 80/20 shading spans two reference lines rather than two series, so its
  // edges are constant columns with no plot of their own. One colour on both
  // sides: a level band has no up or down side to tell apart.
  fills: [{ between: ['bandHigh', 'bandLow'], colorUpKey: 'fillColor', colorDownKey: 'fillColor', opacity: 0.1 }],
  calc: (bars, s) => {
    const lengthStoch = int(s, 'lengthStoch', 14);
    const r = rsi(sourceValues(bars, src(s)), int(s, 'lengthRSI', 14));
    const raw = fromFirstValue(r, (t) => stoch(t, t, t, lengthStoch));
    const k = fromFirstValue(raw, (t) => sma(t, int(s, 'smoothK', 3)));
    const d = fromFirstValue(k, (t) => sma(t, int(s, 'smoothD', 3)));
    // Never null, warmup included: the background covers the whole pane, so its
    // edges have to exist on bars where neither line prints yet.
    return {
      k: nulls(k),
      d: nulls(d),
      bandHigh: new Array<number>(bars.length).fill(80),
      bandLow: new Array<number>(bars.length).fill(20),
    };
  },
  levels: () => [
    { price: 80, color: '#787b86', title: 'Upper Band' },
    // `color.new(#787B86, 50)`: the middle band is deliberately the quiet one.
    { price: 50, color: '#5a6b8c', title: 'Middle Band' },
    { price: 20, color: '#787b86', title: 'Lower Band' },
  ],
  range: () => ({ min: 0, max: 100 }),
});

/**
 * Williams Percent Range: the distance from the window's high down to the
 * close, as a percentage of the window. The sign convention is the whole point:
 * a close at a fresh window high is exactly 0 and one at the window low is
 * exactly -100, so the scale runs -100..0 rather than 0..100.
 *
 * The high and low come from `high` and `low` (the reference single-argument
 * `highest`/`lowest`), while the numerator reads the `source` input, so
 * the three do not have to agree.
 */
export const WILLIAMS_PERCENT_R: IndicatorDescriptor = withTimeframe({
  id: 'williams-percent-r',
  name: 'Williams Percent Range',
  category: 'Momentum',
  placement: 'pane',
  inputs: [
    { key: 'length', type: 'number', label: 'Length', default: 14, min: 1, max: 500, step: 1 },
    { key: 'source', type: 'source', label: 'Source', default: 'close' },
    { key: 'color', type: 'color', label: '%R', default: '#7e57c2' },
    { key: 'fillColor', type: 'color', label: 'Background', default: '#7e57c2' },
  ],
  plots: [{ key: 'percentR', type: 'line', title: '%R', colorKey: 'color', style: { lineWidth: 1.5 } }],
  // Shaded between the -20 and -80 reference lines, not between two series, so
  // the edges are constant columns with no plot. One colour on both sides: a
  // level band has no up or down side to distinguish.
  fills: [{ between: ['bandHigh', 'bandLow'], colorUpKey: 'fillColor', colorDownKey: 'fillColor', opacity: 0.1 }],
  calc: (bars, s) => {
    const length = int(s, 'length', 14);
    const values = sourceValues(bars, src(s));
    const hi = highest(bars.map((b) => b.high), length);
    const lo = lowest(bars.map((b) => b.low), length);
    // Both extremes hold one value per bar.
    const out = values.map((v, i) => {
      const span = hi[i]! - lo[i]!;
      // A window with no range at all is 0/0, which the reference draws as a gap.
      return span === 0 ? NaN : (100 * (v - hi[i]!)) / span;
    });
    // Never null, warmup included: the background is drawn across the pane, so
    // its edges have to exist on bars where the study prints nothing.
    return {
      percentR: nulls(out),
      bandHigh: new Array<number>(bars.length).fill(-20),
      bandLow: new Array<number>(bars.length).fill(-80),
    };
  },
  levels: () => [
    { price: -20, color: '#787b86', title: 'Upper Band' },
    { price: -50, color: '#787b86', title: 'Middle Level', dashed: true },
    { price: -80, color: '#787b86', title: 'Lower Band' },
  ],
  range: () => ({ min: -100, max: 0 }),
});

/**
 * Ultimate Oscillator: buying pressure over true range, measured across three
 * horizons at once and weighted 4:2:1 so the fast window leads without the
 * slower two losing their vote.
 *
 * `high_`/`low_` reach back to the previous close, so bar 0 has no value: the reference
 * `max(high, na)` is `na`, and that bar contributes to neither sum. Summing
 * from bar 1 is what keeps it out: `rollingSum` keeps a running total, and one
 * NaN in a running total never comes back out. With the default 28-bar window
 * the first print is therefore at index 28, not 27.
 */
export const ULTIMATE_OSCILLATOR: IndicatorDescriptor = {
  id: 'ultimate-oscillator',
  name: 'Ultimate Oscillator',
  category: 'Momentum',
  placement: 'pane',
  inputs: [
    { key: 'length1', type: 'number', label: 'Fast Length', default: 7, min: 1, max: 500, step: 1 },
    { key: 'length2', type: 'number', label: 'Middle Length', default: 14, min: 1, max: 500, step: 1 },
    { key: 'length3', type: 'number', label: 'Slow Length', default: 28, min: 1, max: 500, step: 1 },
    { key: 'color', type: 'color', label: 'Oscillator', default: '#f44336' },
  ],
  plots: [{ key: 'uo', type: 'line', title: 'Oscillator', colorKey: 'color', style: { lineWidth: 1.5 } }],
  calc: (bars, s) => {
    const n = bars.length;
    const m = Math.max(0, n - 1);
    const bp = new Array<number>(m);
    const tr = new Array<number>(m);
    // The terms and their averages hold n - 1 values, one per bar from bar 1.
    for (let i = 1; i < n; i++) {
      const prevClose = bars[i - 1]!.close;
      const hi = Math.max(bars[i]!.high, prevClose);
      const lo = Math.min(bars[i]!.low, prevClose);
      bp[i - 1] = bars[i]!.close - lo;
      tr[i - 1] = hi - lo;
    }
    const avg = (length: number): number[] => {
      const sumBp = rollingSum(bp, length);
      const sumTr = rollingSum(tr, length);
      // A run of doji bars sums to zero range, which is `na` rather than 0/0.
      return zip(sumBp, sumTr, (v, tr) => (tr === 0 ? NaN : v / tr));
    };
    const fast = avg(int(s, 'length1', 7));
    const middle = avg(int(s, 'length2', 14));
    const slow = avg(int(s, 'length3', 28));
    const out = new Array<number>(n).fill(NaN);
    for (let i = 0; i < m; i++) {
      out[i + 1] = (100 * (4 * fast[i]! + 2 * middle[i]! + slow[i]!)) / 7;
    }
    return { uo: nulls(out) };
  },
};

/**
 * Relative Vigor Index: the bar's body over its range, on the theory that a
 * rising market closes near its high. Both halves are smoothed by `swma`
 * (the fixed 4-bar 1/2/2/1 kernel) before being summed, so a single wide bar
 * cannot swing the reading on its own.
 *
 * Warmup stacks: 3 bars for the `swma`, `length` more for the sum (index 12 on
 * the defaults), then 3 more for the signal's own `swma`.
 *
 * The reference `offset` input displaces both plots. The library has no per-plot
 * offset, so it is a real shift of the columns instead: see `shifted`.
 */
export const RELATIVE_VIGOR_INDEX: IndicatorDescriptor = {
  id: 'relative-vigor-index',
  name: 'Relative Vigor Index',
  category: 'Momentum',
  placement: 'pane',
  inputs: [
    { key: 'length', type: 'number', label: 'Length', default: 10, min: 1, max: 500, step: 1 },
    { key: 'offset', type: 'number', label: 'Offset', default: 0, min: -500, max: 500, step: 1 },
    { key: 'rvgiColor', type: 'color', label: 'RVGI', default: '#008000' },
    { key: 'signalColor', type: 'color', label: 'Signal', default: '#ff0000' },
  ],
  plots: [
    { key: 'rvgi', type: 'line', title: 'RVGI', colorKey: 'rvgiColor', style: { lineWidth: 1.5 } },
    { key: 'signal', type: 'line', title: 'Signal', colorKey: 'signalColor', style: { lineWidth: 1.5 } },
  ],
  calc: (bars, s) => {
    const length = int(s, 'length', 10);
    const body = swma(bars.map((b) => b.close - b.open));
    const range = swma(bars.map((b) => b.high - b.low));
    const numerator = fromFirstValue(body, (t) => rollingSum(t, length));
    const denominator = fromFirstValue(range, (t) => rollingSum(t, length));
    const rvgi = zip(numerator, denominator, (v, den) => (den === 0 ? NaN : v / den));
    const signal = fromFirstValue(rvgi, (t) => swma(t));
    const offset = offsetOf(s, 'offset', 0);
    return {
      rvgi: nulls(shift(rvgi, offset)),
      signal: nulls(shift(signal, offset)),
    };
  },
};

/**
 * Relative Volatility Index: RSI's arithmetic applied to volatility instead of
 * price: how much of the recent standard deviation arrived on up bars.
 *
 * Two details are easy to get wrong. The `length` input is the standard
 * deviation's window only; the smoothing length is a hard-coded 14 in the reference
 * and stays 14 whatever `length` is set to. And the two smoothed series are not
 * clean: `change(src) <= 0 ? 0 : stddev` yields a real `0` on down bars but
 * `na` on up bars while the standard deviation is still warming up, so the EMA's
 * seed has to wait for a 14-bar window with no holes in it. That makes the first
 * printed bar `length + 12` on a one-way market rather than a fixed index.
 */
export const RELATIVE_VOLATILITY_INDEX: IndicatorDescriptor = {
  id: 'relative-volatility-index',
  name: 'Relative Volatility Index',
  category: 'Volatility',
  placement: 'pane',
  inputs: [
    { key: 'length', type: 'number', label: 'Length', default: 10, min: 1, max: 500, step: 1 },
    { key: 'offset', type: 'number', label: 'Offset', default: 0, min: -500, max: 500, step: 1 },
    { key: 'color', type: 'color', label: 'RVI', default: '#7e57c2' },
    { key: 'fillColor', type: 'color', label: 'Background', default: '#7e57c2' },
    ...smoothingInputs('RVI', 'SMA', 14),
  ],
  plots: [
    { key: 'rvi', type: 'line', title: 'RVI', colorKey: 'color', style: { lineWidth: 1.5 } },
    ...smoothingPlots('RVI'),
  ],
  fills: [
    smoothingFill(),
    // The 80/20 shading spans two reference lines rather than two series, so its
    // edges are constant columns with no plot of their own. One colour on both
    // sides: a level band has no up or down side to tell apart.
    { between: ['bandHigh', 'bandLow'], colorUpKey: 'fillColor', colorDownKey: 'fillColor', opacity: 0.1 },
  ],
  calc: (bars, s) => {
    const n = bars.length;
    // The reference hard-codes `src = close`; only the window is an input.
    const source = bars.map((b) => b.close);
    const sd = stdev(source, int(s, 'length', 10));
    const delta = change(source);
    // Not `length`: the reference `len = 14` is a separate, fixed constant.
    const emaLength = 14;
    const upSource = new Array<number>(n);
    const downSource = new Array<number>(n);
    // Every series here holds one value per bar.
    for (let i = 0; i < n; i++) {
      const d = delta[i]!;
      // Bar 0 has no change, and in the reference both `na <= 0` and `na > 0` are false,
      // so it takes the `stddev` branch of both ternaries, where the value is
      // itself `na`.
      upSource[i] = Number.isFinite(d) && d <= 0 ? 0 : sd[i]!;
      downSource[i] = Number.isFinite(d) && d > 0 ? 0 : sd[i]!;
    }
    // A missing close after the deviation's first reading leaves the sources
    // absent for a stretch; the averages hold across it. Inside the warmup
    // they restart as they always have, so a complete series reads as before.
    let holdFrom = 0;
    while (holdFrom < n && !Number.isFinite(sd[holdFrom])) holdFrom += 1;
    const upper = seededEma(upSource, emaLength, holdFrom);
    const lower = seededEma(downSource, emaLength, holdFrom);
    const rvi = new Array<number>(n).fill(NaN);
    for (let i = 0; i < n; i++) {
      const total = upper[i]! + lower[i]!;
      rvi[i] = total === 0 ? NaN : (upper[i]! / total) * 100;
    }

    return {
      rvi: nulls(shift(rvi, offsetOf(s, 'offset', 0))),
      // The offset moves the RVI line only; the block reads the unshifted
      // values and stays where it is.
      ...smoothingBlock(rvi, bars.map((b) => b.volume ?? 0), s, 'SMA', 14),
      // Never null and never shifted: reference lines stay put when the plot is
      // offset, and the shading covers the pane through the study's warmup.
      bandHigh: new Array<number>(n).fill(80),
      bandLow: new Array<number>(n).fill(20),
    };
  },
  levels: () => [
    { price: 80, color: '#787b86', title: 'Upper Band' },
    { price: 50, color: '#5a6b8c', title: 'Middle Band' },
    { price: 20, color: '#787b86', title: 'Lower Band' },
  ],
};

/**
 * Woodies CCI: a 14-bar CCI drawn twice, as a colour-coded histogram and as a
 * line, with a fast "turbo" CCI over the top. The pair is the method: the turbo
 * line crossing the slow one is the trigger, and the histogram's colour says
 * whether the trend is established enough to take it.
 *
 * The colour is a five-bar state, not a level (`cci14[5] .. cci14[1]` all on
 * one side of zero), so it belongs to `colorBy` rather than to a second plot.
 * Note the fallback branch: with no established run, the reference paints a negative
 * reading teal and a positive one red, which is the opposite of the run colours.
 * That is what the built-in ships, and parity beats tidiness here.
 */
export const WOODIES_CCI: IndicatorDescriptor = {
  id: 'woodies-cci',
  name: 'Woodies CCI',
  category: 'Momentum',
  placement: 'pane',
  inputs: [
    { key: 'cciTurboLength', type: 'number', label: 'CCI Turbo Length', default: 6, min: 3, max: 14, step: 1 },
    { key: 'cci14Length', type: 'number', label: 'CCI 14 Length', default: 14, min: 7, max: 20, step: 1 },
    { key: 'upColor', type: 'color', label: 'Five bars up', default: '#009688' },
    { key: 'downColor', type: 'color', label: 'Five bars down', default: '#f44336' },
    { key: 'turboColor', type: 'color', label: 'CCI Turbo', default: '#009688' },
    { key: 'cciColor', type: 'color', label: 'CCI 14', default: '#f44336' },
  ],
  plots: [
    {
      key: 'hist', type: 'histogram', title: 'CCI Turbo Histogram',
      // `colorKey` is only the fallback a settings UI restyles; `colorBy` wins
      // bar by bar.
      colorKey: 'upColor', style: { base: 0 },
      colorBy: ({ index, values, settings }) => {
        const up = str(settings, 'upColor', '#009688');
        const down = str(settings, 'downColor', '#f44336');
        const at = (back: number): number | null => {
          const v = values.hist?.[index - back];
          return typeof v === 'number' && Number.isFinite(v) ? v : null;
        };
        // the reference compares `na` with `> 0` and `< 0`, and both are false, so a
        // warming-up window establishes neither run.
        let allUp = true;
        let allDown = true;
        for (let back = 1; back <= 5; back += 1) {
          const v = at(back);
          if (v === null || v <= 0) allUp = false;
          if (v === null || v >= 0) allDown = false;
        }
        if (allUp) return up;
        if (allDown) return down;
        const now = at(0);
        return now !== null && now < 0 ? up : down;
      },
    },
    { key: 'turbo', type: 'line', title: 'CCI Turbo', colorKey: 'turboColor', style: { lineWidth: 1.5 } },
    { key: 'cci14', type: 'line', title: 'CCI 14', colorKey: 'cciColor', style: { lineWidth: 1.5 } },
  ],
  calc: (bars, s) => {
    const source = bars.map((b) => b.close);
    const turbo = cci(source, int(s, 'cciTurboLength', 6));
    const slow = cci(source, int(s, 'cci14Length', 14));
    // The histogram and the "CCI 14" line are the same series; the reference plots it
    // twice on purpose, once for the colour and once for the shape.
    return { hist: nulls(slow), turbo: nulls(turbo), cci14: nulls(slow) };
  },
  levels: () => [
    { price: 100, color: '#787b86', title: 'Hundred Line', dashed: true },
    { price: 0, color: '#787b86', title: 'Zero Line' },
    { price: -100, color: '#787b86', title: 'Minus Line', dashed: true },
  ],
};

/**
 * The twelve terms of Pring's Special K, as `weight * sma(roc(src, roc), smooth)`.
 *
 * The reference delegates to a library helper whose body is not in the extracted
 * source, so these are Pring's published lengths and weights rather than a
 * transcription of it. The study is three KSTs added together, which is
 * why the weights run 1/2/3/4 three times over rather than tracking the rate of
 * change lengths. The longest term is what makes the study expensive in history:
 * `roc(530)` smoothed over 195 bars needs 725 bars before it prints anything,
 * and the twice-smoothed signal needs 923.
 */
const SPECIAL_K_TERMS: readonly { weight: number; roc: number; smooth: number }[] = [
  { weight: 1, roc: 10, smooth: 10 },
  { weight: 2, roc: 15, smooth: 10 },
  { weight: 3, roc: 20, smooth: 10 },
  { weight: 4, roc: 30, smooth: 15 },
  { weight: 1, roc: 40, smooth: 50 },
  { weight: 2, roc: 65, smooth: 65 },
  { weight: 3, roc: 75, smooth: 75 },
  { weight: 4, roc: 100, smooth: 100 },
  { weight: 1, roc: 195, smooth: 130 },
  { weight: 2, roc: 265, smooth: 130 },
  { weight: 3, roc: 390, smooth: 130 },
  { weight: 4, roc: 530, smooth: 195 },
];

/**
 * Pring's Special K: twelve rates of change from twelve different horizons, each
 * smoothed and weighted, added into one line. Short-, intermediate- and
 * long-term momentum in a single reading, which is why its turns are read as
 * complete-cycle signals rather than as entries.
 *
 * Every term has to have a value before the sum does, so the slowest one sets
 * the warmup; the reference itself refuses to run on a chart with fewer than 725
 * bars.
 */
export const SPECIAL_K: IndicatorDescriptor = {
  id: 'special-k',
  name: "Pring's Special K",
  category: 'Momentum',
  placement: 'pane',
  inputs: [
    { key: 'source', type: 'source', label: 'Source', default: 'close' },
    { key: 'length1', type: 'number', label: 'Signal length 1', default: 100, min: 1, max: 1000, step: 1 },
    { key: 'length2', type: 'number', label: 'Signal length 2', default: 100, min: 1, max: 1000, step: 1 },
    { key: 'color', type: 'color', label: 'Special K', default: '#2962ff' },
    { key: 'signalColor', type: 'color', label: 'Signal', default: '#ff6d00' },
  ],
  plots: [
    { key: 'specialK', type: 'line', title: 'Special K', colorKey: 'color', style: { lineWidth: 1.5 } },
    { key: 'signal', type: 'line', title: 'Signal', colorKey: 'signalColor', style: { lineWidth: 1.5 } },
  ],
  calc: (bars, s) => {
    const n = bars.length;
    const source = sourceValues(bars, src(s));
    const out = new Array<number>(n).fill(0);
    for (const term of SPECIAL_K_TERMS) {
      const smoothed = fromFirstValue(roc(source, term.roc), (t) => sma(t, term.smooth));
      // NaN in any term makes the total NaN and keeps it there, which is the reference
      // `na` propagation through the sum.
      for (let i = 0; i < n; i++) out[i]! += term.weight * smoothed[i]!;
    }
    const once = fromFirstValue(out, (t) => sma(t, int(s, 'length1', 100)));
    const signal = fromFirstValue(once, (t) => sma(t, int(s, 'length2', 100)));
    return { specialK: nulls(out), signal: nulls(signal) };
  },
  levels: () => [{ price: 0, color: '#787b86', title: 'Zero' }],
};

export const RANGE_INDICATORS: readonly IndicatorDescriptor[] = [
  STOCHASTIC_RSI,
  WILLIAMS_PERCENT_R,
  ULTIMATE_OSCILLATOR,
  RELATIVE_VIGOR_INDEX,
  RELATIVE_VOLATILITY_INDEX,
  WOODIES_CCI,
  SPECIAL_K,
];
