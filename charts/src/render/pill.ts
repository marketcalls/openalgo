/**
 * Shared pill/tag rendering + color helpers for the trading UI (order, position
 * and bracket lines). One place defines the rounded-pill look, the hover
 * brightening, and the text-contrast rule so every trade primitive matches on
 * both light and dark themes.
 */

/** A parsed colour: channels on the 0 to 255 scale and alpha on 0 to 1, neither clamped. */
export interface Rgba { r: number; g: number; b: number; a: number; }

/** Parse #rgb/#rrggbb/#rrggbbaa and rgb()/rgba() strings. Null when unknown. */
export function parseColor(color: string): Rgba | null {
  const c = color.trim();
  if (c.startsWith('#')) {
    const hex = c.slice(1);
    if (hex.length === 3 || hex.length === 4) {
      // Three or four digits: r, g and b are always there, a only with four.
      const [r, g, b, a] = [...hex].map((h) => parseInt(h + h, 16)) as [number, number, number, number?];
      if ([r, g, b].some(Number.isNaN)) return null;
      return { r, g, b, a: hex.length === 4 ? a! / 255 : 1 };
    }
    if (hex.length === 6 || hex.length === 8) {
      const n = parseInt(hex.slice(0, 6), 16);
      if (Number.isNaN(n)) return null;
      const a = hex.length === 8 ? parseInt(hex.slice(6, 8), 16) / 255 : 1;
      return { r: (n >> 16) & 255, g: (n >> 8) & 255, b: n & 255, a: Number.isNaN(a) ? 1 : a };
    }
    return null;
  }
  const m = /^rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*(?:,\s*([\d.]+)\s*)?\)$/i.exec(c);
  if (m === null) return null;
  return { r: Number(m[1]), g: Number(m[2]), b: Number(m[3]), a: m[4] === undefined ? 1 : Number(m[4]) };
}

/** Relative luminance (0..1) of a color; 0.5 for unparseable strings. */
export function luminance(color: string): number {
  const c = parseColor(color);
  return c === null ? 0.5 : srgbLuminance(c);
}

/**
 * Legible text color (near-black or white) for the given fill. The unparsed
 * fallback is written out here rather than calling `luminance`: measured, this
 * is the form that keeps the base, draw and chart-only bundles from growing.
 */
export function contrastText(bg: string): string {
  const c = parseColor(bg);
  return (c !== null ? srgbLuminance(c) : 0.5) > 0.45 ? '#10131a' : '#ffffff';
}

const srgbLinear = (v: number): number => {
  const s = v / 255;
  return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
};

/**
 * Relative luminance (0 black, 1 white) of parsed channels on the sRGB curve.
 * Code that needs it imports this by path instead of keeping a copy: two
 * copies of the curve can disagree at its threshold, and the widget's tokens
 * already feed this one from their own parser. The parsers stay separate on
 * purpose, since the widget's also reads space-separated `rgb()` and the two
 * disagree on malformed input, so sharing one would move a colour on one side
 * or the other.
 */
export function srgbLuminance(c: Rgba): number {
  return 0.2126 * srgbLinear(c.r) + 0.7152 * srgbLinear(c.g) + 0.0722 * srgbLinear(c.b);
}

/**
 * The color as rgba() with the given alpha (parse failure returns the input).
 * The canvas form, published as the package's `withAlpha`. The widget's
 * `withAlpha` is a different function on purpose: it writes token values.
 */
export function withAlpha(color: string, alpha: number): string {
  const c = parseColor(color);
  if (c === null) return color;
  return `rgba(${c.r},${c.g},${c.b},${alpha})`;
}

/**
 * Whether a supported color is fully transparent.
 *
 * An unparseable string is NOT invisible. An opaque named color, a `color-mix()`,
 * a custom property: `parseColor` returns null for all of them, and treating
 * null as "draws nothing" would quietly hide whatever the caller guards with
 * this. Erring the other way only ever leaves something visible.
 */
export function isInvisible(color: string): boolean {
  if (color.trim().toLowerCase() === 'transparent') return true;
  const c = parseColor(color);
  return c !== null && c.a <= 0;
}

/** Mix a color toward white (t>0) or black (t<0) by |t| (0..1): hover states. */
export function shade(color: string, t: number): string {
  const c = parseColor(color);
  if (c === null) return color;
  const to = t >= 0 ? 255 : 0;
  const k = Math.min(1, Math.abs(t));
  const ch = (v: number): number => Math.round(v + (to - v) * k);
  return `rgba(${ch(c.r)},${ch(c.g)},${ch(c.b)},${c.a})`;
}

/**
 * Trace a rounded-rectangle path (uses native roundRect when available, plain
 * rect otherwise, e.g. recording contexts in tests). Caller begins/fills.
 */
