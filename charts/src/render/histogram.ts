/**
 * Histogram renderer (ARCHITECTURE.md §6), used for volume and for a study's
 * histogram plots. Bars are drawn from a base value (0) up to each bar's
 * close. Columns are drawn by `drawColumns` in bars.ts.
 */
import type { Bar } from '../model/bar';
import { optimalBarWidth } from './candles';

export interface HistogramStyle {
  color: string;
  /** Value the bars grow from (default 0). */
  base: number;
}

export const DEFAULT_HISTOGRAM_STYLE: HistogramStyle = {
  color: '#3a4666',
  base: 0,
};

interface HistogramDrawItem {
  x: number; // bar center, media px
  bar: Bar;
}

export function drawHistogram(
  ctx: CanvasRenderingContext2D,
  items: readonly HistogramDrawItem[],
  valueToY: (value: number) => number,
  barSpacing: number,
  dpr: number,
  style: HistogramStyle = DEFAULT_HISTOGRAM_STYLE,
): void {
  const w = optimalBarWidth(barSpacing, dpr);
  const half = Math.floor(w / 2);
  const baseY = Math.round(valueToY(style.base) * dpr);
  // Set per bar rather than once: a bar may carry its own colour.
  let current = '';
  for (const { x, bar } of items) {
    const fill = bar.color ?? style.color;
    if (fill !== current) {
      ctx.fillStyle = fill;
      current = fill;
    }
    const cx = Math.round(x * dpr);
    const y = Math.round(valueToY(bar.close) * dpr);
    const top = Math.min(baseY, y);
    const h = Math.max(1, Math.abs(baseY - y));
    ctx.fillRect(cx - half, top, w, h);
  }
}
