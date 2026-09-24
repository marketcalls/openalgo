import { describe, expect, it } from 'vitest'
import type { Order, Position, Trade } from '@/types/trading'
import {
  type DockOrder,
  type DockPosition,
  type DockTrade,
  isWorking,
  num,
  parseOrder,
  parsePosition,
  parseTrade,
  realisedFromTrades,
  statusTone,
  sumOpenPnl,
} from './blotter'
import { formatTime, signed, signedQty } from './format'
import {
  applyOrderUpdate,
  frameMode,
  holdPushedStatus,
  type PushedStatus,
  RecentKeys,
  rememberPushed,
  updateKey,
} from './orderUpdates'

function order(over: Partial<DockOrder> = {}): DockOrder {
  return {
    orderid: '1',
    symbol: 'RELIANCE',
    exchange: 'NSE',
    action: 'BUY',
    product: 'MIS',
    pricetype: 'LIMIT',
    quantity: 10,
    price: 2500,
    trigger_price: 0,
    order_status: 'open',
    timestamp: '2026-09-04 09:30:00',
    ...over,
  }
}

function position(over: Partial<DockPosition> = {}): DockPosition {
  return {
    symbol: 'RELIANCE',
    exchange: 'NSE',
    product: 'MIS',
    quantity: 10,
    average_price: 2500,
    ltp: 2510,
    pnl: 100,
    ...over,
  }
}

function trade(over: Partial<DockTrade> = {}): DockTrade {
  return {
    orderid: '1',
    symbol: 'RELIANCE',
    exchange: 'NSE',
    action: 'BUY',
    product: 'MIS',
    quantity: 10,
    average_price: 2500,
    trade_value: 25000,
    timestamp: '',
    ...over,
  }
}

describe('num', () => {
  it('reads the strings positionbook sends, once, at the edge', () => {
    expect(num('2,510.50')).toBe(2510.5)
    expect(num('-75')).toBe(-75)
    expect(num(12)).toBe(12)
    expect(num('')).toBe(0)
    expect(num(undefined)).toBe(0)
    expect(num('abc')).toBe(0)
    expect(num(Number.NaN)).toBe(0)
  })
})

describe('parsing', () => {
  it('parses a position with every numeric as a string', () => {
    const raw = {
      symbol: 'VEDL25APR24292.5CE',
      exchange: 'NFO',
      product: 'nrml',
      quantity: '-1250',
      average_price: '12.35',
      ltp: '11.10',
      pnl: '1562.5',
    } as unknown as Position
    expect(parsePosition(raw)).toEqual({
      symbol: 'VEDL25APR24292.5CE',
      exchange: 'NFO',
      product: 'NRML',
      quantity: -1250,
      average_price: 12.35,
      ltp: 11.1,
      pnl: 1562.5,
    })
  })

  it('normalises the status and fills a completed order', () => {
    const raw = {
      orderid: 'A1',
      symbol: 'SBIN',
      exchange: 'NSE',
      action: 'SELL',
      product: 'MIS',
      pricetype: 'MARKET',
      quantity: '5',
      price: '0',
      trigger_price: '0',
      order_status: ' Complete ',
      timestamp: 't',
    } as unknown as Order
    const parsed = parseOrder(raw)
    expect(parsed.order_status).toBe('complete')
    expect(parsed.filled_quantity).toBe(5)
    // An open order says nothing about its fill until a frame does.
    expect(parseOrder({ ...raw, order_status: 'open' }).filled_quantity).toBeUndefined()
  })

  it('parses a trade', () => {
    const raw = {
      orderid: 'A1',
      symbol: 'SBIN',
      exchange: 'NSE',
      action: 'buy',
      product: 'CNC',
      quantity: '5',
      average_price: '800.5',
      trade_value: '4002.5',
      timestamp: 't',
    } as unknown as Trade
    expect(parseTrade(raw)).toMatchObject({ action: 'BUY', quantity: 5, trade_value: 4002.5 })
  })
})

describe('statusTone', () => {
  it('maps the known vocabulary', () => {
    expect(statusTone('open')).toBe('working')
    expect(statusTone('trigger pending')).toBe('working')
    expect(statusTone('Complete')).toBe('done')
    expect(statusTone('rejected')).toBe('failed')
    expect(statusTone('cancelled')).toBe('off')
    expect(statusTone('expired')).toBe('off')
  })

  it('keeps an unknown status rather than dropping it', () => {
    expect(statusTone('amo req received')).toBe('unknown')
    expect(statusTone('')).toBe('unknown')
  })

  it('offers cancel on working statuses only', () => {
    expect(isWorking('open')).toBe(true)
    expect(isWorking('trigger pending')).toBe(true)
    expect(isWorking('complete')).toBe(false)
    expect(isWorking('something new')).toBe(false)
  })
})

