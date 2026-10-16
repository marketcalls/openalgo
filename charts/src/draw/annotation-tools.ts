/**
 * Annotations: the text tool, the price label, callout and flag, the plate
 * notes (note, balloon, comment, signpost, price note), the table and the
 * arrow marks. Every one of them puts a human sentence, or a mark pointing at
 * a bar, on the chart.
 */
import type { PrimitiveRenderContext } from 'openalgo-charts';
import type { AnchoredTool, DrawContext, Drawing, DrawingText, DrawingTool, ScreenPoint } from './types';
import { distToSegment } from './geometry';
import { roundRectPath, contrastText } from '../render/pill';
import {
  type SettingsSchema,
  LINE_FIELDS, FILL_FIELDS, TEXT_FIELDS, FONT_FIELDS, PLATE_TEXT_FIELDS,
  COLOR_FIELD, LINE_WIDTH_FIELD, TEXT_VALUE_FIELD, SPACE_FIELD,
  composeSettings,
} from './schema';
import { drawingTextWidth } from './text-metrics';
import {
  applyStroke, fillStyleOf, textOf, fontOf, contentOf, textBox, measureContext, TEXT_PAD, LINE_GAP, TEXT_SIZE,
} from './tool-paint';

export const TEXT: DrawingTool = {
  // A box of text measured from its own anchor, so it is the note that can be
  // pinned to the screen. The pinned annotations (note, balloon, signpost)
  // point at a bar, which a fixed place on screen would contradict.
  id: 'text', name: 'Text', points: 1, viewport: true,
  defaultText: { value: 'Text', fontSize: TEXT_SIZE },
  settings: composeSettings([TEXT_FIELDS, SPACE_FIELD], { textIsContent: true }),
  draw: (c) => {
    const { ctx, rc, style } = c;
    const d = rc.dpr;
    const t = textOf(c.drawing);
    const box = textBox(ctx, t, contentOf(c.drawing, 'Text'), d);
    const x = c.pts[0].x;
    // The anchor is the box's top, middle or bottom edge: `bottom` is how a
    // note sits above a bar instead of covering it.
    const v = t.valign ?? 'top';
    const y = v === 'middle' ? c.pts[0].y - box.height / 2
      : v === 'bottom' ? c.pts[0].y - box.height
      : c.pts[0].y;

    ctx.save();
    ctx.setLineDash([]);
    if (t.background === true) {
      ctx.globalAlpha = t.backgroundOpacity ?? 1;
      ctx.fillStyle = t.backgroundColor ?? rc.theme.background;
      ctx.beginPath();
      ctx.roundRect(x, y, box.width, box.height, 4 * d);
      ctx.fill();
      ctx.globalAlpha = 1;
    }
    if (t.border === true) {
      ctx.strokeStyle = t.borderColor ?? style.color;
      ctx.lineWidth = Math.max(1, style.lineWidth * d);
      ctx.beginPath();
      ctx.roundRect(x, y, box.width, box.height, 4 * d);
      ctx.stroke();
    }

    ctx.font = fontOf(t, (t.fontSize ?? TEXT_SIZE) * d);
    ctx.fillStyle = t.color ?? style.color;
    ctx.textBaseline = 'top';
    const align = t.align ?? 'left';
    ctx.textAlign = align;
    const tx = align === 'center' ? x + box.width / 2
      : align === 'right' ? x + box.width - TEXT_PAD * d
      : x + TEXT_PAD * d;
    let ty = y + TEXT_PAD * d;
    for (const line of box.lines) {
      ctx.fillText(line, tx, ty);
      ty += box.lineHeight;
    }
    ctx.restore();
  },
  distance: (x, y, h) => {
    const r = textRect(h.pts[0], h.drawing);
    return x >= r.x0 - 3 && x <= r.x1 + 3 && y >= r.y0 - 3 && y <= r.y1 + 3 ? 0 : null;
  },
  // The box it is grabbed by is the box a pinned note keeps on screen.
  bounds: (pts, drawing) => textRect(pts[0], drawing),
} satisfies AnchoredTool<1, true>;

/**
 * The text tool's box in media px from its anchor. Measured with a throwaway
 * 2D context so it matches what is drawn (wrapping and font metrics decide the
 * real size, not a character count).
 */
function textRect(p: ScreenPoint, drawing: Drawing): { x0: number; y0: number; x1: number; y1: number } {
  const t = textOf(drawing);
  const value = contentOf(drawing, 'Text');
  const size = t.fontSize ?? TEXT_SIZE;
  const probe = measureContext();
  const box = probe === null
    ? { width: value.length * size * 0.6 + 10, height: size * LINE_GAP + 10 }
    : textBox(probe, t, value, 1);
  const v = t.valign ?? 'top';
  const top = v === 'middle' ? p.y - box.height / 2 : v === 'bottom' ? p.y - box.height : p.y;
  return { x0: p.x, y0: top, x1: p.x + box.width, y1: top + box.height };
}

// ── notes & marks ─────────────────────────────────────────────────────────

/** The bubble marks share a colour, their content and a face; nothing else applies. */
const BUBBLE_SETTINGS: SettingsSchema = composeSettings([COLOR_FIELD, TEXT_VALUE_FIELD, FONT_FIELDS], { textIsContent: true });

