/**
 * Tier-1 momentum / volatility indicators, computed from the chart's own OHLCV.
 * Part of the lazy `openalgo-charts/indicators` tier.
 */
import { rsi, atr, trueRange, sourceValues, sourceValue } from 'openalgo-charts';
import type { Bar, IndicatorDescriptor } from 'openalgo-charts';
import { sma, rma, smaSeededEma, stdev, highest, lowest, nulls, mfiFromFlows } from './calc';
import { fromFirstValue, smoothingBlock, smoothingInputs, smoothingPlots, smoothingFill } from './smoothing';
import { withTail, windowTail, machineTail, whole, cell, type Tail } from './tail';
import { seeded, smooth, rsiState, rsiStep, wilder, atrStep, trueRangeAt, meanAt } from './steppers';
import { withTimeframe } from './timeframe';
import { num, int, str, src } from './settings';
import { constant, zip } from './series';

type Calc = IndicatorDescriptor['calc'];

export const RSI: IndicatorDescriptor = withTimeframe(withTail({
  id: 'rsi',
  name: 'RSI',
  category: 'Momentum',
  placement: 'pane',
  inputs: [
    { key: 'length', type: 'number', label: 'Length', default: 14, min: 1, max: 500, step: 1 },
    { key: 'source', type: 'source', label: 'Source', default: 'close' },
    { key: 'color', type: 'color', label: 'Color', default: '#e0b020' },
    { key: 'overbought', type: 'number', label: 'Overbought', default: 70, min: 50, max: 100, step: 1 },
    { key: 'oversold', type: 'number', label: 'Oversold', default: 30, min: 0, max: 50, step: 1 },
    { key: 'bandColor', type: 'color', label: 'Background', default: '#7e57c2' },
  ],
  plots: [{ key: 'rsi', type: 'line', title: 'RSI', colorKey: 'color', style: { lineWidth: 1.5 } }],
  fills: [{
    between: ['upperLevel', 'lowerLevel'],
    colorUpKey: 'bandColor',
    colorDownKey: 'bandColor',
    opacity: 0.1,
  }],
  calc: (bars, s) => ({
    rsi: nulls(rsi(sourceValues(bars, src(s)), int(s, 'length', 14))),
    // The two band edges track the overbought / oversold inputs so the shading
    // stays glued to the reference lines when either is moved.
    upperLevel: constant(bars.length, num(s, 'overbought', 70)),
    lowerLevel: constant(bars.length, num(s, 'oversold', 30)),
  }),
  levels: (s) => [
    { price: num(s, 'overbought', 70), color: '#ef5350', title: 'OB', dashed: true },
    { price: 50, color: '#5a6b8c', title: '', dashed: true },
    { price: num(s, 'oversold', 30), color: '#26a69a', title: 'OS', dashed: true },
  ],
  range: () => ({ min: 0, max: 100 }),
}, (calc) => (bars, s, from, previous, store) => {
  const length = int(s, 'length', 14);
  if (!whole(length)) return null;
  const source = src(s);
  const upper = num(s, 'overbought', 70);
  const lower = num(s, 'oversold', 30);
  return machineTail(calc, `${length}|${source}|${upper}|${lower}`, {
    keys: ['rsi', 'upperLevel', 'lowerLevel'],
    start: rsiState,
    step: (st, i, row) => {
      row[0] = cell(rsiStep(st, sourceValue(bars[i]!, source), length));
      row[1] = upper;
      row[2] = lower;
    },
  }, bars, from, previous, store);
}));

