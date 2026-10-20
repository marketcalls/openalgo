/**
 * The dock's pure half: what a broker row becomes once it is in the page,
 * how a live order frame is folded into the book, and the two sums the
 * header strip shows.
 *
 * Every number the books carry arrives as a string from some broker and as
 * a number from another, so parsing happens here, once, at the edge. Past
 * this file a quantity is a number.
 */

import type { Order, Position, Trade } from '@/types/trading'
import { timeKey } from './format'

export interface DockOrder {
  orderid: string
  symbol: string
  exchange: string
  action: string
  product: string
  pricetype: string
  quantity: number
  price: number
  trigger_price: number
  /** Lowercased and trimmed; the vocabulary is open-ended, see statusTone. */
  order_status: string
  timestamp: string
  /** Known only once a live frame has said so, or once the order completed. */
  filled_quantity?: number
  average_price?: number
  rejection_reason?: string
}

export interface DockPosition {
  symbol: string
  exchange: string
  product: string
  quantity: number
  average_price: number
  ltp: number
  pnl: number
  pnlpercent?: number
  lot_size?: number
  today_realized_pnl?: number
}

export interface DockTrade {
  orderid: string
  symbol: string
  exchange: string
  action: string
  product: string
  quantity: number
  average_price: number
  trade_value: number
  timestamp: string
}

/** A number from whatever the broker sent; anything unreadable is 0. */
export function num(value: unknown): number {
  if (typeof value === 'number') return Number.isFinite(value) ? value : 0
  if (typeof value === 'string') {
    const parsed = Number(value.replace(/,/g, ''))
    return Number.isFinite(parsed) ? parsed : 0
  }
  return 0
}

export function text(value: unknown): string {
  return value === null || value === undefined ? '' : String(value)
}

export function normaliseStatus(status: unknown): string {
  return text(status).trim().toLowerCase()
}

export function parseOrder(raw: Order): DockOrder {
  const status = normaliseStatus(raw.order_status)
  const quantity = num(raw.quantity)
  const withFill = raw as Order & { filled_quantity?: unknown; average_price?: unknown }
  const order: DockOrder = {
    orderid: text(raw.orderid),
    symbol: text(raw.symbol),
    exchange: text(raw.exchange),
    action: text(raw.action).toUpperCase(),
    product: text(raw.product).toUpperCase(),
    pricetype: text(raw.pricetype).toUpperCase(),
    quantity,
    price: num(raw.price),
    trigger_price: num(raw.trigger_price),
    order_status: status,
    timestamp: text(raw.timestamp),
  }
  if (withFill.filled_quantity !== undefined) order.filled_quantity = num(withFill.filled_quantity)
  else if (statusTone(status) === 'done') order.filled_quantity = quantity
  if (withFill.average_price !== undefined) order.average_price = num(withFill.average_price)
  return order
}

export function parsePosition(raw: Position): DockPosition {
  const position: DockPosition = {
    symbol: text(raw.symbol),
    exchange: text(raw.exchange),
    product: text(raw.product).toUpperCase(),
    quantity: num(raw.quantity),
    average_price: num(raw.average_price),
    ltp: num(raw.ltp),
    pnl: num(raw.pnl),
  }
  if (raw.pnlpercent !== undefined && raw.pnlpercent !== null) {
    position.pnlpercent = num(raw.pnlpercent)
  }
  if (raw.lot_size !== undefined && raw.lot_size !== null) position.lot_size = num(raw.lot_size)
  if (raw.today_realized_pnl !== undefined && raw.today_realized_pnl !== null) {
    position.today_realized_pnl = num(raw.today_realized_pnl)
  }
  return position
}

export function parseTrade(raw: Trade): DockTrade {
  return {
    orderid: text(raw.orderid),
    symbol: text(raw.symbol),
    exchange: text(raw.exchange),
    action: text(raw.action).toUpperCase(),
    product: text(raw.product).toUpperCase(),
    quantity: num(raw.quantity),
    average_price: num(raw.average_price),
    trade_value: num(raw.trade_value),
    timestamp: text(raw.timestamp),
  }
}

