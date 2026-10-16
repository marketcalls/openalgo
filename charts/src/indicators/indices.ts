/**
 * Built-in volume and volatility studies, ported from their
 * published reference definitions. Part of the lazy `openalgo-charts/indicators`
 * tier.
 *
 * These are reproductions, not inspirations: overlaying one of these on the
 * same symbol in the reference platform has to give the same numbers on the same bars,
 * warmup gap included. Two consequences run through the whole file.
 *
 * First, `smaSeededEma` from `./calc` is used everywhere an EMA is wanted and the
 * base bundle's `ema` is used nowhere. `ema` seeds from the SMA of the first
 * `length` values and is `na` before that; the bundle's `ema` seeds from bar 0
 * and emits from bar 0. They converge eventually but disagree over exactly the
 * stretch a parity check looks at.
 *
 * Second, three of the six studies smooth a series of their own (Mass Index is
 * an EMA of an EMA, PVO runs a signal average over the oscillator, NVI and PVI
 * run a 255-bar EMA over the index), and each treats a gap in it differently.
 * Mass Index calls `smaSeededEma` over the whole series: it seeds on the first
 * clean window after the warmup and holds across a later gap. NVI and PVI have
 * no gap to cross, because the index starts on bar 0 and holds on any bar whose
 * change is unknown. PVO's signal goes through `smoothRuns` and restarts after
 * a stretch with no reading, a documented rule (K13 in the numerical audit).
 */
import { sourceValues } from 'openalgo-charts';
import type { Bar, IndicatorDescriptor } from 'openalgo-charts';
import { cumulative, highest, nulls, smaSeededEma, rollingSum, sma } from './calc';
import { int, str, src } from './settings';
import { volumeOf } from './series';

/** A moving average over a window, in the shape every helper in `./calc` shares. */
type Smoother = (values: readonly number[], period: number) => number[];

/**
 * Smooth a series that already carries gaps, one gapless run at a time.
 *
 * Each run starts the smoother afresh, so after an interior gap the result
 * waits for a new full window. That reduces to a plain call when the only gap
 * is the leading warmup, and on the NVI and PVI index, which has none. A
 * windowed sum loses nothing by it, since a window holding the gap has no sum
 * either. A recursive average restarts: that is PVO's documented signal rule
 * (K13), and it is why Mass Index smooths its second average with
 * `smaSeededEma` directly.
 */
function smoothRuns(values: readonly number[], period: number, smooth: Smoother): number[] {
  const out = new Array<number>(values.length).fill(NaN);
  let i = 0;
  while (i < values.length) {
    if (!Number.isFinite(values[i])) {
      i += 1;
      continue;
    }
    let end = i;
    while (end < values.length && Number.isFinite(values[end])) end += 1;
    const run = smooth(values.slice(i, end), period);
    for (let k = 0; k < run.length; k++) out[i + k] = run[k]!;
    i = end;
  }
  return out;
}

/** the reference `ma()` switch: the two MA types PVO offers for both of its averages. */
const smootherFor = (kind: string): Smoother => (kind === 'SMA' ? sma : smaSeededEma);

/**
 * The shared body of `nvi` and `pvi`.
 *
 * Both are ratcheting indices: they start at a base of 1.0 on the first bar and
 * compound the bar's percentage price change into it, but only on the bars where
 * volume moved the right way. NVI takes the bars where volume *fell*, on the
 * theory that a move the crowd sat out is the smart money's; PVI takes the ones
 * where it rose. Every other bar carries the previous value forward unchanged,
 * which is why these plot as staircases rather than curves.
 *
 * There is no warmup: bar 0 is the base, so the plot starts at index 0.
 */
function volumeIndex(bars: readonly Bar[], on: 'falling' | 'rising'): number[] {
  const out = new Array<number>(bars.length);
  let index = 1;
  for (let i = 0; i < bars.length; i++) {
    if (i > 0) {
      const bar = bars[i]!;
      const prev = bars[i - 1]!;
      const prevClose = prev.close;
      const close = bar.close;
      const moved = on === 'falling' ? volumeOf(bar) < volumeOf(prev) : volumeOf(bar) > volumeOf(prev);
      // A zero or missing previous close, or a missing close, makes the
      // percentage change undefined. Compounding a NaN in would destroy every
      // later bar of a running product, so the index holds instead, exactly as
      // it does on a bar volume did not qualify.
      if (moved && prevClose !== 0 && Number.isFinite(prevClose) && Number.isFinite(close)) {
        index *= close / prevClose;
      }
    }
    // the reference scales the built-in by 1000 at the plot, so the base reads as 1000.
    out[i] = index * 1000;
  }
  return out;
}

