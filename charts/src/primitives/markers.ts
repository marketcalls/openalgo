/**
 * Series markers (ARCHITECTURE.md §8.1): buy/sell signals and shapes anchored
 * to bars. Visible-range culled, per-bar stacked, four discrete sizes.
 *
 * Markers that carry text and sit above or below the bar (or on a pane edge)
 * are laid out in lanes: a label is wider than a bar, so on a whipsaw the
 * signals on neighbouring bars landed on each other. Each one is pushed
 * outward just past any earlier one on its side whose box it overlaps, and
 * one that overlaps nothing stays where it always was. A label moves at most
 * a few of its own heights: where labels outnumber the room, as at a wide
 * zoom, the rest overlap on their bars rather than stack out of the pane.
 */
import type { Bar } from '../model/bar';
import type { SeriesId } from '../model/data-layer';
import type { PriceScale } from '../scale/price-scale';
import type { LogicalRange } from '../scale/time-scale';
import type { IPrimitive, PrimitiveHost, PrimitiveRenderContext, PrimitiveHit, ZOrder } from './primitive';
import { roundRectPath, contrastText } from '../render/pill';
import { hasTextStyle, textFont, validateTextStyle } from '../render/text-style';

/**
 * `labelUp` / `labelDown` are text plates with a tail, for named signals ("Buy",
 * "Sell") rather than bare glyphs. The tail points *at* the anchor price and the
 * body sits clear of it: `labelUp`'s tail points up so its body hangs below the
 * anchor, `labelDown` is the mirror. Both require `text`.
 */
export type MarkerShape =
  | 'arrowUp' | 'arrowDown' | 'circle' | 'square'
  | 'triangleUp' | 'triangleDown' | 'diamond' | 'flag' | 'text'
  | 'labelUp' | 'labelDown'
  | 'cross' | 'xcross';
/**
 * `paneTop` and `paneBottom` pin the glyph to the edge of the plot rather than
 * to a price, so a squeeze dot or a session flag sits in a fixed row whatever
 * the scale does. They need no bar under them and no `price`.
 */
export type MarkerPosition = 'aboveBar' | 'belowBar' | 'inBar' | 'atPrice' | 'paneTop' | 'paneBottom';
export type MarkerSize = 'tiny' | 'small' | 'medium' | 'big';

export interface SeriesMarker {
  time: number;
  position: MarkerPosition;
  price?: number;
  shape: MarkerShape;
  size: MarkerSize;
  color: string;
  text?: string;
  /** Overrides marker-matching text or contrasting label text without changing the glyph fill. */
  textColor?: string;
  /** Positive finite CSS pixels. Defaults to max(9, the size preset), independently of bar spacing. */
  fontSize?: number;
  /** CSS font-family list. Defaults to system-ui, sans-serif. */
  fontFamily?: string;
  /** Label plates default to semibold; other marker text defaults to normal. */
  bold?: boolean;
  italic?: boolean;
  /** Multiline row alignment inside the centered text block. Defaults to center. */
  textAlign?: 'left' | 'center' | 'right';
  id?: string;
}

const SIZE_PX: Record<MarkerSize, number> = { tiny: 6, small: 9, medium: 12, big: 16 };

/** Base glyph size in CSS px for a marker size preset. */
export function markerSizePx(size: MarkerSize): number {
  return SIZE_PX[size];
}

/** Effective glyph px, clamped so it never exceeds the current bar spacing. */
export function effectiveMarkerPx(size: MarkerSize, barSpacing: number): number {
  return Math.max(4, Math.min(SIZE_PX[size], Math.floor(barSpacing)));
}

