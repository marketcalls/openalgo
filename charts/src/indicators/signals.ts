/**
 * Signal-bearing trend studies: two paired-line studies, a correlation study,
 * two whose whole output is named events rather than a curve, and a state
 * machine over the bars themselves. Part of the lazy
 * `openalgo-charts/indicators` tier.
 *
 * These are reproductions of published formulas, faithful down to the warmup
 * gap: someone comparing one of these against the same study elsewhere has to
 * read the same numbers. Two conventions of the source definitions drive the
 * null handling below:
 *   - a missing value propagates through arithmetic and through a rolling sum,
 *     so a window that reaches back past the first bar has no value of its own;
 *   - a comparison against a missing value is false, which is what stops a
 *     warming-up series from producing a pivot or a signal.
 *
 * Three of the six are nothing but plot lines. The other three carry *signals*
 * too: the fractals are nothing but shapes, the divergence study draws labelled
 * plates at pivots, and the consolidation study marks the bar that leaves the
 * range. Those go through the descriptor's `markers` hook, because a plot is a
 * column of prices and a signal is a named event at one bar.
 */
import { rsi, atr, trueRange, sourceValues } from 'openalgo-charts';
import type { IndicatorDescriptor, SeriesMarker } from 'openalgo-charts';
import {
  nulls, rollingSum, correlation, pivotHigh, pivotLow, barsSince, valueWhen,
} from './calc';
import { num, int, str, flag, src } from './settings';
import { shift, shiftFlags } from './series';

/**
 * Vortex Indicator: how much of the window's total travel was spent reaching up
 * versus reaching down.
 *
 * Both movement terms straddle a bar boundary (`high` against the previous
 * `low`), so bar 0 has no term at all: it is missing there, and so is any
 * rolling-sum window containing it. Summing from bar 1 and shifting the answer
 * forward one bar is how that hole stays out of the running total, and it is why
 * the first printed value lands at index `length` rather than at `length - 1`
 * like the denominator does.
 */
export const VORTEX: IndicatorDescriptor = {
  id: 'vortex',
  name: 'Vortex Indicator',
  category: 'Trend',
  placement: 'pane',
  inputs: [
    { key: 'length', type: 'number', label: 'Length', default: 14, min: 2, max: 500, step: 1 },
    { key: 'upColor', type: 'color', label: 'VI +', default: '#2962ff' },
    { key: 'downColor', type: 'color', label: 'VI -', default: '#e91e63' },
  ],
  plots: [
    { key: 'vip', type: 'line', title: 'VI +', colorKey: 'upColor', style: { lineWidth: 1.5 } },
    { key: 'vim', type: 'line', title: 'VI -', colorKey: 'downColor', style: { lineWidth: 1.5 } },
  ],
  calc: (bars, s) => {
    const n = bars.length;
    const length = int(s, 'length', 14);
    const vip = new Array<number>(n).fill(NaN);
    const vim = new Array<number>(n).fill(NaN);
    if (n === 0) return { vip: nulls(vip), vim: nulls(vim) };

    const high = bars.map((b) => b.high);
    const low = bars.map((b) => b.low);
    const close = bars.map((b) => b.close);
    const upTerm = new Array<number>(n - 1);
    const downTerm = new Array<number>(n - 1);
    // The bar columns and `trSum` hold n values; the terms and their sums hold
    // n - 1, one per bar from bar 1, so bar `i` reads term `i - 1`.
    for (let i = 1; i < n; i++) {
      upTerm[i - 1] = Math.abs(high[i]! - low[i - 1]!);
      downTerm[i - 1] = Math.abs(low[i]! - high[i - 1]!);
    }
    const vmp = rollingSum(upTerm, length);
    const vmm = rollingSum(downTerm, length);
    // A one-bar ATR is Wilder's average of the true range over a single bar,
    // which is the true range itself. Its bar 0 is `high - low`, so the
    // denominator warms up one bar earlier than the numerators.
    const trSum = rollingSum(trueRange(high, low, close), length);

    for (let i = 1; i < n; i++) {
      vip[i] = vmp[i - 1]! / trSum[i]!;
      vim[i] = vmm[i - 1]! / trSum[i]!;
    }
    return { vip: nulls(vip), vim: nulls(vim) };
  },
};

