/**
 * Built-ins: two adaptive averages, a volatility channel, and two
 * oscillators, all specified against the published reference definitions rather than this
 * library's own. Part of the lazy `openalgo-charts/indicators` tier.
 *
 * Parity note, and the reason `ema` is absent from the imports: the reference `ema`
 * seeds from the SMA of the first `length` values and is `na` before that, while
 * the base bundle's `ema` seeds from `values[0]` and emits from bar 0 to match
 * `openalgo.ta`. The two disagree across the whole warmup, so anything that has
 * to land on the same pixels as a reference platform plot uses `smaSeededEma` from `./calc`.
 *
 * `atr`, `trueRange`, and the `sourceValues` helper come from the base bundle
 * (`openalgo-charts`), not deep paths. See the note in `src/indicators/index.ts`.
 */
import { atr, trueRange, sourceValues, sourceValue } from 'openalgo-charts';
import type { IndicatorDescriptor } from 'openalgo-charts';
import { sma, rma, nulls, smaSeededEma, change, roc, rollingSum, linreg } from './calc';
import { emaOfGapped } from './smoothing';
import { withTail, machineTail, whole, cell } from './tail';
import { seeded, smooth, wilder, atrStep, trueRangeAt, meanAt } from './steppers';
import { withTimeframe } from './timeframe';
import { num, int, offsetOf, str, flag, src } from './settings';
import { zip } from './series';

/**
 * Kaufman's Adaptive Moving Average: an EMA whose smoothing constant is chosen
 * bar by bar from how *directed* the recent move was.
 *
 * The efficiency ratio divides the net distance travelled over `erLength` bars by
 * the total path walked to get there. A clean trend covers ground in a straight
 * line and scores near 1, which pulls the smoothing toward the fast alpha and the
 * average onto price; chop retraces itself, scores near 0, and the average all but
 * stops. Squaring the interpolated alpha is what makes that transition abrupt
 * rather than linear, so KAMA sits flat through noise instead of drifting.
 *
 * The reference delegates to `an external `kama()` helper`, whose body is not in the file, so
 * this follows Kaufman's published definition. It first prints at `erLength`, the
 * earliest bar where both legs of the ratio exist, seeded there on the source
 * itself, because there is no prior average to carry forward.
 */
export const KAMA: IndicatorDescriptor = withTimeframe({
  id: 'kama',
  name: "Kaufman's Adaptive Moving Average",
  category: 'Trend',
  placement: 'onchart',
  inputs: [
    { key: 'erLength', type: 'number', label: 'ER Length', default: 10, min: 1, max: 1000, step: 1 },
    { key: 'fastLength', type: 'number', label: 'Fast Length', default: 2, min: 1, max: 1000, step: 1 },
    { key: 'slowLength', type: 'number', label: 'Slow Length', default: 30, min: 1, max: 1000, step: 1 },
    { key: 'source', type: 'source', label: 'Source', default: 'close' },
    { key: 'color', type: 'color', label: 'KAMA', default: '#2962ff' },
  ],
  plots: [{
    key: 'kama', type: 'line', title: 'KAMA', colorKey: 'color',
    style: { color: '#2962ff', lineWidth: 1.5 },
  }],
  calc: (bars, s) => {
    const values = sourceValues(bars, src(s));
    const n = values.length;
    const erLength = int(s, 'erLength', 10);
    const out = new Array<number>(n).fill(NaN);
    if (n <= erLength) return { kama: nulls(out) };

    // This path calculation treats nonfinite steps, including bar 0's missing
    // predecessor, as zero contribution. By the first path read, the initial
    // placeholder has left the rolling window. Every series here holds one
    // value per bar, and there are more than `erLength` of them.
    const steps = change(values, 1);
    for (let i = 0; i < n; i++) steps[i] = Number.isFinite(steps[i]) ? Math.abs(steps[i]!) : 0;
    const path = rollingSum(steps, erLength);
    const travel = change(values, erLength);

    const fastAlpha = 2 / (int(s, 'fastLength', 2) + 1);
    const slowAlpha = 2 / (int(s, 'slowLength', 30) + 1);

    let prev = values[erLength]!;
    out[erLength] = prev;
    for (let i = erLength + 1; i < n; i++) {
      const walked = path[i]!;
      // A window that never moved has no direction to measure; Kaufman's rule is
      // to treat that as maximally inefficient rather than as a division by zero.
      const er = Number.isFinite(walked) && walked !== 0 ? Math.abs(travel[i]!) / walked : 0;
      const alpha = er * (fastAlpha - slowAlpha) + slowAlpha;
      prev += alpha * alpha * (values[i]! - prev);
      out[i] = prev;
    }
    return { kama: nulls(out) };
  },
});