export function drawShape(
  ctx: CanvasRenderingContext2D,
  shape: MarkerShape,
  cx: number,
  cy: number,
  px: number,
  color: string,
): void {
  const r = px / 2;
  ctx.fillStyle = color;
  ctx.strokeStyle = color;
  ctx.beginPath();
  switch (shape) {
    case 'arrowUp':
      ctx.moveTo(cx, cy - r); ctx.lineTo(cx + r, cy + r); ctx.lineTo(cx - r, cy + r); ctx.closePath(); ctx.fill();
      break;
    case 'triangleUp':
      ctx.moveTo(cx, cy - r); ctx.lineTo(cx + r, cy + r); ctx.lineTo(cx - r, cy + r); ctx.closePath(); ctx.fill();
      break;
    case 'arrowDown':
      ctx.moveTo(cx, cy + r); ctx.lineTo(cx + r, cy - r); ctx.lineTo(cx - r, cy - r); ctx.closePath(); ctx.fill();
      break;
    case 'triangleDown':
      ctx.moveTo(cx, cy + r); ctx.lineTo(cx + r, cy - r); ctx.lineTo(cx - r, cy - r); ctx.closePath(); ctx.fill();
      break;
    case 'circle':
      ctx.arc(cx, cy, r, 0, Math.PI * 2); ctx.fill();
      break;
    case 'square':
      ctx.fillRect(cx - r, cy - r, px, px);
      break;
    case 'diamond':
      ctx.moveTo(cx, cy - r); ctx.lineTo(cx + r, cy); ctx.lineTo(cx, cy + r); ctx.lineTo(cx - r, cy); ctx.closePath(); ctx.fill();
      break;
    case 'flag':
      ctx.fillRect(cx - 1, cy - r, Math.max(1, px / 8), px); // pole
      ctx.fillRect(cx, cy - r, r, r * 0.8); // flag
      break;
    case 'cross': {
      // Two filled bars rather than a stroke, so the arms stay crisp at the
      // integer widths every other glyph here lands on.
      const t = Math.max(1, Math.round(px / 6));
      ctx.fillRect(cx - r, cy - Math.floor(t / 2), px, t);
      ctx.fillRect(cx - Math.floor(t / 2), cy - r, t, px);
      break;
    }
    case 'xcross':
      ctx.lineWidth = Math.max(1, Math.round(px / 6));
      ctx.moveTo(cx - r, cy - r); ctx.lineTo(cx + r, cy + r);
      ctx.moveTo(cx + r, cy - r); ctx.lineTo(cx - r, cy + r);
      ctx.stroke();
      break;
    case 'text':
    case 'labelUp':
    case 'labelDown':
      // text-bearing markers: nothing drawn here; the caller has the string,
      // the font, and the device ratio. See `drawLabel`.
      break;
  }
}

/**
 * Row pitch for `\n`-separated marker text, as a multiple of the font size.
 * Same pitch the drawings tier uses for its plates, so a label reads the same
 * whichever tier ends up painting it.
 */
const LINE_H = 1.35;
type MarkerTextStyle = Pick<SeriesMarker, 'fontFamily' | 'bold' | 'italic' | 'textAlign' | 'textColor'>;

function labelLayout(ctx: CanvasRenderingContext2D, up: boolean, anchorY: number, text: string, fontPx: number) {
  const padX = fontPx * 0.5;
  const lines = text.indexOf('\n') < 0 ? undefined : text.split('\n');
  // A split returns one part at least, and the loop stays inside the parts.
  let textW = ctx.measureText(lines === undefined ? text : lines[0]!).width;
  if (lines !== undefined) for (let i = 1; i < lines.length; i++) textW = Math.max(textW, ctx.measureText(lines[i]!).width);
  const lh = fontPx * LINE_H;
  const w = textW + padX * 2;
  const h = fontPx + fontPx * 0.64 + (lines === undefined ? 0 : lh * (lines.length - 1));
  const tail = fontPx * 0.42;
  return { lines, lh, w, h, tail, textW, top: up ? anchorY + tail : anchorY - tail - h };
}

/**
 * A signal label: rounded plate, contrasting text, and a tail that points at
 * `anchorY`. All coordinates are bitmap px: the caller has already applied dpr.
 * `up` puts the tail on the top edge and the body below the anchor.
 *
 * `text` may carry `\n`: the plate widens to the longest row and grows
 * downward-and-upward about its own centre, so it stays centred on `cx` and the
 * tail keeps meeting the anchor price.
 */
