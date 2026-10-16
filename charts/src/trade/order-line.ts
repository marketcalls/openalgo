/**
 * Working-order line (ARCHITECTURE.md §9.1). A horizontal dashed line at the
 * order price, colored by side, with a broker-style segmented pill group on the
 * line ([SIDE][qty][TYPE price ±LTP-distance][close]) and a compact price tag on
 * the axis. Pending (un-acked) orders draw dimmed; partial fills show progress
 * (3/10). Hover thickens the line (hit-test `order:<id>`, ns-resize cursor for
 * drag-to-modify; the close segment hit-tests as `order:<id>::close`).
 */
import type { IPrimitive, PrimitiveHost, PrimitiveRenderContext, PrimitiveHit, ZOrder } from 'openalgo-charts';
import type { Order } from './types';
import { contrastText, withAlpha, shade, drawPillGroup } from '../render/pill';
// The one axis tag routine, which price lines and levels draw with too: a pure function, by path.
import { drawAxisTag } from '../primitives/axis-tag';

const TAG_H = 18;
const GAP = 2;

export class WorkingOrderLine implements IPrimitive {
  private _order: Order;
  private _ltp = NaN;
  private _host: PrimitiveHost | null = null;
  private _group: { x0: number; x1: number; closeX0: number } | null = null;
  private readonly _extent: number;
  /** Pre-drag price, self-captured on the first dragged frame (drag ghost). */
  private _ghost: number | null = null;

  public constructor(order: Order, options: { extentFromRight?: number } = {}) {
    this._order = order;
    this._extent = Math.max(0.1, Math.min(1, options.extentFromRight ?? 0.5));
  }

  public attached(host: PrimitiveHost): void { this._host = host; }
  public detached(): void { this._host = null; }
  public zOrder(): ZOrder { return 'normal'; }

  public get order(): Order { return this._order; }

  public update(order: Order): void {
    this._order = order;
    this._host?.requestUpdate();
  }

  public setLtp(ltp: number): void {
    this._ltp = ltp;
    this._host?.requestUpdate(); // refresh the distance-to-LTP label
  }

  public autoscaleInfo(): { min: number; max: number } {
    const p = this._order.triggerPrice ?? this._order.price;
    return { min: p, max: p };
  }

  private _price(): number {
    return this._order.triggerPrice ?? this._order.price;
  }

  public draw(ctx: CanvasRenderingContext2D, rc: PrimitiveRenderContext): void {
    this._group = null;
    const price = this._price();
    const dpr = rc.dpr;
    const y = Math.round(rc.priceScale.priceToY(price) * dpr) + 0.5;
    if (y < 0 || y > rc.plotHeight * dpr) return;
    const side = this._order.side === 'BUY' ? rc.theme.buy : rc.theme.sell;
    const active = rc.hoverId === `order:${this._order.id}` || rc.hoverId === `order:${this._order.id}::close`
      || rc.dragId === `order:${this._order.id}`;
    const pending = this._order.status === 'pending';
    const color = pending ? withAlpha(side, 0.55) : active ? shade(side, 0.1) : side;
    const xEnd = Math.round(rc.plotWidth * dpr);
    const xStart = Math.round(rc.plotWidth * (1 - this._extent) * dpr);

    // drag ghost: capture the price on the first dragged frame, clear after
    const dragging = rc.dragId === `order:${this._order.id}`;
    if (dragging && this._ghost === null) this._ghost = price;
    else if (!dragging && this._ghost !== null) this._ghost = null;

    ctx.save();
    if (this._ghost !== null && Math.abs(this._ghost - price) > 1e-9) {
      const gy = Math.round(rc.priceScale.priceToY(this._ghost) * dpr) + 0.5;
      if (gy >= 0 && gy <= rc.plotHeight * dpr) {
        ctx.strokeStyle = withAlpha(side, 0.35);
        ctx.lineWidth = Math.max(1, Math.round(dpr));
        ctx.setLineDash([2 * dpr, 3 * dpr]);
        ctx.beginPath();
        ctx.moveTo(xStart, gy);
        ctx.lineTo(xEnd, gy);
        ctx.stroke();
        ctx.setLineDash([]);
      }
    }
    if (dragging) { // soft emphasis halo while dragging
      ctx.strokeStyle = withAlpha(side, 0.18);
      ctx.lineWidth = 5 * dpr;
      ctx.beginPath();
      ctx.moveTo(xStart, y);
      ctx.lineTo(xEnd, y);
      ctx.stroke();
    }
    ctx.strokeStyle = color;
    const baseW = Math.max(1, Math.round(dpr));
    ctx.lineWidth = active ? baseW + Math.round(dpr) : baseW;
    ctx.setLineDash([6 * dpr, 4 * dpr]);
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

    // compact axis tag: just the price, colored by side
    const px = rc.priceScale.format(price);
    drawAxisTag(ctx, rc, y, px, pending ? withAlpha(side, 0.7) : side, contrastText(side), boxH, false);

    // segmented pill group on the line: [SIDE][qty][TYPE price ±dist][close]
    const surface = rc.theme.background === 'transparent' ? withAlpha(side, 0.14) : rc.theme.background;
    const surfaceText = rc.theme.background === 'transparent' ? rc.theme.axisText : contrastText(rc.theme.background);
    const border = withAlpha(rc.theme.axisText, active ? 0.75 : 0.5);
    const closeHovered = rc.hoverId === `order:${this._order.id}::close`;
    if (pending) ctx.globalAlpha = 0.75;

    const qtyText = this._order.filledQty > 0 ? `${this._order.filledQty}/${this._order.qty}` : String(this._order.qty - this._order.filledQty);
    let info = `${this._order.type} ${px}`;
    if (!Number.isNaN(this._ltp)) {
      const diff = price - this._ltp;
      info += `  ${diff >= 0 ? '+' : ''}${rc.priceScale.format(diff)}`;
    }

    this._group = drawPillGroup(ctx, xStart, y, [
      { text: this._order.side, fill: active ? shade(side, 0.12) : side, textColor: contrastText(side), border: shade(side, -0.25) },
      { text: qtyText, fill: surface, textColor: surfaceText, border },
      { text: info, fill: surface, textColor: surfaceText, border },
      {
        close: true,
        fill: closeHovered ? side : surface,
        textColor: closeHovered ? contrastText(side) : surfaceText,
        border: closeHovered ? side : border,
      },
    ], {
      height: boxH, padX, radius: r, gap: GAP * dpr,
      backplate: rc.theme.background === 'transparent' ? undefined : rc.theme.background, dpr,
    });
    ctx.restore();
  }

  public hitTest(x: number, y: number, rc: PrimitiveRenderContext): PrimitiveHit | null {
    if (x < 0 || x > rc.plotWidth) return null;
    const lineY = rc.priceScale.priceToY(this._price());
    const distance = Math.abs(y - lineY);
    const g = this._group;
    if (g !== null && distance <= TAG_H / 2 + 1 && x >= g.x0 && x <= g.x1) {
      if (x >= g.closeX0) {
        return { externalId: `order:${this._order.id}::close`, zOrder: 'normal', distance, cursor: 'pointer' };
      }
      return { externalId: `order:${this._order.id}`, zOrder: 'normal', distance, cursor: 'ns-resize' };
    }
    // line-proximity drags only along the visible (partial) span
    if (distance > 4 || x < rc.plotWidth * (1 - this._extent) - 8) return null;
    return { externalId: `order:${this._order.id}`, zOrder: 'normal', distance, cursor: 'ns-resize' };
  }
}