/**
 * Volatility Stop: a trailing stop an ATR multiple away from the running
 * extreme of the source, which flips side when price closes through it.
 *
 * The recursion is the whole study, so it is reproduced term for term. Three
 * details are load-bearing:
 *   - while the ATR is still warming there is no band to scale, and the formula
 *     falls back to the bar's own true range, unmultiplied, so the stop exists
 *     from bar 0. The ATR resumes after a missing bar, so this covers the
 *     warmup alone. An ATR that never resumed would leave the stop on the bare
 *     true range for the rest of the history, plausible and a factor too tight;
 *   - the stop only ever ratchets *towards* price in the live direction, which
 *     is what makes it a stop rather than a band;
 *   - a flip resets the running extreme to the current source and recomputes the
 *     stop from it, so the level jumps once and then resumes ratcheting.
 *
 * The published study draws one cross-style plot whose colour switches with the
 * trend. This library has no per-bar line colour, so the level is split across
 * two null-gated plots exactly as Supertrend and HalfTrend do, and the crosses
 * are stood in for by markers-only dots (as Parabolic SAR does).
 */
export const VOLATILITY_STOP: IndicatorDescriptor = {
  id: 'volatility-stop',
  name: 'Volatility Stop',
  category: 'Trend',
  placement: 'onchart',
  inputs: [
    { key: 'length', type: 'number', label: 'Length', default: 20, min: 2, max: 500, step: 1 },
    { key: 'source', type: 'source', label: 'Source', default: 'close' },
    { key: 'factor', type: 'number', label: 'Multiplier', default: 2, min: 0.25, max: 20, step: 0.25 },
    { key: 'upColor', type: 'color', label: 'Uptrend', default: '#009688' },
    { key: 'downColor', type: 'color', label: 'Downtrend', default: '#f44336' },
  ],
  plots: [
    {
      key: 'up', type: 'line', title: 'Volatility Stop Up', colorKey: 'upColor',
      style: { markersOnly: true, markerRadius: 1.5 },
    },
    {
      key: 'down', type: 'line', title: 'Volatility Stop Down', colorKey: 'downColor',
      style: { markersOnly: true, markerRadius: 1.5 },
    },
  ],
  calc: (bars, s) => {
    const n = bars.length;
    const up: (number | null)[] = new Array(n).fill(null);
    const down: (number | null)[] = new Array(n).fill(null);
    if (n === 0) return { up, down };

    const values = sourceValues(bars, src(s));
    const factor = num(s, 'factor', 2);
    const high = bars.map((b) => b.high);
    const low = bars.map((b) => b.low);
    const close = bars.map((b) => b.close);
    const band = atr(high, low, close, int(s, 'length', 20));
    const tr = trueRange(high, low, close);

    // The running state is seeded on the first bar: both extremes start at the
    // first source value and the stop starts unset. There is a first bar, and
    // every series here holds one value per bar.
    let max: number = values[0]!;
    let min: number = values[0]!;
    let uptrend: boolean = true;
    let stop: number = NaN;

    for (let i = 0; i < n; i++) {
      const v = values[i]!;
      const atrM = Number.isFinite(band[i]) ? band[i]! * factor : tr[i]!;
      max = Math.max(max, v);
      min = Math.min(min, v);
      // `uptrend` still holds the previous bar's answer here, which is what
      // decides whether the stop ratchets up or down this bar. On bar 0 there is
      // no previous stop, so the max/min against it has no value either, and the
      // recursion is seeded at the source itself.
      // Annotated because the recursion is self-referential: `level` decides
      // `nowUp`, which becomes the next bar's `uptrend`, which decides `level`.
      let level: number = uptrend ? Math.max(stop, max - atrM) : Math.min(stop, min + atrM);
      if (!Number.isFinite(level)) level = v;

      const nowUp: boolean = v - level >= 0;
      // Bar 0 is excluded: it has no previous trend to differ from.
      if (i > 0 && nowUp !== uptrend) {
        max = v;
        min = v;
        level = nowUp ? max - atrM : min + atrM;
      }
      uptrend = nowUp;
      stop = level;

      if (!Number.isFinite(level)) continue;
      if (nowUp) up[i] = level;
      else down[i] = level;
    }
    return { up, down };
  },
};

