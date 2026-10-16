/**
 * Chart-type registry (ARCHITECTURE.md §6A). Every series type registers a
 * descriptor: how to draw it and how it contributes to autoscale. The core
 * iterates descriptors, so adding a style is one registration and no core change.
 * The time-indexed types register here; the transform tier registers the ones
 * it draws from its own elements (Point & Figure, Kagi).
 */
import type { Bar } from './bar';
import type { SeriesStyle } from '../render/series-style';
import type { ChartTheme } from '../theme';
import { drawCandles, resolveCandleStyle } from '../render/candles';
import { drawBars, drawColumns } from '../render/bars';
import { drawLine, drawArea, drawBaseline, drawHlcArea } from '../render/line';
import { drawHistogram, DEFAULT_HISTOGRAM_STYLE, type HistogramStyle } from '../render/histogram';
import {
  withAreaColors, withBaselineColors, withHlcAreaColors, withLineColor, withUpDown,
} from '../render/series-style';

export type SeriesType =
  | 'candlestick'
  | 'hollow-candle'
  | 'volume-candle'
  | 'bar'
  | 'high-low'
  | 'line'
  | 'line-markers'
  | 'step'
  | 'area'
  | 'hlc-area'
  | 'baseline'
  | 'column'
  | 'histogram'
  | 'point-figure'
  | 'kagi';

export interface DrawItem {
  x: number; // bar center, media px
  bar: Bar;
  /**
   * Close of the bar left of the visible range, carried on the first item only.
   * Previous-close candle colouring is the one renderer that reads it, because
   * it is the one that needs a reference the visible window does not hold.
   */
  prevClose?: number;
  /**
   * Set only on the neighbour a `connectsBars` renderer gets beyond each edge
   * of the view: the x (media px) of the plot edge between it and the bars in
   * view, 0 on the left and the plot width on the right. That neighbour can
   * sit millions of pixels off screen (a level held for a session on an axis
   * of five-second bars), so a renderer cuts the segment to it at this x,
   * plus whatever its stroke needs, rather than draw it all the way out, and
   * paints nothing of the neighbour's own (a marker, a body).
   */
  edgeX?: number;
}

export interface SeriesRenderContext {
  plotHeight: number;
  maxVolume: number;
  theme: ChartTheme;
}

export interface RendererEntry {
  defaultStyle: SeriesStyle;
  /** True for the price series whose last close drives the last-price line. */
  isPriceSeries: boolean;
  /**
   * True for a renderer that draws a segment from each bar to the next (a
   * line, a step, an area, kagi). Its items then carry the nearest bar beyond
   * each edge of the view as well, marked with `edgeX`, so the segment that
   * crosses an edge is drawn: a sparse line (a level held for an hour, a
   * position that steps twice a session) would otherwise lose the part that
   * enters from off screen. Such a renderer cuts that segment at `edgeX`.
   */
  connectsBars?: boolean;
  /**
   * Paint the items on a bitmap-scope 2D context: the bars in view, and for a
   * `connectsBars` renderer the neighbour beyond each edge (`DrawItem.edgeX`).
   * On screen the pane reaches this through its render backend
   * (src/render/backend.ts); the 2D backend calls it as is, and the vector
   * export calls it directly on the serialising target.
   */
  draw(
    ctx: CanvasRenderingContext2D,
    items: readonly DrawItem[],
    toY: (v: number) => number,
    barSpacing: number,
    dpr: number,
    style: SeriesStyle,
    rc: SeriesRenderContext,
  ): void;
  /** Min/max price contribution of one bar to autoscale. */
  extents(bar: Bar, style: SeriesStyle): { min: number; max: number };
}

const hiLo = (bar: Bar): { min: number; max: number } => ({ min: bar.low, max: bar.high });
const closeOnly = (bar: Bar): { min: number; max: number } => ({ min: bar.close, max: bar.close });
const fromBase = (bar: Bar, s: SeriesStyle): { min: number; max: number } => {
  const base = s.base ?? 0;
  return { min: Math.min(base, bar.close), max: Math.max(base, bar.close) };
};

const registry = new Map<string, RendererEntry>();

/** Series types that live in the lazy transform tier (registered on its import). */
const TRANSFORM_TIER_TYPES: ReadonlySet<string> = new Set(['point-figure', 'kagi']);

/** Register a chart type. `type` accepts a built-in `SeriesType` or any custom string. */
export function registerChartType(type: SeriesType | (string & {}), entry: RendererEntry): void {
  registry.set(type, entry);
}

export function getChartType(type: SeriesType | (string & {})): RendererEntry {
  const e = registry.get(type);
  if (e === undefined) {
    if (TRANSFORM_TIER_TYPES.has(type)) {
      throw new Error(`openalgo-charts: series type "${type}" needs the transform tier, import 'openalgo-charts/transform' first`);
    }
    throw new Error(`openalgo-charts: unknown series type "${type}"`);
  }
  return e;
}

