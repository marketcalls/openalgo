import { describe, expect, it } from 'vitest'
import type { PnlHistoryClosedTrade, PnlHistoryOpenPosition } from '@/api/trading'
import { EMPTY_TABLE_FILTERS } from '@/hooks/usePnlFilters'
import type { CurveData } from './pnlCurve'
import { buildPnlModel } from './pnlModel'

const trade = (over: Partial<PnlHistoryClosedTrade>): PnlHistoryClosedTrade => ({
  symbol: 'ABC',
  exchange: 'NSE',
  product: 'CNC',
  entry_action: 'BUY',
  quantity: 10,
  entry_price: 100,
  entry_timestamp: '2026-05-04T10:00:00',
  exit_price: 110,
  exit_timestamp: '2026-05-05T10:00:00',
  realized_pnl: 100,
  strategy: 'EBP',
  ...over,
})

const openPos = (over: Partial<PnlHistoryOpenPosition>): PnlHistoryOpenPosition => ({
  symbol: 'XYZ',
  exchange: 'NSE',
  product: 'CNC',
  action: 'BUY',
  quantity: 5,
  average_price: 200,
  source: 'holdings',
  strategy: 'EBP',
  ltp: 210,
  unrealized_pnl: 50,
  ...over,
})

const base = {
  closedTrades: [
    trade({ symbol: 'ABC', realized_pnl: 100, strategy: 'EBP' }),
    trade({
      symbol: 'DEF',
      realized_pnl: -30,
      strategy: null,
      exit_timestamp: '2026-05-06T10:00:00',
    }),
    trade({
      symbol: 'GHI',
      exchange: 'BSE',
      realized_pnl: 20,
      strategy: 'EBP',
      exit_timestamp: '2026-05-06T11:00:00',
    }),
  ],
  openPositions: [openPos({}), openPos({ symbol: 'JKL', strategy: null, unrealized_pnl: -10 })],
  unrealizedAvailable: true,
  curve: null,
  segment: 'all',
  pnlType: 'realized' as const,
  filters: EMPTY_TABLE_FILTERS,
  maxStrategies: 8,
}

describe('buildPnlModel (no equity curve)', () => {
  it('lists Untagged as a strategy option next to the tagged ones', () => {
    const model = buildPnlModel(base)
    expect(model.options.strategies).toEqual(['EBP', 'Untagged'])
    expect(model.options.exchanges).toEqual(['BSE', 'NSE'])
  })

  it('sums realized by the day a lot closed and splits realized from unrealized', () => {
    const model = buildPnlModel(base)
    expect(model.series.dates).toEqual(['2026-05-05', '2026-05-06'])
    expect(model.series.total).toEqual([100, -10])
    expect(model.split).toEqual({ realized: 90, unrealized: 40 })
  })

  it('narrows everything by one strategy, and Untagged is selectable', () => {
    const ebp = buildPnlModel({
      ...base,
      filters: { ...EMPTY_TABLE_FILTERS, strategies: ['EBP'] },
    })
    expect(ebp.split.realized).toBe(120)
    expect(ebp.lots.map((t) => t.symbol)).toEqual(['ABC', 'GHI'])
    expect(ebp.open.map((p) => p.symbol)).toEqual(['XYZ'])

    const untagged = buildPnlModel({
      ...base,
      filters: { ...EMPTY_TABLE_FILTERS, strategies: ['Untagged'] },
    })
    expect(untagged.split.realized).toBe(-30)
    expect(untagged.open.map((p) => p.symbol)).toEqual(['JKL'])
  })

  it('narrows by symbol, exchange and product', () => {
    expect(
      buildPnlModel({ ...base, filters: { ...EMPTY_TABLE_FILTERS, symbol: 'de' } }).lots
    ).toHaveLength(1)
    expect(
      buildPnlModel({ ...base, filters: { ...EMPTY_TABLE_FILTERS, exchanges: ['BSE'] } }).split
        .realized
    ).toBe(20)
    expect(
      buildPnlModel({ ...base, filters: { ...EMPTY_TABLE_FILTERS, products: ['MIS'] } }).lots
    ).toHaveLength(0)
  })

  it('splits realized and unrealized per strategy', () => {
    const model = buildPnlModel(base)
    expect(model.perStrategy.get('EBP')).toEqual({ realized: 120, unrealized: 50 })
    expect(model.perStrategy.get('Untagged')).toEqual({ realized: -30, unrealized: -10 })
    const noLive = buildPnlModel({ ...base, unrealizedAvailable: false })
    expect(noLive.perStrategy.get('EBP')?.unrealized).toBeNull()
  })

  it('has no unrealized when the end date is not today', () => {
    expect(buildPnlModel({ ...base, unrealizedAvailable: false }).split.unrealized).toBeNull()
  })
})

describe('buildPnlModel (equity curve)', () => {
  const curve: CurveData = {
    dates: ['2026-05-05', '2026-05-06', '2026-05-07'],
    by_strategy: {
      EBP: { realized: [0, 0, 200], unrealized: [50, 150, 0] },
      Untagged: { realized: [0, 0, 0], unrealized: [30, 30, 30] },
    },
    basis: 'actual_cost',
    base_date: '2026-05-04',
    notes: { orphan_sells: [], missing_close: [], missing_base: [] },
  }
  const input = { ...base, curve, segment: 'equity', pnlType: 'combined' as const }

  it('follows the P&L type and the strategy selection', () => {
    const all = buildPnlModel(input)
    expect(all.hasCurve).toBe(true)
    expect(all.series.total).toEqual([80, 100, 50])
    expect(all.strategyNames).toEqual(['EBP', 'Untagged'])
    expect(all.split).toEqual({ realized: 200, unrealized: 30 })

    const ebp = buildPnlModel({
      ...input,
      filters: { ...EMPTY_TABLE_FILTERS, strategies: ['EBP'] },
    })
    expect(ebp.series.total).toEqual([50, 100, 50])
    expect(ebp.split).toEqual({ realized: 200, unrealized: 0 })
    // The chips' own totals still see every strategy.
    expect(ebp.allSeries.total).toEqual([80, 100, 50])
  })

  it('gives realized and the open level per selected strategy', () => {
    const all = buildPnlModel(input)
    expect(all.perStrategy.get('EBP')).toEqual({ realized: 200, unrealized: 0 })
    expect(all.perStrategy.get('Untagged')).toEqual({ realized: 0, unrealized: 30 })
    const ebp = buildPnlModel({
      ...input,
      filters: { ...EMPTY_TABLE_FILTERS, strategies: ['EBP'] },
    })
    expect(Array.from(ebp.perStrategy.keys())).toEqual(['EBP'])
  })

  it('says when exchange or product cannot narrow the curve', () => {
    const model = buildPnlModel({
      ...input,
      filters: { ...EMPTY_TABLE_FILTERS, exchanges: ['NSE'] },
    })
    expect(model.curveIgnoresFilters).toBe(true)
  })
})
