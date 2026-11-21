import { describe, expect, it } from 'vitest'
import type { Position, Trade } from '@/types/trading'
import { buildPositionRows, openTradePnl } from './scalpingRows'

const CE = 'NIFTY16JUN2623600CE'
const PE = 'NIFTY16JUN2623600PE'

const pos = (o: Partial<Position>): Position => ({
  symbol: CE,
  exchange: 'NFO',
  product: 'NRML',
  quantity: 0,
  average_price: 0,
  ltp: 0,
  pnl: 0,
  pnlpercent: 0,
  ...o,
})

const trade = (o: Partial<Trade>): Trade =>
  ({
    symbol: CE,
    exchange: 'NFO',
    product: 'NRML',
    action: 'BUY',
    quantity: 0,
    average_price: 0,
    trade_value: 0,
    orderid: 'o1',
    timestamp: '2026-06-14 10:00:00',
    ...o,
  }) as Trade

describe('openTradePnl (#2285)', () => {
  it('is null when the book is flat, even with realized P&L from closed trades', () => {
    expect(openTradePnl([])).toBeNull()
    const trades = [
      trade({ action: 'BUY', quantity: 75, average_price: 100 }),
      trade({ action: 'SELL', quantity: 75, average_price: 110 }),
    ]
    const rows = buildPositionRows([], trades, {})
    expect(rows[0].realizedPnl).toBe(750)
    expect(openTradePnl(rows)).toBeNull()
  })

  it('is the open leg unrealized P&L only, leaving out a closed strike', () => {
    const trades = [
      // PE: bought and sold today, closed with +750 realized.
      trade({ symbol: PE, action: 'BUY', quantity: 75, average_price: 100 }),
      trade({ symbol: PE, action: 'SELL', quantity: 75, average_price: 110 }),
      // CE: bought today, still open.
      trade({ action: 'BUY', quantity: 75, average_price: 200 }),
    ]
    const positions = [pos({ quantity: 75, average_price: 200, ltp: 196 })]
    const rows = buildPositionRows(positions, trades, {})
    expect(rows.reduce((a, r) => a + r.totalPnl, 0)).toBe(750 - 300) // MTM
    expect(openTradePnl(rows)).toBe(-300) // (196 - 200) x 75
  })

  it('leaves out the realized part of a partially exited open leg', () => {
    const trades = [
      trade({ action: 'BUY', quantity: 150, average_price: 100 }),
      trade({ action: 'SELL', quantity: 75, average_price: 120 }),
    ]
    const positions = [pos({ quantity: 75, average_price: 100, ltp: 104 })]
    const rows = buildPositionRows(positions, trades, {})
    expect(rows[0].realizedPnl).toBe(1500)
    expect(openTradePnl(rows)).toBe(300) // (104 - 100) x 75
  })

  it('sums every open leg, long and short, at the live LTP', () => {
    const positions = [
      pos({ quantity: 75, average_price: 200, ltp: 190 }),
      pos({ symbol: PE, quantity: -75, average_price: 150, ltp: 150 }),
    ]
    const live: Record<string, number> = { [CE]: 210, [PE]: 140 }
    const rows = buildPositionRows(positions, [], {}, (s) => live[s])
    // CE long (210 - 200) x 75 = 750, PE short (150 - 140) x 75 = 750
    expect(openTradePnl(rows)).toBe(1500)
  })

  it('reads 0, not null, for an open trade at break-even', () => {
    const rows = buildPositionRows([pos({ quantity: 75, average_price: 200, ltp: 200 })], [], {})
    expect(openTradePnl(rows)).toBe(0)
  })
})
