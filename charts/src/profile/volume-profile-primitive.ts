/**
 * Volume Profile renderer (ARCHITECTURE.md §8, §6A). Draws the output of
 * `computeVolumeProfileSessions` as a horizontal volume histogram per session,
 * anchored at the session's left or right edge. Display modes: `total` (one bar),
 * `buySell` (buy vs sell split), and `delta` (net, colored by sign). POC and
 * Value Area are drawn as lines with labels, with an optional value-area fill and
 * dimming of rows outside the value area. A pane primitive that overlays the
 * price range (its `autoscaleInfo` reports its extent so a profile-only chart
 * still frames correctly).
 */
import type { IPrimitive, PrimitiveHost, PrimitiveRenderContext, ZOrder } from 'openalgo-charts';
import type { VolumeProfileFamilyResult, VolumeProfileSessionResult } from './volume-profile-family';
import { sessionsPriceRange } from './profile-model';

export type VolumeDisplayMode = 'total' | 'buySell' | 'delta';
export type VolumeProfileSide = 'left' | 'right';

export interface VolumeProfilePrimitiveOptions {
  displayMode: VolumeDisplayMode;
  /** Anchor the bars at the session's left or right edge. */
  side: VolumeProfileSide;
  /** Maximum bar length in media px. */
  width: number;
  opacity: number;
  barColor: string;
  buyColor: string;
  sellColor: string;
  showPoc: boolean;
  pocColor: string;
  showPocLabel: boolean;
  showValueArea: boolean;
  vahColor: string;
  valColor: string;
  showValueAreaLabels: boolean;
  highlightValueArea: boolean;
  valueAreaFillColor: string;
  valueAreaFillOpacity: number;
  /** Opacity multiplier for rows outside the value area (1 = no dimming). */
  valueAreaOpacityDim: number;
  /** Show a price label at the session edge for the POC/value area. */
  labelSide: VolumeProfileSide;
  zOrder: ZOrder;
}

export const DEFAULT_VOLUME_PROFILE_PRIMITIVE_OPTIONS: VolumeProfilePrimitiveOptions = {
  displayMode: 'total',
  side: 'right',
  width: 90,
  opacity: 0.85,
  barColor: '#3b5168',
  buyColor: '#26a69a',
  sellColor: '#ef5350',
  showPoc: true,
  pocColor: '#f0a020',
  showPocLabel: true,
  showValueArea: true,
  vahColor: '#8892a6',
  valColor: '#8892a6',
  showValueAreaLabels: true,
  highlightValueArea: true,
  valueAreaFillColor: '#4a6fa5',
  valueAreaFillOpacity: 0.08,
  valueAreaOpacityDim: 0.4,
  labelSide: 'right',
  zOrder: 'bottom',
};

interface Segment { color: string; len: number; }

export class VolumeProfile implements IPrimitive {
  private _result: VolumeProfileFamilyResult | null;
  private _opts: VolumeProfilePrimitiveOptions;
  private _host: PrimitiveHost | null = null;

  public constructor(result: VolumeProfileFamilyResult | null = null, opts: Partial<VolumeProfilePrimitiveOptions> = {}) {
    this._result = result;
    this._opts = { ...DEFAULT_VOLUME_PROFILE_PRIMITIVE_OPTIONS, ...opts };
  }

  public attached(host: PrimitiveHost): void { this._host = host; }
  public detached(): void { this._host = null; }
  public zOrder(): ZOrder { return this._opts.zOrder; }

  public autoscaleInfo(): { min: number; max: number } | null {
    return this._result === null ? null : sessionsPriceRange(this._result.sessions);
  }

  public setData(result: VolumeProfileFamilyResult): void {
    this._result = result;
    this._host?.requestUpdate();
  }

  public setOptions(patch: Partial<VolumeProfilePrimitiveOptions>): void {
    this._opts = { ...this._opts, ...patch };
    this._host?.requestUpdate();
  }

  public draw(ctx: CanvasRenderingContext2D, rc: PrimitiveRenderContext): void {
    if (this._result === null || this._result.sessions.length === 0) return;
    const tick = this._result.options.tickSize;
    for (const s of this._result.sessions) this._drawSession(ctx, rc, s, tick);
  }

