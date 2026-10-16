/**
 * Background grid (ARCHITECTURE.md §6) and the shared "Canvas" option block the
 * settings dialog drives. The grid is evenly spaced (`spacing`, 60 px unless
 * the canvas block sets it), independent of the axis tick marks.
 *
 * WHY the options live next to the grid: the grid is the largest of the canvas
 * controls and already owned the line-style vocabulary, so the sibling
 * renderers (crosshair, axis) borrow the type and the dash table from here
 * rather than each growing a private copy.
 *
 * WHY option-over-theme and not a second palette: every colour here already
 * exists on `ChartTheme`, which renderers read when a per-object style is
 * absent, and that is what makes one theme restyle the whole chart. So the
 * canvas options are *overrides*: set means use it, unset means fall through to
 * the theme. Copying theme colours into the options at construction (the other
 * plausible shape) would freeze the palette and make a later `setTheme` a
 * silent no-op for anything the dialog had touched.
 */
import { clamp, snapToDevicePixel } from '../helpers/math';
import type { ChartTheme } from '../theme';
import type { AxisStyle } from './axis';
import type { CrosshairOptions } from './crosshair';

interface GridLines {
  /** Vertical line x-positions in media (CSS) px. */
  verticals: number[];
  /** Horizontal line y-positions in media (CSS) px. */
  horizontals: number[];
}

/** Dash style shared by the grid, crosshair and any other chrome line. */
export type CanvasLineStyle = 'solid' | 'dashed' | 'dotted';

/**
 * Dash pattern in device px for a line style. `solid` (and an unset style)
 * yields an empty array, which is what `setLineDash` wants for a plain line.
 */
export function dashPattern(style: CanvasLineStyle | undefined, dpr: number): number[] {
  if (style === 'dashed') return [4 * dpr, 4 * dpr];
  if (style === 'dotted') return [1 * dpr, 3 * dpr];
  return [];
}

export interface GridOptions {
  /** Target spacing between grid lines, in media px. */
  spacing: number;
  /** Draw the vertical (time) lines. Default true. */
  vertLines?: boolean;
  /** Draw the horizontal (price) lines. Default true. */
  horzLines?: boolean;
  /** Vertical line colour. Unset falls back to `theme.grid`. */
  vertColor?: string;
  /** Horizontal line colour. Unset falls back to `theme.grid`. */
  horzColor?: string;
  /** Vertical line dash. Unset falls back to `theme.gridStyle`, then solid. */
  vertStyle?: CanvasLineStyle;
  /** Horizontal line dash. Unset falls back to `theme.gridStyle`, then solid. */
  horzStyle?: CanvasLineStyle;
  /** Line width in media px. Default 1. */
  lineWidth?: number;
}

/**
 * Pure: compute evenly-spaced grid line positions for a pane of the given
 * media size. Lines start one `spacing` in from the top-left and never sit on
 * the 0 edge (which the axis border owns). An axis switched off returns no
 * positions, so visibility costs the renderer nothing downstream.
 */
export function computeGridLines(width: number, height: number, opts: GridOptions): GridLines {
  const spacing = Math.max(1, opts.spacing);
  const verticals: number[] = [];
  if (opts.vertLines !== false) for (let x = spacing; x < width; x += spacing) verticals.push(x);
  const horizontals: number[] = [];
  if (opts.horzLines !== false) for (let y = spacing; y < height; y += spacing) horizontals.push(y);
  return { verticals, horizontals };
}

/** Colour + dash for one axis of the grid. */
export interface GridAxisStyle {
  color?: string;
  /** Dash pattern (device px already applied by the caller's dpr). */
  dash?: number[];
}

export interface GridStyle {
  color: string;
  lineWidth: number;
  /** Optional dash pattern (device px already applied by the caller's dpr). */
  dash?: number[];
  /** Vertical-line overrides; each field falls back to the flat pair above. */
  vert?: GridAxisStyle;
  /** Horizontal-line overrides; each field falls back to the flat pair above. */
  horz?: GridAxisStyle;
}

/**
 * Fold the canvas grid options over the theme into the style `drawGrid` takes.
 * `theme.grid` / `theme.gridStyle` are the defaults for both axes; a per-axis
 * option replaces one of them without disturbing the other.
 */
export function resolveGridStyle(
  theme: Pick<ChartTheme, 'grid' | 'gridStyle'>,
  opts: Partial<GridOptions> | undefined,
  dpr: number,
): GridStyle {
  const themeDash = dashPattern(theme.gridStyle, dpr);
  return {
    color: theme.grid,
    lineWidth: opts?.lineWidth ?? 1,
    dash: themeDash,
    vert: {
      color: opts?.vertColor ?? theme.grid,
      dash: opts?.vertStyle === undefined ? themeDash : dashPattern(opts.vertStyle, dpr),
    },
    horz: {
      color: opts?.horzColor ?? theme.grid,
      dash: opts?.horzStyle === undefined ? themeDash : dashPattern(opts.horzStyle, dpr),
    },
  };
}

