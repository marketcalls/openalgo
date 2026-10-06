import { describe, expect, it } from 'vitest'
import type { AttributedRow, StrategyAttribution } from '@/api/trading'
import type { Holding, Position } from '@/types/trading'
import { applyM2m, groupByStrategy, narrowHoldingsToStrategy } from './strategyAttribution'

const pos = (over: Partial<Position> = {}): Position => ({
  symbol: 'NIFTYX',
  exchange: 'NFO',
  product: 'NRML',
  quantity: -150,
  average_price: 100,
  ltp: 90,
  pnl: 1500,
  pnlpercent: 10,
  ...over,
})

const attribution = (rows: Partial<AttributedRow>[]): StrategyAttribution => ({
  kind: 'positions',
  strategies: [],
  rows: rows.map((r) => ({
    symbol: 'NIFTYX',
    exchange: 'NFO',
    product: 'NRML',
    quantity: 0,
    average_price: 0,
    slices: [],
    mismatch: false,
    mismatch_reason: null,
    leftover_owner: null,
    ...r,
  })),
})

const slice = (strategy: string, quantity: number, average_price: number, today = 0) => ({
  strategy,
  quantity,
  average_price,
  today_realized_pnl: today,
  attributed: strategy !== 'Unattributed',
})

const total = (groups: Record<string, { pnl: number }[]>) =>
  Object.values(groups)
    .flat()
    .reduce((sum, r) => sum + r.pnl, 0)

describe('groupByStrategy', () => {
  it('splits one broker row across strategies and keeps the broker P&L total', () => {
    const groups = groupByStrategy(
      [pos()],
      attribution([{ slices: [slice('A', -100, 100), slice('B', -50, 100)] }])
    )
    expect(Object.keys(groups).sort()).toEqual(['A', 'B'])
    expect(groups.A[0].quantity).toBe(-100)
    expect(groups.A[0].pnl).toBeCloseTo(1000)
    expect(groups.B[0].pnl).toBeCloseTo(500)
    expect(total(groups)).toBeCloseTo(1500)
  })

  it('shows every row as Unattributed when there is no attribution', () => {
    const groups = groupByStrategy([pos()], null)
    expect(Object.keys(groups)).toEqual(['Unattributed'])
    expect(groups.Unattributed[0].pnl).toBe(1500)
  })

  it('keeps a flat strategy leg realized P&L and puts the rest on Unattributed', () => {
    const groups = groupByStrategy(
      [pos({ quantity: 0, ltp: 0, pnl: 1800 })],
      attribution([{ slices: [slice('IC', 0, 0, 1250)] }])
    )
    expect(groups.IC[0].pnl).toBe(1250)
    expect(groups.Unattributed[0].pnl).toBeCloseTo(550)
    expect(total(groups)).toBeCloseTo(1800)
  })

  it('folds the unexplained P&L into an existing Unattributed remainder slice', () => {
    const groups = groupByStrategy(
      [pos({ quantity: -150, pnl: 1700 })],
      attribution([{ slices: [slice('A', -100, 100), slice('Unattributed', -50, 100)] }])
    )
    expect(groups.Unattributed).toHaveLength(1)
    expect(groups.Unattributed[0].quantity).toBe(-50)
    expect(total(groups)).toBeCloseTo(1700)
  })

  it('does not mark slices without a live price, only realized P&L', () => {
    const groups = groupByStrategy(
      [pos({ ltp: undefined, pnl: 400 })],
      attribution([{ slices: [slice('A', -150, 100, 100)] }])
    )
    expect(groups.A[0].pnl).toBe(100)
    expect(total(groups)).toBeCloseTo(400)
  })
})