/**
 * the reference fills the channel with `color.rgb(33, 150, 243, 95)`, 95 % transparent, so
 * the band is a hint rather than a wash. Kept as-is so the overlay reads the same
 * here as on the reference platform.
 */
const CHANNEL_FILL_OPACITY = 0.05;

/**
 * Keltner Channels: a moving average with volatility rails, where the rail width
 * is a range measure rather than a standard deviation. That is the whole point of
 * the study: Bollinger's bands widen on *dispersion of closes*, Keltner's on how
 * much ground each bar actually covers, so the two disagree exactly when a market
 * gaps or trends in one direction without spreading its closes out.
 *
 * Three rail sources are offered because they answer different questions. ATR (the
 * default) smooths the range over its own `atrlength`, so the rails breathe slowly.
 * True Range uses the raw bar, so a single wide bar throws the rails out on that
 * bar alone. Range is Wilder-smoothed high-minus-low over the channel `length`,
 * ignoring gaps entirely. Each has its own warmup, and the plotted band starts at
 * whichever of the rail and the basis is slower.
 */
export const KELTNER_CHANNEL: IndicatorDescriptor = withTimeframe(withTail({
  id: 'keltner-channel',
  name: 'Keltner Channels',
  category: 'Volatility',
  placement: 'onchart',
  inputs: [
    { key: 'length', type: 'number', label: 'Length', default: 20, min: 1, max: 1000, step: 1 },
    { key: 'mult', type: 'number', label: 'Multiplier', default: 2, min: 0.1, max: 50, step: 0.1 },
    { key: 'source', type: 'source', label: 'Source', default: 'close' },
    { key: 'exp', type: 'boolean', label: 'Use Exponential MA', default: true },
    {
      key: 'bandsStyle', type: 'select', label: 'Bands Style', default: 'Average True Range',
      options: [
        { label: 'Average True Range', value: 'Average True Range' },
        { label: 'True Range', value: 'True Range' },
        { label: 'Range', value: 'Range' },
      ],
    },
    { key: 'atrlength', type: 'number', label: 'ATR Length', default: 10, min: 1, max: 1000, step: 1 },
    { key: 'basisColor', type: 'color', label: 'Basis', default: '#2962ff' },
    { key: 'bandColor', type: 'color', label: 'Bands', default: '#2962ff' },
    { key: 'fillColor', type: 'color', label: 'Background', default: '#2196f3' },
  ],
  plots: [
    { key: 'upper', type: 'line', title: 'Upper', colorKey: 'bandColor', style: { color: '#2962ff', lineWidth: 1 } },
    { key: 'basis', type: 'line', title: 'Basis', colorKey: 'basisColor', style: { color: '#2962ff', lineWidth: 1.5 } },
    { key: 'lower', type: 'line', title: 'Lower', colorKey: 'bandColor', style: { color: '#2962ff', lineWidth: 1 } },
  ],
  fills: [{
    between: ['upper', 'lower'],
    colorUpKey: 'fillColor',
    colorDownKey: 'fillColor',
    opacity: CHANNEL_FILL_OPACITY,
  }],
  calc: (bars, s) => {
    const n = bars.length;
    const length = int(s, 'length', 20);
    const mult = num(s, 'mult', 2);
    const values = sourceValues(bars, src(s));
    const basis = flag(s, 'exp', true) ? smaSeededEma(values, length) : sma(values, length);

    const high = bars.map((b) => b.high);
    const low = bars.map((b) => b.low);
    const close = bars.map((b) => b.close);
    const style = str(s, 'bandsStyle', 'Average True Range');
    let rail: number[];
    if (style === 'True Range') {
      // the reference `tr(true)`: the first bar falls back to high - low rather than
      // going `na`, which is exactly what the shared `trueRange` already does.
      rail = trueRange(high, low, close);
    } else if (style === 'Range') {
      rail = rma(zip(high, low, (h, l) => h - l), length);
    } else {
      rail = atr(high, low, close, int(s, 'atrlength', 10));
    }

    const upper = new Array<number>(n).fill(NaN);
    const lower = new Array<number>(n).fill(NaN);
    // Every rail and the basis hold one value per bar.
    for (let i = 0; i < n; i++) {
      const offset = rail[i]! * mult;
      upper[i] = basis[i]! + offset;
      lower[i] = basis[i]! - offset;
    }
    return { upper: nulls(upper), basis: nulls(basis), lower: nulls(lower) };
  },
}, (calc) => (bars, s, from, previous, store) => {
  const length = int(s, 'length', 20);
  const atrLength = int(s, 'atrlength', 10);
  if (!whole(length) || !whole(atrLength)) return null;
  const mult = num(s, 'mult', 2);
  const source = src(s);
  const exp = flag(s, 'exp', true);
  const style = str(s, 'bandsStyle', 'Average True Range');
  // Read at `i` and, once `i` has warmed up, over the whole window before it.
  const at = (j: number): number => sourceValue(bars[j]!, source);
  return machineTail(calc, `${length}|${atrLength}|${mult}|${source}|${exp}|${style}`, {
    keys: ['upper', 'basis', 'lower'],
    start: () => ({ basis: seeded(), range: seeded(), atr: wilder() }),
    step: (st, i, row) => {
      const bar = bars[i]!;
      const basis = exp ? smooth(st.basis, at(i), length, true) : meanAt(at, i, length);
      const rail = style === 'True Range' ? trueRangeAt(bars, i)
        : style === 'Range' ? smooth(st.range, bar.high - bar.low, length, false)
          : atrStep(st.atr, trueRangeAt(bars, i), atrLength);
      const offset = rail * mult;
      row[0] = cell(basis + offset);
      row[1] = cell(basis);
      row[2] = cell(basis - offset);
    },
  }, bars, from, previous, store);
}));

