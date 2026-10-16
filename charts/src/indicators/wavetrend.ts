/**
 * WaveTrend Pro: a channel oscillator, its signal line, a momentum histogram,
 * zone-filtered crosses and a four-class divergence engine. Part of the lazy
 * `openalgo-charts/indicators` tier.
 *
 * The oscillator asks one question: how far has the source strayed from its own
 * exponential mean, measured in units of how far it usually strays. The 0.015
 * scaling is the convention CCI is calibrated with, which is what puts the
 * readings in a roughly +/-100 band and makes fixed levels at 53 and 60 mean
 * something across instruments.
 *
 * Four smoothers run back to back (mean, mean deviation, the oscillator, its
 * signal line), and each one starts later than its input. `fromFirstValue`
 * keeps each stage aligned by slicing off the leading gap, smoothing the tail
 * and padding the answer back. The smoothers handle their own finite-window
 * availability. With finite seed windows and the defaults, the oscillator
 * prints from bar
 * `2 * (n1 - 1) + n2 - 1` = 38, the signal line `sigLen - 1` bars later at 41,
 * and the momentum with it.
 *
 * Three things the published definition does that this library cannot express,
 * and which are changed or dropped here rather than faked:
 *   - the momentum is a filled area whose colour changes bar to bar. Per-bar
 *     colour is honoured by the histogram and column renderers only, so the
 *     momentum is drawn as a histogram: the colour carries the sign, which is
 *     the reading the area shape was only decorating.
 *   - a signal recolours the price bars. A pane study has no handle on the price
 *     series' styling, so that switch is not reproduced and not offered.
 *   - two connector plots join consecutive pivots and go transparent when the
 *     divergence does not hold. They need a line between two isolated points and
 *     a per-bar line colour, neither of which the line renderer has. The
 *     labelled plates carry the same information.
 */
import { sourceValues } from 'openalgo-charts';
import type { IndicatorDescriptor, SeriesMarker } from 'openalgo-charts';
import {
  smaSeededEma, nulls, pivotHigh, pivotLow, barsSince, valueWhen,
} from './calc';
import { windowMean } from './window-mean';
import { fromFirstValue } from './smoothing';
import { num, int, str, src } from './settings';
import { constant, shift, shiftFlags, zip } from './series';