/**
 * NVI and PVI differ only in which direction of volume change counts, so both
 * descriptors come from here. The value column is keyed by the study's id, which
 * keeps a consumer reading `values.nvi` rather than a shared generic name.
 */
function volumeIndexDescriptor(
  id: 'nvi' | 'pvi',
  name: string,
  short: string,
  on: 'falling' | 'rising',
): IndicatorDescriptor {
  return {
    id,
    name,
    category: 'Volume',
    placement: 'pane',
    inputs: [
      { key: 'maLength', type: 'number', label: 'EMA length', default: 255, min: 1, max: 5000, step: 1 },
      { key: 'color', type: 'color', label: short, default: '#2962ff' },
      { key: 'emaColor', type: 'color', label: `${short}-based EMA`, default: '#ff9800' },
    ],
    plots: [
      { key: id, type: 'line', title: short, colorKey: 'color', style: { lineWidth: 1.5 } },
      { key: 'ema', type: 'line', title: `${short}-based EMA`, colorKey: 'emaColor', style: { lineWidth: 1.5 } },
    ],
    calc: (bars, s) => {
      const index = volumeIndex(bars, on);
      return {
        [id]: nulls(index),
        ema: nulls(smoothRuns(index, int(s, 'maLength', 255), smaSeededEma)),
      };
    },
  };
}

/**
 * Negative Volume Index: the price path compounded across only the bars where
 * volume fell.
 */
export const NVI: IndicatorDescriptor = volumeIndexDescriptor(
  'nvi',
  'Negative Volume Index',
  'NVI',
  'falling',
);

/**
 * Positive Volume Index: the same construction as NVI over the complementary
 * set of bars, the ones where volume rose.
 */
export const PVI: IndicatorDescriptor = volumeIndexDescriptor(
  'pvi',
  'Positive Volume Index',
  'PVI',
  'rising',
);

/**
 * Price Volume Trend: a running total of each bar's percentage price change
 * weighted by the volume behind it.
 *
 * The distinction from On-Balance Volume is the weighting: OBV adds the whole
 * bar's volume on any up close, so a 0.1 percent drift and a 5 percent gap
 * count the same. PVT scales the contribution by how far price actually moved.
 */
export const PVT: IndicatorDescriptor = {
  id: 'pvt',
  name: 'Price Volume Trend',
  category: 'Volume',
  placement: 'pane',
  inputs: [{ key: 'color', type: 'color', label: 'PVT', default: '#2962ff' }],
  plots: [{ key: 'pvt', type: 'line', title: 'PVT', colorKey: 'color', style: { lineWidth: 1.5 } }],
  calc: (bars) => {
    const term = new Array<number>(bars.length).fill(NaN);
    for (let i = 1; i < bars.length; i++) {
      const prevClose = bars[i - 1]!.close;
      if (prevClose === 0 || !Number.isFinite(prevClose)) continue;
      term[i] = ((bars[i]!.close - prevClose) / prevClose) * volumeOf(bars[i]!);
    }
    // `cumulative` reads a non-finite term as 0, which is what bar 0 needs: it
    // has no previous close, so it contributes nothing and the total opens at 0
    // rather than at a gap. That matches the reference plot, which starts at bar 0.
    return { pvt: nulls(cumulative(term)) };
  },
};

/**
 * Percentage Volume Oscillator: MACD's construction applied to volume instead
 * of price, expressed as a percentage of the slow average.
 *
 * The percentage normalisation is the point: raw volume differences are not
 * comparable across symbols or across a decade of one symbol, whereas "the fast
 * average is 12 percent above the slow one" is.
 */
