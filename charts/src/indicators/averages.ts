/**
 * Built-in averages: the ten price-pane studies whose behaviour
 * is specified against the published reference definitions rather than this library's own.
 * Part of the lazy `openalgo-charts/indicators` tier.
 *
 * Parity note, and the reason `ema` is absent from the imports: the reference `ema`
 * seeds from the SMA of the first `length` values and is `na` before that, while
 * the base bundle's `ema` seeds from `values[0]` and emits from bar 0 to match
 * `openalgo.ta`. The two disagree across the whole warmup, so anything that has
 * to land on the same pixels as a reference platform plot uses `smaSeededEma` from `./calc`.
 *
 * `atr`, `sessionStartFlags`, and the `sourceValues` helper come from the base
 * bundle (`openalgo-charts`), not deep paths: see the note in
 * `src/indicators/index.ts`.
 */
import { atr, sourceValues, sessionStartFlags } from 'openalgo-charts';
import type { IndicatorDescriptor, IndicatorInput } from 'openalgo-charts';
import { sma, rma, nulls, smaSeededEma, vwma, percentileNearestRank } from './calc';
import { emaOfGapped, smoothingMa } from './smoothing';
import { withTimeframe } from './timeframe';
import { num, int, offsetOf, str, flag, src, zoneOf } from './settings';
import { crosses } from './statistics';
import { shift, volumeOf, zip } from './series';

/**
 * `close` is hard-coded in the reference (`sma(close, ...)`, not an
 * `input`), so there is no source setting to expose.
 *
 * The long length defaults to 26, not 21: the reference pairs 9 against 26. A
 * saved chart that never set the length explicitly draws a slower line now.
 */
export const MA_CROSS: IndicatorDescriptor = {
  id: 'ma-cross',
  name: 'MA Cross',
  category: 'Trend',
  placement: 'onchart',
  inputs: [
    { key: 'shortLength', type: 'number', label: 'Short MA Length', default: 9, min: 1, max: 1000, step: 1 },
    { key: 'longLength', type: 'number', label: 'Long MA Length', default: 26, min: 1, max: 1000, step: 1 },
    { key: 'shortColor', type: 'color', label: 'Short MA', default: '#ff6d00' },
    { key: 'longColor', type: 'color', label: 'Long MA', default: '#43a047' },
    { key: 'crossColor', type: 'color', label: 'Cross', default: '#2962ff' },
  ],
  plots: [
    { key: 'short', type: 'line', title: 'Short MA', colorKey: 'shortColor', style: { color: '#ff6d00', lineWidth: 1.5 } },
    { key: 'long', type: 'line', title: 'Long MA', colorKey: 'longColor', style: { color: '#43a047', lineWidth: 1.5 } },
    // the reference draws this one with `plot.style_cross`: a value only on the bars
    // where the averages actually crossed, `na` everywhere else. A line with
    // `markersOnly` is the same picture here: the gaps carry no segment.
    {
      key: 'cross', type: 'line', title: 'Cross', colorKey: 'crossColor',
      style: { markersOnly: true, markerRadius: 3 },
    },
  ],
  calc: (bars, s) => {
    const closes = sourceValues(bars, 'close');
    const short = sma(closes, int(s, 'shortLength', 9));
    const long = sma(closes, int(s, 'longLength', 26));
    // the reference `cross(a, b)`: both averages real on this bar and the one before,
    // so nothing fires while either is warming up.
    const hit = crosses(short, long);
    return {
      short: nulls(short),
      long: nulls(long),
      cross: short.map((v, i) => (hit[i] ? v : null)),
    };
  },
};

/**
 * McGinley Dynamic: an average whose smoothing constant is itself a function of
 * how far price has run from the line, so it tightens in a trend and loosens in
 * a range instead of lagging by a fixed number of bars.
 *
 * Recursive, and the reference seeds it from `ema(source, length)` for as long as its
 * own previous value is `na`: the first printed bar is therefore `length - 1`,
 * where the EMA first prints, and the recursion takes over from the bar after.
 * `close` is hard-coded in the reference (`source = close`), so there is no
 * source setting.
 */
