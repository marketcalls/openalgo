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

  describe('MTM across partial exits and re-entries (#2434)', () => {
    // Buy 1 unit at 100, 110 and 120, sell 1 at 130, later buy 1 more at 105, then sell
    // the remaining 3 at 125. The broker (and the sandbox) carries the open quantity at
    // its weighted average cost and books each exit against that average.
    const buys = [
      trade({ action: 'BUY', quantity: 1, average_price: 100 }),
      trade({ action: 'BUY', quantity: 1, average_price: 110 }),
      trade({ action: 'BUY', quantity: 1, average_price: 120 }),
    ]
    const firstExit = trade({ action: 'SELL', quantity: 1, average_price: 130 })
    const reEntry = trade({ action: 'BUY', quantity: 1, average_price: 105 })
    const finalExit = trade({ action: 'SELL', quantity: 3, average_price: 125 })

    it('after a partial exit: realized from the exit, unrealized on the rest', () => {
      const positions = [pos({ quantity: 2, average_price: 110, ltp: 115 })]
      const r = buildPositionRows(positions, [...buys, firstExit], {})[0]
      expect(r.realizedPnl).toBeCloseTo(20) // (130 - 110) x 1
      expect(r.unrealizedPnl).toBeCloseTo(10) // (115 - 110) x 2
      expect(r.totalPnl).toBeCloseTo(30)
    })

    it('a buy after the partial exit does not re-price the earlier exit', () => {
      const avg = (2 * 110 + 105) / 3
      const positions = [pos({ quantity: 3, average_price: avg, ltp: 115 })]
      const r = buildPositionRows(positions, [...buys, firstExit, reEntry], {})[0]
      expect(r.realizedPnl).toBeCloseTo(20) // was 21.25: (130 - day buy avg 108.75) x 1
      expect(r.unrealizedPnl).toBeCloseTo((115 - avg) * 3)
      // Total MTM = sold - bought + open qty at LTP = 130 - 435 + 3 x 115
      expect(r.totalPnl).toBeCloseTo(40)
    })

    it('after the final exit: realized is the whole day and the leg is flat', () => {
      const r = buildPositionRows([], [...buys, firstExit, reEntry, finalExit], {})[0]
      expect(r.netQty).toBe(0)
      expect(r.unrealizedPnl).toBe(0)
      expect(r.realizedPnl).toBeCloseTo(505 - 435) // 70
    })

    it('the total stays right when the broker reports a net average instead', () => {
      // Some brokers fold the booked profit into the open average: (435 - 130) / 3.
      const netAvg = (435 - 130) / 3
      const positions = [pos({ quantity: 3, average_price: netAvg, ltp: 115 })]
      const r = buildPositionRows(positions, [...buys, firstExit, reEntry], {})[0]
      expect(r.totalPnl).toBeCloseTo(40)
    })

    it('short side: re-entry after a partial cover keeps the cover booked', () => {
      const trades = [
        trade({ action: 'SELL', quantity: 2, average_price: 200 }),
        trade({ action: 'BUY', quantity: 1, average_price: 190 }), // cover 1: +10
        trade({ action: 'SELL', quantity: 1, average_price: 230 }), // re-enter short
      ]
      const avg = (200 + 230) / 2
      const positions = [pos({ quantity: -2, average_price: avg, ltp: 210 })]
      const r = buildPositionRows(positions, trades, {})[0]
      expect(r.side).toBe('SELL')
      expect(r.realizedPnl).toBeCloseTo(10) // the matched-average formula gave 20
      expect(r.unrealizedPnl).toBeCloseTo((avg - 210) * 2)
      expect(r.totalPnl).toBeCloseTo(630 - 190 - 2 * 210) // 20
    })

    it('a lot carried in from an earlier day keeps the matched-quantity estimate', () => {
      // Positionbook holds 3 but today shows only a sell of 1: a carried lot.
      const trades = [trade({ action: 'SELL', quantity: 1, average_price: 130 })]
      const positions = [pos({ quantity: 3, average_price: 110, ltp: 115 })]
      const r = buildPositionRows(positions, trades, {})[0]
      expect(r.realizedPnl).toBe(0) // no buy today to match against
      expect(r.unrealizedPnl).toBeCloseTo(15)
    })
  })
})