export function drawLabel(
  ctx: CanvasRenderingContext2D,
  up: boolean,
  cx: number,
  anchorY: number,
  text: string,
  color: string,
  fontPx: number,
): void {
  ctx.font = `600 ${fontPx}px system-ui, sans-serif`;
  // The overwhelmingly common label is one row, so it never pays for a split:
  // undefined here keeps the original single-measure, single-fillText path and
  // with it the exact plate geometry markers have always had.
  const layout = labelLayout(ctx, up, anchorY, text, fontPx);
  paintLabel(ctx, up, cx, anchorY, text, color, fontPx, layout);
}

function paintLabel(ctx: CanvasRenderingContext2D, up: boolean, cx: number, anchorY: number, text: string,
  color: string, fontPx: number, layout: ReturnType<typeof labelLayout>, style?: MarkerTextStyle): void {
  const { w, h, top, tail, lines, lh, textW } = layout;

  ctx.fillStyle = color;
  ctx.beginPath();
  roundRectPath(ctx, cx - w / 2, top, w, h, Math.min(fontPx * 0.3, h / 2));
  ctx.fill();
  // The tail overlaps the plate edge by a pixel so the two fills read as one
  // shape instead of showing a hairline seam at fractional dpr.
  const base = up ? top + 1 : top + h - 1;
  ctx.beginPath();
  ctx.moveTo(cx, anchorY);
  ctx.lineTo(cx - tail, base);
  ctx.lineTo(cx + tail, base);
  ctx.closePath();
  ctx.fill();

  ctx.fillStyle = style?.textColor ?? contrastText(color);
  ctx.textAlign = style?.textAlign ?? 'center';
  ctx.textBaseline = 'middle';
  const tx = style?.textAlign === 'left' ? cx - textW / 2 : style?.textAlign === 'right' ? cx + textW / 2 : cx;
  if (lines === undefined) {
    ctx.fillText(text, tx, top + h / 2);
    return;
  }
  const first = top + h / 2 - (lh * (lines.length - 1)) / 2;
  for (let i = 0; i < lines.length; i++) ctx.fillText(lines[i]!, tx, first + lh * i);
}

/**
 * The bar at exactly `time` in a time-sorted series, by binary search. Where
 * the time repeats (a host that appends the forming bar beside its fetched
 * copy), the last copy is the live one, as the data layer keeps it.
 */
function barAtTime(bars: readonly Bar[], time: number): Bar | undefined {
  let lo = 0;
  let hi = bars.length - 1;
  while (lo <= hi) {
    // mid stays inside [lo, hi], and the walk forward checks the length first.
    let mid = (lo + hi) >> 1;
    const t = bars[mid]!.time;
    if (t === time) {
      while (mid + 1 < bars.length && bars[mid + 1]!.time === time) mid++;
      return bars[mid];
    }
    if (t < time) lo = mid + 1;
    else hi = mid - 1;
  }
  return undefined;
}

const FAMILY = 'system-ui, sans-serif';

/**
 * The side a text mark stacks away from: up for marks above the bar or on
 * the pane's bottom edge, down for marks below it or on the top edge. A mark
 * at a price or in the bar has one place to be and is never moved.
 */
const LANE: Partial<Record<MarkerPosition, -1 | 1>> = { aboveBar: -1, paneBottom: -1, belowBar: 1, paneTop: 1 };

/**
 * How far a text mark may move to clear the ones before it, in its own box
 * heights. At the default bar spacing a whipsaw needs two, and a four-letter
 * signal on every bar of a run needs four. Past this, as at a wide zoom where
 * the labels outnumber the room above the bars, a label stays on its bar and
 * overlaps as it always did, rather than joining a column that climbs out of
 * the pane and costs a frame to lay out.
 */
const LANE_DEPTH = 5;

/**
 * A lane depends on every earlier label whose box reaches it, and on a dense
 * run that chain goes back through the whole history. The layout reads at
 * most two windows of this many marks before the first one drawn, from a start
 * that moves in whole windows, so labels hold still while the view pans and a
 * paint does not grow with the history. Where a gap inside the window breaks
 * the chain, the layout starts at the gap and is exact.
 */
const LANE_WINDOW = 256;

const isLabel = (m: SeriesMarker): boolean => m.shape === 'labelUp' || m.shape === 'labelDown';
const isStyled = (m: SeriesMarker): boolean => hasTextStyle(m) || m.textColor !== undefined;
const markerFontPx = (m: SeriesMarker): number => m.fontSize ?? Math.max(9, markerSizePx(m.size));

