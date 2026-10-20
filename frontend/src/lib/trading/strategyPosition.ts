/**
 * What one running strategy is holding right now, read off the platform's own
 * position book.
 *
 * **Nothing here computes a position, and that is the point.** The strategy is
 * a process on the server; it sent orders, the broker or the sandbox filled
 * them, and the platform already folds those fills into a position with a
 * profit attached. This reads that answer. A panel that re-derived one from the
 * order list would be a second opinion about money, and the first time the two
 * disagreed the trader would have no way of telling which was right.
 *
 * **A broker's row is not one shape.** The same fact is spelled `quantity` by
 * one module and `netqty` by another, and the profit is `pnl` here and
 * `unrealised` there. Every field is therefore read through a list of names
 * rather than one, because a row read by the wrong name reports a flat position
 * on a strategy that is holding something, which is the single most expensive
 * thing this file could get wrong.
 *
 * **Direction comes from the sign of the size, because that is where a book
 * puts it.** A short is a negative quantity. The side is derived once, here,
 * and the size is then reported positive, so nothing downstream has to decide
 * whether a minus means direction or amount.
 */

/** One row of a position book, as much of it as this reads. */
export type PositionRow = Record<string, unknown>

/** What a strategy is holding in one instrument. */
export interface StrategyPosition {
  symbol: string
  exchange: string
  /** `long`, `short`, or `flat` for a row that has been closed out. */
  side: 'long' | 'short' | 'flat'
  /** Always positive. The direction is in `side`. */
  quantity: number
  averagePrice: number | null
  /** Profit as the platform states it, which may be absent. */
  profit: number | null
}

/** Every open position, and the totals a panel shows beside them. */
export interface PositionSummary {
  positions: StrategyPosition[]
  /** Profit across the rows, or the envelope's own figure where it gave one. */
  profit: number | null
  /** True when the platform stated the total rather than this adding rows up. */
  profitIsPlatforms: boolean
}

const QUANTITY = ['quantity', 'netqty', 'net_quantity', 'netQty', 'qty']
const AVERAGE = ['average_price', 'avgprice', 'averagePrice', 'avg_price', 'buy_price']
const PROFIT = ['pnl', 'unrealised', 'unrealized_pnl', 'unrealisedpnl', 'profit', 'p_and_l']
const SYMBOL = ['symbol', 'tradingsymbol']
const EXCHANGE = ['exchange', 'brexchange']

function firstOf(row: PositionRow, names: readonly string[]): unknown {
  for (const name of names) {
    const held = row[name]
    if (held !== undefined && held !== null && held !== '') return held
  }
  return null
}

function numberOf(row: PositionRow, names: readonly string[]): number | null {
  const held = firstOf(row, names)
  if (held === null) return null
  const value = Number(held)
  return Number.isFinite(value) ? value : null
}

function textOf(row: PositionRow, names: readonly string[]): string {
  const held = firstOf(row, names)
  return held === null ? '' : String(held)
}

/**
 * The rows a positions answer carries, wherever the service put them.
 *
 * The three book services in this platform do not agree on the shape: one wraps
 * its rows in an object under a name, two answer the list itself. A reader that
 * knows one of those reports an empty book for the others, which on screen is a
 * strategy that is holding nothing.
 */
export function rowsOfPositions(data: unknown): PositionRow[] {
  const list = (value: unknown): PositionRow[] =>
    Array.isArray(value)
      ? value.filter((one): one is PositionRow => typeof one === 'object' && one !== null)
      : []

  if (Array.isArray(data)) return list(data)
  if (data !== null && typeof data === 'object') {
    for (const key of ['positions', 'positionbook', 'net', 'data']) {
      const found = list((data as Record<string, unknown>)[key])
      if (found.length > 0) return found
    }
  }
  return []
}

/** One row, read into the shape a panel shows. */
export function positionFrom(row: PositionRow): StrategyPosition {
  const size = numberOf(row, QUANTITY) ?? 0
  return {
    symbol: textOf(row, SYMBOL),
    exchange: textOf(row, EXCHANGE),
    side: size > 0 ? 'long' : size < 0 ? 'short' : 'flat',
    quantity: Math.abs(size),
    averagePrice: numberOf(row, AVERAGE),
    profit: numberOf(row, PROFIT),
  }
}

/**
 * What a strategy is holding, from the whole answer the route gave.
 *
 * **A closed-out row is dropped from the list and kept in the profit.** A book
 * keeps a row at zero quantity after a position is squared off, carrying the
 * profit it made. Showing it as a position would say the strategy is in
 * something it is not; dropping its profit would say the day was flat. So the
 * rows shown are the ones still held, and the total still counts everything.
 *
 * **The platform's own total wins where it gave one.** It knows about realised
 * profit on rows that have since closed, which adding up what is on screen
 * cannot see. `profitIsPlatforms` says which of the two a reader is looking at,
 * because a total that does not match the rows above it reads as an error
 * unless something says otherwise.
 */
export function summaryOf(answer: unknown): PositionSummary {
  const envelope = (answer !== null && typeof answer === 'object' ? answer : {}) as Record<
    string,
    unknown
  >
  const rows = rowsOfPositions(envelope.data).map(positionFrom)

  const stated = numberOf(envelope, ['total_pnl', 'total_pnl_today', 'total_unrealized_pnl'])
  const added = rows.reduce<number | null>(
    (sum, one) => (one.profit === null ? sum : (sum ?? 0) + one.profit),
    null
  )

  return {
    positions: rows.filter((one) => one.side !== 'flat'),
    profit: stated ?? added,
    profitIsPlatforms: stated !== null,
  }
}