/**
 * Price label: a pill of the anchored price with a tail pointing at the bar.
 * Reads its value off the anchor, so dragging it re-reads rather than going
 * stale the way a typed-in text would. Text, when given, replaces the price.
 */
export const PRICE_LABEL: DrawingTool = {
  id: 'price-label', name: 'Price Label', points: 1,
  settings: composeSettings([COLOR_FIELD, { ...TEXT_VALUE_FIELD, label: 'Text (blank shows the price)' }, FONT_FIELDS]),
  draw: (c) => {
    const p = c.pts[0];
    const d = c.rc.dpr;
    const text = contentOf(c.drawing, c.formatPrice(c.drawing.points[0].price));
    const box = calloutBox(c, [text], p.x + 18 * d, p.y - 30 * d, 12);
    calloutTail(c, box, p, c.style.color);
    calloutText(c, box, [text], c.style.color, 12);
  },
  distance: (x, y, h) => reached(x, y, priceLabelReach(h.pts[0], h.drawing, h.rc)),
} satisfies AnchoredTool<1>;

/**
 * Where the price label is grabbed, in media px: its pill, centred up and to
 * the right of the anchor as `calloutBox` paints it (see `hitBubble`), and
 * the anchor itself.
 */
function priceLabelReach(p: ScreenPoint, d: Drawing, rc: PrimitiveRenderContext): Reach {
  // A price label is drawn only once it holds its anchor.
  const text = contentOf(d, rc.priceScale.format(d.points[0]!.price));
  return { plate: hitBubble(d, [text], p.x + 18, p.y - 30, 50), dot: { at: p, r: 10 } };
}

/**
 * Callout: a text bubble on its own anchor with a tail back to the point it
 * annotates, so the note can sit clear of the price action it refers to.
 */
export const CALLOUT: DrawingTool = {
  id: 'callout', name: 'Callout', points: 2,
  defaultText: { value: 'Note', fontSize: 12 },
  settings: BUBBLE_SETTINGS,
  draw: (c) => {
    if (c.pts.length < 2) return;
    const [target, seat] = c.pts;
    const lines = contentOf(c.drawing, 'Note').split('\n');
    const box = calloutBox(c, lines, seat.x, seat.y, 12);
    calloutTail(c, box, target, c.style.color);
    calloutText(c, box, lines, c.style.color, 12);
  },
  distance: (x, y, h) => {
    if (h.pts.length < 2) return null;
    const [target, seat] = h.pts;
    // Bubble body, else the tail back to the annotated point.
    const b = calloutReach(seat, h.drawing);
    if (insidePlate(x, y, b.x, b.y, b.w, b.h) !== null) return 0;
    return distToSegment(x, y, target, seat);
  },
} satisfies AnchoredTool<2>;

/** The callout's bubble as a hit test grabs it, in media px; see `hitBubble`. */
function calloutReach(seat: ScreenPoint, d: Drawing): Plate {
  return hitBubble(d, contentOf(d, 'Note').split('\n'), seat.x, seat.y, 106);
}

/** Rounded bubble at (x, y) sized to `lines`; returns its device-px box. */
function calloutBox(
  c: DrawContext, lines: readonly string[], x: number, y: number, defaultSize: number,
): { x: number; y: number; w: number; h: number } {
  const d = c.rc.dpr;
  const t = textOf(c.drawing);
  const size = (t.fontSize ?? defaultSize) * d;
  const w = widest(c.ctx, t, lines, size) + 14 * d;
  const h = size * 1.4 * lines.length + 8 * d;
  return { x: x - w / 2, y: y - h / 2, w, h };
}

/**
 * A bubble centred at (x, y) as a hit test grabs it, in media px: measured as
 * `calloutBox` paints it when a canvas can be made (`measureContext`), else on
 * `guess`, a text width generous enough that a short bubble is grabbable.
 */
function hitBubble(d: Drawing, lines: readonly string[], x: number, y: number, guess: number): Plate {
  const t = textOf(d);
  const size = t.fontSize ?? 12;
  const probe = measureContext();
  const w = (probe === null ? guess : widest(probe, t, lines, size)) + 14;
  const h = size * 1.4 * lines.length + 8;
  return { x: x - w / 2, y: y - h / 2, w, h };
}

/** Bubble fill plus the tail from it to `tip`. */
function calloutTail(
  c: DrawContext, box: { x: number; y: number; w: number; h: number }, tip: ScreenPoint, color: string,
): void {
  const d = c.rc.dpr;
  const cx = box.x + box.w / 2;
  const cy = box.y + box.h / 2;
  const ang = Math.atan2(tip.y - cy, tip.x - cx);
  // Two base points either side of the bubble-to-tip direction, so the tail
  // always leaves from the edge facing the point it annotates.
  const base = 5 * d;
  const bx = cx + Math.cos(ang) * (box.w / 2 - base);
  const by = cy + Math.sin(ang) * (box.h / 2 - base);
  c.ctx.save();
  c.ctx.setLineDash([]);
  c.ctx.fillStyle = color;
  c.ctx.beginPath();
  c.ctx.moveTo(tip.x, tip.y);
  c.ctx.lineTo(bx - Math.sin(ang) * base, by + Math.cos(ang) * base);
  c.ctx.lineTo(bx + Math.sin(ang) * base, by - Math.cos(ang) * base);
  c.ctx.closePath();
  c.ctx.fill();
  c.ctx.beginPath();
  roundRectPath(c.ctx, box.x, box.y, box.w, box.h, 5 * d);
  c.ctx.fill();
  // Anchor dot, so the exact bar being annotated stays visible.
  c.ctx.beginPath();
  c.ctx.arc(tip.x, tip.y, 2.5 * d, 0, Math.PI * 2);
  c.ctx.fill();
  c.ctx.restore();
}

