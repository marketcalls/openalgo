/**
 * the reference platform's built-in volatility studies, reproduced from their published
 * the reference sources. Part of the lazy `openalgo-charts/indicators` tier.
 *
 * These are read side by side with a reference platform chart, so warmup is part of
 * the contract: a plot that starts one bar early is as wrong as one that
 * computes the wrong number. Everything here therefore goes through the
 * the reference-compatible helpers in `./calc` (`smaSeededEma` seeds from the SMA, the base
 * bundle's `ema` seeds from the first bar) and returns `null`, not a guessed
 * value, wherever the reference would return `na`.
 */
import { trueRange, sourceValues } from 'openalgo-charts';
import type { IndicatorDescriptor } from 'openalgo-charts';
import { sma, stdev, highest, lowest, nulls, smaSeededEma, rollingSum, roc, linreg, standardError } from './calc';
import { withTail, windowTail } from './tail';
import { num, int, offsetOf, str, src } from './settings';
import { shift } from './series';

/**
 * the reference `color.new(c, t)` transparency, where 0 is opaque and 100 invisible.
 * Emitted as an 8-digit hex, which canvas `fillStyle` accepts directly.
 */
function withAlphaPercent(hex: string, transparency: number): string {
  const a = Math.round(255 * (1 - transparency / 100));
  return `${hex}${a.toString(16).padStart(2, '0')}`;
}

/**
 * the reference `bb`: an SMA basis with symmetric `mult` **population** standard
 * deviations either side. Three of the studies below are different readings of
 * the same three numbers, so they share one construction rather than each
 * re-deriving the basis.
 *
 * The calc helpers return one value per input, so in this file every series
 * derived from the bars is read at a bar index alongside the bars themselves.
 */
function bands(values: readonly number[], length: number, mult: number): {
  middle: number[]; upper: number[]; lower: number[];
} {
  const n = values.length;
  const middle = sma(values, length);
  const dev = stdev(values, length);
  const upper = new Array<number>(n);
  const lower = new Array<number>(n);
  for (let i = 0; i < n; i++) {
    const d = mult * dev[i]!;
    upper[i] = middle[i]! + d;
    lower[i] = middle[i]! - d;
  }
  return { middle, upper, lower };
}

/**
 * Bollinger Bands %b: where the source sits inside its own bands, rescaled so
 * the lower band is 0 and the upper is 1. Unbounded on purpose: the reading
 * only becomes interesting once it leaves 0..1, which is why the pane declares
 * no fixed range.
 */
export const BOLLINGER_PERCENT_B: IndicatorDescriptor = {
  id: 'bollinger-percent-b',
  name: 'Bollinger Bands %b',
  category: 'Volatility',
  placement: 'pane',
  inputs: [
    { key: 'length', type: 'number', label: 'Length', default: 20, min: 1, max: 2000, step: 1 },
    { key: 'source', type: 'source', label: 'Source', default: 'close' },
    { key: 'mult', type: 'number', label: 'StdDev', default: 2, min: 0.001, max: 50, step: 0.1 },
    { key: 'color', type: 'color', label: 'Bollinger Bands %b', default: '#2962ff' },
    { key: 'fillColor', type: 'color', label: 'Middle Background', default: '#2962ff' },
  ],
  plots: [{ key: 'percentB', type: 'line', title: 'Bollinger Bands %b', colorKey: 'color', style: { lineWidth: 1.5 } }],
  // The 1..0 shading sits between two reference lines rather than two series, so
  // its edges are constant columns carrying no plot. One colour on both sides:
  // a level band has no up or down side to tell apart.
  fills: [{ between: ['bandHigh', 'bandLow'], colorUpKey: 'fillColor', colorDownKey: 'fillColor', opacity: 0.1 }],
  calc: (bars, s) => {
    const values = sourceValues(bars, src(s));
    const { upper, lower } = bands(values, int(s, 'length', 20), num(s, 'mult', 2));
    const out = new Array<number>(values.length);
    for (let i = 0; i < values.length; i++) {
      const span = upper[i]! - lower[i]!;
      // A flat window collapses the bands onto the basis; the reference 0/0 is `na`,
      // and any finite answer we invented here would be a fabricated signal.
      out[i] = span > 0 ? (values[i]! - lower[i]!) / span : NaN;
    }
    // Never null, warmup included: the band is drawn across the whole pane, so
    // its edges have to exist on bars where the study prints nothing.
    return {
      percentB: nulls(out),
      bandHigh: new Array<number>(bars.length).fill(1),
      bandLow: new Array<number>(bars.length).fill(0),
    };
  },
  levels: () => [
    { price: 1, color: '#f23645', title: 'Overbought', dashed: true },
    { price: 0.5, color: '#2962ff', title: 'Middle Band' },
    { price: 0, color: '#089981', title: 'Oversold', dashed: true },
  ],
};

