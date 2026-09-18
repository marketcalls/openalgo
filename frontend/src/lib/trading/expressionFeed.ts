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
export function resolveLeg(leg: string, defaultExchange: string): { symbol: string; exchange: string } {
  const cut = leg.indexOf(':')
  return cut > 0
    ? { exchange: leg.slice(0, cut), symbol: leg.slice(cut + 1) }
    : { exchange: defaultExchange, symbol: leg }
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
    if (!isChartExpression(req.symbol)) return this.inner.getBars(req)
    const expr = parseExpression(req.symbol)
    const fallback = req.exchange || this.defaultExchange()
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
    return evaluateExpression(expr, legs)
  }

  /** A warm snapshot exists only for instruments; a combination is always folded fresh. */
  getCachedBars(req: BarsRequest): Promise<Bar[] | undefined> {
    if (isChartExpression(req.symbol) || !this.inner.getCachedBars) return Promise.resolve(undefined)
    return this.inner.getCachedBars(req)
  }
}