export const MACD: IndicatorDescriptor = withTimeframe(withTail({
  id: 'macd',
  name: 'MACD',
  category: 'Momentum',
  placement: 'pane',
  inputs: [
    { key: 'fastPeriod', type: 'number', label: 'Fast', default: 12, min: 1, max: 500, step: 1 },
    { key: 'slowPeriod', type: 'number', label: 'Slow', default: 26, min: 1, max: 500, step: 1 },
    { key: 'signalPeriod', type: 'number', label: 'Signal', default: 9, min: 1, max: 500, step: 1 },
    { key: 'source', type: 'source', label: 'Source', default: 'close' },
    { key: 'macdColor', type: 'color', label: 'MACD', default: '#2962ff' },
    { key: 'histUpColor', type: 'color', label: 'Histogram up', default: '#26a69a' },
    { key: 'histUpFadeColor', type: 'color', label: 'Histogram up (weakening)', default: '#a7d8d2' },
    { key: 'histDownColor', type: 'color', label: 'Histogram down', default: '#ef5350' },
    { key: 'histDownFadeColor', type: 'color', label: 'Histogram down (weakening)', default: '#f5b0ae' },
    { key: 'signalColor', type: 'color', label: 'Signal', default: '#ff6d00' },
  ],
  plots: [
    {
      key: 'histogram', type: 'histogram', title: 'Histogram',
      style: { color: '#3a4666', base: 0 },
      // Four states, not one colour: sign says which side of zero, and the
      // direction against the previous bar says whether that momentum is
      // building or fading. A single colour throws the second half away.
      colorBy: ({ value, index, values, settings }) => {
        const prev = values.histogram?.[index - 1];
        const rising = prev === null || prev === undefined || !Number.isFinite(prev)
          ? true
          : value >= prev;
        if (value >= 0) {
          return rising
            ? str(settings, 'histUpColor', '#26a69a')
            : str(settings, 'histUpFadeColor', '#a7d8d2');
        }
        return rising
          ? str(settings, 'histDownFadeColor', '#f5b0ae')
          : str(settings, 'histDownColor', '#ef5350');
      },
    },
    { key: 'macd', type: 'line', title: 'MACD', colorKey: 'macdColor', style: { lineWidth: 1.5 } },
    { key: 'signal', type: 'line', title: 'Signal', colorKey: 'signalColor', style: { lineWidth: 1.5 } },
  ],
  calc: (bars, s) => {
    const values = sourceValues(bars, src(s));
    // The standard definition seeds each EMA with the SMA of its first `period`
    // values, so the study has a real warmup. The base bundle's `ema` seeds from
    // bar 0 instead, which prints a line where there should be a gap and stays
    // materially wrong until the seeds decay away.
    const fast = smaSeededEma(values, int(s, 'fastPeriod', 12));
    const slow = smaSeededEma(values, int(s, 'slowPeriod', 26));
    // Every kernel here returns one value per input.
    const macd = zip(fast, slow, (f, sl) => f - sl);
    // The difference opens with its own warmup gap, so the signal's window has
    // to start counting at the first real MACD value.
    const signal = fromFirstValue(macd, (t) => smaSeededEma(t, int(s, 'signalPeriod', 9)));
    const histogram = zip(macd, signal, (m, sig) => m - sig);
    return { macd: nulls(macd), signal: nulls(signal), histogram: nulls(histogram) };
  },
  levels: () => [{ price: 0, color: '#5a6b8c', dashed: true }],
}, (calc) => (bars, s, from, previous, store) => {
  const fast = int(s, 'fastPeriod', 12);
  const slow = int(s, 'slowPeriod', 26);
  const signal = int(s, 'signalPeriod', 9);
  if (!whole(fast) || !whole(slow) || !whole(signal)) return null;
  const source = src(s);
  // The signal's leading gap is the MACD's warmup, which a seeded average
  // steps over the same way `fromFirstValue` trims it.
  return machineTail(calc, `${fast}|${slow}|${signal}|${source}`, {
    keys: ['macd', 'signal', 'histogram'],
    start: () => ({ fast: seeded(), slow: seeded(), signal: seeded() }),
    step: (st, i, row) => {
      const x = sourceValue(bars[i]!, source);
      const m = smooth(st.fast, x, fast, true) - smooth(st.slow, x, slow, true);
      const sig = smooth(st.signal, m, signal, true);
      row[0] = cell(m);
      row[1] = cell(sig);
      row[2] = cell(m - sig);
    },
  }, bars, from, previous, store);
}));