/**
 * Trend Strength Index: the correlation between price and the passage of time.
 *
 * A perfectly straight rising line correlates +1 with the bar index and a
 * straight fall correlates -1, so the reading is "how close to a straight line
 * has this been", not "how fast". Being a correlation it is bounded to -1..1,
 * hence the declared range.
 *
 * Pearson correlation is invariant under shifting either input, so counting the
 * position within the supplied bars, rather than from the start of all history,
 * changes nothing.
 *
 * The published study paints gradient fills between the line and zero, which
 * this library cannot express (a fill needs two plot edges and one flat colour).
 * The two colour inputs it spends on those gradients tint the +1 / -1 bands here
 * instead, so they still mean bullish and bearish.
 */
export const TREND_STRENGTH_INDEX: IndicatorDescriptor = {
  id: 'trend-strength-index',
  name: 'Trend Strength Index',
  category: 'Trend',
  placement: 'pane',
  inputs: [
    { key: 'length', type: 'number', label: 'Length', default: 14, min: 2, max: 500, step: 1 },
    { key: 'color', type: 'color', label: 'Trend Strength Index', default: '#7e57c2' },
    { key: 'bullishColor', type: 'color', label: 'Bullish Color', default: '#089981' },
    { key: 'bearishColor', type: 'color', label: 'Bearish Color', default: '#f23645' },
  ],
  plots: [{
    key: 'tsi', type: 'line', title: 'Trend Strength Index', colorKey: 'color',
    style: { lineWidth: 1.5 },
  }],
  calc: (bars, s) => {
    const index = bars.map((_, i) => i);
    const close = bars.map((b) => b.close);
    return { tsi: nulls(correlation(close, index, int(s, 'length', 14))) };
  },
  levels: (s) => [
    { price: 1, color: str(s, 'bullishColor', '#089981'), title: 'TSI Bullish Band' },
    { price: 0, color: '#787b86', title: 'TSI Middle Band', dashed: true },
    { price: -1, color: str(s, 'bearishColor', '#f23645'), title: 'TSI Bearish Band' },
  ],
  range: () => ({ min: -1, max: 1 }),
};

/**
 * Is `values[at]` a fractal, by the five-variant test the study is defined with?
 *
 * The newer side is strict: all `n` bars after the candidate must be past it.
 * The older side is the interesting half. The definition ORs five flags whose
 * only difference is how many bars immediately before the candidate may merely
 * *equal* it (zero through four) before a run of `n` strictly lower bars is
 * demanded. That tolerance is the point: a flat top of up to five equal highs
 * still reports one fractal, where a naive strict pivot reports none.
 *
 * A bar off either end of the series has no value, and comparisons against it
 * are false, so a missing neighbour fails the variant rather than being skipped.
 * `at` is a bar's index, and each neighbour is read only once `j` is checked
 * to be inside the series.
 */