export function roundRectPath(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number): void {
  const rr = (ctx as CanvasRenderingContext2D & { roundRect?: (x: number, y: number, w: number, h: number, r: number) => void }).roundRect;
  if (typeof rr === 'function') rr.call(ctx, x, y, w, h, Math.max(0, Math.min(r, w / 2, h / 2)));
  else ctx.rect(x, y, w, h);
}

interface PillStyle {
  fill: string;
  text: string;
  /** Optional 1px border color. */
  border?: string;
  /** Corner radius in device px. */
  radius: number;
  /** Opaque under-fill so chart lines don't bleed through a translucent pill. */
  backplate?: string | undefined;
}

/** Filled rounded pill with centered-baseline text; returns the pill width. */
export function drawPill(
  ctx: CanvasRenderingContext2D,
  x: number,
  yCenter: number,
  label: string,
  height: number,
  padX: number,
  style: PillStyle,
): number {
  const w = ctx.measureText(label).width + padX * 2;
  ctx.beginPath();
  roundRectPath(ctx, x, yCenter - height / 2, w, height, style.radius);
  if (style.backplate !== undefined) {
    ctx.fillStyle = style.backplate;
    ctx.fill();
  }
  ctx.fillStyle = style.fill;
  ctx.fill();
  if (style.border !== undefined) {
    ctx.strokeStyle = style.border;
    ctx.lineWidth = 1;
    ctx.stroke();
  }
  ctx.fillStyle = style.text;
  ctx.textAlign = 'left';
  ctx.textBaseline = 'middle';
  ctx.fillText(label, x + padX, yCenter);
  return w;
}

/** Width of a close segment in media px. */
const CLOSE_SEGMENT_W = 20;

/** One segment of a broker-style pill group: text box or close box. */
export interface PillSegment {
  /** Text content; omit for a close segment. */
  text?: string;
  /** Render the close cross instead of text. */
  close?: boolean;
  fill: string;
  textColor: string;
  border?: string;
}

interface PillGroupMetrics {
  /** Group left edge, media px. */
  x0: number;
  /** Group right edge, media px. */
  x1: number;
  /** Left edge of the close segment (Infinity when none), media px. */
  closeX0: number;
}

/**
 * Draw a segmented pill group ([badge][qty][label][close]) with an opaque
 * backplate behind the whole group (so the chart line doesn't bleed through
 * the segment gaps). Coordinates are device px; the returned metrics are
 * media px, ready for hit-testing. The caller sets the font beforehand.
 */
export function drawPillGroup(
  ctx: CanvasRenderingContext2D,
  x: number,
  yCenter: number,
  segments: readonly PillSegment[],
  opts: { height: number; padX: number; radius: number; gap: number; backplate?: string | undefined; dpr: number },
): PillGroupMetrics {
  const { height, padX, radius, gap, dpr } = opts;
  const widths = segments.map((s) => (s.close === true ? CLOSE_SEGMENT_W * dpr : ctx.measureText(s.text ?? '').width + padX * 2));
  const total = widths.reduce((a, b) => a + b, 0) + gap * Math.max(0, segments.length - 1);
  if (opts.backplate !== undefined) {
    ctx.beginPath();
    roundRectPath(ctx, x, yCenter - height / 2, total, height, radius);
    ctx.fillStyle = opts.backplate;
    ctx.fill();
  }
  let closeX0 = Number.POSITIVE_INFINITY;
  let cx = x;
  for (let i = 0; i < segments.length; i++) {
    const s = segments[i]!;
    const w = widths[i]!; // widths maps segments, so both hold i
    ctx.beginPath();
    roundRectPath(ctx, cx, yCenter - height / 2, w, height, radius);
    ctx.fillStyle = s.fill;
    ctx.fill();
    if (s.border !== undefined) {
      ctx.strokeStyle = s.border;
      ctx.lineWidth = Math.max(1, Math.round(dpr));
      ctx.stroke();
    }
    if (s.close === true) {
      closeX0 = cx;
      ctx.strokeStyle = s.textColor;
      ctx.lineWidth = Math.max(1, Math.round(1.4 * dpr));
      const mx = cx + w / 2;
      const p = 3.5 * dpr;
      ctx.beginPath();
      ctx.moveTo(mx - p, yCenter - p); ctx.lineTo(mx + p, yCenter + p);
      ctx.moveTo(mx + p, yCenter - p); ctx.lineTo(mx - p, yCenter + p);
      ctx.stroke();
    } else {
      ctx.fillStyle = s.textColor;
      ctx.textAlign = 'left';
      ctx.textBaseline = 'middle';
      ctx.fillText(s.text ?? '', cx + padX, yCenter);
    }
    cx += w + gap;
  }
  return { x0: x / dpr, x1: (cx - gap) / dpr, closeX0: closeX0 / dpr };
}