export function registeredChartTypes(): string[] {
  return Array.from(registry.keys());
}

// ── Family A registrations ────────────────────────────────────────────────

registerChartType('candlestick', {
  defaultStyle: {}, isPriceSeries: true,
  draw: (g, items, toY, bs, dpr, s, rc) => drawCandles(g, items, toY, bs, dpr, resolveCandleStyle(s, rc.theme)),
  extents: hiLo,
});

registerChartType('hollow-candle', {
  defaultStyle: {}, isPriceSeries: true,
  draw: (g, items, toY, bs, dpr, s, rc) => drawCandles(g, items, toY, bs, dpr, resolveCandleStyle(s, rc.theme, { hollow: true })),
  extents: hiLo,
});

registerChartType('volume-candle', {
  defaultStyle: {}, isPriceSeries: true,
  draw: (g, items, toY, bs, dpr, s, rc) => {
    const max = rc.maxVolume;
    const scaled = resolveCandleStyle(s, rc.theme, { widthScale: (b) => (max > 0 ? (b.volume ?? 0) / max : 1) });
    drawCandles(g, items, toY, bs, dpr, scaled);
  },
  extents: hiLo,
});

registerChartType('bar', {
  defaultStyle: {}, isPriceSeries: true,
  draw: (g, items, toY, bs, dpr, s, rc) => drawBars(g, items, toY, bs, dpr, withUpDown(s, rc.theme)),
  extents: hiLo,
});

registerChartType('high-low', {
  defaultStyle: {}, isPriceSeries: true,
  draw: (g, items, toY, bs, dpr, s, rc) => drawBars(g, items, toY, bs, dpr, withUpDown(s, rc.theme), true),
  extents: hiLo,
});

registerChartType('line', {
  defaultStyle: { lineWidth: 1.5 }, isPriceSeries: true, connectsBars: true,
  draw: (g, items, toY, _bs, dpr, s, rc) => drawLine(g, items, toY, dpr, withLineColor(s, rc.theme)),
  extents: closeOnly,
});

registerChartType('line-markers', {
  defaultStyle: { lineWidth: 1.5, markers: true }, isPriceSeries: true, connectsBars: true,
  draw: (g, items, toY, _bs, dpr, s, rc) => drawLine(g, items, toY, dpr, withLineColor(s, rc.theme, { markers: true })),
  extents: closeOnly,
});

registerChartType('step', {
  defaultStyle: { lineWidth: 1.5, step: true }, isPriceSeries: true, connectsBars: true,
  draw: (g, items, toY, _bs, dpr, s, rc) => drawLine(g, items, toY, dpr, withLineColor(s, rc.theme, { step: true })),
  extents: closeOnly,
});

registerChartType('area', {
  defaultStyle: { lineWidth: 1.5 }, isPriceSeries: true, connectsBars: true,
  draw: (g, items, toY, _bs, dpr, s, rc) => drawArea(g, items, toY, dpr, rc.plotHeight, withAreaColors(s, rc.theme)),
  extents: closeOnly,
});

registerChartType('hlc-area', {
  defaultStyle: { lineWidth: 1.5 }, isPriceSeries: true, connectsBars: true,
  draw: (g, items, toY, _bs, dpr, s, rc) => drawHlcArea(g, items, toY, dpr, withHlcAreaColors(s, rc.theme)),
  extents: hiLo,
});

registerChartType('baseline', {
  defaultStyle: { baseValue: 0, lineWidth: 1.5 }, isPriceSeries: true, connectsBars: true,
  draw: (g, items, toY, _bs, dpr, s, rc) => drawBaseline(g, items, toY, dpr, withBaselineColors(s, rc.theme)),
  extents: (bar, s) => {
    const base = s.baseValue ?? 0;
    return { min: Math.min(base, bar.close), max: Math.max(base, bar.close) };
  },
});

registerChartType('column', {
  defaultStyle: { base: 0 }, isPriceSeries: false,
  draw: (g, items, toY, bs, dpr, s, rc) => drawColumns(g, items, toY, bs, dpr, withUpDown(s, rc.theme)),
  extents: fromBase,
});

registerChartType('histogram', {
  defaultStyle: { base: 0, color: DEFAULT_HISTOGRAM_STYLE.color }, isPriceSeries: false,
  draw: (g, items, toY, bs, dpr, s) => {
    const hs: HistogramStyle = { color: s.color ?? DEFAULT_HISTOGRAM_STYLE.color, base: s.base ?? 0 };
    drawHistogram(g, items, toY, bs, dpr, hs);
  },
  extents: fromBase,
});

// NOTE: 'point-figure' and 'kagi' are registered by the transform tier
// (src/transform/index.ts) so their renderers stay out of the base bundle.
// They are valid SeriesType names but only resolve once that tier is loaded.
