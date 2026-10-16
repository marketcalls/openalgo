/**
 * Built-in overlays, the ten price-pane studies whose behaviour
 * is specified against the published reference definitions rather than this library's own.
 * Part of the lazy `openalgo-charts/indicators` tier.
 *
 * Parity note, and the reason `ema` is absent from the imports: the reference `ema`
 * seeds from the SMA of the first `length` values and is `na` before that, while
 * the base bundle's `ema` seeds from `values[0]` and emits from bar 0 to match
 * `openalgo.ta`. The two disagree over the whole warmup, so anything that has to
 * land on the same pixels as a reference platform plot uses `smaSeededEma` from `./calc`.
 *
 * `atr` and the `sourceValues` helper come from the base bundle
 * (`openalgo-charts`), not deep paths, see the note in `src/indicators/index.ts`.
 */
import { atr, sourceValues } from 'openalgo-charts';
import type { IndicatorDescriptor } from 'openalgo-charts';
import { sma, wma, highest, lowest, nulls, smaSeededEma, alma, linreg, standardError } from './calc';
import { emaOfGapped } from './smoothing';
import { withTail, windowTail, whole } from './tail';
import { withTimeframe } from './timeframe';
import { num, int, offsetOf, str, src } from './settings';
import { shift, zip } from './series';

const highs = (bars: readonly { high: number }[]): number[] => bars.map((b) => b.high);
const lows = (bars: readonly { low: number }[]): number[] => bars.map((b) => b.low);

/**
 * A rolling extreme that refuses any window containing a warmup gap. `highest` /
 * `lowest` in `./calc` step over non-finite values, which is what you want for
 * raw highs and lows but not when the input is itself an indicator: the reference builds
 * `highest` out of `max`, and `max(na, x)` is `na`, so a window
 * straddling the inner series' warmup is `na` across its whole span. Chande
 * Kroll stacks one extreme on top of another and is the only place it shows.
 */
function extremeStrict(values: readonly number[], period: number, wantHigh: boolean): number[] {
  const n = values.length;
  const out = new Array<number>(n).fill(NaN);
  if (period <= 0) return out;
  // The one caller passes a whole period, so each window is [i - period + 1, i].
  for (let i = period - 1; i < n; i++) {
    let best = wantHigh ? -Infinity : Infinity;
    let live = true;
    for (let k = 0; k < period; k++) {
      const v = values[i - k]!;
      if (!Number.isFinite(v)) { live = false; break; }
      if (wantHigh ? v > best : v < best) best = v;
    }
    if (live) out[i] = best;
  }
  return out;
}

/**
 * the reference fills these channels with `color.rgb(33, 150, 243, 95)`, 95 % transparent,
 * so the band is a hint rather than a wash. Kept as-is so the overlay reads the
 * same here as on the reference platform.
 */
const CHANNEL_FILL_OPACITY = 0.05;

/**
 * The source is hard-coded to `close` in the reference (`source = close`,
 * not an `input`), so there is no source setting to expose.
 */
export const ALMA: IndicatorDescriptor = withTimeframe({
  id: 'alma',
  name: 'Arnaud Legoux Moving Average',
  category: 'Trend',
  placement: 'onchart',
  inputs: [
    { key: 'length', type: 'number', label: 'Length', default: 9, min: 1, max: 1000, step: 1 },
    { key: 'offset', type: 'number', label: 'Offset', default: 0.85, min: 0, max: 1, step: 0.01 },
    { key: 'sigma', type: 'number', label: 'Sigma', default: 6, min: 0.1, max: 100, step: 0.1 },
    { key: 'color', type: 'color', label: 'ALMA', default: '#2962ff' },
  ],
  plots: [{
    key: 'alma', type: 'line', title: 'ALMA', colorKey: 'color',
    style: { color: '#2962ff', lineWidth: 1.5 },
  }],
  calc: (bars, s) => ({
    alma: nulls(alma(
      sourceValues(bars, 'close'),
      int(s, 'length', 9),
      num(s, 'offset', 0.85),
      num(s, 'sigma', 6),
    )),
  }),
});

