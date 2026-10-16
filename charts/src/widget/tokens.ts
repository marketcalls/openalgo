/**
 * Design tokens for the widget chrome, as CSS custom properties derived from
 * the chart theme in force.
 *
 * The engine's `ChartTheme` names a dozen colours for the canvas (background,
 * grid, axis text, the candle pair, the line colour). The rail, the top bar
 * and every dialog need perhaps thirty: panel and raised-panel greys, a soft
 * and a firm border, three text weights, an accent and its pressed tint. None
 * of those is worth a second palette a host has to keep in step with the
 * first, so every one is computed here from the theme, and switching the
 * chart's theme restyles the chrome in the same call.
 *
 * Pure: strings in, strings out. `applyTokens` is the one function that
 * touches an element, and it only writes `style.setProperty`.
 */
import type { ChartTheme } from 'openalgo-charts';
// A pure helper, so importing it by path inlines the one function and nothing
// else. It reads the canvas module's `Rgba`, which the widget's own `Rgba` below
// matches field for field. The widget keeps its own declaration because it is
// published: re-exporting the canvas one would move the reference page and hand
// the type the pill module's header as its doc comment.
import { srgbLuminance } from '../render/pill';

/** Every custom property carries this prefix, so a host stylesheet cannot collide with one. */
export const TOKEN_PREFIX = '--oac-';

export type WidgetThemeName = 'dark' | 'light';

/** Property name (with the prefix) to value. */
export type WidgetTokens = Readonly<Record<string, string>>;

export interface Rgba { r: number; g: number; b: number; a: number }

const clamp01 = (v: number): number => (v < 0 ? 0 : v > 1 ? 1 : v);

/**
 * Parse a CSS colour in the forms a theme uses: `#rgb`, `#rgba`, `#rrggbb`,
 * `#rrggbbaa`, `rgb()` and `rgba()`. Anything else (a named colour, `hsl()`)
 * is returned as null, and the caller falls back to a sensible neutral rather
 * than throwing: a theme with one exotic colour should still get chrome.
 */
export function parseColor(input: string): Rgba | null {
  const s = input.trim();
  const hex = /^#([0-9a-f]{3,8})$/i.exec(s);
  if (hex !== null) {
    const h = hex[1]!; // the group is not optional, so any match fills it
    if (h.length === 3 || h.length === 4) {
      const wide = h.split('').map((c) => c + c).join('');
      return parseColor('#' + wide);
    }
    if (h.length !== 6 && h.length !== 8) return null;
    const r = parseInt(h.slice(0, 2), 16);
    const g = parseInt(h.slice(2, 4), 16);
    const b = parseInt(h.slice(4, 6), 16);
    const a = h.length === 8 ? parseInt(h.slice(6, 8), 16) / 255 : 1;
    return { r, g, b, a };
  }
  // The separator is a comma with optional space, or space alone. Written as one
  // alternation rather than `\s*[, ]\s*`, whose space-in-the-class overlaps the
  // neighbouring `\s*` and makes a long run of spaces backtrack quadratically.
  const fn = /^rgba?\(\s*([\d.]+)(?:\s*,\s*|\s+)([\d.]+)(?:\s*,\s*|\s+)([\d.]+)(?:\s*[,/]\s*([\d.]+%?))?\s*\)$/i.exec(s);
  if (fn !== null) {
    let a = 1;
    if (fn[4] !== undefined) a = fn[4].endsWith('%') ? Number(fn[4].slice(0, -1)) / 100 : Number(fn[4]);
    return { r: Number(fn[1]), g: Number(fn[2]), b: Number(fn[3]), a: clamp01(a) };
  }
  return null;
}

const hex2 = (v: number): string => Math.round(Math.max(0, Math.min(255, v))).toString(16).padStart(2, '0');

/** Serialise: opaque colours as `#rrggbb`, translucent ones as `rgba()`. */
export function formatColor(c: Rgba): string {
  if (c.a >= 1) return `#${hex2(c.r)}${hex2(c.g)}${hex2(c.b)}`;
  return `rgba(${Math.round(c.r)},${Math.round(c.g)},${Math.round(c.b)},${Math.round(c.a * 1000) / 1000})`;
}