/**
 * Bollinger BandWidth: the band spread as a percentage of the basis, so it is
 * comparable across instruments and across price levels.
 *
 * The two companion plots are rolling extremes **of the bandwidth itself**, not
 * of price: they turn "is this narrow?" from a judgement call into a comparison
 * against the last N bars of the same series.
 */
export const BOLLINGER_BANDWIDTH: IndicatorDescriptor = {
  id: 'bollinger-bandwidth',
  name: 'Bollinger BandWidth',
  category: 'Volatility',
  placement: 'pane',
  inputs: [
    { key: 'length', type: 'number', label: 'Length', default: 20, min: 1, max: 2000, step: 1 },
    { key: 'source', type: 'source', label: 'Source', default: 'close' },
    { key: 'mult', type: 'number', label: 'StdDev', default: 2, min: 0.001, max: 50, step: 0.1 },
    {
      key: 'expansionLength', type: 'number', label: 'Highest Expansion Length', default: 125, min: 1, max: 5000, step: 1,
      tooltip: 'Bars searched for the widest bandwidth reading, drawn as the upper reference line.',
    },
    {
      key: 'contractionLength', type: 'number', label: 'Lowest Contraction Length', default: 125, min: 1, max: 5000, step: 1,
      tooltip: 'Bars searched for the narrowest bandwidth reading, drawn as the lower reference line. A squeeze is price sitting on it.',
    },
    { key: 'color', type: 'color', label: 'Bollinger BandWidth', default: '#2962ff' },
    { key: 'expansionColor', type: 'color', label: 'Highest Expansion', default: '#f23645' },
    { key: 'contractionColor', type: 'color', label: 'Lowest Contraction', default: '#089981' },
  ],
  plots: [
    // (upper - lower) / basis, times 100: a percentage of the basis, not a price.
    {
      key: 'bandwidth', type: 'line', title: 'Bollinger BandWidth', colorKey: 'color',
      style: { lineWidth: 1.5 }, priceFormat: { type: 'percent' },
    },
    { key: 'expansion', type: 'line', title: 'Highest Expansion', colorKey: 'expansionColor', style: { lineWidth: 1 } },
    { key: 'contraction', type: 'line', title: 'Lowest Contraction', colorKey: 'contractionColor', style: { lineWidth: 1 } },
  ],
  calc: (bars, s) => {
    const values = sourceValues(bars, src(s));
    const { middle, upper, lower } = bands(values, int(s, 'length', 20), num(s, 'mult', 2));
    const bbw = new Array<number>(values.length);
    for (let i = 0; i < values.length; i++) {
      bbw[i] = middle[i] === 0 ? NaN : ((upper[i]! - lower[i]!) / middle[i]!) * 100;
    }
    // `highest`/`lowest` compare, and a NaN loses every comparison, so the
    // bandwidth's own warmup is skipped rather than poisoning the window: the
    // extremes appear as soon as the lookback is long enough and something
    // finite has entered it, which is where the reference platform starts drawing them.
    // A window holding nothing finite yields +/-Infinity, which `nulls` gaps.
    return {
      bandwidth: nulls(bbw),
      expansion: nulls(highest(bbw, int(s, 'expansionLength', 125))),
      contraction: nulls(lowest(bbw, int(s, 'contractionLength', 125))),
    };
  },
};

