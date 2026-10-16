/**
 * Inline Buy/Sell button panel (ARCHITECTURE.md §9). An on-chart trade
 * panel docked inside the plot: a SELL button (bid), a quantity chip, and a BUY
 * button (ask), drawn on the overlay canvas so it stays fixed while the chart
 * pans/zooms. Clicks hit-test to `${id}:sell` / `${id}:buy` / `${id}:qty`, which
 * the chart routes through `subscribeClick`: the app places the order. Prices
 * update cheaply on every tick (`setPrices` / `setMark`).
 */
import type { IPrimitive, PrimitiveHost, PrimitiveRenderContext, PrimitiveHit, ZOrder } from './primitive';
import { contrastText, roundRectPath, shade } from '../render/pill';
import type { WatermarkPosition } from './watermark';

export interface BuySellButtonsOptions {
  /** Stable id prefix; hit-tests emit `${id}:sell` / `${id}:buy` / `${id}:qty`. Default `trade`. */
  id?: string;
  /** Corner to dock to. Default `top-left`. */
  position?: WatermarkPosition;
  /**
   * Gap from the plot edges in media px. A number applies to both axes; pass
   * `{ x, y }` to offset independently (e.g. clear an OHLC legend at the top).
   */
  margin?: number | { x: number; y: number };
  /** Quantity shown in the centre chip (e.g. lots or absolute qty). */
  qty?: string | number;
  /** Buy button color (defaults to the theme `buy`). */
  buyColor?: string;
  /** Sell button color (defaults to the theme `sell`). */
  sellColor?: string;
  /** Button labels. Default `BUY` / `SELL`. */
  buyLabel?: string;
  sellLabel?: string;
  /** Show the price line above each label. Default true. */
  showPrices?: boolean;
  /**
   * Uniform size multiplier for the whole panel: box, gaps and type. Default 1.
   * A dense trading layout wants these smaller so they do not crowd the pane's
   * legend rows. Clamped to 0.6..1.5; below that the labels stop being legible.
   */
  scale?: number;
}

interface Rect { x: number; y: number; w: number; h: number; }

const BTN_W = 74;
const QTY_W = 40;
const H = 42;
const GAP = 1;
const RADIUS = 7;
/** Below ~0.6 the labels stop being legible; above 1.5 it dominates the pane. */
const MIN_SCALE = 0.6;
const MAX_SCALE = 1.5;

export class BuySellButtons implements IPrimitive {
  private readonly _id: string;
  private readonly _position: WatermarkPosition;
  private readonly _mx: number;
  private readonly _my: number;
  private readonly _scale: number;
  private readonly _btnW: number;
  private readonly _qtyW: number;
  private readonly _h: number;
  private readonly _buyLabel: string;
  private readonly _sellLabel: string;
  private readonly _showPrices: boolean;
  private _qty: string;
  private _buyColor?: string | undefined;
  private _sellColor?: string | undefined;
  private _bid = NaN;
  private _ask = NaN;
  private _host: PrimitiveHost | null = null;
  // hit rects from the last draw, in media px relative to the pane plot
  private _sellRect: Rect | null = null;
  private _buyRect: Rect | null = null;
  private _qtyRect: Rect | null = null;

  public constructor(options: BuySellButtonsOptions = {}) {
    this._id = options.id ?? 'trade';
    this._position = options.position ?? 'top-left';
    const m = options.margin ?? 12;
    this._mx = typeof m === 'number' ? m : m.x;
    this._my = typeof m === 'number' ? m : m.y;
    this._buyLabel = options.buyLabel ?? 'BUY';
    this._sellLabel = options.sellLabel ?? 'SELL';
    this._showPrices = options.showPrices ?? true;
    this._scale = Math.max(MIN_SCALE, Math.min(MAX_SCALE, options.scale ?? 1));
    this._btnW = BTN_W * this._scale;
    this._qtyW = QTY_W * this._scale;
    this._h = H * this._scale;
    this._qty = options.qty !== undefined ? String(options.qty) : '';
    this._buyColor = options.buyColor;
    this._sellColor = options.sellColor;
  }

  public attached(host: PrimitiveHost): void { this._host = host; }
  public detached(): void { this._host = null; }
  public zOrder(): ZOrder { return 'top'; }
  public autoscaleInfo(): null { return null; }

  /** Distinct bid/ask (shows a spread on the two buttons). */
  public setPrices(bid: number, ask: number): void {
    this._bid = bid; this._ask = ask;
    this._host?.requestUpdate();
  }

  /** Single mark price shown on both buttons (when there is no bid/ask). */
  public setMark(price: number): void { this.setPrices(price, price); }

  public setQty(qty: string | number): void {
    this._qty = String(qty);
    this._host?.requestUpdate();
  }

  public setColors(buyColor?: string, sellColor?: string): void {
    this._buyColor = buyColor; this._sellColor = sellColor;
    this._host?.requestUpdate();
  }

  private _origin(plotW: number, plotH: number): { x: number; y: number; w: number } {
    const w = this._btnW * 2 + this._qtyW + GAP * 2;
    const left = this._mx;
    const right = plotW - this._mx - w;
    const top = this._my;
    const bottom = plotH - this._my - this._h;
    switch (this._position) {
      case 'top-right': return { x: right, y: top, w };
      case 'bottom-left': return { x: left, y: bottom, w };
      case 'bottom-right': return { x: right, y: bottom, w };
      case 'center': return { x: (plotW - w) / 2, y: (plotH - this._h) / 2, w };
      case 'top-left':
      default: return { x: left, y: top, w };
    }
  }

