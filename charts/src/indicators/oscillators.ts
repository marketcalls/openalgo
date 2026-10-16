/**
 * Built-in momentum studies, ported from their published
 * sources. Part of the lazy `openalgo-charts/indicators` tier.
 *
 * These are reproductions, not inspirations: a user who overlays one of these
 * on the same symbol in the reference platform has to see the same numbers, including the
 * warmup gap. That constraint is why the reference-compatible helpers in `./calc`
 * exist (`smaSeededEma`, `highestBars`, `percentRank`, ...) and why the base
 * bundle's `ema` is deliberately not used anywhere in this file: it seeds from
 * bar 0 rather than from an SMA, so it disagrees with `ema` for the first
 * `length` bars.
 *
 * Two the reference conventions drive most of the null handling below:
 *   - `na` propagates through arithmetic, so a value derived from a warming-up
 *     series is itself `na` until every input has a value;
 *   - `nz(x)` reads `na` as `0`, which is how the recursive studies (Fisher,
 *     the Connors streak) get their first term.
 */
import { rsi, sourceValues } from 'openalgo-charts';
import type { Bar, IndicatorDescriptor } from 'openalgo-charts';
import {
  sma, wma, highest, lowest, nulls,
  change, roc, percentRank, highestBars, lowestBars, rollingSum,
} from './calc';
import { int, str, src } from './settings';
import { zip } from './series';

const hl2 = (bars: readonly Bar[]): number[] => sourceValues(bars, 'hl2');

/**
 * Aroon: how recently the window made its extreme, as a percentage of the
 * window.
 *
 * `highestbars` answers "how many bars back is the high" as a **negative
 * offset**, `0` meaning the current bar. The whole study is that offset mapped
 * onto 0..100, so the sign convention is load-bearing: a fresh high gives
 * `100 * (0 + length) / length` = exactly 100, and a high at the far edge of
 * the window gives 0. Note the window is `length + 1` bars, not `length`:
 * the reference counts the gaps between bars, not the bars.
 */
export const AROON: IndicatorDescriptor = {
  id: 'aroon',
  name: 'Aroon',
  category: 'Trend',
  placement: 'pane',
  inputs: [
    { key: 'length', type: 'number', label: 'Length', default: 14, min: 1, max: 500, step: 1 },
    { key: 'upColor', type: 'color', label: 'Aroon Up', default: '#fb8c00' },
    { key: 'downColor', type: 'color', label: 'Aroon Down', default: '#2962ff' },
  ],
  plots: [
    { key: 'up', type: 'line', title: 'Aroon Up', colorKey: 'upColor', style: { lineWidth: 1.5 } },
    { key: 'down', type: 'line', title: 'Aroon Down', colorKey: 'downColor', style: { lineWidth: 1.5 } },
  ],
  calc: (bars, s) => {
    const length = int(s, 'length', 14);
    const upBars = highestBars(bars.map((b) => b.high), length + 1);
    const downBars = lowestBars(bars.map((b) => b.low), length + 1);
    const scale = (offsets: readonly number[]): number[] =>
      offsets.map((o) => (100 * (o + length)) / length);
    return { up: nulls(scale(upBars)), down: nulls(scale(downBars)) };
  },
  levels: () => [{ price: 50, color: '#5a6b8c', dashed: true }],
  range: () => ({ min: 0, max: 100 }),
};

/**
 * Aroon Oscillator: Aroon Up minus Aroon Down, so a single line through zero.
 *
 * The reference colours the *line* by sign and shades it to a hidden zero plot. This
 * library's line renderer has no per-bar colour (only histogram and column
 * honour `colorBy`), so the sign is carried by the band instead, which is what
 * actually reads on a chart. `zero` is a value column with no plot, exactly as
 * the reference `display.none` zero plot is: it exists only to give the fill a
 * second edge.
 */