/**
 * `2 * ema - ema(ema)`. The second pass runs over a series that is already NaN
 * for its own warmup, which is what pushes the first plotted bar out to
 * `2 * length - 2`, see `emaOfGapped`.
 */
export const DEMA: IndicatorDescriptor = withTimeframe({
  id: 'dema',
  name: 'Double EMA',
  category: 'Trend',
  placement: 'onchart',
  inputs: [
    { key: 'length', type: 'number', label: 'Length', default: 9, min: 1, max: 1000, step: 1 },
    { key: 'source', type: 'source', label: 'Source', default: 'close' },
    { key: 'color', type: 'color', label: 'DEMA', default: '#43a047' },
  ],
  plots: [{
    key: 'dema', type: 'line', title: 'DEMA', colorKey: 'color',
    style: { color: '#43a047', lineWidth: 1.5 },
  }],
  calc: (bars, s) => {
    const values = sourceValues(bars, src(s));
    const length = int(s, 'length', 9);
    const e1 = smaSeededEma(values, length);
    const e2 = emaOfGapped(e1, length);
    // Both averages hold one value per bar, as every calc helper returns.
    return { dema: nulls(zip(e1, e2, (v, e) => 2 * v - e)) };
  },
});

export const HMA: IndicatorDescriptor = withTimeframe({
  id: 'hma',
  name: 'Hull Moving Average',
  category: 'Trend',
  placement: 'onchart',
  inputs: [
    { key: 'length', type: 'number', label: 'Length', default: 9, min: 1, max: 1000, step: 1 },
    { key: 'source', type: 'source', label: 'Source', default: 'close' },
    { key: 'color', type: 'color', label: 'HMA', default: '#2962ff' },
  ],
  plots: [{
    key: 'hma', type: 'line', title: 'HMA', colorKey: 'color',
    style: { color: '#2962ff', lineWidth: 1.5 },
  }],
  calc: (bars, s) => {
    const values = sourceValues(bars, src(s));
    const length = int(s, 'length', 9);
    return { hma: nulls(hullHma(values, length)) };
  },
});

export const ENVELOPE: IndicatorDescriptor = withTimeframe({
  id: 'envelope',
  name: 'Envelope',
  category: 'Volatility',
  placement: 'onchart',
  inputs: [
    { key: 'length', type: 'number', label: 'Length', default: 20, min: 1, max: 1000, step: 1 },
    { key: 'percent', type: 'number', label: 'Percent', default: 10, min: 0, max: 100, step: 0.1 },
    { key: 'source', type: 'source', label: 'Source', default: 'close' },
    { key: 'exponential', type: 'boolean', label: 'Exponential', default: false },
    { key: 'basisColor', type: 'color', label: 'Basis', default: '#ff6d00' },
    { key: 'bandColor', type: 'color', label: 'Bands', default: '#2962ff' },
    { key: 'fillColor', type: 'color', label: 'Background', default: '#2196f3' },
  ],
  plots: [
    { key: 'upper', type: 'line', title: 'Env Upper', colorKey: 'bandColor', style: { color: '#2962ff', lineWidth: 1 } },
    { key: 'basis', type: 'line', title: 'Env Basis', colorKey: 'basisColor', style: { color: '#ff6d00', lineWidth: 1.5 } },
    { key: 'lower', type: 'line', title: 'Env Lower', colorKey: 'bandColor', style: { color: '#2962ff', lineWidth: 1 } },
  ],
  fills: [{
    between: ['upper', 'lower'],
    colorUpKey: 'fillColor',
    colorDownKey: 'fillColor',
    opacity: CHANNEL_FILL_OPACITY,
  }],
  calc: (bars, s) => {
    const values = sourceValues(bars, src(s));
    const length = int(s, 'length', 20);
    const k = num(s, 'percent', 10) / 100;
    const basis = s.exponential === true ? smaSeededEma(values, length) : sma(values, length);
    return {
      upper: nulls(basis.map((b) => b * (1 + k))),
      basis: nulls(basis),
      lower: nulls(basis.map((b) => b * (1 - k))),
    };
  },
});