/** Bubble text, centred, in the block's colour or the one that contrasts with the bubble. */
function calloutText(
  c: DrawContext, box: { x: number; y: number; w: number; h: number },
  lines: readonly string[], color: string, defaultSize: number,
): void {
  const d = c.rc.dpr;
  const t = textOf(c.drawing);
  const size = (t.fontSize ?? defaultSize) * d;
  c.ctx.save();
  c.ctx.setLineDash([]);
  c.ctx.font = fontOf(t, size);
  c.ctx.textAlign = 'center';
  c.ctx.textBaseline = 'middle';
  c.ctx.fillStyle = t.color ?? contrastText(color);
  const lh = size * 1.4;
  const top = box.y + box.h / 2 - (lh * (lines.length - 1)) / 2;
  for (let i = 0; i < lines.length; i++) c.ctx.fillText(lines[i]!, box.x + box.w / 2, top + lh * i); // i is in range
  c.ctx.restore();
}

/** A one-anchor glyph: outline plus an optional fill, nothing else applies. */
const MARK_SETTINGS: SettingsSchema = composeSettings([LINE_FIELDS, FILL_FIELDS]);

/** Flag mark: a pennant on a pole at one anchor, for tagging a bar. */
export const FLAG_MARK: DrawingTool = {
  id: 'flag-mark', name: 'Flag Mark', points: 1,
  defaultStyle: { fill: true, fillOpacity: 0.95 },
  settings: MARK_SETTINGS,
  draw: (c) => {
    const p = c.pts[0];
    const d = c.rc.dpr;
    const pole = 22 * d;
    const flagW = 15 * d;
    const flagH = 11 * d;
    applyStroke(c);
    c.ctx.beginPath();
    c.ctx.moveTo(p.x, p.y);
    c.ctx.lineTo(p.x, p.y - pole);
    c.ctx.stroke();
    c.ctx.setLineDash([]);
    // Pennant off the top of the pole, notched on its trailing edge.
    c.ctx.beginPath();
    c.ctx.moveTo(p.x, p.y - pole);
    c.ctx.lineTo(p.x + flagW, p.y - pole + flagH * 0.28);
    c.ctx.lineTo(p.x + flagW * 0.72, p.y - pole + flagH * 0.5);
    c.ctx.lineTo(p.x + flagW, p.y - pole + flagH * 0.72);
    c.ctx.lineTo(p.x, p.y - pole + flagH);
    c.ctx.closePath();
    // The pennant is filled unless asked not to be: an outlined flag is a
    // legitimate, quieter mark.
    if (c.style.fill !== false) {
      c.ctx.save();
      c.ctx.globalAlpha = c.style.fillOpacity ?? 0.95;
      c.ctx.fillStyle = fillStyleOf(c);
      c.ctx.fill();
      c.ctx.restore();
    }
    c.ctx.stroke();
  },
  distance: (x, y, h) => {
    const p = h.pts[0];
    // Pole plus the pennant box hanging off its top.
    if (x >= p.x - 4 && x <= p.x + 16 && y >= p.y - 24 && y <= p.y + 2) return 0;
    return Math.hypot(x - p.x, y - p.y) <= 8 ? 0 : null;
  },
} satisfies AnchoredTool<1>;


/* ── annotations ───────────────────────────────────────────────────────────
 * Tools whose whole job is to put a human sentence on the chart. They share
 * the plate-and-tail machinery the callout already had, because a note, a
 * balloon and a comment differ in where the tail leaves the plate and how the
 * plate is shaped, not in anything structural.
 */

/** A box by its top-left and size. */
type Plate = { x: number; y: number; w: number; h: number };

/**
 * An annotation's plate: its face when the text block sets nothing, and where
 * it sits. One statement for painting and for hit testing, so the plate that
 * is grabbed is the plate that is painted.
 */
interface PlateDefaults {
  /** Font size in media px. */
  size: number;
  /** Plate opacity, 0..1. */
  opacity: number;
  /** What the plate says when the text block is empty. */
  fallback: string;
  /** The anchored price, formatted, is the plate's first line. */
  price?: true;
  /**
   * The plate's top-left for a plate `w` by `h` at the anchor `p`, in the px
   * of ratio `d`: device px to paint, media px (`d` 1) to hit-test.
   */
  at(p: ScreenPoint, w: number, h: number, d: number): ScreenPoint;
  /** The post a hit also takes, in media px; without one, a dot of 8 px about the anchor. */
  post?(p: ScreenPoint): Plate;
}

/** Where an annotation is grabbed, in media px: its plate, and a dot or a post at its anchor. */
interface Reach { plate: Plate; dot?: { at: ScreenPoint; r: number }; post?: Plate }

/**
 * The widest of `lines` in `t`'s face at `sizePx`, measured on `ctx`: the
 * context being painted, or the offscreen probe, which answers in media px.
 */
