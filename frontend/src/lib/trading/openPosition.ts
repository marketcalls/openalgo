/**
 * The position a strategy is still holding at the end of a run, marked to the
 * live price.
 *
 * **A strategy applied to the chart does not trade, and this is what it shows
 * instead.** Applying a script draws its marks and its labels on the price and
 * sends nothing: trading is what adding it to strategy management is for. So
 * the question a trader has while looking at one is "where would I be right
 * now", and the honest answer is the position the run finished holding, valued
 * at what the instrument is trading at this second.
 *
 * **The open position is not derived here, it is read.** A report already
 * carries it: the trade it never closed, flagged `isOpen`, with the side, the
 * size, the entry and the excursions the engine measured bar by bar. Folding
 * the fills again to work out what is open would be a second opinion about what
 * the engine already decided, and the two would disagree the first time either
 * changed. All this does is find it and value it.
 *
 * **The valuation is the engine's arithmetic, not the platform's.** A holdings
 * page computes profit the way a broker states it, over a position a broker
 * holds. This is a position nobody holds. Its size is in the units the script
 * trades and its money is in the contract's own point value, which is what
 * every other figure in the report rests on, so valuing it any other way would
 * put a number beside the report that the report disagrees with.
 *
 * **It is marked live and says when it is not.** A price that has stopped
 * arriving still renders, because a stale number a reader knows is stale is
 * more use than a blank; what it must never do is look current. The freshness
 * comes back with the answer so the panel can say so.
 */

/** One trade of the report's `trades` channel, as much as this reads. */
export interface ReportTrade {
  index?: unknown
  side?: unknown
  units?: unknown
  entryPrice?: unknown
  openedAt?: unknown
  openedOnBar?: unknown
  barsHeld?: unknown
  maxFavourable?: unknown
  maxAdverse?: unknown
  isOpen?: unknown
}

/** What the strategy is holding, valued at a price. */
export interface OpenPosition {
  /** `long` or `short`, as the engine states it. */
  side: 'long' | 'short'
  /** Always positive. The direction lives in `side`, never in the sign. */
  units: number
  entryPrice: number
  /** When the position was opened, in milliseconds. */
  openedAt: number | null
  /** Bars held as at the last bar of the run. */
  barsHeld: number | null
  /** The best and worst it has been, in money, as the engine measured it. */
  maxFavourable: number | null
  maxAdverse: number | null
}

/** A position valued at a price, which is the thing a trader reads. */
export interface MarkedPosition extends OpenPosition {
  /** The price it was valued at, and where that price came from. */
  price: number
  /** Profit in money, signed: positive is in the trader's favour. */
  profit: number
  /** The same as a percentage of what the position cost. */
  profitPercent: number | null
}

function finite(value: unknown): number | null {
  if (value === null || value === undefined || value === '') return null
  const asNumber = Number(value)
  return Number.isFinite(asNumber) ? asNumber : null
}

/**
 * The position a report finished holding, or nothing.
 *
 * Nothing is the ordinary answer: most runs end flat, and a panel that showed
 * an empty position row would be claiming a position exists.
 *
 * A report may hold more than one open trade where the strategy pyramided. The
 * earliest is answered, because it is the one whose entry a trader is watching,
 * and the count is separate so a panel can say there are others rather than
 * silently showing one of several.
 */
export function openPositionOf(trades: readonly ReportTrade[] | undefined): OpenPosition | null {
  for (const trade of trades ?? []) {
    if (trade.isOpen !== true) continue

    const units = finite(trade.units)
    const entryPrice = finite(trade.entryPrice)
    // A position with no size or no entry is not a position anybody can read,
    // and showing it valued at zero would be worse than not showing it.
    if (units === null || units <= 0 || entryPrice === null) continue

    return {
      side: trade.side === 'short' ? 'short' : 'long',
      units,
      entryPrice,
      openedAt: finite(trade.openedAt),
      barsHeld: finite(trade.barsHeld),
      maxFavourable: finite(trade.maxFavourable),
      maxAdverse: finite(trade.maxAdverse),
    }
  }
  return null
}

/** How many trades a report finished holding, which may be more than one. */
export function openCountOf(trades: readonly ReportTrade[] | undefined): number {
  let count = 0
  for (const trade of trades ?? []) if (trade.isOpen === true) count += 1
  return count
}

/**
 * A position valued at a price.
 *
 * `pointValue` is what one point of price movement is worth per unit, which is
 * the contract's own and is 1 for cash equity. It is taken as an argument rather
 * than assumed, because assuming 1 on a contract where it is 50 reports a
 * fiftieth of the real exposure and reads perfectly while doing it.
 */
export function markToPrice(
  position: OpenPosition,
  price: number,
  pointValue = 1
): MarkedPosition | null {
  if (!Number.isFinite(price) || !Number.isFinite(pointValue)) return null

  const move = position.side === 'short' ? position.entryPrice - price : price - position.entryPrice
  const profit = move * position.units * pointValue
  const cost = position.entryPrice * position.units * pointValue

  return {
    ...position,
    price,
    profit,
    // Guarded because an entry at zero is a real price in some instruments and
    // dividing by it would put Infinity in front of a trader.
    profitPercent: cost > 0 ? (profit / cost) * 100 : null,
  }
}