export const DONCHIAN: IndicatorDescriptor = withTimeframe(withTail({
  id: 'donchian',
  name: 'Donchian Channels',
  category: 'Volatility',
  placement: 'onchart',
  inputs: [
    { key: 'length', type: 'number', label: 'Length', default: 20, min: 1, max: 1000, step: 1 },
    { key: 'offset', type: 'number', label: 'Offset', default: 0, min: -500, max: 500, step: 1 },
    { key: 'basisColor', type: 'color', label: 'Basis', default: '#ff6d00' },
    { key: 'bandColor', type: 'color', label: 'Bands', default: '#2962ff' },
    { key: 'fillColor', type: 'color', label: 'Background', default: '#2196f3' },
  ],
  plots: [
    { key: 'upper', type: 'line', title: 'DC Upper', colorKey: 'bandColor', style: { color: '#2962ff', lineWidth: 1 } },
    { key: 'basis', type: 'line', title: 'DC Basis', colorKey: 'basisColor', style: { color: '#ff6d00', lineWidth: 1.5 } },
    { key: 'lower', type: 'line', title: 'DC Lower', colorKey: 'bandColor', style: { color: '#2962ff', lineWidth: 1 } },
  ],
  fills: [{
    between: ['upper', 'lower'],
    colorUpKey: 'fillColor',
    colorDownKey: 'fillColor',
    opacity: CHANNEL_FILL_OPACITY,
  }],
  calc: (bars, s) => {
    const length = int(s, 'length', 20);
    // Offset is a displacement, so it is the one setting that may be negative.
    const offset = offsetOf(s, 'offset', 0);
    const upper = highest(highs(bars), length);
    const lower = lowest(lows(bars), length);
    const basis = zip(upper, lower, (u, lo) => (u + lo) / 2);
    return {
      upper: nulls(shift(upper, offset)),
      basis: nulls(shift(basis, offset)),
      lower: nulls(shift(lower, offset)),
    };
  },
}, (calc) => windowTail(calc, (s) => {
  // A forward offset only reaches further back. A backward one draws the
  // forming bar's channel on an earlier slot than the tail covers.
  const length = int(s, 'length', 20);
  const offset = offsetOf(s, 'offset', 0);
  return whole(length) && offset >= 0 ? length - 1 + offset : null;
})));

/**
 * Two stacked extremes: an ATR-padded high/low band, then the running extreme of
 * *that* over `q` bars, which is what keeps each stop monotone through a pullback.
 * The second pass is NaN-strict (`extremeStrict`), so nothing prints until the
 * whole `q`-bar window is past the ATR warmup, bar `p + q - 2`.
 *
 * The long stop is padded off the lowest **low**, which is the published
 * definition and what the short stop mirrors. The reference implementation takes
 * both extremes over the high series (it never reads a low at all), so the two
 * long stops disagree by roughly the average high-low range while the short
 * stops agree to the last bit. Measured, deliberate, and left alone: matching it
 * would move a stop line for every existing user onto a reading that the
 * published definition of this stop contradicts.
 */
export const CHANDE_KROLL_STOP: IndicatorDescriptor = {
  id: 'chande-kroll-stop',
  name: 'Chande Kroll Stop',
  category: 'Trend',
  placement: 'onchart',
  inputs: [
    { key: 'p', type: 'number', label: 'ATR Length (p)', default: 10, min: 1, max: 500, step: 1 },
    { key: 'x', type: 'number', label: 'ATR Coefficient (x)', default: 1, min: 1, max: 100, step: 1 },
    { key: 'q', type: 'number', label: 'Stop Length (q)', default: 9, min: 1, max: 500, step: 1 },
    { key: 'longColor', type: 'color', label: 'Stop Long', default: '#2962ff' },
    { key: 'shortColor', type: 'color', label: 'Stop Short', default: '#ff6d00' },
  ],
  plots: [
    { key: 'stopLong', type: 'line', title: 'Stop Long', colorKey: 'longColor', style: { color: '#2962ff', lineWidth: 1.5 } },
    { key: 'stopShort', type: 'line', title: 'Stop Short', colorKey: 'shortColor', style: { color: '#ff6d00', lineWidth: 1.5 } },
  ],
  calc: (bars, s) => {
    const p = int(s, 'p', 10);
    const x = int(s, 'x', 1);
    const q = int(s, 'q', 9);
    const high = highs(bars);
    const low = lows(bars);
    const range = atr(high, low, bars.map((b) => b.close), p);
    const firstHighStop = zip(highest(high, p), range, (v, r) => v - x * r);
    const firstLowStop = zip(lowest(low, p), range, (v, r) => v + x * r);
    return {
      stopLong: nulls(extremeStrict(firstLowStop, q, false)),
      stopShort: nulls(extremeStrict(firstHighStop, q, true)),
    };
  },
};

