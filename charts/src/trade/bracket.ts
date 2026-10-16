/**
 * Bracket group (ARCHITECTURE.md §9.1). SL + Target lines tied to a position,
 * with theme-derived shaded risk/reward zones, rounded "SL/TP @ price" chips at
 * the left edge, and an R:R chip near entry: the core advanced-trade-management
 * visualisation. The SL/TP lines thicken on hover and are draggable (OCO modify).
 */
import type { IPrimitive, PrimitiveHost, PrimitiveRenderContext, PrimitiveHit, ZOrder } from 'openalgo-charts';
import type { OrderSide } from './types';
import { riskReward } from './pnl';
import { withAlpha, drawPill } from '../render/pill';

export interface BracketState {
  symbol: string;
  side: OrderSide;
  entry: number;
  stop: number;
  target: number;
}

export class BracketGroup implements IPrimitive {
  private _state: BracketState;
  private _host: PrimitiveHost | null = null;

  public constructor(state: BracketState) {
    this._state = state;
  }

  public attached(host: PrimitiveHost): void { this._host = host; }
  public detached(): void { this._host = null; }
  public zOrder(): ZOrder { return 'bottom'; } // zones behind the candles

  public get state(): BracketState { return this._state; }

  public update(state: BracketState): void {
    this._state = state;
    this._host?.requestUpdate();
  }

  public autoscaleInfo(): { min: number; max: number } {
    return {
      min: Math.min(this._state.stop, this._state.target, this._state.entry),
      max: Math.max(this._state.stop, this._state.target, this._state.entry),
    };
  }

  public draw(ctx: CanvasRenderingContext2D, rc: PrimitiveRenderContext): void {
    const { entry, stop, target } = this._state;
    const dpr = rc.dpr;
    const xEnd = Math.round(rc.plotWidth * dpr);
    const yEntry = rc.priceScale.priceToY(entry) * dpr;
    const yStop = rc.priceScale.priceToY(stop) * dpr;
    const yTarget = rc.priceScale.priceToY(target) * dpr;

    ctx.save();
    // risk zone (entry to stop) and reward zone (entry to target), theme-derived
    ctx.fillStyle = withAlpha(rc.theme.loss, 0.09);
    ctx.fillRect(0, Math.min(yEntry, yStop), xEnd, Math.abs(yStop - yEntry));
    ctx.fillStyle = withAlpha(rc.theme.profit, 0.09);
    ctx.fillRect(0, Math.min(yEntry, yTarget), xEnd, Math.abs(yTarget - yEntry));

    // SL and TP lines + rounded "SL @ price" chips at the left edge
    ctx.font = `500 ${10 * dpr}px system-ui, sans-serif`;
    ctx.textBaseline = 'middle';
    for (const [yRaw, color, tag, price, id] of [
      [yStop, rc.theme.loss, 'SL', stop, `bracket-sl:${this._state.symbol}`],
      [yTarget, rc.theme.profit, 'TP', target, `bracket-tp:${this._state.symbol}`],
    ] as const) {
      const y = Math.round(yRaw) + 0.5;
      const hovered = rc.hoverId === id || rc.dragId === id;
      ctx.strokeStyle = color;
      const baseW = Math.max(1, Math.round(dpr));
      ctx.lineWidth = hovered ? baseW + Math.round(dpr) : baseW;
      ctx.setLineDash([4 * dpr, 4 * dpr]);
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(xEnd, y);
      ctx.stroke();
      ctx.setLineDash([]);
      drawPill(ctx, 4 * dpr, y, `${tag} ${rc.priceScale.format(price)}`, 16 * dpr, 6 * dpr, {
        fill: withAlpha(color, hovered ? 0.28 : 0.16), text: color, border: withAlpha(color, 0.55), radius: 3 * dpr,
        backplate: rc.theme.background === 'transparent' ? undefined : rc.theme.background,
      });
    }

    // R:R chip near entry
    const rr = riskReward(entry, stop, target);
    if (rr !== null) {
      drawPill(ctx, 4 * dpr, Math.round(yEntry) - 12 * dpr, `R:R ${rr.toFixed(2)}`, 16 * dpr, 6 * dpr, {
        fill: withAlpha(rc.theme.axisText, 0.16), text: rc.theme.axisText, radius: 3 * dpr,
        backplate: rc.theme.background === 'transparent' ? undefined : rc.theme.background,
      });
    }
    ctx.restore();
  }

  public hitTest(x: number, y: number, rc: PrimitiveRenderContext): PrimitiveHit | null {
    if (x < 0 || x > rc.plotWidth) return null;
    const yStop = rc.priceScale.priceToY(this._state.stop);
    const yTarget = rc.priceScale.priceToY(this._state.target);
    const dStop = Math.abs(y - yStop);
    const dTarget = Math.abs(y - yTarget);
    if (dStop <= 4) return { externalId: `bracket-sl:${this._state.symbol}`, zOrder: 'bottom', distance: dStop, cursor: 'ns-resize' };
    if (dTarget <= 4) return { externalId: `bracket-tp:${this._state.symbol}`, zOrder: 'bottom', distance: dTarget, cursor: 'ns-resize' };
    return null;
  }
}