/**
 * BBTrend: a short and a long Bollinger set compared band for band. When the
 * short set's lower band has pulled further from the long set's lower band than
 * the two upper bands have separated, the short-term range is expanding
 * downward and the reading is negative; the reverse is positive. Normalised by
 * the short basis so it reads as a percentage.
 */
export const BB_TREND: IndicatorDescriptor = {
  id: 'bb-trend',
  name: 'BBTrend',
  category: 'Volatility',
  placement: 'pane',
  inputs: [
    { key: 'shortLength', type: 'number', label: 'Short BB Length', default: 20, min: 1, max: 2000, step: 1 },
    { key: 'longLength', type: 'number', label: 'Long BB Length', default: 50, min: 1, max: 2000, step: 1 },
    { key: 'stdDevMult', type: 'number', label: 'StdDev', default: 2, min: 0.001, max: 50, step: 0.1 },
    { key: 'posColor', type: 'color', label: 'Above zero', default: '#089981' },
    { key: 'negColor', type: 'color', label: 'Below zero', default: '#f23645' },
  ],
  plots: [
    {
      key: 'bbtrend', type: 'column', title: 'BBTrend', colorKey: 'posColor',
      style: { base: 0 },
      // Four states, as in the reference switch: the sign says which side of zero,
      // the step against the previous bar says whether it is building or
      // fading. The switch has no `na` arm, so the first bar (and an exact
      // zero) falls through to the weak positive colour, reproduced here by
      // treating a missing previous value as "no state".
      colorBy: ({ value, index, values, settings }) => {
        const prev = values.bbtrend?.[index - 1];
        const hasPrev = typeof prev === 'number' && Number.isFinite(prev);
        // the reference paints two base colours at two transparencies (25 strengthening,
        // 50 weakening) rather than four distinct hues, so the strength is alpha.
        // Keeping the inputs at 6-digit hex leaves them pickable in a settings
        // dialog's colour control, which an 8-digit value would break.
        if (hasPrev && value > 0) {
          return withAlphaPercent(str(settings, 'posColor', '#089981'), value >= prev ? 25 : 50);
        }
        if (hasPrev && value < 0) {
          return withAlphaPercent(str(settings, 'negColor', '#f23645'), value > prev ? 50 : 25);
        }
        return withAlphaPercent(str(settings, 'posColor', '#089981'), 50);
      },
    },
  ],
  calc: (bars, s) => {
    const closes = bars.map((b) => b.close);
    const mult = num(s, 'stdDevMult', 2);
    const short = bands(closes, int(s, 'shortLength', 20), mult);
    const long = bands(closes, int(s, 'longLength', 50), mult);
    const out = new Array<number>(closes.length);
    for (let i = 0; i < closes.length; i++) {
      const spread = Math.abs(short.lower[i]! - long.lower[i]!) - Math.abs(short.upper[i]! - long.upper[i]!);
      out[i] = short.middle[i] === 0 ? NaN : (spread / short.middle[i]!) * 100;
    }
    return { bbtrend: nulls(out) };
  },
  levels: () => [{ price: 0, color: '#5a6b8c', title: 'Zero line', dashed: true }],
};

/**
 * Choppiness Index: how much ground the bar-by-bar travel covers compared with
 * the net range it produced. A market that retraces everything spends the full
 * `length` bars of true range inside one range and reads near 100; a trend
 * covers the same range in a fraction of the travel and reads low.
 *
 * the reference writes the numerator as `sum(atr(1), length)`. `atr(1)` is
 * `rma(tr, 1)`, which is the true range itself, so this is a plain rolling sum
 * of true range, including bar 0, where the reference true range is `high - low`.
 */