function isFractal(values: readonly number[], at: number, n: number, wantHigh: boolean): boolean {
  const v = values[at]!;
  if (!Number.isFinite(v)) return false;
  const beyond = (j: number): boolean =>
    j >= 0 && j < values.length && Number.isFinite(values[j]) && (wantHigh ? values[j]! < v : values[j]! > v);
  const level = (j: number): boolean =>
    j >= 0 && j < values.length && Number.isFinite(values[j]) && (wantHigh ? values[j]! <= v : values[j]! >= v);

  for (let k = 1; k <= n; k++) if (!beyond(at + k)) return false;

  for (let plateau = 0; plateau <= 4; plateau++) {
    let ok = true;
    for (let k = 1; k <= plateau && ok; k++) if (!level(at - k)) ok = false;
    for (let k = 1; k <= n && ok; k++) if (!beyond(at - plateau - k)) ok = false;
    if (ok) return true;
  }
  return false;
}

/**
 * Williams Fractals: the pivot highs and lows the alligator is built around.
 *
 * The study is entirely shapes: two of them, and not one line. A descriptor
 * still needs a series for the marker layer to hang off,
 * so `fractals` is declared and returns an all-null column: it draws nothing and
 * contributes nothing to autoscale, it exists to own the markers. The two signal
 * columns beside it carry the price each shape is anchored to, which is what
 * makes the markers testable without re-deriving them.
 *
 * A fractal at bar `p` is only known at bar `p + n`, which is why the study
 * draws it `n` bars back. The columns follow that: the signal sits on the
 * candidate bar, and the last `n` bars can never carry one, being unconfirmed.
 */
export const WILLIAMS_FRACTALS: IndicatorDescriptor = {
  id: 'williams-fractals',
  name: 'Williams Fractals',
  category: 'Trend',
  placement: 'onchart',
  inputs: [
    { key: 'periods', type: 'number', label: 'Periods', default: 2, min: 2, max: 100, step: 1 },
    { key: 'showUp', type: 'boolean', label: 'Show Up Fractals', default: true },
    { key: 'showDown', type: 'boolean', label: 'Show Down Fractals', default: true },
    { key: 'upColor', type: 'color', label: 'Up Fractal', default: '#009688' },
    { key: 'downColor', type: 'color', label: 'Down Fractal', default: '#f44336' },
  ],
  // An all-null column draws nothing and is skipped by autoscale, and the marker
  // layer is created on the first plot's series, so this is the series the
  // triangles live on.
  plots: [{ key: 'fractals', type: 'line', title: 'Fractals', colorKey: 'upColor' }],
  calc: (bars, s) => {
    const n = bars.length;
    const fractals: (number | null)[] = new Array(n).fill(null);
    const upFractal: (number | null)[] = new Array(n).fill(null);
    const downFractal: (number | null)[] = new Array(n).fill(null);
    const out = { fractals, upFractal, downFractal };
    if (n === 0) return out;

    const periods = Math.max(2, int(s, 'periods', 2));
    const high = bars.map((b) => b.high);
    const low = bars.map((b) => b.low);
    const showUp = flag(s, 'showUp', true);
    const showDown = flag(s, 'showDown', true);
    for (let i = 0; i < n; i++) {
      if (showUp && isFractal(high, i, periods, true)) upFractal[i] = high[i]!;
      if (showDown && isFractal(low, i, periods, false)) downFractal[i] = low[i]!;
    }
    return out;
  },
  // The up shape belongs above its bar and the down shape below it. An explicit
  // price is closer to that than the stacked above/below positions are: the
  // shape sits on the extreme that made the fractal.
  markers: ({ bars, values, settings }) => {
    const up = values.upFractal ?? [];
    const down = values.downFractal ?? [];
    const upColor = str(settings, 'upColor', '#009688');
    const downColor = str(settings, 'downColor', '#f44336');
    const out: SeriesMarker[] = [];
    for (let i = 0; i < bars.length; i++) {
      const u = up[i];
      if (u !== null && u !== undefined) {
        out.push({
          time: bars[i]!.time, position: 'atPrice', price: u,
          shape: 'triangleUp', size: 'small', color: upColor,
        });
      }
      const d = down[i];
      if (d !== null && d !== undefined) {
        out.push({
          time: bars[i]!.time, position: 'atPrice', price: d,
          shape: 'triangleDown', size: 'small', color: downColor,
        });
      }
    }
    return out;
  },
};