export const PVO: IndicatorDescriptor = {
  id: 'pvo',
  name: 'Percentage Volume Oscillator',
  category: 'Volume',
  placement: 'pane',
  inputs: [
    { key: 'fastLength', type: 'number', label: 'Fast length', default: 12, min: 1, max: 500, step: 1 },
    { key: 'slowLength', type: 'number', label: 'Slow length', default: 26, min: 1, max: 500, step: 1 },
    { key: 'signalLength', type: 'number', label: 'Signal length', default: 9, min: 1, max: 500, step: 1 },
    {
      key: 'oscType', type: 'select', label: 'Oscillator MA type', default: 'EMA',
      options: [{ label: 'EMA', value: 'EMA' }, { label: 'SMA', value: 'SMA' }],
    },
    {
      key: 'sigType', type: 'select', label: 'Signal MA type', default: 'EMA',
      options: [{ label: 'EMA', value: 'EMA' }, { label: 'SMA', value: 'SMA' }],
    },
    { key: 'histUpColor', type: 'color', label: 'Histogram up', default: '#26a69a' },
    { key: 'histUpFadeColor', type: 'color', label: 'Histogram up (weakening)', default: '#b2dfdb' },
    { key: 'histDownFadeColor', type: 'color', label: 'Histogram down (weakening)', default: '#ffcdd2' },
    { key: 'histDownColor', type: 'color', label: 'Histogram down', default: '#ff5252' },
    { key: 'color', type: 'color', label: 'PVO', default: '#2962ff' },
    { key: 'signalColor', type: 'color', label: 'Signal line', default: '#ff6d00' },
  ],
  plots: [
    {
      key: 'hist', type: 'column', title: 'Histogram', colorKey: 'histUpColor',
      style: { base: 0 },
      // Four states, not two: the sign says which side of the signal line the
      // oscillator sits on, and the move against the previous bar says whether
      // that gap is opening or closing. The faded pair is the closing case.
      // the reference `hist > hist[1]` is false on the first printed bar, where
      // `hist[1]` is na, so the series opens on a fading colour.
      colorBy: ({ value, index, values, settings }) => {
        const prev = values.hist?.[index - 1];
        const rising = prev !== null && prev !== undefined && Number.isFinite(prev) && value > prev;
        if (value >= 0) {
          return rising ? str(settings, 'histUpColor', '#26a69a') : str(settings, 'histUpFadeColor', '#b2dfdb');
        }
        return rising ? str(settings, 'histDownFadeColor', '#ffcdd2') : str(settings, 'histDownColor', '#ff5252');
      },
    },
    { key: 'pvo', type: 'line', title: 'PVO', colorKey: 'color', style: { lineWidth: 1.5 } },
    { key: 'signal', type: 'line', title: 'Signal line', colorKey: 'signalColor', style: { lineWidth: 1.5 } },
  ],
  calc: (bars, s) => {
    const n = bars.length;
    const volumes = bars.map(volumeOf);
    const osc = smootherFor(str(s, 'oscType', 'EMA'));
    const fast = osc(volumes, int(s, 'fastLength', 12));
    const slow = osc(volumes, int(s, 'slowLength', 26));

    const pvo = new Array<number>(n).fill(NaN);
    // Every series here holds one value per bar.
    for (let i = 0; i < n; i++) {
      // A window that traded nothing has no baseline to express the spread as a
      // percentage of. the reference division by zero is na, so this stays a gap --
      // which is the whole of a feed the vendor sends no volume for.
      if (slow[i] !== 0) pvo[i] = (100 * (fast[i]! - slow[i]!)) / slow[i]!;
    }

    // After its warmup PVO has no reading only where the slow average is
    // exactly 0: a slow window that traded nothing, which complete data has as
    // often as a feed with missing volume. Holding the signal across it would
    // move readings on complete series, so the restart stays (K13).
    const signal = smoothRuns(pvo, int(s, 'signalLength', 9), smootherFor(str(s, 'sigType', 'EMA')));
    const hist = new Array<number>(n);
    for (let i = 0; i < n; i++) hist[i] = pvo[i]! - signal[i]!;
    return { hist: nulls(hist), pvo: nulls(pvo), signal: nulls(signal) };
  },
  levels: () => [{ price: 0, color: '#787b8680', title: 'Zero' }],
};

/**
 * Mass Index: how much the range is expanding relative to its own recent
 * expansion, summed over a window.
 *
 * The ratio of a 9-bar EMA of the range to a 9-bar EMA of *that* is near 1 while
 * volatility is steady and rises as the range widens, so the sum reads as
 * "volatility has been building for a while" rather than "this bar was wide".
 * The nested EMA is the parity trap in this file: its input is already `na` for
 * the first 8 bars, and the second average seeds past that rather than
 * propagating it, which is why the plot starts two warmups plus a window deep.
 */