export const AROON_OSCILLATOR: IndicatorDescriptor = {
  id: 'aroon-oscillator',
  name: 'Aroon Oscillator',
  category: 'Trend',
  placement: 'pane',
  inputs: [
    { key: 'length', type: 'number', label: 'Length', default: 14, min: 1, max: 500, step: 1 },
    { key: 'upColor', type: 'color', label: 'Positive', default: '#4caf50' },
    { key: 'downColor', type: 'color', label: 'Negative', default: '#ff5252' },
  ],
  plots: [
    { key: 'osc', type: 'line', title: 'Oscillator', colorKey: 'upColor', style: { lineWidth: 1.5 } },
  ],
  fills: [{ between: ['osc', 'zero'], colorUpKey: 'upColor', colorDownKey: 'downColor', opacity: 0.1 }],
  calc: (bars, s) => {
    const length = int(s, 'length', 14);
    const upBars = highestBars(bars.map((b) => b.high), length + 1);
    const downBars = lowestBars(bars.map((b) => b.low), length + 1);
    // The calc helpers return one value per input, here and below.
    const osc = zip(upBars, downBars, (o, d) => (100 * (o - d)) / length);
    return { osc: nulls(osc), zero: osc.map((v) => (Number.isFinite(v) ? 0 : null)) };
  },
  levels: () => [
    { price: 90, color: '#5a6b8c', title: 'Upper level', dashed: true },
    { price: 0, color: '#787b86' },
    { price: -90, color: '#5a6b8c', title: 'Lower level', dashed: true },
  ],
  range: () => ({ min: -100, max: 100 }),
};

/**
 * Awesome Oscillator: the gap between a fast and a slow midpoint average.
 *
 * The reference hard-codes 5 and 34 and exposes no inputs, so neither does this: the
 * two periods are the definition of the study, not a preference. Colour is the
 * second half of the signal (green while the histogram is building against the
 * previous bar, red while it is fading), and that is a per-bar decision, hence
 * `colorBy` on one column rather than two plots that would each carry holes.
 * On the first printed bar the previous value is `na`, and the reference `na <= 0` is
 * false, so it starts green.
 */
export const AWESOME_OSCILLATOR: IndicatorDescriptor = {
  id: 'awesome-oscillator',
  name: 'Awesome Oscillator',
  category: 'Momentum',
  placement: 'pane',
  inputs: [
    { key: 'upColor', type: 'color', label: 'Rising', default: '#009688' },
    { key: 'downColor', type: 'color', label: 'Falling', default: '#f44336' },
  ],
  plots: [
    {
      // `colorKey` is only the fallback the settings UI restyles; `colorBy`
      // overrides it bar by bar.
      key: 'ao', type: 'column', title: 'AO', colorKey: 'upColor',
      style: { base: 0 },
      colorBy: ({ value, index, values, settings }) => {
        const prev = values.ao?.[index - 1];
        const rising = prev === null || prev === undefined || !Number.isFinite(prev)
          ? true
          : value - prev > 0;
        return rising ? str(settings, 'upColor', '#009688') : str(settings, 'downColor', '#f44336');
      },
    },
  ],
  calc: (bars) => {
    const mid = hl2(bars);
    const fast = sma(mid, 5);
    const slow = sma(mid, 34);
    return { ao: nulls(zip(fast, slow, (f, sl) => f - sl)) };
  },
  levels: () => [{ price: 0, color: '#787b86' }],
};

/**
 * Balance of Power: where the close finished inside the bar's range, relative
 * to where it opened. No smoothing and no inputs; the reference is one line.
 *
 * A zero-range bar makes this 0/0, which is `na` in the reference, so it draws a gap
 * rather than a spike.
 */
export const BALANCE_OF_POWER: IndicatorDescriptor = {
  id: 'balance-of-power',
  name: 'Balance of Power',
  category: 'Momentum',
  placement: 'pane',
  inputs: [
    { key: 'color', type: 'color', label: 'BOP', default: '#ff5252' }, // the reference color.red
  ],
  plots: [{ key: 'bop', type: 'line', title: 'BOP', colorKey: 'color', style: { lineWidth: 1.5 } }],
  calc: (bars) => ({
    bop: bars.map((b) => {
      const range = b.high - b.low;
      const change = b.close - b.open;
      // An overflowed range is undefined, not a zero-strength observation.
      if (range === 0 || !Number.isFinite(range) || !Number.isFinite(change)) return null;
      const value = change / range;
      return Number.isFinite(value) ? value : null;
    }),
  }),
  levels: () => [{ price: 0, color: '#787b86' }],
};

/**
 * Chande Momentum Oscillator: the same up/down split as RSI, but as a plain
 * ratio of summed moves instead of a Wilder average, so it swings the full
 * -100..100 rather than compressing towards the middle.
 *
 * `change` is `na` on the first bar, so the first published value is the one
 * backed by `length` real changes: index `length`, not `length - 1`. The sums
 * are therefore taken over the series from bar 1 onwards, which also keeps the
 * running total in `rollingSum` from ever touching a NaN: one NaN would poison
 * it for the rest of the series, because subtracting it back out when it leaves
 * the window does not undo it.
 */
