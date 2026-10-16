/**
 * Horizontal price line primitive (ARCHITECTURE.md §8). The reusable base for
 * order/SL/TP/alert/indicator-level lines: a line across the plot plus a fixed
 * price-axis tag and an optional broker-style segmented pill group on the
 * line ([badge][qty][label][close]) with hover / dragging states (the chart
 * passes `hoverId`/`dragId` on the render context) and a drag ghost at the
 * pre-drag price via `setDragGhost`. Interaction semantics are unchanged from
 * the classic tag: the close segment hit-tests as `${id}::close`, everything else drags.
 */
import type { IPrimitive, PrimitiveHost, PrimitiveRenderContext, PrimitiveHit, ZOrder } from './primitive';
import { contrastText, withAlpha, shade, drawPillGroup, type PillSegment } from '../render/pill';
import { dashPattern, type CanvasLineStyle } from '../render/grid';
import { drawAxisTag } from './axis-tag';
import type { LooseOptional } from '../helpers/types';

export interface PriceLineOptions {
  price: number;
  color: string;
  /** Line thickness in media px. Default 1. */
  lineWidth?: number;
  /**
   * Two-state shorthand for `lineStyle`: `true` draws `'dashed'`. A retained
   * form rather than a deprecated one (COMPATIBILITY.md lists why); reach for
   * `lineStyle` when a line needs `'dotted'`.
   */
  dashed?: boolean;
  /**
   * Dash style, the three-way form of `dashed`. Set, it wins over the boolean;
   * unset, the boolean still decides, so a line built before this existed draws
   * exactly as it did.
   */
  lineStyle?: CanvasLineStyle;
  /** Price-axis tag text. Defaults to the formatted price. Hidden scales omit the tag. */
  label?: string;
  /** Solid colored badge segment at the start of the pill group (e.g. 'BUY', 'TP', 'SL'). */
  badge?: string;
  /** Quantity segment rendered as a neutral box after the badge. */
  qty?: string | number;
  /** Info text segment (order type, price, P&L ...): the classic left tag text. */
  leftLabel?: string;
  /**
   * Fraction of the plot width the line spans, measured from the right (price)
   * axis. 1 = full width (default); 0.3 = only the rightmost 30%, like a
   * partial-width order line. Visible scales also carry a price tag.
   */
  extentFromRight?: number;
  /** Draw a close (cancel) segment at the end of the pill group; hit-tests as `${id}::close`. */
  closeButton?: boolean;
  /** Stable id returned by hit-test (for click/drag routing). */
  id: string;
  /** Cursor hint when hovered (e.g. 'ns-resize' for draggable lines). */
  cursor?: string;
}

/** Pill/segment height in media px (shared by draw + hit-test). */
const TAG_H = 18;
/** Gap between segments in media px. */
const GAP = 2;

export class PriceLine implements IPrimitive {
  private _opts: PriceLineOptions;
  private _host: PrimitiveHost | null = null;
  private _ghostPrice: number | null = null;
  /** Pill-group geometry from the last draw (media px) for hit-testing. */
  private _group: { x0: number; x1: number; closeX0: number } | null = null;

  public constructor(opts: PriceLineOptions) {
    this._opts = opts;
  }

  public attached(host: PrimitiveHost): void {
    this._host = host;
  }

  public detached(): void {
    this._host = null;
  }

  public get price(): number {
    return this._opts.price;
  }

  /** Move the line; schedules a repaint via the host. */
  public setPrice(price: number): void {
    this._opts.price = price;
    this._host?.requestUpdate();
  }

  /** Update the info segment text (e.g. live position P&L); repaints. */
  public setLeftLabel(text: string): void {
    this._opts.leftLabel = text;
    this._host?.requestUpdate();
  }