/**
 * Draw the grid onto a bitmap-scope context (device px). Coordinates are given
 * in media px and snapped to crisp device-pixel edges. The two axes stroke
 * separately because each carries its own colour and dash.
 */
export function drawGrid(
  ctx: CanvasRenderingContext2D,
  lines: GridLines,
  mediaWidth: number,
  mediaHeight: number,
  dpr: number,
  style: GridStyle,
): void {
  ctx.save();
  ctx.lineWidth = Math.max(1, Math.round(style.lineWidth * dpr));
  const w = Math.round(mediaWidth * dpr);
  const h = Math.round(mediaHeight * dpr);
  strokeAxis(ctx, lines.verticals, true, style.vert, style, dpr, w, h);
  strokeAxis(ctx, lines.horizontals, false, style.horz, style, dpr, w, h);
  ctx.setLineDash([]);
  ctx.restore();
}

function strokeAxis(
  ctx: CanvasRenderingContext2D,
  positions: number[],
  vertical: boolean,
  axis: GridAxisStyle | undefined,
  style: GridStyle,
  dpr: number,
  w: number,
  h: number,
): void {
  if (positions.length === 0) return;
  ctx.strokeStyle = axis?.color ?? style.color;
  ctx.setLineDash(axis?.dash ?? style.dash ?? []);
  ctx.beginPath();
  for (const p of positions) {
    const q = Math.round(snapToDevicePixel(p, dpr) * dpr);
    if (vertical) {
      ctx.moveTo(q, 0);
      ctx.lineTo(q, h);
    } else {
      ctx.moveTo(0, q);
      ctx.lineTo(w, q);
    }
  }
  ctx.stroke();
}

/** The "Scales: Text" and "Scales: Lines" controls. */
export interface ScaleCanvasOptions {
  /** Tick label colour. Unset falls back to `theme.axisText`. */
  textColor?: string;
  /** Tick label size in px, clamped to the dialog's 10..14 range. */
  fontSize?: number;
  /** Axis line and tick colour. Unset falls back to `theme.axisLine`. */
  lineColor?: string;
}

/** Bounds of the "Scales: Text" size control. */
export const SCALE_FONT_MIN = 10;
export const SCALE_FONT_MAX = 14;

/**
 * Fold the scale options over the theme into the axis renderer's style.
 *
 * Only the *option* is clamped to 10..14: a theme is code, not a dialog, and a
 * host that set `axisFontSize: 16` deliberately keeps it.
 */
export function resolveScaleStyle(
  theme: Pick<ChartTheme, 'axisText' | 'axisLine' | 'axisFontSize'>,
  opts: ScaleCanvasOptions | undefined,
): AxisStyle {
  const size = opts?.fontSize === undefined
    ? theme.axisFontSize ?? 11
    : clamp(Math.round(opts.fontSize), SCALE_FONT_MIN, SCALE_FONT_MAX);
  return {
    textColor: opts?.textColor ?? theme.axisText,
    lineColor: opts?.lineColor ?? theme.axisLine,
    font: `${size}px system-ui, sans-serif`,
  };
}

/** Plot-area margins, in percent of pane height (the dialog's units). */
export interface PlotMarginOptions {
  top?: number;
  bottom?: number;
}

/**
 * Percent -> the fraction `PriceScaleOptions.marginTop/marginBottom` already
 * store. There is no second margin state: the price scale stays the owner, this
 * only converts the dialog's units. Each side is capped at 49% so the pair
 * always leaves a band for the data (the scale itself only guards the sum with
 * a 1% floor, which would squash the plot to a line).
 */
export function resolvePlotMargins(opts: PlotMarginOptions | undefined): { marginTop?: number; marginBottom?: number } {
  const out: { marginTop?: number; marginBottom?: number } = {};
  if (opts?.top !== undefined) out.marginTop = clamp(opts.top, 0, 49) / 100;
  if (opts?.bottom !== undefined) out.marginBottom = clamp(opts.bottom, 0, 49) / 100;
  return out;
}

/**
 * Everything the settings dialog's Canvas tab can set, in one block.
 *
 * No watermark field: the mark is a primitive the host owns and configures
 * (`LogoWatermark`), so a switch here would be a stored value nothing reads.
 * Same rule as the settings schema itself, see model/chart-settings.ts.
 */
export interface CanvasOptions {
  grid?: Partial<GridOptions>;
  crosshair?: CrosshairOptions;
  scales?: ScaleCanvasOptions;
  /** Plot-area margins in percent of pane height. */
  margins?: PlotMarginOptions;
}