/**
 * Relative luminance, 0 (black) to 1 (white), on the sRGB curve. The canvas
 * helpers' arithmetic read through this module's parser, so a colour only the
 * widget can parse (space-separated `rgb()`) still gets a real reading.
 */
export function luminance(color: string): number {
  const c = parseColor(color);
  return c === null ? 0.5 : srgbLuminance(c);
}

/**
 * The WCAG contrast ratio of two colours, 1 (none) to 21 (black on white).
 * Alpha is ignored: a token is read as the colour it is painted in.
 */
export function contrastRatio(a: string, b: string): number {
  const la = luminance(a);
  const lb = luminance(b);
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
}

/** The WCAG AA minimum for body-size text, which every chrome label is. */
export const TEXT_CONTRAST = 4.5;

/**
 * `color` as text on every one of `surfaces`: unchanged when it already reads
 * at `min` against each, else stepped toward `pole` by the least amount that
 * does. The least, so a dim role stays as dim as the rule allows and keeps
 * its place below the brighter ones. A pole that cannot reach `min` gives
 * the pole itself, the most any colour could do on those surfaces.
 */
export function readableOn(color: string, surfaces: readonly string[], pole: string, min = TEXT_CONTRAST): string {
  const passes = (c: string): boolean => surfaces.every((s) => contrastRatio(c, s) >= min);
  if (passes(color)) return color;
  if (!passes(pole)) return pole;
  let lo = 0;
  let hi = 1;
  // Twenty halvings resolve the blend far below one step of an 8-bit channel.
  for (let i = 0; i < 20; i++) {
    const mid = (lo + hi) / 2;
    if (passes(mix(color, pole, mid))) hi = mid; else lo = mid;
  }
  // The blend rounds to whole channels, which can land a hair under the line.
  for (let t = hi; t <= 1; t += 1 / 256) {
    const c = mix(color, pole, t);
    if (passes(c)) return c;
  }
  return pole;
}

/** Which of the two modes a theme is, judged from its background. */
export function themeMode(theme: Pick<ChartTheme, 'background'>): WidgetThemeName {
  return luminance(theme.background) < 0.35 ? 'dark' : 'light';
}

/** Linear blend of `a` toward `b` by `t` (0 keeps `a`, 1 gives `b`). Alpha blends too. */
export function mix(a: string, b: string, t: number): string {
  const ca = parseColor(a);
  const cb = parseColor(b);
  if (ca === null || cb === null) return a;
  const k = clamp01(t);
  return formatColor({
    r: ca.r + (cb.r - ca.r) * k,
    g: ca.g + (cb.g - ca.g) * k,
    b: ca.b + (cb.b - ca.b) * k,
    a: ca.a + (cb.a - ca.a) * k,
  });
}

/**
 * The colour with its alpha replaced, written as a token value: `#rrggbb` when
 * opaque, otherwise `rgba()` with the alpha clamped and rounded. Deliberately
 * not the base package's `withAlpha`, which feeds canvas and always writes
 * `rgba()` with the alpha as given; callers of each rely on its output.
 */
export function withAlpha(color: string, alpha: number): string {
  const c = parseColor(color);
  if (c === null) return color;
  return formatColor({ ...c, a: clamp01(alpha) });
}

/** The system UI stack every piece of chrome sets in text. */
export const WIDGET_FONT = 'ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif';
export const WIDGET_MONO = 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace';

/** Layout measurements, in CSS pixels, shared by the stylesheet and the placement maths. */
export const RAIL_WIDTH = 42;
export const TOPBAR_HEIGHT = 40;
export const STATUSLINE_HEIGHT = 24;

/**
 * Compute the token set for a theme.
 *
 * Every grey is the background stepped toward the opposite pole (white on a
 * dark theme, near-black on a light one), so a host theme with a blue-black
 * background gets blue-black panels rather than a neutral grey pasted onto
 * it. The accent is the theme's line colour, the up and down pair are the
 * candle colours, and text comes from the axis text colour lifted for
 * legibility: the axis is deliberately muted on the canvas, and a panel label
 * at that weight reads as disabled.
 */