export const STOCHASTIC: IndicatorDescriptor = withTimeframe(withTail({
  id: 'stochastic',
  name: 'Stochastic',
  category: 'Momentum',
  placement: 'pane',
  inputs: [
    { key: 'kPeriod', type: 'number', label: '%K Length', default: 14, min: 1, max: 500, step: 1 },
    { key: 'kSmoothing', type: 'number', label: '%K Smoothing', default: 1, min: 1, max: 100, step: 1 },
    { key: 'dPeriod', type: 'number', label: '%D Smoothing', default: 3, min: 1, max: 100, step: 1 },
    { key: 'kColor', type: 'color', label: '%K', default: '#4f8cff' },
    { key: 'dColor', type: 'color', label: '%D', default: '#f5a623' },
    { key: 'bandColor', type: 'color', label: 'Background', default: '#2196f3' },
  ],
  plots: [
    { key: 'k', type: 'line', title: '%K', colorKey: 'kColor', style: { lineWidth: 1.5 } },
    { key: 'd', type: 'line', title: '%D', colorKey: 'dColor', style: { lineWidth: 1.5 } },
  ],
  fills: [{
    between: ['upperLevel', 'lowerLevel'],
    colorUpKey: 'bandColor',
    colorDownKey: 'bandColor',
    opacity: 0.1,
  }],
  calc: (bars, s) => {
    const hi = highest(bars.map((b) => b.high), int(s, 'kPeriod', 14));
    const lo = lowest(bars.map((b) => b.low), int(s, 'kPeriod', 14));
    // Scaled before dividing, the arrangement the definition fixes. A span
    // that overflows has no reading, where dividing by it printed a flat 0; a
    // scaled distance that overflows leaves an infinity, which the smoothing
    // and `nulls` both drop as absent.
    // `hi` and `lo` hold one value per bar.
    const raw = bars.map((b, i) => {
      const span = hi[i]! - lo[i]!;
      return span > 0 && span < Infinity ? (100 * (b.close - lo[i]!)) / span : NaN;
    });
    const k = sma(raw, int(s, 'kSmoothing', 1));
    const d = sma(k, int(s, 'dPeriod', 3));
    // The 80 / 20 band edges are fixed in the definition, so they are literals
    // here rather than inputs.
    return {
      k: nulls(k),
      d: nulls(d),
      upperLevel: constant(bars.length, 80),
      lowerLevel: constant(bars.length, 20),
    };
  },
  levels: () => [
    { price: 80, color: '#ef5350', title: 'OB', dashed: true },
    { price: 20, color: '#26a69a', title: 'OS', dashed: true },
  ],
  range: () => ({ min: 0, max: 100 }),
}, (calc) => windowTail(calc, (s) => {
  // %D averages %K, which averages the raw reading, which reads the range.
  const k = int(s, 'kPeriod', 14);
  const smoothing = int(s, 'kSmoothing', 1);
  const d = int(s, 'dPeriod', 3);
  return whole(k) && whole(smoothing) && whole(d) ? k + smoothing + d - 3 : null;
})));

