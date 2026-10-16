/**
 * Bar-family renderers (ARCHITECTURE.md §6A): OHLC bars, high-low bars, and
 * columns. Pure geometry helpers are split out for unit testing.
 */
import type { Bar } from '../model/bar';
import type { SeriesStyle } from './series-style';
import { optimalBarWidth } from './candles';

export interface BarDrawItem {
  x: number; // bar center, media px
  bar: Bar;
  /**
   * Close of the bar immediately before this one when that bar is not itself in
   * `items`, which is the case for the first visible bar after a scroll. Only
   * read when `colorByPreviousClose` is on, and only for the first item.
   */
  prevClose?: number;
}

interface BarGeometry {
  cx: number;
  yOpen: number;
  yClose: number;
  yHigh: number;
  yLow: number;
  up: boolean;
}

/** Pure: device-pixel geometry for one OHLC bar. */
export function barGeometry(item: BarDrawItem, toY: (v: number) => number, dpr: number): BarGeometry {
  const b = item.bar;
  return {
    cx: Math.round(item.x * dpr),
    yOpen: Math.round(toY(b.open) * dpr),
    yClose: Math.round(toY(b.close) * dpr),
    yHigh: Math.round(toY(b.high) * dpr),
    yLow: Math.round(toY(b.low) * dpr),
    up: b.close >= b.open,
  };
}

/** OHLC bars: vertical high to low, left tick = open, right tick = close. */
export function drawBars(
  ctx: CanvasRenderingContext2D,
  items: readonly BarDrawItem[],
  toY: (v: number) => number,
  barSpacing: number,
  dpr: number,
  style: SeriesStyle,
  highLowOnly = false,
): void {
  const tick = Math.max(1, Math.floor(optimalBarWidth(barSpacing, dpr) / 2));
  const lw = Math.max(1, Math.floor(dpr));
  ctx.save();
  for (let i = 0; i < items.length; i++) {
    const item = items[i]!; // i, and i - 1 when positive, index items
    // `barGeometry`, worked out in place: this runs for every bar in view on
    // every frame, and an object per bar is garbage by the next one.
    const b = item.bar;
    const cx = Math.round(item.x * dpr);
    const yOpen = Math.round(toY(b.open) * dpr);
    const yClose = Math.round(toY(b.close) * dpr);
    const yHigh = Math.round(toY(b.high) * dpr);
    const yLow = Math.round(toY(b.low) * dpr);
    // An OHLC bar is the type this option is named for, so it follows the same
    // rule the candle renderer does: the reference is the bar before this one,
    // taken from `prevClose` for the first drawn bar, and a missing or
    // non-finite reference falls back to close-versus-own-open rather than
    // inventing one. See `CandleStyle.colorByPreviousClose`.
    const ref = i > 0 ? items[i - 1]!.bar.close : item.prevClose;
    const up = style.colorByPreviousClose === true && ref !== undefined && Number.isFinite(ref)
      ? item.bar.close >= ref
      : b.close >= b.open;
    // A per-bar colour override wins over the up/down verdict, the
    // same override the candle renderer honours. The whole bar takes it: range,
    // open tick and close tick are one glyph.
    ctx.fillStyle = item.bar.color
      ?? (up ? (style.upColor ?? '#26a69a') : (style.downColor ?? '#ef5350'));
    ctx.fillRect(cx - Math.floor(lw / 2), yHigh, lw, Math.max(1, yLow - yHigh));
    if (!highLowOnly) {
      ctx.fillRect(cx - tick, yOpen, tick, lw); // open tick (left)
      ctx.fillRect(cx, yClose, tick, lw); // close tick (right)
    }
  }
  ctx.restore();
}

/** Columns: filled bars from a base value up to each bar's close. */
export function drawColumns(
  ctx: CanvasRenderingContext2D,
  items: readonly BarDrawItem[],
  toY: (v: number) => number,
  barSpacing: number,
  dpr: number,
  style: SeriesStyle,
): void {
  const w = optimalBarWidth(barSpacing, dpr);
  const half = Math.floor(w / 2);
  const baseY = Math.round(toY(style.base ?? 0) * dpr);
  ctx.save();
  for (const item of items) {
    // `barGeometry`'s centre, close and direction, worked out in place, and
    // its open, high and low not at all: a column draws none of them.
    const cx = Math.round(item.x * dpr);
    const yClose = Math.round(toY(item.bar.close) * dpr);
    const up = item.bar.close >= item.bar.open;
    // A per-bar colour wins over the up/down pair, matching the histogram
    // renderer. Indicators whose meaning changes bar to bar set it through the
    // descriptor's `colorBy`, and a column plot that ignored it would silently
    // paint the whole series one colour.
    //
    // `style.color` sits between the two, again as in the histogram: a single
    // colour is what an indicator plot's Colour control writes, and a column
    // that read only the up/down pair left that control inert.
    ctx.fillStyle = item.bar.color ?? style.color
      ?? (up ? (style.upColor ?? '#26a69a') : (style.downColor ?? '#ef5350'));
    const top = Math.min(baseY, yClose);
    ctx.fillRect(cx - half, top, w, Math.max(1, Math.abs(baseY - yClose)));
  }
  ctx.restore();
}