interface LaneBox { l: number; r: number; t: number; b: number }

function extraRows(text: string): number {
  let n = 0;
  for (let i = text.indexOf('\n'); i >= 0; i = text.indexOf('\n', i + 1)) n++;
  return n;
}

/**
 * Half the width a text mark takes, from its widest row `textW`: a plate is
 * its text plus padding, bare text is its text, and a glyph with text is the
 * wider of the two at the glyph size `px`.
 */
function halfWidth(m: SeriesMarker, textW: number, fontPx: number, px: number): number {
  if (isLabel(m)) return (textW + fontPx) / 2;
  if (m.shape === 'text') return textW / 2;
  return Math.max(textW, px) / 2;
}

/**
 * The box a text mark takes in its lane, in bitmap px: the same plate, tail
 * and text block the renderer draws around `y`, worked out from the measured
 * row width so a mark laid out left of the view costs no canvas call.
 */
function laneBox(m: SeriesMarker, x: number, y: number, px: number, fontPx: number, textW: number, below: boolean): LaneBox {
  const half = halfWidth(m, textW, fontPx, px);
  const rows = extraRows(m.text ?? '');
  if (isLabel(m)) {
    const h = fontPx + fontPx * 0.64 + (rows === 0 ? 0 : fontPx * LINE_H * rows);
    const tail = fontPx * 0.42;
    return m.shape === 'labelUp'
      ? { l: x - half, r: x + half, t: y, b: y + tail + h }
      : { l: x - half, r: x + half, t: y - tail - h, b: y };
  }
  const textH = fontPx + rows * fontPx * LINE_H;
  const top = below ? y + px : y - px - textH;
  // A bare text mark draws no glyph, so only its text takes lane room.
  if (m.shape === 'text') return { l: x - half, r: x + half, t: top, b: top + textH };
  return { l: x - half, r: x + half, t: Math.min(y - px / 2, top), b: Math.max(y + px / 2, top + textH) };
}

/**
 * Push a box outward (`dir` -1 up, 1 down) just past every box already in its
 * lane that it overlaps, record it, and return how far it moved: nothing when
 * it overlaps nothing, and nothing when clearing the lane would take it
 * further than `limit`. Boxes whose right edge is at or left of `keepFrom`
 * cannot reach this box or any later one, and are dropped once the lane grows.
 */
function placeInLane(lane: LaneBox[], dir: -1 | 1, box: LaneBox, gap: number, keepFrom: number, limit: number): number {
  if (lane.length > 32) {
    let k = 0;
    for (const other of lane) if (other.r > keepFrom) lane[k++] = other;
    lane.length = k;
  }
  let dy = 0;
  for (let moved = true; moved;) {
    moved = false;
    for (const other of lane) {
      if (other.r <= box.l || other.l >= box.r || other.b <= box.t + dy || other.t >= box.b + dy) continue;
      dy = dir < 0 ? other.t - gap - box.b : other.b + gap - box.t;
      moved = true;
      if (Math.abs(dy) > limit) { dy = 0; moved = false; break; }
    }
  }
  box.t += dy;
  box.b += dy;
  lane.push(box);
  return dy;
}

/** Where a painted mark landed, in media px, for hit-testing; a styled mark is clipped to the plot. */
interface MarkPosition { id: string; x: number; y: number; clip?: { width: number; height: number } | undefined }

/** Where a mark sits before lanes move it, in device px; NaN when it has nothing to sit on. */
function anchorY(m: SeriesMarker, bar: Bar | undefined, px: number, gap: number, priceScale: PriceScale,
  rc: PrimitiveRenderContext): number {
  if (m.position === 'paneTop') {
    // Pinned to the plot edge, stacking inward, so the row never moves
    // with the scale and needs no bar under it.
    return px / 2 + 4 * rc.dpr + gap;
  } else if (m.position === 'paneBottom') {
    return rc.plotHeight * rc.dpr - px / 2 - 4 * rc.dpr - gap;
  } else if (m.position === 'atPrice' && m.price !== undefined) {
    return priceScale.priceToY(m.price) * rc.dpr;
  } else if (bar !== undefined && m.position === 'aboveBar') {
    return priceScale.priceToY(bar.high) * rc.dpr - px - gap;
  } else if (bar !== undefined && m.position === 'belowBar') {
    return priceScale.priceToY(bar.low) * rc.dpr + px + gap;
  } else if (bar !== undefined) {
    return priceScale.priceToY((bar.open + bar.close) / 2) * rc.dpr;
  }
  return NaN;
}