export const CHANDE_MOMENTUM: IndicatorDescriptor = {
  id: 'chande-momentum',
  name: 'Chande Momentum Oscillator',
  category: 'Momentum',
  placement: 'pane',
  inputs: [
    { key: 'length', type: 'number', label: 'Length', default: 9, min: 1, max: 500, step: 1 },
    { key: 'source', type: 'source', label: 'Source', default: 'close' },
    { key: 'color', type: 'color', label: 'Chande MO', default: '#2962ff' },
  ],
  plots: [{ key: 'cmo', type: 'line', title: 'Chande MO', colorKey: 'color', style: { lineWidth: 1.5 } }],
  calc: (bars, s) => {
    const n = bars.length;
    const length = int(s, 'length', 9);
    const momm = change(sourceValues(bars, src(s)));
    const gains = new Array<number>(Math.max(0, n - 1));
    const losses = new Array<number>(Math.max(0, n - 1));
    // The moves and their sums hold n - 1 values, one per bar from bar 1.
    for (let i = 1; i < n; i++) {
      const m = momm[i]!;
      gains[i - 1] = m >= 0 ? m : 0;
      losses[i - 1] = m >= 0 ? 0 : -m;
    }
    const sumUp = rollingSum(gains, length);
    const sumDown = rollingSum(losses, length);
    const out = new Array<number>(n).fill(NaN);
    for (let i = 0; i < sumUp.length; i++) {
      const total = sumUp[i]! + sumDown[i]!;
      // A perfectly flat window is 0/0, which the reference prints as a gap.
      out[i + 1] = total === 0 ? NaN : (100 * (sumUp[i]! - sumDown[i]!)) / total;
    }
    return { cmo: nulls(out) };
  },
  levels: () => [{ price: 0, color: '#787b86', title: 'Zero Line', dashed: true }],
};

/**
 * Coppock Curve: a weighted average of two rates of change, one long and one
 * short. Both `roc` terms must have a value before the WMA has anything to
 * chew on, so the first print lands at `longRoCLength + wmaLength - 1`.
 */
export const COPPOCK_CURVE: IndicatorDescriptor = {
  id: 'coppock-curve',
  name: 'Coppock Curve',
  category: 'Momentum',
  placement: 'pane',
  inputs: [
    { key: 'wmaLength', type: 'number', label: 'WMA Length', default: 10, min: 1, max: 500, step: 1 },
    { key: 'longRoCLength', type: 'number', label: 'Long RoC Length', default: 14, min: 1, max: 500, step: 1 },
    { key: 'shortRoCLength', type: 'number', label: 'Short RoC Length', default: 11, min: 1, max: 500, step: 1 },
    { key: 'color', type: 'color', label: 'Coppock Curve', default: '#2962ff' },
  ],
  plots: [{ key: 'curve', type: 'line', title: 'Coppock Curve', colorKey: 'color', style: { lineWidth: 1.5 } }],
  calc: (bars, s) => {
    const source = bars.map((b) => b.close);
    const long = roc(source, int(s, 'longRoCLength', 14));
    const short = roc(source, int(s, 'shortRoCLength', 11));
    return { curve: nulls(wma(zip(long, short, (v, sh) => v + sh), int(s, 'wmaLength', 10))) };
  },
};

/**
 * Detrended Price Oscillator: price against a moving average taken from half a
 * cycle ago, which strips the trend and leaves the cycle.
 *
 * `barsback = period/2 + 1` indexes a series, so it has to be a whole number:
 * the reference integer division truncates, and this floors, which agrees for both odd
 * and even lengths (21 -> 11, 20 -> 11).
 *
 * The `centered` mode is the awkward one. the reference computes `close[barsback] - ma`
 * and then draws it with `offset = -barsback`, i.e. shifted back in time.
 * Plots here have no per-plot offset, so the shift is folded into the column
 * itself: the value drawn at bar `i` is the one the reference computed on bar
 * `i + barsback`, which reduces to `close[i] - ma[i + barsback]`. The picture
 * matches the reference platform exactly, including the fact that the centered line stops
 * `barsback` bars short of the right edge. The non-centered mode needs no such
 * trick and is implemented straight.
 */