/** The same colour at 60 percent opacity, for the dimmer hidden-divergence plates. */
const dim = (hex: string): string => (/^#[0-9a-f]{6}$/i.test(hex) ? `${hex}99` : hex);

export const WAVETREND: IndicatorDescriptor = {
  id: 'wavetrend',
  name: 'WaveTrend Pro',
  category: 'Momentum',
  placement: 'pane',
  inputs: [
    { key: 'source', type: 'source', label: 'Source', default: 'hlc3', group: 'WaveTrend' },
    { key: 'n1', type: 'number', label: 'Channel Length', default: 10, min: 1, max: 500, step: 1, group: 'WaveTrend' },
    { key: 'n2', type: 'number', label: 'Average Length', default: 21, min: 1, max: 500, step: 1, group: 'WaveTrend' },
    { key: 'sigLen', type: 'number', label: 'Signal Smoothing', default: 4, min: 1, max: 100, step: 1, group: 'WaveTrend' },
    { key: 'wt1Color', type: 'color', label: 'WT1', default: '#2962ff', group: 'WaveTrend' },
    { key: 'wt2Color', type: 'color', label: 'WT2', default: '#ff6d00', group: 'WaveTrend' },
    { key: 'fillUpColor', type: 'color', label: 'WT Fill Up', default: '#4caf50', group: 'WaveTrend' },
    { key: 'fillDownColor', type: 'color', label: 'WT Fill Down', default: '#ff5252', group: 'WaveTrend' },

    { key: 'obLevel1', type: 'number', label: 'Overbought 1', default: 60, min: -200, max: 200, step: 1, group: 'Levels' },
    { key: 'obLevel2', type: 'number', label: 'Overbought 2', default: 53, min: -200, max: 200, step: 1, group: 'Levels' },
    { key: 'osLevel1', type: 'number', label: 'Oversold 1', default: -60, min: -200, max: 200, step: 1, group: 'Levels' },
    { key: 'osLevel2', type: 'number', label: 'Oversold 2', default: -53, min: -200, max: 200, step: 1, group: 'Levels' },
    { key: 'obBandColor', type: 'color', label: 'OB Band', default: '#ff5252', group: 'Levels' },
    { key: 'osBandColor', type: 'color', label: 'OS Band', default: '#4caf50', group: 'Levels' },

    { key: 'filterZone', type: 'boolean', label: 'Only show crosses inside OB/OS zones', default: true, group: 'Signals' },
    { key: 'useInner', type: 'boolean', label: 'Use inner levels (53) as the zone gate', default: true, group: 'Signals' },
    { key: 'showMom', type: 'boolean', label: 'Show momentum histogram (wt1 - wt2)', default: true, group: 'Signals' },
    { key: 'momUpColor', type: 'color', label: 'Momentum Up', default: '#008080', group: 'Signals' },
    { key: 'momDownColor', type: 'color', label: 'Momentum Down', default: '#880e4f', group: 'Signals' },
    { key: 'buyColor', type: 'color', label: 'Bullish Cross', default: '#00e676', group: 'Signals' },
    { key: 'sellColor', type: 'color', label: 'Bearish Cross', default: '#ff5252', group: 'Signals' },

    { key: 'showRegDiv', type: 'boolean', label: 'Regular divergence', default: true, group: 'Divergence' },
    { key: 'showHidDiv', type: 'boolean', label: 'Hidden divergence', default: false, group: 'Divergence' },
    { key: 'lbL', type: 'number', label: 'Pivot Lookback Left', default: 3, min: 1, max: 100, step: 1, group: 'Divergence' },
    { key: 'lbR', type: 'number', label: 'Pivot Lookback Right', default: 3, min: 1, max: 100, step: 1, group: 'Divergence' },
    { key: 'rangeUpper', type: 'number', label: 'Max Bars Between Pivots', default: 60, min: 1, max: 1000, step: 1, group: 'Divergence' },
    { key: 'rangeLower', type: 'number', label: 'Min Bars Between Pivots', default: 5, min: 1, max: 1000, step: 1, group: 'Divergence' },
    { key: 'bullColor', type: 'color', label: 'Bullish Divergence', default: '#4caf50', group: 'Divergence' },
    { key: 'bearColor', type: 'color', label: 'Bearish Divergence', default: '#ff5252', group: 'Divergence' },
  ],
  // The momentum is declared first so the two lines draw over it rather than
  // under it, which is the stacking the filled-area original relies on.
  plots: [
    {
      key: 'mom', type: 'histogram', title: 'Momentum', colorKey: 'momUpColor',
      style: { base: 0 },
      // The sign is the whole reading, and it is the half of the original's
      // per-bar area colour that survives into a shape the renderer can tint.
      colorBy: ({ value, settings }) => {
        return value >= 0 ? str(settings, 'momUpColor', '#008080') : str(settings, 'momDownColor', '#880e4f');
      },
    },
    { key: 'wt1', type: 'line', title: 'WT1', colorKey: 'wt1Color', style: { lineWidth: 2 } },
    { key: 'wt2', type: 'line', title: 'WT2', colorKey: 'wt2Color', style: { lineWidth: 1 } },
  ],
  // The first band is the one the source definition tints by `wt1 > wt2`, which
  // is precisely the up/down test a fill already makes. The other two span a
  // pair of constant columns, so they shade the zones from the first bar. Each
  // literal colour repeats its input's default: a settings blob that never
  // wrote the key still shades in this study's palette rather than in the
  // runtime's generic fallback pair.
  fills: [
    {
      between: ['wt1', 'wt2'],
      colorUp: '#4caf50', colorDown: '#ff5252',
      colorUpKey: 'fillUpColor', colorDownKey: 'fillDownColor', opacity: 0.15,
    },
    {
      between: ['obUpper', 'obLower'],
      colorUp: '#ff5252', colorDown: '#ff5252',
      colorUpKey: 'obBandColor', colorDownKey: 'obBandColor', opacity: 0.08,
    },
    {
      between: ['osUpper', 'osLower'],
      colorUp: '#4caf50', colorDown: '#4caf50',
      colorUpKey: 'osBandColor', colorDownKey: 'osBandColor', opacity: 0.08,
    },
  ],
  calc: (bars, s) => {
    const n = bars.length;
    const n1 = int(s, 'n1', 10);
    const n2 = int(s, 'n2', 21);
    const sigLen = int(s, 'sigLen', 4);
    const obLevel1 = num(s, 'obLevel1', 60);
    const obLevel2 = num(s, 'obLevel2', 53);
    const osLevel1 = num(s, 'osLevel1', -60);
    const osLevel2 = num(s, 'osLevel2', -53);

    const buy: (number | null)[] = new Array(n).fill(null);
    const sell: (number | null)[] = new Array(n).fill(null);
    const bull: (number | null)[] = new Array(n).fill(null);
    const bear: (number | null)[] = new Array(n).fill(null);
    const hiddenBull: (number | null)[] = new Array(n).fill(null);
    const hiddenBear: (number | null)[] = new Array(n).fill(null);

    // Every series below holds one value per bar.
    const ap = sourceValues(bars, src(s, 'source', 'hlc3'));
    const esa = fromFirstValue(ap, (t) => smaSeededEma(t, n1));
    const absDev = fromFirstValue(
      zip(ap, esa, (v, e) => Math.abs(v - e)),
      (t) => smaSeededEma(t, n1),
    );
    // A flat stretch has no deviation to divide by, and the reading there is
    // "exactly average", not "infinitely far from average". While the deviation
    // is still warming there is no reading at all, which is a different answer
    // from zero and has to stay missing.
    const ci = ap.map((v, i) => {
      const dv = absDev[i]!;
      if (!Number.isFinite(dv)) return NaN;
      return dv === 0 ? 0 : (v - esa[i]!) / (0.015 * dv);
    });
    const wt1 = fromFirstValue(ci, (t) => smaSeededEma(t, n2));
    const wt2 = fromFirstValue(wt1, (t) => windowMean(t, sigLen));
    const mom = zip(wt1, wt2, (v, w2) => v - w2);

    const out = {
      wt1: nulls(wt1),
      wt2: nulls(wt2),
      mom: s.showMom === false ? new Array<number | null>(n).fill(null) : nulls(mom),
      // The band edges track their level inputs, so the shading stays glued to
      // the reference lines when either is moved.
      obUpper: constant(n, obLevel1),
      obLower: constant(n, obLevel2),
      osUpper: constant(n, osLevel2),
      osLower: constant(n, osLevel1),
      buy,
      sell,
      bull,
      bear,
      hiddenBull,
      hiddenBear,
    };

    // ── crosses, optionally gated by the zone the signal line sits in ───────
    const filterZone = s.filterZone !== false;
    const useInner = s.useInner !== false;
    const obZone = useInner ? obLevel2 : obLevel1;
    const osZone = useInner ? osLevel2 : osLevel1;
    for (let i = 1; i < n; i++) {
      const prevFast = wt1[i - 1]!;
      const prevSlow = wt2[i - 1]!;
      const fast = wt1[i]!;
      const slow = wt2[i]!;
      // A comparison against a missing value is false in the source definition,
      // which is what stops the warmup from firing a cross on its first print.
      if (!Number.isFinite(prevFast) || !Number.isFinite(prevSlow)) continue;
      if (!Number.isFinite(fast) || !Number.isFinite(slow)) continue;
      if (fast > slow && prevFast <= prevSlow && (!filterZone || slow <= osZone)) buy[i] = slow;
      if (fast < slow && prevFast >= prevSlow && (!filterZone || slow >= obZone)) sell[i] = slow;
    }

    // ── divergence, pivoting on the signal line rather than on price ────────
    // The bookkeeping is "the previous pivot" said three ways: a pivot is
    // confirmed `lbR` bars after it happened, the value-when lookup reads each
    // series as it stood at the pivot before this one, and the range gate counts
    // the bars since that predecessor. The gate counts from the found flag
    // delayed one bar, so the pivot being confirmed now is not its own
    // predecessor.
    const lbL = int(s, 'lbL', 3);
    const lbR = int(s, 'lbR', 3);
    const lower = int(s, 'rangeLower', 5);
    const upper = int(s, 'rangeUpper', 60);
    const wantRegular = s.showRegDiv !== false;
    const wantHidden = s.showHidDiv === true;

    const plFound = pivotLow(wt2, lbL, lbR).map((v) => Number.isFinite(v));
    const phFound = pivotHigh(wt2, lbL, lbR).map((v) => Number.isFinite(v));
    const oscAt = shift(wt2, lbR);
    const lowAt = shift(bars.map((b) => b.low), lbR);
    const highAt = shift(bars.map((b) => b.high), lbR);
    const sincePl = barsSince(shiftFlags(plFound, 1));
    const sincePh = barsSince(shiftFlags(phFound, 1));
    const prevOscLow = valueWhen(plFound, oscAt, 1);
    const prevPriceLow = valueWhen(plFound, lowAt, 1);
    const prevOscHigh = valueWhen(phFound, oscAt, 1);
    const prevPriceHigh = valueWhen(phFound, highAt, 1);

    for (let i = 0; i < n; i++) {
      // The signal belongs to the pivot bar, `lbR` back from its confirmation.
      const at = i - lbR;
      if (at < 0) continue;
      const oscPivot = oscAt[i]!;

      if (plFound[i]) {
        const inRange = lower <= sincePl[i]! && sincePl[i]! <= upper;
        if (wantRegular && inRange && oscPivot > prevOscLow[i]! && lowAt[i]! < prevPriceLow[i]!) {
          bull[at] = oscPivot;
        }
        if (wantHidden && inRange && oscPivot < prevOscLow[i]! && lowAt[i]! > prevPriceLow[i]!) {
          hiddenBull[at] = oscPivot;
        }
      }
      if (phFound[i]) {
        const inRange = lower <= sincePh[i]! && sincePh[i]! <= upper;
        if (wantRegular && inRange && oscPivot < prevOscHigh[i]! && highAt[i]! > prevPriceHigh[i]!) {
          bear[at] = oscPivot;
        }
        if (wantHidden && inRange && oscPivot > prevOscHigh[i]! && highAt[i]! < prevPriceHigh[i]!) {
          hiddenBear[at] = oscPivot;
        }
      }
    }

    return out;
  },
  // A cross and a divergence are named events at one bar, not columns of
  // prices, so both go through the marker layer. Every plate is anchored to the
  // signal line's own reading: a marker whose time is not a real bar time is
  // dropped, so the time comes from the bar rather than from arithmetic.
  markers: ({ bars, values, settings }) => {
    const bullColor = str(settings, 'bullColor', '#4caf50');
    const bearColor = str(settings, 'bearColor', '#ff5252');
    const classes = [
      {
        col: values.buy, shape: 'circle' as const, size: 'tiny' as const,
        color: str(settings, 'buyColor', '#00e676'), text: undefined as string | undefined,
      },
      {
        col: values.sell, shape: 'circle' as const, size: 'tiny' as const,
        color: str(settings, 'sellColor', '#ff5252'), text: undefined as string | undefined,
      },
      { col: values.bull, shape: 'labelUp' as const, size: 'small' as const, color: bullColor, text: 'R' },
      { col: values.bear, shape: 'labelDown' as const, size: 'small' as const, color: bearColor, text: 'R' },
      // The hidden pair takes the dimmer shade its source definition gives it,
      // so a chart showing both classes at once still reads which is which.
      { col: values.hiddenBull, shape: 'labelUp' as const, size: 'small' as const, color: dim(bullColor), text: 'H' },
      { col: values.hiddenBear, shape: 'labelDown' as const, size: 'small' as const, color: dim(bearColor), text: 'H' },
    ];
    const out: SeriesMarker[] = [];
    for (let i = 0; i < bars.length; i++) {
      for (const c of classes) {
        const v = c.col?.[i];
        if (v === null || v === undefined) continue;
        const marker: SeriesMarker = {
          time: bars[i]!.time, position: 'atPrice', price: v,
          shape: c.shape, size: c.size, color: c.color,
        };
        if (c.text !== undefined) marker.text = c.text;
        out.push(marker);
      }
    }
    return out;
  },
  // The level renderer has one dashed flag and no dotted variant, so the two
  // inner levels and the zero line come through dashed as well; the grey keeps
  // the zero line distinguishable from the four coloured ones.
  levels: (s) => [
    { price: num(s, 'obLevel1', 60), color: str(s, 'obBandColor', '#ff5252'), title: 'Overbought 1', dashed: true },
    { price: num(s, 'obLevel2', 53), color: str(s, 'obBandColor', '#ff5252'), title: 'Overbought 2', dashed: true },
    { price: 0, color: '#787b86', title: 'Zero', dashed: true },
    { price: num(s, 'osLevel2', -53), color: str(s, 'osBandColor', '#4caf50'), title: 'Oversold 2', dashed: true },
    { price: num(s, 'osLevel1', -60), color: str(s, 'osBandColor', '#4caf50'), title: 'Oversold 1', dashed: true },
  ],
};

export const WAVETREND_INDICATORS: readonly IndicatorDescriptor[] = [WAVETREND];