/** How a paint finds the bar a mark sits on: on its own series, else among the fallback bars. */
function barLookup(own: readonly Bar[], fallbackBars: (() => readonly Bar[]) | undefined): (time: number) => Bar | undefined {
  // Bars are looked up per drawn marker, never collected up front: a paint
  // runs on every live tick, and indexing the whole history here made the
  // frame cost grow with the history length instead of with what is shown.
  let fallback: readonly Bar[] | undefined;
  let fallbackByTime: Map<number, Bar> | undefined;
  return (time: number): Bar | undefined => {
    // A real point on the marker's own series wins; indicator null columns
    // retain their timestamp as NaN points. Where that series has a gap the
    // instrument's bar stands in, which is the whole point: the mark is drawn
    // rather than lost.
    const bar = barAtTime(own, time);
    if (bar !== undefined && Number.isFinite(bar.close)) return bar;
    if (fallbackBars === undefined) return undefined;
    fallback ??= fallbackBars();
    // The fallback comes from the host and is not promised to be sorted. An
    // exact hit is right when it is sorted (a repeated time's copies sit
    // together and the last wins) and when it repeats no time; only a miss
    // has to be confirmed by indexing it, at most once per paint.
    const hit = barAtTime(fallback, time);
    if (hit !== undefined) return hit;
    if (fallbackByTime === undefined) {
      fallbackByTime = new Map();
      for (const b of fallback) fallbackByTime.set(b.time, b);
    }
    return fallbackByTime.get(time);
  };
}

/**
 * Where a paint starts laying out: the lane window before the first mark
 * that may be painted, so text marks left of the view still make room, and
 * the widest half of any text mark laid out. Null when no mark can be painted.
 */
function laneWindow(
  markers: readonly SeriesMarker[],
  anyStyled: boolean,
  rc: PrimitiveRenderContext,
  range: LogicalRange,
  laneFont: (m: SeriesMarker) => number,
  halfOf: (m: SeriesMarker, fontPx: number) => number,
): { start: number; widest: number } | null {
  const dpr = rc.dpr;
  // Every walk over the marks stays inside the list: the loop bounds hold `i`,
  // `first` is short of the length once the early return below has passed, and
  // a mark's predecessor is read only after the first one.
  // The first mark that may be painted; none before it is.
  let first = markers.length;
  for (let i = 0; i < markers.length; i++) {
    const m = markers[i]!;
    const index = rc.dataLayer.timeToIndex(m.time);
    if (index === undefined) continue;
    if (isStyled(m)) {
      const fontPx = markerFontPx(m) * dpr;
      const half = m.text !== undefined && Number.isFinite(fontPx) && fontPx > 0 ? halfOf(m, fontPx) : 0;
      if (rc.timeScale.indexToX(index) * dpr + Math.max(half, 16 * dpr) < 0) continue;
    } else if (index < range.from - 1) {
      continue;
    }
    first = i;
    break;
  }
  if (first === markers.length) return null;
  // Marks at one time stack in order, so the first bar's earlier marks count too.
  while (first > 0 && markers[first - 1]!.time === markers[first]!.time) first--;
  const from = Math.max(0, Math.floor((first - LANE_WINDOW) / LANE_WINDOW) * LANE_WINDOW);

  // The widest half of any text mark laid out, which bounds how far left of
  // its own x a later box can start.
  let widest = 0;
  for (let i = from; i < markers.length; i++) {
    const m = markers[i]!;
    const index = rc.dataLayer.timeToIndex(m.time);
    if (index === undefined) continue;
    if (!isStyled(m) && index > range.to + 1) {
      if (anyStyled) continue;
      break;
    }
    const fontPx = laneFont(m);
    if (fontPx > 0) widest = Math.max(widest, halfOf(m, fontPx));
  }
  // The latest mark in the window that nothing laid out before it reaches.
  let start = from;
  let reach = -Infinity;
  for (let i = from; i < first; i++) {
    const m = markers[i]!;
    const index = rc.dataLayer.timeToIndex(m.time);
    if (index === undefined) continue;
    const x = rc.timeScale.indexToX(index) * dpr;
    if (x - widest >= reach && (i === from || markers[i - 1]!.time !== m.time)) start = i;
    const fontPx = laneFont(m);
    if (fontPx > 0) reach = Math.max(reach, x + halfOf(m, fontPx));
  }
  if (first > start) {
    const index = rc.dataLayer.timeToIndex(markers[first]!.time);
    if (index !== undefined && rc.timeScale.indexToX(index) * dpr - widest >= reach) start = first;
  }
  return { start, widest };
}

