/**
 * What this pins.
 *
 * The first two tests are the whole card. A derived number is only worth
 * showing if it is exactly the sum of the legs printed under it, and a reader
 * has to be able to check that by eye: if the headline and the legs can
 * disagree, the headline is an assertion nobody can verify. So one test adds
 * the legs up by hand, and one moves a leg and watches the headline move by
 * the same amount.
 *
 * The third is the roll. The legs are pinned at the strikes they were resolved
 * against and are never resubscribed, so the only thing standing between an
 * operator and a card headed "ATM straddle" that stopped being one an hour ago
 * is the sentence this test asserts. It is deliberately paired with its
 * opposite: a strangle drifts by design and must not carry the warning.
 *
 * The rest are the same honesty rules the quotes card is held to. A leg with
 * no price withholds the value rather than counting as zero, which would read
 * as a real number and be wrong by a whole leg.
 */

import { act, render, screen, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/lib/MarketDataManager', () => import('@/test/marketDataHarness'))

import { feed } from '@/test/marketDataHarness'
import { LiveComboCard } from './LiveComboCard'
import { BUDGET } from './live'

const HOUR = 3_600_000

const MARKET = {
  date: '2026-09-03',
  as_of: '2026-09-03T12:44:12+05:30',
  timezone: 'Asia/Kolkata',
  known: true,
  exchanges: [
    {
      exchange: 'NSE',
      known: true,
      is_open: true,
      opens_at: Date.now() - HOUR,
      closes_at: Date.now() + HOUR,
    },
    {
      exchange: 'NFO',
      known: true,
      is_open: true,
      opens_at: Date.now() - HOUR,
      closes_at: Date.now() + HOUR,
    },
  ],
  is_open: true,
}

const CALL = {
  symbol: 'NIFTY08SEP2623850CE',
  exchange: 'NFO',
  segment: 'OPTION',
  side: 'BUY',
  lots: 1,
  multiplier: 1,
  origin: 'structure',
  role: 'atm_call',
  option_type: 'CE',
  strike: 23850,
  expiry: '08SEP26',
  lot_size: 75,
  tick_size: 0.05,
  seed: { ltp: 120.5, prev_close: 118.0 },
}

const PUT = {
  ...CALL,
  symbol: 'NIFTY08SEP2623850PE',
  role: 'atm_put',
  option_type: 'PE',
  seed: { ltp: 95.25, prev_close: 99.5 },
}

const STRADDLE = {
  structure: 'straddle',
  summary: 'The combined premium of both legs, per unit.',
  label: 'NIFTY 08SEP26 23850 straddle',
  underlying: 'NIFTY',
  underlying_exchange: 'NSE_INDEX',
  expiry: '08SEP26',
  expiry_choice: 'current_week',
  mode: 'Quote',
  currency: 'INR',
  account_mode: 'live',
  as_of: '2026-09-03T12:44:12+05:30',
  timezone: 'Asia/Kolkata',
  spot: {
    symbol: 'NIFTY',
    exchange: 'NSE_INDEX',
    ltp: 23873.45,
    seed: { ltp: 23873.45, prev_close: 23914.45 },
  },
  legs: [CALL, PUT],
  formula: {
    kind: 'signed_sum',
    constant: null,
    per: 'unit',
    expression: 'NIFTY08SEP2623850CE + NIFTY08SEP2623850PE',
  },
  seed: { value: 215.75, complete: true, legs_priced: 2 },
  lot_size: 75,
  atm: {
    strike: 23850,
    strike_interval: 50,
    spot_at_resolution: 23873.45,
    roll_threshold: 25,
    pinned: true,
    claims_atm: true,
  },
  subscribe: [
    { symbol: 'NIFTY08SEP2623850CE', exchange: 'NFO' },
    { symbol: 'NIFTY08SEP2623850PE', exchange: 'NFO' },
    { symbol: 'NIFTY', exchange: 'NSE_INDEX' },
  ],
  market: MARKET,
}

/** A short leg, so the sum has to respect the sign rather than just add. */
const BASIS = {
  ...STRADDLE,
  structure: 'basis',
  label: 'NIFTY 29SEP26 basis',
  summary: 'The future over the spot, per unit.',
  legs: [
    {
      ...CALL,
      symbol: 'NIFTY29SEP26FUT',
      segment: 'FUTURE',
      role: 'named',
      option_type: undefined,
      strike: undefined,
      seed: { ltp: 24000.0, prev_close: 23990.0 },
    },
    {
      ...CALL,
      symbol: 'NIFTY',
      exchange: 'NSE_INDEX',
      segment: 'SPOT',
      side: 'SELL',
      multiplier: -1,
      role: 'spot',
      option_type: undefined,
      strike: undefined,
      lot_size: undefined,
      seed: { ltp: 23873.45, prev_close: 23914.45 },
    },
  ],
  atm: undefined,
  lot_size: undefined,
  subscribe: [
    { symbol: 'NIFTY29SEP26FUT', exchange: 'NFO' },
    { symbol: 'NIFTY', exchange: 'NSE_INDEX' },
  ],
}

beforeEach(() => {
  feed.reset()
  BUDGET.reset()
})

describe('LiveComboCard value', () => {
  it('shows the signed sum of exactly the legs printed under it', () => {
    render(<LiveComboCard spec={STRADDLE} source="quotes_service" />)

    // 120.50 + 95.25, and both terms are on screen to be checked by eye.
    expect(screen.getByText('215.75')).toBeInTheDocument()
    expect(screen.getByText('120.50')).toBeInTheDocument()
    expect(screen.getByText('95.25')).toBeInTheDocument()
    expect(screen.getByText('NIFTY08SEP2623850CE')).toBeInTheDocument()
    expect(screen.getByText('NIFTY08SEP2623850PE')).toBeInTheDocument()

    // The session move, from each leg's own served previous close: the same
    // expression evaluated at yesterday's closes, 118.00 + 99.50.
    expect(screen.getByText('-1.75 (0.80%)')).toBeInTheDocument()
    // Per unit, and what that is in money.
    expect(screen.getByText(/One lot of 75 is 16,181.25/)).toBeInTheDocument()
  })

  it('subtracts a short leg rather than adding it', () => {
    render(<LiveComboCard spec={BASIS} />)

    // 24,000.00 less 23,873.45, which is the only answer that is a basis.
    expect(screen.getByText('126.55')).toBeInTheDocument()
    expect(screen.getByText('-1')).toBeInTheDocument()
    expect(screen.getByText('SELL')).toBeInTheDocument()
  })

  it('adds the constant a synthetic is quoted against', () => {
    render(
      <LiveComboCard
        spec={{
          ...STRADDLE,
          structure: 'synthetic',
          legs: [CALL, { ...PUT, side: 'SELL', multiplier: -1 }],
          formula: { ...STRADDLE.formula, constant: 23850 },
        }}
      />
    )

    // 23850 + 120.50 - 95.25. Null would have been zero; 23850 is not.
    expect(screen.getByText('23,875.25')).toBeInTheDocument()
  })

  it('moves the headline by exactly what the leg moved', () => {
    render(<LiveComboCard spec={STRADDLE} />)
    expect(screen.getByText('215.75')).toBeInTheDocument()

    act(() => {
      feed.push('NIFTY08SEP2623850CE', 'NFO', { ltp: 130.5 })
    })

    // The call rose ten rupees, so the straddle did.
    expect(screen.getByText('225.75')).toBeInTheDocument()
    expect(screen.getByText('130.50')).toBeInTheDocument()
    expect(screen.queryByText('215.75')).toBeNull()
  })

  it('is only as live as its stalest leg', () => {
    render(<LiveComboCard spec={STRADDLE} />)
    act(() => {
      feed.push('NIFTY08SEP2623850CE', 'NFO', { ltp: 130.5 })
    })

    // One leg ticked and one did not, so the number built from both is still
    // a snapshot and is labelled as one.
    const value = screen.getByText('225.75').closest('div') as HTMLElement
    expect(within(value).getByText(/snapshot 2026-09-03 12:44 IST/)).toBeInTheDocument()
  })

  it('withholds the value when a leg has no price at all', () => {
    render(
      <LiveComboCard spec={{ ...STRADDLE, legs: [CALL, { ...PUT, seed: { prev_close: 99.5 } }] }} />
    )

    // Counting the missing leg as zero would print 120.50, which reads as a
    // real number and is wrong by a whole leg.
    expect(screen.getByText('No value yet: 1 of 2 legs have no price.')).toBeInTheDocument()
    expect(screen.queryByText('215.75')).toBeNull()
    expect(screen.getByText('no price')).toBeInTheDocument()
  })
})

describe('LiveComboCard roll', () => {
  it('says the strike is no longer at the money once spot walks past half an interval', () => {
    render(<LiveComboCard spec={STRADDLE} />)
    // 23,873.45 is 23.45 from the strike, inside the 25 point threshold.
    expect(screen.queryByText(/no longer the at the money strike/)).toBeNull()

    act(() => {
      feed.push('NIFTY', 'NSE_INDEX', { ltp: 23920 })
    })

    expect(screen.getByText(/23,850 is no longer the at the money strike/)).toBeInTheDocument()
    // And it keeps showing this combination rather than relabelling it or
    // quietly resubscribing to a different pair of contracts.
    expect(screen.getByText('NIFTY 08SEP26 23850 straddle')).toBeInTheDocument()
    expect(feed.live()).toContain('NFO:NIFTY08SEP2623850CE:Quote')
    expect(feed.live()).toHaveLength(3)
  })

  it('shows the drift without the stale label warning when nothing claimed the money', () => {
    render(
      <LiveComboCard
        spec={{
          ...STRADDLE,
          structure: 'strangle',
          label: 'NIFTY 08SEP26 strangle',
          atm: { ...STRADDLE.atm, claims_atm: false },
        }}
      />
    )
    act(() => {
      feed.push('NIFTY', 'NSE_INDEX', { ltp: 23920 })
    })

    expect(screen.queryByText(/no longer the at the money strike/)).toBeNull()
    expect(screen.getByText(/Spot has moved to 23,920.00/)).toBeInTheDocument()
  })
})

describe('LiveComboCard subscriptions', () => {
  it('subscribes every leg and the spot in Quote, and releases them on unmount', () => {
    const view = render(<LiveComboCard spec={STRADDLE} />)

    expect(feed.live()).toEqual([
      'NFO:NIFTY08SEP2623850CE:Quote',
      'NFO:NIFTY08SEP2623850PE:Quote',
      'NSE_INDEX:NIFTY:Quote',
    ])

    view.unmount()

    expect(feed.live()).toEqual([])
    expect(feed.closed).toHaveLength(3)
  })

  it('says it is not connected rather than showing a still value as live', () => {
    render(<LiveComboCard spec={STRADDLE} />)
    act(() => {
      feed.setState({ isConnected: false, isAuthenticated: false })
    })

    expect(screen.getByText('Not connected')).toBeInTheDocument()
    expect(screen.getByText(/nothing here is moving/)).toBeInTheDocument()
  })

  it('recomputes the session against the clock rather than trusting is_open', () => {
    render(
      <LiveComboCard
        spec={{
          ...STRADDLE,
          market: {
            ...MARKET,
            exchanges: MARKET.exchanges.map((row) => ({
              ...row,
              opens_at: Date.now() - 5 * HOUR,
              closes_at: Date.now() - 2 * HOUR,
            })),
          },
        }}
      />
    )

    expect(screen.getByText('Closed')).toBeInTheDocument()
    expect(screen.getByText(/Market closed/)).toBeInTheDocument()
  })
})

describe('LiveComboCard malformed frames', () => {
  it.each([
    ['null', null],
    ['a string', 'straddle'],
    ['an empty object', {}],
    ['no legs', { ...STRADDLE, legs: [] }],
    ['legs of the wrong shape', { ...STRADDLE, legs: [1, 'x', null] }],
    ['a leg with no multiplier', { ...STRADDLE, legs: [{ ...CALL, multiplier: undefined }] }],
    ['a formula of the wrong shape', { ...STRADDLE, formula: 'add them up' }],
    ['sections of the wrong shape', { ...STRADDLE, spot: 3, atm: [], market: 'open', seed: 9 }],
  ])('renders rather than throwing for %s', (_name, value) => {
    expect(() => render(<LiveComboCard spec={value} title="Combination" />)).not.toThrow()
  })

  it('says so when the frame carried no usable leg', () => {
    render(<LiveComboCard spec={{ ...STRADDLE, legs: [] }} title="NIFTY straddle" />)

    expect(screen.getByText(/could not be drawn/)).toBeInTheDocument()
    expect(feed.live()).toEqual([])
  })
})