/**
 * Least Squares Moving Average: the endpoint of a least-squares line fitted over
 * the last `length` bars, so unlike an SMA it has no lag against a straight trend:
 * fit a line to a line and you get the line back.
 *
 * `offset` steps back down that same fitted line rather than re-fitting, which is
 * why it can shift the plot without changing its shape. See the x-axis convention
 * on `linreg` in `./calc`: x is 0 at the oldest bar of the window.
 */
export const LSMA: IndicatorDescriptor = withTimeframe({
  id: 'lsma',
  name: 'Least Squares Moving Average',
  category: 'Trend',
  placement: 'onchart',
  inputs: [
    { key: 'length', type: 'number', label: 'Length', default: 25, min: 2, max: 1000, step: 1 },
    { key: 'offset', type: 'number', label: 'Offset', default: 0, min: -500, max: 500, step: 1 },
    { key: 'source', type: 'source', label: 'Source', default: 'close' },
    { key: 'color', type: 'color', label: 'LSMA', default: '#2962ff' },
  ],
  plots: [{
    key: 'lsma', type: 'line', title: 'LSMA', colorKey: 'color',
    style: { color: '#2962ff', lineWidth: 1.5 },
  }],
  calc: (bars, s) => ({
    lsma: nulls(linreg(
      sourceValues(bars, src(s)),
      int(s, 'length', 25, 2),
      offsetOf(s, 'offset', 0),
    )),
  }),
});

// the reference hard-codes the Klinger periods; the reference exposes no inputs for them,
// so neither does this descriptor.
const KLINGER_FAST = 34;
const KLINGER_SLOW = 55;
const KLINGER_SIGNAL = 13;

/**
 * Klinger Oscillator: volume signed by the direction of the typical price, then
 * read as a MACD-style spread of two EMAs. Signing is what separates it from a
 * plain volume study: a heavy bar only counts as accumulation if `hlc3` actually
 * rose, so churn at an unchanged price nets out instead of registering as force.
 *
 * Two chained warmups stack here. The slow leg cannot print before bar 54, so the
 * spread cannot either; the signal EMA then runs over a series that is `na` up to
 * that point and the reference re-seeds it from an SMA, pushing its first bar a further
 * `KLINGER_SIGNAL - 1` out. See `emaOfGapped`.
 */
