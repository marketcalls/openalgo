/**
 * The order rows the chart's right-click menu offers for the symbol on the
 * chart: cancel its working orders, and close, halve or reverse each open
 * position in it. Pure: the books come from the dock's cache and the menu
 * renders what this returns.
 *
 * Every row is an action on something that exists. With no working order
 * and no open position there is nothing to return and the menu shows none.
 *
 * What each row sends:
 *
 * - Cancel: the dock's own cancel, once per working order on the symbol.
 * - Close: the dock's own Close, the per-position square-off route.
 * - Close half: one market order on the closing side for half the net
 *   quantity, rounded down to whole lots, through the chart's order ticket
 *   path. A single lot, or a single share, cannot be halved, so the row is
 *   greyed with the reason.
 * - Reverse: never one order of twice the quantity. That order is sized from
 *   a book that can be a second old, and nothing on the way to the broker
 *   checks it against the position actually held, so a fill the books had
 *   not caught up with would turn into a position of the wrong size. The row
 *   closes through the dock's Close and then opens the order ticket filled in
 *   with the opposite side, for the trader to place. Delivery (CNC) is never
 *   reversed: the other side of a delivery position is a short delivery sale.
 */

import { type DockOrder, type DockPosition, isWorking } from './blotter'

export type OrderSide = 'BUY' | 'SELL'

export interface ChartInstrument {
  symbol: string
  exchange: string
  /** Quantity is entered in lots on this segment. */
  lots: boolean
  lotsize: number
  /** The exchange's freeze quantity; 0 or 1 when there is none. */
  freezeQty: number
}

export interface PositionRow {
  position: DockPosition
  /** The side that reduces this position. */
  side: OrderSide
  /** The whole net quantity, unsigned. */
  quantity: number
  /** Half the net quantity in whole lots, or 0 when it cannot be halved. */
  half: number
  /** Why Close half is greyed, when it is. */
  halfReason?: string
  /** Why Reverse is greyed, when it is. */
  reverseReason?: string
  /** The product named on the rows when the symbol has more than one position. */
  suffix: string
}

export interface ChartOrderRows {
  symbol: string
  exchange: string
  /** Working orders on the symbol, for "Cancel orders on SYMBOL (n)". */
  working: DockOrder[]
  positions: PositionRow[]
}

/** Lot size for a position row: the book's own when it has one, else the chart's. */
function lotOf(p: DockPosition, inst: ChartInstrument): number {
  if (!inst.lots) return 1
  const lot = p.lot_size && p.lot_size > 0 ? p.lot_size : inst.lotsize
  return lot > 0 ? lot : 1
}

/**
 * Half of `net`, rounded down to whole lots. 0 when one lot (or one share)
 * is all there is, which cannot be halved.
 */
export function halfQuantity(net: number, lotSize: number): number {
  const lot = lotSize > 0 ? lotSize : 1
  const lots = Math.floor(Math.abs(net) / lot)
  return Math.floor(lots / 2) * lot
}

/** Whether a row in the book is the instrument on the chart. */
function onChart(row: { symbol: string; exchange: string }, inst: ChartInstrument): boolean {
  return row.symbol === inst.symbol && row.exchange === inst.exchange
}

/**
 * The rows for `inst`, or null when it has no working order and no open
 * position: the menu then shows none.
 */
export function chartOrderRows(
  inst: ChartInstrument,
  book: { orders: readonly DockOrder[]; positions: readonly DockPosition[] }
): ChartOrderRows | null {
  const working = book.orders.filter((o) => onChart(o, inst) && isWorking(o.order_status))
  const open = book.positions.filter((p) => onChart(p, inst) && p.quantity !== 0)
  if (working.length === 0 && open.length === 0) return null
  const named = open.length > 1
  const positions = open.map((position): PositionRow => {
    const quantity = Math.abs(position.quantity)
    const lot = lotOf(position, inst)
    const half = halfQuantity(quantity, lot)
    const row: PositionRow = {
      position,
      side: position.quantity > 0 ? 'SELL' : 'BUY',
      quantity,
      half,
      suffix: named ? position.product : '',
    }
    if (half === 0) {
      row.halfReason = lot > 1 ? 'One lot cannot be halved' : 'One share cannot be halved'
    } else if (inst.freezeQty > 1 && half > inst.freezeQty) {
      row.half = 0
      row.halfReason = `Half is ${half}, above the freeze limit of ${inst.freezeQty}`
    }
    if (position.product === 'CNC') {
      row.reverseReason = 'A delivery (CNC) position is not reversed'
    }
    return row
  })
  return { symbol: inst.symbol, exchange: inst.exchange, working, positions }
}

/* ── the confirmation ──────────────────────────────────────────────────── */

export type ChartOrderAction =
  | { kind: 'cancel'; symbol: string; exchange: string; orders: DockOrder[] }
  | { kind: 'close' | 'half' | 'reverse'; row: PositionRow; lotSize: number }

export interface OrderConfirmation {
  title: string
  /** Each paragraph of the explanation, in order. */
  body: string[]
  /** The button that sends it. */
  confirm: string
  /** The button that sends nothing. */
  keep: string
}