describe('order_update frames', () => {
  it('deduplicates on orderid, status and filled quantity', () => {
    const a = updateKey({ orderid: 1, order_status: 'Open', filled_quantity: '0' })
    const b = updateKey({ orderid: '1', order_status: 'open', filled_quantity: 0 })
    const c = updateKey({ orderid: '1', order_status: 'open', filled_quantity: 5 })
    expect(a).toBe(b)
    expect(a).not.toBe(c)
    const seen = new RecentKeys(2)
    expect(seen.add(a)).toBe(true)
    expect(seen.add(b)).toBe(false)
    expect(seen.add(c)).toBe(true)
    // Bounded: the oldest key is forgotten once the limit is passed.
    expect(seen.add('x')).toBe(true)
    expect(seen.add(a)).toBe(true)
  })

  it('names the mode the page uses', () => {
    expect(frameMode('live')).toBe('live')
    expect(frameMode('analyze')).toBe('analyzer')
    expect(frameMode(undefined)).toBeNull()
  })

  it('updates a known row in place and keeps its slot', () => {
    const book = [order({ orderid: '1' }), order({ orderid: '2' })]
    const next = applyOrderUpdate(book, {
      orderid: '2',
      order_status: 'complete',
      filled_quantity: 10,
      average_price: '2501.5',
    })
    expect(next.map((o) => o.orderid)).toEqual(['1', '2'])
    expect(next[1]).toMatchObject({
      order_status: 'complete',
      filled_quantity: 10,
      average_price: 2501.5,
      price: 2500,
    })
    expect(next[0]).toBe(book[0])
  })

  it('adds an unknown order at the top when the frame names the instrument', () => {
    const next = applyOrderUpdate([order({ orderid: '1' })], {
      orderid: '9',
      symbol: 'SBIN',
      exchange: 'NSE',
      action: 'sell',
      quantity: 3,
      pricetype: 'MARKET',
      product: 'MIS',
      order_status: 'rejected',
      rejection_reason: 'Insufficient funds',
    })
    expect(next[0]).toMatchObject({
      orderid: '9',
      symbol: 'SBIN',
      action: 'SELL',
      order_status: 'rejected',
      rejection_reason: 'Insufficient funds',
    })
    expect(next).toHaveLength(2)
  })

  it('ignores a frame with no order id or no instrument for an unknown one', () => {
    const book = [order()]
    expect(applyOrderUpdate(book, { order_status: 'open' })).toBe(book)
    expect(applyOrderUpdate(book, { orderid: '7', order_status: 'open' })).toBe(book)
  })

  it('takes a broker-side modify as a new frame, not a repeat of open', () => {
    // Changed in the broker's own app: the same status and fill come back
    // with a new price and quantity. Both frames must reach the row.
    const first = {
      orderid: 'X',
      order_status: 'open',
      filled_quantity: 0,
      price: 100,
      quantity: 10,
    }
    const second = { ...first, price: 101, quantity: 20 }
    expect(updateKey(first)).not.toBe(updateKey(second))
    const seen = new RecentKeys()
    expect(seen.add(updateKey(first))).toBe(true)
    expect(seen.add(updateKey(second))).toBe(true)
    let book = applyOrderUpdate([order({ orderid: 'X', price: 100, quantity: 10 })], first)
    book = applyOrderUpdate(book, second)
    expect(book[0]).toMatchObject({ price: 101, quantity: 20, order_status: 'open' })
  })

  it('carries a changed type, product and side onto a known row', () => {
    const next = applyOrderUpdate([order({ orderid: 'X', pricetype: 'LIMIT' })], {
      orderid: 'X',
      order_status: 'open',
      pricetype: 'market',
      product: 'nrml',
      action: 'sell',
    })
    expect(next[0]).toMatchObject({ pricetype: 'MARKET', product: 'NRML', action: 'SELL' })
  })
})

