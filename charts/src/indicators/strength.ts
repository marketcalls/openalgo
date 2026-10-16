/**
 * A third batch of built-in momentum studies, ported from the published v6
 * sources of the upstream charting platform. Part of the lazy
 * `openalgo-charts/indicators` tier.
 *
 * These are reproductions, not inspirations: overlaying one of these on the same
 * symbol upstream has to give the same numbers, including the warmup gap.
 *
 * Almost every study here chains smoothers, so each stage's warmup must stay
 * aligned with the preceding stage. `emaOfGapped` slices off the leading gap
 * and pads the result back into place, while `smaSeededEma` handles finite-window
 * seeding and subsequent input gaps.
 *
 * The base bundle's own `ema` is deliberately absent from this file. It seeds
 * from bar 0 rather than from an SMA, so it disagrees with the upstream
 * definition over the first `length` bars, which is exactly the region these
 * studies are judged on.
 */
import { sourceValues } from 'openalgo-charts';
import type { IndicatorDescriptor } from 'openalgo-charts';
import { sma, nulls, change, roc, highest, lowest } from './calc';
import { emaOfGapped } from './smoothing';
import { int, str, src } from './settings';
import { zip } from './series';

/**
 * The upstream `tsi(source, shortLength, longLength)`.
 *
 * Blau's double smoothing runs **long first, then short**, even though the
 * public argument order puts `short` first: the long EMA is what removes the
 * noise, and the short one only tidies the result. Getting that backwards
 * produces a plausible-looking but wrong curve, so the routine lives here once
 * and is shared by True Strength Index and both SMI Ergodic studies rather than
 * being written out three times where the three copies could drift apart.
 *
 * `change` is `na` on bar 0, so both smoothed legs inherit that gap and the
 * first printed value lands at `longLength + shortLength - 1`.
 *
 * The 100 is applied before the division, the arrangement the definition
 * fixes. Near the top of the double range that product can overflow where the
 * ratio would not. The infinity it leaves is absent to every consumer: the
 * signal average skips it and `nulls` prints a gap.
 */
function tsiSeries(values: readonly number[], shortLength: number, longLength: number): number[] {
  const pc = change(values);
  const doubleSmooth = (v: readonly number[]): number[] =>
    emaOfGapped(emaOfGapped(v, longLength), shortLength);
  const smoothed = doubleSmooth(pc);
  const smoothedAbs = doubleSmooth(pc.map((v) => Math.abs(v)));
  // The smoothers return one value per input, here and in every study below.
  return zip(smoothed, smoothedAbs, (v, abs) => (100 * v) / abs);
}

/**
 * Momentum: the rawest reading there is, today's price against the price `len`
 * bars ago. No smoothing, no normalisation, so the scale is the instrument's
 * own and only the sign and the slope carry meaning.
 */
export const MOMENTUM: IndicatorDescriptor = {
  id: 'momentum',
  name: 'Momentum',
  category: 'Momentum',
  placement: 'pane',
  inputs: [
    { key: 'len', type: 'number', label: 'Length', default: 10, min: 1, max: 500, step: 1 },
    { key: 'source', type: 'source', label: 'Source', default: 'close' },
    { key: 'color', type: 'color', label: 'MOM', default: '#2962ff' },
  ],
  plots: [{ key: 'mom', type: 'line', title: 'MOM', colorKey: 'color', style: { lineWidth: 1.5 } }],
  calc: (bars, s) => ({
    mom: nulls(change(sourceValues(bars, src(s)), int(s, 'len', 10))),
  }),
};

/**
 * Rate of Change: the same comparison as Momentum, expressed as a percentage of
 * the older price so readings are comparable across instruments and across time.
 *
 * A zero reference price makes the ratio undefined, which is drawn upstream as a
 * gap rather than as an infinite spike; the `roc` helper already returns NaN.
 */
export const ROC: IndicatorDescriptor = {
  id: 'roc',
  name: 'Rate of Change',
  category: 'Momentum',
  placement: 'pane',
  inputs: [
    { key: 'length', type: 'number', label: 'Length', default: 9, min: 1, max: 500, step: 1 },
    { key: 'source', type: 'source', label: 'Source', default: 'close' },
    { key: 'color', type: 'color', label: 'ROC', default: '#2962ff' },
  ],
  plots: [{ key: 'roc', type: 'line', title: 'ROC', colorKey: 'color', style: { lineWidth: 1.5 } }],
  calc: (bars, s) => ({
    roc: nulls(roc(sourceValues(bars, src(s)), int(s, 'length', 9))),
  }),
  levels: () => [{ price: 0, color: '#787b86', title: 'Zero Line', dashed: true }],
};

