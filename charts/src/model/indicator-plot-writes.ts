/**
 * How a running study writes its plots (ARCHITECTURE.md §8): each plot series
 * gets only the points that moved since the last pass, in place.
 *
 * A study recomputes on every frame that carries a tick, and used to hand each
 * plot its whole history through `setData`: a new point per bar, a new bar per
 * point, a sort, and a re-merge of the chart's time index, per plot per tick.
 * A plot's times are the source's own, though, and a tick moves the value of
 * the forming bar and perhaps opens one more. So each plot keeps a record of
 * what its series holds, and a pass whose bars begin with the times the last
 * pass wrote sends the few points that differ through `update`. Anything else
 * (new history, a gap filled, a plot the pass before did not write, more than
 * `IN_PLACE` moved points, which new settings usually are) is a whole write
 * through `setData`, as before.
 *
 * The record is never output. Every pass computes every point afresh, colours
 * included, and compares it with the record, so the forming bar is written
 * whenever it moved and nothing a reader sees comes from the record (CLAUDE.md,
 * never cache the forming bar). A pass that stops part way leaves its records
 * stamped with the pass before, and the next pass writes those plots whole.
 * The record describes the series only while the study is its one writer,
 * which is why `IndicatorApi.series` hands a plot out for styling alone.
 */
import type { Bar, SeriesDataItem } from './bar';
import type { SeriesApi } from './series';
import { plotStyleKeys, type IndicatorPlot, type IndicatorSettings, type IndicatorValues } from './indicator-registry';
import { parseColor } from '../render/pill';

/**
 * Most points one plot writes in place in a pass. Each is a data-layer update
 * with an invalidation of its own, and a pass that moved more than a few
 * points (a study that revises its past) is closer to a new plot than a tick.
 */
const IN_PLACE = 8;

type List = unknown[];

interface PlotRecord {
  /** The pass that last wrote the series whole or in place. */
  pass: number;
  /** Values as written: `[value]`, or `[open, high, low, close]` for a candle plot. */
  readonly cols: unknown[][];
  /** Colours as written: `[body]`, or `[body, wick, border]` for a candle plot. */
  readonly colors: unknown[][];
}

type Settings = Readonly<IndicatorSettings>;

/**
 * The same written value: equal, with zero's sign kept and NaN equal to
 * itself. `Object.is` answers the same and measured at twice the cost in the
 * loop that runs over every bar of every plot on every tick.
 */
function same(a: unknown, b: unknown): boolean {
  return a === b ? a !== 0 || 1 / (a as number) === 1 / (b as number) : a !== a && b !== b;
}

/**
 * The plot's generated Opacity setting, 100 when unset. The series colour folds
 * it in (IndicatorInstance._plotStyle); a plot that colours bar by bar paints
 * over the series colour, so its per-bar colours are faded here too.
 */
function opacityOf(plot: IndicatorPlot, settings: Settings): number {
  const v = settings[plotStyleKeys(plot).opacity];
  return typeof v === 'number' && Number.isFinite(v) ? v : 100;
}

/**
 * A per-bar colour at `opacity` percent of its own alpha. Multiplied rather than
 * replaced: a study that says something with the alpha of a bar (a weakening
 * histogram drawn lighter) keeps saying it when the whole plot is faded. What
 * does not parse as a colour passes through.
 */
function faded(color: unknown, opacity: number): unknown {
  if (typeof color !== 'string' || opacity >= 100) return color;
  const c = parseColor(color);
  return c === null ? color : `rgba(${c.r},${c.g},${c.b},${c.a * Math.max(0, opacity) / 100})`;
}

export class PlotWrites {
  /** Times of the bars the last pass wrote. */
  private readonly _times: number[] = [];
  /**
   * Whether those times rise strictly. A point written in place is found by
   * its time, which names one point only while there is one bar per time, in
   * order; a chart's source always is, and anything else is written whole.
   */
  private _ordered = true;
  /** How many of them the current pass kept, or -1 when its bars rewrote them. */
  private _kept = -1;
  private _pass = 0;
  private readonly _records = new WeakMap<SeriesApi, PlotRecord>();

  /**
   * Start a pass over `bars`. The last pass's records stay comparable only
   * when these bars begin with the times it wrote: the same bars with a moved
   * tail, or the same with new ones appended.
   */
  public begin(bars: readonly Bar[]): void {
    const times = this._times, m = times.length, n = bars.length;
    let kept = this._ordered && n >= m;
    for (let i = 0; i < m && kept; i++) kept = bars[i]!.time === times[i];
    if (!kept) {
      times.length = 0;
      this._ordered = true;
    }
    for (let i = times.length; i < n; i++) { // `times` holds the first `i` of them
      const time = bars[i]!.time;
      if (i > 0 && !(time > times[i - 1]!)) this._ordered = false;
      times.push(time);
    }
    this._kept = kept && this._ordered ? m : -1;
    this._pass++;
  }

  /** Empty a plot's series; its next write is whole. */
  public clear(series: SeriesApi): void {
    this._records.delete(series);
    series.setData([]);
  }