export const ADX: IndicatorDescriptor = withTimeframe(withTail({
  id: 'adx',
  name: 'ADX / DMI',
  category: 'Trend',
  placement: 'pane',
  inputs: [
    { key: 'period', type: 'number', label: 'DI Length', default: 14, min: 1, max: 500, step: 1 },
    { key: 'adxPeriod', type: 'number', label: 'ADX Smoothing', default: 14, min: 1, max: 500, step: 1 },
    { key: 'adxColor', type: 'color', label: 'ADX', default: '#e0e3ea' },
    { key: 'plusColor', type: 'color', label: '+DI', default: '#26a69a' },
    { key: 'minusColor', type: 'color', label: '-DI', default: '#ef5350' },
  ],
  plots: [
    { key: 'plusDi', type: 'line', title: '+DI', colorKey: 'plusColor', style: { lineWidth: 1 } },
    { key: 'minusDi', type: 'line', title: '-DI', colorKey: 'minusColor', style: { lineWidth: 1 } },
    { key: 'adx', type: 'line', title: 'ADX', colorKey: 'adxColor', style: { lineWidth: 1.5 } },
  ],
  calc: (bars, s) => {
    const n = bars.length;
    const period = int(s, 'period', 14);
    const high = bars.map((b) => b.high);
    const low = bars.map((b) => b.low);
    const close = bars.map((b) => b.close);
    const tr = trueRange(high, low, close);
    // True range needs the previous close, which bar 0 does not have. The shared
    // helper substitutes high-low there for ATR's sake; seeding Wilder's average
    // on that fabricated term starts the whole study a bar early and biases every
    // value after it, so the standard definition leaves bar 0 absent here.
    if (n > 0) tr[0] = NaN;
    const plusDm = new Array<number>(n).fill(NaN);
    const minusDm = new Array<number>(n).fill(NaN);
    // Every column here holds one value per bar.
    for (let i = 1; i < n; i++) {
      if (!Number.isFinite(high[i]) || !Number.isFinite(low[i])
        || !Number.isFinite(high[i - 1]) || !Number.isFinite(low[i - 1])) continue;
      const up = high[i]! - high[i - 1]!;
      const down = low[i - 1]! - low[i]!;
      plusDm[i] = up > down && up > 0 ? up : 0;
      minusDm[i] = down > up && down > 0 ? down : 0;
    }
    // Bar 0 is absent in every stream. Later partial observations can make their
    // finite windows start separately, so each smoother retains its own history.
    const trR = rma(tr, period);
    const plusR = rma(plusDm, period);
    const minusR = rma(minusDm, period);
    const plusDi = new Array<number>(n).fill(NaN);
    const minusDi = new Array<number>(n).fill(NaN);
    const dx = new Array<number>(n).fill(NaN);
    // A zero or unavailable denominator defines no directional ratio. Emitting
    // a held reading would also advance DX and ADX with an invented observation.
    for (let i = 0; i < n; i++) {
      const range = trR[i]!;
      if (!Number.isFinite(range) || range === 0) continue;
      const plus = (plusR[i]! / range) * 100;
      const minus = (minusR[i]! / range) * 100;
      if (Number.isFinite(plus)) plusDi[i] = plus;
      if (Number.isFinite(minus)) minusDi[i] = minus;
      if (!Number.isFinite(plusDi[i]) || !Number.isFinite(minusDi[i])) continue;
      const sum = plusDi[i]! + minusDi[i]!;
      dx[i] = sum > 0 ? (Math.abs(plusDi[i]! - minusDi[i]!) / sum) * 100 : 0;
    }
    // The DX series is NaN during DI warmup; smooth only the finite tail.
    const adx = fromFirstValue(dx, (tail) => rma(tail, int(s, 'adxPeriod', 14)));
    return { plusDi: nulls(plusDi), minusDi: nulls(minusDi), adx: nulls(adx) };
  },
  levels: () => [{ price: 25, color: '#5a6b8c', title: '25', dashed: true }],
}, (calc) => (bars, s, from, previous, store) => {
  const period = int(s, 'period', 14);
  const adxPeriod = int(s, 'adxPeriod', 14);
  if (!whole(period) || !whole(adxPeriod)) return null;
  return machineTail(calc, `${period}|${adxPeriod}`, {
    keys: ['plusDi', 'minusDi', 'adx'],
    start: () => ({ tr: seeded(), plus: seeded(), minus: seeded(), adx: seeded() }),
    step: (st, i, row) => {
      const [tr, up, down] = directionalAt(bars, i);
      const range = smooth(st.tr, tr, period, false);
      const plusR = smooth(st.plus, up, period, false);
      const minusR = smooth(st.minus, down, period, false);
      let plusDi = NaN;
      let minusDi = NaN;
      let dx = NaN;
      if (Number.isFinite(range) && range !== 0) {
        const plus = (plusR / range) * 100;
        const minus = (minusR / range) * 100;
        if (Number.isFinite(plus)) plusDi = plus;
        if (Number.isFinite(minus)) minusDi = minus;
        if (Number.isFinite(plusDi) && Number.isFinite(minusDi)) {
          const sum = plusDi + minusDi;
          dx = sum > 0 ? (Math.abs(plusDi - minusDi) / sum) * 100 : 0;
        }
      }
      row[0] = cell(plusDi);
      row[1] = cell(minusDi);
      row[2] = cell(smooth(st.adx, dx, adxPeriod, false));
    },
  }, bars, from, previous, store);
}));

