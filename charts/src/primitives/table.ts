/**
 * A grid overlay pinned to a corner of the pane rather than to bars.
 *
 * Seasonality heatmaps, performance summaries and signal scoreboards are all
 * the same shape: a small table of coloured cells that stays put while the
 * chart pans underneath. That makes this a screen-space primitive like the
 * watermark and the pane legend, not a series: it has no time anchor, takes no
 * part in autoscale, and survives a zoom untouched.
 */
import type { IPrimitive, PrimitiveHost, PrimitiveRenderContext, PrimitiveHit, ZOrder } from './primitive';
import { contrastText, roundRectPath } from '../render/pill';

export type TablePosition =
  | 'top-left' | 'top-center' | 'top-right'
  | 'middle-left' | 'middle-center' | 'middle-right'
  | 'bottom-left' | 'bottom-center' | 'bottom-right';

export interface TableCell {
  /** Explicit newlines form a block with 1.2em line spacing. */
  text: string;
  /** Plain-text hover detail. Newlines are preserved; a merged cell uses its anchor's tooltip. */
  tooltip?: string;
  /** Cell fill. Transparent when omitted, so the pane shows through. */
  bgColor?: string;
  /** Text colour. Derived from `bgColor` for contrast when omitted. */
  textColor?: string;
  align?: 'left' | 'center' | 'right';
  /** Overrides the table's `fontSize` for this cell, for a heading row. */
  fontSize?: number;
  bold?: boolean;
  italic?: boolean;
  /** CSS font-family list. Defaults to `system-ui, sans-serif`. */
  fontFamily?: string;
  /** Aligns the text block within the cell, with 4px edge padding. Defaults to middle. */
  verticalAlign?: 'top' | 'middle' | 'bottom';
  /** Positive safe integer, default 1. The top-left cell supplies a merged cell's content. */
  colSpan?: number;
  /** Positive safe integer, default 1. Spans stay inside the existing rectangular grid. */
  rowSpan?: number;
}

export interface ChartTableOptions {
  position: TablePosition;
  /** Gap from the pane edge, media px. */
  margin: number;
  /**
   * Column width in media px. A per-column array sizes each one separately.
   *
   * `'auto'` measures instead: every column takes the width of its own widest
   * cell at the size that cell will be drawn at. A grid whose cells are
   * sentences rather than numbers cannot be sized by a caller who has not
   * measured the text, and a fixed width there is a column of readings running
   * into the column beside it.
   */
  cellWidth: number | readonly number[] | 'auto';
  cellHeight: number;
  /**
   * Type size in media px, or `'auto'` to fit each cell: as large as its row
   * allows, shrunk until its text also fits its column. A stretched grid with
   * one long label would otherwise either clip that cell or be sized down as a
   * whole to suit it.
   */
  fontSize: number | 'auto';
  /** Grid line colour. Omit to draw no grid. */
  borderColor?: string;
  borderWidth: number;
  /** Outer frame, independent of cell borders. Omit to draw no frame. */
  frameColor?: string;
  /** Outer frame width in media px. Defaults to 1 when a frame color is supplied. */
  frameWidth?: number;
  /**
   * Table width as a percentage of the plot, 0 or omitted to size from
   * `cellWidth` instead. Column proportions are preserved, so a per-column
   * `cellWidth` array still controls the relative widths, and the percentage
   * only decides the total.
   */
  widthPercent?: number;
  /** Table height as a percentage of the plot, 0 or omitted to size from `cellHeight`. */
  heightPercent?: number;
  /**
   * Relative row heights, one per row, defaulting to 1. A separator row is the
   * reason this exists: stretched to fill a pane, an equal split makes a rule
   * between two sections as tall as the sections themselves.
   */
  rowWeights?: readonly number[];
  /** Backdrop behind the whole grid, drawn before the cells. */
  background?: string;
  /** Hit-test id, so a host can route clicks the way it does for other primitives. */
  id?: string;
}

export const DEFAULT_CHART_TABLE_OPTIONS: ChartTableOptions = {
  position: 'bottom-right',
  margin: 8,
  cellWidth: 64,
  cellHeight: 18,
  fontSize: 11,
  borderWidth: 1,
};