  /**
   * Restyle in place; repaints. `id` is the hit-test handle the chart routes
   * clicks and drags through, so it is not patchable: swapping it under a
   * live drag would strand the gesture.
   *
   * A last-price line is the case this exists for: it has to follow the tick
   * direction, and only `setPrice` was updatable, so the colour was stuck at
   * whatever it was constructed with.
   */
  public setOptions(patch: Partial<Omit<PriceLineOptions, 'id'>>): void {
    this._opts = { ...this._opts, ...patch };
    this._host?.requestUpdate();
  }

  /**
   * Show a dimmed reference line at the pre-drag price while the user drags
   * (pass the original price on drag start, null on drag end to clear).
   */
  public setDragGhost(price: number | null): void {
    this._ghostPrice = price;
    this._host?.requestUpdate();
  }

  public options(): Readonly<PriceLineOptions> {
    return this._opts;
  }

  public zOrder(): ZOrder {
    return 'normal';
  }

  public autoscaleInfo(): { min: number; max: number } | null {
    return { min: this._opts.price, max: this._opts.price };
  }

  public draw(ctx: CanvasRenderingContext2D, rc: PrimitiveRenderContext): void {
    this._group = null;
    const y = Math.round(rc.priceScale.priceToY(this._opts.price) * rc.dpr) + 0.5;
    // The stroke's half-pixel offset must not discard a left tag at the lower edge.
    const tagY = rc.priceAxisSide === 'left' ? y - 0.5 : y;
    if (!Number.isFinite(y) || tagY < 0 || tagY > rc.plotHeight * rc.dpr) return;
    const dpr = rc.dpr;
    const lineWidth = this._opts.lineWidth ?? 1;
    const xEnd = Math.round(rc.plotWidth * dpr);
    const extent = Math.max(0, Math.min(1, this._opts.extentFromRight ?? 1));
    const xStart = Math.round(rc.plotWidth * (1 - extent) * dpr);
    const color = this._opts.color;
    // Hover/dragging visual states apply to interactive lines only (draggable
    // or cancellable); plain level lines stay static under the pointer.
    const interactive = this._opts.cursor !== undefined || this._opts.closeButton === true;
    const dragging = rc.dragId === this._opts.id;
    const hovered = interactive && !dragging && (rc.hoverId === this._opts.id || rc.hoverId === `${this._opts.id}::close`);
    const closeHovered = rc.hoverId === `${this._opts.id}::close`;

    ctx.save();

    // drag ghost: dimmed line at the pre-drag price (revert reference)
    if (this._ghostPrice !== null && dragging) {
      const gy = Math.round(rc.priceScale.priceToY(this._ghostPrice) * dpr) + 0.5;
      if (gy >= 0 && gy <= rc.plotHeight * dpr) {
        ctx.strokeStyle = withAlpha(color, 0.35);
        ctx.lineWidth = Math.max(1, Math.round(dpr));
        ctx.setLineDash([2 * dpr, 3 * dpr]);
        ctx.beginPath();
        ctx.moveTo(xStart, gy);
        ctx.lineTo(xEnd, gy);
        ctx.stroke();
        ctx.setLineDash([]);
      }
    }

    // soft emphasis halo while dragging (no shadowBlur: cheap wide stroke)
    if (dragging) {
      ctx.strokeStyle = withAlpha(color, 0.18);
      ctx.lineWidth = Math.max(5 * dpr, Math.round(lineWidth * dpr) + 4 * dpr);
      ctx.beginPath();
      ctx.moveTo(xStart, y);
      ctx.lineTo(xEnd, y);
      ctx.stroke();
    }

    ctx.strokeStyle = hovered || dragging ? shade(color, 0.1) : color;
    const baseW = Math.max(1, Math.round(lineWidth * dpr));
    ctx.lineWidth = hovered || dragging ? baseW + Math.round(dpr) : baseW;
    // `lineStyle` wins over `dashed`, which stays the fallback so a line built
    // before the style existed still draws exactly as it did.
    ctx.setLineDash(dashPattern(this._opts.lineStyle ?? (this._opts.dashed === true ? 'dashed' : 'solid'), dpr));
    ctx.beginPath();
    ctx.moveTo(xStart, y);
    ctx.lineTo(xEnd, y);
    ctx.stroke();
    ctx.setLineDash([]);

    ctx.font = `500 ${11 * dpr}px system-ui, sans-serif`;
    ctx.textBaseline = 'middle';
    ctx.textAlign = 'left';
    const boxH = TAG_H * dpr;
    const padX = 6 * dpr;
    const r = 3 * dpr;

    // Explicit columns confine only the axis tag; plot furniture stays put.
    drawAxisTag(ctx, rc, y, this._opts.label ?? rc.priceScale.format(this._opts.price),
      dragging || hovered ? shade(color, 0.12) : color, contrastText(color), boxH, false);

    // segmented pill group on the line: [badge][qty][label][close]
    const hasGroup = this._opts.badge !== undefined || this._opts.qty !== undefined ||
      (this._opts.leftLabel !== undefined && this._opts.leftLabel !== '') || this._opts.closeButton === true;
    if (hasGroup) {
      // neutral "surface" segments: opaque so the line doesn't run through text
      const transparentBg = rc.theme.background === 'transparent';
      const surface = transparentBg ? withAlpha(color, 0.14) : rc.theme.background;
      const surfaceText = transparentBg ? rc.theme.axisText : contrastText(rc.theme.background);
      const border = withAlpha(rc.theme.axisText, hovered || dragging ? 0.75 : 0.5);
      const segments: PillSegment[] = [];
      if (this._opts.badge !== undefined) {
        segments.push({
          text: this._opts.badge,
          fill: dragging ? shade(color, 0.2) : hovered ? shade(color, 0.12) : color,
          textColor: contrastText(color),
          border: shade(color, -0.25),
        });
      }
      if (this._opts.qty !== undefined) {
        segments.push({ text: String(this._opts.qty), fill: surface, textColor: surfaceText, border });
      }
      if (this._opts.leftLabel !== undefined && this._opts.leftLabel !== '') {
        segments.push({ text: this._opts.leftLabel, fill: surface, textColor: surfaceText, border });
      }
      if (this._opts.closeButton === true) {
        segments.push({
          close: true,
          fill: closeHovered ? color : surface,
          textColor: closeHovered ? contrastText(color) : surfaceText,
          border: closeHovered ? color : border,
        });
      }
      this._group = drawPillGroup(ctx, xStart + (extent === 1 ? 6 * dpr : 0), y, segments, {
        height: boxH, padX, radius: r, gap: GAP * dpr, backplate: transparentBg ? undefined : rc.theme.background, dpr,
      });
    }
    ctx.restore();
  }

  public hitTest(x: number, y: number, rc: PrimitiveRenderContext): PrimitiveHit | null {
    if (x < 0 || x > rc.plotWidth) return null;
    const lineY = rc.priceScale.priceToY(this._opts.price);
    const distance = Math.abs(y - lineY);
    // An unset cursor goes out as undefined below, which the pane reads as no cursor.
    // Inside the pill group (segment boxes are taller than the 4px line zone):
    // the close segment routes as a click, the rest of the group drags the line.
    const g = this._group;
    if (g !== null && distance <= TAG_H / 2 + 1 && x >= g.x0 && x <= g.x1) {
      if (this._opts.closeButton && x >= g.closeX0) {
        return { externalId: `${this._opts.id}::close`, zOrder: 'normal', distance, cursor: 'pointer' };
      }
      return { externalId: this._opts.id, zOrder: 'normal', distance, cursor: this._opts.cursor } satisfies LooseOptional<PrimitiveHit> as PrimitiveHit;
    }
    if (distance > 4) return null;
    return { externalId: this._opts.id, zOrder: 'normal', distance, cursor: this._opts.cursor } satisfies LooseOptional<PrimitiveHit> as PrimitiveHit;
  }
}