/**
 * RSI Divergence Indicator: the RSI, plus a labelled plate wherever a fresh RSI
 * pivot disagrees with the price pivot beside it.
 *
 * Four signal classes, each comparing the newest oscillator pivot with the one
 * before it and the price at both:
 *   - regular bullish: oscillator higher low against a lower price low;
 *   - hidden bullish: oscillator lower low against a higher price low;
 *   - regular bearish: oscillator lower high against a higher price high;
 *   - hidden bearish: oscillator higher high against a lower price high.
 *
 * The bookkeeping is all "the previous pivot", said three ways: a pivot low of
 * the oscillator fires on the bar that *confirms* it, `lbR` bars after it
 * happened; the value-when lookup reads a series as it stood at the pivot before
 * this one; and the range gate counts the bars since that previous pivot,
 * rejecting pairs closer together than `rangeLower` or further apart than
 * `rangeUpper`. The gate counts from the found flag delayed one bar, so the
 * pivot being confirmed right now is not counted as its own predecessor.
 *
 * Every comparison is fed a missing value until a second pivot exists, and those
 * comparisons are false, so nothing fires before then without an explicit guard.
 *
 * Not reproduced: the four connector plots, which join consecutive pivot
 * readings and go transparent when the divergence does not hold. They need a
 * line drawn between two isolated points and a per-bar line colour, neither of
 * which this library's line renderer has. The labels carry the same information.
 */
