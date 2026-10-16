const active = new WeakMap<CanvasRenderingContext2D, Map<string, number>>();
const MAX_LABELS = 1024;

/** Keep measurements within one paint so newly loaded fonts cannot leave stale widths. */
export function withDrawingTextMetrics<T>(ctx: CanvasRenderingContext2D, paint: () => T): T {
  const previous = active.get(ctx);
  active.set(ctx, new Map());
  try { return paint(); } finally {
    if (previous) active.set(ctx, previous);
    else active.delete(ctx);
  }
}

export function drawingTextWidth(ctx: CanvasRenderingContext2D, text: string): number {
  const cache = active.get(ctx);
  if (!cache) return ctx.measureText(text).width;
  const key = ctx.font + '\0' + text;
  const cached = cache.get(key);
  if (cached !== undefined) return cached;
  const width = ctx.measureText(text).width;
  if (cache.size < MAX_LABELS) cache.set(key, width);
  return width;
}