/** The `ma()` helper the source script defines: one length, one of two shapes. */
function ppoMa(values: readonly number[], period: number, maType: string): number[] {
  // `emaOfGapped` rather than `smaSeededEma`: the signal line is a MA *of the PPO*,
  // which starts `slowLength - 1` bars in. `sma` already tolerates a gap.
  return maType === 'SMA' ? sma(values, period) : emaOfGapped(values, period);
}

/**
 * Percentage Price Oscillator: MACD rewritten as a percentage of the slow
 * average, so the histogram of a 20 dollar stock and a 2000 dollar index can be
 * read on the same axis.
 *
 * Both the oscillator and its signal take a selectable EMA/SMA shape, and the
 * signal is a MA of the PPO rather than of price, so it inherits the PPO's own
 * warmup on top of its own: on defaults the oscillator prints from bar 25 and
 * the signal and histogram from bar 33.
 */
export const PPO: IndicatorDescriptor = {
  id: 'ppo',
  name: 'Percentage Price Oscillator',
  category: 'Momentum',
  placement: 'pane',
  inputs: [
    { key: 'source', type: 'source', label: 'Source', default: 'close' },
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
    { key: 'ppoColor', type: 'color', label: 'PPO', default: '#2962ff' },
    { key: 'signalColor', type: 'color', label: 'Signal line', default: '#ff6d00' },
  ],
  plots: [
    {
      key: 'hist', type: 'column', title: 'Histogram', colorKey: 'histUpColor',
      style: { base: 0 },
      // Four states, not one colour: the sign says which side of zero, and the
      // direction against the previous bar says whether that momentum is
      // building or fading. The source script uses a strict `hist > hist[1]`,
      // and `na > x` is false, so the first printed bar always takes the
      // weakening branch. Reproducing that is why the guard is not the more
      // forgiving "assume rising when there is no previous bar".
      colorBy: ({ value, index, values, settings }) => {
        const prev = values.hist?.[index - 1];
        const rising = typeof prev === 'number' && Number.isFinite(prev) && value > prev;
        if (value >= 0) {
          return rising ? str(settings, 'histUpColor', '#26a69a') : str(settings, 'histUpFadeColor', '#b2dfdb');
        }
        return rising ? str(settings, 'histDownFadeColor', '#ffcdd2') : str(settings, 'histDownColor', '#ff5252');
      },
    },
    { key: 'ppo', type: 'line', title: 'PPO', colorKey: 'ppoColor', style: { lineWidth: 1.5 } },
    { key: 'signal', type: 'line', title: 'Signal line', colorKey: 'signalColor', style: { lineWidth: 1.5 } },
  ],
  calc: (bars, s) => {
    const values = sourceValues(bars, src(s));
    const oscType = str(s, 'oscType', 'EMA');
    const fast = ppoMa(values, int(s, 'fastLength', 12), oscType);
    const slow = ppoMa(values, int(s, 'slowLength', 26), oscType);
    // A zero slow average makes the percentage undefined, which is a gap
    // upstream, not a division blowing up to Infinity.
    const ppo = zip(fast, slow, (f, sl) => (sl === 0 ? NaN : (100 * (f - sl)) / sl));
    const signal = ppoMa(ppo, int(s, 'signalLength', 9), str(s, 'sigType', 'EMA'));
    return {
      hist: nulls(zip(ppo, signal, (v, sig) => v - sig)),
      ppo: nulls(ppo),
      signal: nulls(signal),
    };
  },
  levels: () => [{ price: 0, color: '#787b86', title: 'Zero', dashed: true }],
};

/**
 * TRIX: the one-bar rate of change of a triple-smoothed log price.
 *
 * Working in logs is what makes the output a pure percentage rate (scaled by
 * 10000, so a reading of 100 is one percent per bar) independent of price
 * level, and three EMAs in series strip nearly everything that is not the
 * underlying trend, which is why it crosses zero so cleanly and so late.
 *
 * That lateness is the cost: each EMA starts `length - 1` bars after its input,
 * and `change` adds one more, so the first print is at `3 * length - 2`
 * (bar 52 on the default 18).
 */
export const TRIX: IndicatorDescriptor = {
  id: 'trix',
  name: 'TRIX',
  category: 'Momentum',
  placement: 'pane',
  inputs: [
    { key: 'length', type: 'number', label: 'Length', default: 18, min: 1, max: 500, step: 1 },
    { key: 'color', type: 'color', label: 'TRIX', default: '#f44336' },
  ],
  plots: [{ key: 'trix', type: 'line', title: 'TRIX', colorKey: 'color', style: { lineWidth: 1.5 } }],
  calc: (bars, s) => {
    const length = int(s, 'length', 18);
    // `log` of a non-positive price is undefined, and a synthetic or adjusted
    // series can reach zero; that prints as a gap upstream.
    const logs = bars.map((b) => (b.close > 0 ? Math.log(b.close) : NaN));
    const smoothed = emaOfGapped(emaOfGapped(emaOfGapped(logs, length), length), length);
    return { trix: nulls(change(smoothed).map((v) => 10000 * v)) };
  },
  levels: () => [{ price: 0, color: '#787b86', title: 'Zero', dashed: true }],
};