function widest(ctx: CanvasRenderingContext2D, t: DrawingText, lines: readonly string[], sizePx: number): number {
  ctx.save();
  ctx.font = fontOf(t, sizePx);
  let w = 0;
  for (const s of lines) w = Math.max(w, ctx.measureText(s).width);
  ctx.restore();
  return w;
}

/** The plate's lines: the price first where it shows one, then the text or its fallback. */
function plateLines(def: PlateDefaults, d: Drawing, format: (price: number) => string): string[] {
  const text = contentOf(d, def.fallback).split('\n');
  // A price plate is drawn only once the drawing holds its anchor.
  return def.price === true ? [format(d.points[0]!.price), ...text] : text;
}

/**
 * The plate as painted, in device px: sized to `lines` in the text block's
 * face and placed by `def`.
 *
 * Placed by a corner, not centred on a point as `calloutBox` is: an annotation
 * that grows downward from where it was dropped stays where the user put it
 * as the text is typed, while a centred one creeps upward a half-line at a time.
 */
function notePlate(c: DrawContext, p: ScreenPoint, lines: readonly string[], def: PlateDefaults): Plate {
  const d = c.rc.dpr;
  const size = (textOf(c.drawing).fontSize ?? def.size) * d;
  const w = widest(c.ctx, textOf(c.drawing), lines, size) + 16 * d;
  const h = size * 1.45 * lines.length + 10 * d;
  return { ...def.at(p, w, h, d), w, h };
}

/**
 * Where a plate annotation is grabbed, in media px. The plate is measured as
 * `notePlate` paints it when a canvas can be made (`measureContext`); where
 * none can, it is taken as 120 px wide, generous enough that a short plate is
 * always grabbable, and the dot or post at the anchor catches the rest.
 */
function plateReach(def: PlateDefaults, p: ScreenPoint, d: Drawing, rc: PrimitiveRenderContext): Reach {
  const t = textOf(d);
  const size = t.fontSize ?? def.size;
  const lines = plateLines(def, d, (price) => rc.priceScale.format(price));
  const probe = measureContext();
  const w = probe === null ? 120 : widest(probe, t, lines, size) + 16;
  const h = size * 1.45 * lines.length + 10;
  const plate = { ...def.at(p, w, h, 1), w, h };
  return def.post === undefined ? { plate, dot: { at: p, r: 8 } } : { plate, post: def.post(p) };
}

/** Whether (x, y) is on what `r` reaches: 0 when it is, as for anywhere on a plate, else null. */
function reached(x: number, y: number, r: Reach): 0 | null {
  const { plate, dot, post } = r;
  if (insidePlate(x, y, plate.x, plate.y, plate.w, plate.h) !== null) return 0;
  if (dot !== undefined) return Math.hypot(x - dot.at.x, y - dot.at.y) <= dot.r ? 0 : null;
  return post !== undefined && insidePlate(x, y, post.x, post.y, post.w, post.h) !== null ? 0 : null;
}

/** The plate's colour: the text block's own, else the drawing's. */
function plateColor(c: DrawContext): string {
  return c.drawing.text?.backgroundColor ?? c.style.color;
}

/** Fill the plate, stroke its border, and lay the lines inside it. */
function paintPlate(
  c: DrawContext,
  box: { x: number; y: number; w: number; h: number },
  lines: readonly string[],
  def: PlateDefaults,
  radius = 6,
): void {
  const d = c.rc.dpr;
  const t = textOf(c.drawing);
  const size = (t.fontSize ?? def.size) * d;
  const bg = plateColor(c);
  c.ctx.save();
  c.ctx.setLineDash([]);
  c.ctx.globalAlpha = t.backgroundOpacity ?? def.opacity;
  c.ctx.fillStyle = bg;
  c.ctx.beginPath();
  roundRectPath(c.ctx, box.x, box.y, box.w, box.h, radius * d);
  c.ctx.fill();
  c.ctx.globalAlpha = 1;
  if (t.border === true) {
    c.ctx.strokeStyle = t.borderColor ?? c.style.color;
    c.ctx.lineWidth = Math.max(1, c.style.lineWidth * d);
    c.ctx.stroke();
  }
  c.ctx.font = fontOf(t, size);
  c.ctx.textAlign = 'left';
  c.ctx.textBaseline = 'middle';
  c.ctx.fillStyle = t.color ?? contrastText(bg);
  const lh = size * 1.45;
  const top = box.y + box.h / 2 - (lh * (lines.length - 1)) / 2;
  for (let i = 0; i < lines.length; i++) {
    c.ctx.fillText(lines[i]!, box.x + 8 * d, top + lh * i); // i is in range
  }
  c.ctx.restore();
}

/** Inside the plate, in media px. Annotations are grabbable anywhere on them. */
function insidePlate(
  x: number, y: number, bx: number, by: number, w: number, h: number,
): number | null {
  return x >= bx && x <= bx + w && y >= by && y <= by + h ? 0 : null;
}

/** A plate on a stem: the stem's colour and width apply, and the plate's text surface. */
const STEMMED_NOTE_SETTINGS: SettingsSchema = composeSettings(
  [COLOR_FIELD, LINE_WIDTH_FIELD, PLATE_TEXT_FIELDS], { textIsContent: true },
);
/** A plate with a tail: only the colour applies outside the text surface. */
const TAILED_NOTE_SETTINGS: SettingsSchema = composeSettings([COLOR_FIELD, PLATE_TEXT_FIELDS], { textIsContent: true });

