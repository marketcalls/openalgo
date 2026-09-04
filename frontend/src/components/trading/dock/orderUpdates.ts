/**
 * The SocketIO order_update feed, folded into the order book.
 *
 * socketio_subscriber.py emits one frame per asynchronous status change,
 * in both modes, and nothing else in the app consumed it. A fill or a
 * rejection lands on its row the moment the broker pushes it; the refetch
 * behind it confirms.
 */

import type { AppMode } from '@/stores/themeStore'
import { type DockOrder, normaliseStatus, num, statusTone, text } from './blotter'

/** The SocketIO order_update payload, as socketio_subscriber.py emits it. */
export interface OrderUpdateFrame {
  mode?: string
  broker?: string
  orderid?: string | number
  symbol?: string
  exchange?: string
  action?: string
  quantity?: unknown
  price?: unknown
  trigger_price?: unknown
  pricetype?: string
  product?: string
  order_status?: string
  filled_quantity?: unknown
  pending_quantity?: unknown
  average_price?: unknown
  rejection_reason?: string
}

/**
 * The identity a frame is deduplicated on: the same fill is reported once.
 * Status and fill alone are not enough. A modify made in the broker's own
 * app comes back as another 'open' with zero filled and a new price or
 * quantity, and a key that ignored those dropped it, so the row kept the
 * old price and a later Modify from the dock sent the old quantity back.
 */
export function updateKey(frame: OrderUpdateFrame): string {
  return [
    text(frame.orderid),
    normaliseStatus(frame.order_status),
    num(frame.filled_quantity),
    num(frame.quantity),
    num(frame.price),
    num(frame.trigger_price),
    text(frame.pricetype).toUpperCase(),
  ].join('|')
}

/** The page's name for the mode a frame was emitted in. */
export function frameMode(mode: string | undefined): AppMode | null {
  if (mode === 'live') return 'live'
  if (mode === 'analyze' || mode === 'analyzer') return 'analyzer'
  return null
}

/**
 * Fold a live frame into the order book. A known order is updated in place
 * and keeps its slot; an unknown one goes to the top, where the next refetch
 * will put it properly. Nothing here waits for that refetch: the status the
 * broker just pushed is the one on screen.
 */
export function applyOrderUpdate(orders: DockOrder[], frame: OrderUpdateFrame): DockOrder[] {
  const orderid = text(frame.orderid)
  if (!orderid) return orders
  const status = normaliseStatus(frame.order_status)
  const patch: Partial<DockOrder> = {}
  if (status) patch.order_status = status
  if (frame.filled_quantity !== undefined) patch.filled_quantity = num(frame.filled_quantity)
  if (frame.average_price !== undefined) patch.average_price = num(frame.average_price)
  if (frame.price !== undefined && num(frame.price) > 0) patch.price = num(frame.price)
  if (frame.trigger_price !== undefined && num(frame.trigger_price) > 0) {
    patch.trigger_price = num(frame.trigger_price)
  }
  if (frame.quantity !== undefined && num(frame.quantity) > 0) patch.quantity = num(frame.quantity)
  if (frame.rejection_reason) patch.rejection_reason = frame.rejection_reason
  // A modify can change the type as well as the figures (LIMIT to MARKET);
  // the Type cell must follow it, and so must the modify context sent back.
  if (frame.pricetype) patch.pricetype = text(frame.pricetype).toUpperCase()
  if (frame.product) patch.product = text(frame.product).toUpperCase()
  if (frame.action) patch.action = text(frame.action).toUpperCase()

  const index = orders.findIndex((o) => o.orderid === orderid)
  if (index >= 0) {
    const next = orders.slice()
    next[index] = { ...orders[index], ...patch }
    return next
  }
  // A frame for an order the book has not fetched yet. Only worth a row when
  // it names the instrument; a bare status for an unknown id has nothing to
  // show and the refetch behind it fills the gap.
  if (!frame.symbol || !frame.exchange) return orders
  const fresh: DockOrder = {
    orderid,
    symbol: frame.symbol,
    exchange: frame.exchange,
    action: text(frame.action).toUpperCase(),
    product: text(frame.product).toUpperCase(),
    pricetype: text(frame.pricetype).toUpperCase(),
    quantity: num(frame.quantity),
    price: num(frame.price),
    trigger_price: num(frame.trigger_price),
    order_status: status,
    timestamp: '',
    ...patch,
  }
  return [fresh, ...orders]
}

/**
 * How long a pushed terminal status outranks a fetched working one. The
 * postback publishes the moment the broker reports a fill, and the REST
 * order book behind the refetch can say 'open' for a second or more after
 * that; the broker never pushes the fill twice, so the refetch must not be
 * allowed to undo it.
 */
export const PUSHED_HOLD_MS = 5000

export interface PushedStatus {
  order_status: string
  filled_quantity?: number
  average_price?: number
  at: number
}

/** Note what a frame said about its order, for holdPushedStatus. */
export function rememberPushed(
  pushed: Map<string, PushedStatus>,
  frame: OrderUpdateFrame,
  now: number
): void {
  const orderid = text(frame.orderid)
  const status = normaliseStatus(frame.order_status)
  if (!orderid || !status) return
  const entry: PushedStatus = { order_status: status, at: now }
  if (frame.filled_quantity !== undefined) entry.filled_quantity = num(frame.filled_quantity)
  if (frame.average_price !== undefined) entry.average_price = num(frame.average_price)
  pushed.set(orderid, entry)
}

/**
 * A fetched book, with the rows a recent frame has already moved past kept
 * where the frame put them. Only a terminal status outranks the fetch, and
 * only over a fetched status that is still working: a fetch that has
 * caught up, or says something new, is taken as it is. Entries older than
 * the hold are dropped on the way through.
 */
export function holdPushedStatus(
  fetched: DockOrder[],
  pushed: Map<string, PushedStatus>,
  now: number,
  holdMs = PUSHED_HOLD_MS
): DockOrder[] {
  for (const [orderid, entry] of pushed) {
    if (now - entry.at > holdMs) pushed.delete(orderid)
  }
  if (pushed.size === 0) return fetched
  return fetched.map((row) => {
    const entry = pushed.get(row.orderid)
    if (!entry) return row
    if (statusTone(entry.order_status) === 'working') return row
    if (statusTone(row.order_status) !== 'working') return row
    const { at: _at, ...held } = entry
    return { ...row, ...held }
  })
}

/**
 * A bounded memory of frames already applied. Insertion-ordered, so once it
 * is full the oldest key goes first.
 */
export class RecentKeys {
  private readonly keys = new Set<string>()
  private readonly limit: number

  constructor(limit = 500) {
    this.limit = limit
  }

  /** True the first time a key is seen. */
  add(key: string): boolean {
    if (this.keys.has(key)) return false
    this.keys.add(key)
    if (this.keys.size > this.limit) {
      const oldest = this.keys.values().next().value
      if (oldest !== undefined) this.keys.delete(oldest)
    }
    return true
  }
}