/**
 * True Strength Index: the double-smoothed one-bar change divided by the
 * double-smoothed size of that change.
 *
 * Dividing by the smoothed magnitude is what bounds the study to -100..100 and
 * makes it read as "what fraction of recent movement went one way": a run of
 * unbroken up bars gives exactly +100 because the numerator and denominator are
 * then the same series.
 */
export const TSI: IndicatorDescriptor = {
  id: 'tsi',
  name: 'True Strength Index',
  category: 'Momentum',
  placement: 'pane',
  inputs: [
    { key: 'long', type: 'number', label: 'Long Length', default: 25, min: 1, max: 500, step: 1 },
    { key: 'short', type: 'number', label: 'Short Length', default: 13, min: 1, max: 500, step: 1 },
    { key: 'signal', type: 'number', label: 'Signal Length', default: 13, min: 1, max: 500, step: 1 },
    { key: 'color', type: 'color', label: 'True Strength Index', default: '#2962ff' },
    { key: 'signalColor', type: 'color', label: 'Signal', default: '#e91e63' },
  ],
  plots: [
    { key: 'tsi', type: 'line', title: 'True Strength Index', colorKey: 'color', style: { lineWidth: 1.5 } },
    { key: 'signal', type: 'line', title: 'Signal', colorKey: 'signalColor', style: { lineWidth: 1.5 } },
  ],
  calc: (bars, s) => {
    const value = tsiSeries(bars.map((b) => b.close), int(s, 'short', 13), int(s, 'long', 25));
    return {
      tsi: nulls(value),
      signal: nulls(emaOfGapped(value, int(s, 'signal', 13))),
    };
  },
  levels: () => [{ price: 0, color: '#787b86', title: 'Zero', dashed: true }],
};

/**
 * SMI Ergodic Indicator: Blau's Ergodic, which is TSI plotted against its own
 * EMA signal. Same maths as True Strength Index, different default lengths (20
 * and 5 rather than 25 and 13), so it turns much faster.
 *
 * The source script draws no horizontal lines here, and none are declared:
 * adding a zero line would be a nicer chart but a different one.
 */
export const SMI_ERGODIC_INDICATOR: IndicatorDescriptor = {
  id: 'smi-ergodic-indicator',
  name: 'SMI Ergodic Indicator',
  category: 'Momentum',
  placement: 'pane',
  inputs: [
    { key: 'longlen', type: 'number', label: 'Long Length', default: 20, min: 1, max: 500, step: 1 },
    { key: 'shortlen', type: 'number', label: 'Short Length', default: 5, min: 1, max: 500, step: 1 },
    { key: 'siglen', type: 'number', label: 'Signal Line Length', default: 5, min: 1, max: 500, step: 1 },
    { key: 'color', type: 'color', label: 'SMI', default: '#2962ff' },
    { key: 'signalColor', type: 'color', label: 'Signal', default: '#ff6d00' },
  ],
  plots: [
    { key: 'erg', type: 'line', title: 'SMI', colorKey: 'color', style: { lineWidth: 1.5 } },
    { key: 'sig', type: 'line', title: 'Signal', colorKey: 'signalColor', style: { lineWidth: 1.5 } },
  ],
  calc: (bars, s) => {
    const erg = tsiSeries(bars.map((b) => b.close), int(s, 'shortlen', 5), int(s, 'longlen', 20));
    return { erg: nulls(erg), sig: nulls(emaOfGapped(erg, int(s, 'siglen', 5))) };
  },
};

/**
 * SMI Ergodic Oscillator: the gap between the Ergodic and its signal, drawn as
 * a histogram. The same relationship the Indicator shows as two lines, reduced
 * to the one number that crosses zero.
 */
export const SMI_ERGODIC_OSCILLATOR: IndicatorDescriptor = {
  id: 'smi-ergodic-oscillator',
  name: 'SMI Ergodic Oscillator',
  category: 'Momentum',
  placement: 'pane',
  inputs: [
    { key: 'longlen', type: 'number', label: 'Long Length', default: 20, min: 1, max: 500, step: 1 },
    { key: 'shortlen', type: 'number', label: 'Short Length', default: 5, min: 1, max: 500, step: 1 },
    { key: 'siglen', type: 'number', label: 'Signal Line Length', default: 5, min: 1, max: 500, step: 1 },
    { key: 'color', type: 'color', label: 'SMI Ergodic Oscillator', default: '#ff5252' },
  ],
  plots: [
    {
      key: 'osc', type: 'histogram', title: 'SMI Ergodic Oscillator',
      colorKey: 'color', style: { base: 0 },
    },
  ],
  calc: (bars, s) => {
    const erg = tsiSeries(bars.map((b) => b.close), int(s, 'shortlen', 5), int(s, 'longlen', 20));
    const sig = emaOfGapped(erg, int(s, 'siglen', 5));
    return { osc: nulls(zip(erg, sig, (v, sg) => v - sg)) };
  },
};