/**
 * The reference imports an external helper library and calls `an external `chandelier()` helper`, whose
 * body is not in the reference file. This is the published definition of that stop:
 * the highest high of the window pulled down by `mult` ATRs, and its mirror.
 */
export const CHANDELIER_EXIT: IndicatorDescriptor = {
  id: 'chandelier-exit',
  name: 'Chandelier Exit',
  category: 'Trend',
  placement: 'onchart',
  inputs: [
    { key: 'length', type: 'number', label: 'Length', default: 22, min: 1, max: 500, step: 1 },
    { key: 'atrLength', type: 'number', label: 'ATR length', default: 22, min: 1, max: 500, step: 1 },
    { key: 'atrMultiplier', type: 'number', label: 'ATR multiplier', default: 3, min: 0, max: 50, step: 0.01 },
    { key: 'longColor', type: 'color', label: 'Long exit', default: '#2962ff' },
    { key: 'shortColor', type: 'color', label: 'Short exit', default: '#ff6d00' },
  ],
  plots: [
    { key: 'longExit', type: 'line', title: 'Long Exit', colorKey: 'longColor', style: { color: '#2962ff', lineWidth: 1.5 } },
    { key: 'shortExit', type: 'line', title: 'Short Exit', colorKey: 'shortColor', style: { color: '#ff6d00', lineWidth: 1.5 } },
  ],
  calc: (bars, s) => {
    const length = int(s, 'length', 22);
    const mult = num(s, 'atrMultiplier', 3);
    const high = highs(bars);
    const low = lows(bars);
    const range = atr(high, low, bars.map((b) => b.close), int(s, 'atrLength', 22));
    return {
      longExit: nulls(zip(highest(high, length), range, (v, r) => v - mult * r)),
      shortExit: nulls(zip(lowest(low, length), range, (v, r) => v + mult * r)),
    };
  },
};

/**
 * Bands centred on the regression **endpoint**, not on a moving average of price:
 * the fitted line's value at the newest bar of the window, pushed out by
 * `errors` standard errors, and only then smoothed. The middle plot is that
 * smoothed endpoint, so it is not the same line as a plain regression curve.
 * All three legs are smoothed independently, which is why the first bar of each
 * lands at `(periods - 1) + (averagePeriods - 1)`.
 */
