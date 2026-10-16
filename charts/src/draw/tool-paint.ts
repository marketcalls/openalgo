/**
 * What the built-in tool families paint with: stroke and fill, the text face,
 * readout plates and chips, number formats, the direction tints, and the text
 * layout a shape label and the text tool share. Internal to the tier.
 */
import type { PrimitiveRenderContext } from 'openalgo-charts';
import type { AnchoredTool, DrawContext, Drawing, DrawingText, ScreenPoint } from './types';
import { rectOf } from './geometry';
import { roundRectPath, contrastText } from '../render/pill';
// The one dash table, which series lines and study drawings read too: a pure function, by path.
import { dashFor } from '../render/line';
import type { SettingsField } from './schema';
import { drawingTextWidth } from './text-metrics';

/** A translucent tool's one opacity (highlighter ink, a measure's band). */
export const OPACITY_FIELD: SettingsField = {
  path: 'style.fillOpacity', label: 'Opacity', kind: 'opacity', min: 0, max: 1, step: 0.01, group: 'fill',
};

// ── shared drawing helpers ────────────────────────────────────────────────

/** A stroke's width in device px: whole pixels, and never under one. */
export const strokeWidth = (width: number, d: number): number => Math.max(1, Math.round(width * d));

/** A point in data space on the pane's plot, in media px. */
export function projectPoint(rc: PrimitiveRenderContext, p: { time: number; price: number }): ScreenPoint {
  return { x: rc.timeScale.indexToX(rc.dataLayer.timeToIndexFloat(p.time)), y: rc.priceScale.priceToY(p.price) };
}

export function applyStroke(c: DrawContext): void {
  const { ctx, rc, style } = c;
  const d = rc.dpr;
  ctx.strokeStyle = style.color;
  ctx.lineWidth = strokeWidth(style.lineWidth, d);
  ctx.lineJoin = 'round';
  ctx.lineCap = 'round';
  ctx.setLineDash(dashFor(style.lineStyle, d));
}

export function fillStyleOf(c: DrawContext): string {
  return c.style.fillColor ?? c.style.color;
}

export function withFill(c: DrawContext, paint: () => void): void {
  if (c.style.fill !== true) return;
  const { ctx } = c;
  ctx.save();
  ctx.globalAlpha = c.style.fillOpacity ?? 0.12;
  ctx.fillStyle = fillStyleOf(c);
  paint();
  ctx.restore();
}

// ── text ──────────────────────────────────────────────────────────────────

const DEFAULT_FONT = 'ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, sans-serif';
const NO_TEXT: DrawingText = { value: '' };

/** The drawing's text block, or an empty one so every reader falls back per field. */
export function textOf(d: Drawing): DrawingText {
  return d.text ?? NO_TEXT;
}

/**
 * The CSS font shorthand for a text block at `sizePx`. `weight` overrides the
 * bold flag, for the one place (a table header) that wants a weight of its own.
 */
export function fontOf(t: DrawingText, sizePx: number, weight?: string): string {
  const w = weight ?? (t.bold === true ? '700' : '');
  const italic = t.italic === true ? 'italic ' : '';
  const family = t.fontFamily === undefined || t.fontFamily === '' ? DEFAULT_FONT : t.fontFamily;
  return `${italic}${w === '' ? '' : `${w} `}${sizePx}px ${family}`;
}

/**
 * The text a mark shows, with the tool's own fallback when there is none. An
 * annotation with no text is still a mark on the chart, and an empty plate
 * reads as a rendering bug rather than as a note waiting for content; worse,
 * it cannot be seen, so it cannot be found and deleted.
 */
export function contentOf(d: Drawing, fallback: string): string {
  const v = d.text?.value;
  return v === undefined || v === '' ? fallback : v;
}

/**
 * A readout on a plate of the pane background. `color` is the mark the text
 * belongs to (a level's colour); the text block's own colour wins over it,
 * and the drawing's colour is the last resort. `tint` washes the plate with a
 * direction colour, and `center` puts the plate about `x` instead of to its
 * right; both are for readouts that sit on the shape rather than beside it.
 */
export function label(
  c: DrawContext, text: string, x: number, y: number, color?: string,
  opts: { tint?: string; center?: boolean } = {},
): void {
  const { ctx, rc, style } = c;
  const t = textOf(c.drawing);
  const size = (t.fontSize ?? 11) * rc.dpr;
  ctx.save();
  ctx.setLineDash([]);
  ctx.font = fontOf(t, size);
  ctx.textBaseline = 'middle';
  ctx.textAlign = 'left';
  const w = drawingTextWidth(ctx, text);
  const left = opts.center === true ? x - w / 2 : x;
  ctx.globalAlpha = 0.85;
  ctx.fillStyle = rc.theme.background;
  ctx.fillRect(left - 2 * rc.dpr, y - size * 0.75, w + 4 * rc.dpr, size * 1.5);
  if (opts.tint !== undefined) {
    ctx.globalAlpha = 0.22;
    ctx.fillStyle = opts.tint;
    ctx.fillRect(left - 2 * rc.dpr, y - size * 0.75, w + 4 * rc.dpr, size * 1.5);
  }
  ctx.globalAlpha = 1;
  ctx.fillStyle = t.color ?? color ?? style.color;
  ctx.fillText(text, left, y);
  ctx.restore();
}

