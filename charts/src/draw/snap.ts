/**
 * The magnet: where an anchor lands when it snaps to what its pane plots. On
 * the price pane that is the open, high, low or close of the bar under it; on
 * a study pane it is the value each plot drawn there has at that bar. Either
 * way the anchor takes the bar's own time, so a snapped point sits on the bar
 * centre, and a study's value is read the way its legend reads it: the value
 * painted under the bar, after the plot's offset.
 *
 * The candles are compared by price, as they always have been. A study pane
 * can carry plots on more than one scale (an overlay on the left axis beside
 * the pane's own), where one price means a different place on each, so its
 * candidates are compared where they are painted, in pixels, and the price an
 * anchor takes is read back through the pane's own scale.
 */
import { getIndicator } from 'openalgo-charts';
import type { Bar } from 'openalgo-charts';
import type { DrawingPoint, MagnetMode } from './types';
import type { DrawingChartHost } from './controller-types';

/** How close, in media px, a value must be for the weak magnet to pull. */
const WEAK_MAGNET_PX = 8;

/** The 1.9.x boolean and the 2.0 modes, folded onto one. */
export function magnetModeOf(value: boolean | MagnetMode | undefined): MagnetMode {
  if (value === true) return 'strong';
  if (value === 'weak' || value === 'strong') return value;
  return 'off';
}

/** A bar of the price series at its own time: what the price pane snaps to. */
export interface SnapBar {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
}

/**
 * The slice of the chart the magnet reads. Every member past the data layer
 * is optional: without `priceToCoordinate` the weak magnet cannot judge
 * "close" on the price pane, without a pane's own projection (`panes`) a
 * study pane cannot be compared at all, and without the price series or the
 * studies there is nothing to snap to.
 */
type MagnetHost = Pick<DrawingChartHost, 'dataLayer' | 'priceToCoordinate' | 'primaryBars' | 'indicators' | 'panes' | 'seriesStyle'>;

/** What a study pane is read through: its scales and its own price projection, pane-local. `Pane` has them. */
interface StudyPane {
  scales(): readonly unknown[];
  priceToY(price: number): number;
  yToPrice(y: number): number;
}

/** A study pane the magnet can compare in pixels, or null. */
function studyPane(host: MagnetHost, paneIndex: number): StudyPane | null {
  const pane = (host.panes?.() ?? [])[paneIndex] as Partial<StudyPane> | undefined;
  return typeof pane?.scales === 'function' && typeof pane.priceToY === 'function' && typeof pane.yToPrice === 'function'
    ? pane as StudyPane : null;
}

/** The index of the bar at exactly `time` in time-sorted `bars`, or -1. */
function indexOfTime(bars: readonly Bar[], time: number): number {
  let lo = 0;
  let hi = bars.length - 1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    const t = bars[mid]!.time; // lo <= mid <= hi, all in range
    if (t === time) return mid;
    if (t < time) lo = mid + 1;
    else hi = mid - 1;
  }
  return -1;
}

/**
 * The price bar whose slot `time` falls in, or null past the data or on a
 * host that cannot say. What a drag snaps against: the chart reports no bar
 * while a drawing is in hand, only the pointer's time.
 */
export function barAt(host: MagnetHost, time: number): SnapBar | null {
  const bars = host.primaryBars?.();
  if (bars === undefined || bars.length === 0 || !Number.isFinite(time)) return null;
  const at = host.dataLayer.indexToTime(Math.round(host.dataLayer.timeToIndexFloat(time)));
  const i = at === undefined ? -1 : indexOfTime(bars, at);
  if (i < 0) return null;
  const { open, high, low, close } = bars[i]!; // a found index
  return { time: bars[i]!.time, open, high, low, close };
}

