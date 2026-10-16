/**
 * Position marker (ARCHITECTURE.md §9.1). A line at the average entry price
 * with a broker-style segmented pill group ([LONG|SHORT][qty][P&L (pct)][close]),
 * a compact avg-price tag on the axis, and a shaded entry-to-LTP band colored by
 * P&L sign. Updates cheaply on every LTP tick. The close segment hit-tests as
 * `position:<symbol>::close` (wire it to your square-off flow).
 */
import type { IPrimitive, PrimitiveHost, PrimitiveRenderContext, PrimitiveHit, ZOrder } from 'openalgo-charts';
import type { Position } from './types';
import { unrealizedPnl, unrealizedPnlPercent } from './pnl';
import { withAlpha, shade, contrastText, drawPillGroup } from '../render/pill';
// The one axis tag routine, which price lines and levels draw with too: a pure function, by path.
import { drawAxisTag } from '../primitives/axis-tag';

const TAG_H = 18;
const GAP = 2;

export class PositionMarker implements IPrimitive {
  private _position: Position;
  private _ltp = NaN;
  private _host: PrimitiveHost | null = null;
  private _group: { x0: number; x1: number; closeX0: number } | null = null;
  private readonly _extent: number;

  public constructor(position: Position, options: { extentFromRight?: number } = {}) {
    this._position = position;
    this._extent = Math.max(0.1, Math.min(1, options.extentFromRight ?? 0.5));
  }

  public attached(host: PrimitiveHost): void { this._host = host; }
  public detached(): void { this._host = null; }
  public zOrder(): ZOrder { return 'normal'; }

  public get position(): Position { return this._position; }

  public update(position: Position): void {
    this._position = position;
    this._host?.requestUpdate();
  }

  public setLtp(ltp: number): void {
    this._ltp = ltp;
    this._host?.requestUpdate();
  }

  public autoscaleInfo(): { min: number; max: number } {
    return { min: this._position.avgPrice, max: this._position.avgPrice };
  }

  public draw(ctx: CanvasRenderingContext2D, rc: PrimitiveRenderContext): void {
    this._group = null;
    if (this._position.netQty === 0) return;
    const dpr = rc.dpr;
    const entryY = Math.round(rc.priceScale.priceToY(this._position.avgPrice) * dpr) + 0.5;
    if (entryY < 0 || entryY > rc.plotHeight * dpr) return;
    const xEnd = Math.round(rc.plotWidth * dpr);
    const pnl = Number.isNaN(this._ltp) ? 0 : unrealizedPnl(this._position, this._ltp);
    const pnlColor = pnl >= 0 ? rc.theme.profit : rc.theme.loss;
    const long = this._position.netQty > 0;
    const sideColor = long ? rc.theme.buy : rc.theme.sell;
    const id = `position:${this._position.symbol}`;
    const active = rc.hoverId === id || rc.hoverId === `${id}::close`;

    const xStart = Math.round(rc.plotWidth * (1 - this._extent) * dpr);

    ctx.save();
    // entry line (solid, side-colored on hover)
    ctx.strokeStyle = active ? sideColor : rc.theme.axisText;
    ctx.lineWidth = Math.max(1, Math.round(dpr)) + (active ? Math.round(dpr) : 0);
    ctx.beginPath();
    ctx.moveTo(xStart, entryY);
    ctx.lineTo(xEnd, entryY);
    ctx.stroke();

    // shaded band from entry to LTP, colored by P&L sign (theme-derived)
    if (!Number.isNaN(this._ltp)) {
      const ltpY = Math.round(rc.priceScale.priceToY(this._ltp) * dpr);
      ctx.fillStyle = withAlpha(pnlColor, 0.1);
      ctx.fillRect(xStart, Math.min(entryY, ltpY), xEnd - xStart, Math.abs(ltpY - entryY));
    }

    ctx.font = `500 ${11 * dpr}px system-ui, sans-serif`;
    ctx.textBaseline = 'middle';
    ctx.textAlign = 'left';
    const boxH = TAG_H * dpr;
    const padX = 6 * dpr;
    const r = 3 * dpr;

    // compact axis tag: avg entry price, colored by P&L sign
    drawAxisTag(ctx, rc, entryY, rc.priceScale.format(this._position.avgPrice), pnlColor, contrastText(pnlColor), boxH, false);

    // segmented pill group: [LONG|SHORT][qty][±pnl (±pct)][close]
    const surface = rc.theme.background === 'transparent' ? withAlpha(sideColor, 0.14) : rc.theme.background;
    const surfaceText = rc.theme.background === 'transparent' ? rc.theme.axisText : contrastText(rc.theme.background);
    const border = withAlpha(rc.theme.axisText, active ? 0.75 : 0.5);
    const closeHovered = rc.hoverId === `${id}::close`;
    const pct = Number.isNaN(this._ltp) ? 0 : unrealizedPnlPercent(this._position, this._ltp);
    const dir = long ? 'LONG' : 'SHORT';
    const qtyText = String(Math.abs(this._position.netQty));
    const pnlText = `${pnl >= 0 ? '+' : ''}${pnl.toFixed(2)} (${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%)`;

    this._group = drawPillGroup(ctx, xStart, entryY, [
      { text: dir, fill: active ? shade(sideColor, 0.12) : sideColor, textColor: contrastText(sideColor), border: shade(sideColor, -0.25) },
      { text: qtyText, fill: surface, textColor: surfaceText, border },
      { text: pnlText, fill: surface, textColor: pnlColor, border: withAlpha(pnlColor, 0.65) },
      {
        close: true,
        fill: closeHovered ? sideColor : surface,
        textColor: closeHovered ? contrastText(sideColor) : surfaceText,
        border: closeHovered ? sideColor : border,
      },
    ], {
      height: boxH, padX, radius: r, gap: GAP * dpr,
      backplate: rc.theme.background === 'transparent' ? undefined : rc.theme.background, dpr,
    });
    ctx.restore();
  }

  public hitTest(x: number, y: number, rc: PrimitiveRenderContext): PrimitiveHit | null {
    if (this._position.netQty === 0 || x < 0 || x > rc.plotWidth) return null;
    const lineY = rc.priceScale.priceToY(this._position.avgPrice);
    const distance = Math.abs(y - lineY);
    const id = `position:${this._position.symbol}`;
    const g = this._group;
    if (g !== null && distance <= TAG_H / 2 + 1 && x >= g.x0 && x <= g.x1) {
      if (x >= g.closeX0) return { externalId: `${id}::close`, zOrder: 'normal', distance, cursor: 'pointer' };
      return { externalId: id, zOrder: 'normal', distance, cursor: 'pointer' };
    }
    // line-proximity hits only along the visible (partial) span
    if (distance > 4 || x < rc.plotWidth * (1 - this._extent) - 8) return null;
    return { externalId: id, zOrder: 'normal', distance, cursor: 'pointer' };
  }
}
