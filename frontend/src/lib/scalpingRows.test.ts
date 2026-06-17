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

  it('coerces string numerics from the live PositionBook contract (#1532)', () => {
    // Live brokers (e.g. Zerodha) return PositionBook numerics as strings, per
    // the documented API contract: { quantity: "-1", average_price: "83.74", ... }.
    // The row must be numeric so the UI can call avgPrice.toFixed() without crashing.
    const livePos = {
      symbol: SYM,
      exchange: 'NFO',
      product: 'NRML',
      quantity: '65',
      average_price: '90.5',
      ltp: '110.25',
      pnl: '0',
      pnlpercent: '0',
    } as unknown as Position
    const liveTrade = {
      symbol: SYM,
      exchange: 'NFO',
      product: 'NRML',
      action: 'BUY',
      quantity: '65',
      average_price: '90.5',
      trade_value: '5882.5',
      orderid: 'o1',
      timestamp: '2026-06-14 10:00:00',
    } as unknown as Trade
    const r = buildPositionRows([livePos], [liveTrade], {})[0]
    expect(typeof r.avgPrice).toBe('number')
    expect(typeof r.netQty).toBe('number')
    expect(typeof r.ltp).toBe('number')
    expect(typeof r.buyAvg).toBe('number')
    expect(r.netQty).toBe(65)
    expect(r.avgPrice).toBe(90.5)
    expect(r.unrealizedPnl).toBe((110.25 - 90.5) * 65)
    expect(() => r.avgPrice.toFixed(2)).not.toThrow()
    expect(r.avgPrice.toFixed(2)).toBe('90.50')
  })
})
