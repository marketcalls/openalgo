import { describe, expect, it } from 'vitest'
import { STRATEGY } from '@/lib/trading/terminal'
import type { DockOrder, DockPosition } from './blotter'
import {
  CHART_ORDER_STRATEGY,
  chartOrderRows,
  confirmationFor,
  halfQuantity,
  reverseTicket,
  stillHeld,
} from './chartOrderRows'

const SBIN = { symbol: 'SBIN', exchange: 'NSE', lots: false, lotsize: 1, freezeQty: 0 }
const NIFTY = {
  symbol: 'NIFTY30OCT26FUT',
  exchange: 'NFO',
  lots: true,
  lotsize: 65,
  freezeQty: 1755,
}

const pos = (over: Partial<DockPosition>): DockPosition => ({
  symbol: 'SBIN',
  exchange: 'NSE',
  product: 'MIS',
  quantity: 10,
  average_price: 800,
  ltp: 801,
  pnl: 10,
  ...over,
})
const ord = (over: Partial<DockOrder>): DockOrder => ({
  orderid: '1',
  symbol: 'SBIN',
  exchange: 'NSE',
  action: 'BUY',
  product: 'MIS',
  pricetype: 'LIMIT',
  quantity: 5,
  price: 790,
  trigger_price: 0,
  order_status: 'open',
  timestamp: '',
  ...over,
})

describe('chartOrderRows', () => {
  it('is null when flat with no working order, so the menu shows no order rows', () => {
    expect(chartOrderRows(SBIN, { orders: [], positions: [] })).toBeNull()
    expect(
      chartOrderRows(SBIN, {
        orders: [ord({ order_status: 'complete' }), ord({ order_status: 'rejected' })],
        positions: [pos({ quantity: 0 })],
      })
    ).toBeNull()
  })

  it('takes only this symbol on this exchange', () => {
    const rows = chartOrderRows(SBIN, {
      orders: [ord({}), ord({ exchange: 'BSE' }), ord({ symbol: 'INFY' })],
      positions: [pos({}), pos({ exchange: 'BSE' })],
    })
    expect(rows?.working).toHaveLength(1)
    expect(rows?.positions).toHaveLength(1)
  })

  it('closes a long by selling and a short by buying, the whole net quantity', () => {
    const long = chartOrderRows(SBIN, { orders: [], positions: [pos({ quantity: 10 })] })
    expect(long?.positions[0]).toMatchObject({ side: 'SELL', quantity: 10, half: 5 })
    const short = chartOrderRows(SBIN, { orders: [], positions: [pos({ quantity: -7 })] })
    expect(short?.positions[0]).toMatchObject({ side: 'BUY', quantity: 7, half: 3 })
  })

  it('halves in whole lots and refuses to halve a single lot or share', () => {
    expect(halfQuantity(260, 65)).toBe(130)
    expect(halfQuantity(195, 65)).toBe(65)
    expect(halfQuantity(65, 65)).toBe(0)
    expect(halfQuantity(1, 1)).toBe(0)
    const one = chartOrderRows(NIFTY, {
      orders: [],
      positions: [pos({ symbol: NIFTY.symbol, exchange: 'NFO', product: 'NRML', quantity: 65 })],
    })
    expect(one?.positions[0]).toMatchObject({ half: 0, halfReason: 'One lot cannot be halved' })
  })

  it('refuses a half above the freeze quantity rather than sending one the exchange rejects', () => {
    const rows = chartOrderRows(
      { ...NIFTY, freezeQty: 1000 },
      {
        orders: [],
        positions: [
          pos({ symbol: NIFTY.symbol, exchange: 'NFO', product: 'NRML', quantity: 2600 }),
        ],
      }
    )
    expect(rows?.positions[0].half).toBe(0)
    expect(rows?.positions[0].halfReason).toContain('freeze limit of 1000')
  })

  it('never reverses delivery, and names the product when there are two positions', () => {
    const rows = chartOrderRows(SBIN, {
      orders: [],
      positions: [pos({ product: 'CNC' }), pos({ product: 'MIS', quantity: -4 })],
    })
    expect(rows?.positions.map((r) => r.suffix)).toEqual(['CNC', 'MIS'])
    expect(rows?.positions[0].reverseReason).toBeDefined()
    expect(rows?.positions[1].reverseReason).toBeUndefined()
  })
})

describe('confirmationFor', () => {
  const rows = chartOrderRows(NIFTY, {
    orders: [],
    positions: [pos({ symbol: NIFTY.symbol, exchange: 'NFO', product: 'NRML', quantity: -260 })],
  })
  const row = rows?.positions[0]
  if (!row) throw new Error('fixture')

  it('names symbol, side, quantity and product for each action', () => {
    const close = confirmationFor({ kind: 'close', row, lotSize: 65 }, 'live')
    expect(close.body[0]).toContain(`BUY 260 (4 lots) ${NIFTY.symbol} on NFO, product NRML`)
    const half = confirmationFor({ kind: 'half', row, lotSize: 65 }, 'live')
    expect(half.body[0]).toContain('BUY 130 (2 lots)')
    expect(half.body[0]).toContain('130 (2 lots) of the 260 (4 lots) stay open')
    const reverse = confirmationFor({ kind: 'reverse', row, lotSize: 65 }, 'live')
    expect(reverse.body.join(' ')).toContain('BUY 260 (4 lots) NRML at market')
    expect(reverse.body.join(' ')).toContain('not entered until you place that order yourself')
  })

  it('says sandbox in analyzer mode and never paper', () => {
    const text = confirmationFor({ kind: 'close', row, lotSize: 65 }, 'analyzer').body.join(' ')
    expect(text).toContain('sandbox')
    expect(text.toLowerCase()).not.toContain('paper')
  })

  it('lists each order a cancel would cancel', () => {
    const text = confirmationFor(
      {
        kind: 'cancel',
        symbol: 'SBIN',
        exchange: 'NSE',
        orders: [ord({}), ord({ action: 'SELL', pricetype: 'SL-M', trigger_price: 780 })],
      },
      'live'
    )
    expect(text.title).toBe('Cancel 2 orders on SBIN?')
    expect(text.body).toContain('BUY 5 LIMIT at 790, MIS')
    expect(text.body).toContain('SELL 5 SL-M trigger 780, MIS')
  })
})

describe('the reverse ticket and the freshness check', () => {
  it('fills the opposite side at market with the chart strategy tag', () => {
    const row = chartOrderRows(SBIN, { orders: [], positions: [pos({ quantity: 10 })] })
      ?.positions[0]
    if (!row) throw new Error('fixture')
    expect(reverseTicket(row, 0.05, 1)).toEqual({
      symbol: 'SBIN',
      exchange: 'NSE',
      action: 'SELL',
      quantity: 10,
      lotSize: 1,
      tickSize: 0.05,
      product: 'MIS',
      priceType: 'MARKET',
      strategy: CHART_ORDER_STRATEGY,
    })
    expect(CHART_ORDER_STRATEGY).toBe(STRATEGY)
  })

  it('holds only while the server reports the same net quantity', () => {
    const p = pos({ quantity: 10 })
    expect(stillHeld(p, [pos({ quantity: 10 })])).toBe(true)
    expect(stillHeld(p, [pos({ quantity: 5 })])).toBe(false)
    expect(stillHeld(p, [pos({ quantity: 10, product: 'CNC' })])).toBe(false)
    expect(stillHeld(p, [])).toBe(false)
  })
})