export const CHOPPINESS_INDEX: IndicatorDescriptor = {
  id: 'choppiness-index',
  name: 'Choppiness Index',
  category: 'Volatility',
  placement: 'pane',
  inputs: [
    { key: 'length', type: 'number', label: 'Length', default: 14, min: 1, max: 2000, step: 1 },
    { key: 'offset', type: 'number', label: 'Offset', default: 0, min: -500, max: 500, step: 1 },
    { key: 'color', type: 'color', label: 'CHOP', default: '#2962ff' },
    { key: 'fillColor', type: 'color', label: 'Background', default: '#2196f3' },
  ],
  plots: [{ key: 'chop', type: 'line', title: 'CHOP', colorKey: 'color', style: { lineWidth: 1.5 } }],
  // Shaded between the two reference lines, not between two series, so the
  // edges are constant columns with no plot. One colour on both sides: a level
  // band has no up or down side to distinguish.
  fills: [{ between: ['bandHigh', 'bandLow'], colorUpKey: 'fillColor', colorDownKey: 'fillColor', opacity: 0.1 }],
  calc: (bars, s) => {
    const length = int(s, 'length', 14);
    const high = bars.map((b) => b.high);
    const low = bars.map((b) => b.low);
    const travel = rollingSum(trueRange(high, low, bars.map((b) => b.close)), length);
    // the reference bare `highest(length)` / `lowest(length)` default to `high`
    // and `low`, not to the chart source.
    const hi = highest(high, length);
    const lo = lowest(low, length);
    const scale = Math.log10(length);
    const out = new Array<number>(bars.length).fill(NaN);
    if (scale !== 0) {
      for (let i = 0; i < bars.length; i++) {
        const span = hi[i]! - lo[i]!;
        if (!(span > 0)) continue;
        const ratio = travel[i]! / span;
        if (!(ratio > 0)) continue;
        out[i] = (100 * Math.log10(ratio)) / scale;
      }
    }
    // The band edges are never null and never shifted: reference lines stay put
    // when the plot is offset, and the shading covers the pane during warmup.
    return {
      chop: nulls(shift(out, offsetOf(s, 'offset', 0))),
      bandHigh: new Array<number>(bars.length).fill(61.8),
      bandLow: new Array<number>(bars.length).fill(38.2),
    };
  },
  levels: () => [
    { price: 61.8, color: '#787b86', title: 'Upper Band', dashed: true },
    { price: 50, color: '#787b86', title: 'Middle Band' },
    { price: 38.2, color: '#787b86', title: 'Lower Band', dashed: true },
  ],
  range: () => ({ min: 0, max: 100 }),
};

/**
 * Historical Volatility: the annualised standard deviation of log returns.
 *
 * the reference derives the annualisation divisor from the chart's timeframe:
 * `per = timeframe.isintraday or (timeframe.isdaily and multiplier == 1) ? 1 : 7`.
 * A descriptor here is handed bars and settings and nothing else. It cannot
 * see the timeframe, and guessing one from bar spacing would silently change
 * the plot on a gappy or irregular series. So `per` is an input: leave it at 1
 * for intraday and daily charts, set it to 7 for weekly and above, which is
 * exactly the branch the reference takes.
 */
export const HISTORICAL_VOLATILITY: IndicatorDescriptor = {
  id: 'historical-volatility',
  name: 'Historical Volatility',
  category: 'Volatility',
  placement: 'pane',
  inputs: [
    { key: 'length', type: 'number', label: 'Length', default: 10, min: 1, max: 2000, step: 1 },
    {
      key: 'per', type: 'number', label: 'Days per bar unit', default: 1, min: 1, max: 365, step: 1,
      tooltip: 'Calendar days each bar covers, used to annualise: 1 for intraday and daily, 7 for weekly and above.',
    },
    { key: 'color', type: 'color', label: 'HV', default: '#2962ff' },
  ],
  // Annualised standard deviation of log returns, already multiplied by 100, so
  // the axis says so rather than leaving a bare 18.4 to be read as a price.
  plots: [{
    key: 'hv', type: 'line', title: 'HV', colorKey: 'color', style: { lineWidth: 1.5 },
    priceFormat: { type: 'percent' },
  }],
  calc: (bars, s) => {
    const n = bars.length;
    const per = num(s, 'per', 1);
    const annual = 365; // the reference hard-codes calendar days, not trading days.
    const returns = new Array<number>(n).fill(NaN);
    for (let i = 1; i < n; i++) {
      const prev = bars[i - 1]!.close;
      const curr = bars[i]!.close;
      returns[i] = prev > 0 && curr > 0 ? Math.log(curr / prev) : NaN;
    }
    // The first return is `na` (no prior close), and `stdev` refuses a window
    // holding one, so the first reading lands at `length`, not `length - 1`:
    // one bar later than a naive rolling window would put it, and where
    // the reference platform puts it.
    const dev = stdev(returns, int(s, 'length', 10));
    const factor = per > 0 ? Math.sqrt(annual / per) : NaN;
    return { hv: nulls(dev.map((v) => 100 * v * factor)) };
  },
};