/** A position row's identity: an MIS and an NRML in one contract are two rows. */
export function positionKey(p: { symbol: string; exchange: string; product: string }): string {
  return `${p.exchange}:${p.symbol}:${p.product}`
}

/* status */

/**
 * How a status reads, not what it is. The vocabulary is the broker's and it
 * is open-ended (open, trigger pending, complete, rejected, cancelled, plus
 * extras such as expired), so anything unrecognised keeps its own words and
 * takes the neutral tone rather than being dropped.
 */
export type StatusTone = 'working' | 'done' | 'failed' | 'off' | 'unknown'

export function statusTone(status: string): StatusTone {
  const s = normaliseStatus(status)
  if (s === 'complete' || s === 'completed' || s === 'filled' || s === 'executed') return 'done'
  if (s === 'rejected' || s === 'failed') return 'failed'
  if (s === 'cancelled' || s === 'canceled' || s === 'expired' || s === 'lapsed') return 'off'
  if (
    s === 'open' ||
    s === 'pending' ||
    s === 'trigger pending' ||
    s === 'validation pending' ||
    s === 'open pending' ||
    s === 'modify pending' ||
    s === 'cancel pending' ||
    s === 'put order req received' ||
    s === 'modify validation pending' ||
    s.endsWith(' pending')
  ) {
    return 'working'
  }
  return 'unknown'
}

/** Cancel and modify are offered on these and nothing else. */
export function isWorking(status: string): boolean {
  return statusTone(status) === 'working'
}

/* sums */

export interface OpenPnl {
  pnl: number
  open: number
  closed: number
}

/** P&L across the rows that still hold a quantity, and how many rows do. */
export function sumOpenPnl(positions: readonly DockPosition[]): OpenPnl {
  let pnl = 0
  let open = 0
  let closed = 0
  for (const p of positions) {
    if (p.quantity === 0) {
      closed += 1
      continue
    }
    open += 1
    pnl += p.pnl
  }
  return { pnl, open, closed }
}

/**
 * The trade book in the order the fills happened. Sorted by the timestamp
 * when every row carries a readable one, else left as the broker sent it;
 * the sort is stable, so rows in the same second keep their book order.
 */
function inFillOrder(trades: readonly DockTrade[]): DockTrade[] {
  const keyed = trades.map((t) => ({ t, at: timeKey(t.timestamp) }))
  if (keyed.some((k) => k.at === null)) return trades.slice()
  return keyed.sort((a, b) => (a.at as number) - (b.at as number)).map((k) => k.t)
}

/**
 * Realised P&L the trade book can vouch for: for each instrument and product,
 * each fill matched against the oldest open fills on the other side, in the
 * order they happened, so a leg that is closed and re-entered prices its
 * round trip the way the broker's statement does. Two averages over the
 * whole day did not: buy 100 at 10, sell 50 at 12, buy 50 at 11 is 100
 * realised, and the averages said 83. A leg with only buys or only sells
 * today has no round trip to price, so it contributes nothing; if no leg has
 * one at all there is no figure, and the strip says so rather than printing 0.
 */
export function realisedFromTrades(trades: readonly DockTrade[]): number | null {
  const open = new Map<string, { side: string; qty: number; price: number }[]>()
  let realised = 0
  let derivable = false
  for (const t of inFillOrder(trades)) {
    if (t.action !== 'BUY' && t.action !== 'SELL') continue
    let qty = Math.abs(t.quantity)
    if (qty <= 0) continue
    const key = positionKey(t)
    const lots = open.get(key) ?? []
    while (qty > 0 && lots.length > 0 && lots[0].side !== t.action) {
      const lot = lots[0]
      const matched = Math.min(qty, lot.qty)
      const perUnit =
        t.action === 'SELL' ? t.average_price - lot.price : lot.price - t.average_price
      realised += matched * perUnit
      derivable = true
      lot.qty -= matched
      qty -= matched
      if (lot.qty <= 0) lots.shift()
    }
    if (qty > 0) lots.push({ side: t.action, qty, price: t.average_price })
    open.set(key, lots)
  }
  return derivable ? realised : null
}
