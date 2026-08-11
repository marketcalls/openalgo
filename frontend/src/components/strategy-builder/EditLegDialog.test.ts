import { describe, expect, it } from 'vitest'
import type { StrategyLeg } from '@/lib/strategyMath'
import { invalidateIvWhenContractChanges } from './EditLegDialog'

const original: StrategyLeg = {
  id: 'leg-1',
  segment: 'OPTION',
  side: 'BUY',
  lots: 1,
  lotSize: 25,
  expiry: '04AUG26',
  strike: 24000,
  optionType: 'CE',
  price: 100,
  iv: 14.2,
  active: true,
  symbol: 'NIFTY04AUG2624000CE',
  marketGreeks: { delta: 0.5, gamma: 0.01, theta: -2, vega: 4 },
}

describe('EditLegDialog payoff market-data invalidation', () => {
  it.each([
    ['strike', { strike: 24500 }],
    ['option type', { optionType: 'PE' as const }],
    ['expiry', { expiry: '11AUG26' }],
  ])('PG-13 clears stale IV when %s changes', (_label, change) => {
    const result = invalidateIvWhenContractChanges(original, { ...original, ...change })
    expect(result.iv).toBe(0)
    expect(result.marketGreeks).toBeUndefined()
  })

  it('clears the Greek snapshot when the canonical symbol changes', () => {
    const result = invalidateIvWhenContractChanges(original, {
      ...original,
      symbol: 'NIFTY04AUG2624000CE-CANONICAL',
    })

    expect(result.iv).toBe(0)
    expect(result.marketGreeks).toBeUndefined()
  })

  it('keeps IV for quantity, side, and entry-price-only edits', () => {
    expect(
      invalidateIvWhenContractChanges(original, {
        ...original,
        side: 'SELL',
        lots: 2,
        price: 101,
      })
    ).toMatchObject({ iv: 14.2, marketGreeks: original.marketGreeks })
  })
})
