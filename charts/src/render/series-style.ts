/**
 * Unified style bag for all Family-A series types (ARCHITECTURE.md §6A). Each
 * renderer reads the fields it needs; per-type defaults are filled by the
 * chart-type registry. Keeping one optional-field interface avoids a sprawling
 * discriminated union at the rendering boundary.
 */
import type { ChartTheme } from '../theme';

export interface SeriesStyle {
  // candle / bar family
  upColor?: string;
  downColor?: string;
  borderUpColor?: string;
  borderDownColor?: string;
  wickUpColor?: string;
  wickDownColor?: string;
  borderVisible?: boolean;
  wickVisible?: boolean;
  /** Paint candle bodies. Off leaves outline and wick. Default true. */
  bodyVisible?: boolean;
  /**
   * Has no effect: no renderer reads it, and a `candlestick` series with it set
   * draws filled candles.
   *
   * @deprecated Removed in 3.0.0. Add the series as `'hollow-candle'` (or switch it with
   * `chart.setSeriesType`), which draws up candles as outlines and down candles filled.
   */
  hollow?: boolean;
  /**
   * Color bars by close-versus-previous-close instead of close-versus-own-open,
   * which is how most terminals paint a bar. Body, border and wick switch
   * together. Default false.
   */
  colorByPreviousClose?: boolean;

  /** Whether the series is drawn and counted in autoscale. Default true. */
  visible?: boolean;
  /** Optional label carried with the series (for host-drawn legends). */
  title?: string;
  /** Show the dashed horizontal last-price line across the plot. Default true. */
  priceLineVisible?: boolean;
  /**
   * Show this series' current value as a tag on the price axis. Default true.
   *
   * Each visible left or right scale labels its own series, including indicator
   * overlays, comparison lines and studies. Hidden scales have no tags. The
   * instrument's tag is the up/down coloured one that also carries the bar
   * countdown; the rest are drawn in their own plot colour. A series whose
   * current value is not a number draws no tag, so a study that is `na` right
   * now says nothing rather than showing a stale reading.
   */
  lastValueVisible?: boolean;
  /**
   * Decimal places for every price the scale this series maps to formats: the
   * axis ticks, the last-value tag, the crosshair label and the drawing-tool
   * labels. It overrides the precision the price scale infers from the tick
   * size or the visible range. Undefined is the "Default" entry of the
   * Precision dropdown: keep inferring. Valid range 0 to 8.
   *
   * It does not reach a legend row: a `PaneLegend` is handed finished strings,
   * so whoever builds those readings owns their formatting.
   */
  precision?: number;

  /**
   * Draw every point this many bars to the right of the bar it belongs to
   * (negative: left). The data is untouched and keeps its own times; only the
   * painted position moves, so the last `barOffset` points of a series land in
   * the right margin, past the newest bar. Autoscale follows what is drawn in
   * view. Default 0.
   */
  barOffset?: number;

  // line / area / baseline / hlc-area family
  color?: string;
  lineWidth?: number;
  /** Line dash style for line/step/area/HLC series. Default 'solid'. */
  lineStyle?: 'solid' | 'dashed' | 'dotted';
  step?: boolean;
  markers?: boolean;
  /** Draw only the markers, with no connecting line (Parabolic SAR, scatter). */
  markersOnly?: boolean;
  markerRadius?: number;
  areaTopColor?: string;
  areaBottomColor?: string;
  baseValue?: number;
  topColor?: string;
  bottomColor?: string;
  /**
   * Stroke for the top edge of an HLC area's band. Undefined leaves the edge
   * unstroked, which is how the band has always drawn.
   */
  highColor?: string;
  /** Stroke for the bottom edge of an HLC area's band. See `highColor`. */
  lowColor?: string;
  closeColor?: string;

  // histogram / column family
  base?: number;

  // point & figure / kagi family
  /**
   * Fallback box size for stacking P&F X/O glyphs. Columns from
   * `PointFigureTransform` carry their own `boxSize`, which wins, so set this
   * only for hand-built column data.
   */
  boxSize?: number;
  /** Kagi thick (yang) line color. */
  thickColor?: string;
  /** Kagi thin (yin) line color. */
  thinColor?: string;
}

// Theme fallbacks per family: where the style sets no colour, the theme's.
// The 2D registry and the GPU backend both resolve through these, so a
// family's defaults are written once. Candles have `resolveCandleStyle`.

/** Bars, high-low and columns: up and down colours. */
export function withUpDown(s: SeriesStyle, t: ChartTheme): SeriesStyle {
  return { ...s, upColor: s.upColor ?? t.upColor, downColor: s.downColor ?? t.downColor };
}

/** Lines: the line colour, plus the type's own switch (`markers`, `step`). */
export function withLineColor(s: SeriesStyle, t: ChartTheme, extra?: SeriesStyle): SeriesStyle {
  return { ...s, color: s.color ?? t.lineColor, ...extra };
}

/** Area: the line colour and both fill stops. */
export function withAreaColors(s: SeriesStyle, t: ChartTheme): SeriesStyle {
  return {
    ...s,
    color: s.color ?? t.lineColor,
    areaTopColor: s.areaTopColor ?? t.areaTopColor,
    areaBottomColor: s.areaBottomColor ?? t.areaBottomColor,
  };
}

/** Baseline: the line and fill on each side of the base. */
export function withBaselineColors(s: SeriesStyle, t: ChartTheme): SeriesStyle {
  return {
    ...s,
    topColor: s.topColor ?? t.baselineTopLine,
    bottomColor: s.bottomColor ?? t.baselineBottomLine,
    areaTopColor: s.areaTopColor ?? t.baselineTopFill,
    areaBottomColor: s.areaBottomColor ?? t.baselineBottomFill,
  };
}

/** HLC area: the close line. The band has its own default, see `HLC_AREA_BAND_COLOR`. */
export function withHlcAreaColors(s: SeriesStyle, t: ChartTheme): SeriesStyle {
  return { ...s, closeColor: s.closeColor ?? t.lineColor };
}
