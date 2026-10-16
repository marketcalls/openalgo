/**
 * Logo / brand watermark (ARCHITECTURE.md §8). Draws a small image (or an
 * already-decoded bitmap) faintly in a corner of the plot, the way charting
 * apps stamp a product/brand mark. Because it draws on the canvas it is captured
 * by `chart.takeScreenshot()`, and an optional `tint` recolors the opaque pixels
 * so a single-color logo reads on both dark and light themes.
 *
 * Pass a `src` (URL or data URI) or a preloaded `image` for custom artwork.
 * Without a source, the original OpenAlgo glyph draws without a network request.
 */
import type { IPrimitive, PrimitiveHit, PrimitiveHost, PrimitiveRenderContext, ZOrder } from './primitive';
import { roundRectPath, withAlpha } from '../render/pill';
import { drawOpenAlgoGlyph } from './openalgo-glyph';

export type WatermarkPosition =
  | 'top-left' | 'top-right' | 'bottom-left' | 'bottom-right' | 'center';

export interface LogoWatermarkOptions {
  /** Image URL or data URI. Ignored when `image` is provided. */
  src?: string;
  /** A preloaded image/bitmap to draw (skips loading). */
  image?: CanvasImageSource & { width: number; height: number };
  /** Corner (or center) to anchor to. Default `bottom-right`. */
  position?: WatermarkPosition;
  /** Gap from the plot edges in px. Default `12`. */
  margin?: number;
  /** Rendered logo height in px; width follows the source aspect. Default `28`. */
  height?: number;
  /** 0..1. Default `0.7`. */
  opacity?: number;
  /** Recolor the opaque pixels to this color (e.g. a faint theme gray). */
  tint?: string;
  /** Layer order vs the series. Default `top`. */
  zOrder?: ZOrder;
  /**
   * Text revealed to the right of the mark on hover: "Chart by OpenAlgo".
   * The mark alone is what sits on the chart at rest; the wording is only
   * needed when someone looks at it, so it unrolls rather than occupying the
   * corner permanently. Omit for a plain, non-interactive mark.
   */
  label?: string;
  /** Hit-test id, so the chart can report hover. Default `watermark`. */
  id?: string;
  /** Reveal duration in seconds. Default 0.18. */
  revealSeconds?: number;
  /** Label colour. Defaults to `tint`, then the theme's text. */
  labelColor?: string;
  /** Label size in media px. Default 12. */
  fontSize?: number;
  /**
   * Rounded plate behind the mark and label. Without one the wording sits
   * straight on the candles and is unreadable wherever the chart is busy.
   * Defaults to a translucent form of the theme background; `'none'` omits it.
   */
  background?: string;
  /** Plate border. Defaults to the theme's axis line. `'none'` omits it. */
  borderColor?: string;
  /** Plate corner radius in media px. Default 6. */
  radius?: number;
  /**
   * Plate padding around the lockup, in media px. A number pads both axes;
   * `{ x, y }` pads them separately. Default `{ x: 7, y: 4 }`, which keeps the
   * revealed label clear of the plate edge.
   *
   * Use it to size the resting plate exactly: a 40px mark with `padding: 2.5`
   * sits in a 45x45 square. The plate widens as the label unrolls; the padding
   * is what stays constant.
   */
  padding?: number | { x: number; y: number };
  /**
   * Where the mark points. A canvas cannot hold an anchor, so this only marks
   * it as clickable: the hit reports a pointer cursor, and the host opens
   * {@link href} from its own click handler.
   *
   * Given a bare URL, `href()` appends UTM parameters naming the page the chart
   * is embedded in, so the referral is attributable. Pass a URL that already
   * has a query string to compose your own and skip that entirely.
   */
  href?: string;
  /** `utm_medium` for the composed link. Default `oac-link`. */
  utmMedium?: string;
  /** `utm_campaign` for the composed link. Default `oac-chart`. */
  utmCampaign?: string;
}

interface ImageLike { width: number; height: number; naturalWidth?: number; naturalHeight?: number; complete?: boolean; }

/** Plate padding as a pair, from either accepted form. */
function resolvePadding(p: LogoWatermarkOptions['padding']): { x: number; y: number } {
  if (p === undefined) return { x: 7, y: 4 };
  return typeof p === 'number' ? { x: p, y: p } : { x: p.x, y: p.y };
}