/** ADX's three inputs at one bar: true range and the two directional moves, all absent on bar 0. */
function directionalAt(bars: readonly Bar[], i: number): [number, number, number] {
  if (i === 0) return [NaN, NaN, NaN];
  const b = bars[i]!;
  const p = bars[i - 1]!;
  const tr = trueRangeAt(bars, i);
  if (!Number.isFinite(b.high) || !Number.isFinite(b.low) || !Number.isFinite(p.high) || !Number.isFinite(p.low)) {
    return [tr, NaN, NaN];
  }
  const up = b.high - p.high;
  const down = p.low - b.low;
  return [tr, up > down && up > 0 ? up : 0, down > up && down > 0 ? down : 0];
}

export const CCI: IndicatorDescriptor = withTimeframe(withTail({
  id: 'cci',
  name: 'CCI',
  category: 'Momentum',
  placement: 'pane',
  inputs: [
    { key: 'period', type: 'number', label: 'Length', default: 20, min: 1, max: 500, step: 1 },
    { key: 'constant', type: 'number', label: 'Constant', default: 0.015, min: 0.001, max: 1, step: 0.001 },
    { key: 'color', type: 'color', label: 'Color', default: '#26c6da' },
    { key: 'bandColor', type: 'color', label: 'Background', default: '#2196f3' },
    ...smoothingInputs('CCI', 'SMA', 20),
  ],
  plots: [
    { key: 'cci', type: 'line', title: 'CCI', colorKey: 'color', style: { lineWidth: 1.5 } },
    ...smoothingPlots('CCI'),
  ],
  // Background first, so the Bollinger shading sits on top of it rather than
  // underneath.
  fills: [
    {
      between: ['upperLevel', 'lowerLevel'],
      colorUpKey: 'bandColor',
      colorDownKey: 'bandColor',
      opacity: 0.1,
    },
    smoothingFill(),
  ],
  calc: (bars, s) => {
    const n = bars.length;
    const period = int(s, 'period', 20);
    const k = num(s, 'constant', 0.015);
    const tp = bars.map((b) => (b.high + b.low + b.close) / 3);
    const avg = sma(tp, period);
    const out = new Array<number>(n).fill(NaN);
    // A whole period reads [i - period + 1, i]. A fractional one reads between
    // bars, and its NaN deviation leaves those readings absent.
    for (let i = period - 1; i < n; i++) {
      let dev = 0;
      for (let j = 0; j < period; j++) dev += Math.abs(tp[i - j]! - avg[i]!);
      const md = dev / period;
      // A window holding a missing bar, or one whose deviation overflows, has
      // no reading. Only a genuinely flat window (md exactly 0) prints 0; the
      // public `cci` kernel, which Woodies CCI uses, has no reading there.
      out[i] = !Number.isFinite(md) ? NaN : md > 0 ? (tp[i]! - avg[i]!) / (k * md) : 0;
    }

    return {
      cci: nulls(out),
      ...smoothingBlock(out, bars.map((b) => b.volume ?? 0), s, 'SMA', 20),
      upperLevel: constant(n, 100),
      lowerLevel: constant(n, -100),
    };
  },
  levels: () => [
    { price: 100, color: '#ef5350', dashed: true },
    { price: 0, color: '#5a6b8c', dashed: true },
    { price: -100, color: '#26a69a', dashed: true },
  ],
}, cciTail));

