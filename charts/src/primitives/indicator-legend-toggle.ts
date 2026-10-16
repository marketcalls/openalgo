import type { IPrimitive, PrimitiveHost, PrimitiveRenderContext, PrimitiveHit } from './primitive';
import { withAlpha } from '../render/pill';

export const INDICATOR_LEGEND_TOGGLE = 'indicator-legend::toggle';

interface ToggleOptions {
  count: number;
  collapsed: boolean;
  left: number;
  top: number;
  height: number;
}

/** Internal chart control. Its label and hit area never depend on hover or readout switches. */
export class IndicatorLegendToggle implements IPrimitive {
  private _host: PrimitiveHost | null = null;
  private _bounds: { x: number; y: number; width: number; height: number } | null = null;
  private _options: ToggleOptions = { count: 0, collapsed: false, left: 8, top: 6, height: 18 };

  public attached(host: PrimitiveHost): void { this._host = host; }
  public detached(): void { this._host = null; this._bounds = null; }
  public zOrder(): 'top' { return 'top'; }
  public setOptions(options: ToggleOptions): void {
    if (Object.keys(options).every(key => options[key as keyof ToggleOptions] === this._options[key as keyof ToggleOptions])) return;
    this._options = options;
    this._bounds = null;
    this._host?.requestUpdate();
  }

  public draw(ctx: CanvasRenderingContext2D, rc: PrimitiveRenderContext): void {
    this._bounds = null;
    const o = this._options, dpr = rc.dpr, height = o.height;
    if (o.count === 0 || rc.plotWidth < 18 || o.top < 0 || o.top + height > rc.plotHeight) return;
    ctx.save();
    ctx.font = `500 ${11 * dpr}px ui-sans-serif, system-ui, sans-serif`;
    let label = `Indicators ${o.count}`;
    if (ctx.measureText(label).width / dpr + 24 > rc.plotWidth) label = String(o.count);
    const width = Math.min(rc.plotWidth, ctx.measureText(label).width / dpr + 24);
    const x = Math.max(0, Math.min(o.left, rc.plotWidth - width)), y = o.top;
    this._bounds = { x, y, width, height };
    ctx.beginPath(); ctx.rect(x * dpr, y * dpr, width * dpr, height * dpr); ctx.clip();
    ctx.fillStyle = withAlpha(rc.theme.background, 0.9);
    ctx.beginPath(); ctx.roundRect(x * dpr, y * dpr, width * dpr, height * dpr, 3 * dpr); ctx.fill();
    ctx.strokeStyle = rc.theme.axisText; ctx.lineWidth = dpr;
    const cx = (x + 8) * dpr, cy = (y + height / 2) * dpr, r = 3 * dpr;
    ctx.beginPath();
    if (o.collapsed) { ctx.moveTo(cx - r / 2, cy - r); ctx.lineTo(cx + r / 2, cy); ctx.lineTo(cx - r / 2, cy + r); }
    else { ctx.moveTo(cx - r, cy - r / 2); ctx.lineTo(cx, cy + r / 2); ctx.lineTo(cx + r, cy - r / 2); }
    ctx.stroke();
    ctx.fillStyle = rc.theme.axisText; ctx.textBaseline = 'middle'; ctx.textAlign = 'left';
    ctx.fillText(label, (x + 16) * dpr, cy);
    ctx.restore();
  }

  public hitTest(x: number, y: number): PrimitiveHit | null {
    const b = this._bounds;
    return b && x >= b.x && x < b.x + b.width && y >= b.y && y < b.y + b.height
      ? { externalId: INDICATOR_LEGEND_TOGGLE, zOrder: 'top', distance: 0, cursor: 'pointer' } : null;
  }
}
