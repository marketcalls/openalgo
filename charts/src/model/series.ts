/**
 * Series records (ARCHITECTURE.md §4.3). A series references its rows in the
 * shared DataLayer by id, names a registered chart type, and carries a style
 * bag. The chart-type registry (§6A) supplies the renderer + autoscale extents,
 * so the core never switches on type.
 */
import type { SeriesId } from './data-layer';
import type { SeriesType } from './chart-type-registry';
import { getChartType } from './chart-type-registry';
import type { SeriesStyle } from '../render/series-style';
import type { Bar, SeriesDataItem } from './bar';
import type { SeriesMarkers } from '../primitives/markers';
import type { PriceScale } from '../scale/price-scale';

export type { SeriesType };

/**
 * Which price axis a series maps to. 'right' (default) and 'left' each draw an
 * axis and autoscale independently; '' is a hidden overlay scale (no axis, its
 * own autoscale) used to pin a volume histogram inside the price pane.
 * `overlay:name` creates an independent scale, hidden by default and shared only
 * by series using that same name on this pane. Chart.setPriceAxisPlacement can
 * display an overlay or change any scale's side without changing its identity.
 */
export type PriceScaleId = 'right' | 'left' | '' | `overlay:${string}`;
// `isPriceScaleId` (price-axis-layout.ts) checks a value against this. It lives
// there because that module imports nothing at run time, so a lazy tier can
// take it by path without this module's chart-type registry.

/**
 * Value formatting for a price scale (its axis labels and crosshair tag):
 * `price` (tick-size precision), `volume` (compact 1.2K / 3.4M / 5.6B),
 * `percent` (a `%` suffix at a fixed precision), or a `custom` formatter.
 *
 * It lives here rather than beside `addSeries` because an indicator plot names
 * one too, and the model tier cannot reach into the core.
 *
 * `percent` suffixes the value as it stands and does **not** scale it: a study
 * that already returns 0..100 reads `62.24%`, and one that returns a 0..1
 * fraction reads `0.62%`. Scaling here would put the axis and the plotted value
 * into disagreement, which is the one thing a formatter must never do.
 */
export type PriceFormat =
  | { type: 'price'; precision?: number; minMove?: number }
  | { type: 'volume' }
  | { type: 'percent'; precision?: number }
  | { type: 'custom'; formatter: (value: number) => string };

export interface SeriesRecord {
  dataId: SeriesId;
  type: SeriesType;
  style: SeriesStyle;
  scaleId: PriceScaleId;
}

/**
 * Explicit state of the supplied bar, including count-driven bars. For
 * `setData`, describes the last bar. `auto` returns to interval/clock inference.
 * Empty datasets have no confirmation override.
 */
export interface BarConfirmationOptions {
  confirmation?: 'auto' | 'forming' | 'confirmed';
}

/** Updates are live by default; historical corrections never count as live. */
export interface SeriesUpdateOptions extends BarConfirmationOptions {
  source?: 'live' | 'history';
}

/** Source metadata offered by native charts and optionally by custom indicator hosts. */
export interface SeriesDataState {
  /** Stable identity within the host; revisions belong to this source only. */
  readonly sourceId: number;
  readonly revision: number;
  /** Advances whenever a previously calculated history prefix may have changed. */
  readonly historyRevision: number;
  readonly provenance: 'history' | 'live' | 'replay';
  readonly change: 'reset' | 'prepend' | 'append' | 'replace' | 'correction';
  readonly confirmation?: 'forming' | 'confirmed';
  readonly confirmationSource?: 'provider' | 'replay';
}

/** Public handle returned by `chart.addSeries(...)`. */
export interface SeriesApi {
  /**
   * Replace historical data. Accepts OHLC bars, `{ time, value }` points, or
   * `{ time }` gaps. Omitted confirmation clears any previous tail override.
   */
  setData(bars: readonly SeriesDataItem[], options?: BarConfirmationOptions): void;
  /** Merge older data (history paging); same item shapes as `setData`. */
  prependData(bars: readonly SeriesDataItem[]): void;
  /**
   * Update one item. Replacing or appending the tail is live by default;
   * older corrections are historical. Same item shapes as `setData`.
   * Confirmation applies only when the supplied item is the tail; metadata
   * on older corrections cannot alter tail confirmation. An omitted override
   * survives same-tail writes, but clears when a new tail is appended.
   */
  update(bar: SeriesDataItem, options?: SeriesUpdateOptions): void;
  /** Current bars for this series (sorted old -> new, normalized to OHLC). Handy for computing the next live update. */
  getData(): Bar[];
  /** Merge a partial style into the series and repaint (recolor, `{ visible:false }` to hide, ...). */
  applyOptions(style: Partial<SeriesStyle>): void;
  /** Remove the series from its pane and free its data rows. */
  remove(): void;
  /** The price scale this series maps to (call `.setOptions({ marginTop, marginBottom })` on it). */
  priceScale(): PriceScale;
  /**
   * Create a markers layer (buy/sell signals, shapes) bound to this series.
   *
   * `fallbackBars` positions a mark whose time this series has no point for,
   * which happens whenever the series is drawn with gaps. Without it such a
   * mark is dropped silently.
   */
  createMarkers(fallbackBars?: () => readonly Bar[]): SeriesMarkers;
}

export function createSeriesRecord(dataId: SeriesId, type: SeriesType, style?: SeriesStyle, scaleId: PriceScaleId = 'right'): SeriesRecord {
  const entry = getChartType(type);
  return { dataId, type, style: { ...entry.defaultStyle, ...style }, scaleId };
}