/** Whether a colour paints nothing: the helper plot a band or a mark is measured from. */
function invisible(color: string | undefined): boolean {
  const c = color?.trim().toLowerCase() ?? '';
  if (c === 'transparent') return true;
  if (/^#[0-9a-f]{4}$/.test(c)) return c[4] === '0';
  if (/^#[0-9a-f]{8}$/.test(c)) return c.endsWith('00');
  const args = /^(?:rgb|hsl)a?\((.*)\)$/.exec(c)?.[1]!.split(/[\s,/]+/).filter(Boolean);
  return args?.length === 4 && parseFloat(args[3]!) === 0; // the group is in every match; four args
}

/**
 * Where each visible plot drawn on `paneIndex` is painted at the bar of
 * `time`, in pane media px, each with the value it shows and whether its
 * scale is the pane's own (the value is then the price as it stands).
 */
function plotCandidates(host: MagnetHost, pane: StudyPane, time: number): { y: number; value: number; own: boolean }[] {
  const studies = host.indicators?.() ?? [];
  if (studies.length === 0) return [];
  const bars = host.primaryBars?.();
  const index = bars === undefined ? Math.round(host.dataLayer.timeToIndexFloat(time)) : indexOfTime(bars, time);
  if (index < 0) return [];
  const out: { y: number; value: number; own: boolean }[] = [];
  for (const study of studies) {
    if (!study.visible()) continue;
    let plots;
    try { plots = getIndicator(study.indicatorId).plots; } catch { continue; }
    const values = study.values();
    for (const plot of plots) {
      const series = study.series(plot.key);
      if (series === undefined) continue;
      const scale = series.priceScale();
      if (!pane.scales().includes(scale)) continue;
      const style = host.seriesStyle?.(series);
      if (style?.visible === false || invisible(style?.color)) continue;
      const columns = plot.ohlc === undefined ? [plot.key] : [plot.ohlc.open, plot.ohlc.high, plot.ohlc.low, plot.ohlc.close];
      for (const column of columns) {
        const value = values[column]?.[index - (plot.offset ?? 0)];
        if (value === null || value === undefined || !Number.isFinite(value)) continue;
        const y = scale.priceToY(value);
        if (!Number.isFinite(y)) continue;
        // The same place through the pane's own mapping means the same scale,
        // and the value itself is the price; any other scale reads it back.
        out.push({ y, value, own: Math.abs(pane.priceToY(value) - y) < 1e-6 });
      }
    }
  }
  return out;
}

/**
 * Where the magnet lands `point` on `paneIndex`, or null when it does not
 * pull. `bar` is the price bar the anchor is on: the one the chart reported
 * under the pointer, or `barAt` for a drag. `strong` always takes the nearest
 * value; `weak` only one within {@link WEAK_MAGNET_PX} on screen, so a click
 * on open space stays where it was made.
 */
export function magnetPoint(
  host: MagnetHost, point: DrawingPoint, paneIndex: number, mode: 'weak' | 'strong', pricePane: number, bar: SnapBar | null,
): DrawingPoint | null {
  if (bar === null) return null;
  const toY = host.priceToCoordinate;
  if (paneIndex === pricePane) {
    const values = [bar.open, bar.high, bar.low, bar.close];
    if (mode === 'strong') {
      let best = values[0]!; // four values
      let bestD = Infinity;
      for (const v of values) {
        const d = Math.abs(v - point.price);
        if (d < bestD) { bestD = d; best = v; }
      }
      return { time: bar.time, price: best };
    }
    // Weak: the nearest value by screen distance, and only when it is close.
    // Without a pixel mapping there is no "close", so nothing pulls.
    if (toY === undefined) return null;
    const y = toY.call(host, point.price, paneIndex);
    if (y === null || !Number.isFinite(y)) return null;
    let best: number | null = null;
    let bestD = WEAK_MAGNET_PX;
    for (const v of values) {
      const vy = toY.call(host, v, paneIndex);
      if (vy === null || !Number.isFinite(vy)) continue;
      const d = Math.abs(vy - y);
      if (d <= bestD) { bestD = d; best = v; }
    }
    return best === null ? null : { time: bar.time, price: best };
  }
  const pane = studyPane(host, paneIndex);
  const y = pane?.priceToY(point.price) ?? Number.NaN;
  if (pane === null || !Number.isFinite(y)) return null;
  let best: { y: number; value: number; own: boolean } | null = null;
  let bestD = mode === 'strong' ? Infinity : WEAK_MAGNET_PX;
  for (const c of plotCandidates(host, pane, bar.time)) {
    const d = Math.abs(c.y - y);
    if (d <= bestD) { bestD = d; best = c; }
  }
  if (best === null) return null;
  const price = best.own ? best.value : pane.yToPrice(best.y);
  return Number.isFinite(price) ? { time: bar.time, price } : null;
}
