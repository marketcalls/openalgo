import { describe, expect, it } from 'vitest'
import {
  buildRoundTrips,
  collapseToUnderlyings,
  derivePositions,
  deriveTrades,
  lotSizeFromRows,
} from '@/api/strategy_module'
import {
  convertLegKind,
  defaultQtyMode,
  derivativeExchangeFor,
  favorablePeakPoints,
  filterStrikes,
  formatIst,
  formatListPnl,
  formatPnl,
  freshSignalLeg,
  isDerivativeExchange,
  isWholeLots,
  type Leg,
  legToPayload,
  MAX_SIGNAL_LOTS,
  MAX_SIGNAL_QTY,
  monthlyExpiries,
  type Order,
  parseExpiryDate,
  type QtyMode,
  resolvedQuantity,
  resolveExpiryRank,
  SIGNAL_LEG_SEGMENTS,
  SIGNAL_MODE_TABS,
  sortExpiries,
  TAB_SEGMENTS,
  withQtyMode,
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

// An index chain as the platform returns it: weeklies for the near month, then
// one contract per month further out. Ascending, DD-MMM-YY.
const NIFTY_OPTION_EXPIRIES = [
  '10-JUL-25',
  '17-JUL-25',
  '24-JUL-25',
  '31-JUL-25',
  '07-AUG-25',
  '28-AUG-25',
  '25-SEP-25',
  '24-DEC-25',
]

// Futures are monthly on every Indian exchange, index included.
const NIFTY_FUTURE_EXPIRIES = ['31-JUL-25', '28-AUG-25', '25-SEP-25']

describe('parseExpiryDate', () => {
  it('reads a DD-MMM-YY date as a UTC calendar date', () => {
    const date = parseExpiryDate('10-JUL-25')
    expect(date?.getUTCFullYear()).toBe(2025)
    expect(date?.getUTCMonth()).toBe(6)
    expect(date?.getUTCDate()).toBe(10)
  })

  it('accepts a lowercase month and a single-digit day', () => {
    expect(parseExpiryDate('7-aug-25')?.getUTCDate()).toBe(7)
  })

  it('refuses a date that is not one rather than rolling it forward', () => {
    expect(parseExpiryDate('31-FEB-25')).toBeNull()
    expect(parseExpiryDate('10-XXX-25')).toBeNull()
    expect(parseExpiryDate('2025-07-10')).toBeNull()
    expect(parseExpiryDate('')).toBeNull()
  })
})

describe('sortExpiries', () => {
  it('orders by date, not by string, and drops what it cannot parse', () => {
    expect(sortExpiries(['28-AUG-25', 'garbage', '10-JUL-25', '24-DEC-25'])).toEqual([
      '10-JUL-25',
      '28-AUG-25',
      '24-DEC-25',
    ])
  })
})

describe('monthlyExpiries', () => {
  it('keeps the last contract of each calendar month', () => {
    expect(monthlyExpiries(NIFTY_OPTION_EXPIRIES)).toEqual([
      '31-JUL-25',
      '28-AUG-25',
      '25-SEP-25',
      '24-DEC-25',
    ])
  })

  it('leaves a monthly-only list alone', () => {
    expect(monthlyExpiries(NIFTY_FUTURE_EXPIRIES)).toEqual(NIFTY_FUTURE_EXPIRIES)
  })
})

describe('resolveExpiryRank', () => {
  it('resolves the weekly ranks to the two nearest contracts', () => {
    expect(resolveExpiryRank('weekly', NIFTY_OPTION_EXPIRIES)).toBe('10-JUL-25')
    expect(resolveExpiryRank('next_week', NIFTY_OPTION_EXPIRIES)).toBe('17-JUL-25')
  })

  it('resolves the monthly ranks to the last contract of the month, not the nearest', () => {
    expect(resolveExpiryRank('monthly', NIFTY_OPTION_EXPIRIES)).toBe('31-JUL-25')
    expect(resolveExpiryRank('next_month', NIFTY_OPTION_EXPIRIES)).toBe('28-AUG-25')
  })

  it('treats the legacy spellings as the monthly pair', () => {
    expect(resolveExpiryRank('current', NIFTY_OPTION_EXPIRIES)).toBe(
      resolveExpiryRank('monthly', NIFTY_OPTION_EXPIRIES)
    )
    expect(resolveExpiryRank('next', NIFTY_OPTION_EXPIRIES)).toBe(
      resolveExpiryRank('next_month', NIFTY_OPTION_EXPIRIES)
    )
  })

  it('resolves against a monthly-only futures list', () => {
    expect(resolveExpiryRank('monthly', NIFTY_FUTURE_EXPIRIES)).toBe('31-JUL-25')
    expect(resolveExpiryRank('next_month', NIFTY_FUTURE_EXPIRIES)).toBe('28-AUG-25')
  })

  it('does not care what order the platform returned them in', () => {
    const shuffled = ['24-DEC-25', '17-JUL-25', '31-JUL-25', '10-JUL-25', '28-AUG-25']
    expect(resolveExpiryRank('weekly', shuffled)).toBe('10-JUL-25')
    expect(resolveExpiryRank('monthly', shuffled)).toBe('31-JUL-25')
  })

  // Null rather than the nearest expiry: quietly substituting a different
  // contract is how a leg ends up on an expiry nobody chose.
  it('returns null rather than substituting when the list cannot answer', () => {
    expect(resolveExpiryRank('weekly', [])).toBeNull()
    expect(resolveExpiryRank('next_week', ['10-JUL-25'])).toBeNull()
    expect(resolveExpiryRank('next_month', ['31-JUL-25'])).toBeNull()
  })
})

describe('derivativeExchangeFor', () => {
  it('sends an NSE underlying to NFO and a BSE one to BFO', () => {
    expect(derivativeExchangeFor('NSE_INDEX')).toBe('NFO')
    expect(derivativeExchangeFor('NSE')).toBe('NFO')
    expect(derivativeExchangeFor('BSE_INDEX')).toBe('BFO')
    expect(derivativeExchangeFor('BSE')).toBe('BFO')
  })

  it('leaves an exchange that is already its own derivative venue alone', () => {
    expect(derivativeExchangeFor('MCX')).toBe('MCX')
    expect(derivativeExchangeFor('CDS')).toBe('CDS')
  })
})

describe('filterStrikes', () => {
  const strikes = [23900, 24000, 24050, 24400, 25000]

  it('returns everything when nothing is typed', () => {
    expect(filterStrikes(strikes, '')).toEqual(strikes)
    expect(filterStrikes(strikes, '   ')).toEqual(strikes)
  })

  it('matches a substring, not just a prefix', () => {
    // 24000 matches too: it contains "400" in the middle, which is the whole
    // point of a substring match on a chain that does not start at zero.
    expect(filterStrikes(strikes, '400')).toEqual([24000, 24400])
    expect(filterStrikes(strikes, '2400')).toEqual([24000])
    expect(filterStrikes(strikes, '405')).toEqual([24050])
  })

  it('narrows to one strike when the whole number is typed', () => {
    expect(filterStrikes(strikes, '24050')).toEqual([24050])
  })

  it('returns nothing when the filter matches nothing', () => {
    expect(filterStrikes(strikes, '999')).toEqual([])
  })
})

describe('collapseToUnderlyings', () => {
  const rows = [
    { symbol: 'RELIANCE25AUG1500CE', name: 'RELIANCE', exchange: 'NFO', instrumenttype: 'CE' },
    { symbol: 'RELIANCE25AUG1500PE', name: 'RELIANCE', exchange: 'NFO', instrumenttype: 'PE' },
    { symbol: 'RELIANCE25AUGFUT', name: 'RELIANCE', exchange: 'NFO', instrumenttype: 'FUT' },
    { symbol: 'RELIANCEPP25AUGFUT', name: 'RELIANCEPP', exchange: 'NFO', instrumenttype: 'FUT' },
  ]

  it('collapses contracts onto the underlying behind them', () => {
    const results = collapseToUnderlyings(rows, 'RELIANCE')
    expect(results).toHaveLength(2)
    expect(results[0].symbol).toBe('RELIANCE')
    expect(results[0].instruments).toBe('CE, FUT, PE')
  })

  it('puts the exact match above a longer name that merely starts the same', () => {
    const results = collapseToUnderlyings(rows, 'RELIANCE')
    expect(results.map((result) => result.symbol)).toEqual(['RELIANCE', 'RELIANCEPP'])
  })

  it('ignores a row with no name to collapse onto', () => {
    expect(
      collapseToUnderlyings([{ symbol: '', name: '', exchange: 'NFO', instrumenttype: '' }], 'X')
    ).toEqual([])
  })
})

// ---------------------------------------------------------------------------
// Leg shapes
//
// The validator rejects unknown keys on both sides, so what matters is not
// only the values but the exact key set. A batch field surviving into a signal
// payload is refused outright, naming a field the user cannot see any more.
// ---------------------------------------------------------------------------

const BATCH_OPTION_LEG: Leg = {
  id: 1,
  segment: 'options',
  position: 'S',
  lots: 2,
  option_type: 'CE',
  strike_mode: 'atm',
  atm_offset: 'OTM2',
  strike: null,
  expiry: 'weekly',
  sl_pts: 30,
  target_pts: 60,
  trail: { x: 10, y: 5 },
}

describe('legToPayload, batch', () => {
  // The regression guard: batch mode is the one that already works.
  it('round-trips a batch options leg unchanged', () => {
    expect(legToPayload(BATCH_OPTION_LEG, 'batch')).toEqual({
      id: 1,
      segment: 'options',
      position: 'S',
      lots: 2,
      expiry: 'weekly',
      option_type: 'CE',
      strike_mode: 'atm',
      atm_offset: 'OTM2',
      sl_pts: 30,
      target_pts: 60,
      trail: { x: 10, y: 5 },
    })
  })

  it('defaults to batch when no kind is given, so an old call site is unchanged', () => {
    expect(legToPayload(BATCH_OPTION_LEG)).toEqual(legToPayload(BATCH_OPTION_LEG, 'batch'))
  })

  it('never emits a signal field', () => {
    const payload = legToPayload(
      { ...BATCH_OPTION_LEG, symbol: 'RELIANCE', exchange: 'NSE', side: 'long', qty: 500 },
      'batch'
    )
    expect(payload).not.toHaveProperty('symbol')
    expect(payload).not.toHaveProperty('exchange')
    expect(payload).not.toHaveProperty('side')
    expect(payload).not.toHaveProperty('qty')
  })

  it('sends atm_offset or strike, never both', () => {
    const atm = legToPayload(BATCH_OPTION_LEG, 'batch')
    expect(atm).toHaveProperty('atm_offset')
    expect(atm).not.toHaveProperty('strike')

    const direct = legToPayload(
      { ...BATCH_OPTION_LEG, strike_mode: 'strike', strike: 24500 },
      'batch'
    )
    expect(direct.strike).toBe(24500)
    expect(direct).not.toHaveProperty('atm_offset')
  })

  it('omits expiry on a cash leg, which the validator refuses outright', () => {
    const payload = legToPayload(
      { id: 1, segment: 'cash', position: 'B', lots: 1, expiry: 'monthly' },
      'batch'
    )
    expect(payload).not.toHaveProperty('expiry')
    expect(Object.keys(payload).sort()).toEqual(['id', 'lots', 'position', 'segment'])
  })
})

describe('legToPayload, signal', () => {
  const SIGNAL_CASH_LEG: Leg = {
    id: 1,
    segment: 'cash',
    symbol: ' reliance ',
    exchange: 'nse',
    side: 'long',
    qty: 500,
    expiry: null,
    sl_pts: null,
    target_pts: null,
    trail: { x: 0, y: 0 },
  }

  it('emits exactly the keys the signal validator accepts', () => {
    expect(legToPayload(SIGNAL_CASH_LEG, 'signal')).toEqual({
      id: 1,
      segment: 'cash',
      symbol: 'RELIANCE',
      exchange: 'NSE',
      side: 'long',
      qty: 500,
      qty_mode: 'units',
    })
  })

  // The guard the whole conversion exists for.
  it('never leaks a batch or option field, even when the leg still carries one', () => {
    const stale: Leg = {
      ...SIGNAL_CASH_LEG,
      position: 'S',
      lots: 3,
      option_type: 'CE',
      strike_mode: 'atm',
      atm_offset: 'ATM',
      strike: 24500,
    }
    const payload = legToPayload(stale, 'signal')
    for (const forbidden of [
      'position',
      'lots',
      'option_type',
      'strike_mode',
      'atm_offset',
      'strike',
    ]) {
      expect(payload).not.toHaveProperty(forbidden)
    }
  })

  it('omits expiry on a cash leg and keeps it on a futures leg', () => {
    expect(legToPayload(SIGNAL_CASH_LEG, 'signal')).not.toHaveProperty('expiry')

    const futures = legToPayload(
      { ...SIGNAL_CASH_LEG, segment: 'futures', expiry: 'next_month' },
      'signal'
    )
    expect(futures.expiry).toBe('next_month')
  })

  it('defaults a futures leg to the current month rather than sending nothing', () => {
    const futures = legToPayload({ ...SIGNAL_CASH_LEG, segment: 'futures', expiry: null }, 'signal')
    expect(futures.expiry).toBe('monthly')
  })

  it('defaults side to both and quantity to one', () => {
    const payload = legToPayload(
      { id: 2, segment: 'cash', symbol: 'TCS', exchange: 'NSE' },
      'signal'
    )
    expect(payload.side).toBe('both')
    expect(payload.qty).toBe(1)
  })

  it('sends a whole quantity, because the validator takes an integer', () => {
    expect(legToPayload({ ...SIGNAL_CASH_LEG, qty: 12.9 }, 'signal').qty).toBe(12)
    expect(Number.isInteger(legToPayload({ ...SIGNAL_CASH_LEG, qty: 0.5 }, 'signal').qty)).toBe(
      true
    )
  })

  it('keeps a quantity at the cap the validator allows', () => {
    expect(legToPayload({ ...SIGNAL_CASH_LEG, qty: MAX_SIGNAL_QTY }, 'signal').qty).toBe(
      MAX_SIGNAL_QTY
    )
  })

  it('drops a zero trail and keeps a configured one', () => {
    expect(legToPayload(SIGNAL_CASH_LEG, 'signal')).not.toHaveProperty('trail')
    const trailing = legToPayload({ ...SIGNAL_CASH_LEG, trail: { x: 8, y: 2 } }, 'signal')
    expect(trailing.trail).toEqual({ x: 8, y: 2 })
  })
})

describe('convertLegKind', () => {
  it('turns an options leg into a cash signal leg with no option fields left', () => {
    const converted = convertLegKind(BATCH_OPTION_LEG, 'signal', 'stocks_fno')
    expect(converted.segment).toBe('cash')
    expect(converted.symbol).toBe('')
    expect(converted.exchange).toBe('NSE')
    expect(converted.side).toBe('both')
    expect(converted.qty).toBe(1)
    for (const forbidden of ['position', 'lots', 'option_type', 'strike_mode', 'atm_offset']) {
      expect(converted).not.toHaveProperty(forbidden)
    }
  })

  it('carries per-leg risk across the switch, because it means the same thing', () => {
    const converted = convertLegKind(BATCH_OPTION_LEG, 'signal', 'stocks_fno')
    expect(converted.sl_pts).toBe(30)
    expect(converted.target_pts).toBe(60)
    expect(converted.trail).toEqual({ x: 10, y: 5 })
  })

  it('leaves a futures leg on futures and keeps its rank', () => {
    const converted = convertLegKind(
      { id: 1, segment: 'futures', position: 'B', lots: 1, expiry: 'next_month' },
      'signal',
      'mcx'
    )
    expect(converted.segment).toBe('futures')
    expect(converted.expiry).toBe('next_month')
    expect(converted.exchange).toBe('MCX')
  })

  it('rebuilds a batch leg coming back from signal mode', () => {
    const signalLeg = convertLegKind(BATCH_OPTION_LEG, 'signal', 'stocks_fno')
    const back = convertLegKind(signalLeg, 'batch', 'stocks_fno')
    expect(back.position).toBe('S')
    expect(back.lots).toBe(1)
    expect(back.segment).toBe('cash')
    for (const forbidden of ['symbol', 'exchange', 'side', 'qty']) {
      expect(back).not.toHaveProperty(forbidden)
    }
  })

  it('never produces a segment the tab does not allow', () => {
    // MCX has no cash market, so a cash signal leg cannot come back as one.
    const back = convertLegKind(
      { id: 1, segment: 'cash', symbol: 'GOLD', exchange: 'MCX', side: 'both', qty: 1 },
      'batch',
      'mcx'
    )
    expect(TAB_SEGMENTS.mcx).toContain(back.segment)
    expect(back.segment).not.toBe('cash')
  })

  it('always comes back ATM-relative, since there is no strike to carry over', () => {
    const back = convertLegKind(
      { id: 1, segment: 'futures', symbol: 'RELIANCE', exchange: 'NFO', side: 'both', qty: 1 },
      'batch',
      'weekly_monthly'
    )
    // futures stays futures, so no option fields at all
    expect(back.strike_mode).toBeNull()
    expect(back.strike).toBeNull()
  })
})

describe('freshSignalLeg', () => {
  it('starts a stocks leg on cash with no expiry and no symbol', () => {
    const leg = freshSignalLeg(1, 'stocks_fno')
    expect(leg.segment).toBe('cash')
    expect(leg.expiry).toBeNull()
    expect(leg.symbol).toBe('')
    expect(leg.exchange).toBe('NSE')
    expect(leg.qty).toBe(1)
    expect(leg.side).toBe('both')
  })

  it('starts an MCX leg on futures, which is what MCX trades', () => {
    const leg = freshSignalLeg(1, 'mcx')
    expect(leg.segment).toBe('futures')
    expect(leg.expiry).toBe('monthly')
    expect(leg.exchange).toBe('MCX')
  })

  it('produces a leg that survives its own payload conversion', () => {
    const payload = legToPayload(freshSignalLeg(3, 'mcx'), 'signal')
    expect(Object.keys(payload).sort()).toEqual([
      'exchange',
      'expiry',
      'id',
      'qty',
      'qty_mode',
      'segment',
      'side',
      'symbol',
    ])
  })
})

describe('signal mode universe', () => {
  it('offers only the tabs that have something for a signal leg to trade', () => {
    expect(SIGNAL_MODE_TABS).toEqual(['stocks_fno', 'mcx'])
    expect(SIGNAL_MODE_TABS).not.toContain('weekly_monthly')
    expect(SIGNAL_MODE_TABS).not.toContain('monthly_only')
  })

  it('offers no options segment, because a signal leg carries no option fields', () => {
    expect(SIGNAL_LEG_SEGMENTS).toEqual(['cash', 'futures'])
    expect(SIGNAL_LEG_SEGMENTS).not.toContain('options')
  })
})

// ---------------------------------------------------------------------------
// Quantity modes
//
// The stored number means one of two things and the mode is what says which,
// so the tests are about what reaches the wire, not about arithmetic.
// ---------------------------------------------------------------------------

const NIFTY_FUT_LEG: Leg = {
  id: 1,
  segment: 'futures',
  symbol: 'NIFTY',
  exchange: 'NFO',
  side: 'both',
  qty: 5,
  qty_mode: 'lots',
  expiry: 'monthly',
}

const RELIANCE_CASH_LEG: Leg = {
  id: 1,
  segment: 'cash',
  symbol: 'RELIANCE',
  exchange: 'NSE',
  side: 'both',
  qty: 500,
  qty_mode: 'units',
}

describe('quantity mode defaults', () => {
  it('counts a derivative venue in lots and a cash one in units', () => {
    expect(defaultQtyMode('NFO')).toBe('lots')
    expect(defaultQtyMode('BFO')).toBe('lots')
    expect(defaultQtyMode('MCX')).toBe('lots')
    expect(defaultQtyMode('NSE')).toBe('units')
    expect(defaultQtyMode('BSE')).toBe('units')
  })

  it('classifies exchanges the way the validator does', () => {
    for (const venue of ['NFO', 'BFO', 'MCX', 'CDS', 'NCO', 'BCD', 'NCDEX', 'CRYPTO']) {
      expect(isDerivativeExchange(venue)).toBe(true)
    }
    for (const venue of ['NSE', 'BSE', 'NSE_INDEX', '', null, undefined]) {
      expect(isDerivativeExchange(venue)).toBe(false)
    }
  })

  it('is case and whitespace insensitive, since the field is typed by hand', () => {
    expect(defaultQtyMode(' nfo ')).toBe('lots')
  })

  it('seeds a new leg with the mode its venue implies', () => {
    expect(freshSignalLeg(1, 'stocks_fno').qty_mode).toBe('units')
    expect(freshSignalLeg(1, 'mcx').qty_mode).toBe('lots')
    expect(freshSignalLeg(1, 'mcx').exchange).toBe('MCX')
  })
})

describe('legToPayload, quantity mode', () => {
  // The whole point of the mode: five lots of NIFTY is stored as 5, not 325.
  it('sends the lot count, never the product', () => {
    const payload = legToPayload(NIFTY_FUT_LEG, 'signal')
    expect(payload.qty).toBe(5)
    expect(payload.qty_mode).toBe('lots')
    expect(payload.qty).not.toBe(325)
  })

  it('sends the quantity itself in units mode', () => {
    const payload = legToPayload(RELIANCE_CASH_LEG, 'signal')
    expect(payload.qty).toBe(500)
    expect(payload.qty_mode).toBe('units')
  })

  it('falls back to the venue default when the leg has no mode of its own', () => {
    const noMode = { ...NIFTY_FUT_LEG, qty_mode: null }
    expect(legToPayload(noMode, 'signal').qty_mode).toBe('lots')
    expect(legToPayload({ ...RELIANCE_CASH_LEG, qty_mode: null }, 'signal').qty_mode).toBe('units')
  })

  // Refused outright by the validator, so it never leaves the browser.
  it('forces units on a cash leg however the mode got set', () => {
    const wrong = { ...RELIANCE_CASH_LEG, qty_mode: 'lots' as QtyMode }
    expect(legToPayload(wrong, 'signal').qty_mode).toBe('units')
  })

  it('clamps to the cap that belongs to the mode', () => {
    expect(legToPayload({ ...NIFTY_FUT_LEG, qty: 99_999 }, 'signal').qty).toBe(MAX_SIGNAL_LOTS)
    expect(legToPayload({ ...RELIANCE_CASH_LEG, qty: 9_999_999 }, 'signal').qty).toBe(
      MAX_SIGNAL_QTY
    )
  })

  it('still sends a whole number', () => {
    expect(legToPayload({ ...NIFTY_FUT_LEG, qty: 5.9 }, 'signal').qty).toBe(5)
  })

  // Batch legs count lots in their own field and the batch validator rejects
  // qty_mode outright.
  it('never puts qty_mode on a batch leg', () => {
    const payload = legToPayload(
      { id: 1, segment: 'options', position: 'S', lots: 2, expiry: 'weekly', qty_mode: 'lots' },
      'batch'
    )
    expect(payload).not.toHaveProperty('qty_mode')
    expect(payload.lots).toBe(2)
  })
})

describe('withQtyMode', () => {
  // Decided: the number is kept and reinterpreted, never converted. Converting
  // would silently rewrite what the user typed, and could only work one way.
  it('keeps the number the user typed rather than converting it', () => {
    const asUnits = withQtyMode(NIFTY_FUT_LEG, 'units')
    expect(asUnits.qty).toBe(5)
    expect(asUnits.qty_mode).toBe('units')

    const backToLots = withQtyMode(asUnits, 'lots')
    expect(backToLots.qty).toBe(5)
    expect(backToLots.qty_mode).toBe('lots')
  })

  it('leaves a round trip through the toggle exactly where it started', () => {
    expect(withQtyMode(withQtyMode(NIFTY_FUT_LEG, 'units'), 'lots')).toEqual(NIFTY_FUT_LEG)
  })

  it('clamps only when the new cap is smaller', () => {
    const big = { ...NIFTY_FUT_LEG, qty_mode: 'units' as QtyMode, qty: 500_000 }
    expect(withQtyMode(big, 'lots').qty).toBe(MAX_SIGNAL_LOTS)
    expect(withQtyMode({ ...NIFTY_FUT_LEG, qty: 200 }, 'units').qty).toBe(200)
  })

  it('refuses lots on a cash venue, leaving the leg untouched', () => {
    expect(withQtyMode(RELIANCE_CASH_LEG, 'lots')).toBe(RELIANCE_CASH_LEG)
  })
})

describe('resolvedQuantity', () => {
  it('multiplies a lot count by the lot size', () => {
    expect(resolvedQuantity(5, 'lots', 65)).toBe(325)
    expect(resolvedQuantity(1, 'lots', 65)).toBe(65)
  })

  it('leaves a units quantity alone, lot size or not', () => {
    expect(resolvedQuantity(325, 'units', 65)).toBe(325)
    expect(resolvedQuantity(500, 'units', null)).toBe(500)
  })

  it('cannot answer for lots without a lot size, and says so with null', () => {
    expect(resolvedQuantity(5, 'lots', null)).toBeNull()
    expect(resolvedQuantity(5, 'lots', 0)).toBeNull()
    expect(resolvedQuantity(null, 'lots', 65)).toBeNull()
  })

  // The reason the lot count is what gets stored: the same leg follows a
  // revised lot size instead of silently becoming a different number of lots.
  it('follows a revised lot size, which a stored product could not', () => {
    expect(resolvedQuantity(5, 'lots', 75)).toBe(375)
    expect(resolvedQuantity(5, 'lots', 65)).toBe(325)
  })
})

describe('isWholeLots', () => {
  it('accepts a whole multiple and rejects a part lot', () => {
    expect(isWholeLots(325, 65)).toBe(true)
    expect(isWholeLots(300, 65)).toBe(false)
  })

  it('accepts anything when there is no lot size to check against', () => {
    expect(isWholeLots(7, null)).toBe(true)
    expect(isWholeLots(7, 0)).toBe(true)
  })
})

describe('lotSizeFromRows', () => {
  const rows = [
    {
      symbol: 'NIFTY25AUG2625000CE',
      name: 'NIFTY',
      exchange: 'NFO',
      instrumenttype: 'CE',
      lotsize: 65,
    },
    {
      symbol: 'NIFTY25AUG26FUT',
      name: 'NIFTY',
      exchange: 'NFO',
      instrumenttype: 'FUT',
      lotsize: 65,
    },
    {
      symbol: 'NIFTYNXT50FUT',
      name: 'NIFTYNXT50',
      exchange: 'NFO',
      instrumenttype: 'FUT',
      lotsize: 25,
    },
  ]

  it('reads the lot size for the root that was asked for', () => {
    expect(lotSizeFromRows(rows, 'NIFTY')).toBe(65)
    expect(lotSizeFromRows(rows, 'NIFTYNXT50')).toBe(25)
  })

  it('does not answer with a different underlying that merely matched the search', () => {
    expect(lotSizeFromRows(rows, 'BANKNIFTY')).toBeNull()
  })

  it('returns null rather than a guess when no row carries a usable lot size', () => {
    expect(
      lotSizeFromRows(
        [{ symbol: 'X', name: 'X', exchange: 'NFO', instrumenttype: 'FUT', lotsize: 0 }],
        'X'
      )
    ).toBeNull()
    expect(lotSizeFromRows([], 'NIFTY')).toBeNull()
  })
})