/** Up and to the right of the pin, where the stem meets its bottom-left corner. */
const NOTE_PLATE: PlateDefaults = {
  size: 12, opacity: 0.95, fallback: 'Note', at: (p, _w, _h, d) => ({ x: p.x + 16 * d, y: p.y - 34 * d }),
};

/**
 * Note: a pin at the bar with its text to the upper right.
 *
 * The pin is the point being annotated and the plate is the annotation, which
 * is why the two are drawn as separate marks joined by a stem rather than as
 * one bubble: the reader needs to see exactly which bar is meant, and a bubble
 * wide enough to hold a sentence covers several.
 */
export const NOTE: DrawingTool = {
  id: 'note', name: 'Note', points: 1,
  defaultText: { value: 'Note', fontSize: NOTE_PLATE.size },
  settings: STEMMED_NOTE_SETTINGS,
  draw: (c) => {
    const d = c.rc.dpr;
    const p = c.pts[0];
    const lines = plateLines(NOTE_PLATE, c.drawing, c.formatPrice);
    const box = notePlate(c, p, lines, NOTE_PLATE);
    c.ctx.save();
    c.ctx.setLineDash([]);
    c.ctx.strokeStyle = c.style.color;
    c.ctx.lineWidth = Math.max(1, c.style.lineWidth * d);
    c.ctx.beginPath();
    c.ctx.moveTo(p.x, p.y);
    c.ctx.lineTo(box.x, box.y + box.h);
    c.ctx.stroke();
    // The pin head, so the annotated bar stays identifiable at any zoom.
    c.ctx.fillStyle = c.style.color;
    c.ctx.beginPath();
    c.ctx.arc(p.x, p.y, 3.5 * d, 0, Math.PI * 2);
    c.ctx.fill();
    c.ctx.restore();
    paintPlate(c, box, lines, NOTE_PLATE);
  },
  distance: (x, y, h) => reached(x, y, plateReach(NOTE_PLATE, h.pts[0], h.drawing, h.rc)),
} satisfies AnchoredTool<1>;

/** Centred over the anchor, clear of the tail. */
const BALLOON_PLATE: PlateDefaults = {
  size: 12, opacity: 0.95, fallback: 'Balloon', at: (p, w, h, d) => ({ x: p.x - w / 2, y: p.y - h - 12 * d }),
};

/**
 * Balloon: a speech bubble sitting above its anchor, tail pointing down.
 *
 * One anchor rather than the callout's two: a balloon is for saying something
 * *about this bar*, so letting the bubble be dragged away from what it labels
 * would only invite it to drift.
 */
export const BALLOON: DrawingTool = {
  id: 'balloon', name: 'Balloon', points: 1,
  defaultText: { value: 'Balloon', fontSize: BALLOON_PLATE.size },
  settings: TAILED_NOTE_SETTINGS,
  draw: (c) => {
    const d = c.rc.dpr;
    const p = c.pts[0];
    const lines = plateLines(BALLOON_PLATE, c.drawing, c.formatPrice);
    const box = notePlate(c, p, lines, BALLOON_PLATE);
    c.ctx.save();
    c.ctx.setLineDash([]);
    c.ctx.globalAlpha = c.drawing.text?.backgroundOpacity ?? BALLOON_PLATE.opacity;
    c.ctx.fillStyle = plateColor(c);
    c.ctx.beginPath();
    c.ctx.moveTo(p.x, p.y);
    c.ctx.lineTo(p.x - 6 * d, box.y + box.h);
    c.ctx.lineTo(p.x + 6 * d, box.y + box.h);
    c.ctx.closePath();
    c.ctx.fill();
    c.ctx.restore();
    paintPlate(c, box, lines, BALLOON_PLATE, 8);
  },
  distance: (x, y, h) => reached(x, y, plateReach(BALLOON_PLATE, h.pts[0], h.drawing, h.rc)),
} satisfies AnchoredTool<1>;

/** Up and to the right of the anchor, the tail off its bottom-left corner. */
const COMMENT_PLATE: PlateDefaults = {
  size: 11, opacity: 0.92, fallback: 'Comment', at: (p, _w, h, d) => ({ x: p.x + 8 * d, y: p.y - h - 10 * d }),
};

/**
 * Comment: a small square-cornered box with a tail off its bottom left.
 *
 * Deliberately plainer than the balloon: a chart that says something at every
 * other bar needs one of these marks to be quiet, and the shape is the only
 * thing distinguishing them once both are the user's own colour.
 */
export const COMMENT: DrawingTool = {
  id: 'comment', name: 'Comment', points: 1,
  defaultText: { value: 'Comment', fontSize: COMMENT_PLATE.size },
  settings: TAILED_NOTE_SETTINGS,
  draw: (c) => {
    const d = c.rc.dpr;
    const p = c.pts[0];
    const lines = plateLines(COMMENT_PLATE, c.drawing, c.formatPrice);
    const box = notePlate(c, p, lines, COMMENT_PLATE);
    c.ctx.save();
    c.ctx.setLineDash([]);
    c.ctx.globalAlpha = c.drawing.text?.backgroundOpacity ?? COMMENT_PLATE.opacity;
    c.ctx.fillStyle = plateColor(c);
    c.ctx.beginPath();
    c.ctx.moveTo(p.x, p.y);
    c.ctx.lineTo(box.x, box.y + box.h - 5 * d);
    c.ctx.lineTo(box.x + 10 * d, box.y + box.h);
    c.ctx.closePath();
    c.ctx.fill();
    c.ctx.restore();
    paintPlate(c, box, lines, COMMENT_PLATE, 3);
  },
  distance: (x, y, h) => reached(x, y, plateReach(COMMENT_PLATE, h.pts[0], h.drawing, h.rc)),
} satisfies AnchoredTool<1>;