export const DPO: IndicatorDescriptor = {
  id: 'dpo',
  name: 'Detrended Price Oscillator',
  category: 'Momentum',
  placement: 'pane',
  inputs: [
    { key: 'period', type: 'number', label: 'Length', default: 21, min: 1, max: 500, step: 1 },
    { key: 'isCentered', type: 'boolean', label: 'Centered', default: false },
    { key: 'color', type: 'color', label: 'DPO', default: '#43a047' },
  ],
  plots: [{ key: 'dpo', type: 'line', title: 'DPO', colorKey: 'color', style: { lineWidth: 1.5 } }],
  calc: (bars, s) => {
    const n = bars.length;
    const period = int(s, 'period', 21);
    const barsback = Math.floor(period / 2) + 1;
    const close = bars.map((b) => b.close);
    const ma = sma(close, period);
    const out = new Array<number>(n).fill(NaN);
    if (s.isCentered === true) {
      for (let i = 0; i + barsback < n; i++) out[i] = close[i]! - ma[i + barsback]!;
    } else {
      for (let i = barsback; i < n; i++) out[i] = close[i]! - ma[i - barsback]!;
    }
    return { dpo: nulls(out) };
  },
  levels: () => [{ price: 0, color: '#787b86', title: 'Zero Line' }],
};

/**
 * Fisher Transform: squash the position of `hl2` inside its recent range into
 * -1..1, then run it through the inverse hyperbolic tangent so the tails
 * stretch out and turning points become sharp.
 *
 * Two recursions, each carrying two thirds / one half of the previous bar. The
 * clamp to +/-0.999 is not cosmetic: at exactly +/-1 the log blows up, so the
 * the reference `round_` is what keeps the series finite. Both recursions read the
 * previous bar through `nz`, so a missing previous value counts as 0, which
 * happens on the first printed bar and again after any bar that produced `na`.
 * A flat window (`high_ == low_`) is not one of those: the range divide is
 * floored at 0.001, so the ratio is 0, the bar still prints, and both
 * recursions carry on.
 *
 * `Trigger` is simply `fish1[1]`, so it lags Fisher by exactly one bar.
 */
export const FISHER_TRANSFORM: IndicatorDescriptor = {
  id: 'fisher-transform',
  name: 'Fisher Transform',
  category: 'Momentum',
  placement: 'pane',
  inputs: [
    { key: 'length', type: 'number', label: 'Length', default: 9, min: 1, max: 500, step: 1 },
    { key: 'fisherColor', type: 'color', label: 'Fisher', default: '#2962ff' },
    { key: 'triggerColor', type: 'color', label: 'Trigger', default: '#ff6d00' },
  ],
  plots: [
    { key: 'fisher', type: 'line', title: 'Fisher', colorKey: 'fisherColor', style: { lineWidth: 1.5 } },
    { key: 'trigger', type: 'line', title: 'Trigger', colorKey: 'triggerColor', style: { lineWidth: 1.5 } },
  ],
  calc: (bars, s) => {
    const n = bars.length;
    const length = int(s, 'length', 9);
    const mid = hl2(bars);
    const hi = highest(mid, length);
    const lo = lowest(mid, length);
    const fisher = new Array<number>(n).fill(NaN);
    // `nz(value[1])` / `nz(fish1[1])`: zero stands in for a missing prior bar.
    let prevValue = 0;
    let prevFish = 0;
    for (let i = 0; i < n; i++) {
      const span = hi[i]! - lo[i]!;
      // The window extremes skip a missing midpoint, so the span alone can stay
      // finite on a bar that has none; letting that NaN into the two recursions
      // would blank the study for the rest of the history.
      if (!Number.isFinite(span) || !Number.isFinite(mid[i])) {
        prevValue = 0;
        prevFish = 0;
        continue;
      }
      const raw = 0.66 * ((mid[i]! - lo[i]!) / Math.max(span, 0.001) - 0.5) + 0.67 * prevValue;
      const value = raw > 0.99 ? 0.999 : raw < -0.99 ? -0.999 : raw;
      const fish = 0.5 * Math.log((1 + value) / (1 - value)) + 0.5 * prevFish;
      fisher[i] = fish;
      prevValue = value;
      prevFish = fish;
    }
    const trigger = new Array<number>(n).fill(NaN);
    for (let i = 1; i < n; i++) trigger[i] = fisher[i - 1]!;
    return { fisher: nulls(fisher), trigger: nulls(trigger) };
  },
  levels: () => [
    { price: 1.5, color: '#e91e63', title: '1.5' },
    { price: 0.75, color: '#787b86', title: '0.75' },
    { price: 0, color: '#e91e63', title: '0' },
    { price: -0.75, color: '#787b86', title: '-0.75' },
    { price: -1.5, color: '#e91e63', title: '-1.5' },
  ],
};