export const KLINGER_OSCILLATOR: IndicatorDescriptor = {
  id: 'klinger-oscillator',
  name: 'Klinger Oscillator',
  category: 'Volume',
  placement: 'pane',
  inputs: [
    { key: 'kvoColor', type: 'color', label: 'Klinger Oscillator', default: '#2962ff' },
    { key: 'signalColor', type: 'color', label: 'Signal', default: '#43a047' },
  ],
  plots: [
    {
      key: 'kvo', type: 'line', title: 'Klinger Oscillator', colorKey: 'kvoColor',
      style: { color: '#2962ff', lineWidth: 1.5 },
    },
    {
      key: 'signal', type: 'line', title: 'Signal', colorKey: 'signalColor',
      style: { color: '#43a047', lineWidth: 1.5 },
    },
  ],
  calc: (bars) => {
    const n = bars.length;
    const step = change(sourceValues(bars, 'hlc3'), 1);
    const signed = new Array<number>(n);
    // `step`, `fast` and `slow` hold one value per bar.
    for (let i = 0; i < n; i++) {
      const volume = bars[i]!.volume ?? 0;
      // Bar 0 has no change to test. the reference compares `na >= 0` and gets false, so
      // the first bar's volume is signed negative; `NaN >= 0` is false here too,
      // which reproduces that without a special case.
      signed[i] = step[i]! >= 0 ? volume : -volume;
    }
    const fast = smaSeededEma(signed, KLINGER_FAST);
    const slow = smaSeededEma(signed, KLINGER_SLOW);
    const kvo = new Array<number>(n).fill(NaN);
    for (let i = 0; i < n; i++) kvo[i] = fast[i]! - slow[i]!;
    return { kvo: nulls(kvo), signal: nulls(emaOfGapped(kvo, KLINGER_SIGNAL)) };
  },
  // The reference plots no explicit hline, but the oscillator carries no scale of
  // its own and is read entirely by which side of zero it sits on.
  levels: () => [{ price: 0, color: '#787b86', title: 'Zero', dashed: true }],
};

/**
 * Know Sure Thing: four rate-of-change readings taken over lengthening horizons,
 * each smoothed, then summed with weights 1/2/3/4 so the slowest cycle dominates.
 * The point is that a single ROC is a statement about one horizon; KST asks
 * whether short, medium, and long momentum agree, and weights the answer toward
 * the horizon least likely to be noise.
 *
 * Every term carries its own warmup and the sum is only real once the slowest one
 * is. With the defaults that is bar 44, `roclen4 + smalen4 - 1`. The signal SMA
 * then runs over a series with that gap in front of it, so it starts `siglen - 1`
 * bars later again; `sma` in `./calc` refuses any window holding a warmup slot,
 * which is what makes both boundaries fall where the reference puts them.
 */