export const MCGINLEY_DYNAMIC: IndicatorDescriptor = withTimeframe({
  id: 'mcginley-dynamic',
  name: 'McGinley Dynamic',
  category: 'Trend',
  placement: 'onchart',
  inputs: [
    { key: 'length', type: 'number', label: 'Length', default: 14, min: 1, max: 1000, step: 1 },
    { key: 'color', type: 'color', label: 'McGinley Dynamic', default: '#2962ff' },
  ],
  plots: [{
    key: 'mg', type: 'line', title: 'McGinley Dynamic', colorKey: 'color',
    style: { color: '#2962ff', lineWidth: 1.5 },
  }],
  calc: (bars, s) => {
    const values = sourceValues(bars, 'close');
    const length = int(s, 'length', 14);
    const seed = smaSeededEma(values, length);
    const out = new Array<number>(values.length).fill(NaN);
    let prev = NaN;
    // `seed` and `out` hold one value per bar.
    for (let i = 0; i < values.length; i++) {
      if (!Number.isFinite(prev) || prev === 0) {
        // the reference `na(mg[1]) ? ema(...)` branch, which also covers the
        // degenerate zero: the ratio `source / mg[1]` has no value there, so the
        // line re-seeds from the EMA rather than propagating a non-finite state.
        out[i] = seed[i]!;
      } else {
        const step = length * Math.pow(values[i]! / prev, 4);
        const next = prev + (values[i]! - prev) / step;
        out[i] = Number.isFinite(next) ? next : seed[i]!;
      }
      prev = out[i]!;
    }
    return { mg: nulls(out) };
  },
});

/**
 * Median: the nearest-rank 50th percentile of the source, banded by ATR and
 * shaded against its own EMA. The percentile is a real member of the window
 * rather than an interpolation (see `percentileNearestRank`), so on an
 * even-length window it is the upper of the two middles, not their mean.
 *
 * The EMA is chained onto the percentile series, so it inherits that series'
 * warmup and first prints at `2 * length - 2`: see `emaOfGapped`.
 */
export const MEDIAN: IndicatorDescriptor = {
  id: 'median',
  name: 'Median',
  category: 'Trend',
  placement: 'onchart',
  inputs: [
    { key: 'source', type: 'source', label: 'Median Source', default: 'hl2' },
    { key: 'length', type: 'number', label: 'Median Length', default: 3, min: 1, max: 1000, step: 1 },
    { key: 'atrLength', type: 'number', label: 'ATR Length', default: 14, min: 1, max: 1000, step: 1 },
    { key: 'atrMult', type: 'number', label: 'ATR Multiplier', default: 2, min: 0, max: 50, step: 0.1 },
    { key: 'medianColor', type: 'color', label: 'Median', default: '#ff5252' },
    { key: 'upperColor', type: 'color', label: 'Upper Band', default: '#00e676' },
    { key: 'lowerColor', type: 'color', label: 'Lower Band', default: '#e040fb' },
    { key: 'emaColor', type: 'color', label: 'Median EMA', default: '#2196f3' },
  ],
  plots: [
    { key: 'median', type: 'line', title: 'Median', colorKey: 'medianColor', style: { color: '#ff5252', lineWidth: 3 } },
    { key: 'upper', type: 'line', title: 'Upper Band', colorKey: 'upperColor', style: { color: '#00e676', lineWidth: 1 } },
    { key: 'lower', type: 'line', title: 'Lower Band', colorKey: 'lowerColor', style: { color: '#e040fb', lineWidth: 1 } },
    { key: 'medianEma', type: 'line', title: 'Median EMA', colorKey: 'emaColor', style: { color: '#2196f3', lineWidth: 1 } },
  ],
  // the reference colours this band lime when `median > median_ema` and fuchsia
  // otherwise, at 10 % transparency. The fill spec's up/down split is the same
  // predicate: `median` is the first plot of the pair.
  fills: [{
    between: ['median', 'medianEma'],
    colorUpKey: 'upperColor',
    colorDownKey: 'lowerColor',
    opacity: 0.9,
  }],
  calc: (bars, s) => {
    const values = sourceValues(bars, src(s, 'source', 'hl2'));
    const length = int(s, 'length', 3);
    const mult = num(s, 'atrMult', 2);
    const median = percentileNearestRank(values, length, 50);
    const range = atr(
      bars.map((b) => b.high),
      bars.map((b) => b.low),
      bars.map((b) => b.close),
      int(s, 'atrLength', 14),
    );
    return {
      median: nulls(median),
      // Both series hold one value per bar, as every calc helper returns.
      upper: nulls(zip(median, range, (v, r) => v + mult * r)),
      lower: nulls(zip(median, range, (v, r) => v - mult * r)),
      medianEma: nulls(emaOfGapped(median, length)),
    };
  },
};