export const RSI_DIVERGENCE: IndicatorDescriptor = {
  id: 'rsi-divergence',
  name: 'RSI Divergence Indicator',
  category: 'Momentum',
  placement: 'pane',
  inputs: [
    { key: 'length', type: 'number', label: 'RSI Period', default: 14, min: 1, max: 500, step: 1 },
    { key: 'source', type: 'source', label: 'RSI Source', default: 'close' },
    { key: 'lbR', type: 'number', label: 'Pivot Lookback Right', default: 5, min: 1, max: 100, step: 1 },
    { key: 'lbL', type: 'number', label: 'Pivot Lookback Left', default: 5, min: 1, max: 100, step: 1 },
    { key: 'rangeUpper', type: 'number', label: 'Max of Lookback Range', default: 60, min: 1, max: 1000, step: 1 },
    { key: 'rangeLower', type: 'number', label: 'Min of Lookback Range', default: 5, min: 1, max: 1000, step: 1 },
    { key: 'plotBull', type: 'boolean', label: 'Plot Bullish', default: true },
    { key: 'plotHiddenBull', type: 'boolean', label: 'Plot Hidden Bullish', default: false },
    { key: 'plotBear', type: 'boolean', label: 'Plot Bearish', default: true },
    { key: 'plotHiddenBear', type: 'boolean', label: 'Plot Hidden Bearish', default: false },
    { key: 'color', type: 'color', label: 'RSI', default: '#2962ff' },
    { key: 'bullColor', type: 'color', label: 'Bullish', default: '#4caf50' },
    { key: 'bearColor', type: 'color', label: 'Bearish', default: '#ff5252' },
  ],
  plots: [{ key: 'rsi', type: 'line', title: 'RSI', colorKey: 'color', style: { lineWidth: 2 } }],
  calc: (bars, s) => {
    const n = bars.length;
    const bull: (number | null)[] = new Array(n).fill(null);
    const hiddenBull: (number | null)[] = new Array(n).fill(null);
    const bear: (number | null)[] = new Array(n).fill(null);
    const hiddenBear: (number | null)[] = new Array(n).fill(null);
    const osc = rsi(sourceValues(bars, src(s)), int(s, 'length', 14));
    const out = { rsi: nulls(osc), bull, hiddenBull, bear, hiddenBear };
    if (n === 0) return out;

    const lbR = int(s, 'lbR', 5);
    const lbL = int(s, 'lbL', 5);
    const lower = int(s, 'rangeLower', 5);
    const upper = int(s, 'rangeUpper', 60);
    // Each class is gated on its own input, so an unwanted one produces no signal
    // at all rather than an invisible one.
    const wantBull = s.plotBull !== false;
    const wantHiddenBull = s.plotHiddenBull === true;
    const wantBear = s.plotBear !== false;
    const wantHiddenBear = s.plotHiddenBear === true;

    const plFound = pivotLow(osc, lbL, lbR).map((v) => Number.isFinite(v));
    const phFound = pivotHigh(osc, lbL, lbR).map((v) => Number.isFinite(v));
    // `osc[lbR]`, `low[lbR]`, `high[lbR]`: the pivot bar's own readings, sampled
    // from the bar that confirms it.
    const oscAt = shift(osc, lbR);
    const lowAt = shift(bars.map((b) => b.low), lbR);
    const highAt = shift(bars.map((b) => b.high), lbR);
    const sincePl = barsSince(shiftFlags(plFound, 1));
    const sincePh = barsSince(shiftFlags(phFound, 1));
    const prevOscLow = valueWhen(plFound, oscAt, 1);
    const prevPriceLow = valueWhen(plFound, lowAt, 1);
    const prevOscHigh = valueWhen(phFound, oscAt, 1);
    const prevPriceHigh = valueWhen(phFound, highAt, 1);

    // Every column read here holds one value per bar.
    for (let i = 0; i < n; i++) {
      // The signal belongs to the pivot bar, `lbR` back from the confirmation.
      const at = i - lbR;
      if (at < 0) continue;
      const oscPivot = oscAt[i]!;

      if (plFound[i]) {
        const inRange = lower <= sincePl[i]! && sincePl[i]! <= upper;
        const oscHigherLow = oscPivot > prevOscLow[i]! && inRange;
        const oscLowerLow = oscPivot < prevOscLow[i]! && inRange;
        if (wantBull && oscHigherLow && lowAt[i]! < prevPriceLow[i]!) bull[at] = oscPivot;
        if (wantHiddenBull && oscLowerLow && lowAt[i]! > prevPriceLow[i]!) hiddenBull[at] = oscPivot;
      }
      if (phFound[i]) {
        const inRange = lower <= sincePh[i]! && sincePh[i]! <= upper;
        const oscLowerHigh = oscPivot < prevOscHigh[i]! && inRange;
        const oscHigherHigh = oscPivot > prevOscHigh[i]! && inRange;
        if (wantBear && oscLowerHigh && highAt[i]! > prevPriceHigh[i]!) bear[at] = oscPivot;
        if (wantHiddenBear && oscHigherHigh && highAt[i]! < prevPriceHigh[i]!) hiddenBear[at] = oscPivot;
      }
    }
    return out;
  },
  // A divergence is a named event at one bar, not a column of prices, so it is a
  // marker. The plate's tail points at the pivot it belongs to: a bullish plate
  // hangs below the RSI low, a bearish one sits above the RSI high. Both hidden
  // classes take the same colour as their regular sibling, as in the source
  // definition, where only the connector lines are dimmed.
  markers: ({ bars, values, settings }) => {
    const bullColor = str(settings, 'bullColor', '#4caf50');
    const bearColor = str(settings, 'bearColor', '#ff5252');
    const classes = [
      { col: values.bull, shape: 'labelUp' as const, text: 'Bull', color: bullColor },
      { col: values.hiddenBull, shape: 'labelUp' as const, text: 'H Bull', color: bullColor },
      { col: values.bear, shape: 'labelDown' as const, text: 'Bear', color: bearColor },
      { col: values.hiddenBear, shape: 'labelDown' as const, text: 'H Bear', color: bearColor },
    ];
    const out: SeriesMarker[] = [];
    for (let i = 0; i < bars.length; i++) {
      for (const c of classes) {
        const v = c.col?.[i];
        if (v === null || v === undefined) continue;
        out.push({
          time: bars[i]!.time, position: 'atPrice', price: v,
          shape: c.shape, size: 'small', color: c.color, text: c.text,
        });
      }
    }
    return out;
  },
  levels: () => [
    { price: 70, color: '#787b86', title: 'Overbought', dashed: true },
    { price: 50, color: '#787b86', title: 'Middle Line', dashed: true },
    { price: 30, color: '#787b86', title: 'Oversold', dashed: true },
  ],
  range: () => ({ min: 0, max: 100 }),
};

