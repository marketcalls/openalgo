/**
 * Links into the /trading terminal for one instrument.
 *
 * The order book, trade book and positions pages show symbols a trader wants
 * to look at on a chart. They link to `/trading?symbol=...&exchange=...`, and
 * the terminal loads that instrument into its focused pane once the page is
 * up, then drops the parameters so a refresh does not undo a later change.
 */
import type { SearchRow } from './terminal'

const SYMBOL = 'symbol'
const EXCHANGE = 'exchange'

/** The path that opens `symbol` on `exchange` in the chart terminal. */
export function chartHref(symbol: string, exchange: string): string {
  const params = new URLSearchParams({ [SYMBOL]: symbol, [EXCHANGE]: exchange })
  return `/trading?${params.toString()}`
}

/**
 * The instrument a link asked for, or null when it asked for none.
 *
 * Both parts are required: a symbol without its exchange names more than one
 * instrument, and guessing one would chart the wrong thing.
 */
export function readChartRequest(params: URLSearchParams): SearchRow | null {
  const symbol = params.get(SYMBOL)?.trim() ?? ''
  const exchange = params.get(EXCHANGE)?.trim().toUpperCase() ?? ''
  if (!symbol || !exchange) return null
  return { symbol, exchange }
}

/** Whether the URL carries either part of a chart request. */
export function hasChartRequest(params: URLSearchParams): boolean {
  return params.has(SYMBOL) || params.has(EXCHANGE)
}

/** The same parameters without the chart request, for replacing the URL. */
export function withoutChartRequest(params: URLSearchParams): URLSearchParams {
  const next = new URLSearchParams(params)
  next.delete(SYMBOL)
  next.delete(EXCHANGE)
  return next
}