describe('flat position closed outside the book', () => {
  it('gives the realized P&L to the one strategy the book still shows holding it', () => {
    const groups = groupByStrategy(
      [pos({ quantity: 0, ltp: 0.4, pnl: 1088.75 })],
      attribution([{ slices: [], leftover_owner: 'IronCondor' }])
    )
    expect(Object.keys(groups)).toEqual(['IronCondor'])
    expect(groups.IronCondor[0].pnl).toBeCloseTo(1088.75)
    expect(groups.IronCondor[0].quantity).toBe(0)
  })

  it('keeps it Unattributed when no single strategy owns it', () => {
    const groups = groupByStrategy(
      [pos({ quantity: 0, ltp: 0.4, pnl: 1088.75 })],
      attribution([{ slices: [], leftover_owner: null }])
    )
    expect(Object.keys(groups)).toEqual(['Unattributed'])
  })

  it('adds to the owner row when that strategy also realized P&L today', () => {
    const groups = groupByStrategy(
      [pos({ quantity: 0, ltp: 0, pnl: 1500 })],
      attribution([{ slices: [slice('IC', 0, 0, 1000)], leftover_owner: 'IC' }])
    )
    expect(groups.IC).toHaveLength(1)
    expect(groups.IC[0].pnl).toBeCloseTo(1500)
  })
})

describe('carried position the broker values differently from the fills', () => {
  it('keeps the whole difference under the one strategy that traded it, not Unattributed', () => {
    // ExpiryFade 22350PE NRML: fills give -5616, Kite reports -11544 for the row.
    const groups = groupByStrategy(
      [pos({ product: 'NRML', quantity: 0, ltp: 0.05, pnl: -11544 })],
      attribution([
        {
          product: 'NRML',
          slices: [slice('ExpiryFade', 0, 0, -5616)],
          leftover_owner: 'ExpiryFade',
        },
      ])
    )
    expect(Object.keys(groups)).toEqual(['ExpiryFade'])
    expect(groups.ExpiryFade).toHaveLength(1)
    expect(groups.ExpiryFade[0].pnl).toBeCloseTo(-11544)
  })
})

describe('applyM2m', () => {
  const withM2m = (r: Partial<AttributedRow>): StrategyAttribution =>
    attribution([{ m2m_available: true, ...r }])

  it("replaces the broker's P&L with today's M2M for a carried row", () => {
    // acc1 22350PE NRML: Kite pnl -11544, today's M2M -4377.75, carried 195 from a close of 22.7.
    const { positions, fallbackRows } = applyM2m(
      [pos({ product: 'NRML', quantity: 0, ltp: 0.05, pnl: -11544 })],
      withM2m({
        product: 'NRML',
        m2m_fixed: -4377.75,
        overnight_quantity: 195,
        prev_close: 22.7,
      })
    )
    expect(fallbackRows).toBe(0)
    expect(positions[0].pnl).toBeCloseTo(-4377.75)
  })

  it('keeps the move live: the fixed part plus quantity times the current price', () => {
    const { positions } = applyM2m(
      [pos({ quantity: 10, ltp: 110, pnl: 0 })],
      withM2m({ m2m_fixed: -1000, overnight_quantity: 0 })
    )
    expect(positions[0].pnl).toBeCloseTo(100)
  })

  it('measures percent from yesterday close for a carried row and from entry otherwise', () => {
    const carried = applyM2m(
      [pos({ quantity: 10, ltp: 112, average_price: 90 })],
      withM2m({ m2m_fixed: -1100, overnight_quantity: 10, prev_close: 110 })
    ).positions[0]
    expect(carried.pnl).toBeCloseTo(20)
    expect(carried.pnlpercent).toBeCloseTo((20 / (10 * 110)) * 100)
    const fresh = applyM2m(
      [pos({ quantity: 10, ltp: 105, average_price: 100 })],
      withM2m({ m2m_fixed: -1000, overnight_quantity: 0 })
    ).positions[0]
    expect(fresh.pnlpercent).toBeCloseTo((50 / 1000) * 100)
  })

  it('keeps the broker figure for a row M2M could not be computed for', () => {
    const { positions, fallbackRows } = applyM2m(
      [pos({ pnl: 1234 })],
      attribution([{ m2m_available: false, m2m_reason: 'previous close unavailable' }])
    )
    expect(fallbackRows).toBe(1)
    expect(positions[0].pnl).toBe(1234)
  })

  it('falls back for every row when there is no attribution at all', () => {
    const { positions, fallbackRows } = applyM2m([pos({ pnl: 5 }), pos({ pnl: 6 })], null)
    expect(fallbackRows).toBe(2)
    expect(positions.map((p) => p.pnl)).toEqual([5, 6])
  })
})