/** Column x offsets and the total width, from a uniform or per-column setting. */
function columnEdges(cellWidth: number | readonly number[], cols: number): { x: number[]; total: number } {
  const x: number[] = [];
  let acc = 0;
  for (let c = 0; c < cols; c++) {
    x.push(acc);
    acc += typeof cellWidth === 'number' ? cellWidth : (cellWidth[c] ?? cellWidth[cellWidth.length - 1] ?? 0);
  }
  return { x, total: acc };
}

/** Use the same bitmap rounding and row limit for measurement and painting. */
function maximumFontSize(rowH: number, lineCount: number, dpr: number): number {
  const rowMax = Math.floor(rowH * 0.62);
  return lineCount === 1 ? rowMax
    : Math.max(0, Math.min(rowMax, Math.floor((rowH - 2 * Math.round(4 * dpr)) / (1.2 * lineCount))));
}

function clampedFontSize(size: number, rowH: number, dpr: number, lineCount: number): number {
  return Math.min(Math.round(size * dpr), maximumFontSize(rowH, lineCount, dpr));
}

function cellFont(cell: TableCell, size: number): string {
  return `${cell.italic === true ? 'italic ' : ''}${cell.bold === true ? '600 ' : ''}${size}px ${cell.fontFamily ?? 'system-ui, sans-serif'}`;
}

function textLines(cell: TableCell): string[] { return cell.text.split(/\r\n|\r|\n/); }

function widestLine(ctx: CanvasRenderingContext2D, lines: readonly string[]): number {
  let widest = 0;
  for (const line of lines) widest = Math.max(widest, ctx.measureText(line).width);
  return widest;
}

/**
 * The bitmap font size a cell's text is drawn at, leaving `ctx` in the last
 * font it tried. `room` is the width inside the cell's padding.
 */
function cellFontSize(ctx: CanvasRenderingContext2D, cell: TableCell, lines: readonly string[], rowH: number,
  room: number, o: ChartTableOptions, dpr: number): number {
  const px = (v: number): number => Math.round(v * dpr);
  // Shrink the type when a stretched row is shorter than the declared
  // font, so a tall grid in a short pane stays legible instead of
  // overlapping into its neighbours.
  const rowMax = maximumFontSize(rowH, lines.length, dpr);
  let size: number;
  if (cell.fontSize === undefined && o.fontSize === 'auto') {
    // Fit: as large as the row allows, then shrunk until the text also
    // fits its column, so one long label sizes only itself down.
    const singleLine = lines.length === 1;
    const floor = singleLine ? px(6) : Math.min(px(6), rowMax);
    size = singleLine ? Math.max(floor, rowMax) : rowMax;
    ctx.font = cellFont(cell, size);
    const step = singleLine ? Math.max(1, px(1)) : 1;
    while (size > floor && widestLine(ctx, lines) > room) {
      size = singleLine ? size - step : Math.max(floor, size - step);
      ctx.font = cellFont(cell, size);
    }
  } else {
    size = clampedFontSize(cell.fontSize ?? (o.fontSize === 'auto' ? 11 : o.fontSize), rowH, dpr, lines.length);
  }
  return size;
}

interface PositionedCell {
  cell: TableCell;
  row: number;
  col: number;
  rowSpan: number;
  colSpan: number;
}