/**
 * How stale a range may be before a body leaving it stops counting as a
 * breakout, and how fresh. A body that escapes the bar right after the mother is
 * that mother's own follow-through rather than a break of a consolidation, and a
 * range still standing 250 bars later has stopped being one. Both are constants
 * of the standard formula, not inputs: neither has a reading a user would tune.
 */
const MIN_BARS = 1;
const MAX_BARS = 250;

/**
 * Consolidation and Breakout: a mother bar's range, the inside bars that keep it
 * alive, and the bar that finally leaves it.
 *
 * This one is a state machine rather than a formula. A single index is carried
 * from bar to bar: the bar whose high and low currently define the range. Every
 * later bar whose *body* (open to close, wicks ignored) sits inside that range
 * extends the consolidation, and the first body to escape it becomes the new
 * mother.
 *
 * The two reads of that index straddle the reassignment, and that ordering is
 * the study:
 *   - the breakout tests read the range as it stood *before* this bar could
 *     claim it, which is what makes a breakout a statement about the old range;
 *   - the plotted range and the inside-bar tint read it *after*, so a bar that
 *     breaks out is already the new mother and is correctly left untinted.
 * One bar therefore both fires a marker and opens the next consolidation.
 * Collapsing the two into one read shifts every signal by a bar, which still
 * looks plausible on a chart, so `tests/study-consolidation.test.ts` pins the
 * breaking bar itself.
 *
 * Bar 1 is excluded from the inside test by the definition: with the carried
 * index seeded at 0, bar 1 would otherwise be measured against a range that has
 * had no chance to be broken.
 *
 * Not reproduced: the thickness control the published definition puts on the two
 * range lines. `style.lineWidth` is static here and no settings key stands
 * behind it, so the control would move nothing. The lines are fixed at 2.
 */