/** Paint one placed mark, clipped to the plot when it is styled, and record where it landed. */
function paintMark(ctx: CanvasRenderingContext2D, rc: PrimitiveRenderContext, m: SeriesMarker, x: number, y: number,
  px: number, fontPx: number, drawText: boolean, below: boolean, styled: boolean, label: boolean, positions: MarkPosition[]): void {
  const ty = below ? y + px : y - px;
  let textW = 0, layout: ReturnType<typeof labelLayout> | undefined;
  if (styled) {
    if (drawText) ctx.font = textFont(m, fontPx, FAMILY, label);
    let left = x - px / 2, right = x + px / 2, top = y - px / 2, bottom = y + px / 2;
    if (drawText && m.text !== undefined) {
      if (label) {
        layout = labelLayout(ctx, m.shape === 'labelUp', y, m.text, fontPx);
        left = x - layout.w / 2; right = x + layout.w / 2;
        top = Math.min(y, layout.top); bottom = Math.max(y, layout.top + layout.h);
      } else {
        const lines = m.text.split('\n');
        for (const line of lines) textW = Math.max(textW, ctx.measureText(line).width);
        const textH = fontPx + (lines.length - 1) * fontPx * LINE_H;
        left = Math.min(left, x - textW / 2); right = Math.max(right, x + textW / 2);
        top = Math.min(top, below ? ty : ty - textH); bottom = Math.max(bottom, below ? ty + textH : ty);
      }
    }
    if (!label && ![left, right, top, bottom].every(Number.isFinite)) {
      // Unrenderable text cannot erase an independently sized signal glyph.
      drawText = false;
      left = x - px / 2; right = x + px / 2; top = y - px / 2; bottom = y + px / 2;
    }
    if (![left, right, top, bottom].every(Number.isFinite) || right < 0 || left > rc.plotWidth * rc.dpr
      || bottom < 0 || top > rc.plotHeight * rc.dpr) return;
    ctx.save(); ctx.beginPath(); ctx.rect(0, 0, rc.plotWidth * rc.dpr, rc.plotHeight * rc.dpr); ctx.clip();
  }
  const clip = styled ? { width: rc.plotWidth, height: rc.plotHeight } : undefined;
  if (m.shape === 'labelUp' || m.shape === 'labelDown') {
    if (m.text !== undefined) {
      if (layout) paintLabel(ctx, m.shape === 'labelUp', x, y, m.text, m.color, fontPx, layout, m);
      else drawLabel(ctx, m.shape === 'labelUp', x, y, m.text, m.color, fontPx);
    }
    if (m.id !== undefined) positions.push({ id: m.id, x: x / rc.dpr, y: y / rc.dpr, clip });
    if (styled) ctx.restore();
    return;
  }
  drawShape(ctx, m.shape, x, y, px, m.color);
  if (drawText && m.text !== undefined) {
    ctx.fillStyle = m.textColor ?? m.color;
    ctx.font = textFont(m, fontPx, FAMILY);
    ctx.textAlign = m.textAlign ?? 'center';
    // Text grows away from the edge a pinned marker sits on, the way it
    // grows away from the bar for the bar-anchored positions.
    ctx.textBaseline = below ? 'top' : 'bottom';
    const tx = m.textAlign === 'left' ? x - textW / 2 : m.textAlign === 'right' ? x + textW / 2 : x;
    if (m.text.indexOf('\n') < 0) {
      ctx.fillText(m.text, tx, ty);
    } else {
      // Rows grow away from the bar (down below it, up above it) and the
      // block is written from the anchor outward, so whichever edge the
      // baseline pins stays put and the text never runs back over the candle.
      const lines = m.text.split('\n');
      const lh = fontPx * LINE_H;
      for (let i = 0; i < lines.length; i++) {
        ctx.fillText(lines[below ? i : lines.length - 1 - i]!, tx, below ? ty + lh * i : ty - lh * i);
      }
    }
  }
  if (m.id !== undefined) positions.push({ id: m.id, x: x / rc.dpr, y: y / rc.dpr, clip });
  if (styled) ctx.restore();
}