export const STANDARD_ERROR_BANDS: IndicatorDescriptor = {
  id: 'standard-error-bands',
  name: 'Standard Error Bands',
  category: 'Volatility',
  placement: 'onchart',
  inputs: [
    { key: 'periods', type: 'number', label: 'Periods', default: 21, min: 3, max: 1000, step: 1 },
    { key: 'errors', type: 'number', label: 'Standard Errors', default: 2, min: 0, max: 100, step: 0.1 },
    {
      key: 'method', type: 'select', label: 'Method', default: 'Simple',
      options: [
        { label: 'Simple', value: 'Simple' },
        { label: 'Exponential', value: 'Exponential' },
        { label: 'Weighted', value: 'Weighted' },
      ],
    },
    { key: 'averagePeriods', type: 'number', label: 'Averaging Periods', default: 3, min: 1, max: 1000, step: 1 },
    { key: 'basisColor', type: 'color', label: 'Basis', default: '#ff6d00' },
    { key: 'bandColor', type: 'color', label: 'Bands', default: '#2962ff' },
    { key: 'fillColor', type: 'color', label: 'Background', default: '#2196f3' },
  ],
  plots: [
    { key: 'upper', type: 'line', title: 'SEB Upper', colorKey: 'bandColor', style: { color: '#2962ff', lineWidth: 1 } },
    { key: 'basis', type: 'line', title: 'SEB Basis', colorKey: 'basisColor', style: { color: '#ff6d00', lineWidth: 1.5 } },
    { key: 'lower', type: 'line', title: 'SEB Lower', colorKey: 'bandColor', style: { color: '#2962ff', lineWidth: 1 } },
  ],
  fills: [{
    between: ['upper', 'lower'],
    colorUpKey: 'fillColor',
    colorDownKey: 'fillColor',
    opacity: CHANNEL_FILL_OPACITY,
  }],
  calc: (bars, s) => {
    // The source is hard-coded to `close` in the reference, so there is nothing
    // to expose: a regression over highs would not be this indicator.
    const values = sourceValues(bars, 'close');
    const periods = int(s, 'periods', 21, 3);
    const errors = num(s, 'errors', 2);
    const avg = int(s, 'averagePeriods', 3);
    const se = standardError(values, periods);
    const mid = linreg(values, periods, 0);
    // Each leg is smoothed on its own, so the band width is smoothed too, not
    // recomputed around a smoothed middle.
    const smooth = (v: readonly number[]): (number | null)[] => nulls(
      s.method === 'Exponential' ? emaOfGapped(v, avg)
        : s.method === 'Weighted' ? wma(v, avg) : sma(v, avg),
    );
    return {
      upper: smooth(zip(mid, se, (m, err) => m + errors * err)),
      basis: smooth(mid),
      lower: smooth(zip(mid, se, (m, err) => m - errors * err)),
    };
  },
};

/**
 * Two independent legs, a mean of highs and a mean of lows, each with its own
 * length and its own plot-time displacement. Not a mean of the close with a
 * spread around it, and simple throughout: there is no smoothing method here.
 */
export const MA_CHANNEL: IndicatorDescriptor = {
  id: 'ma-channel',
  name: 'Moving Average Channel',
  category: 'Volatility',
  placement: 'onchart',
  inputs: [
    { key: 'upperLength', type: 'number', label: 'Upper Length', default: 20, min: 1, max: 1000, step: 1 },
    { key: 'lowerLength', type: 'number', label: 'Lower Length', default: 20, min: 1, max: 1000, step: 1 },
    { key: 'upperOffset', type: 'number', label: 'Upper Offset', default: 0, min: -500, max: 500, step: 1 },
    { key: 'lowerOffset', type: 'number', label: 'Lower Offset', default: 0, min: -500, max: 500, step: 1 },
    { key: 'upperColor', type: 'color', label: 'Upper', default: '#2962ff' },
    { key: 'lowerColor', type: 'color', label: 'Lower', default: '#ff6d00' },
    { key: 'fillColor', type: 'color', label: 'Background', default: '#2196f3' },
  ],
  plots: [
    { key: 'upper', type: 'line', title: 'MAC Upper', colorKey: 'upperColor', style: { color: '#2962ff', lineWidth: 1.5 } },
    { key: 'lower', type: 'line', title: 'MAC Lower', colorKey: 'lowerColor', style: { color: '#ff6d00', lineWidth: 1.5 } },
  ],
  fills: [{
    between: ['upper', 'lower'],
    colorUpKey: 'fillColor',
    colorDownKey: 'fillColor',
    opacity: CHANNEL_FILL_OPACITY,
  }],
  calc: (bars, s) => ({
    // Offsets are displacements, so they are the settings here that may be negative.
    upper: nulls(shift(sma(highs(bars), int(s, 'upperLength', 20)), offsetOf(s, 'upperOffset', 0))),
    lower: nulls(shift(sma(lows(bars), int(s, 'lowerLength', 20)), offsetOf(s, 'lowerOffset', 0))),
  }),
};