/** Validate before publishing rows so a rejected merge leaves the previous grid usable. */
function positionCells(rows: readonly (readonly TableCell[])[]): { cols: number; cells: PositionedCell[] } {
  let cols = 0;
  for (const row of rows) cols = Math.max(cols, row.length);
  // Store covered intervals, not every grid slot: ragged rows can leave a
  // large empty rectangle inside a perfectly valid merged cell.
  const covered = new Map<number, { from: number; to: number }[]>();
  const cells: PositionedCell[] = [];
  for (let r = 0; r < rows.length; r++) {
    for (let c = 0; c < rows[r]!.length; c++) { // both loops stay inside the rows as given
      const cell = rows[r]![c]!;
      if (cell.tooltip !== undefined && typeof cell.tooltip !== 'string') throw new TypeError('Table tooltip must be text');
      const rowSpan = cell.rowSpan === undefined ? 1 : cell.rowSpan;
      const colSpan = cell.colSpan === undefined ? 1 : cell.colSpan;
      if (!Number.isSafeInteger(rowSpan) || rowSpan < 1 || !Number.isSafeInteger(colSpan) || colSpan < 1) {
        throw new RangeError('Table spans must be positive safe integers');
      }
      if (rowSpan > rows.length - r || colSpan > cols - c) throw new RangeError('Table span exceeds the grid bounds');
      if (rowSpan > 1 || colSpan > 1) {
        for (let y = r; y < r + rowSpan; y++) {
          let occupied = covered.get(y);
          if (occupied === undefined) { occupied = []; covered.set(y, occupied); }
          if (occupied.some(range => c < range.to && range.from < c + colSpan)) throw new RangeError('Table spans overlap');
          occupied.push({ from: c, to: c + colSpan });
        }
      } else if (covered.get(r)?.some(range => range.from <= c && c < range.to)) continue;
      cells.push({ cell, row: r, col: c, rowSpan, colSpan });
    }
  }
  return { cols, cells };
}

/**
 * Each column's width, from the widest cell in it.
 *
 * Measured at the size each cell will actually be drawn at, because a cell may
 * carry its own `fontSize` and a row may be short enough to shrink one, and a
 * column sized against the wrong size is a column that still does not fit.
 * Automatic fonts use an 11px baseline instead: fitting them here would size
 * the column to the text and the text to the column at once.
 *
 * Returned in media px, the units every other width here is in.
 */
function measuredColumns(
  ctx: CanvasRenderingContext2D,
  cells: readonly PositionedCell[],
  cols: number,
  cellHeights: readonly number[],
  o: ChartTableOptions,
  dpr: number,
): number[] {
  const widths = Array<number>(cols).fill(MIN_AUTO_COLUMN);
  const padding = 10;
  const widthOf = ({ cell }: PositionedCell, rowH: number): number => {
    if (cell.text === '') return 0;
    const lines = textLines(cell);
    const declaredSize = cell.fontSize ?? o.fontSize;
    const size = declaredSize === 'auto' ? Math.round(11 * dpr)
      : clampedFontSize(declaredSize, rowH, dpr, lines.length);
    if (size <= 0) return 0;
    ctx.font = cellFont(cell, size);
    return widestLine(ctx, lines) / dpr + padding;
  };
  // cellHeights holds one height per cell, and every cell's columns lie inside the
  // grid: positionCells refuses a span past it.
  for (let i = 0; i < cells.length; i++) {
    const entry = cells[i]!;
    if (entry.colSpan === 1) widths[entry.col] = Math.max(widths[entry.col]!, widthOf(entry, cellHeights[i]!));
  }
  // A merged heading should enlarge only the columns it covers, after their
  // ordinary content has established the column proportions.
  for (let i = 0; i < cells.length; i++) {
    const entry = cells[i]!;
    if (entry.colSpan === 1) continue;
    let current = 0;
    for (let c = entry.col; c < entry.col + entry.colSpan; c++) current += widths[c]!;
    const extra = Math.max(0, widthOf(entry, cellHeights[i]!) - current) / entry.colSpan;
    for (let c = entry.col; c < entry.col + entry.colSpan; c++) widths[c]! += extra;
  }
  return widths;
}

/** The narrowest an automatic column goes, so an empty one is still a column. */
const MIN_AUTO_COLUMN = 28;

/** Top-left corner of the grid for a position keyword, in media px. */
export function tableOrigin(
  position: TablePosition,
  margin: number,
  w: number,
  h: number,
  plotW: number,
  plotH: number,
): { x: number; y: number } {
  const [vert, horz] = position.split('-') as ['top' | 'middle' | 'bottom', 'left' | 'center' | 'right'];
  const x = horz === 'left' ? margin : horz === 'right' ? plotW - w - margin : (plotW - w) / 2;
  const y = vert === 'top' ? margin : vert === 'bottom' ? plotH - h - margin : (plotH - h) / 2;
  return { x, y };
}

interface CellHit { x: number; y: number; w: number; h: number; key: string; tooltip: string }
let nextTableId = 0;