/**
 * A solid rounded chip with contrasting text, one row per line: the readout
 * style the position and forecast tools share. `align` positions the box
 * horizontally about `x`, `place` vertically about `y`. Returns its height so a
 * caller can stack chips.
 */
export function chip(
  c: DrawContext,
  lines: readonly string[],
  x: number,
  y: number,
  bg: string,
  opts: { align?: 'left' | 'center' | 'right'; place?: 'above' | 'below' | 'middle' } = {},
): number {
  const { ctx, rc } = c;
  const d = rc.dpr;
  const t = textOf(c.drawing);
  const size = (t.fontSize ?? 11) * d;
  ctx.save();
  ctx.setLineDash([]);
  ctx.globalAlpha = 1;
  ctx.font = fontOf(t, size);
  ctx.textBaseline = 'middle';
  ctx.textAlign = 'left';
  const padX = 5 * d;
  const padY = 3 * d;
  const lh = size * 1.35;
  let textW = 0;
  for (const s of lines) textW = Math.max(textW, drawingTextWidth(ctx, s));
  const w = textW + padX * 2;
  const h = lh * lines.length + padY * 2;
  const align = opts.align ?? 'left';
  const bx = align === 'center' ? x - w / 2 : align === 'right' ? x - w : x;
  const place = opts.place ?? 'above';
  const by = place === 'above' ? y - h - 4 * d : place === 'below' ? y + 4 * d : y - h / 2;
  ctx.beginPath();
  roundRectPath(ctx, bx, by, w, h, 3 * d);
  ctx.fillStyle = bg;
  ctx.fill();
  ctx.fillStyle = t.color ?? contrastText(bg);
  for (let i = 0; i < lines.length; i++) ctx.fillText(lines[i]!, bx + padX, by + padY + lh * (i + 0.5)); // i is in range
  ctx.restore();
  return h;
}

/** Thousands-separated fixed-point, locale-independent so output is stable. */
export function grouped(n: number, dp = 0): string {
  const [i, f] = Math.abs(n).toFixed(dp).split('.'); // a split has a first part
  const sign = n < 0 ? '-' : '';
  return sign + i!.replace(/\B(?=(\d{3})+(?!\d))/g, ',') + (f === undefined ? '' : '.' + f);
}

/** Filled arrowhead at `b`, pointing away from `a`. Scales with line width. */
export function arrowHead(c: DrawContext, a: ScreenPoint, b: ScreenPoint): void {
  const head = Math.max(8, c.style.lineWidth * 5) * c.rc.dpr;
  const ang = Math.atan2(b.y - a.y, b.x - a.x);
  c.ctx.beginPath();
  c.ctx.moveTo(b.x, b.y);
  c.ctx.lineTo(b.x - head * Math.cos(ang - 0.4), b.y - head * Math.sin(ang - 0.4));
  c.ctx.lineTo(b.x - head * Math.cos(ang + 0.4), b.y - head * Math.sin(ang + 0.4));
  c.ctx.closePath();
  c.ctx.fillStyle = c.style.color;
  c.ctx.fill();
}

/**
 * The rising or the falling colour: the theme's own up and down colours, so a
 * measure or a position zone reads the same as the candles beside it.
 */
export const tintOf = (c: DrawContext, up: boolean): string => (up ? c.rc.theme.upColor : c.rc.theme.downColor);

/** A check passed or failed: a harmonic pattern's ratios, a forecast's verdict. */
export const VALID_COLOR = '#16a34a';
export const INVALID_COLOR = '#dc2626';

// ── text layout ───────────────────────────────────────────────────────────

export const TEXT_PAD = 5;
export const LINE_GAP = 1.35;
/** The text tool's size when the block sets none. */
export const TEXT_SIZE = 14;

/**
 * Split into rendered lines: honour explicit `\n` always, and soft-wrap each
 * paragraph at `maxWidth` when `wrap` is on. Measured with the *live* context
 * so the wrap matches the font actually being drawn.
 */
function textLines(ctx: CanvasRenderingContext2D, t: DrawingText, value: string, maxWidth: number): string[] {
  const paragraphs = value.split('\n');
  if (t.wrap !== true) return paragraphs;
  const out: string[] = [];
  for (const para of paragraphs) {
    const words = para.split(/\s+/).filter((w) => w !== '');
    if (words.length === 0) { out.push(''); continue; }
    let line = words[0]!; // not empty, and every i below is in range
    for (let i = 1; i < words.length; i++) {
      const next = `${line} ${words[i]!}`;
      if (ctx.measureText(next).width > maxWidth) { out.push(line); line = words[i]!; }
      else line = next;
    }
    out.push(line);
  }
  return out;
}

