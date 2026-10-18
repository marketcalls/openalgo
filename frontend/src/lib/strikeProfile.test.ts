import { describe, expect, it } from 'vitest'
import {
  columnTotal,
  expiryPeaks,
  formatExposure,
  nearestStrikeIndex,
  rangeCovered,
  shadeStrength,
  shortExpiryLabel,
  toApiExpiry,
  visibleStrikeIndexes,
} from './strikeProfile'

describe('formatExposure', () => {
  it('writes values the way the grid reads', () => {
    expect(formatExposure(5234)).toBe('5.2K')
    expect(formatExposure(808.4)).toBe('808')
    expect(formatExposure(88.64)).toBe('88.6')
    expect(formatExposure(0.5)).toBe('0.5')
    expect(formatExposure(-3012)).toBe('-3.0K')
    expect(formatExposure(-34.6)).toBe('-34.6')
  })

  it('adds a plus only when asked, and never signs a zero', () => {
    expect(formatExposure(4200, true)).toBe('+4.2K')
    expect(formatExposure(-4200, true)).toBe('-4.2K')
    expect(formatExposure(0.01, true)).toBe('0.0')
    expect(formatExposure(-0.01)).toBe('0.0')
  })
})

describe('expiry codes', () => {
  it('converts the listing format to the API format', () => {
    expect(toApiExpiry('28-AUG-2026')).toBe('28AUG26')
    expect(toApiExpiry('28-aug-26')).toBe('28AUG26')
  })

  it('labels a column with day and month', () => {
    expect(shortExpiryLabel('03NOV26')).toBe('3 Nov')
    expect(shortExpiryLabel('bad')).toBe('bad')
  })
})

describe('strike rows', () => {
  const strikes = [22800, 22900, 23000, 23100, 23200, 23300, 23400, 23500, 23600]

  it('keeps strikes inside the range, highest first', () => {
    const rows = visibleStrikeIndexes(strikes, 23150, 1)
    expect(rows.map((i) => strikes[i])).toEqual([23300, 23200, 23100, 23000])
  })

  it('shows every strike for the All range', () => {
    expect(visibleStrikeIndexes(strikes, 23150, null)).toHaveLength(strikes.length)
  })

  it('finds the strike nearest spot', () => {
    expect(strikes[nearestStrikeIndex(strikes, 23160)]).toBe(23200)
    expect(nearestStrikeIndex([], 23160)).toBe(-1)
  })

  it('knows when the loaded window already covers a range', () => {
    expect(rangeCovered(2, 5)).toBe(true)
    expect(rangeCovered(10, 5)).toBe(false)
    expect(rangeCovered(null, 10)).toBe(false)
    expect(rangeCovered(10, null)).toBe(true)
  })
})

describe('expiryPeaks', () => {
  const values = [12, -80, 300, null, -50, 90]
  const rows = [0, 1, 2, 3, 4, 5]

  it('marks the highest and the most negative cell for All', () => {
    expect([...expiryPeaks(values, rows, 'all')].sort()).toEqual([1, 2])
  })

  it('leaves out a weak opposite side for All', () => {
    // -50 is under a fifth of 300, so only the positive peak is marked
    expect([...expiryPeaks([12, -50, 300], [0, 1, 2], 'all')]).toEqual([2])
    // the rule is symmetric: a strong negative column drops a weak positive
    expect([...expiryPeaks([10, -300, 70], [0, 1, 2], 'all')].sort()).toEqual([1, 2])
    expect([...expiryPeaks([10, -300, 50], [0, 1, 2], 'all')]).toEqual([1])
  })

  it('marks only the larger magnitude for Max', () => {
    expect([...expiryPeaks(values, rows, 'max')]).toEqual([2])
    expect([...expiryPeaks([10, -50], [0, 1], 'max')]).toEqual([1])
  })

  it('marks nothing for Off, and only looks at the rows shown', () => {
    expect(expiryPeaks(values, rows, 'off').size).toBe(0)
    expect([...expiryPeaks(values, [4, 5], 'all')].sort()).toEqual([4, 5])
  })

  it('marks a one-sided column once', () => {
    expect([...expiryPeaks([1, 2, 3], [0, 1, 2], 'all')]).toEqual([2])
  })
})

describe('columnTotal and shading', () => {
  it('sums the rows shown and returns null when the expiry lists none of them', () => {
    expect(columnTotal([1, 2, null, 4], [0, 1, 2])).toBe(3)
    expect(columnTotal([null, null], [0, 1])).toBeNull()
  })

  it('shades by the square root of the share of the maximum', () => {
    expect(shadeStrength(25, 100)).toBeCloseTo(0.5)
    expect(shadeStrength(-100, 100)).toBe(1)
    expect(shadeStrength(500, 100)).toBe(1)
  })
})