export const KNOW_SURE_THING: IndicatorDescriptor = {
  id: 'know-sure-thing',
  name: 'Know Sure Thing',
  category: 'Momentum',
  placement: 'pane',
  inputs: [
    { key: 'roclen1', type: 'number', label: 'ROC Length #1', default: 10, min: 1, max: 1000, step: 1 },
    { key: 'roclen2', type: 'number', label: 'ROC Length #2', default: 15, min: 1, max: 1000, step: 1 },
    { key: 'roclen3', type: 'number', label: 'ROC Length #3', default: 20, min: 1, max: 1000, step: 1 },
    { key: 'roclen4', type: 'number', label: 'ROC Length #4', default: 30, min: 1, max: 1000, step: 1 },
    { key: 'smalen1', type: 'number', label: 'SMA Length #1', default: 10, min: 1, max: 1000, step: 1 },
    { key: 'smalen2', type: 'number', label: 'SMA Length #2', default: 10, min: 1, max: 1000, step: 1 },
    { key: 'smalen3', type: 'number', label: 'SMA Length #3', default: 10, min: 1, max: 1000, step: 1 },
    { key: 'smalen4', type: 'number', label: 'SMA Length #4', default: 15, min: 1, max: 1000, step: 1 },
    { key: 'siglen', type: 'number', label: 'Signal Line Length', default: 9, min: 1, max: 1000, step: 1 },
    { key: 'kstColor', type: 'color', label: 'KST', default: '#009688' },
    { key: 'signalColor', type: 'color', label: 'Signal', default: '#f44336' },
  ],
  plots: [
    { key: 'kst', type: 'line', title: 'KST', colorKey: 'kstColor', style: { color: '#009688', lineWidth: 1.5 } },
    {
      key: 'signal', type: 'line', title: 'Signal', colorKey: 'signalColor',
      style: { color: '#f44336', lineWidth: 1.5 },
    },
  ],
  calc: (bars, s) => {
    const n = bars.length;
    const closes = sourceValues(bars, 'close');
    const term = (rocKey: string, rocDefault: number, smaKey: string, smaDefault: number): number[] =>
      sma(roc(closes, int(s, rocKey, rocDefault)), int(s, smaKey, smaDefault));

    const first = term('roclen1', 10, 'smalen1', 10);
    const second = term('roclen2', 15, 'smalen2', 10);
    const third = term('roclen3', 20, 'smalen3', 10);
    const fourth = term('roclen4', 30, 'smalen4', 15);

    const kst = new Array<number>(n).fill(NaN);
    // Each term holds one value per bar.
    for (let i = 0; i < n; i++) {
      kst[i] = first[i]! + 2 * second[i]! + 3 * third[i]! + 4 * fourth[i]!;
    }
    return { kst: nulls(kst), signal: nulls(sma(kst, int(s, 'siglen', 9))) };
  },
  levels: () => [{ price: 0, color: '#787b86', title: 'Zero', dashed: true }],
};

/**
 * Linear Regression Slope: the gradient of the least-squares line fitted over the
 * last `periods` closes, in price per bar.
 *
 * It asks a different question from LSMA, which plots where that same line ends.
 * Dropping the level and keeping only the gradient is what lets the study say
 * that an advance is still an advance but no longer as steep, at a bar where
 * price itself is making a new high. Zero is the whole reading: above it the fit
 * rises, below it the fit falls.
 *
 * The x axis is unit-spaced and the reference scales the result by nothing, so
 * the answer is per bar rather than per window. Only that spacing matters: a
 * least-squares slope is unchanged by shifting x, so running x from 1 to
 * `periods` (the reference's own convention, newest bar highest) and running it
 * from 0 give the identical number.
 */
export const LINREG_SLOPE: IndicatorDescriptor = {
  id: 'linreg-slope',
  name: 'Linear Regression Slope',
  category: 'Trend',
  placement: 'pane',
  inputs: [
    { key: 'periods', type: 'number', label: 'Periods', default: 14, min: 2, max: 1000, step: 1 },
    { key: 'color', type: 'color', label: 'Slope', default: '#ff5252' },
  ],
  plots: [{
    key: 'slope', type: 'line', title: 'Slope', colorKey: 'color',
    style: { color: '#ff5252', lineWidth: 1.5 },
  }],
  calc: (bars, s) => {
    const values = sourceValues(bars, 'close');
    const n = values.length;
    const period = int(s, 'periods', 14, 2);
    const out = new Array<number>(n).fill(NaN);
    const sumX = (period * (period + 1)) / 2;
    // The window is the same shape on every bar, so the x sums are loop-invariant.
    // This is the closed form of `period * sum(x^2) - sum(x)^2` over x = 1..period,
    // and it is only zero at period 1, which the input floor rules out.
    const denom = (period * period * (period * period - 1)) / 12;
    for (let i = period - 1; i < n; i++) {
      let sumY = 0;
      let sumXY = 0;
      for (let k = 0; k < period; k++) {
        const y = values[i - k]!;
        sumY += y;
        sumXY += y * (period - k);
      }
      out[i] = (period * sumXY - sumX * sumY) / denom;
    }
    return { slope: nulls(out) };
  },
  // The reference declares no band, but the study carries no scale of its own and
  // is read entirely by which side of zero the gradient sits on.
  levels: () => [{ price: 0, color: '#787b86', title: 'Zero', dashed: true }],
};

export const ADAPTIVE_INDICATORS: readonly IndicatorDescriptor[] = [
  KAMA, KELTNER_CHANNEL, LSMA, KLINGER_OSCILLATOR, KNOW_SURE_THING, LINREG_SLOPE,
];