/** How tall the signpost's post stands, in media px. */
const POST = 34;

/**
 * Centred on top of the post. The post itself is grabbed too, so a signpost
 * whose plate is off the pane stays grabbable.
 */
const SIGNPOST_PLATE: PlateDefaults = {
  size: 11, opacity: 0.95, fallback: 'Event', at: (p, w, h, d) => ({ x: p.x - w / 2, y: p.y - POST * d - h }),
  post: (p) => ({ x: p.x - 5, y: p.y - POST, w: 10, h: POST + 4 }),
};

/**
 * Signpost: a post standing on the bar with its plate at the top.
 *
 * The one annotation anchored to *time* rather than to a level: the post is
 * vertical so the plate can clear the price action entirely while the foot
 * still names an exact bar. Useful for events, which happen at a moment and
 * not at a price.
 */
export const SIGNPOST: DrawingTool = {
  id: 'signpost', name: 'Signpost', points: 1,
  defaultText: { value: 'Event', fontSize: SIGNPOST_PLATE.size },
  settings: STEMMED_NOTE_SETTINGS,
  draw: (c) => {
    const d = c.rc.dpr;
    const p = c.pts[0];
    const lines = plateLines(SIGNPOST_PLATE, c.drawing, c.formatPrice);
    const box = notePlate(c, p, lines, SIGNPOST_PLATE);
    c.ctx.save();
    c.ctx.setLineDash([]);
    c.ctx.strokeStyle = c.style.color;
    c.ctx.lineWidth = Math.max(1, c.style.lineWidth * d);
    c.ctx.beginPath();
    c.ctx.moveTo(p.x, p.y);
    c.ctx.lineTo(p.x, p.y - POST * d);
    c.ctx.stroke();
    c.ctx.fillStyle = c.style.color;
    c.ctx.beginPath();
    c.ctx.arc(p.x, p.y, 3 * d, 0, Math.PI * 2);
    c.ctx.fill();
    c.ctx.restore();
    paintPlate(c, box, lines, SIGNPOST_PLATE, 4);
  },
  distance: (x, y, h) => reached(x, y, plateReach(SIGNPOST_PLATE, h.pts[0], h.drawing, h.rc)),
} satisfies AnchoredTool<1>;

/** To the right of the anchor, level with it, the price on its first line. */
const PRICE_NOTE_PLATE: PlateDefaults = {
  size: 11, opacity: 0.95, fallback: 'Note', price: true, at: (p, _w, _h, d) => ({ x: p.x + 14 * d, y: p.y - 12 * d }),
};

/**
 * Price note: the anchored price, with the user's text under it.
 *
 * The price is read off the anchor rather than typed, so dragging the note
 * re-reads it. A typed price is a number that was true once, which on a chart
 * is worse than no number at all.
 */
export const PRICE_NOTE: DrawingTool = {
  id: 'price-note', name: 'Price Note', points: 1,
  defaultText: { value: 'Note', fontSize: PRICE_NOTE_PLATE.size },
  settings: STEMMED_NOTE_SETTINGS,
  draw: (c) => {
    const d = c.rc.dpr;
    const p = c.pts[0];
    const lines = plateLines(PRICE_NOTE_PLATE, c.drawing, c.formatPrice);
    const box = notePlate(c, p, lines, PRICE_NOTE_PLATE);
    c.ctx.save();
    c.ctx.setLineDash([]);
    c.ctx.strokeStyle = c.style.color;
    c.ctx.lineWidth = Math.max(1, c.style.lineWidth * d);
    c.ctx.beginPath();
    c.ctx.moveTo(p.x, p.y);
    c.ctx.lineTo(box.x, p.y);
    c.ctx.stroke();
    c.ctx.restore();
    paintPlate(c, box, lines, PRICE_NOTE_PLATE, 4);
  },
  distance: (x, y, h) => reached(x, y, plateReach(PRICE_NOTE_PLATE, h.pts[0], h.drawing, h.rc)),
} satisfies AnchoredTool<1>;

const PLATES = new Map<DrawingTool, PlateDefaults>([
  [NOTE, NOTE_PLATE], [BALLOON, BALLOON_PLATE], [COMMENT, COMMENT_PLATE], [SIGNPOST, SIGNPOST_PLATE], [PRICE_NOTE, PRICE_NOTE_PLATE],
]);

/**
 * The box outside which a plate annotation, the price label or the callout's
 * bubble reports no hit, in media px, for the layer's hit index: read off the
 * same measured plate the hit test reads, so the two cannot disagree. The
 * callout's tail is a segment the index adds itself. Undefined for any other
 * tool, and for a drawing short of its anchors.
 */