export const CONSOLIDATION_BREAKOUT: IndicatorDescriptor = {
  id: 'consolidation-breakout',
  name: 'Consolidation and Breakout',
  category: 'Trend',
  placement: 'onchart',
  inputs: [
    { key: 'markbreakout', type: 'boolean', label: 'Mark Breakouts', default: true },
    { key: 'colorinside', type: 'boolean', label: 'Tint Inside Bars', default: true },
    { key: 'bullBreakColor', type: 'color', label: 'Break Up', default: '#00c853' },
    { key: 'bearBreakColor', type: 'color', label: 'Break Down', default: '#ff5252' },
    { key: 'insideColor', type: 'color', label: 'Inside Bar', default: '#000000' },
    { key: 'highlowColor', type: 'color', label: 'Range', default: '#e91e63' },
  ],
  // Null wherever no consolidation is running, so the renderer breaks the line
  // across the gap instead of joining one range to the next. That gap is the
  // reading: two disconnected rails are two separate consolidations.
  plots: [
    {
      key: 'rangeHigh', type: 'line', title: 'Range High',
      colorKey: 'highlowColor', style: { lineWidth: 2 },
    },
    {
      key: 'rangeLow', type: 'line', title: 'Range Low',
      colorKey: 'highlowColor', style: { lineWidth: 2 },
    },
  ],
  calc: (bars) => {
    const n = bars.length;
    const rangeHigh = new Array<number>(n).fill(NaN);
    const rangeLow = new Array<number>(n).fill(NaN);
    // The three signal columns the two presentation hooks read: which bars broke
    // out and where, and how long each bar has been inside. Holding them here
    // rather than recomputing keeps the state machine walked once.
    const breakUp = new Array<number>(n).fill(NaN);
    const breakDown = new Array<number>(n).fill(NaN);
    const insideAge = new Array<number>(n).fill(NaN);

    // `mainIndex` is always a bar at or before `i`.
    let mainIndex = 0;
    for (let i = 0; i < n; i++) {
      const b = bars[i]!;
      const bodyTop = Math.max(b.open, b.close);
      const bodyBottom = Math.min(b.open, b.close);
      const motherHigh = bars[mainIndex]!.high;
      const motherLow = bars[mainIndex]!.low;
      const age = i - mainIndex;

      // Read one: the range the bar is breaking is the one it has not claimed.
      const breakable = age > MIN_BARS && age <= MAX_BARS;
      if (breakable && bodyTop > motherHigh) breakUp[i] = motherHigh;
      if (breakable && bodyBottom < motherLow) breakDown[i] = motherLow;

      const inside = i > 1
        && bodyBottom >= motherLow && bodyBottom <= motherHigh
        && bodyTop >= motherLow && bodyTop <= motherHigh;
      const previous = mainIndex;
      mainIndex = inside ? mainIndex : i;

      // Read two, after the reassignment. A bar that took the range over prints
      // nothing, so the rails stop at the last bar the old range held. Bar 0 is
      // the one place where the carried seed and the reassignment agree, so it
      // prints its own high and low and starts the first range.
      if (mainIndex === previous) {
        rangeHigh[i] = bars[mainIndex]!.high;
        rangeLow[i] = bars[mainIndex]!.low;
      }
      const held = i - mainIndex;
      if (held > 0) insideAge[i] = held;
    }
    return {
      rangeHigh: nulls(rangeHigh), rangeLow: nulls(rangeLow),
      breakUp: nulls(breakUp), breakDown: nulls(breakDown), insideAge: nulls(insideAge),
    };
  },
  // Both toggles are applied here rather than in `calc`, so the columns stay the
  // state machine's own answer and switching a toggle restyles what is already
  // computed. The shape points the way the body went and sits on the far side of
  // the bar from it, which keeps it clear of the range rails.
  markers: ({ bars, values, settings }) => {
    const out: SeriesMarker[] = [];
    if (!flag(settings, 'markbreakout', true)) return out;
    const up = values.breakUp ?? [];
    const down = values.breakDown ?? [];
    const upColor = str(settings, 'bullBreakColor', '#00c853');
    const downColor = str(settings, 'bearBreakColor', '#ff5252');
    for (let i = 0; i < bars.length; i++) {
      if (up[i] !== null && up[i] !== undefined) {
        out.push({
          time: bars[i]!.time, position: 'belowBar',
          shape: 'triangleUp', size: 'small', color: upColor,
        });
      }
      if (down[i] !== null && down[i] !== undefined) {
        out.push({
          time: bars[i]!.time, position: 'aboveBar',
          shape: 'triangleDown', size: 'small', color: downColor,
        });
      }
    }
    return out;
  },
  // A consolidation is a property of the price bars, not a second series beside
  // them, so the inside bars are tinted on the candles themselves. The mother
  // bar keeps its own colour: it is the range, not part of what is inside it.
  barColors: ({ bars, values, settings }) => {
    const age = values.insideAge ?? [];
    const tint = str(settings, 'insideColor', '#000000');
    const wanted = flag(settings, 'colorinside', true);
    return bars.map((_, i) =>
      (wanted && age[i] !== null && age[i] !== undefined ? tint : null));
  },
};

export const SIGNAL_INDICATORS: readonly IndicatorDescriptor[] = [
  VORTEX,
  VOLATILITY_STOP,
  TREND_STRENGTH_INDEX,
  WILLIAMS_FRACTALS,
  RSI_DIVERGENCE,
  CONSOLIDATION_BREAKOUT,
];