describe('a pushed status against a lagging fetch', () => {
  const now = 1_000_000

  function pushedComplete(): Map<string, PushedStatus> {
    const pushed = new Map<string, PushedStatus>()
    rememberPushed(
      pushed,
      { orderid: '1', order_status: 'complete', filled_quantity: 10, average_price: '2501.5' },
      now
    )
    return pushed
  }

  it('keeps the fill the broker pushed when the refetch still says open', () => {
    const held = holdPushedStatus([order({ order_status: 'open' })], pushedComplete(), now + 500)
    expect(held[0]).toMatchObject({
      order_status: 'complete',
      filled_quantity: 10,
      average_price: 2501.5,
    })
  })

  it('takes the fetch once it has caught up or says something new', () => {
    const pushed = pushedComplete()
    expect(
      holdPushedStatus([order({ order_status: 'complete' })], pushed, now + 500)[0]
    ).toMatchObject({ order_status: 'complete' })
    expect(
      holdPushedStatus([order({ order_status: 'cancelled' })], pushed, now + 500)[0]
    ).toMatchObject({ order_status: 'cancelled' })
  })

  it('never lets a pushed working status outrank the fetch', () => {
    const pushed = new Map<string, PushedStatus>()
    rememberPushed(pushed, { orderid: '1', order_status: 'open' }, now)
    const rows = [order({ order_status: 'complete' })]
    expect(holdPushedStatus(rows, pushed, now + 10)[0].order_status).toBe('complete')
  })

  it('forgets a frame once the hold has passed', () => {
    const pushed = pushedComplete()
    const rows = [order({ order_status: 'open' })]
    expect(holdPushedStatus(rows, pushed, now + 6000, 5000)[0].order_status).toBe('open')
    expect(pushed.size).toBe(0)
  })
})

describe('sums', () => {
  it('sums open P&L and counts the rows either side of zero', () => {
    const sum = sumOpenPnl([
      position({ pnl: 100 }),
      position({ symbol: 'SBIN', quantity: -5, pnl: -30.5 }),
      position({ symbol: 'TCS', quantity: 0, pnl: 999 }),
    ])
    expect(sum).toEqual({ pnl: 69.5, open: 2, closed: 1 })
  })

  it('derives realised P&L from matched round trips only', () => {
    const trades = [
      trade({ action: 'BUY', quantity: 10, average_price: 100 }),
      trade({ action: 'SELL', quantity: 4, average_price: 110 }),
      // A leg with only a buy today has no round trip to price.
      trade({ symbol: 'TCS', action: 'BUY', quantity: 1, average_price: 3000 }),
      // A different product in the same contract is a different leg.
      trade({ product: 'NRML', action: 'SELL', quantity: 10, average_price: 50 }),
    ]
    expect(realisedFromTrades(trades)).toBe(40)
  })

  it('has no realised figure when nothing was round-tripped', () => {
    expect(realisedFromTrades([trade()])).toBeNull()
    expect(realisedFromTrades([])).toBeNull()
  })

  it('matches fills oldest first, so a re-entered leg prices its round trip', () => {
    // Buy 100 at 10, sell 50 at 12, buy 50 at 11: the statement says 100.
    // Two day-long averages said 83.33.
    const trades = [
      trade({ action: 'BUY', quantity: 100, average_price: 10, timestamp: '09:15:00' }),
      trade({ action: 'SELL', quantity: 50, average_price: 12, timestamp: '09:20:00' }),
      trade({ action: 'BUY', quantity: 50, average_price: 11, timestamp: '09:25:00' }),
    ]
    expect(realisedFromTrades(trades)).toBe(100)
    // A book sent newest first is put back in fill order by its timestamps.
    expect(realisedFromTrades(trades.slice().reverse())).toBe(100)
  })

  it('prices a short the same way round', () => {
    const trades = [
      trade({ action: 'SELL', quantity: 10, average_price: 100, timestamp: '10:00:00' }),
      trade({ action: 'BUY', quantity: 10, average_price: 90, timestamp: '10:05:00' }),
    ]
    expect(realisedFromTrades(trades)).toBe(100)
  })
})

describe('formatting', () => {
  it('always prints the sign', () => {
    expect(signed(1234.5)).toBe('+1,234.50')
    expect(signed(-0.4)).toBe('-0.40')
    expect(signed(0)).toBe('0.00')
    expect(signedQty(1250)).toBe('+1,250')
    expect(signedQty(-75)).toBe('-75')
    expect(signedQty(0)).toBe('0')
  })

  it('finds the clock in the shapes brokers send', () => {
    expect(formatTime('09:15:07 04-09-2026')).toMatch(/09:15:07/)
    expect(formatTime('04-09-2026 15:29:59')).toMatch(/15:29:59/)
    expect(formatTime('2026-09-04T10:00:01')).toMatch(/10:00:01/)
    expect(formatTime('')).toBe('-')
    expect(formatTime('later')).toBe('later')
  })
})