  /** Write a value plot: one point per bar, coloured by `colorParts` or `colorBy`. */
  public writeValues(series: SeriesApi, plot: IndicatorPlot, col: IndicatorValues[string] | undefined,
    bars: readonly Bar[], values: IndicatorValues, settings: Settings): void {
    if (col === undefined) { this.clear(series); return; }
    const n = bars.length;
    const { colorBy, colorParts } = plot;
    const coloured = colorBy !== undefined || colorParts !== undefined;
    const opacity = coloured ? opacityOf(plot, settings) : 100;
    const [rec, m] = this._claim(series, 1, 1);
    const value = rec.cols[0]!, body = rec.colors[0]!; // the one list each that _claim made
    const changed: number[] = [];
    let whole = m < 0;
    for (let i = 0; i < n; i++) {
      const v = col[i];
      const next = v === null || v === undefined ? NaN : v;
      // A value column has only a body to paint; the split form's wick and
      // border are for the candle plot, see `writeCandles`.
      let paint: unknown;
      if (coloured && Number.isFinite(next)) {
        paint = faded(colorParts?.({ value: next, index: i, values, settings })?.body ?? colorBy?.({ value: next, index: i, values, settings }), opacity);
      }
      if (!whole && (i >= m || !same(value[i], next) || (coloured && body[i] !== paint)) && changed.push(i) > IN_PLACE) whole = true;
      value[i] = next;
      if (coloured) body[i] = paint;
    }
    const point = (i: number): { time: number; value: number; color?: string } => {
      const p: { time: number; value: number; color?: string } = { time: bars[i]!.time, value: value[i] as number };
      if (body[i] !== undefined) p.color = body[i] as string;
      return p;
    };
    this._commit(series, rec, whole, changed, n, point);
  }

  /**
   * Write a candle plot from four columns. Validated here rather than at
   * registration: a descriptor declares column *names*, and whether `calc`
   * actually returns them is only knowable once it has run, which is inside
   * the constructor, so a wrong name still throws out of `addIndicator`
   * instead of drawing an empty pane.
   */
  public writeCandles(series: SeriesApi, plot: IndicatorPlot, ohlc: NonNullable<IndicatorPlot['ohlc']>,
    bars: readonly Bar[], values: IndicatorValues, settings: Settings, indicatorId: string): void {
    const n = bars.length;
    const cols = [ohlc.open, ohlc.high, ohlc.low, ohlc.close].map((key) => {
      const col = values[key];
      if (col === undefined || col.length !== n) {
        throw new Error(`openalgo-charts: ${indicatorId} plot "${plot.key}" ohlc column "${key}" must be ${n} values`);
      }
      return col;
    });
    const { colorBy, colorParts } = plot;
    const opacity = colorBy !== undefined || colorParts !== undefined ? opacityOf(plot, settings) : 100;
    const [rec, m] = this._claim(series, 4, 3);
    const [open, high, low, close] = rec.cols as [List, List, List, List], [color, wick, border] = rec.colors as [List, List, List];
    const changed: number[] = [];
    let whole = m < 0;
    for (let i = 0; i < n; i++) { // four columns of `n` values each, checked above
      const c = cols[3]![i] as number | null;
      const value = c === null ? NaN : c;
      const o = cols[0]![i] ?? NaN, h = cols[1]![i] ?? NaN, l = cols[2]![i] ?? NaN;
      let body: unknown, wickColor: unknown, borderColor: unknown;
      if (Number.isFinite(value)) {
        body = colorBy?.({ value, index: i, values, settings });
        const parts = colorParts?.({ value, index: i, values, settings });
        if (parts !== undefined) {
          if (parts.body !== undefined) body = parts.body;
          wickColor = faded(parts.wick, opacity);
          borderColor = faded(parts.border, opacity);
        }
        body = faded(body, opacity);
      }
      if (!whole && (i >= m || !same(open[i], o) || !same(high[i], h) || !same(low[i], l)
        || !same(close[i], value) || color[i] !== body || wick[i] !== wickColor || border[i] !== borderColor)
        && changed.push(i) > IN_PLACE) whole = true;
      open[i] = o; high[i] = h; low[i] = l; close[i] = value;
      color[i] = body; wick[i] = wickColor; border[i] = borderColor;
    }
    const point = (i: number): Bar => {
      const bar: Bar = { time: bars[i]!.time, open: open[i] as number, high: high[i] as number, low: low[i] as number, close: close[i] as number };
      if (color[i] !== undefined) bar.color = color[i] as string;
      if (wick[i] !== undefined) bar.wickColor = wick[i] as string;
      if (border[i] !== undefined) bar.borderColor = border[i] as string;
      return bar;
    };
    this._commit(series, rec, whole, changed, n, point);
  }

  /**
   * A plot's record and how many of its points this pass may compare with:
   * all of them when the last pass wrote it and this pass kept those times,
   * otherwise none (-1), and the record starts over.
   */
  private _claim(series: SeriesApi, cols: number, colors: number): [PlotRecord, number] {
    let rec = this._records.get(series);
    const m = rec !== undefined && rec.pass === this._pass - 1 ? this._kept : -1;
    if (rec === undefined) {
      rec = { pass: -1, cols: Array.from({ length: cols }, () => []), colors: Array.from({ length: colors }, () => []) };
      this._records.set(series, rec);
    } else if (m < 0) {
      for (const list of [...rec.cols, ...rec.colors]) list.length = 0;
    }
    return [rec, m];
  }

  // `point` is asked for indices below `n` only, so it reads the pass's bars in range.
  private _commit(series: SeriesApi, rec: PlotRecord, whole: boolean, changed: readonly number[], n: number,
    point: (i: number) => SeriesDataItem): void {
    if (whole) {
      const out = new Array<SeriesDataItem>(n);
      for (let i = 0; i < n; i++) out[i] = point(i);
      series.setData(out);
    } else if (n === 0) {
      series.setData([]);
    } else {
      // In index order, so an appended point lands after the one it follows.
      for (const i of changed) series.update(point(i));
      // The last point goes out even unmoved: a write is what repaints, and a
      // recompute has always repainted whether or not its numbers moved.
      if (changed[changed.length - 1] !== n - 1) series.update(point(n - 1));
    }
    // Stamped last: a write that throws leaves the record a pass behind, and
    // the next pass writes this plot whole.
    rec.pass = this._pass;
  }
}
