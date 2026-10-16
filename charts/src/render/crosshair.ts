/**
 * Crosshair renderer (ARCHITECTURE.md §3.1, §6). Drawn on each pane's *top*
 * canvas so a cursor move only repaints the cheap overlay.
 *
 * The vertical (time) line is drawn in every pane for a synced **global**
 * crosshair; the horizontal (price) line + price tag are drawn only in the pane
 * under the cursor; the time tag is drawn on the bottom pane's axis strip.
 * Lines are a 1-device-px hairline so they stay thin/subtle on HiDPI.
 */
import { dashPattern } from './grid';
import type { CanvasLineStyle } from './grid';
import type { ChartTheme } from '../theme';
import { DEFAULT_AXIS_STYLE, scaleFont, type AxisStyle } from './axis';

/**
 * The Canvas tab's crosshair controls. Same precedence as the rest of the
 * canvas block (see grid.ts): set overrides the theme, unset falls through.
 */
export interface CrosshairOptions {
  /** Line colour. Unset falls back to `theme.crosshair`. */
  color?: string;
  /** Line dash. Unset falls back to `theme.crosshairStyle`, then dashed. */
  style?: CanvasLineStyle;
  /** Line width in device px (1 = hairline). Unset falls back to the theme. */
  width?: number;
}

/** Resolved crosshair line style, ready for `drawCrosshair`. */
export interface CrosshairStyle {
  color: string;
  width: number;
  dash: number[];
}

/** Fold the crosshair options over the theme. */
export function resolveCrosshairStyle(
  theme: Pick<ChartTheme, 'crosshair' | 'crosshairStyle' | 'crosshairWidth'>,
  opts: CrosshairOptions | undefined,
  dpr: number,
): CrosshairStyle {
  return {
    color: opts?.color ?? theme.crosshair,
    width: opts?.width ?? theme.crosshairWidth ?? 1,
    // The crosshair reads as dashed by default; the grid reads as solid.
    dash: dashPattern(opts?.style ?? theme.crosshairStyle ?? 'dashed', dpr),
  };
}

/** Draw the crosshair lines. `y === null` draws the vertical line only. */
export function drawCrosshair(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number | null,
  plotWidth: number,
  plotHeight: number,
  dpr: number,
  color: string,
  width = 1,
  dash: number[] = [4 * dpr, 4 * dpr],
): void {
  ctx.save();
  ctx.strokeStyle = color;
  ctx.lineWidth = Math.max(1, width); // device px; 1 = hairline (thin on HiDPI)
  ctx.setLineDash(dash);
  if (x >= 0 && x <= plotWidth) {
    const px = Math.round(x * dpr) + 0.5;
    ctx.beginPath();
    ctx.moveTo(px, 0);
    ctx.lineTo(px, Math.round(plotHeight * dpr));
    ctx.stroke();
  }
  if (y !== null && y >= 0 && y <= plotHeight) {
    const py = Math.round(y * dpr) + 0.5;
    ctx.beginPath();
    ctx.moveTo(0, py);
    ctx.lineTo(Math.round(plotWidth * dpr), py);
    ctx.stroke();
  }
  ctx.setLineDash([]);
  ctx.restore();
}

/**
 * Width in device px of the box `drawCrosshairTag` draws for `text` with the
 * 'right' anchor, from `cx` to its far edge. A tag on a left strip is placed
 * by it, so it ends at the strip's edge.
 */
export function crosshairTagWidth(ctx: CanvasRenderingContext2D, text: string, dpr: number, style: AxisStyle = DEFAULT_AXIS_STYLE): number {
  ctx.save();
  ctx.font = scaleFont(style.font, dpr);
  const w = ctx.measureText(text).width + 12 * dpr + 1;
  ctx.restore();
  return w;
}

/**
 * Draw a filled crosshair value tag (price on the right axis, or time on the
 * bottom axis), in the axis text style so it reads like the labels beside it.
 * All coordinates are device px. `anchor`:
 *  - 'right': box starts at (cx) and extends right, vertically centred on cy
 *  - 'bottom': box centred on cx, top edge at cy
 */
export function drawCrosshairTag(
  ctx: CanvasRenderingContext2D,
  text: string,
  cx: number,
  cy: number,
  dpr: number,
  bg: string,
  fg: string,
  anchor: 'right' | 'bottom',
  style: AxisStyle = DEFAULT_AXIS_STYLE,
): void {
  ctx.save();
  ctx.font = scaleFont(style.font, dpr);
  const padX = 6 * dpr;
  const h = 16 * dpr;
  const tw = ctx.measureText(text).width;
  ctx.fillStyle = bg;
  ctx.textBaseline = 'middle';
  if (anchor === 'right') {
    ctx.fillRect(cx + 1, cy - h / 2, tw + padX * 2, h);
    ctx.fillStyle = fg;
    ctx.textAlign = 'left';
    ctx.fillText(text, cx + 1 + padX, cy);
  } else {
    const bw = tw + padX * 2;
    ctx.fillRect(cx - bw / 2, cy, bw, h);
    ctx.fillStyle = fg;
    ctx.textAlign = 'center';
    ctx.fillText(text, cx, cy + h / 2);
  }
  ctx.restore();
}