/** The five kernels the reference `ma()` switch offers the ribbon. */
const MA_TYPE_OPTIONS: readonly { label: string; value: string }[] = [
  { label: 'SMA', value: 'SMA' },
  { label: 'EMA', value: 'EMA' },
  { label: 'SMMA (RMA)', value: 'SMMA (RMA)' },
  { label: 'WMA', value: 'WMA' },
  { label: 'VWMA', value: 'VWMA' },
];

/**
 * The ribbon's four lanes are configured identically, so the inputs are
 * generated rather than written out four times. `group` puts each lane's five
 * settings on one row of a settings UI, which is what the reference `inline` does.
 */
function ribbonInputs(lane: number, length: number, color: string): IndicatorInput[] {
  const group = `MA #${lane}`;
  return [
    { key: `showMa${lane}`, type: 'boolean', label: group, default: true, group },
    { key: `ma${lane}Type`, type: 'select', label: 'Type', default: 'SMA', options: MA_TYPE_OPTIONS, group },
    { key: `ma${lane}Source`, type: 'source', label: 'Source', default: 'close', group },
    { key: `ma${lane}Length`, type: 'number', label: 'Length', default: length, min: 1, max: 1000, step: 1, group },
    { key: `ma${lane}Color`, type: 'color', label: 'Color', default: color, group },
  ];
}

const RIBBON_LANES: readonly { lane: number; length: number; color: string }[] = [
  { lane: 1, length: 20, color: '#f6c309' },
  { lane: 2, length: 50, color: '#fb9800' },
  { lane: 3, length: 100, color: '#fb6500' },
  { lane: 4, length: 200, color: '#f60c0c' },
];

/**
 * Moving Average Ribbon: four independent averages on one overlay, so the
 * spacing between them reads as trend strength and their order as trend
 * direction. Every lane picks its own kernel, source, and length.
 *
 * the reference hides a lane by setting `display.none` on the plot; here a hidden lane
 * returns an all-null column, which draws nothing and keeps autoscale clean.
 */
export const MA_RIBBON: IndicatorDescriptor = {
  id: 'ma-ribbon',
  name: 'Moving Average Ribbon',
  category: 'Trend',
  placement: 'onchart',
  inputs: RIBBON_LANES.flatMap((l) => ribbonInputs(l.lane, l.length, l.color)),
  plots: RIBBON_LANES.map((l) => ({
    key: `ma${l.lane}`,
    type: 'line' as const,
    title: `MA #${l.lane}`,
    colorKey: `ma${l.lane}Color`,
    style: { color: l.color, lineWidth: 1.5 },
  })),
  calc: (bars, s) => {
    const vols = bars.map(volumeOf);
    const out: Record<string, (number | null)[]> = {};
    for (const { lane, length } of RIBBON_LANES) {
      if (!flag(s, `showMa${lane}`, true)) {
        out[`ma${lane}`] = new Array<number | null>(bars.length).fill(null);
        continue;
      }
      const values = sourceValues(bars, src(s, `ma${lane}Source`));
      out[`ma${lane}`] = nulls(smoothingMa(
        str(s, `ma${lane}Type`, 'SMA'),
        values,
        vols,
        int(s, `ma${lane}Length`, length),
      ));
    }
    return out;
  },
};

/**
 * Triple EMA: `3 * ema1 - 3 * ema2 + ema3`, which cancels the lag of a linear
 * trend exactly rather than merely reducing it.
 *
 * Three chained EMAs, each running over a series that is already `na` for its
 * own warmup, so the first printed bar is `3 * length - 3` and not `length - 1`
 * (see `emaOfGapped`). `close` is hard-coded in the reference, so there is no
 * source setting.
 *
 * The three terms are added left to right, as the definition writes them, not
 * regrouped as `3 * (ema1 - ema2) + ema3`: the two round differently in the last
 * digits, and the grouped form can hide an overflowing term. Any absent term, or
 * a sum that is not finite, leaves the bar absent (`nulls`).
 */