export class SeriesMarkers implements IPrimitive {
  private readonly _seriesId: SeriesId;
  private readonly _fallbackBars: (() => readonly Bar[]) | undefined;
  private readonly _priceScale: (() => PriceScale) | undefined;
  private _markers: SeriesMarker[] = [];
  private _host: PrimitiveHost | null = null;
  private _lastPositions: MarkPosition[] = [];
  /** The widest row of each text mark measured so far, for this marker set and `_widthDpr`. */
  private _widths = new Map<SeriesMarker, number>();
  private _widthDpr = 0;
  /** The same widths by font and string, kept across marker sets. */
  private readonly _fontWidths = new Map<string, number>();
  private _anyStyled = false;

  /**
   * @param seriesId The series whose pane and price scale the marks live on.
   * @param fallbackBars Bars to position against where that series has none.
   *
   * The second argument exists because a marker's series decides *where* it is
   * drawn while the bar under it decides *how high*, and those are not always
   * the same row of data. An indicator that draws one line in an uptrend and
   * another in a downtrend has a gap in each, and a mark that lands in a gap
   * had no bar to measure from and was dropped without a word. The caller
   * passes the instrument's own bars, which have no gaps.
   */
  public constructor(seriesId: SeriesId, fallbackBars?: () => readonly Bar[], priceScale?: () => PriceScale) {
    this._seriesId = seriesId;
    this._fallbackBars = fallbackBars;
    this._priceScale = priceScale;
  }

  public attached(host: PrimitiveHost): void { this._host = host; }
  public detached(): void { this._host = null; this._lastPositions = []; }
  public zOrder(): ZOrder { return 'normal'; }

  public setMarkers(markers: readonly SeriesMarker[]): void {
    for (const marker of markers) {
      validateTextStyle(marker);
      if (marker.textColor !== undefined && (typeof marker.textColor !== 'string' || marker.textColor.trim() === '')) {
        throw new TypeError('Marker textColor must be a nonempty color string');
      }
    }
    this._markers = markers.slice().sort((a, b) => a.time - b.time);
    this._lastPositions = [];
    this._widths = new Map();
    this._anyStyled = this._markers.some(isStyled);
    this._host?.requestUpdate();
  }

  /**
   * The widest row of a mark's text in its own font, measured only for marks a
   * paint lays out, never the whole history. A study sets its marks again on
   * every recompute, with new objects and the same few strings, so a width is
   * also kept by font and string: setting the font is the costly part.
   */
  private _textWidth(ctx: CanvasRenderingContext2D, m: SeriesMarker, fontPx: number, dpr: number): number {
    if (this._widthDpr !== dpr) { this._widths = new Map(); this._widthDpr = dpr; }
    let w = this._widths.get(m);
    if (w !== undefined) return w;
    const font = textFont(m, fontPx, FAMILY, isLabel(m));
    const text = m.text ?? '';
    const key = font + '\n' + text;
    w = this._fontWidths.get(key);
    if (w === undefined) {
      ctx.font = font;
      w = 0;
      for (const line of text.split('\n')) w = Math.max(w, ctx.measureText(line).width);
      // Marks that print a price are each a new string, so this is kept small.
      if (this._fontWidths.size >= 512) this._fontWidths.clear();
      this._fontWidths.set(key, w);
    }
    this._widths.set(m, w);
    return w;
  }

