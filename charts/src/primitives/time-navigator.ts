/**
 * Time navigator (ARCHITECTURE.md section 8): hover-revealed zoom, reset and
 * one-bar step controls just above the time axis.
 *
 * Invisible until the pointer nears the bottom of the chart, so a clean chart
 * stays clean. It fades in and out rather than snapping, which is what keeps it
 * from reading as a glitch when the cursor crosses the reveal band.
 *
 * Reveal is driven by an explicit `setPointer` from the chart, **not** by
 * `rc.hoverId`. Hover ids come from `bestHit`, which picks the nearest primitive,
 * so a drawing or an order line near the bottom of the chart would win the
 * hit and silently hide the controls. Pointer position is the honest input here;
 * hit-testing still owns the buttons themselves.
 */
import type { IPrimitive, PrimitiveHit, PrimitiveHost, PrimitiveRenderContext, ZOrder } from './primitive';
import { parseColor, withAlpha } from '../render/pill';

/** Command each button runs. These are `Chart` shortcut command ids. */
export type TimeNavigatorAction = 'zoomOut' | 'zoomIn' | 'resetScale' | 'panLeftBar' | 'panRightBar';

export interface TimeNavigatorOptions {
  /** Prefix for hit ids. Lets a host run more than one. */
  id: string;
  /** Buttons, left to right. A `null` inserts a gap between groups. */
  buttons: readonly (TimeNavigatorAction | null)[];
  /** Button box size in media px. */
  size: number;
  /** Gap between buttons, and the wider gap a `null` produces. */
  gap: number;
  groupGap: number;
  /** Distance from the bottom of the plot to the bottom of the buttons. */
  bottomMargin: number;
  /**
   * Height of the reveal band above the plot bottom. The pointer anywhere in
   * this band brings the controls in.
   */
  revealHeight: number;
  /** Seconds the fade takes. 0 disables the animation. */
  fadeSeconds: number;
  /** Tooltip label overrides per action. */
  labels: Partial<Record<TimeNavigatorAction, string>>;
  /** Optional keyboard hint shown next to the label, e.g. `"Ctrl + −"`. */
  hints: Partial<Record<TimeNavigatorAction, string>>;
  /** Show the tooltip above the hovered button. */
  showTooltip: boolean;
  font: number;
  radius: number;
  zOrder: ZOrder;
}

const DEFAULT_LABELS: Record<TimeNavigatorAction, string> = {
  zoomOut: 'Zoom out',
  zoomIn: 'Zoom in',
  resetScale: 'Reset view',
  panLeftBar: 'Move left',
  panRightBar: 'Move right',
};

export const DEFAULT_TIME_NAVIGATOR_OPTIONS: TimeNavigatorOptions = {
  id: 'timenav',
  buttons: ['zoomOut', 'zoomIn', null, 'resetScale', null, 'panLeftBar', 'panRightBar'],
  size: 26,
  gap: 4,
  groupGap: 16,
  bottomMargin: 10,
  revealHeight: 64,
  fadeSeconds: 0.12,
  labels: DEFAULT_LABELS,
  hints: {},
  showTooltip: true,
  font: 11,
  radius: 6,
  zOrder: 'top',
};

interface Box {
  action: TimeNavigatorAction;
  x: number;
  y: number;
  w: number;
  h: number;
}

export class TimeNavigator implements IPrimitive {
  private _opts: TimeNavigatorOptions;
  private _host: PrimitiveHost | null = null;
  /** Button geometry from the last paint, in media px relative to the plot. */
  private _boxes: Box[] = [];
  /** Pointer in plot-local media px, or null when it left the pane. */
  private _pointer: { x: number; y: number } | null = null;
  /** 0 hidden, 1 fully shown. Eased toward the target each frame. */
  private _opacity = 0;
  private _lastFrameMs: number | null = null;
  private _now: () => number;

  public constructor(opts: Partial<TimeNavigatorOptions> = {}, now?: () => number) {
    this._opts = {
      ...DEFAULT_TIME_NAVIGATOR_OPTIONS, ...opts,
      labels: { ...DEFAULT_TIME_NAVIGATOR_OPTIONS.labels, ...opts.labels },
    };
    // Injectable so tests can step the fade deterministically.
    this._now = now ?? ((): number => (typeof performance !== 'undefined' ? performance.now() : 0));
  }

  public attached(host: PrimitiveHost): void { this._host = host; }
  public detached(): void { this._host = null; }
  public zOrder(): ZOrder { return this._opts.zOrder ?? 'top'; }
  public options(): TimeNavigatorOptions { return this._opts; }

  public setOptions(patch: Partial<TimeNavigatorOptions>): void {
    this._opts = {
      ...this._opts, ...patch,
      labels: { ...this._opts.labels, ...patch.labels },
    };
    this._host?.requestUpdate();
  }