export const TEMA: IndicatorDescriptor = withTimeframe({
  id: 'tema',
  name: 'Triple EMA',
  category: 'Trend',
  placement: 'onchart',
  inputs: [
    { key: 'length', type: 'number', label: 'Length', default: 9, min: 1, max: 1000, step: 1 },
    { key: 'color', type: 'color', label: 'TEMA', default: '#2962ff' },
  ],
  plots: [{
    key: 'tema', type: 'line', title: 'TEMA', colorKey: 'color',
    style: { color: '#2962ff', lineWidth: 1.5 },
  }],
  calc: (bars, s) => {
    const values = sourceValues(bars, 'close');
    const length = int(s, 'length', 9);
    const e1 = smaSeededEma(values, length);
    const e2 = emaOfGapped(e1, length);
    const e3 = emaOfGapped(e2, length);
    return { tema: nulls(e1.map((v, i) => 3 * v - 3 * e2[i]! + e3[i]!)) };
  },
});

/**
 * Time Weighted Average Price: the running mean of the source since the anchor,
 * the volume-blind sibling of VWAP. Where VWAP asks what the average traded
 * price was, TWAP asks what the average quoted price was, so a thin bar counts
 * for exactly as much as a heavy one.
 *
 * Anchor substitution: the reference takes an `input.timeframe` (default `1D`) and resets
 * on `timeframe.change(anchor)`, which needs a resolution resolver a chart
 * library does not have. The `session` option resets on the exchange's own
 * trading day, read back from the bar gaps exactly as the VWAP descriptor
 * anchors, and `continuous` never resets. The option used to be labelled
 * "Session (IST day)"; it names no zone now because it hardcodes none.
 */
export const TWAP: IndicatorDescriptor = {
  id: 'twap',
  name: 'Time Weighted Average Price',
  category: 'Trend',
  placement: 'onchart',
  inputs: [
    {
      key: 'anchor', type: 'select', label: 'Anchor Period', default: 'session',
      options: [{ label: 'Session', value: 'session' }, { label: 'Continuous', value: 'continuous' }],
    },
    { key: 'source', type: 'source', label: 'Source', default: 'ohlc4' },
    { key: 'offset', type: 'number', label: 'Offset', default: 0, min: -500, max: 500, step: 1 },
    { key: 'color', type: 'color', label: 'TWAP', default: '#dd7a28' },
  ],
  plots: [{
    key: 'twap', type: 'line', title: 'TWAP', colorKey: 'color',
    style: { color: '#dd7a28', lineWidth: 1.5 },
  }],
  calc: (bars, s) => {
    const values = sourceValues(bars, src(s, 'source', 'ohlc4'));
    const perSession = s.anchor !== 'continuous';
    // Read from the bar gaps rather than a fixed midnight, so the average
    // restarts when the exchange opens and not partway through its afternoon.
    // The zone is only consulted for the fallback the gaps cannot answer: on
    // daily bars, or a market that never closes, a session is a calendar day,
    // and whose calendar that is now follows the chart.
    const restarts = perSession ? sessionStartFlags(bars.map((b) => b.time), zoneOf(s)) : null;
    const out = new Array<number>(bars.length).fill(NaN);
    let sum = 0;
    let count = 0;
    for (let i = 0; i < bars.length; i++) {
      if (restarts !== null && restarts[i]) { sum = 0; count = 0; }
      // A bar with no price is a gap: it neither joins the sum nor counts as a
      // bar, so it costs only its own reading instead of the rest of the session.
      const value = values[i]!;
      if (!Number.isFinite(value)) continue;
      sum += value;
      count += 1;
      out[i] = sum / count;
    }
    return { twap: nulls(shift(out, offsetOf(s, 'offset', 0))) };
  },
};

/**
 * Volume Weighted Moving Average: an SMA whose window is weighted by volume,
 * so the bars that actually traded set the level. Identical to an SMA when
 * volume is flat, and `na` on any window whose volume sums to zero, which is
 * what a feed with no volume produces.
 */
export const VWMA: IndicatorDescriptor = withTimeframe({
  id: 'vwma',
  name: 'Volume Weighted Moving Average',
  category: 'Volume',
  placement: 'onchart',
  inputs: [
    { key: 'length', type: 'number', label: 'Length', default: 20, min: 1, max: 1000, step: 1 },
    { key: 'source', type: 'source', label: 'Source', default: 'close' },
    { key: 'offset', type: 'number', label: 'Offset', default: 0, min: -500, max: 500, step: 1 },
    { key: 'color', type: 'color', label: 'VWMA', default: '#2962ff' },
  ],
  plots: [{
    key: 'vwma', type: 'line', title: 'VWMA', colorKey: 'color',
    style: { color: '#2962ff', lineWidth: 1.5 },
  }],
  calc: (bars, s) => {
    const ma = vwma(sourceValues(bars, src(s)), bars.map(volumeOf), int(s, 'length', 20));
    return { vwma: nulls(shift(ma, offsetOf(s, 'offset', 0))) };
  },
});