const HULL_BULLISH = '#00ff00';
const HULL_BEARISH = '#ff0000';
const HULL_NEUTRAL = '#ff9800';

/**
 * The published definition divides its length by two and by three and lets the
 * results truncate, so a short setting would otherwise hand a smoother a
 * zero-bar window. One bar is the floor everywhere a length is derived.
 */
const span = (n: number): number => Math.max(1, Math.floor(n));

/**
 * The outer length is the only one that rounds. That asymmetry against `span`
 * is in the definition, not an oversight: `sqrt(55)` is 7.42, and rounding it
 * to 7 rather than truncating to 7 happens to agree here but does not at, say,
 * `sqrt(50)`, where the two differ by a whole bar of smoothing.
 */
const rootSpan = (n: number): number => Math.max(1, Math.round(Math.sqrt(n)));

function hullHma(values: readonly number[], n: number): number[] {
  const fast = wma(values, span(n / 2));
  const slow = wma(values, n);
  // Each WMA requires a complete finite window, so the outer pass remains
  // unavailable while its window still contains the raw series' warmup gap.
  return wma(zip(fast, slow, (v, sl) => 2 * v - sl), rootSpan(n));
}

function hullEhma(values: readonly number[], n: number): number[] {
  const fast = smaSeededEma(values, span(n / 2));
  const slow = smaSeededEma(values, n);
  // The difference inherits `slow`'s warmup gap. Keep the outer smoothing
  // pass aligned with that first available difference.
  return emaOfGapped(zip(fast, slow, (v, sl) => 2 * v - sl), rootSpan(n));
}

/**
 * The odd one out: three windows combined and then smoothed over the **full**
 * length rather than its square root, which is why the caller hands this one
 * half the length the other two variations get.
 */
function hullThma(values: readonly number[], n: number): number[] {
  const third = wma(values, span(n / 3));
  const half = wma(values, span(n / 2));
  const full = wma(values, n);
  return wma(third.map((v, i) => v * 3 - half[i]! - full[i]!), n);
}

function hullSeries(values: readonly number[], mode: string, len: number): number[] {
  if (mode === 'Ehma') return hullEhma(values, len);
  // Halving the length here and nowhere else is deliberate in the published
  // definition. Passing the full length would land this variation on a
  // different line from the one users are comparing against.
  if (mode === 'Thma') return hullThma(values, span(len / 2));
  return hullHma(values, len);
}

/**
 * The one colour decision both plots and the candles share: is the hull above
 * where it stood two bars ago. Everything reads `mhull`, never its own value,
 * so the band, the two lines and the candles cannot disagree, and switching the
 * band off does not change what colour anything else is.
 *
 * A slot with nothing to compare against (the warmup, or the first two bars of
 * a degenerate length) is not rising, so it takes the bearish colour. That is
 * what comparing against an undefined value does in the published definition
 * too, and on every such bar the line itself is a gap anyway.
 */
const hullTrendColor = (
  hull: readonly (number | null)[] | undefined,
  index: number,
  s: Readonly<Record<string, unknown>>,
): string => {
  if (s.switchColor === false) return str(s, 'neutralColor', HULL_NEUTRAL);
  const now = hull?.[index];
  const back = hull?.[index - 2];
  const rising = typeof now === 'number' && typeof back === 'number' && now > back;
  return rising ? str(s, 'bullishColor', HULL_BULLISH) : str(s, 'bearishColor', HULL_BEARISH);
};

/**
 * Hull Suite: one hull average plotted twice, the second copy displaced two
 * bars. The band is therefore the average against its own recent past rather
 * than a second study, and "the first plot is above the second" is exactly the
 * rising condition, which is what lets a plain two-colour fill carry the trend.
 *
 * Three variations are offered because they trade lag against smoothness
 * differently, and two quirks of the published definition are preserved rather
 * than tidied: the Thma branch is handed half the length the other two get, and
 * the intermediate lengths truncate while only the outer square root rounds.
 * Anyone reading this beside the study they already run needs the same line.
 *
 * Deliberately not offered, because nothing here could back them: a line
 * thickness input (`style.lineWidth` is static and there is no width settings
 * key), a band transparency input (`opacity` is a fixed number on the fill spec,
 * not a settings key), and a higher-timeframe mode (`calc` is handed the chart's
 * own bars and has no way to request another resolution).
 */
