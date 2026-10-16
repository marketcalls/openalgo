/**
 * A word stamped faintly across the plot, to say what mode the chart is in.
 *
 * The case it exists for is replay: a chart showing a past session looks exactly
 * like a chart showing the present one, and a trader who forgets which they are
 * looking at can read a live decision off history. The mark is large, centred
 * and static on purpose. It is not decoration and not a brand: it is the answer
 * to "am I looking at the market or a recording of it", and it has to be
 * readable without being looked for.
 *
 * Distinct from `LogoWatermark`, which is a small corner image with a hover
 * label. This one draws text, takes no interaction, and reports no hit, so it
 * never intercepts a click meant for the chart under it.
 */
import type { IPrimitive, PrimitiveHost, PrimitiveRenderContext, ZOrder } from './primitive';

export interface TextWatermarkOptions {
  /** The word itself. Kept short: it is read at a glance, not studied. */
  text: string;
  /**
   * Cap height in px at the plot's natural size, scaled down on a narrow chart
   * so a long word never runs past the edges. Default 64.
   */
  fontSize?: number;
  /** 0..1. Default 0.08, which reads as present without competing with bars. */
  opacity?: number;
  /** Default a neutral grey that works on either theme. */
  color?: string;
  font?: string;
  /**
   * Below the series by default. A mode marker that covered the candles would
   * be worse than no marker, since the candles are what the mode is about.
   */
  zOrder?: ZOrder;
  id?: string;
}

const DEFAULT_FONT = '600 {size}px system-ui, -apple-system, "Segoe UI", sans-serif';

export class TextWatermark implements IPrimitive {
  private _host: PrimitiveHost | null = null;
  // The constructor copies an absent color or font as undefined, read as unset.
  private _opts: Required<Omit<TextWatermarkOptions, 'color' | 'font'>>
    & { [K in 'color' | 'font']?: TextWatermarkOptions[K] | undefined };

  public constructor(opts: TextWatermarkOptions) {
    this._opts = {
      text: opts.text,
      fontSize: opts.fontSize ?? 64,
      opacity: opts.opacity ?? 0.08,
      zOrder: opts.zOrder ?? 'bottom',
      id: opts.id ?? 'text-watermark',
      color: opts.color,
      font: opts.font,
    };
  }

  public zOrder(): ZOrder { return this._opts.zOrder; }
  public attached(host: PrimitiveHost): void { this._host = host; }
  public detached(): void { this._host = null; }
  public autoscaleInfo(): null { return null; }
  /** Never hit: the mark must not eat a click aimed at the chart beneath it. */
  public hitTest(): null { return null; }

  public setOptions(patch: Partial<TextWatermarkOptions>): void {
    this._opts = { ...this._opts, ...patch };
    this._host?.requestUpdate();
  }

  public draw(ctx: CanvasRenderingContext2D, rc: PrimitiveRenderContext): void {
    const o = this._opts;
    if (o.text === '') return;
    const dpr = rc.dpr;
    const w = rc.plotWidth * dpr;
    const h = rc.plotHeight * dpr;
    if (w <= 0 || h <= 0) return;

    ctx.save();
    ctx.beginPath();
    ctx.rect(0, 0, w, h);
    ctx.clip();
    ctx.globalAlpha = o.opacity;
    ctx.fillStyle = o.color ?? '#9aa4b2';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';

    // Measure at the requested size, then shrink to fit rather than clipping: a
    // half-visible word is worse than a small one, and panes get narrow.
    const size = Math.min(o.fontSize * dpr, h * 0.8);
    const face = (o.font ?? DEFAULT_FONT).replace('{size}', String(Math.round(size)));
    ctx.font = face;
    const natural = ctx.measureText(o.text).width;
    const room = w * 0.8;
    if (natural > room && natural > 0) {
      const shrunk = Math.max(0.1, size * (room / natural));
      ctx.font = (o.font ?? DEFAULT_FONT).replace('{size}', String(shrunk));
    }
    ctx.fillText(o.text, w / 2, h / 2);
    ctx.restore();
  }
}