export const MASS_INDEX: IndicatorDescriptor = {
  id: 'mass-index',
  name: 'Mass Index',
  category: 'Volatility',
  placement: 'pane',
  inputs: [
    { key: 'length', type: 'number', label: 'Length', default: 10, min: 1, max: 500, step: 1 },
    { key: 'color', type: 'color', label: 'Mass Index', default: '#2962ff' },
  ],
  plots: [{ key: 'mi', type: 'line', title: 'Mass Index', colorKey: 'color', style: { lineWidth: 1.5 } }],
  calc: (bars, s) => {
    const n = bars.length;
    const span = bars.map((b) => b.high - b.low);
    // The two 9-bar periods are part of the definition of the study, not inputs:
    // the reference hard-codes them and exposes only the sum length.
    const single = smaSeededEma(span, 9);
    // Over the whole series, not run by run: after a missing range the second
    // average holds and resumes with the first, where restarting it would
    // blank the study for another nine bars and then print a fresh-seed value.
    const double = smaSeededEma(single, 9);

    const ratio = new Array<number>(n).fill(NaN);
    // Both averages hold one value per bar.
    for (let i = 0; i < n; i++) {
      // A flat market long enough for the smoothed range to reach zero has no
      // expansion to measure; the reference divides by zero and gets na.
      if (double[i] !== 0) ratio[i] = single[i]! / double[i]!;
    }
    // `rollingSum` accumulates every term it is handed, non-finite ones
    // included, so it has to run inside `smoothRuns` rather than over the
    // ratio's leading gap.
    return { mi: nulls(smoothRuns(ratio, int(s, 'length', 10), rollingSum)) };
  },
};

/**
 * Ulcer Index: the root-mean-square percentage drawdown from the window's
 * running high.
 *
 * Standard deviation treats an upside surprise as risk; this only counts the
 * distance below the recent peak, and squaring before averaging makes one deep
 * drawdown weigh more than several shallow ones. The reading is therefore a
 * measure of how uncomfortable holding the instrument was, not of how much it
 * moved, and it is 0 on any series that only rises.
 */
export const ULCER_INDEX: IndicatorDescriptor = {
  id: 'ulcer-index',
  name: 'Ulcer Index',
  category: 'Volatility',
  placement: 'pane',
  inputs: [
    { key: 'source', type: 'source', label: 'Source', default: 'close' },
    { key: 'length', type: 'number', label: 'Length', default: 14, min: 1, max: 500, step: 1 },
    { key: 'color', type: 'color', label: 'Ulcer Index', default: '#2962ff' },
    { key: 'fillColor', type: 'color', label: 'Background', default: '#2196f3' },
  ],
  plots: [{ key: 'ui', type: 'line', title: 'Ulcer Index', colorKey: 'color', style: { lineWidth: 1.5 } }],
  // The reference shades the plot down to a hidden zero plot. `zero` is a value
  // column with no plot of its own, exactly as that `display.none` plot is: it
  // exists only to give the fill a second edge.
  fills: [{ between: ['ui', 'zero'], colorUpKey: 'fillColor', colorDownKey: 'fillColor', opacity: 0.1 }],
  calc: (bars, s) => {
    const n = bars.length;
    const length = int(s, 'length', 14);
    const values = sourceValues(bars, src(s));
    const peak = highest(values, length);

    const squared = new Array<number>(n).fill(NaN);
    // Every series here holds one value per bar.
    for (let i = 0; i < n; i++) {
      const hi = peak[i]!;
      if (!Number.isFinite(hi) || hi === 0) continue;
      const drawdown = (100 * (values[i]! - hi)) / hi;
      squared[i] = drawdown * drawdown;
    }
    // `sma` refuses to average a window holding a non-finite value, so the
    // drawdown's own warmup pushes the first reading a second window out
    // instead of leaking into it.
    const mean = sma(squared, length);
    const ui = new Array<number>(n);
    for (let i = 0; i < n; i++) ui[i] = Math.sqrt(mean[i]!);
    return {
      ui: nulls(ui),
      zero: ui.map((v) => (Number.isFinite(v) ? 0 : null)),
    };
  },
  // the reference bare `hline(0, "Zero")` takes the default colour, `color.blue`, which
  // is the same hue as the fill above.
  levels: () => [{ price: 0, color: '#2196f3', title: 'Zero' }],
};

/** Every descriptor in this module, in picker order. */
export const INDEX_INDICATORS: readonly IndicatorDescriptor[] = [
  NVI,
  PVI,
  PVT,
  PVO,
  MASS_INDEX,
  ULCER_INDEX,
];
