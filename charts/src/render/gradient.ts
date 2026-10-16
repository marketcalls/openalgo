/**
 * Cached vertical gradients (ARCHITECTURE.md §6), plus the sRGB colour helpers
 * a custom indicator needs. A `CanvasGradient` belongs to the context that
 * created it, so the cache is keyed per-context (WeakMap) and by height +
 * colors. Used for area/baseline fills.
 */
import { parseColor } from './pill';

/**
 * Re-exported, not reimplemented: one import path covers an indicator's colour
 * work, while the colour parsing stays in `pill.ts`. A copy of it elsewhere in
 * the base costs bytes and drifts out of step with it.
 */
export { withAlpha } from './pill';

const perCtx = new WeakMap<CanvasRenderingContext2D, Map<string, CanvasGradient>>();

export function verticalGradient(
  ctx: CanvasRenderingContext2D,
  heightPx: number,
  topColor: string,
  bottomColor: string,
): CanvasGradient {
  let m = perCtx.get(ctx);
  if (m === undefined) { m = new Map(); perCtx.set(ctx, m); }
  const key = `${Math.round(heightPx)}|${topColor}|${bottomColor}`;
  let g = m.get(key);
  if (g === undefined) {
    g = ctx.createLinearGradient(0, 0, 0, heightPx);
    g.addColorStop(0, topColor);
    g.addColorStop(1, bottomColor);
    m.set(key, g);
  }
  return g;
}

/**
 * Blend `low` to `high` in sRGB by where `value` sits in [min, max], clamped
 * outside. Heatmap plots and per-bar colouring call this once per bar, so it
 * allocates only the result string: no closure, no cache, no lookup table.
 *
 * The clamp is two comparisons rather than Math.min/Math.max because both are
 * false against a not-available value, which lands it on `low` instead of
 * poisoning the output with NaN. Canvas ignores an unparseable fillStyle and
 * silently keeps the previous one, so a bad string would bleed a neighbour's
 * colour across the bar rather than fail loudly.
 */
export function fromGradient(value: number, min: number, max: number, low: string, high: string): string {
  const a = parseColor(low);
  const b = parseColor(high);
  if (a === null || b === null) return low;
  const t = (value - min) / (max - min);
  const k = t > 0 ? (t < 1 ? t : 1) : 0;
  return `rgba(${Math.round(a.r + (b.r - a.r) * k)},${Math.round(a.g + (b.g - a.g) * k)},${Math.round(a.b + (b.b - a.b) * k)},${a.a + (b.a - a.a) * k})`;
}