/**
 * Williams Alligator: three Wilder-smoothed medians of differing speed, each
 * displaced forward in time. The lines braid when the market has nothing to say
 * and fan out in order once a trend takes hold.
 *
 * the reference `smma` is `na(smma[1]) ? sma(src, length) : (smma[1] * (length - 1)
 * + src) / length`, which is Wilder's RMA to the letter, so `rma` reproduces it
 * exactly and first prints at `length - 1`.
 *
 * Lengths default to 21 / 13 / 8, not to Williams' original 13 / 8 / 5: the
 * reference runs the slower set, and the offsets 8 / 5 / 3 are shared by both,
 * so only the smoothing lengths move. A saved chart that never set them draws
 * three slower lines now.
 *
 * The three plots carry `offset = 8 / 5 / 3`. A plot offset is not available
 * per-plot here, so the displacement is applied to the values instead: the value
 * computed on bar `i` is returned in slot `i + offset`, which leaves `offset`
 * leading nulls and puts the shifted tail in the last `offset` slots. A line
 * therefore first prints at `length - 1 + offset`.
 */
export const ALLIGATOR: IndicatorDescriptor = {
  id: 'alligator',
  name: 'Williams Alligator',
  category: 'Trend',
  placement: 'onchart',
  inputs: [
    { key: 'jawLength', type: 'number', label: 'Jaw Length', default: 21, min: 1, max: 1000, step: 1 },
    { key: 'teethLength', type: 'number', label: 'Teeth Length', default: 13, min: 1, max: 1000, step: 1 },
    { key: 'lipsLength', type: 'number', label: 'Lips Length', default: 8, min: 1, max: 1000, step: 1 },
    { key: 'jawOffset', type: 'number', label: 'Jaw Offset', default: 8, min: -500, max: 500, step: 1 },
    { key: 'teethOffset', type: 'number', label: 'Teeth Offset', default: 5, min: -500, max: 500, step: 1 },
    { key: 'lipsOffset', type: 'number', label: 'Lips Offset', default: 3, min: -500, max: 500, step: 1 },
    { key: 'jawColor', type: 'color', label: 'Jaw', default: '#2962ff' },
    { key: 'teethColor', type: 'color', label: 'Teeth', default: '#e91e63' },
    { key: 'lipsColor', type: 'color', label: 'Lips', default: '#66bb6a' },
  ],
  plots: [
    { key: 'jaw', type: 'line', title: 'Jaw', colorKey: 'jawColor', style: { color: '#2962ff', lineWidth: 1.5 } },
    { key: 'teeth', type: 'line', title: 'Teeth', colorKey: 'teethColor', style: { color: '#e91e63', lineWidth: 1.5 } },
    { key: 'lips', type: 'line', title: 'Lips', colorKey: 'lipsColor', style: { color: '#66bb6a', lineWidth: 1.5 } },
  ],
  calc: (bars, s) => {
    // `hl2` is hard-coded in the reference, so there is no source setting.
    const values = sourceValues(bars, 'hl2');
    return {
      jaw: nulls(shift(rma(values, int(s, 'jawLength', 21)), offsetOf(s, 'jawOffset', 8))),
      teeth: nulls(shift(rma(values, int(s, 'teethLength', 13)), offsetOf(s, 'teethOffset', 5))),
      lips: nulls(shift(rma(values, int(s, 'lipsLength', 8)), offsetOf(s, 'lipsOffset', 3))),
    };
  },
};

/**
 * Smoothed Moving Average, Wilder's smoother over a plain price source. Its
 * alpha is `1 / length` where an EMA of the same length uses `2 / (length + 1)`,
 * so it lags further and turns only once a run of closes has genuinely shifted
 * the level, which is the point: it is the noise filter, not the fast line.
 *
 * The reference `smma` is the recursion `rma` already implements, seeded from
 * the simple average of the first `length` values, so it first prints at
 * `length - 1` and needs no code of its own here.
 */