export const HULL_SUITE: IndicatorDescriptor = {
  id: 'hull-suite',
  name: 'Hull Suite',
  category: 'Trend',
  placement: 'onchart',
  inputs: [
    { key: 'source', type: 'source', label: 'Source', default: 'close' },
    {
      key: 'mode', type: 'select', label: 'Variation', default: 'Hma',
      options: [
        { label: 'HMA', value: 'Hma' },
        { label: 'THMA', value: 'Thma' },
        { label: 'EHMA', value: 'Ehma' },
      ],
    },
    { key: 'length', type: 'number', label: 'Length', default: 55, min: 1, max: 1000, step: 1 },
    { key: 'lengthMult', type: 'number', label: 'Length Multiplier', default: 1, min: 0.1, max: 10, step: 0.1 },
    { key: 'switchColor', type: 'boolean', label: 'Color Hull By Trend', default: true },
    { key: 'candleCol', type: 'boolean', label: 'Color Candles By Trend', default: false },
    { key: 'visualSwitch', type: 'boolean', label: 'Show Band', default: true },
    { key: 'bullishColor', type: 'color', label: 'Bullish Color', default: HULL_BULLISH },
    { key: 'bearishColor', type: 'color', label: 'Bearish Color', default: HULL_BEARISH },
    { key: 'neutralColor', type: 'color', label: 'Neutral Color', default: HULL_NEUTRAL },
  ],
  plots: [
    {
      key: 'mhull', type: 'line', title: 'Hull',
      // The neutral colour is the honest static fallback: it is what both lines
      // wear when the trend colouring is switched off. `colorBy` wins bar by bar.
      colorKey: 'neutralColor', style: { color: HULL_NEUTRAL, lineWidth: 2 },
      colorBy: ({ index, values, settings }) => hullTrendColor(values.mhull, index, settings),
    },
    {
      key: 'shull', type: 'line', title: 'Hull Displaced',
      colorKey: 'neutralColor', style: { color: HULL_NEUTRAL, lineWidth: 2 },
      colorBy: ({ index, values, settings }) => hullTrendColor(values.mhull, index, settings),
    },
  ],
  fills: [{
    between: ['mhull', 'shull'],
    colorUp: HULL_BULLISH,
    colorDown: HULL_BEARISH,
    colorUpKey: 'bullishColor',
    colorDownKey: 'bearishColor',
    // Not CHANNEL_FILL_OPACITY: those bands are a hint around a line that
    // carries the reading, whereas here the band is the reading and a 5 %
    // wash would erase it.
    opacity: 0.6,
  }],
  calc: (bars, s) => {
    const values = sourceValues(bars, src(s));
    const len = span(int(s, 'length', 55) * num(s, 'lengthMult', 1));
    const hull = hullSeries(values, str(s, 'mode', 'Hma'), len);
    // The displaced copy and its band are one control, so they have to vanish
    // together: a lone line hanging two bars behind the hull reads as a second
    // average, which is the one thing this plot is not.
    const band = s.visualSwitch !== false;
    return {
      mhull: nulls(hull),
      shull: nulls(band ? shift(hull, 2) : new Array<number>(hull.length).fill(NaN)),
    };
  },
  barColors: ({ bars, values, settings }) => (
    settings.candleCol === true
      ? bars.map((_, i) => hullTrendColor(values.mhull, i, settings))
      : bars.map(() => null)
  ),
};

export const OVERLAY_INDICATORS: readonly IndicatorDescriptor[] = [
  ALMA, DEMA, HMA, ENVELOPE, DONCHIAN, CHANDE_KROLL_STOP, CHANDELIER_EXIT,
  STANDARD_ERROR_BANDS, MA_CHANNEL, HULL_SUITE,
];