  public draw(ctx: CanvasRenderingContext2D, rc: PrimitiveRenderContext): void {
    this._lastPositions = [];
    if (this._markers.length === 0) return;
    const barAt = barLookup(rc.dataLayer.seriesBars(this._seriesId), this._fallbackBars);
    const priceScale = this._priceScale?.() ?? rc.priceScale;
    const range = rc.timeScale.visibleRange();
    const stackByTime = new Map<number, number>();
    const markers = this._markers;
    const dpr = rc.dpr;
    // A mark that takes a lane: its bitmap font size, else NaN.
    const laneFont = (m: SeriesMarker): number => {
      if (m.text === undefined || LANE[m.position] === undefined) return NaN;
      const fontPx = markerFontPx(m) * dpr;
      return Number.isFinite(fontPx) && fontPx > 0 ? fontPx : NaN;
    };
    const halfOf = (m: SeriesMarker, fontPx: number): number => halfWidth(m, this._textWidth(ctx, m, fontPx, dpr),
      fontPx, effectiveMarkerPx(m.size, rc.timeScale.barSpacing) * dpr);

    ctx.save();
    const window = laneWindow(markers, this._anyStyled, rc, range, laneFont, halfOf);
    if (window === null) { ctx.restore(); return; }
    const { start, widest } = window;
    const laneGap = 2 * dpr;
    const lanes: Record<-1 | 1, LaneBox[]> = { [-1]: [], [1]: [] };

    for (let i = start; i < markers.length; i++) {
      const m = markers[i]!;
      const styled = isStyled(m);
      const index = rc.dataLayer.timeToIndex(m.time);
      if (index === undefined) continue;
      if (!styled && index > range.to + 1) {
        if (this._anyStyled) continue;
        break;
      }
      const laneFontPx = laneFont(m);
      // Left of the view a text mark is laid out and not drawn: the marks in
      // view make room for it all the same.
      const hidden = !styled && index < range.from - 1;
      if (hidden && !(laneFontPx > 0)) continue;
      const bar = m.position === 'paneTop' || m.position === 'paneBottom' ? undefined : barAt(m.time);
      const px = effectiveMarkerPx(m.size, rc.timeScale.barSpacing) * rc.dpr;
      const x = rc.timeScale.indexToX(index) * rc.dpr;
      const stack = stackByTime.get(m.time) ?? 0;
      const gap = (px + 4 * rc.dpr) * stack;
      let y = anchorY(m, bar, px, gap, priceScale, rc);
      if (!Number.isFinite(y) || !Number.isFinite(x)) continue;
      stackByTime.set(m.time, stack + 1);
      const fontPx = markerFontPx(m) * rc.dpr;
      const label = m.shape === 'labelUp' || m.shape === 'labelDown';
      const validFont = Number.isFinite(fontPx) && fontPx > 0;
      if (label && !validFont) continue;
      const drawText = validFont && m.text !== undefined;
      const below = m.position === 'belowBar' || m.position === 'paneTop';
      if (laneFontPx > 0) {
        const side = LANE[m.position] as -1 | 1;
        const box = laneBox(m, x, y, px, laneFontPx, this._textWidth(ctx, m, laneFontPx, dpr), below);
        if (Number.isFinite(box.l) && Number.isFinite(box.r) && Number.isFinite(box.t) && Number.isFinite(box.b)) {
          y += placeInLane(lanes[side], side, box, laneGap, x - widest, LANE_DEPTH * (box.b - box.t + laneGap));
        }
      }
      if (hidden) continue;
      paintMark(ctx, rc, m, x, y, px, fontPx, drawText, below, styled, label, this._lastPositions);
    }
    ctx.restore();
  }

  public hitTest(x: number, y: number): PrimitiveHit | null {
    let best: PrimitiveHit | null = null;
    for (const p of this._lastPositions) {
      if (p.clip && (x < 0 || y < 0 || x > p.clip.width || y > p.clip.height)) continue;
      const d = Math.hypot(p.x - x, p.y - y);
      if (d <= 8 && (best === null || d < best.distance)) {
        best = { externalId: p.id, zOrder: 'normal', distance: d, cursor: 'pointer' };
      }
    }
    return best;
  }
}
