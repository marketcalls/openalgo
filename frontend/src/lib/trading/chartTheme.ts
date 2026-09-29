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

/** The colour painted over an opaque background, as read straight back. */
function over(background: string, color: string): Uint8ClampedArray {
  const c = ctx as CanvasRenderingContext2D
  c.fillStyle = background
  c.fillRect(0, 0, 1, 1)
  c.fillStyle = color
  c.fillRect(0, 0, 1, 1)
  return c.getImageData(0, 0, 1, 1).data
}

/**
 * Any CSS colour as a plain `rgb()` or `rgba()` string the canvas will parse.
 *
 * **The alpha has to survive this, and for a long time it did not.** The app's
 * `--border` is white at a tenth opacity, which is a hairline on a dark panel.
 * Read as three channels and handed on as `rgb(245,255,255)` it became a solid
 * near-white line: the chart drew its axis in it, and the chart's own dialogs
 * derive every input and select border from the same value, so every form
 * control in them was outlined in near-white while the app's controls beside
 * them wore the tenth. Nothing was broken enough to look broken, which is why
 * it lasted.
 *
 * **Painted over two known backgrounds rather than over nothing.** Reading a
 * colour off a cleared canvas means asking the browser to undo its own
 * premultiplication, and at a tenth opacity that rounding turned pure white
 * into `245,255,255`. Over black a pixel reads `C x a`, and over white it reads
 * `C x a + 255 x (1 - a)`; subtracting the two gives the alpha exactly and the
 * colour follows from it. Two fills instead of one, on a single pixel, at theme
 * changes only.
 */
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
  // Resolve the variable through the DOM first (it applies the active theme
  // class), then let the canvas normalise whatever comes back: oklch, hsl,
  // color-mix, a named colour. Assigning an invalid value leaves `fillStyle`
  // as it was, so the black set first is what an unparseable colour becomes.
  // Cleared first. Assigning a value the browser rejects leaves the property
  // as it was, so without this an unreadable colour quietly resolves to
  // whatever the last readable one was: the caller gets a real colour, from
  // the wrong token, and nothing anywhere says so.
  probe.style.color = ''
  probe.style.color = cssColor
  const resolved = probe.style.color === '' ? '#000' : getComputedStyle(probe).color || '#000'
  ctx.fillStyle = '#000'
  ctx.fillStyle = resolved
  const parsed = ctx.fillStyle as string

  const onBlack = over('#000', parsed)
  const onWhite = over('#fff', parsed)
  // Every channel gives the same alpha, so the three are averaged: one channel
  // alone carries its own rounding, and on a grey token that is the whole error.
  let alpha = 0
  for (let i = 0; i < 3; i++) alpha += 1 - (onWhite[i] - onBlack[i]) / 255
  alpha = Math.min(1, Math.max(0, alpha / 3))

  if (alpha >= 0.999) return `rgb(${onBlack[0]},${onBlack[1]},${onBlack[2]})`
  if (alpha <= 0.001) return 'rgba(0,0,0,0)'
  const channel = (value: number): number => Math.min(255, Math.max(0, Math.round(value / alpha)))
  const [r, g, b] = [channel(onBlack[0]), channel(onBlack[1]), channel(onBlack[2])]
  return `rgba(${r},${g},${b},${Math.round(alpha * 1000) / 1000})`
}

const token = (name: string) => rasterize(`var(${name})`)

/**
 * Any CSS colour as an `rgb()` or `rgba()` string the canvas is certain to
 * parse: a token, a computed style read back off an element, anything.
 * Exported for code that paints app-themed text onto a canvas (the chart's PNG
 * export). A token with alpha keeps it, which is what the chart's axis lines
 * and the control borders in its dialogs are made of.
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

/**
 * Control metrics for the chart's own dialogs, so their forms match the app's.
 *
 * The engine ships its dialogs as canvas-adjacent DOM with its own token set,
 * and its defaults are a step smaller than this app's: a 28px control against
 * our 32px, 12.5px text against 14px, a 7px corner against 8px. Each gap is
 * small and together they are what makes the alert editor read as a window
 * from somewhere else, sitting over a page whose every other control agrees.
 *
 * Written as the engine's own custom properties rather than as CSS that fights
 * it. The tokens are the documented surface, they are applied to the widget
 * root as inline properties, and setting the same properties afterwards is
 * using that surface rather than overriding an internal. A stylesheet could
 * not win against an inline property without `!important` on every rule, which
 * is the brittle version of this and breaks the first time the engine renames
 * a class.
 *
 * The text is 13px rather than the app's 14px, and that is deliberate: 14px is
 * the size of a control you meet one at a time in a page, and the alert editor
 * is nine fields in a column. The rest of the scale is the app's exactly.
 */
export const CHART_DIALOG_METRICS: Readonly<Record<string, string>> = {
  '--oac-ctl-h': '32px',
  '--oac-fs': '13px',
  '--oac-radius': '8px',
}

/**
 * Applies them to one of the engine's widget roots.
 *
 * Called after the root is built, because the engine writes its own token set
 * on creation and on every theme change: these have to land after it, not
 * before, or the next theme write takes them off again.
 */
export function applyChartDialogMetrics(root: HTMLElement): void {
  for (const [name, value] of Object.entries(CHART_DIALOG_METRICS)) {
    root.style.setProperty(name, value)
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
