/**
 * Horizontal profile renderer (ARCHITECTURE.md §6A): volume-at-price / TPO-count
 * bars drawn sideways with POC + Value-Area lines. A pane primitive that
 * overlays the existing price range, so it does not drive autoscale.
 *
 * The footprint renderer lives in `footprint-primitive.ts`.
 */
import type { IPrimitive, PrimitiveHost, PrimitiveRenderContext, ZOrder } from 'openalgo-charts';

export interface ProfileLevel { price: number; value: number; }

export interface HorizontalProfileOptions {
  buckets: ProfileLevel[];
  poc: number;
  vah: number;
  val: number;
  /** Strip width in media px. */
  width: number;
  side: 'left' | 'right';
  barColor: string;
  vaColor: string;
}

export class HorizontalProfile implements IPrimitive {
  private _opts: HorizontalProfileOptions;
  private _host: PrimitiveHost | null = null;

  public constructor(opts: HorizontalProfileOptions) {
    this._opts = opts;
  }

  public attached(host: PrimitiveHost): void { this._host = host; }
  public detached(): void { this._host = null; }
  public zOrder(): ZOrder { return 'bottom'; }
  public autoscaleInfo(): null { return null; } // overlays existing range

  public setData(opts: HorizontalProfileOptions): void {
    this._opts = opts;
    this._host?.requestUpdate();
  }

  public draw(ctx: CanvasRenderingContext2D, rc: PrimitiveRenderContext): void {
    const o = this._opts;
    if (o.buckets.length === 0) return;
    const dpr = rc.dpr;
    const maxVal = o.buckets.reduce((m, b) => Math.max(m, b.value), 0) || 1;
    const stripW = o.width * dpr;
    const baseX = o.side === 'left' ? 0 : rc.plotWidth * dpr;
    const rowH = Math.max(2 * dpr, ((rc.plotHeight * dpr) / Math.max(1, o.buckets.length)) - dpr);

    ctx.save();
    for (const b of o.buckets) {
      const y = rc.priceScale.priceToY(b.price) * dpr;
      const w = stripW * (b.value / maxVal);
      const inVa = b.price <= o.vah && b.price >= o.val;
      ctx.fillStyle = b.price === o.poc ? '#f0a020' : (inVa ? o.vaColor : o.barColor);
      const x = o.side === 'left' ? baseX : baseX - w;
      ctx.fillRect(x, y - rowH / 2, w, rowH);
    }
    // POC + VA lines across the plot
    for (const [price, color] of [[o.poc, '#f0a020'], [o.vah, '#5a6b8c'], [o.val, '#5a6b8c']] as const) {
      const y = Math.round(rc.priceScale.priceToY(price) * dpr) + 0.5;
      ctx.strokeStyle = color;
      ctx.lineWidth = Math.max(1, Math.round(dpr));
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(rc.plotWidth * dpr, y);
      ctx.stroke();
    }
    ctx.restore();
  }
}