/**
 * Average Daily Range: the mean high-to-low range over `length` bars. "Daily"
 * is the reference platform's name for it; the calculation is per bar, whatever the chart
 * timeframe is.
 */
export const AVERAGE_DAILY_RANGE: IndicatorDescriptor = {
  id: 'average-daily-range',
  name: 'Average Daily Range',
  category: 'Volatility',
  placement: 'pane',
  inputs: [
    { key: 'length', type: 'number', label: 'Length', default: 14, min: 1, max: 2000, step: 1 },
    { key: 'color', type: 'color', label: 'ADR', default: '#2962ff' },
  ],
  plots: [{ key: 'adr', type: 'line', title: 'ADR', colorKey: 'color', style: { lineWidth: 1.5 } }],
  calc: (bars, s) => ({
    adr: nulls(sma(bars.map((b) => b.high - b.low), int(s, 'length', 14))),
  }),
};

/** the reference `atan(1) * 4`, spelled out because the study's angles depend on it. */
const CHOP_ZONE_PI = Math.atan(1) * 4;
/** Both fixed in the reference source; Chop Zone exposes no numeric inputs at all. */
const CHOP_ZONE_PERIODS = 30;
const CHOP_ZONE_EMA_LENGTH = 34;

/**
 * Chop Zone: the slope of a 34-bar EMA, read as an angle and bucketed into a
 * nine-colour ladder from turquoise (steep rise) through yellow (flat) to dark
 * red (steep fall).
 *
 * The plot itself is a constant 1: every bar is the same height and all the
 * information is in the colour. That is not a stylistic choice we can improve
 * on: it is the study. The slope is made comparable across instruments by
 * `span`, which rescales it against the 30-bar range, so the angle means the
 * same thing on a 20-rupee stock and a 20000-point index.
 *
 * `angle` is returned as an unplotted column so `colorBy` can read it; the
 * ladder is a property of the bar, not of the value being plotted.
 */