/** Bound work by the visible height as well as wrapping width, even for a very long word. */
function tooltipLines(ctx: CanvasRenderingContext2D, text: string, width: number, limit: number): string[] {
  const lines: string[] = [];
  for (const line of text.split(/\r\n|\r|\n/)) {
    const chars = Array.from(line);
    if (chars.length === 0) lines.push('');
    for (let start = 0; start < chars.length && lines.length < limit;) {
      let lo = 0, hi = chars.length - start;
      while (lo < hi) {
        const mid = Math.ceil((lo + hi) / 2);
        if (ctx.measureText(chars.slice(start, start + mid).join('')).width <= width) lo = mid;
        else hi = mid - 1;
      }
      let count = Math.max(1, lo);
      if (start + count < chars.length) {
        for (let i = count - 1; i > 0; i--) if (/\s/.test(chars[start + i]!)) { count = i + 1; break; } // before start + count
      }
      lines.push(chars.slice(start, start + count).join(''));
      start += count;
    }
    if (lines.length >= limit) break;
  }
  return lines;
}

export class ChartTable implements IPrimitive {
  private _rows: readonly (readonly TableCell[])[] = [];
  private _grid: { cols: number; cells: PositionedCell[] } = { cols: 0, cells: [] };
  private _opts: ChartTableOptions;
  private _host: PrimitiveHost | null = null;
  /** Last drawn rect in media px, for hit-testing without recomputing layout. */
  private _rect: { x: number; y: number; w: number; h: number } | null = null;
  private readonly _hitId = `table-tooltip:${++nextTableId}`;
  private _revision = 0;
  private _hits: CellHit[] = [];
  private _size: { width: number; height: number; dpr: number } | null = null;

  public constructor(options: Partial<ChartTableOptions> = {}) {
    this._opts = { ...DEFAULT_CHART_TABLE_OPTIONS, ...options };
  }

  public attached(host: PrimitiveHost): void { this._host = host; }
  public detached(): void { this._host = null; this._clearHits(); }
  public zOrder(): ZOrder { return 'top'; }

  public options(): Readonly<ChartTableOptions> { return this._opts; }

  public setOptions(patch: Partial<ChartTableOptions>): void {
    this._opts = { ...this._opts, ...patch };
    this._clearHits();
    this._host?.requestUpdate();
  }

  /** Replace the grid atomically. Ragged rows share the maximum column count; covered cells are ignored. */
  public setRows(rows: readonly (readonly TableCell[])[]): void {
    const grid = positionCells(rows);
    this._rows = rows;
    this._grid = grid;
    this._clearHits();
    this._host?.requestUpdate();
  }

  public rows(): readonly (readonly TableCell[])[] { return this._rows; }

  private _clearHits(): void {
    this._rect = null; this._hits = []; this._size = null; this._revision++;
  }

  private _sameSize(rc: PrimitiveRenderContext): boolean {
    return this._size?.width === rc.plotWidth && this._size.height === rc.plotHeight && this._size.dpr === rc.dpr;
  }