export function annotationBox(
  tool: DrawingTool, pts: readonly ScreenPoint[], d: Drawing, rc: PrimitiveRenderContext,
): { x0: number; y0: number; x1: number; y1: number } | undefined {
  const def = PLATES.get(tool), p = pts[0], seat = pts[1];
  let r: Reach;
  if (tool === CALLOUT && seat !== undefined) r = { plate: calloutReach(seat, d) };
  else if (tool === PRICE_LABEL && p !== undefined) r = priceLabelReach(p, d, rc);
  else if (def !== undefined && p !== undefined) r = plateReach(def, p, d, rc);
  else return undefined;
  const { plate, dot, post } = r;
  const mark = dot !== undefined ? { x: dot.at.x - dot.r, y: dot.at.y - dot.r, w: 2 * dot.r, h: 2 * dot.r } : post ?? plate;
  return {
    x0: Math.min(plate.x, mark.x), y0: Math.min(plate.y, mark.y),
    x1: Math.max(plate.x + plate.w, mark.x + mark.w), y1: Math.max(plate.y + plate.h, mark.y + mark.h),
  };
}

const TABLE_SIZE = 11;
const TABLE_OPACITY = 0.92;

function tableWidths(ctx: CanvasRenderingContext2D | null, text: DrawingText, rows: string[][], dpr: number): number[] {
  const size = (text.fontSize ?? TABLE_SIZE) * dpr;
  const widths = Array.from({ length: Math.max(...rows.map(row => row.length)) }, () => 0);
  ctx?.save();
  try {
    for (let r = 0; r < rows.length; r++) {
      if (ctx !== null) ctx.font = fontOf(text, size, r === 0 ? text.bold === true ? '800' : '600' : undefined);
      for (let col = 0; col < widths.length; col++) {
        const cell = rows[r]![col] ?? ''; // r and col are in range: a short row reads blank
        const width = ctx === null ? cell.length * size * 0.6 : drawingTextWidth(ctx, cell);
        widths[col] = Math.max(widths[col]!, width + 14 * dpr);
      }
    }
  } finally { ctx?.restore(); }
  return widths;
}

/**
 * Table: rows of text in a grid, anchored top-left.
 *
 * Cells come from the text: a newline starts a row and a pipe separates
 * columns, so a whole table is one editable string and survives `getState`
 * with no new shape in the drawing model. The first row is drawn as a header
 * because a table on a chart is nearly always labelled.
 */
export const TABLE: DrawingTool = {
  // Laid out from its top-left anchor alone, so a table of levels can stay in
  // a corner of the pane while the chart pans under it.
  id: 'table', name: 'Table', points: 1, viewport: true,
  defaultText: { value: 'Level|Price\nEntry|-\nStop|-', fontSize: TABLE_SIZE },
  settings: composeSettings([
    COLOR_FIELD,
    { ...LINE_WIDTH_FIELD, label: 'Border width' },
    TEXT_VALUE_FIELD,
    FONT_FIELDS,
    { path: 'text.backgroundColor', label: 'Background color', kind: 'color', group: 'text' },
    { path: 'text.backgroundOpacity', label: 'Background opacity', kind: 'opacity', min: 0, max: 1, step: 0.01, group: 'text' },
    { path: 'text.border', label: 'Border', kind: 'boolean', group: 'text' },
    { path: 'text.borderColor', label: 'Border color', kind: 'color', group: 'text' },
    SPACE_FIELD,
  ], { textIsContent: true }),
  draw: (c) => {
    const d = c.rc.dpr;
    const p = c.pts[0];
    const t = textOf(c.drawing);
    const rows = tableRows(c.drawing);
    const size = (t.fontSize ?? TABLE_SIZE) * d;
    const pad = 7 * d;
    const rowH = size * 1.7;
    c.ctx.save();
    // Column widths are the widest cell in each column, so a table with one
    // long label does not stretch every other column to match it. Include
    // the heavier header font in the same layout used for hit testing.
    const widths = tableWidths(c.ctx, t, rows, d);
    const total = widths.reduce((a, b) => a + b, 0);
    const h = rowH * rows.length;
    c.ctx.setLineDash([]);
    c.ctx.globalAlpha = t.backgroundOpacity ?? TABLE_OPACITY;
    c.ctx.fillStyle = t.backgroundColor ?? c.rc.theme.background;
    c.ctx.beginPath();
    roundRectPath(c.ctx, p.x, p.y, total, h, 4 * d);
    c.ctx.fill();
    c.ctx.globalAlpha = 1;
    // A table is bordered unless told otherwise: the grid is what makes the
    // numbers read as a table rather than as loose text.
    if (t.border !== false) {
      c.ctx.strokeStyle = t.borderColor ?? c.style.color;
      c.ctx.lineWidth = Math.max(1, c.style.lineWidth * d);
      c.ctx.stroke();
      // Rules between rows and columns, drawn faintly: the grid should organise
      // the numbers, not compete with them.
      c.ctx.globalAlpha = 0.45;
      c.ctx.beginPath();
      for (let r = 1; r < rows.length; r++) {
        c.ctx.moveTo(p.x, p.y + rowH * r);
        c.ctx.lineTo(p.x + total, p.y + rowH * r);
      }
      let cx = p.x;
      for (let i = 0; i < widths.length - 1; i++) {
        cx += widths[i]!; // i is in range
        c.ctx.moveTo(cx, p.y);
        c.ctx.lineTo(cx, p.y + h);
      }
      c.ctx.stroke();
      c.ctx.globalAlpha = 1;
    }
    c.ctx.textBaseline = 'middle';
    c.ctx.textAlign = 'left';
    // The header is a step heavier than the body, and a step heavier again
    // when the body itself is bold, so it stays the header either way.
    const headFont = fontOf(t, size, t.bold === true ? '800' : '600');
    const bodyFont = fontOf(t, size);
    for (let r = 0; r < rows.length; r++) {
      c.ctx.fillStyle = t.color ?? c.style.color;
      c.ctx.font = r === 0 ? headFont : bodyFont;
      let x = p.x;
      for (let i = 0; i < widths.length; i++) {
        c.ctx.fillText(rows[r]![i] ?? '', x + pad, p.y + rowH * r + rowH / 2); // r and i are in range
        x += widths[i]!;
      }
    }
    c.ctx.restore();
  },
  distance: (x, y, h) => {
    const r = tableRect(h.pts[0], h.drawing);
    return insidePlate(x, y, r.x0, r.y0, r.x1 - r.x0, r.y1 - r.y0);
  },
  bounds: (pts, drawing) => tableRect(pts[0], drawing),
} satisfies AnchoredTool<1, true>;