export function widgetTokens(theme: ChartTheme, mode: WidgetThemeName = themeMode(theme)): WidgetTokens {
  const dark = mode === 'dark';
  const bg = theme.background;
  const pole = dark ? '#ffffff' : '#0c1120';
  const step = (t: number): string => mix(bg, pole, t);
  const accent = theme.lineColor;
  const text = mix(theme.axisText, pole, dark ? 0.55 : 0.6);
  const panel = step(dark ? 0.035 : 0.02);
  const panel2 = step(dark ? 0.02 : 0.045);
  const elev = step(dark ? 0.07 : 0.06);
  const elev2 = step(dark ? 0.11 : 0.1);
  // Where chrome text rests: the chart, the bars, the rail and a raised
  // control. A hovered row and the tooltip sit a step higher on `elev-2`, so
  // text there takes `mut`, which reads on that step as well.
  const resting = [bg, panel, panel2, elev];
  const readable = (color: string, on: readonly string[] = resting): string => readableOn(color, on, pole);
  const t: Record<string, string> = {
    bg,
    panel,
    'panel-2': panel2,
    elev,
    'elev-2': elev2,
    'elev-3': step(dark ? 0.18 : 0.16),
    bd: theme.axisLine,
    'bd-soft': theme.paneSeparator,
    'bd-hover': mix(theme.axisLine, pole, 0.25),
    tx: text,
    'tx-strong': mix(text, pole, 0.5),
    // The axis colour is the host's; as panel text it has to read on every
    // step, the hovered one included.
    mut: readable(theme.axisText, [...resting, elev2]),
    // Dimmer than `mut`, but only as far as the text contrast minimum allows:
    // hints, chords and section heads are read, not decoration.
    faint: readable(mix(theme.axisText, bg, 0.4)),
    acc: accent,
    'acc-2': mix(accent, pole, dark ? 0.2 : 0.1),
    'on-bg': withAlpha(accent, 0.16),
    'on-bd': mix(accent, bg, 0.45),
    ring: accent,
    'ring-soft': withAlpha(accent, 0.2),
    buy: theme.upColor,
    sell: theme.downColor,
    // The candle pair as text (a change, a watchlist move): a light theme's
    // green is a fill colour and too pale to read at label size.
    up: readable(theme.upColor),
    down: readable(theme.downColor),
    amber: readable(dark ? '#e6b53c' : '#b8860b'),
    danger: readable(mix(theme.downColor, pole, dark ? 0.3 : 0.1), [...resting, elev2]),
    scrim: dark ? 'rgba(6,8,12,0.55)' : 'rgba(24,30,40,0.38)',
    shadow: dark ? '0 14px 40px rgba(0,0,0,0.55)' : '0 14px 40px rgba(24,32,48,0.16)',
    'sb-thumb': step(dark ? 0.16 : 0.2),
    'sb-thumb-hover': step(dark ? 0.24 : 0.3),
    font: WIDGET_FONT,
    mono: WIDGET_MONO,
    fs: '12.5px',
    radius: '7px',
    'rail-w': `${RAIL_WIDTH}px`,
    'topbar-h': `${TOPBAR_HEIGHT}px`,
    'status-h': `${STATUSLINE_HEIGHT}px`,
    'ctl-h': '28px',
  };
  const out: Record<string, string> = {};
  for (const [k, v] of Object.entries(t)) out[TOKEN_PREFIX + k] = v;
  return out;
}

/** Write a token set onto an element as inline custom properties. */
export function applyTokens(el: HTMLElement, tokens: WidgetTokens): void {
  for (const [k, v] of Object.entries(tokens)) el.style.setProperty(k, v);
}

/** `var(--oac-name)`, for code that builds inline style values from a token. */
export const token = (name: string): string => `var(${TOKEN_PREFIX}${name})`;