  public draw(ctx: CanvasRenderingContext2D, rc: PrimitiveRenderContext): void {
    this._sellRect = this._buyRect = this._qtyRect = null;
    const dpr = rc.dpr;
    const o = this._origin(rc.plotWidth, rc.plotHeight);
    const sell = this._sellColor ?? rc.theme.sell;
    const buy = this._buyColor ?? rc.theme.buy;
    // media-px hit rects
    this._sellRect = { x: o.x, y: o.y, w: this._btnW, h: this._h };
    this._qtyRect = { x: o.x + this._btnW + GAP, y: o.y, w: this._qtyW, h: this._h };
    this._buyRect = { x: o.x + this._btnW + this._qtyW + GAP * 2, y: o.y, w: this._btnW, h: this._h };

    ctx.save();
    // subtle drop shadow so the panel reads as a floating control
    ctx.shadowColor = 'rgba(0,0,0,0.35)';
    ctx.shadowBlur = 8 * dpr;
    ctx.shadowOffsetY = 2 * dpr;

    const hovered = (r: Rect | null, id: string): boolean =>
      r !== null && rc.hoverId === `${this._id}:${id}`;

    this._drawButton(ctx, this._sellRect, dpr, hovered(this._sellRect, 'sell') ? shade(sell, 0.12) : sell,
      this._sellLabel, this._showPrices ? this._fmt(rc, this._bid) : '', 'left');
    // qty chip (neutral surface)
    const qtyFill = rc.theme.background === 'transparent' ? shade(sell, -0.6) : rc.theme.grid;
    this._drawChip(ctx, this._qtyRect, dpr, qtyFill, this._qty || '-', rc.theme.axisText);
    this._drawButton(ctx, this._buyRect, dpr, hovered(this._buyRect, 'buy') ? shade(buy, 0.12) : buy,
      this._buyLabel, this._showPrices ? this._fmt(rc, this._ask) : '', 'right');
    ctx.restore();
  }

  private _fmt(rc: PrimitiveRenderContext, p: number): string {
    return Number.isNaN(p) ? '' : rc.priceScale.format(p);
  }

  private _drawButton(
    ctx: CanvasRenderingContext2D, r: Rect, dpr: number, fill: string,
    label: string, price: string, side: 'left' | 'right',
  ): void {
    const radius = RADIUS * this._scale * dpr;
    // rounded on the outer edge, flat toward the qty chip
    ctx.beginPath();
    this._roundedSide(ctx, r.x * dpr, r.y * dpr, r.w * dpr, r.h * dpr, radius, side);
    ctx.fillStyle = fill;
    ctx.fill();
    const text = contrastText(fill);
    ctx.textAlign = 'center';
    const cx = (r.x + r.w / 2) * dpr;
    if (price !== '') {
      ctx.fillStyle = text;
      ctx.font = `${10 * this._scale * dpr}px system-ui, sans-serif`;
      ctx.textBaseline = 'alphabetic';
      // Baselines as a fraction of the button, not fixed px: at 18/33 of a
      // 42px box they were exact at scale 1 and hung the label *below* the
      // button at anything smaller.
      ctx.fillText(price, cx, (r.y + r.h * (18 / H)) * dpr);
      ctx.font = `700 ${12 * this._scale * dpr}px system-ui, sans-serif`;
      ctx.fillText(label, cx, (r.y + r.h * (33 / H)) * dpr);
    } else {
      ctx.fillStyle = text;
      ctx.font = `700 ${13 * this._scale * dpr}px system-ui, sans-serif`;
      ctx.textBaseline = 'middle';
      ctx.fillText(label, cx, (r.y + r.h / 2) * dpr);
    }
  }

  private _drawChip(ctx: CanvasRenderingContext2D, r: Rect, dpr: number, fill: string, txt: string, color: string): void {
    ctx.beginPath();
    // square middle (no rounding: it butts against the buttons)
    ctx.rect(r.x * dpr, r.y * dpr, r.w * dpr, r.h * dpr);
    ctx.fillStyle = fill;
    ctx.fill();
    ctx.fillStyle = color;
    ctx.font = `600 ${13 * this._scale * dpr}px system-ui, sans-serif`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(txt, (r.x + r.w / 2) * dpr, (r.y + r.h / 2) * dpr);
  }

  /** Trace a rect rounded on the left or right pair of corners only. */
  private _roundedSide(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, rad: number, side: 'left' | 'right'): void {
    const anyCtx = ctx as CanvasRenderingContext2D & { roundRect?: (x: number, y: number, w: number, h: number, r: number | number[]) => void };
    if (typeof anyCtx.roundRect === 'function') {
      const radii = side === 'left' ? [rad, 0, 0, rad] : [0, rad, rad, 0];
      anyCtx.roundRect(x, y, w, h, radii);
    } else {
      roundRectPath(ctx, x, y, w, h, rad);
    }
  }

  public hitTest(x: number, y: number, _rc: PrimitiveRenderContext): PrimitiveHit | null {
    const inside = (r: Rect | null): boolean =>
      r !== null && x >= r.x && x <= r.x + r.w && y >= r.y && y <= r.y + r.h;
    if (inside(this._buyRect)) return { externalId: `${this._id}:buy`, zOrder: 'top', distance: 0, cursor: 'pointer' };
    if (inside(this._sellRect)) return { externalId: `${this._id}:sell`, zOrder: 'top', distance: 0, cursor: 'pointer' };
    if (inside(this._qtyRect)) return { externalId: `${this._id}:qty`, zOrder: 'top', distance: 0, cursor: 'pointer' };
    return null;
  }
}