export const CHOP_ZONE: IndicatorDescriptor = {
  id: 'chop-zone',
  name: 'Chop Zone',
  category: 'Volatility',
  placement: 'pane',
  inputs: [
    { key: 'turquoiseColor', type: 'color', label: 'Steep up', default: '#26c6da' },
    { key: 'darkGreenColor', type: 'color', label: 'Up', default: '#43a047' },
    { key: 'paleGreenColor', type: 'color', label: 'Mild up', default: '#a5d6a7' },
    { key: 'limeColor', type: 'color', label: 'Slight up', default: '#009688' },
    { key: 'yellowColor', type: 'color', label: 'Flat', default: '#fdd835' },
    { key: 'lightOrangeColor', type: 'color', label: 'Slight down', default: '#ffb74d' },
    { key: 'orangeColor', type: 'color', label: 'Mild down', default: '#ff6d00' },
    { key: 'redColor', type: 'color', label: 'Down', default: '#e91e63' },
    { key: 'darkRedColor', type: 'color', label: 'Steep down', default: '#d50000' },
  ],
  plots: [
    {
      key: 'chopZone', type: 'column', title: 'Chop Zone', colorKey: 'yellowColor',
      style: { base: 0 },
      // The reference ternary chain, flattened. Each rung is already bounded above
      // by the rung before it failing, so only one comparison per rung is left.
      // A missing angle takes the chain's final `else`, which is yellow, the
      // same colour the reference paints during warmup, when every `na` comparison is
      // false.
      colorBy: ({ index, values, settings }) => {
        const a = values.angle?.[index];
        if (a === null || a === undefined || !Number.isFinite(a)) return str(settings, 'yellowColor', '#fdd835');
        if (a >= 5) return str(settings, 'turquoiseColor', '#26c6da');
        if (a >= 3.57) return str(settings, 'darkGreenColor', '#43a047');
        if (a >= 2.14) return str(settings, 'paleGreenColor', '#a5d6a7');
        if (a >= 0.71) return str(settings, 'limeColor', '#009688');
        if (a <= -5) return str(settings, 'darkRedColor', '#d50000');
        if (a <= -3.57) return str(settings, 'redColor', '#e91e63');
        if (a <= -2.14) return str(settings, 'orangeColor', '#ff6d00');
        if (a <= -0.71) return str(settings, 'lightOrangeColor', '#ffb74d');
        return str(settings, 'yellowColor', '#fdd835');
      },
    },
  ],
  calc: (bars) => {
    const n = bars.length;
    const hi = highest(bars.map((b) => b.high), CHOP_ZONE_PERIODS);
    // Both extremes come off the highs in the reference, so `span` rescales
    // against the 30-bar range of the high series, not the high-low range.
    const lo = lowest(bars.map((b) => b.high), CHOP_ZONE_PERIODS);
    const ema34 = smaSeededEma(bars.map((b) => b.close), CHOP_ZONE_EMA_LENGTH);
    const angle = new Array<number>(n).fill(NaN);
    for (let i = 1; i < n; i++) {
      const range = hi[i]! - lo[i]!;
      const avg = (bars[i]!.high + bars[i]!.low + bars[i]!.close) / 3;
      if (!(range > 0) || avg === 0) continue;
      const span = (25 / range) * lo[i]!;
      // One bar wide, so the rise is the whole triangle: dy against dx of 1.
      // the reference measures the drop (previous EMA minus current), which makes an
      // advancing EMA negative here and positive after the sign flip below.
      const dy = ((ema34[i - 1]! - ema34[i]!) / avg) * span;
      if (!Number.isFinite(dy)) continue;
      const hyp = Math.sqrt(1 + dy * dy);
      const degrees = Math.round((180 * Math.acos(1 / hyp)) / CHOP_ZONE_PI);
      angle[i] = dy > 0 ? -degrees : degrees;
    }
    // the reference plots the constant on every bar, warmup included; only the colour
    // knows about the warmup.
    return { chopZone: new Array<number>(n).fill(1), angle: nulls(angle) };
  },
  range: () => ({ min: 0, max: 1 }),
};

/**
 * Chaikin Volatility: the rate of change of a smoothed high-to-low range, so it
 * answers "is the bar getting wider?" rather than "how wide is it?".
 *
 * The smoother is an EMA, not an SMA: an average of ranges reacts to a single
 * wide bar for `periods` bars and then drops it in one step, which prints a
 * spurious second move on the rate of change. Zero is the neutral reading, and
 * a zero denominator (a period of perfectly flat bars) has no rate of change to
 * report, so it stays a gap rather than becoming Infinity.
 */
export const CHAIKIN_VOLATILITY: IndicatorDescriptor = {
  id: 'chaikin-volatility',
  name: 'Chaikin Volatility',
  category: 'Volatility',
  placement: 'pane',
  inputs: [
    { key: 'periods', type: 'number', label: 'Periods', default: 10, min: 1, max: 2000, step: 1 },
    { key: 'rocLookback', type: 'number', label: 'Rate of Change Lookback', default: 10, min: 1, max: 2000, step: 1 },
    { key: 'color', type: 'color', label: 'Chaikin Volatility', default: '#ab47bc' },
  ],
  plots: [{ key: 'chaikinVolatility', type: 'line', title: 'Chaikin Volatility', colorKey: 'color', style: { lineWidth: 1.5 } }],
  calc: (bars, s) => ({
    chaikinVolatility: nulls(
      roc(smaSeededEma(bars.map((b) => b.high - b.low), int(s, 'periods', 10)), int(s, 'rocLookback', 10)),
    ),
  }),
  levels: () => [{ price: 0, color: '#787b86', title: 'Zero', dashed: true }],
};

