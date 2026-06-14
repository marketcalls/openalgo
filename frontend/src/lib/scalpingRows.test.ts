import { describe, expect, it } from 'vitest'
import type { Position, Trade } from '@/types/trading'
import { buildPositionRows } from './scalpingRows'

const SYM = 'NIFTY16JUN2623600CE'

const pos = (o: Partial<Position>): Position => ({
  symbol: SYM,
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
    symbol: SYM,
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

describe('buildPositionRows', () => {
  it('takes net qty from the positionbook (authoritative), not trade imbalance', () => {
    // Today's trades net -65, but the leg is absent from the positionbook (closed) ->
    // must read flat, not a phantom open short. (Regression test for the F6 bug.)
    const trades = [
      trade({ action: 'BUY', quantity: 9685, average_price: 179 }),
      trade({ action: 'SELL', quantity: 9750, average_price: 179 }),
    ]
    const r = buildPositionRows([], trades, {}).find((x) => x.symbol === SYM)
    expect(r?.netQty).toBe(0)
    expect(r?.side).toBe('-')
  })

  it('uses the BROKER position average (not today VWAP) for unrealized P&L', () => {
    // Bought 130 today @100 VWAP, but broker avg is 90 (carried lot). Net +65 @ ltp 110.
    const trades = [trade({ action: 'BUY', quantity: 130, average_price: 100 })]
    const positions = [pos({ quantity: 65, average_price: 90, ltp: 110 })]
    const r = buildPositionRows(positions, trades, {})[0]
    expect(r.netQty).toBe(65)
    expect(r.avgPrice).toBe(90) // broker avg, not 100
    expect(r.unrealizedPnl).toBe((110 - 90) * 65) // 1300, not (110-100)*65=650
  })

  it('short position: SELL side, unrealized from broker avg', () => {
    const r = buildPositionRows([pos({ quantity: -65, average_price: 200, ltp: 180 })], [], {})[0]
    expect(r.side).toBe('SELL')
    expect(r.unrealizedPnl).toBe((200 - 180) * 65) // 1300
  })

  it('computes realized P&L from matched buy/sell and reads flat', () => {
    const trades = [
      trade({ action: 'BUY', quantity: 65, average_price: 100 }),
      trade({ action: 'SELL', quantity: 65, average_price: 110 }),
    ]
    const r = buildPositionRows([], trades, {})[0]
    expect(r.realizedPnl).toBe((110 - 100) * 65) // 650
    expect(r.netQty).toBe(0)
  })

  it('scopes rows to trackedKeys', () => {
    const positions = [
      pos({ symbol: 'RELIANCE', exchange: 'NSE', product: 'MIS', quantity: 1, ltp: 1010 }),
    ]
    // empty tracked set -> account-wide position excluded
    expect(buildPositionRows(positions, [], {}, undefined, new Set())).toHaveLength(0)
    // included when tracked
    const tracked = new Set(['NSE:RELIANCE:MIS'])
    expect(buildPositionRows(positions, [], {}, undefined, tracked)).toHaveLength(1)
  })

  it('prefers liveLtp() over the positionbook ltp for unrealized P&L', () => {
    const positions = [pos({ quantity: 65, average_price: 90, ltp: 100 })]
    const liveLtp = () => 120
    const r = buildPositionRows(positions, [], {}, liveLtp)[0]
    expect(r.ltp).toBe(120)
    expect(r.unrealizedPnl).toBe((120 - 90) * 65)
  })
})
