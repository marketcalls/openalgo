import { describe, expect, it } from 'vitest'
import { buildRoundTrips, derivePositions, deriveTrades } from '@/api/strategy_module'
import {
  favorablePeakPoints,
  formatIst,
  formatListPnl,
  formatPnl,
  type Order,
} from '@/types/strategy_module'

function order(partial: Partial<Order> & Pick<Order, 'id'>): Order {
  return {
    run_id: 1,
    leg_id: 1,
    kind: 'entry',
    broker_order_id: null,
    symbol: 'NIFTY28MAR2420800CE',
    exchange: 'NFO',
    action: 'BUY',
    qty: 50,
    pricetype: 'MARKET',
    price: 0,
    trigger_price: 0,
    status: 'complete',
    placed_at: '2026-04-12T03:45:00+00:00',
    filled_at: '2026-04-12T03:45:01+00:00',
    avg_fill_price: 100,
    filled_qty: 50,
    reject_reason: null,
    ...partial,
  }
}

describe('P&L formatting', () => {
  // The two rules differ on purpose. A list is scanned, so a strategy that has
  // not traded should read as blank rather than as a real zero; a detail page
  // is read, so there a zero is a measurement.
  it('renders zero as an em dash in the list and as 0.00 on the detail page', () => {
    expect(formatListPnl(0)).toBe('—')
    expect(formatPnl(0)).toBe('0.00')
  })

  it('signs a profit and leaves a loss with its own minus', () => {
    expect(formatListPnl(12.5)).toBe('+12.50')
    expect(formatPnl(12.5)).toBe('+12.50')
    expect(formatListPnl(-3)).toBe('-3.00')
    expect(formatPnl(-3)).toBe('-3.00')
  })

  it('renders an absent figure as an em dash in both', () => {
    expect(formatListPnl(null)).toBe('—')
    expect(formatListPnl(undefined)).toBe('—')
    expect(formatPnl(null)).toBe('—')
    expect(formatPnl(Number.NaN)).toBe('—')
  })
})

describe('IST rendering', () => {
  // The API sends UTC with an explicit offset. 03:45 UTC is 09:15 IST, and it
  // has to read as 09:15 whatever zone the browser is set to.
  it('converts a UTC timestamp to IST and says so', () => {
    const rendered = formatIst('2026-04-12T03:45:00+00:00')
    expect(rendered).toContain('09:15')
    expect(rendered).toContain('Apr')
    expect(rendered).toContain('2026')
    expect(rendered.endsWith('IST')).toBe(true)
  })

  it('drops the seconds and shortens the year for the list', () => {
    const rendered = formatIst('2026-04-12T03:45:09+00:00', false)
    expect(rendered).toContain('09:15')
    expect(rendered).not.toContain(':09')
    expect(rendered.endsWith('IST')).toBe(true)
  })

  it('renders a missing timestamp as an em dash', () => {
    expect(formatIst(null)).toBe('—')
    expect(formatIst(undefined)).toBe('—')
  })
})

describe('buildRoundTrips', () => {
  it('pairs an entry with its exit and signs a long trip from the exit price', () => {
    const trips = buildRoundTrips([
      order({ id: 1, kind: 'entry', action: 'BUY', avg_fill_price: 100 }),
      order({
        id: 2,
        kind: 'exit_target',
        action: 'SELL',
        avg_fill_price: 120,
        filled_at: '2026-04-12T05:00:00+00:00',
      }),
    ])
    expect(trips).toHaveLength(1)
    expect(trips[0].side).toBe('long')
    expect(trips[0].qty).toBe(50)
    expect(trips[0].pnl).toBe(1000) // (120 - 100) * 50
    expect(trips[0].exit_kind).toBe('exit_target')
  })

  it('inverts the sign for a short leg', () => {
    const trips = buildRoundTrips([
      order({ id: 1, kind: 'entry', action: 'SELL', avg_fill_price: 120 }),
      order({
        id: 2,
        kind: 'exit_sl',
        action: 'BUY',
        avg_fill_price: 100,
        filled_at: '2026-04-12T05:00:00+00:00',
      }),
    ])
    expect(trips[0].side).toBe('short')
    expect(trips[0].pnl).toBe(1000) // sold at 120, bought back at 100
  })

  it('matches FIFO when a leg re-enters within the same run', () => {
    const trips = buildRoundTrips([
      order({ id: 1, kind: 'entry', action: 'BUY', avg_fill_price: 100, filled_at: 't1' }),
      order({ id: 2, kind: 'entry', action: 'BUY', avg_fill_price: 110, filled_at: 't2' }),
      order({
        id: 3,
        kind: 'exit_sl',
        action: 'SELL',
        avg_fill_price: 130,
        filled_at: 't3',
      }),
      order({
        id: 4,
        kind: 'exit_eod',
        action: 'SELL',
        avg_fill_price: 90,
        filled_at: 't4',
      }),
    ])
    expect(trips).toHaveLength(2)
    // Newest first, so the second exit leads. It closes the 110 lot.
    expect(trips[0].entry_price).toBe(110)
    expect(trips[0].pnl).toBe(-1000)
    expect(trips[1].entry_price).toBe(100)
    expect(trips[1].pnl).toBe(1500)
  })

  it('never matches an exit against an entry from a different run', () => {
    const trips = buildRoundTrips([
      order({ id: 1, run_id: 1, kind: 'entry', action: 'BUY', filled_at: 't1' }),
      order({ id: 2, run_id: 2, kind: 'exit_eod', action: 'SELL', filled_at: 't2' }),
    ])
    expect(trips).toHaveLength(0)
  })

  it('ignores an order that never filled', () => {
    const trips = buildRoundTrips([
      order({ id: 1, kind: 'entry', action: 'BUY', filled_at: 't1' }),
      order({
        id: 2,
        kind: 'exit_sl',
        action: 'SELL',
        status: 'rejected',
        filled_qty: 0,
        avg_fill_price: null,
        filled_at: 't2',
      }),
    ])
    expect(trips).toHaveLength(0)
  })
})