  public draw(ctx: CanvasRenderingContext2D, rc: PrimitiveRenderContext): void {
    if (!this._sameSize(rc)) this._clearHits();
    this._size = { width: rc.plotWidth, height: rc.plotHeight, dpr: rc.dpr };
    this._rect = null;
    this._hits = [];
    const rows = this._rows;
    if (rows.length === 0) return;
    const o = this._opts;
    const dpr = rc.dpr;
    const { cols, cells } = this._grid;
    if (cols === 0) return;

    // Row tops and the total height, from the weights and the base cell height.
    const weights = rows.map((_, r) => {
      const w2 = o.rowWeights?.[r];
      return typeof w2 === 'number' && w2 > 0 ? w2 : 1;
    });
    const weightTotal = weights.reduce((a, b) => a + b, 0);
    let unit = o.cellHeight;
    let h = unit * weightTotal;
    if (o.heightPercent !== undefined && o.heightPercent > 0) {
      h = (rc.plotHeight * o.heightPercent) / 100;
      unit = h / weightTotal;
    }
    // weights, rowY and rowHeights hold one entry per row, and every cell sits in one;
    // only the edge below the last row needs its fallback.
    const rowY: number[] = [];
    for (let r = 0, acc = 0; r < rows.length; r++) { rowY.push(acc); acc += unit * weights[r]!; }
    const rowHeights = weights.map((weight) => Math.round(unit * weight * dpr));
    const cellHeights = cells.map(entry => entry.rowSpan === 1 ? rowHeights[entry.row]!
      : Math.round((rowY[entry.row + entry.rowSpan] ?? h) * dpr) - Math.round(rowY[entry.row]! * dpr));
    ctx.save();
    const edges = columnEdges(
      o.cellWidth === 'auto' ? measuredColumns(ctx, cells, cols, cellHeights, o, dpr) : o.cellWidth,
      cols,
    );
    let colX = edges.x;
    let w = edges.total;
    // A percentage stretches the grid to the pane it sits in. The columns keep
    // their declared proportions, so a heatmap with a wide year column still
    // reads correctly at any width.
    if (o.widthPercent !== undefined && o.widthPercent > 0 && w > 0) {
      const target = (rc.plotWidth * o.widthPercent) / 100;
      const k = target / w;
      colX = colX.map((v) => v * k);
      w = target;
    }
    const origin = tableOrigin(o.position, o.margin, w, h, rc.plotWidth, rc.plotHeight);
    this._rect = { x: origin.x, y: origin.y, w, h };

    const px = (v: number): number => Math.round(v * dpr);
    const ox = px(origin.x);
    const oy = px(origin.y);

    if (o.background !== undefined) {
      ctx.fillStyle = o.background;
      ctx.fillRect(ox, oy, px(w), px(h));
    }

    ctx.textBaseline = 'middle';
    // One height per cell and one edge per column: only the edge after the last
    // column needs its fallback.
    for (let i = 0; i < cells.length; i++) {
      const { cell, row: r, col: c, colSpan } = cells[i]!;
      const cellTop = oy + px(rowY[r]!);
      const rowH = cellHeights[i]!;
      const cellLeft = ox + px(colX[c]!);
      const endX = colX[c + colSpan] ?? w;
      const cellW = colSpan === 1 ? px(endX - colX[c]!) : px(endX) - px(colX[c]!);

      if (cell.tooltip) {
        const x = Math.max(0, cellLeft / dpr), y = Math.max(0, cellTop / dpr);
        const right = Math.min(rc.plotWidth, (cellLeft + cellW) / dpr);
        const bottom = Math.min(rc.plotHeight, (cellTop + rowH) / dpr);
        if (right > x && bottom > y) this._hits.push({ x, y, w: right - x, h: bottom - y,
          key: `${this._hitId}:${this._revision}:${r}:${c}`, tooltip: cell.tooltip });
      }

      if (cell.bgColor !== undefined) {
        ctx.fillStyle = cell.bgColor;
        ctx.fillRect(cellLeft, cellTop, cellW, rowH);
      }
      if (o.borderColor !== undefined && o.borderWidth > 0) {
        ctx.strokeStyle = o.borderColor;
        ctx.lineWidth = Math.max(1, px(o.borderWidth));
        ctx.strokeRect(cellLeft, cellTop, cellW, rowH);
      }
      if (cell.text === '') continue;

      const pad = px(4);
      // A cell draws inside its own cell, always. The auto font path shrinks
      // text until it fits, but a fixed size has nothing stopping it, and a
      // reading wider than its column was simply painted across the column
      // beside it: two numbers on top of each other, both unreadable, and
      // nothing about the grid to say which belonged where. Clipping makes
      // an over-long cell look cut off, which is a thing a reader can see
      // and act on.
      ctx.save();
      ctx.beginPath();
      ctx.rect(cellLeft, cellTop, cellW, rowH);
      ctx.clip();
      const lines = textLines(cell);
      const size = cellFontSize(ctx, cell, lines, rowH, cellW - pad * 2, o, dpr);
      if (size <= 0) { ctx.restore(); continue; }
      ctx.font = cellFont(cell, size);
      // A cell with a fill picks its own readable ink; one without falls back
      // to the axis colour, which is legible on either theme's background.
      ctx.fillStyle = cell.textColor
        ?? (cell.bgColor !== undefined ? contrastText(cell.bgColor) : rc.theme.axisText);
      const align = cell.align ?? 'center';
      ctx.textAlign = align;
      const tx = align === 'left' ? cellLeft + pad
        : align === 'right' ? cellLeft + cellW - pad
        : cellLeft + cellW / 2;
      const lineHeight = size * 1.2;
      const blockHeight = lines.length * lineHeight;
      const inset = Math.min(pad, Math.max(0, (rowH - blockHeight) / 2));
      const firstY = cell.verticalAlign === 'top' ? cellTop + inset + lineHeight / 2
        : cell.verticalAlign === 'bottom' ? cellTop + rowH - inset - blockHeight + lineHeight / 2
        : cellTop + rowH / 2 - (lines.length - 1) * lineHeight / 2;
      for (let line = 0; line < lines.length; line++) ctx.fillText(lines[line]!, tx, firstY + line * lineHeight);
      ctx.restore();
    }
    if (o.frameColor !== undefined && (o.frameWidth ?? 1) > 0) {
      ctx.strokeStyle = o.frameColor;
      ctx.lineWidth = Math.max(1, px(o.frameWidth ?? 1));
      ctx.strokeRect(ox, oy, px(w), px(h));
    }
    this._drawTooltip(ctx, rc);
    ctx.restore();
  }