/** Top-left placement (in media px) of a `w x h` logo within a `plotW x plotH` plot. */
export function watermarkRect(
  position: WatermarkPosition, margin: number, w: number, h: number, plotW: number, plotH: number,
): { x: number; y: number; w: number; h: number } {
  const right = plotW - margin - w;
  const bottom = plotH - margin - h;
  switch (position) {
    case 'top-left': return { x: margin, y: margin, w, h };
    case 'top-right': return { x: right, y: margin, w, h };
    case 'bottom-left': return { x: margin, y: bottom, w, h };
    case 'center': return { x: (plotW - w) / 2, y: (plotH - h) / 2, w, h };
    case 'bottom-right':
    default: return { x: right, y: bottom, w, h };
  }
}

export class LogoWatermark implements IPrimitive {
  private _opts: Required<Omit<LogoWatermarkOptions, 'src' | 'image' | 'tint' | 'label' | 'labelColor' | 'background' | 'borderColor' | 'href' | 'padding'>>
    // The constructor copies each absent one as undefined, which every reader treats as unset.
    & { [K in 'src' | 'image' | 'tint' | 'label' | 'labelColor' | 'background' | 'borderColor' | 'href']?: LogoWatermarkOptions[K] | undefined }
    & { padding: { x: number; y: number } };
  /** 0..1 reveal progress, eased toward hover state each frame. */
  private _reveal = 0;
  private _lastFrameMs: number | null = null;
  /** Label width in media px, measured once the font is known. */
  private _labelW = 0;
  private readonly _now: () => number =
    typeof performance !== 'undefined' ? () => performance.now() : () => 0;
  private _host: PrimitiveHost | null = null;
  private _img: (CanvasImageSource & ImageLike) | null = null;
  private _ready = false;
  private _autoHeight: boolean;
  private _tintCanvas: (CanvasImageSource & { width: number; height: number }) | null = null;
  private _tintKey = '';

  public constructor(opts: LogoWatermarkOptions = {}) {
    this._autoHeight = opts.height === undefined;
    this._opts = {
      position: opts.position ?? 'bottom-right',
      margin: opts.margin ?? 12,
      height: opts.height ?? 28,
      opacity: opts.opacity ?? 0.7,
      zOrder: opts.zOrder ?? 'top',
      src: opts.src,
      image: opts.image,
      tint: opts.tint,
      label: opts.label,
      id: opts.id ?? 'watermark',
      revealSeconds: opts.revealSeconds ?? 0.18,
      labelColor: opts.labelColor,
      fontSize: opts.fontSize ?? 12,
      background: opts.background,
      borderColor: opts.borderColor,
      radius: opts.radius ?? 6,
      padding: resolvePadding(opts.padding),
      href: opts.href,
      utmMedium: opts.utmMedium ?? 'oac-link',
      utmCampaign: opts.utmCampaign ?? 'oac-chart',
    };
    if (opts.image) { this._img = opts.image as CanvasImageSource & ImageLike; this._ready = true; }
  }

  public attached(host: PrimitiveHost): void {
    this._host = host;
    if (!this._ready && this._opts.src && typeof Image !== 'undefined') {
      const img = new Image();
      img.onload = (): void => { this._img = img; this._ready = true; this._host?.requestUpdate(); };
      img.decoding = 'async';
      img.src = this._opts.src;
    }
  }

  public detached(): void { this._host = null; }
  public zOrder(): ZOrder { return this._opts.zOrder; }
  public autoscaleInfo(): null { return null; }

  /** Live restyle. Pass a new `src`/`image` to swap the logo. */
  public setOptions(patch: Partial<LogoWatermarkOptions>): void {
    // `padding` is stored resolved, so it cannot ride along with the spread.
    const { padding, ...rest } = patch;
    this._opts = { ...this._opts, ...rest };
    if (padding !== undefined) this._opts.padding = resolvePadding(padding);
    if (patch.height !== undefined) this._autoHeight = false;
    if (patch.label !== undefined || patch.fontSize !== undefined) this._labelW = 0;
    this._tintCanvas = null;
    if (patch.image) { this._img = patch.image as CanvasImageSource & ImageLike; this._ready = true; }
    else if (patch.src !== undefined) { this._ready = false; this._img = null; this.attached(this._host as PrimitiveHost); }
    this._host?.requestUpdate();
  }

  /**
   * The mark's box, in media px. The label unrolls to its right, so the hit
   * area is the mark alone: hovering the revealed text keeps it open because
   * the pointer is still within the widened box below.
   */
  private _rect(rc: PrimitiveRenderContext): { x: number; y: number; w: number; h: number; logoW: number } | null {
    if (!this._builtin() && (!this._ready || this._img === null)) return null;
    const iw = this._img?.naturalWidth ?? this._img?.width ?? 1;
    const ih = this._img?.naturalHeight ?? this._img?.height ?? 1;
    if (!iw || !ih) return null;
    const o = this._opts;
    const margin = Math.max(0, o.margin, o.padding.x, o.padding.y);
    const availableW = rc.plotWidth - 2 * margin;
    const availableH = rc.plotHeight - 2 * margin;
    if (availableW <= 0 || availableH <= 0) return null;
    const height = this._builtin() && this._autoHeight && rc.plotWidth < 480 ? 24 : o.height;
    const h = Math.max(0, Math.min(height, availableH, availableW * ih / iw));
    if (!Number.isFinite(h) || h <= 0) return null;
    const logoW = h * (iw / ih);
    const w = Math.min(availableW, logoW + this._labelW * this._reveal);
    const r = watermarkRect(o.position, margin, w, h, rc.plotWidth, rc.plotHeight);
    return { ...r, logoW };
  }