/** Measured box of a text drawing, in the context's px, anchored at its top-left. */
export function textBox(
  ctx: CanvasRenderingContext2D,
  t: DrawingText,
  value: string,
  dpr: number,
): { lines: string[]; width: number; height: number; lineHeight: number } {
  const size = (t.fontSize ?? TEXT_SIZE) * dpr;
  ctx.font = fontOf(t, size);
  const maxWidth = (t.wrapWidth ?? 220) * dpr;
  const lines = textLines(ctx, t, value, maxWidth);
  let width = 0;
  for (const l of lines) width = Math.max(width, ctx.measureText(l).width);
  const lineHeight = size * LINE_GAP;
  return {
    lines,
    width: width + TEXT_PAD * 2 * dpr,
    height: lines.length * lineHeight + TEXT_PAD * 2 * dpr,
    lineHeight,
  };
}

/**
 * Draw a shape's attached label. Shapes carry an optional text block that
 * renders inside (or just above) their bounds, with its own colour, font and
 * alignment: the outline colour and the label colour are different decisions.
 * `align` and `valign` are the shape's own defaults for when the block sets
 * neither; a rectangle labels its corner, an ellipse its middle.
 */
export function shapeLabel(
  c: DrawContext,
  r: Box,
  align: LabelAlign = 'left',
  valign: LabelValign = 'top',
): void {
  const { ctx, rc, style } = c;
  const t = textOf(c.drawing);
  if (t.value === '') return;
  ctx.save();
  ctx.setLineDash([]);
  const at = labelLayout(ctx, t, r, rc.dpr, align, valign);
  ctx.fillStyle = t.color ?? style.color;
  ctx.textBaseline = 'top';
  ctx.textAlign = at.align;
  let ty = at.y;
  for (const line of at.lines) {
    ctx.fillText(line, at.x, ty);
    ty += at.lineHeight;
  }
  ctx.restore();
}

type Box = { x0: number; y0: number; x1: number; y1: number };
type LabelAlign = 'left' | 'center' | 'right';
type LabelValign = 'top' | 'middle' | 'bottom';

/**
 * Where a shape's label goes in `r`: its lines, the x they align on and the
 * block's top, in the px of `r` at ratio `d`. Painting and `shapeBounds` both
 * read it, so the box a pinned shape keeps on screen is the label it paints.
 * With no context it measures nothing and wraps nothing.
 */
function labelLayout(
  ctx: CanvasRenderingContext2D | null, t: DrawingText, r: Box, d: number, align: LabelAlign, valign: LabelValign,
): { lines: string[]; align: LabelAlign; x: number; y: number; lineHeight: number; height: number } {
  const size = (t.fontSize ?? TEXT_SIZE) * d;
  const pad = 6 * d;
  // A shape's label wraps to the shape, not to a width of its own.
  if (ctx !== null) ctx.font = fontOf(t, size);
  const lines = ctx === null ? t.value.split('\n') : textLines(ctx, t, t.value, Math.max(20 * d, r.x1 - r.x0 - pad * 2));
  const lineHeight = size * LINE_GAP;
  const height = lines.length * lineHeight;
  const a = t.align ?? align;
  const x = a === 'center' ? (r.x0 + r.x1) / 2 : a === 'right' ? r.x1 - pad : r.x0 + pad;
  // `outside` lifts the block clear of the shape so it never sits on the outline.
  const v = t.valign ?? valign;
  const y = t.position === 'outside' ? r.y0 - height - pad
    : v === 'middle' ? (r.y0 + r.y1 - height) / 2
    : v === 'bottom' ? r.y1 - height - pad
    : r.y0 + pad;
  return { lines, align: a, x, y, lineHeight, height };
}

/**
 * A two-anchor shape's box with its label in it. An `outside` label sits above
 * the shape and a long one runs past its sides, so a shape pinned to the
 * screen with only its outline kept on the plot could lose its label off the
 * top edge.
 */
export function shapeBounds(align: LabelAlign, valign: LabelValign): NonNullable<AnchoredTool<2, true>['bounds']> {
  return (pts, drawing) => {
    const r = rectOf(pts[0], pts[1]);
    const t = textOf(drawing);
    if (t.value === '') return r;
    const probe = measureContext();
    const at = labelLayout(probe, t, r, 1, align, valign);
    let w = 0;
    for (const l of at.lines) w = Math.max(w, probe === null ? l.length * (t.fontSize ?? TEXT_SIZE) * 0.6 : probe.measureText(l).width);
    const x0 = at.align === 'center' ? at.x - w / 2 : at.align === 'right' ? at.x - w : at.x;
    return { x0: Math.min(r.x0, x0), y0: Math.min(r.y0, at.y), x1: Math.max(r.x1, x0 + w), y1: Math.max(r.y1, at.y + at.height) };
  };
}

/** A 1x1 offscreen context used only for text measurement. Cached. */
let _probe: CanvasRenderingContext2D | null | undefined;
export function measureContext(): CanvasRenderingContext2D | null {
  if (_probe !== undefined) return _probe;
  try {
    _probe = (typeof document === 'undefined' ? null : document.createElement('canvas').getContext('2d'));
  } catch {
    _probe = null;
  }
  return _probe;
}