/**
 * The Connors "updown" streak: how many consecutive bars price has risen or
 * fallen, signed. An unchanged close resets it to 0; a rise continues a
 * positive run or starts a new one at +1; a fall mirrors that.
 *
 * Exported because it is the one piece of Connors RSI worth testing on its own
 * (the rest is three well-known series averaged).
 *
 * Bar 0 is deliberately -1, not 0. In the reference `close == close[1]` and
 * `close > close[1]` are both false against `na`, so the first bar falls into
 * the down branch with `nz(ud[1])` reading 0, which yields -1.
 */
export function connorsStreak(values: readonly number[]): number[] {
  const n = values.length;
  const out = new Array<number>(n).fill(0);
  for (let i = 0; i < n; i++) {
    const prev = i > 0 ? out[i - 1]! : 0;
    if (i > 0 && values[i] === values[i - 1]) out[i] = 0;
    else if (i > 0 && values[i]! > values[i - 1]!) out[i] = prev <= 0 ? 1 : prev + 1;
    else out[i] = prev >= 0 ? -1 : prev - 1;
  }
  return out;
}

/**
 * Connors RSI is the mean of three unrelated readings of the same bar: how
 * overbought price is (a short RSI), how stretched the up/down streak is (an
 * RSI of the streak itself), and where today's one-bar return sits in its own
 * recent distribution (a percent rank).
 *
 * Averaging only works if all three have a value, and the percent rank is the
 * slow one: `roc(close, 1)` is `na` on bar 0, and `percentrank` compares
 * the current value against the previous `lenroc` of them, so the first
 * complete reading is at index `lenroc + 1`: 101 on defaults. Running the rank
 * over the series from bar 1 is what keeps that `na` out of the window.
 */
export const CONNORS_RSI: IndicatorDescriptor = {
  id: 'connors-rsi',
  name: 'Connors RSI',
  category: 'Momentum',
  placement: 'pane',
  inputs: [
    { key: 'lenrsi', type: 'number', label: 'RSI Length', default: 3, min: 1, max: 500, step: 1 },
    { key: 'lenupdown', type: 'number', label: 'UpDown Length', default: 2, min: 1, max: 500, step: 1 },
    { key: 'lenroc', type: 'number', label: 'ROC Length', default: 100, min: 1, max: 1000, step: 1 },
    { key: 'color', type: 'color', label: 'CRSI', default: '#2962ff' },
    { key: 'fillColor', type: 'color', label: 'Background', default: '#2196f3' },
  ],
  plots: [{ key: 'crsi', type: 'line', title: 'CRSI', colorKey: 'color', style: { lineWidth: 1.5 } }],
  // The 70/30 background is shaded between two reference lines, not between two
  // series, so its edges are constant columns with no plot of their own, the
  // same trick `AROON_OSCILLATOR` uses for its zero edge. One colour on both
  // sides: a level band has no up or down side to distinguish.
  fills: [{ between: ['bandHigh', 'bandLow'], colorUpKey: 'fillColor', colorDownKey: 'fillColor', opacity: 0.1 }],
  calc: (bars, s) => {
    const n = bars.length;
    const close = bars.map((b) => b.close);
    const priceRsi = rsi(close, int(s, 'lenrsi', 3));
    const streakRsi = rsi(connorsStreak(close), int(s, 'lenupdown', 2));

    const returns = roc(close, 1);
    const ranked = percentRank(returns.slice(1), int(s, 'lenroc', 100));
    const rank = new Array<number>(n).fill(NaN);
    for (let i = 0; i < ranked.length; i++) rank[i + 1] = ranked[i]!;

    // `avg` of three values, and `na` in any of them makes the mean `na`.
    const out = new Array<number>(n);
    for (let i = 0; i < n; i++) out[i] = (priceRsi[i]! + streakRsi[i]! + rank[i]!) / 3;
    // Never null, not even over the study's 101-bar warmup: the background
    // spans the whole pane, so its edges have to exist where the line does not.
    return { crsi: nulls(out), bandHigh: new Array<number>(n).fill(70), bandLow: new Array<number>(n).fill(30) };
  },
  levels: () => [
    { price: 70, color: '#787b86', title: 'Upper Band' },
    { price: 50, color: '#5a6b8c', title: 'Middle Band', dashed: true },
    { price: 30, color: '#787b86', title: 'Lower Band' },
  ],
  range: () => ({ min: 0, max: 100 }),
};

export const OSCILLATOR_INDICATORS: readonly IndicatorDescriptor[] = [
  AROON,
  AROON_OSCILLATOR,
  AWESOME_OSCILLATOR,
  BALANCE_OF_POWER,
  CHANDE_MOMENTUM,
  COPPOCK_CURVE,
  DPO,
  FISHER_TRANSFORM,
  CONNORS_RSI,
];
