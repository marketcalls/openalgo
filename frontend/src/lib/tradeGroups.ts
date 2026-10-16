/**
 * Group tradebook fills by the order they belong to (fork-only, see
 * SKYSHIELD_PATCHES.md).
 *
 * One order is filled by the exchange in many pieces and the broker returns
 * every piece as its own trade with its own trade id. The Tradebook shows
 * them as returned; this folds them into one row per order for reading and
 * tagging, with the individual fills kept so the row can be expanded.
 */
import type { Trade } from '@/types/trading'

export interface OrderGroup {
  /** Stable React key: the order id, or the row's own identity when it has none. */
  key: string
  /** The merged row. For a single fill this is the fill itself. */
  trade: Trade
  /** Every fill folded into `trade`, in the order they were passed in. */
  fills: Trade[]
  /** Some fills carry a strategy tag and some do not. */
  partiallyTagged: boolean
}

export const MIXED_STRATEGY = 'Mixed'

function groupKey(trade: Trade): string | null {
  if (!trade.orderid) return null
  return [trade.orderid, trade.exchange, trade.symbol, trade.action].join('|')
}

function merge(fills: Trade[]): { trade: Trade; partiallyTagged: boolean } {
  const first = fills[0]
  if (fills.length === 1) {
    return { trade: first, partiallyTagged: false }
  }

  const quantity = fills.reduce((sum, f) => sum + f.quantity, 0)
  const value = fills.reduce((sum, f) => sum + (f.trade_value ?? f.average_price * f.quantity), 0)

  const tagged = fills.map((f) => f.strategy).filter((s): s is string => !!s)
  const distinct = new Set(tagged)
  let strategy: string | undefined
  if (distinct.size === 1) strategy = tagged[0]
  else if (distinct.size > 1) strategy = MIXED_STRATEGY

  return {
    trade: {
      ...first,
      quantity,
      trade_value: value,
      average_price: quantity > 0 ? value / quantity : first.average_price,
      tradeid: undefined,
      strategy,
    },
    partiallyTagged: tagged.length > 0 && tagged.length < fills.length,
  }
}

/**
 * Fold fills of the same order (and symbol, exchange, action) into one row.
 * Order is the order of first appearance, so a list sorted by time stays
 * sorted. A fill without an order id is never merged with another.
 */
export function groupTradesByOrder(trades: Trade[]): OrderGroup[] {
  const buckets = new Map<string, Trade[]>()
  const order: string[] = []

  trades.forEach((trade, index) => {
    const key = groupKey(trade) ?? `single|${trade.id ?? ''}|${trade.tradeid ?? ''}|${index}`
    const bucket = buckets.get(key)
    if (bucket) {
      bucket.push(trade)
    } else {
      buckets.set(key, [trade])
      order.push(key)
    }
  })

  return order.map((key) => {
    const fills = buckets.get(key) as Trade[]
    const { trade, partiallyTagged } = merge(fills)
    return { key, trade, fills, partiallyTagged }
  })
}

/** One group per fill: the unmerged view, in the same shape as the grouped one. */
export function ungrouped(trades: Trade[]): OrderGroup[] {
  return trades.map((trade, index) => ({
    key: `${trade.orderid}-${trade.tradeid ?? ''}-${index}`,
    trade,
    fills: [trade],
    partiallyTagged: false,
  }))
}