  private _builtin(): boolean { return this._opts.src === undefined && this._opts.image === undefined; }

  /**
   * The link to open, with attribution appended. A caller who supplied their
   * own query string gets it back untouched.
   */
  public href(): string | undefined {
    const base = this._opts.href;
    if (base === undefined || base.includes('?')) return base;
    const loc = typeof location !== 'undefined' ? location : undefined;
    const parts = [
      `utm_medium=${encodeURIComponent(this._opts.utmMedium)}`,
      `utm_campaign=${encodeURIComponent(this._opts.utmCampaign)}`,
    ];
    // The embedding page, host and path only, never the query string, which
    // is the part most likely to carry something private.
    if (loc?.host) parts.push(`utm_source=${loc.host}${loc.pathname}`);
    return `${base}${base.includes('?') ? '&' : '?'}${parts.join('&')}`;
  }

  public hitTest(x: number, y: number, rc: PrimitiveRenderContext): PrimitiveHit | null {
    // Nothing to reveal and nowhere to go: stay out of the hit path entirely so
    // a plain mark cannot swallow clicks meant for the chart.
    if (this._opts.label === undefined && this._opts.href === undefined) return null;
    const r = this._rect(rc);
    if (r === null) return null;
    // Match the plate the user can see, but never shrink below the old 4px
    // slack: a tightly padded mark still needs a forgiving target.
    const padX = Math.max(this._opts.padding.x, 4, (44 - r.w) / 2);
    const padY = Math.max(this._opts.padding.y, 4, (44 - r.h) / 2);
    const w = Math.min(rc.plotWidth, r.w + 2 * padX);
    const h = Math.min(rc.plotHeight, r.h + 2 * padY);
    const left = Math.max(0, Math.min(rc.plotWidth - w, r.x - padX));
    const top = Math.max(0, Math.min(rc.plotHeight - h, r.y - padY));
    const inside = x >= left && x <= left + w && y >= top && y <= top + h;
    return inside
      ? {
          externalId: this._opts.id,
          zOrder: this._opts.zOrder,
          distance: 0,
          cursor: this._opts.href !== undefined ? 'pointer' : 'default',
        }
      : null;
  }