describe('groupByStrategy in M2M mode', () => {
  it('gives a flat carried row to the one strategy that traded it', () => {
    const groups = groupByStrategy(
      [pos({ product: 'NRML', quantity: 0, pnl: -4377.75 })],
      attribution([
        {
          product: 'NRML',
          slices: [slice('ExpiryFade', 0, 0, -5616)],
          leftover_owner: 'ExpiryFade',
        },
      ]),
      'm2m'
    )
    expect(Object.keys(groups)).toEqual(['ExpiryFade'])
    expect(groups.ExpiryFade[0].pnl).toBeCloseTo(-4377.75)
  })

  it('splits an open row between its strategies by quantity and keeps the total', () => {
    const groups = groupByStrategy(
      [pos({ quantity: -150, pnl: 900 })],
      attribution([{ slices: [slice('A', -100, 100), slice('B', -50, 100)] }]),
      'm2m'
    )
    expect(groups.A[0].pnl).toBeCloseTo(600)
    expect(groups.B[0].pnl).toBeCloseTo(300)
    expect(total(groups)).toBeCloseTo(900)
  })

  it('leaves a flat row Unattributed when no single strategy owns it', () => {
    const groups = groupByStrategy(
      [pos({ quantity: 0, pnl: 50 })],
      attribution([{ slices: [], leftover_owner: null }]),
      'm2m'
    )
    expect(Object.keys(groups)).toEqual(['Unattributed'])
    expect(groups.Unattributed[0].pnl).toBe(50)
  })
})

describe('narrowHoldingsToStrategy', () => {
  const holding: Holding = {
    symbol: 'INFY',
    exchange: 'NSE',
    product: 'CNC',
    quantity: 60,
    t1_quantity: 10,
    pledged_quantity: 30,
    average_price: 1500,
    ltp: 1600,
    pnl: 10000,
    pnlpercent: 6.67,
  }
  const attr = (slices: ReturnType<typeof slice>[]): StrategyAttribution => ({
    kind: 'holdings',
    strategies: [],
    rows: [
      {
        symbol: 'INFY',
        exchange: 'NSE',
        product: 'CNC',
        quantity: 100,
        average_price: 1500,
        slices,
        mismatch: false,
        mismatch_reason: null,
        leftover_owner: null,
      },
    ],
  })

  it('keeps only the strategy share at its own cost, marked to the live price', () => {
    const [row] = narrowHoldingsToStrategy(
      [holding],
      attr([slice('EBP', 40, 1550), slice('Unattributed', 60, 1466.67)]),
      'EBP'
    )
    expect(row.quantity).toBe(40)
    expect(row.t1_quantity).toBe(0)
    expect(row.pledged_quantity).toBe(0)
    expect(row.average_price).toBe(1550)
    expect(row.pnl).toBeCloseTo(2000)
    expect(row.pnlpercent).toBeCloseTo((2000 / (40 * 1550)) * 100)
  })

  it('drops holdings the strategy does not own', () => {
    expect(narrowHoldingsToStrategy([holding], attr([slice('Other', 100, 1500)]), 'EBP')).toEqual(
      []
    )
  })

  it('returns nothing without an attribution', () => {
    expect(narrowHoldingsToStrategy([holding], null, 'EBP')).toEqual([])
  })
})