  private _drawTooltip(ctx: CanvasRenderingContext2D, rc: PrimitiveRenderContext): void {
    if (rc.hoverId !== (this._opts.id ?? this._hitId) || !rc.hoverKey) return;
    const hit = this._hits.find(cell => cell.key === rc.hoverKey);
    const d = rc.dpr, width = rc.plotWidth * d, height = rc.plotHeight * d;
    if (!hit || width <= 10 * d || height <= 6 * d) return;
    ctx.save();
    ctx.font = `${11 * d}px system-ui, sans-serif`;
    ctx.textAlign = 'left'; ctx.textBaseline = 'middle';
    const padX = 5 * d, padY = 3 * d, lineHeight = 11 * d * 1.35;
    const lines = tooltipLines(ctx, hit.tooltip, width - 2 * padX, Math.ceil((height - 2 * padY) / lineHeight));
    const w = Math.min(width, widestLine(ctx, lines) + 2 * padX), h = lines.length * lineHeight + 2 * padY;
    const x = Math.max(0, Math.min((hit.x + hit.w / 2) * d - w / 2, width - w));
    const above = hit.y * d - 8 * d - h;
    const y = Math.max(0, Math.min(above >= 0 ? above : (hit.y + hit.h) * d + 8 * d, height - h));
    ctx.beginPath(); ctx.rect(0, 0, width, height); ctx.clip();
    ctx.beginPath(); roundRectPath(ctx, x, y, w, h, Math.min(3 * d, w / 2, h / 2));
    ctx.fillStyle = rc.theme.axisText; ctx.fill();
    ctx.fillStyle = contrastText(rc.theme.axisText);
    for (let i = 0; i < lines.length; i++) ctx.fillText(lines[i]!, x + padX, y + padY + (i + 0.5) * lineHeight);
    ctx.restore();
  }

  public hitTest(x: number, y: number, rc?: PrimitiveRenderContext): PrimitiveHit | null {
    if (rc !== undefined && !this._sameSize(rc)) { this._clearHits(); return null; }
    if (!Number.isFinite(x) || !Number.isFinite(y) || !this._size
      || x < 0 || y < 0 || x > this._size.width || y > this._size.height) return null;
    const r = this._rect;
    if (r === null) return null;
    for (const cell of this._hits) {
      if (x >= cell.x && x < cell.x + cell.w && y >= cell.y && y < cell.y + cell.h) {
        return { externalId: this._opts.id ?? this._hitId, hoverKey: cell.key, zOrder: 'top', distance: 0, cursor: 'default' };
      }
    }
    if (this._opts.id === undefined) return null;
    if (x < r.x || x > r.x + r.w || y < r.y || y > r.y + r.h) return null;
    return { externalId: this._opts.id, zOrder: 'top', distance: 0, cursor: 'default' };
  }
}
