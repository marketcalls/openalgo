/**
 * Point & Figure renderer (ARCHITECTURE.md §6A). Each column Bar (from the P&F
 * transform) is drawn as a stack of X (up) or O (down) glyphs over its price
 * range.
 *
 * The box size comes from the column itself (`PointFigureColumn.boxSize`), so
 * variable-box modes (percent / ATR) render correctly and a mismatched
 * `style.boxSize` can no longer desync the glyph stack from the data.
 * `style.boxSize` remains a fallback for hand-built column data, and failing
 * that the box is inferred from the shortest column in view.
 *
 * Glyph rows are walked by **integer box index**, not by accumulating `+= box`
 * (30 steps of 0.05 lands on 101.49999999999991, which used to drop or
 * duplicate the top glyph of tall columns). Rows outside the plot are culled.
 */
import type { DrawItem } from '../model/chart-type-registry';
import type { SeriesStyle } from './series-style';

/** Hard cap on glyphs per column, so a pathological box size can't hang a frame. */
const MAX_GLYPHS = 4000;

/** Box size for a column: its own, else the style's, else inferred. */
function boxOf(bar: DrawItem['bar'], style: SeriesStyle, inferred: number): number {
  const own = (bar as { boxSize?: number }).boxSize;
  if (typeof own === 'number' && own > 0) return own;
  if (style.boxSize !== undefined && style.boxSize > 0) return style.boxSize;
  return inferred;
}

/** Shortest non-zero column height in view: a usable box when nothing declares one. */
function inferBox(items: readonly DrawItem[]): number {
  let min = Infinity;
  for (const { bar } of items) {
    const h = bar.high - bar.low;
    if (h > 0 && h < min) min = h;
  }
  return Number.isFinite(min) ? min : 0;
}

export function drawPointFigure(
  ctx: CanvasRenderingContext2D,
  items: readonly DrawItem[],
  toY: (v: number) => number,
  barSpacing: number,
  dpr: number,
  style: SeriesStyle,
  plotHeight = Infinity,
): void {
  if (items.length === 0) return;
  const inferred = inferBox(items);
  const cellW = Math.max(3, Math.floor(barSpacing * dpr * 0.7));
  const r = cellW / 2;
  const bottom = plotHeight === Infinity ? Infinity : plotHeight * dpr;

  ctx.save();
  ctx.lineWidth = Math.max(1, Math.floor(dpr));
  for (const { x, bar } of items) {
    const box = boxOf(bar, style, inferred);
    if (!(box > 0)) continue;

    // Integer box indices: [k0, k1] inclusive. `high` is the exclusive top edge.
    const k0 = Math.round(bar.low / box);
    const k1 = Math.round(bar.high / box) - 1;
    if (k1 < k0) continue;
    if (k1 - k0 + 1 > MAX_GLYPHS) continue;

    const up = bar.close >= bar.open;
    ctx.strokeStyle = up ? (style.upColor ?? '#26a69a') : (style.downColor ?? '#ef5350');
    const cx = x * dpr;

    for (let k = k0; k <= k1; k++) {
      const yTop = toY((k + 1) * box) * dpr;
      const yBot = toY(k * box) * dpr;
      // Cull rows fully outside the plot (tall columns at deep zoom).
      if (yBot < 0 || yTop > bottom) continue;
      ctx.beginPath();
      if (up) {
        // X glyph
        ctx.moveTo(cx - r, yTop); ctx.lineTo(cx + r, yBot);
        ctx.moveTo(cx + r, yTop); ctx.lineTo(cx - r, yBot);
      } else {
        // O glyph
        ctx.ellipse(cx, (yTop + yBot) / 2, r, Math.abs(yBot - yTop) / 2, 0, 0, Math.PI * 2);
      }
      ctx.stroke();
    }
  }
  ctx.restore();
}
