import { describe, expect, it } from 'vitest'
import { formatFundsAmount, summarizeFunds } from './scalpingFunds'

describe('summarizeFunds', () => {
  it('reads available balance and utilised margin from numbers', () => {
    expect(
      summarizeFunds({
        availablecash: 98765.4,
        collateral: 0,
        m2munrealized: 0,
        m2mrealized: 0,
        utiliseddebits: 1234.6,
      })
    ).toEqual({ available: 98765.4, utilised: 1234.6 })
  })

  it('reads the numeric strings most brokers send', () => {
    const data = { availablecash: '98765.40', utiliseddebits: '1,234.60' } as unknown as Parameters<
      typeof summarizeFunds
    >[0]
    expect(summarizeFunds(data)).toEqual({ available: 98765.4, utilised: 1234.6 })
  })

  it('keeps a negative available balance (margin shortfall)', () => {
    expect(summarizeFunds({ availablecash: -500, utiliseddebits: 2500 })).toEqual({
      available: -500,
      utilised: 2500,
    })
  })

  it('leaves a missing field unknown instead of zero when the other is present', () => {
    expect(summarizeFunds({ availablecash: 1000 })).toEqual({ available: 1000, utilised: null })
    expect(summarizeFunds({ utiliseddebits: 250 })).toEqual({ available: null, utilised: 250 })
  })

  it('leaves an unusable field unknown while keeping the usable one', () => {
    const data = { availablecash: 'n/a', utiliseddebits: '500' } as unknown as Parameters<
      typeof summarizeFunds
    >[0]
    expect(summarizeFunds(data)).toEqual({ available: null, utilised: 500 })
  })

  it('reports both fields unknown when there is no usable figure', () => {
    const unknown = { available: null, utilised: null }
    expect(summarizeFunds(undefined)).toEqual(unknown)
    expect(summarizeFunds(null)).toEqual(unknown)
    expect(summarizeFunds({})).toEqual(unknown)
    const junk = { availablecash: 'n/a', utiliseddebits: '' } as unknown as Parameters<
      typeof summarizeFunds
    >[0]
    expect(summarizeFunds(junk)).toEqual(unknown)
  })
})

describe('formatFundsAmount', () => {
  it('groups digits the Indian way with two decimals', () => {
    expect(formatFundsAmount(1234567.5)).toBe('12,34,567.50')
    expect(formatFundsAmount(0)).toBe('0.00')
    expect(formatFundsAmount(-500)).toBe('-500.00')
  })

  it("shows '-' for an unknown amount", () => {
    expect(formatFundsAmount(null)).toBe('-')
  })
})