  public draw(ctx: CanvasRenderingContext2D, rc: PrimitiveRenderContext): void {
    if (!this._builtin() && (!this._ready || this._img === null)) return;
    const o = this._opts;
    const dpr = rc.dpr;

    // Measure the label once the context's font is set; the width feeds the
    // hit box, so it has to be known before the reveal starts moving.
    if (o.label !== undefined && this._labelW === 0) {
      ctx.save();
      ctx.font = `600 ${o.fontSize * dpr}px system-ui, sans-serif`;
      this._labelW = ctx.measureText(o.label).width / dpr + 8;
      ctx.restore();
    }
    this._advanceReveal(rc);

    const r = this._rect(rc);
    if (r === null) return;
    const dx = Math.round(r.x * dpr);
    const dy = Math.round(r.y * dpr);
    const dw = Math.round(r.logoW * dpr);
    const dh = Math.round(r.h * dpr);

    ctx.save();
    // Plate first, at full alpha: it is what makes the mark legible over
    // candles, so it must not inherit the logo's own transparency.
    //
    // The four edges are snapped, rather than the padding being snapped and
    // doubled: that way the plate measures exactly `height + 2 * padding.y`
    // media px at every DPR, so a caller asking for a 45x45 square gets one
    // instead of 46 on a non-retina display.
    const pad = o.padding;
    const plateX = Math.round((r.x - pad.x) * dpr);
    const plateY = Math.round((r.y - pad.y) * dpr);
    const plateW = Math.round((r.x + r.w + pad.x) * dpr) - plateX;
    const plateH = Math.round((r.y + r.h + pad.y) * dpr) - plateY;
    const theme = rc.theme as typeof rc.theme | undefined;
    const plateBg = o.background ?? (theme ? withAlpha(theme.background, 0.82) : 'none');
    const plateBorder = o.borderColor ?? theme?.axisLine ?? 'none';
    if (plateBg !== 'none') {
      ctx.beginPath();
      roundRectPath(ctx, plateX, plateY, plateW, plateH, Math.round(o.radius * dpr));
      ctx.fillStyle = plateBg;
      ctx.fill();
      if (plateBorder !== 'none') {
        ctx.strokeStyle = plateBorder;
        ctx.lineWidth = Math.max(1, Math.round(dpr));
        ctx.stroke();
      }
    }
    ctx.globalAlpha = Math.max(0, Math.min(1, o.opacity));
    // Mark and label are one lockup, so they share a colour. Whichever the
    // caller specified wins for both; specifying neither takes the theme's
    // text. Without this the mark kept its source colour and sat beside the
    // label in an unrelated shade.
    const ink = this._ink(rc);
    const tint = o.label !== undefined ? ink : o.tint;
    if (this._builtin()) {
      ctx.fillStyle = ink;
      drawOpenAlgoGlyph(ctx, dx, dy, dh);
    } else {
      const src = tint ? this._tinted(ctx, dw, dh, tint) : this._img;
      if (tint && src) ctx.drawImage(src, dx, dy);
      else if (this._img) ctx.drawImage(this._img, dx, dy, dw, dh);
    }

    if (o.label !== undefined && this._reveal > 0.001) {
      // Clip to the revealed width so the text wipes out of the mark rather
      // than fading in place: the motion is what reads as "attached to it".
      const shown = (r.w - r.logoW) * dpr;
      ctx.beginPath();
      ctx.rect(dx + dw, dy, shown, dh);
      ctx.clip();
      // Full alpha and an integer baseline: the text is the thing being read,
      // so it should not fade with the mark or land on a half pixel.
      ctx.globalAlpha = this._reveal;
      ctx.font = `600 ${Math.round(o.fontSize * dpr)}px system-ui, -apple-system, sans-serif`;
      ctx.textBaseline = 'middle';
      ctx.textAlign = 'left';
      ctx.fillStyle = ink;
      ctx.fillText(o.label, Math.round(dx + dw + 6 * dpr), Math.round(dy + dh / 2));
    }
    ctx.restore();
  }

  /**
   * The single colour the mark and its label share. Either option can set it;
   * they follow each other so the pair never renders in two shades.
   */
  private _ink(rc: PrimitiveRenderContext): string {
    const o = this._opts;
    const theme = rc.theme as typeof rc.theme | undefined;
    return o.labelColor ?? o.tint ?? theme?.axisText ?? '#9aa3b2';
  }

  /** Ease the reveal toward the hover state, asking for frames while moving. */
  private _advanceReveal(rc: PrimitiveRenderContext): void {
    if (this._opts.label === undefined) return;
    const target = rc.hoverId === this._opts.id ? 1 : 0;
    const nowMs = this._now();
    const dt = this._lastFrameMs === null ? 0 : Math.max(0, (nowMs - this._lastFrameMs) / 1000);
    this._lastFrameMs = nowMs;
    const secs = this._opts.revealSeconds;
    if (secs <= 0) this._reveal = target;
    else if (this._reveal !== target) {
      const step = dt / secs;
      this._reveal += Math.sign(target - this._reveal) * Math.min(step, Math.abs(target - this._reveal));
    }
    // Keep frames coming until it settles, then stop asking.
    if (Math.abs(target - this._reveal) > 0.001) this._host?.requestUpdate();
    else this._reveal = target;
  }

  /** Recolor the opaque logo pixels to `color` at (dw x dh) device px, cached. */
  private _tinted(ctx: CanvasRenderingContext2D, dw: number, dh: number, color: string): CanvasImageSource & { width: number; height: number } | null {
    const key = `${dw}x${dh}:${color}`;
    if (this._tintCanvas && this._tintKey === key) return this._tintCanvas;
    // A recording or offscreen context has no canvas/document to borrow, and
    // an untinted mark is a better outcome than a thrown frame.
    const canvas = ctx.canvas as HTMLCanvasElement | undefined;
    const doc = canvas?.ownerDocument as Document | undefined;
    let off: HTMLCanvasElement | null = null;
    if (doc && typeof doc.createElement === 'function') off = doc.createElement('canvas');
    if (!off) return null;
    off.width = dw; off.height = dh;
    const g = off.getContext('2d');
    if (!g || this._img === null) return null;
    g.clearRect(0, 0, dw, dh);
    g.drawImage(this._img, 0, 0, dw, dh);
    g.globalCompositeOperation = 'source-in';
    g.fillStyle = color;
    g.fillRect(0, 0, dw, dh);
    this._tintCanvas = off;
    this._tintKey = key;
    return off;
  }
}
