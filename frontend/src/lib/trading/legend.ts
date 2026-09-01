/**
 * The charting terminal's OHLC readout, expressed as data rather than markup.
 *
 * One builder feeds two renderers: the live DOM overlay pinned to the top-left
 * of the pane (`legendHtml`), and the PNG export, which paints the same runs
 * onto the captured canvas (`terminal.ts`). openalgo-charts' `takeScreenshot()`
 * composites only its own pane canvases, so the DOM overlay is invisible to the
 * export -- sharing one model is what keeps the saved image and the screen
 * showing the same numbers instead of two hand-maintained copies drifting.
 *
 * Runs carry a semantic tone, not a colour. The DOM renderer stays relative to
 * the CSS theme (inherit the foreground, dim the meta with opacity) so a theme
 * toggle recolours it with no repaint, while the canvas renderer resolves the
 * tone to a concrete colour, which is all a canvas can paint.
 */

/** Candle direction colours, shared by the OHLC legend and the last-price line. */
export const UP = '#26a69a'
export const DN = '#ef5350'
/** Last-price colour before any bar exists to take a direction from. */
export const LTP_NEUTRAL = '#e0b020'

/** What a run of legend text means; each renderer maps this to its own styling. */
export type LegendTone = 'symbol' | 'meta' | 'up' | 'down' | 'ltp'

/** One contiguous, single-tone run of legend text. Carries no padding. */
export interface LegendRun {
  text: string
  tone: LegendTone
}

/** The bar the readout describes (the crosshair bar, else the latest one). */
export interface LegendBar {
  open: number
  high: number
  low: number
  close: number
  volume?: number
}

export interface LegendInput {
  symbol: string
  interval: string
  exchange: string
  /** Contract lot size, or null for an instrument quoted in shares. */
  lotsize: number | null
  bar: LegendBar | null
  /**
   * Close of the bar before `bar`, which is what the readout measures against.
   *
   * The legend describes **one bar**, and every number in it has to belong to
   * that same bar or the line reports two different moments at once. It used to
   * carry the live LTP and the day's change beside a crosshair bar's O/H/L/C, so
   * hovering a candle from three weeks ago printed that candle's prices next to
   * today's price and today's percentage, which is what made the LTP hard to
   * read. The live price and the day change belong in the watchlist row, where
   * they are always about now.
   *
   * Null when there is no earlier bar (the first bar of the loaded history), in
   * which case no change is shown at all rather than a change from zero.
   */
  prevClose: number | null
  /** Price formatter bound to the instrument tick. */
  fmt(value: number): string
  /** Compact volume formatter (e.g. 1.20M). */
  fmtVolume(value: number): string
}

/**
 * Build the readout: symbol, then its meta (interval, exchange, lot size), the
 * bar's O/H/L/C/V, and that bar's own change against the close before it.
 *
 * Everything here describes a single bar, so the whole line moves together as
 * the crosshair moves. Every section past the symbol and its meta is optional: a
 * freshly loaded chart has no crosshair bar, and the first bar of the loaded
 * history has nothing behind it to measure against.
 */
export function buildChartLegend(input: LegendInput): LegendRun[] {
  const runs: LegendRun[] = [{ text: input.symbol, tone: 'symbol' }]
  const lot = input.lotsize ? ` · lot ${input.lotsize}` : ''
  runs.push({ text: `· ${input.interval} · ${input.exchange}${lot}`, tone: 'meta' })

  const bar = input.bar
  if (bar) {
    let text =
      `O ${input.fmt(bar.open)} H ${input.fmt(bar.high)} ` +
      `L ${input.fmt(bar.low)} C ${input.fmt(bar.close)}`
    // Volume is absent on the transformed chart types (renko, point-and-figure),
    // whose elements are not one bar each, so it is shown only when it is real.
    if (typeof bar.volume === 'number' && Number.isFinite(bar.volume) && bar.volume > 0) {
      text += ` V ${input.fmtVolume(bar.volume)}`
    }
    runs.push({ text, tone: bar.close >= bar.open ? 'up' : 'down' })
  }

  // The bar's own change, against the close before it. Absolute first, percent
  // in parentheses, which is how a reader compares two instruments at a glance:
  // the points say how far it moved, the percent says how much that was.
  if (bar && input.prevClose != null && input.prevClose !== 0) {
    const change = bar.close - input.prevClose
    const pct = (change / input.prevClose) * 100
    const sign = change >= 0 ? '+' : '-'
    const mag = Math.abs(change)
    runs.push({
      text: `${sign}${input.fmt(mag)} (${sign}${Math.abs(pct).toFixed(2)}%)`,
      tone: change >= 0 ? 'up' : 'down',
    })
  }
  return runs
}

/** The second legend line: what one lot of quantity actually buys. */
export function lotInfoText(
  v: { lots: boolean; lotsize: number; freezeQty: number; quoteOnly: boolean } | null,
  qty: number
): string {
  if (!v) return ''
  if (v.lots) {
    const lots = Math.max(1, Math.floor(qty || 1))
    let t = `${lots} × ${v.lotsize} = ${lots * v.lotsize} qty`
    if (v.freezeQty > 1 && lots * v.lotsize > v.freezeQty) t += ` ⚠ freeze ${v.freezeQty}`
    return t
  }
  return v.quoteOnly ? 'quote-only (no trading)' : ''
}

const esc = (s: unknown) =>
  String(s).replace(
    /[&<>"]/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c] as string
  )

/** Inline style per tone for the DOM overlay; empty means inherit the theme. */
const HTML_TONE_STYLE: Record<LegendTone, string> = {
  symbol: '',
  meta: 'opacity:.55',
  up: `color:${UP}`,
  down: `color:${DN}`,
  ltp: `color:${LTP_NEUTRAL}`,
}

/** Render the runs as the DOM overlay's markup, space-separated. */
export function legendHtml(runs: readonly LegendRun[]): string {
  return runs
    .map((run) => {
      const style = HTML_TONE_STYLE[run.tone]
      const attr = style ? ` style="${style}"` : ''
      const tag = run.tone === 'symbol' ? 'b' : 'span'
      return `<${tag}${attr}>${esc(run.text)}</${tag}>`
    })
    .join(' ')
}

/**
 * Canvas paint attributes for a tone. `foreground` is the app's resolved text
 * colour, read off the live overlay element, so the export tracks the theme
 * exactly as the screen does; the dimmed meta mirrors the overlay's opacity.
 */
export function legendToneStyle(
  tone: LegendTone,
  foreground: string
): { color: string; alpha: number } {
  switch (tone) {
    case 'meta':
      return { color: foreground, alpha: 0.55 }
    case 'up':
      return { color: UP, alpha: 1 }
    case 'down':
      return { color: DN, alpha: 1 }
    case 'ltp':
      return { color: LTP_NEUTRAL, alpha: 1 }
    default:
      return { color: foreground, alpha: 1 }
  }
}
