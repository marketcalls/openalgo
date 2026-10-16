/**
 * Dims everything from a bar onward, and draws the line where the cut falls.
 *
 * Two jobs, one shape. Picking a replay start means answering "from here, what
 * happens next?", and the honest way to ask it is to hide the answer: the bars
 * to the right of the cursor are greyed while the user chooses, so a start bar
 * is picked on what was known at the time rather than on the shape of what
 * followed. Once replay is running the same veil marks the part of the session
 * that has not been reached yet.
 *
 * The shade is drawn over the series rather than under it, because covering the
 * future is the entire point: a translucent wash still shows the shape faintly,
 * which is what tells a user there is more session there to walk into.
 */
import type { IPrimitive, PrimitiveHost, PrimitiveRenderContext, ZOrder } from './primitive';

export interface ReplayShadeOptions {
  /**
   * The last bar left uncovered. Everything after it is dimmed. Null draws
   * nothing at all, which is how a host keeps one instance around across
   * entering and leaving the mode.
   */
  index: number | null;
  /** Wash colour over the covered bars. Default a dark, low-alpha neutral. */
  color?: string;
  /** The rule at the cut. Default a muted blue, the colour of a chosen thing. */
  lineColor?: string;
  lineWidth?: number;
  /** Draw the divider. Default true. */
  lineVisible?: boolean;
  zOrder?: ZOrder;
  id?: string;
}

export class ReplayShade implements IPrimitive {
  private _opts: Required<Omit<ReplayShadeOptions, 'index'>> & { index: number | null };
  private _host: PrimitiveHost | null = null;

  public constructor(opts: ReplayShadeOptions) {
    this._opts = {
      index: opts.index,
      color: opts.color ?? 'rgba(12,14,20,0.62)',
      lineColor: opts.lineColor ?? '#3b82f6',
      lineWidth: opts.lineWidth ?? 1,
      lineVisible: opts.lineVisible ?? true,
      zOrder: opts.zOrder ?? 'top',
      id: opts.id ?? 'replay-shade',
    };
  }

  public attached(host: PrimitiveHost): void { this._host = host; }
  public detached(): void { this._host = null; }

  public zOrder(): ZOrder { return this._opts.zOrder; }
  /** Takes no part in autoscale: it covers bars, it is not one. */
  public autoscaleInfo(): null { return null; }
  /** Never hit, so the click that picks a bar reaches the chart. */
  public hitTest(): null { return null; }

  /** Moving or clearing the cut repaints at once: a host sets it on a click, not only on a pointer move. */
  public setOptions(patch: Partial<ReplayShadeOptions>): void {
    this._opts = { ...this._opts, ...patch };
    this._host?.requestUpdate();
  }

  public draw(ctx: CanvasRenderingContext2D, rc: PrimitiveRenderContext): void {
    const o = this._opts;
    if (o.index === null) return;
    const dpr = rc.dpr;
    const w = rc.plotWidth * dpr;
    const h = rc.plotHeight * dpr;
    if (w <= 0 || h <= 0) return;

    // The cut sits on the right edge of the chosen bar, so that bar stays fully
    // visible: it is the last one the user is allowed to have seen.
    const half = (rc.timeScale.barSpacing * dpr) / 2;
    const x = Math.round(rc.timeScale.indexToX(o.index) * dpr + half);
    if (x >= w) return; // nothing to the right of the last visible bar

    const from = Math.max(0, x);
    ctx.save();
    ctx.fillStyle = o.color;
    ctx.fillRect(from, 0, w - from, h);
    if (o.lineVisible && x >= 0) {
      ctx.strokeStyle = o.lineColor;
      ctx.lineWidth = Math.max(1, Math.round(o.lineWidth * dpr));
      ctx.beginPath();
      ctx.moveTo(x + 0.5, 0);
      ctx.lineTo(x + 0.5, h);
      ctx.stroke();
    }
    ctx.restore();
  }
}
