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

  it('treats one missing field as zero when the other is present', () => {
    expect(summarizeFunds({ availablecash: 1000 })).toEqual({ available: 1000, utilised: 0 })
  })

  it('returns null when there is no usable figure, so the header shows a placeholder', () => {
    expect(summarizeFunds(undefined)).toBeNull()
    expect(summarizeFunds(null)).toBeNull()
    expect(summarizeFunds({})).toBeNull()
    const junk = { availablecash: 'n/a', utiliseddebits: '' } as unknown as Parameters<
      typeof summarizeFunds
    >[0]
    expect(summarizeFunds(junk)).toBeNull()
  })
})

describe('formatFundsAmount', () => {
  it('groups digits the Indian way with two decimals', () => {
    expect(formatFundsAmount(1234567.5)).toBe('12,34,567.50')
    expect(formatFundsAmount(0)).toBe('0.00')
    expect(formatFundsAmount(-500)).toBe('-500.00')
  })
})