/**
 * CCI reads one window of typical prices. Its smoothing either reads a window
 * of CCI in turn, and the whole study reruns over the run that covers both, or
 * carries an exponential or Wilder average, which resumes.
 */
function cciTail(calc: Calc): Tail {
  const windowed = windowTail(calc, (s) => {
    const period = int(s, 'period', 20);
    const maLength = int(s, 'maLength', 20);
    if (!whole(period) || !whole(maLength)) return null;
    return period - 1 + (str(s, 'maType', 'SMA') === 'None' ? 0 : maLength - 1);
  });
  return (bars, s, from, previous, store, ctx) => {
    const maType = str(s, 'maType', 'SMA');
    if (maType !== 'EMA' && maType !== 'SMMA (RMA)') return windowed(bars, s, from, previous, store, ctx);
    const period = int(s, 'period', 20);
    const k = num(s, 'constant', 0.015);
    const maLength = int(s, 'maLength', 20);
    if (!whole(period) || !whole(maLength)) return null;
    // Read at `i` and the whole window before it, all bars once `i` has warmed up.
    const tp = (j: number): number => (bars[j]!.high + bars[j]!.low + bars[j]!.close) / 3;
    return machineTail(calc, `${period}|${k}|${maType}|${maLength}`, {
      keys: ['cci', 'ma', 'bbUpper', 'bbLower', 'upperLevel', 'lowerLevel'],
      start: seeded,
      step: (st, i, row) => {
        let out = NaN;
        if (i >= period - 1) {
          const avg = meanAt(tp, i, period);
          const typical = tp(i);
          let dev = 0;
          for (let j = 0; j < period; j++) dev += Math.abs(tp(i - j) - avg);
          const md = dev / period;
          out = !Number.isFinite(md) ? NaN : md > 0 ? (typical - avg) / (k * md) : 0;
        }
        row[0] = cell(out);
        row[1] = cell(smooth(st, out, maLength, maType === 'EMA'));
        row[2] = null;
        row[3] = null;
        row[4] = 100;
        row[5] = -100;
      },
    }, bars, from, previous, store);
  };
}

export const MFI: IndicatorDescriptor = {
  id: 'mfi',
  name: 'Money Flow Index',
  category: 'Momentum',
  placement: 'pane',
  inputs: [
    { key: 'period', type: 'number', label: 'Length', default: 14, min: 1, max: 500, step: 1 },
    { key: 'color', type: 'color', label: 'Color', default: '#ab47bc' },
    { key: 'bandColor', type: 'color', label: 'Background', default: '#7e57c2' },
  ],
  plots: [{ key: 'mfi', type: 'line', title: 'MFI', colorKey: 'color', style: { lineWidth: 1.5 } }],
  fills: [{
    between: ['upperLevel', 'lowerLevel'],
    colorUpKey: 'bandColor',
    colorDownKey: 'bandColor',
    opacity: 0.1,
  }],
  calc: (bars, s) => {
    const n = bars.length;
    const period = int(s, 'period', 14);
    const tp = bars.map((b) => (b.high + b.low + b.close) / 3);
    const pos = new Array<number>(n).fill(0);
    const neg = new Array<number>(n).fill(0);
    // `tp`, `pos` and `neg` hold one value per bar. A bar without a typical
    // price or a volume is absent, so no window holding it has a reading.
    // AlphaTrend's gauge (./studies) forms its flows the published script's
    // way, where such a bar compares false and adds no flow; the two are kept
    // apart because each is the output its study is pinned to.
    for (let i = 1; i < n; i++) {
      const volume = bars[i]!.volume ?? 0;
      if (!Number.isFinite(tp[i]) || !Number.isFinite(tp[i - 1]) || !Number.isFinite(volume)) {
        pos[i] = NaN;
        neg[i] = NaN;
        continue;
      }
      const rawFlow = tp[i]! * volume;
      const flow = Number.isFinite(rawFlow) ? rawFlow : NaN;
      // A price tie contributes zero even when its unused raw product overflows.
      if (tp[i]! > tp[i - 1]!) pos[i] = flow;
      else if (tp[i]! < tp[i - 1]!) neg[i] = flow;
    }
    // The 80 / 20 band edges are fixed in the definition, so they are literals
    // here rather than inputs.
    return {
      mfi: nulls(mfiFromFlows(pos, neg, period)),
      upperLevel: constant(n, 80),
      lowerLevel: constant(n, 20),
    };
  },
  levels: () => [
    { price: 80, color: '#ef5350', title: 'OB', dashed: true },
    { price: 20, color: '#26a69a', title: 'OS', dashed: true },
  ],
  range: () => ({ min: 0, max: 100 }),
};