  private _segments(l: VolumeProfileSessionResult['levels'][number], maxMetric: number, widthDev: number): Segment[] {
    const o = this._opts;
    if (o.displayMode === 'delta') {
      const len = (Math.abs(l.delta) / maxMetric) * widthDev;
      return [{ color: l.delta >= 0 ? o.buyColor : o.sellColor, len }];
    }
    const len = (l.volume / maxMetric) * widthDev;
    if (o.displayMode === 'buySell' && l.volume > 0) {
      const buyLen = len * (l.buyVolume / l.volume);
      return [{ color: o.buyColor, len: buyLen }, { color: o.sellColor, len: len - buyLen }];
    }
    return [{ color: o.barColor, len }];
  }

  private _drawSession(
    ctx: CanvasRenderingContext2D,
    rc: PrimitiveRenderContext,
    s: VolumeProfileSessionResult,
    tick: number,
  ): void {
    const o = this._opts;
    const dpr = rc.dpr;
    const i0 = rc.dataLayer.timeToIndex(s.startTime);
    const i1 = rc.dataLayer.timeToIndex(s.endTime);
    if (i0 === undefined || i1 === undefined) return;
    const x0 = Math.round(rc.timeScale.indexToX(i0) * dpr);
    const x1 = Math.max(x0 + 1, Math.round(rc.timeScale.indexToX(i1) * dpr));
    const yOf = (p: number): number => rc.priceScale.priceToY(p) * dpr;
    const rowH = Math.max(1, Math.abs(rc.priceScale.priceToY(s.poc) - rc.priceScale.priceToY(s.poc + tick)) * dpr);
    const widthDev = o.width * dpr;
    const anchor = o.side === 'right' ? x1 : x0;

    let maxMetric = 0;
    for (const l of s.levels) {
      const m = o.displayMode === 'delta' ? Math.abs(l.delta) : l.volume;
      if (m > maxMetric) maxMetric = m;
    }
    if (maxMetric <= 0) maxMetric = 1;

    ctx.save();

    // value-area highlight fill
    if (o.highlightValueArea) {
      const yTop = yOf(s.vah) - rowH / 2;
      const yBot = yOf(s.val) + rowH / 2;
      const fx = o.side === 'right' ? x1 - widthDev : x0;
      ctx.globalAlpha = o.valueAreaFillOpacity;
      ctx.fillStyle = o.valueAreaFillColor;
      ctx.fillRect(fx, yTop, widthDev, yBot - yTop);
      ctx.globalAlpha = 1;
    }

    // bars
    for (const l of s.levels) {
      const inVa = l.price <= s.vah && l.price >= s.val;
      const alpha = o.opacity * (inVa ? 1 : o.valueAreaOpacityDim);
      const y = yOf(l.price);
      const top = y - rowH / 2;
      const h = Math.max(1, rowH - 1);
      let cursor = anchor;
      ctx.globalAlpha = alpha;
      for (const seg of this._segments(l, maxMetric, widthDev)) {
        if (seg.len <= 0) continue;
        const x = o.side === 'right' ? cursor - seg.len : cursor;
        ctx.fillStyle = seg.color;
        ctx.fillRect(x, top, seg.len, h);
        cursor = o.side === 'right' ? cursor - seg.len : cursor + seg.len;
      }
    }
    ctx.globalAlpha = 1;

    // POC / VAH / VAL lines + labels across the session
    const hline = (price: number, color: string, label: string): void => {
      const y = Math.round(yOf(price)) + 0.5;
      ctx.strokeStyle = color;
      ctx.lineWidth = Math.max(1, Math.round(dpr));
      ctx.beginPath();
      ctx.moveTo(x0, y);
      ctx.lineTo(x1, y);
      ctx.stroke();
      if (label !== '') {
        ctx.font = `${9 * dpr}px ui-sans-serif, system-ui, sans-serif`;
        ctx.textBaseline = 'middle';
        ctx.fillStyle = color;
        if (o.labelSide === 'right') { ctx.textAlign = 'left'; ctx.fillText(label, x1 + 3 * dpr, y); }
        else { ctx.textAlign = 'right'; ctx.fillText(label, x0 - 3 * dpr, y); }
      }
    };
    if (o.showValueArea) {
      hline(s.vah, o.vahColor, o.showValueAreaLabels ? `VAH ${rc.priceScale.format(s.vah)}` : '');
      hline(s.val, o.valColor, o.showValueAreaLabels ? `VAL ${rc.priceScale.format(s.val)}` : '');
    }
    if (o.showPoc) hline(s.poc, o.pocColor, o.showPocLabel ? `POC ${rc.priceScale.format(s.poc)}` : '');

    ctx.restore();
  }
}