describe('derivePositions', () => {
  it('nets two legs on the same contract and averages only the open lots', () => {
    const positions = derivePositions(
      [
        order({ id: 1, leg_id: 1, action: 'BUY', avg_fill_price: 100, filled_at: 't1' }),
        order({ id: 2, leg_id: 2, action: 'BUY', avg_fill_price: 200, filled_at: 't2' }),
      ],
      'NRML'
    )
    expect(positions).toHaveLength(1)
    expect(positions[0].net_qty).toBe(100)
    expect(positions[0].side).toBe('long')
    expect(positions[0].avg_entry_price).toBe(150)
    expect(positions[0].realized_pnl_lifetime).toBe(0)
  })

  it('books realized P&L when a lot is closed and leaves the rest open', () => {
    const positions = derivePositions(
      [
        order({
          id: 1,
          action: 'BUY',
          qty: 50,
          filled_qty: 50,
          avg_fill_price: 100,
          filled_at: 't1',
        }),
        order({
          id: 2,
          action: 'BUY',
          qty: 50,
          filled_qty: 50,
          avg_fill_price: 120,
          filled_at: 't2',
        }),
        order({
          id: 3,
          kind: 'exit_target',
          action: 'SELL',
          qty: 50,
          filled_qty: 50,
          avg_fill_price: 130,
          filled_at: 't3',
        }),
      ],
      'NRML'
    )
    // FIFO: the 100 lot closes at 130, leaving the 120 lot open.
    expect(positions[0].realized_pnl_lifetime).toBe(1500)
    expect(positions[0].net_qty).toBe(50)
    expect(positions[0].avg_entry_price).toBe(120)
  })

  it('marks a flat contract flat and prices unrealized off the live LTP', () => {
    const flat = derivePositions(
      [
        order({ id: 1, action: 'BUY', avg_fill_price: 100, filled_at: 't1' }),
        order({ id: 2, kind: 'exit_eod', action: 'SELL', avg_fill_price: 110, filled_at: 't2' }),
      ],
      'MIS'
    )
    expect(flat[0].side).toBe('flat')
    expect(flat[0].net_qty).toBe(0)
    expect(flat[0].unrealized_pnl).toBe(0)

    const open = derivePositions([order({ id: 1, action: 'SELL', avg_fill_price: 100 })], 'MIS', [
      {
        leg_id: 1,
        position: 'S',
        symbol: 'NIFTY28MAR2420800CE',
        exchange: 'NFO',
        lots: 1,
        qty: 50,
        entry_order_id: null,
        entry_status: 'complete',
        entry_avg: 100,
        exit_order_id: null,
        exit_kind: null,
        exit_avg: null,
        ltp: 90,
        mtm: 500,
        realized_pnl: 0,
        status: 'open',
        tick_source: 'ws',
        sl_pts: null,
        target_pts: null,
        trail_x: 0,
        trail_y: 0,
        effective_sl: null,
        effective_target: null,
        trail_active: false,
        highest_price: null,
        lowest_price: null,
      },
    ])
    // Short 50 at 100, now 90: (90 - 100) * 50 * -1 = +500.
    expect(open[0].side).toBe('short')
    expect(open[0].unrealized_pnl).toBe(500)
  })
})

describe('deriveTrades', () => {
  it('keeps only fills and values each one at its executed price', () => {
    const trades = deriveTrades([
      order({ id: 1, avg_fill_price: 101.5, filled_qty: 50 }),
      order({ id: 2, status: 'rejected', avg_fill_price: null, filled_qty: 0 }),
    ])
    expect(trades).toHaveLength(1)
    expect(trades[0].trade_value).toBeCloseTo(5075)
  })
})

describe('favorablePeakPoints', () => {
  it('measures a long leg from its high and a short leg from its low', () => {
    const base = { entry_avg: 100, highest_price: null, lowest_price: null }
    expect(favorablePeakPoints({ ...base, position: 'B', highest_price: 130 })).toBe(30)
    expect(favorablePeakPoints({ ...base, position: 'S', lowest_price: 80 })).toBe(20)
  })

  it('never reports an adverse move as favourable', () => {
    expect(
      favorablePeakPoints({
        position: 'B',
        entry_avg: 100,
        highest_price: 90,
        lowest_price: null,
      })
    ).toBe(0)
  })

  it('is zero before the leg has an entry price', () => {
    expect(
      favorablePeakPoints({
        position: 'B',
        entry_avg: 0,
        highest_price: 130,
        lowest_price: null,
      })
    ).toBe(0)
  })
})