/**
 * Standard Deviation: the population standard deviation of the close over
 * `periods` bars, scaled by `deviations` so it can be read as the same band
 * width a Bollinger set would draw.
 */
export const STANDARD_DEVIATION: IndicatorDescriptor = {
  id: 'standard-deviation',
  name: 'Standard Deviation',
  category: 'Volatility',
  placement: 'pane',
  inputs: [
    { key: 'periods', type: 'number', label: 'Periods', default: 5, min: 1, max: 2000, step: 1 },
    { key: 'deviations', type: 'number', label: 'Deviations', default: 1, min: 0.001, max: 50, step: 0.1 },
    { key: 'color', type: 'color', label: 'Standard Deviation', default: '#089981' },
  ],
  plots: [{ key: 'stdDev', type: 'line', title: 'Standard Deviation', colorKey: 'color', style: { lineWidth: 1.5 } }],
  calc: (bars, s) => {
    const mult = num(s, 'deviations', 1);
    return { stdDev: nulls(stdev(bars.map((b) => b.close), int(s, 'periods', 5)).map((v) => v * mult)) };
  },
};

/**
 * Standard Error: the residual spread of the closes about the least-squares
 * line fitted through them, which is what makes it an *error* rather than a
 * deviation. Two degrees of freedom go into the fitted slope and intercept, so
 * the divisor is `length - 2` and the input cannot go below 3.
 */
export const STANDARD_ERROR: IndicatorDescriptor = {
  id: 'standard-error',
  name: 'Standard Error',
  category: 'Volatility',
  placement: 'pane',
  inputs: [
    { key: 'length', type: 'number', label: 'Length', default: 14, min: 3, max: 2000, step: 1 },
    { key: 'color', type: 'color', label: 'Standard Error', default: '#ff6d00' },
  ],
  plots: [{ key: 'stdErr', type: 'line', title: 'Standard Error', colorKey: 'color', style: { lineWidth: 1.5 } }],
  calc: (bars, s) => {
    return { stdErr: nulls(standardError(bars.map((b) => b.close), int(s, 'length', 14, 3))) };
  },
};

/** A length for the squeeze: its momentum fits a line, which needs two points. */
const squeezeLength = (s: Readonly<Record<string, unknown>>): number => int(s, 'length', 20, 2);

/**
 * Volatility Squeeze: whether the Bollinger Bands have contracted inside the
 * Keltner Channel, the quiet stretch that tends to come before a move, and a
 * momentum histogram that says which way the move is leaning.
 *
 *   basis    = sma(close, length)
 *   bands    = basis +/- bbMult * stdev(close, length)
 *   channel  = basis +/- kcMult * sma(true range, length)
 *   on       = lower band > lower channel and upper band < upper channel
 *   momentum = linreg(close - ((highest(high, length) + lowest(low, length)) / 2 + basis) / 2, length)
 *
 * Both envelopes share one basis and one length, so the squeeze is either on
 * or off; `state` carries it (1 on, 0 off) for the dots on the zero line. The
 * state needs one window and prints from `length - 1`; the momentum fits a line
 * to `length` values that each read a window, so it prints from
 * `2 * length - 2`. The histogram is coloured by sign and by direction against
 * the previous bar, a missing previous bar reading as zero.
 */