/** The table's grid in media px from its top-left anchor, laid out as it is drawn. */
function tableRect(p: ScreenPoint, drawing: Drawing): { x0: number; y0: number; x1: number; y1: number } {
  const rows = tableRows(drawing);
  const size = drawing.text?.fontSize ?? TABLE_SIZE;
  const width = tableWidths(measureContext(), textOf(drawing), rows, 1).reduce((sum, w) => sum + w, 0);
  return { x0: p.x, y0: p.y, x1: p.x + width, y1: p.y + size * 1.7 * rows.length };
}

/** Rows of cells from the pipe-and-newline encoding. Always at least one cell. */
function tableRows(d: Drawing): string[][] {
  // An empty table is an empty grid, which reads as a rendering fault rather
  // than as a table waiting for content, so it falls back like the rest.
  return contentOf(d, 'Level|Price').split('\n').map((r) => r.split('|'));
}

// ── arrow marks ───────────────────────────────────────────────────────────

/** A single-anchor marker that points at a bar. `up` sits below, pointing up. */
function arrowMarker(
  id: string, name: string, up: boolean, axis: 'vertical' | 'left' | 'right' = 'vertical',
): DrawingTool {
  return {
    id, name, points: 1,
    defaultStyle: { fill: true, fillOpacity: 0.9 },
    settings: MARK_SETTINGS,
    draw: (c) => {
      const d = c.rc.dpr;
      const { x, y } = c.pts[0];
      const len = 16 * d;
      const w = 6 * d;
      const dir = up ? 1 : -1;
      // Offset off the anchor so the marker sits beside the bar, not on top of it.
      const tipY = y + dir * 2 * d;
      c.ctx.beginPath();
      if (axis !== 'vertical') {
        // The same arrow rotated a quarter turn: the shaft runs along x and the
        // head points at the bar, so a left or right mark reads as pointing
        // *into* the price action rather than along it.
        const h = axis === 'right' ? -1 : 1;
        const tipX = x + h * 2 * d;
        c.ctx.moveTo(tipX, y);
        c.ctx.lineTo(tipX + h * w, y - w);
        c.ctx.lineTo(tipX + h * w, y - w / 2.4);
        c.ctx.lineTo(tipX + h * len, y - w / 2.4);
        c.ctx.lineTo(tipX + h * len, y + w / 2.4);
        c.ctx.lineTo(tipX + h * w, y + w / 2.4);
        c.ctx.lineTo(tipX + h * w, y + w);
        c.ctx.closePath();
      } else {
        c.ctx.moveTo(x, tipY);
        c.ctx.lineTo(x - w, tipY + dir * w);
        c.ctx.lineTo(x - w / 2.4, tipY + dir * w);
        c.ctx.lineTo(x - w / 2.4, tipY + dir * len);
        c.ctx.lineTo(x + w / 2.4, tipY + dir * len);
        c.ctx.lineTo(x + w / 2.4, tipY + dir * w);
        c.ctx.lineTo(x + w, tipY + dir * w);
        c.ctx.closePath();
      }
      if (c.style.fill !== false) {
        c.ctx.save();
        c.ctx.globalAlpha = c.style.fillOpacity ?? 0.9;
        c.ctx.fillStyle = fillStyleOf(c);
        c.ctx.fill();
        c.ctx.restore();
      }
      applyStroke(c);
      c.ctx.stroke();
      c.ctx.setLineDash([]);
    },
    distance: (x, y, hc) => {
      const a = hc.pts[0];
      const dy = up ? y - a.y : a.y - y;
      return Math.abs(x - a.x) <= 8 && dy >= -4 && dy <= 20 ? 0 : null;
    },
  } satisfies AnchoredTool<1>;
}
export const ARROW_UP = arrowMarker('arrow-up', 'Arrow Up', true);
export const ARROW_DOWN = arrowMarker('arrow-down', 'Arrow Down', false);
export const ARROW_LEFT = arrowMarker('arrow-left', 'Arrow Left', true, 'left');
export const ARROW_RIGHT = arrowMarker('arrow-right', 'Arrow Right', true, 'right');