export const SMMA: IndicatorDescriptor = withTimeframe({
  id: 'smma',
  name: 'Smoothed Moving Average',
  category: 'Trend',
  placement: 'onchart',
  inputs: [
    { key: 'length', type: 'number', label: 'Length', default: 7, min: 1, max: 1000, step: 1 },
    { key: 'source', type: 'source', label: 'Source', default: 'close' },
    { key: 'color', type: 'color', label: 'SMMA', default: '#673ab7' },
  ],
  plots: [{
    key: 'smma', type: 'line', title: 'SMMA', colorKey: 'color',
    style: { color: '#673ab7', lineWidth: 1.5 },
  }],
  calc: (bars, s) => ({ smma: nulls(rma(sourceValues(bars, src(s)), int(s, 'length', 7))) }),
});

/**
 * One T3 layer: an exponential average pushed past itself by `factor` times the
 * error its own second smoothing still carries. On a straight ramp that trades
 * exactly `factor` of the layer's lag away, which is the whole trick, and at
 * `factor = 1` it is a plain DEMA.
 *
 * The second average is dropped rather than multiplied by zero when the factor
 * is zero. It contributes nothing but its warmup there, and `NaN * 0` is `NaN`,
 * so keeping it would blank `length - 1` bars of a line that has by then
 * collapsed to the plain chained average the definition says it is.
 */
function generalizedDouble(values: readonly number[], length: number, factor: number): number[] {
  const e1 = emaOfGapped(values, length);
  if (factor === 0) return e1;
  const e2 = emaOfGapped(e1, length);
  return zip(e1, e2, (v, e) => v * (1 + factor) - e * factor);
}

/**
 * T3 Average, that generalised double average applied three times over. The
 * result reads as smooth as a long moving average while turning close to as
 * early as a short one, which no single exponential average of either length
 * does.
 *
 * Warmup is the thing to get right here, and it is deeper than the length
 * suggests. One layer is two chained averages, and the layers nest three deep,
 * so the longest term is six averages of averages. Each is chained onto a series
 * that is already `na` for its own warmup and so starts `length - 1` bars after
 * the one it reads (see `emaOfGapped`), which puts the first printed bar at
 * `6 * (length - 1)`: index 24 at the default length of 5, not index 4.
 *
 * Highlighting is a colour on one line, not a second plot: the line is
 * continuous either way and only its paint changes, so a break in the colour
 * must not become a break in the series.
 */
export const T3: IndicatorDescriptor = withTimeframe({
  id: 't3',
  name: 'T3 Average',
  category: 'Trend',
  placement: 'onchart',
  inputs: [
    { key: 'length', type: 'number', label: 'Length', default: 5, min: 1, max: 1000, step: 1 },
    { key: 'factor', type: 'number', label: 'Factor', default: 0.7, min: 0, max: 1, step: 0.1 },
    { key: 'highlightMovements', type: 'boolean', label: 'Highlight Movements', default: true },
    { key: 'source', type: 'source', label: 'Source', default: 'close' },
    { key: 'upColor', type: 'color', label: 'Rising', default: '#26a69a' },
    { key: 'downColor', type: 'color', label: 'Falling', default: '#ff5252' },
    { key: 'neutralColor', type: 'color', label: 'T3', default: '#6d1e7f' },
  ],
  plots: [{
    key: 't3',
    type: 'line',
    title: 'T3',
    // `colorKey` is the plain colour a settings UI restyles and the one the line
    // wears with highlighting off; `colorBy` wins bar by bar when it is on.
    colorKey: 'neutralColor',
    style: { color: '#6d1e7f', lineWidth: 2 },
    colorBy: ({ value, index, values, settings }) => {
      if (!flag(settings, 'highlightMovements', true)) return str(settings, 'neutralColor', '#6d1e7f');
      const prev = values.t3?.[index - 1];
      // Only a genuine rise takes the up colour: an unchanged value and the
      // first printed bar, which has nothing behind it, both read as falling,
      // the way a comparison against `na` does.
      const rising = typeof prev === 'number' && Number.isFinite(prev) && value > prev;
      return rising ? str(settings, 'upColor', '#26a69a') : str(settings, 'downColor', '#ff5252');
    },
  }],
  calc: (bars, s) => {
    const values = sourceValues(bars, src(s));
    const length = int(s, 'length', 5);
    const factor = num(s, 'factor', 0.7);
    const once = generalizedDouble(values, length, factor);
    const twice = generalizedDouble(once, length, factor);
    return { t3: nulls(generalizedDouble(twice, length, factor)) };
  },
});

export const AVERAGE_INDICATORS: readonly IndicatorDescriptor[] = [
  MA_CROSS, MCGINLEY_DYNAMIC, MEDIAN, MA_RIBBON, TEMA, TWAP, VWMA, ALLIGATOR, SMMA, T3,
];