  /**
   * Tell the navigator where the pointer is, in plot-local media px. `null`
   * when it leaves. The chart calls this; hosts driving their own navigator
   * should too.
   */
  public setPointer(p: { x: number; y: number } | null): void {
    const was = this._pointer;
    this._pointer = p;
    // Only repaint when the reveal state could actually change, so ordinary
    // crosshair movement across the chart body costs nothing.
    if ((was === null) !== (p === null) || this._opacity > 0 || this._targetOpacity() > 0) {
      this._host?.requestUpdate();
    }
  }

  /** True when the pointer is inside the reveal band. */
  private _revealed(): boolean {
    return this._pointer !== null && this._pointer.y >= this._revealTop;
  }

  private _targetOpacity(): number {
    return this._revealed() ? 1 : 0;
  }

  /** Top of the reveal band, recomputed each paint from the plot height. */
  private _revealTop = Infinity;

  /** Whether the fade is still running: the chart keeps painting while true. */
  public animating(): boolean {
    return Math.abs(this._targetOpacity() - this._opacity) > 0.001;
  }

  public draw(ctx: CanvasRenderingContext2D, rc: PrimitiveRenderContext): void {
    const o = this._opts;
    const dpr = rc.dpr;
    this._revealTop = Math.max(0, rc.plotHeight - o.revealHeight);

    // Ease toward the target. A time-based step keeps the fade the same speed
    // whatever the frame rate, and survives a stalled tab without jumping.
    const target = this._targetOpacity();
    const nowMs = this._now();
    const dt = this._lastFrameMs === null ? 0 : Math.max(0, (nowMs - this._lastFrameMs) / 1000);
    this._lastFrameMs = nowMs;
    if (o.fadeSeconds <= 0 || dt <= 0) {
      if (o.fadeSeconds <= 0) this._opacity = target;
    } else {
      const step = dt / o.fadeSeconds;
      this._opacity += Math.sign(target - this._opacity) * Math.min(step, Math.abs(target - this._opacity));
    }
    if (this._opacity <= 0.001) { this._boxes = []; this._opacity = 0; return; }

    // ── layout: one centred row, groups separated by the wider gap ──────────
    const size = o.size;
    let total = 0;
    for (let i = 0; i < o.buttons.length; i++) {
      const b = o.buttons[i];
      if (b === null) { total += o.groupGap; continue; }
      total += size;
      // A gap follows every button except the last, and a group gap replaces it.
      if (i < o.buttons.length - 1 && o.buttons[i + 1] !== null) total += o.gap;
    }
    const startX = (rc.plotWidth - total) / 2;
    const y = rc.plotHeight - o.bottomMargin - size;

    this._boxes = [];
    let x = startX;
    for (let i = 0; i < o.buttons.length; i++) {
      const action = o.buttons[i] as TimeNavigatorAction | null; // i is inside the list
      if (action === null) { x += o.groupGap; continue; }
      this._boxes.push({ action, x, y, w: size, h: size });
      x += size;
      if (i < o.buttons.length - 1 && o.buttons[i + 1] !== null) x += o.gap;
    }

    const hovered = this._hoveredAction();
    ctx.save();
    ctx.globalAlpha = this._opacity;
    for (const b of this._boxes) this._button(ctx, b, b.action === hovered, rc, dpr);
    if (o.showTooltip && hovered !== null) this._tooltip(ctx, hovered, rc, dpr);
    ctx.restore();
  }

  /** Which button the pointer is over, or null. */
  private _hoveredAction(): TimeNavigatorAction | null {
    const p = this._pointer;
    if (p === null) return null;
    for (const b of this._boxes) {
      if (p.x >= b.x && p.x <= b.x + b.w && p.y >= b.y && p.y <= b.y + b.h) return b.action;
    }
    return null;
  }