/** "130 (2 lots)" on a lot segment, "10" otherwise. */
export function quantityText(quantity: number, lotSize: number): string {
  if (lotSize <= 1) return String(quantity)
  const lots = quantity / lotSize
  return `${quantity} (${lots} ${lots === 1 ? 'lot' : 'lots'})`
}

function orderText(o: DockOrder): string {
  const price =
    o.pricetype === 'MARKET'
      ? ''
      : o.pricetype === 'SL-M'
        ? ` trigger ${o.trigger_price}`
        : ` at ${o.price}`
  return `${o.action} ${o.quantity} ${o.pricetype}${price}, ${o.product}`
}

/**
 * Where an order goes, said in the platform's own words. Analyzer mode is
 * decided on the server; this only tells the trader which one it is.
 */
export function destinationText(appMode: 'live' | 'analyzer'): string {
  return appMode === 'analyzer'
    ? 'Analyzer mode is on: this goes to the sandbox, not to your broker.'
    : 'Live mode: this goes to your broker.'
}

/**
 * What the confirmation says before anything is sent. Every order it can
 * lead to is named by symbol, side, quantity and product.
 */
export function confirmationFor(
  action: ChartOrderAction,
  appMode: 'live' | 'analyzer'
): OrderConfirmation {
  const where = destinationText(appMode)
  if (action.kind === 'cancel') {
    const n = action.orders.length
    return {
      title: `Cancel ${n} ${n === 1 ? 'order' : 'orders'} on ${action.symbol}?`,
      body: [
        ...action.orders.map(orderText),
        `Open positions in ${action.symbol} are not touched.`,
        where,
      ],
      confirm: n === 1 ? 'Cancel order' : 'Cancel orders',
      keep: n === 1 ? 'Keep order' : 'Keep orders',
    }
  }
  const { row, lotSize } = action
  const p = row.position
  const held = quantityText(row.quantity, lotSize)
  const long = p.quantity > 0
  const what = long ? 'long' : 'short'
  if (action.kind === 'close') {
    return {
      title: `Close ${p.symbol} ${p.product} position?`,
      body: [
        `Places a market order to ${row.side} ${held} ${p.symbol} on ${p.exchange}, product ${p.product}. The whole ${what} ${p.product} position is squared off.`,
        where,
      ],
      confirm: 'Close position',
      keep: 'Keep position',
    }
  }
  if (action.kind === 'half') {
    const half = quantityText(row.half, lotSize)
    const left = quantityText(row.quantity - row.half, lotSize)
    return {
      title: `Close half of ${p.symbol} ${p.product}?`,
      body: [
        `Places a market order to ${row.side} ${half} ${p.symbol} on ${p.exchange}, product ${p.product}. ${left} of the ${held} stay open.`,
        where,
      ],
      confirm: 'Close half',
      keep: 'Keep position',
    }
  }
  const opposite = row.side
  return {
    title: `Reverse ${p.symbol} ${p.product} position?`,
    body: [
      `Step 1: places a market order to ${row.side} ${held} ${p.symbol} on ${p.exchange}, product ${p.product}, closing the ${what} position.`,
      `Step 2: the order ticket opens filled in with ${opposite} ${held} ${p.product} at market. The new ${long ? 'short' : 'long'} position is not entered until you place that order yourself.`,
      where,
    ],
    confirm: 'Close and open ticket',
    keep: 'Keep position',
  }
}

/* ── the reverse's second step ─────────────────────────────────────────── */

/** The chart's own order tag, the one its ticket and One-Click orders carry. */
export const CHART_ORDER_STRATEGY = 'chart-trading'

/**
 * The ticket Reverse opens once the close is sent: the opposite side, the
 * same quantity and product, at market. It is only a filled-in form; the
 * trader places it, changes it or closes it.
 */
export function reverseTicket(
  row: PositionRow,
  tickSize: number,
  lotSize: number
): {
  symbol: string
  exchange: string
  action: OrderSide
  quantity: number
  lotSize: number
  tickSize: number
  product: 'MIS' | 'NRML' | 'CNC'
  priceType: 'MARKET'
  strategy: string
} {
  const p = row.position
  return {
    symbol: p.symbol,
    exchange: p.exchange,
    action: row.side,
    quantity: row.quantity,
    lotSize: lotSize > 0 ? lotSize : 1,
    tickSize,
    product: p.product as 'MIS' | 'NRML' | 'CNC',
    priceType: 'MARKET',
    strategy: CHART_ORDER_STRATEGY,
  }
}

/**
 * Whether a position read fresh from the server is still the one a
 * confirmation was sized from. Close half sends a plain order of a fixed
 * quantity, so a position that moved since the menu opened (a fill, a close
 * from another screen) refuses it rather than sending the stale half.
 */
export function stillHeld(confirmed: DockPosition, fresh: readonly DockPosition[]): boolean {
  const now = fresh.find(
    (p) =>
      p.symbol === confirmed.symbol &&
      p.exchange === confirmed.exchange &&
      p.product === confirmed.product
  )
  return !!now && now.quantity === confirmed.quantity
}