export const ATR: IndicatorDescriptor = withTimeframe(withTail({
  id: 'atr',
  name: 'ATR',
  category: 'Volatility',
  placement: 'pane',
  inputs: [
    { key: 'period', type: 'number', label: 'Length', default: 14, min: 1, max: 500, step: 1 },
    { key: 'color', type: 'color', label: 'Color', default: '#f5a623' },
  ],
  plots: [{ key: 'atr', type: 'line', title: 'ATR', colorKey: 'color', style: { lineWidth: 1.5 } }],
  calc: (bars, s) => ({
    atr: nulls(atr(bars.map((b) => b.high), bars.map((b) => b.low), bars.map((b) => b.close), int(s, 'period', 14))),
  }),
}, (calc) => (bars, s, from, previous, store) => {
  const period = int(s, 'period', 14);
  if (!whole(period)) return null;
  return machineTail(calc, `${period}`, {
    keys: ['atr'],
    start: wilder,
    step: (st, i, row) => { row[0] = cell(atrStep(st, trueRangeAt(bars, i), period)); },
  }, bars, from, previous, store);
}));

/**
 * CM Williams Vix Fix: a synthetic VIX from price alone.
 *
 * `wvf` is how far the current low sits below the highest close of the lookback,
 * as a percentage: a spike means capitulation. The signal is not the level but
 * the *breakout* (`wvf` piercing its own Bollinger upper band, or the top
 * percentile of its recent range), so the histogram carries two colours and the
 * bands are what it is measured against.
 */
