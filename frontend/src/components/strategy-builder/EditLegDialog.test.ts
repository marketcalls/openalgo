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
}

describe('EditLegDialog payoff market-data invalidation', () => {
  it.each([
    ['strike', { strike: 24500 }],
    ['option type', { optionType: 'PE' as const }],
    ['expiry', { expiry: '11AUG26' }],
  ])('PG-13 clears stale IV when %s changes', (_label, change) => {
    expect(invalidateIvWhenContractChanges(original, { ...original, ...change }).iv).toBe(0)
  })

  it('keeps IV for quantity, side, and entry-price-only edits', () => {
    expect(
      invalidateIvWhenContractChanges(original, {
        ...original,
        side: 'SELL',
        lots: 2,
        price: 101,
      }).iv
    ).toBe(14.2)
  })
})
