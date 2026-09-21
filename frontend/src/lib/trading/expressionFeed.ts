import type { Bar, BarsRequest, DataFeed } from 'openalgo-charts'
import { evaluateExpression, isPlainSymbol, parseExpression } from 'openalgo-charts/transform'

/**
 * Is this search text arithmetic rather than one instrument?
 *
 * A parse failure answers no: a half-typed `NIFTY/` arrives on every
 * keystroke, and the ordinary symbol path already knows how to say that a
 * symbol is unknown.
 */
export function isChartExpression(text: string): boolean {
  const s = (text || '').trim()
  if (s === '' || isPlainSymbol(s)) return false
  try {
    parseExpression(s)
    return true
  } catch {
    return false
  }
}

/**
 * `NSE:RELIANCE` names its exchange; a bare leg inherits the pane's, which is
 * what a trader typing `NIFTY/RELIANCE` means.
 */
export function resolveLeg(
  leg: string,
  defaultExchange: string
): { symbol: string; exchange: string } {
  const cut = leg.indexOf(':')
  return cut > 0
    ? { exchange: leg.slice(0, cut), symbol: leg.slice(cut + 1) }
    : { exchange: defaultExchange, symbol: leg }
}

/**
 * Is this request for a computed chart, rather than for one instrument?
 *
 * **An exchange is what settles it, not the name.** Reading the symbol alone
 * cannot tell `BAJAJ-AUTO` from a subtraction, because to the grammar that is
 * exactly what it is: `isPlainSymbol` says no and `parseExpression` succeeds.
 * Every load goes through this feed, so a name with a hyphen in it was folded
 * as `BAJAJ` minus `AUTO` and fetched as two instruments that do not exist.
 * The symbol search resolved the instrument correctly, the terminal passed it
 * down correctly, and it was taken apart here, one layer below both.
 *
 * A computed chart carries no exchange and never can: it is several
 * instruments, possibly on different venues, which is why its legs resolve
 * against a default. One instrument always carries its own. So the request
 * already knows the answer, and nothing has to guess at the name.
 */
function isComputed(req: BarsRequest): boolean {
  if (req.exchange) return false
  return isChartExpression(req.symbol)
}

/**
 * A history feed that also answers for an expression symbol.
 *
 * `NIFTY22SEP2623200CE+NIFTY22SEP2623200PE` is not an instrument the history
 * API knows, so a request for it fetches every leg through the inner feed (the
 * warm cache in front of REST) and folds them with `evaluateExpression`. The
 * loading controller only ever sees a DataFeed, so everything it does for a
 * plain symbol, the warm load, the repair after each bar closes, the gap
 * repair and paging, works for a combination unchanged. The legs of the most
 * recent fold are kept so the live path can start with one price per leg.
 */
export class ExpressionFeed implements DataFeed {
  /** Bars per leg from the most recent fold, keyed as the expression names them. */
  legBars: Record<string, readonly Bar[]> = {}
  private readonly inner: DataFeed
  private readonly defaultExchange: () => string

  constructor(inner: DataFeed, defaultExchange: () => string) {
    this.inner = inner
    this.defaultExchange = defaultExchange
  }

  async getBars(req: BarsRequest): Promise<Bar[]> {
    if (!isComputed(req)) return this.inner.getBars(req)
    const expr = parseExpression(req.symbol)
    // The pane's exchange. A folded request carries none of its own, by the
    // rule above, so this is the only source for a leg written without one.
    const fallback = this.defaultExchange()
    // The first failure wins: a combination missing a leg is not a chart with
    // a gap, it is no chart at all.
    const loaded = await Promise.all(
      expr.symbols.map(async (leg) => {
        const bars = await this.inner.getBars({ ...req, ...resolveLeg(leg, fallback) })
        if (!bars.length) throw new Error(`no bars for ${leg}`)
        return [leg, bars] as const
      })
    )
    const legs: Record<string, readonly Bar[]> = Object.fromEntries(loaded)
    this.legBars = legs
    // Combined leg activity uses each distinct leg once, independent of price
    // signs and coefficients. Price-only live quotes add no invented quantity.
    return evaluateExpression(expr, legs, { volume: 'sum' })
  }

  /** A warm snapshot exists only for instruments; a combination is always folded fresh. */
  getCachedBars(req: BarsRequest): Promise<Bar[] | undefined> {
    if (isComputed(req) || !this.inner.getCachedBars) return Promise.resolve(undefined)
    return this.inner.getCachedBars(req)
  }
}
