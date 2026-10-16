/**
 * Tier-1 volume indicators, computed from the chart's own OHLCV.
 * Part of the lazy `openalgo-charts/indicators` tier.
 */
import type { IndicatorDescriptor } from 'openalgo-charts';
import { nulls, sma } from './calc';
import { smoothingBlock, smoothingInputs, smoothingPlots, smoothingFill } from './smoothing';
import { withTail, machineTail, claimOf, settle, whole, cell } from './tail';
import { seeded, smooth } from './steppers';
import { int, str } from './settings';
import { volumeOf } from './series';

export const VOLUME: IndicatorDescriptor = {
  id: 'volume',
  name: 'Volume',
  category: 'Volume',
  placement: 'pane',
  inputs: [
    { key: 'color', type: 'color', label: 'Color', default: '#3a4666' },
    { key: 'colorByDirection', type: 'boolean', label: 'Match candle direction', default: false },
    { key: 'upColor', type: 'color', label: 'Up candle', default: '#26a69a' },
    { key: 'downColor', type: 'color', label: 'Down candle', default: '#ef5350' },
    { key: 'showMA', type: 'boolean', label: 'Show moving average', default: false, group: 'Moving average' },
    { key: 'maPeriod', type: 'number', label: 'Period', default: 20, min: 1, max: 500, step: 1, group: 'Moving average' },
    { key: 'maColor', type: 'color', label: 'Color', default: '#e6b53c', group: 'Moving average' },
  ],
  plots: [
    {
      key: 'volume', type: 'histogram', title: 'Volume', colorKey: 'color', style: { base: 0 },
      // `calc` below always writes `direction`.
      colorBy: ({ index, values, settings }) => settings.colorByDirection === true
        ? values.direction![index] === -1 ? str(settings, 'downColor', '#ef5350') : str(settings, 'upColor', '#26a69a')
        : undefined,
    },
    { key: 'ma', type: 'line', title: 'Volume average', colorKey: 'maColor', style: { lineWidth: 1.5 } },
  ],
  calc: (bars, settings) => {
    const volume = bars.map(b => b.volume ?? 0);
    return {
      volume: nulls(volume),
      direction: bars.map(b => b.close >= b.open ? 1 : -1),
      ma: settings.showMA === true ? nulls(sma(volume, int(settings, 'maPeriod', 20))) : volume.map(() => null),
    };
  },
};

export const OBV: IndicatorDescriptor = withTail({
  id: 'obv',
  name: 'On-Balance Volume',
  category: 'Volume',
  placement: 'pane',
  inputs: [
    { key: 'color', type: 'color', label: 'Color', default: '#26c6da' },
    // 9, not the 14 the smoothing block carries elsewhere: the reference
    // definition of this study fixes its own smoothing length at 9.
    ...smoothingInputs('OBV', 'None', 9),
  ],
  plots: [
    { key: 'obv', type: 'line', title: 'OBV', colorKey: 'color', style: { lineWidth: 1.5 } },
    ...smoothingPlots('OBV'),
  ],
  fills: [smoothingFill()],
  calc: (bars, s) => {
    const n = bars.length;
    const out = new Array<number>(n).fill(NaN);
    let acc = 0;
    for (let i = 0; i < n; i++) {
      if (i > 0) {
        const bar = bars[i]!;
        const prev = bars[i - 1]!;
        const v = volumeOf(bar);
        if (bar.close > prev.close) acc += v;
        else if (bar.close < prev.close) acc -= v;
      }
      out[i] = acc;
    }
    return { obv: nulls(out), ...smoothingBlock(out, bars.map(volumeOf), s, 'None', 9) };
  },
}, (calc) => (bars, s, from, previous, store) => {
  // The running total resumes. An exponential or Wilder smoothing resumes with
  // it; a window over the total reads the held values before the tail, which
  // are exact wherever finite and absent wherever the total was not, and a
  // window treats every absent value alike.
  const maType = str(s, 'maType', 'None');
  const maLength = int(s, 'maLength', 9);
  if (!whole(maLength)) return null;
  const recursive = maType === 'EMA' || maType === 'SMMA (RMA)';
  const tail = machineTail(calc, `${maType}|${maLength}`, {
    keys: recursive ? ['obv', 'ma', 'bbUpper', 'bbLower'] : ['obv'],
    start: () => ({ acc: 0, ma: seeded() }),
    step: (st, i, row) => {
      if (i > 0) {
        const bar = bars[i]!;
        const prev = bars[i - 1]!;
        const v = volumeOf(bar);
        if (bar.close > prev.close) st.acc += v;
        else if (bar.close < prev.close) st.acc -= v;
      }
      row[0] = cell(st.acc);
      if (!recursive) return;
      row[1] = cell(smooth(st.ma, st.acc, maLength, maType === 'EMA'));
      row[2] = null;
      row[3] = null;
    },
  }, bars, from, previous, store);
  if (tail === null || recursive) return tail;
  const held = previous.obv;
  const claim = claimOf(store, calc, bars, from);
  if (claim === undefined || held === undefined || held.length < from) return null;
  const start = Math.max(0, from - maLength);
  // The machine above writes `obv`.
  const run: number[] = [];
  for (let j = start; j < bars.length; j++) run.push((j < from ? held[j] : tail.obv![j - from]) ?? NaN);
  const smoothed = settle(claim, smoothingBlock(run, bars.slice(start).map(volumeOf), s, 'None', 9), from - start, previous, from);
  return smoothed === null ? null : { obv: tail.obv!, ...smoothed };
});

export const ADL: IndicatorDescriptor = {
  id: 'adl',
  name: 'Accumulation/Distribution',
  category: 'Volume',
  placement: 'pane',
  inputs: [{ key: 'color', type: 'color', label: 'Color', default: '#4f8cff' }],
  plots: [{ key: 'adl', type: 'line', title: 'A/D Line', colorKey: 'color', style: { lineWidth: 1.5 } }],
  calc: (bars) => {
    const out = new Array<number>(bars.length).fill(NaN);
    let acc = 0;
    for (let i = 0; i < bars.length; i++) {
      const b = bars[i]!;
      // A bar missing its high, low or close, or whose span or term overflows, has
      // no term: it is absent and the total stays where it was. Added in, one NaN
      // would blank the line for the rest of the history, and a missing high used
      // to pass for a doji and print the carried total as if it were a reading.
      if (!Number.isFinite(b.high) || !Number.isFinite(b.low) || !Number.isFinite(b.close)) continue;
      const span = b.high - b.low;
      if (!Number.isFinite(span)) continue;
      // A doji bar (high === low) has an undefined money-flow multiplier;
      // the standard treatment is to contribute nothing.
      if (span > 0) {
        const term = (((b.close - b.low) - (b.high - b.close)) / span) * volumeOf(b);
        if (!Number.isFinite(term)) continue;
        acc += term;
      }
      out[i] = acc;
    }
    return { adl: nulls(out) };
  },
};