/**
 * Stochastic Momentum Index: Stochastic measured from the *midpoint* of the
 * range instead of from its low.
 *
 * That single change is what re-centres the study on zero and lets it say which
 * half of the range price is in, rather than only how high in it. Both the
 * distance from the midpoint and the range itself are double-smoothed before
 * being divided, which is why the reading is far steadier than a raw %K.
 *
 * A bare `highest(lengthK)` / `lowest(lengthK)` upstream defaults to `high` and
 * `low`, not to the source of the surrounding expression, so the window really
 * is a high/low range and not a close-only one.
 */
export const SMI: IndicatorDescriptor = {
  id: 'smi',
  name: 'Stochastic Momentum Index',
  category: 'Momentum',
  placement: 'pane',
  inputs: [
    { key: 'lengthK', type: 'number', label: '%K Length', default: 10, min: 1, max: 15000, step: 1 },
    { key: 'lengthD', type: 'number', label: '%D Length', default: 3, min: 1, max: 4999, step: 1 },
    { key: 'lengthEMA', type: 'number', label: 'EMA Length', default: 3, min: 1, max: 4999, step: 1 },
    { key: 'color', type: 'color', label: 'SMI', default: '#2196f3' },
    { key: 'emaColor', type: 'color', label: 'SMI-based EMA', default: '#ff9800' },
    { key: 'fillColor', type: 'color', label: 'Background', default: '#2196f3' },
  ],
  plots: [
    { key: 'smi', type: 'line', title: 'SMI', colorKey: 'color', style: { lineWidth: 1.5 } },
    { key: 'ema', type: 'line', title: 'SMI-based EMA', colorKey: 'emaColor', style: { lineWidth: 1.5 } },
  ],
  // The 40/-40 shading spans two reference lines rather than two series, so its
  // edges are constant columns with no plot of their own. One colour on both
  // sides: a level band has no up or down side to tell apart.
  //
  // The reference also paints two clipped gradients from the plot down to the
  // zero line, one per side. A fill here is one flat colour between two columns
  // with no gradient stops and no clip range, so approximating them would draw
  // a picture the reference never draws; they are left out rather than faked,
  // and the overbought and oversold levels carry that reading instead.
  fills: [{ between: ['bandHigh', 'bandLow'], colorUpKey: 'fillColor', colorDownKey: 'fillColor', opacity: 0.1 }],
  calc: (bars, s) => {
    const lengthK = int(s, 'lengthK', 10);
    const lengthD = int(s, 'lengthD', 3);
    const highestHigh = highest(bars.map((b) => b.high), lengthK);
    const lowestLow = lowest(bars.map((b) => b.low), lengthK);
    const span = zip(highestHigh, lowestLow, (h, ll) => h - ll);
    const relative = bars.map((b, i) => b.close - (highestHigh[i]! + lowestLow[i]!) / 2);
    const emaEma = (v: readonly number[]): number[] =>
      emaOfGapped(emaOfGapped(v, lengthD), lengthD);
    const numerator = emaEma(relative);
    const denominator = emaEma(span);
    // A window with no range at all (a halted or synthetic flat series) divides
    // by zero. That prints as a gap upstream; without the guard it would be
    // +/-Infinity and would drag the pane's autoscale with it.
    const value = zip(numerator, denominator, (v, den) => (den === 0 ? NaN : 200 * (v / den)));
    // The band edges are never null: the background covers the whole pane, so
    // they have to exist on bars where neither line prints yet.
    return {
      smi: nulls(value),
      ema: nulls(emaOfGapped(value, int(s, 'lengthEMA', 3))),
      bandHigh: new Array<number>(bars.length).fill(40),
      bandLow: new Array<number>(bars.length).fill(-40),
    };
  },
  levels: () => [
    { price: 40, color: '#787b86', title: 'Overbought Line', dashed: true },
    { price: 0, color: '#787b86', title: 'Middle Line', dashed: true },
    { price: -40, color: '#787b86', title: 'Oversold Line', dashed: true },
  ],
};

export const STRENGTH_INDICATORS: readonly IndicatorDescriptor[] = [
  MOMENTUM,
  ROC,
  PPO,
  TRIX,
  TSI,
  SMI_ERGODIC_INDICATOR,
  SMI_ERGODIC_OSCILLATOR,
  SMI,
];