export const VOLATILITY_SQUEEZE: IndicatorDescriptor = withTail({
  id: 'volatility-squeeze',
  name: 'Volatility Squeeze',
  category: 'Volatility',
  placement: 'pane',
  inputs: [
    { key: 'length', type: 'number', label: 'Length', default: 20, min: 2, max: 1000, step: 1 },
    { key: 'bbMult', type: 'number', label: 'BB StdDev', default: 2, min: 0.1, max: 10, step: 0.1 },
    { key: 'kcMult', type: 'number', label: 'KC Multiplier', default: 1.5, min: 0.1, max: 10, step: 0.1 },
    { key: 'upColor', type: 'color', label: 'Momentum up', default: '#26a69a' },
    { key: 'upFadeColor', type: 'color', label: 'Momentum up (weakening)', default: '#a7d8d2' },
    { key: 'downColor', type: 'color', label: 'Momentum down', default: '#ef5350' },
    { key: 'downFadeColor', type: 'color', label: 'Momentum down (weakening)', default: '#f5b0ae' },
    { key: 'onColor', type: 'color', label: 'Squeeze on', default: '#ff9800' },
    { key: 'offColor', type: 'color', label: 'Squeeze off', default: '#787b86' },
  ],
  plots: [
    {
      key: 'momentum', type: 'histogram', title: 'Momentum', colorKey: 'upColor',
      style: { color: '#26a69a', base: 0 },
      colorBy: ({ value, index, values, settings }) => {
        const prev = values.momentum?.[index - 1];
        const before = typeof prev === 'number' && Number.isFinite(prev) ? prev : 0;
        if (value > 0) return value > before ? str(settings, 'upColor', '#26a69a') : str(settings, 'upFadeColor', '#a7d8d2');
        return value < before ? str(settings, 'downColor', '#ef5350') : str(settings, 'downFadeColor', '#f5b0ae');
      },
    },
    {
      key: 'squeeze', type: 'line', title: 'Squeeze', colorKey: 'offColor',
      style: { color: '#787b86', markersOnly: true, markerRadius: 3 },
      colorBy: ({ index, values, settings }) =>
        values.state?.[index] === 1 ? str(settings, 'onColor', '#ff9800') : str(settings, 'offColor', '#787b86'),
    },
  ],
  calc: (bars, s) => {
    const n = bars.length;
    const length = squeezeLength(s);
    const high = bars.map((b) => b.high);
    const low = bars.map((b) => b.low);
    const close = bars.map((b) => b.close);
    const { middle, upper, lower } = bands(close, length, num(s, 'bbMult', 2));
    const range = sma(trueRange(high, low, close), length);
    const kcMult = num(s, 'kcMult', 1.5);
    const hh = highest(high, length);
    const ll = lowest(low, length);
    const delta = close.map((c, i) => c - ((hh[i]! + ll[i]!) / 2 + middle[i]!) / 2);
    const state = new Array<number | null>(n).fill(null);
    const squeeze = new Array<number | null>(n).fill(null);
    for (let i = 0; i < n; i++) {
      const rail = kcMult * range[i]!;
      const upperKc = middle[i]! + rail;
      const lowerKc = middle[i]! - rail;
      if (![upper[i], lower[i], upperKc, lowerKc].every(Number.isFinite)) continue;
      state[i] = lower[i]! > lowerKc && upper[i]! < upperKc ? 1 : 0;
      squeeze[i] = 0;
    }
    return { momentum: nulls(linreg(delta, length)), squeeze, state };
  },
}, (calc) => windowTail(calc, (s) => {
  // The momentum at a bar fits `length` values that each read `length` bars,
  // and a slice's first true range has no previous close, so it must fall
  // outside the last channel window: both hold at 2 * length - 2 for length 2 up.
  return 2 * squeezeLength(s) - 2;
}));

export const VOLATILITY_INDICATORS: readonly IndicatorDescriptor[] = [
  BOLLINGER_PERCENT_B,
  BOLLINGER_BANDWIDTH,
  BB_TREND,
  CHOPPINESS_INDEX,
  HISTORICAL_VOLATILITY,
  AVERAGE_DAILY_RANGE,
  CHOP_ZONE,
  CHAIKIN_VOLATILITY,
  STANDARD_DEVIATION,
  STANDARD_ERROR,
  VOLATILITY_SQUEEZE,
];