  private _button(
    ctx: CanvasRenderingContext2D,
    b: Box,
    hot: boolean,
    rc: PrimitiveRenderContext,
    dpr: number,
  ): void {
    const o = this._opts;
    const x = b.x * dpr;
    const y = b.y * dpr;
    const w = b.w * dpr;
    const h = b.h * dpr;
    const r = Math.min(o.radius * dpr, w / 2, h / 2);

    ctx.beginPath();
    ctx.roundRect(x, y, w, h, r);
    // An opaque plate: these sit over candles, and a translucent one leaves the
    // series showing through the glyph, which reads as a rendering fault.
    ctx.fillStyle = hot ? mix(rc.theme.background, rc.theme.axisText, 0.28)
      : mix(rc.theme.background, rc.theme.axisText, 0.12);
    ctx.fill();
    ctx.strokeStyle = withAlpha(rc.theme.axisLine, hot ? 1 : 0.8);
    ctx.lineWidth = Math.max(1, Math.round(dpr));
    ctx.stroke();

    ctx.strokeStyle = rc.theme.axisText;
    ctx.fillStyle = rc.theme.axisText;
    ctx.lineWidth = Math.max(1, Math.round(1.5 * dpr));
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    const cx = x + w / 2;
    const cy = y + h / 2;
    const g = Math.min(w, h) * 0.22;   // half-extent of the glyph
    ctx.beginPath();
    switch (b.action) {
      case 'zoomOut':
        ctx.moveTo(cx - g, cy); ctx.lineTo(cx + g, cy);
        break;
      case 'zoomIn':
        ctx.moveTo(cx - g, cy); ctx.lineTo(cx + g, cy);
        ctx.moveTo(cx, cy - g); ctx.lineTo(cx, cy + g);
        break;
      case 'resetScale': {
        const tip = g * Math.SQRT1_2;
        ctx.arc(cx, cy, g, -Math.PI * 0.75, Math.PI * 0.75);
        ctx.moveTo(cx - tip, cy - tip * 2);
        ctx.lineTo(cx - tip, cy - tip);
        ctx.lineTo(cx, cy - tip);
        break;
      }
      case 'panLeftBar':
        ctx.moveTo(cx + g * 0.55, cy - g); ctx.lineTo(cx - g * 0.5, cy); ctx.lineTo(cx + g * 0.55, cy + g);
        break;
      case 'panRightBar':
        ctx.moveTo(cx - g * 0.55, cy - g); ctx.lineTo(cx + g * 0.5, cy); ctx.lineTo(cx - g * 0.55, cy + g);
        break;
    }
    ctx.stroke();
  }

  private _tooltip(
    ctx: CanvasRenderingContext2D,
    action: TimeNavigatorAction,
    rc: PrimitiveRenderContext,
    dpr: number,
  ): void {
    const o = this._opts;
    const box = this._boxes.find((b) => b.action === action);
    if (box === undefined) return;
    const label = o.labels[action] ?? DEFAULT_LABELS[action];
    const hint = o.hints[action];

    ctx.font = `${o.font * dpr}px ui-sans-serif, system-ui, sans-serif`;
    ctx.textBaseline = 'middle';
    ctx.textAlign = 'left';
    const padX = 7 * dpr;
    const gap = 8 * dpr;
    const labelW = ctx.measureText(label).width;
    const hintW = hint === undefined ? 0 : ctx.measureText(hint).width + gap + 8 * dpr;
    const w = padX * 2 + labelW + hintW;
    const h = 22 * dpr;
    // Centre over the button, then keep it inside the plot.
    let x = (box.x + box.w / 2) * dpr - w / 2;
    x = Math.max(2 * dpr, Math.min(x, rc.plotWidth * dpr - w - 2 * dpr));
    const y = box.y * dpr - h - 6 * dpr;

    ctx.beginPath();
    ctx.roundRect(x, y, w, h, 5 * dpr);
    ctx.fillStyle = mix(rc.theme.background, rc.theme.axisText, 0.22);
    ctx.fill();
    ctx.strokeStyle = withAlpha(rc.theme.axisLine, 0.9);
    ctx.lineWidth = Math.max(1, Math.round(dpr));
    ctx.stroke();

    ctx.fillStyle = rc.theme.axisText;
    ctx.fillText(label, x + padX, y + h / 2);
    if (hint !== undefined) {
      const hx = x + padX + labelW + gap;
      const hw = ctx.measureText(hint).width + 8 * dpr;
      ctx.beginPath();
      ctx.roundRect(hx - 4 * dpr, y + 4 * dpr, hw, h - 8 * dpr, 3 * dpr);
      ctx.fillStyle = mix(rc.theme.background, rc.theme.axisText, 0.42);
      ctx.fill();
      ctx.fillStyle = rc.theme.axisText;
      ctx.fillText(hint, hx, y + h / 2);
    }
  }

  /**
   * Buttons hit-test only while visible, so a hidden navigator never steals a
   * click from the chart body underneath it.
   */
  public hitTest(x: number, y: number): PrimitiveHit | null {
    if (this._opacity < 0.5) return null;
    for (const b of this._boxes) {
      if (x >= b.x && x <= b.x + b.w && y >= b.y && y <= b.y + b.h) {
        return {
          externalId: `${this._opts.id}::${b.action}`,
          zOrder: 'top',
          distance: 0,
          cursor: 'pointer',
        };
      }
    }
    return null;
  }
}

/** Blend two colours; `t` 0 -> a, 1 -> b. Used for opaque plates over the series. */
function mix(a: string, b: string, t: number): string {
  const ca = parseColor(a);
  const cb = parseColor(b);
  if (ca === null || cb === null) return a;
  const k = t < 0 ? 0 : t > 1 ? 1 : t;
  const ch = (from: number, to: number): number => Math.round(from + (to - from) * k);
  return `rgb(${ch(ca.r, cb.r)},${ch(ca.g, cb.g)},${ch(ca.b, cb.b)})`;
}