export const WILLIAMS_VIX_FIX: IndicatorDescriptor = {
  id: 'williams-vix-fix',
  name: 'Williams VIX Fix',
  category: 'Volatility',
  placement: 'pane',
  inputs: [
    { key: 'pd', type: 'number', label: 'LookBack Period Standard Deviation High', default: 22, min: 1, max: 500, step: 1 },
    { key: 'bbl', type: 'number', label: 'Bollinger Band Length', default: 20, min: 1, max: 500, step: 1 },
    { key: 'mult', type: 'number', label: 'Bollinger Band Standard Deviation Up', default: 2, min: 1, max: 5, step: 0.1 },
    { key: 'lb', type: 'number', label: 'Look Back Period Percentile High', default: 50, min: 1, max: 500, step: 1 },
    { key: 'ph', type: 'number', label: 'Highest Percentile', default: 0.85, min: 0, max: 1, step: 0.01 },
    { key: 'pl', type: 'number', label: 'Lowest Percentile', default: 1.01, min: 1, max: 2, step: 0.01 },
    { key: 'hp', type: 'boolean', label: 'Show High Range', default: false },
    { key: 'sd', type: 'boolean', label: 'Show Standard Deviation Line', default: false },
    { key: 'highColor', type: 'color', label: 'Alert', default: '#00ff00' },
    { key: 'normalColor', type: 'color', label: 'Normal', default: '#808080' },
    { key: 'rangeColor', type: 'color', label: 'Range', default: '#ffa500' },
    { key: 'bandColor', type: 'color', label: 'Band', default: '#00ffff' },
  ],
  plots: [
    {
      key: 'wvf', type: 'histogram', title: 'Williams Vix Fix',
      style: { lineWidth: 4, base: 0 },
      // Lime once wvf breaks its upper band or the range high, gray otherwise:
      // the study is a state, not a level.
      colorBy: ({ index, values, settings }) => {
        const v = values.wvf?.[index];
        const upper = values.alertUpper?.[index];
        const high = values.alertHigh?.[index];
        if (v === null || v === undefined) return undefined;
        const hitBand = upper !== null && upper !== undefined && v >= upper;
        const hitRange = high !== null && high !== undefined && v >= high;
        return hitBand || hitRange ? str(settings, 'highColor', '#00ff00') : str(settings, 'normalColor', '#808080');
      },
    },
    { key: 'rangeHigh', type: 'line', title: 'Range High Percentile', colorKey: 'rangeColor', style: { lineWidth: 4 } },
    { key: 'rangeLow', type: 'line', title: 'Range Low Percentile', colorKey: 'rangeColor', style: { lineWidth: 4 } },
    { key: 'upperBand', type: 'line', title: 'Upper Band', colorKey: 'bandColor', style: { lineWidth: 3 } },
  ],
  calc: (bars, s) => {
    const n = bars.length;
    const closes = bars.map((b) => b.close);
    const lows = bars.map((b) => b.low);
    const pd = int(s, 'pd', 22);
    const bbl = int(s, 'bbl', 20);
    const mult = num(s, 'mult', 2);
    const lb = int(s, 'lb', 50);
    const ph = num(s, 'ph', 0.85);
    const pl = num(s, 'pl', 1.01);
    const showRange = s.hp === true;
    const showBand = s.sd === true;

    const highestClose = highest(closes, pd);
    const wvf = new Array<number>(n);
    // Every column here holds one value per bar.
    for (let i = 0; i < n; i++) {
      const hc = highestClose[i]!;
      wvf[i] = Number.isFinite(hc) && hc !== 0 ? ((hc - lows[i]!) / hc) * 100 : NaN;
    }

    const dev = stdev(wvf, bbl);
    const mid = sma(wvf, bbl);
    const highestWvf = highest(wvf, lb);
    const lowestWvf = lowest(wvf, lb);

    // Two sets of columns. The plotted ones honour the show toggles, exactly as
    // the reference `sd and upperBand ? ... : na` guards do. The colour rule needs
    // the real values whether or not they are drawn, so it reads its own pair:
    // hiding the band must not silently stop the histogram going lime.
    const upper: (number | null)[] = new Array(n);
    const high: (number | null)[] = new Array(n);
    const plotUpper: (number | null)[] = new Array(n);
    const plotHigh: (number | null)[] = new Array(n);
    const plotLow: (number | null)[] = new Array(n);
    for (let i = 0; i < n; i++) {
      const up = mid[i]! + mult * dev[i]!;
      const rh = highestWvf[i]! * ph;
      const rl = lowestWvf[i]! * pl;
      upper[i] = Number.isFinite(up) ? up : null;
      high[i] = Number.isFinite(rh) ? rh : null;
      plotUpper[i] = showBand ? upper[i] as number | null : null;
      plotHigh[i] = showRange ? high[i] as number | null : null;
      plotLow[i] = showRange && Number.isFinite(rl) ? rl : null;
    }

    return {
      wvf: nulls(wvf),
      rangeHigh: plotHigh,
      rangeLow: plotLow,
      upperBand: plotUpper,
      // Colour-only columns: no plot names them, so nothing draws them.
      alertUpper: upper,
      alertHigh: high,
    };
  },
};
