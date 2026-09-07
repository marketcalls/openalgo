/**
 * Bridges the app's shadcn CSS theme tokens into an openalgo-charts `ChartTheme`
 * so the canvas chrome (background, grid, axes, crosshair) matches whatever
 * theme the app is in — live light, live dark, or the analyzer violet palette.
 *
 * Tokens are oklch, which the canvas color parser doesn't read; we resolve each
 * to a plain rgb() string by painting it onto a 1×1 canvas and reading the pixel
 * back — the same rasterize trick the standalone page used, so pill-text
 * contrast and axis colors stay correct on every browser.
 */
import { type ChartTheme, darkTheme, lightTheme } from 'openalgo-charts'
import type { AppMode, ThemeMode } from '@/stores/themeStore'

let probe: HTMLSpanElement | null = null
let ctx: CanvasRenderingContext2D | null = null

function rasterize(cssColor: string): string {
  if (!probe) {
    probe = document.createElement('span')
    probe.style.display = 'none'
    document.body.appendChild(probe)
    const cnv = document.createElement('canvas')
    cnv.width = cnv.height = 1
    ctx = cnv.getContext('2d', { willReadFrequently: true })
  }
  if (!ctx) return cssColor
  // Resolve the variable through the DOM first (applies the active theme class),
  // then rasterize whatever format comes back (oklch / hsl / rgb) to rgb.
  probe.style.color = cssColor
  const resolved = getComputedStyle(probe).color || '#000'
  ctx.clearRect(0, 0, 1, 1)
  ctx.fillStyle = '#000'
  ctx.fillStyle = resolved // invalid values keep #000
  ctx.fillRect(0, 0, 1, 1)
  const [r, g, b] = ctx.getImageData(0, 0, 1, 1).data
  return `rgb(${r},${g},${b})`
}

const token = (name: string) => rasterize(`var(${name})`)

/**
 * Any CSS colour as a plain `rgb()` string the canvas is certain to parse —
 * a token, a computed style read back off an element, anything. Exported for
 * code that paints app-themed text onto a canvas (the chart's PNG export).
 */
export const resolveCssColor = (cssColor: string): string => rasterize(cssColor)

/** True when the app is in live light mode (analyzer is always a dark palette). */
export function isLightTheme(mode: ThemeMode, appMode: AppMode): boolean {
  return appMode === 'live' && mode === 'light'
}

/** Build the canvas theme from the base palette + the app's live token colors. */
export function buildChartTheme(mode: ThemeMode, appMode: AppMode): ChartTheme {
  const base = isLightTheme(mode, appMode) ? lightTheme : darkTheme
  return {
    ...base,
    background: token('--background'),
    grid: token('--card'),
    axisText: token('--muted-foreground'),
    axisLine: token('--border'),
    crosshair: token('--muted-foreground'),
  }
}

/** Volume-histogram color that reads well against the current theme. */
export function volumeColor(mode: ThemeMode, appMode: AppMode): string {
  return isLightTheme(mode, appMode) ? '#d4d4d8' : '#33415e'
}

/**
 * The two colour forms this module ever meets: the library palette's hex and
 * the `rgb()` the token rasterizer produces. Anything else reads as null and
 * the caller keeps the colour it had; a guess here would be painted.
 */
function parseRgb(color: string): [number, number, number] | null {
  const hex = /^#([0-9a-f]{6})$/i.exec(color.trim())
  if (hex) {
    const n = Number.parseInt(hex[1], 16)
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
  }
  const rgb = /^rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/i.exec(color.trim())
  if (rgb) return [Number(rgb[1]), Number(rgb[2]), Number(rgb[3])]
  return null
}

/**
 * `color` moved `amount` of the way towards `towards`, in sRGB. At 0 it is the
 * colour itself, at 1 it is the target. Opaque on purpose: the trade buttons
 * derive their label colour from the fill's luminance, and a translucent fill
 * would give that reader nothing to go on.
 */
export function mixColors(color: string, towards: string, amount: number): string {
  const a = parseRgb(color)
  const b = parseRgb(towards)
  if (!a || !b) return color
  const t = Math.min(1, Math.max(0, amount))
  const ch = (i: number) => Math.round(a[i] + (b[i] - a[i]) * t)
  return `rgb(${ch(0)},${ch(1)},${ch(2)})`
}

/** How far the disarmed Buy and Sell sink towards the chart background. */
const DISARMED_BLEND = 0.55

/**
 * The Buy and Sell panel's colours while One-Click is off: the theme's own
 * pair pulled towards its background, so the buttons still say which is which
 * but no longer look like a thing that fires. Derived from the theme rather
 * than fixed so the same blend reads right on the light, dark and analyzer
 * palettes.
 */
export function mutedTradeColors(theme: Pick<ChartTheme, 'buy' | 'sell' | 'background'>): {
  buy: string
  sell: string
} {
  return {
    buy: mixColors(theme.buy, theme.background, DISARMED_BLEND),
    sell: mixColors(theme.sell, theme.background, DISARMED_BLEND),
  }
}
