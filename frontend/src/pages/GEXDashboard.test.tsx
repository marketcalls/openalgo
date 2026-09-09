import { describe, expect, it } from 'vitest'
import { formatNumber } from './GEXDashboard'

describe('formatNumber', () => {
  it('abbreviates large positive values with Cr/L/K suffixes', () => {
    expect(formatNumber(444071)).toBe('4.4L')
    expect(formatNumber(270000)).toBe('2.7L')
    expect(formatNumber(15000000)).toBe('1.5Cr')
    expect(formatNumber(1500)).toBe('1.5K')
  })

  it('abbreviates large negative values the same way, keeping the sign', () => {
    expect(formatNumber(-444071)).toBe('-4.4L')
    expect(formatNumber(-259693)).toBe('-2.6L')
    expect(formatNumber(-254946)).toBe('-2.5L')
    expect(formatNumber(-15000000)).toBe('-1.5Cr')
    expect(formatNumber(-1500)).toBe('-1.5K')
  })

  it('leaves small values (below 1000 in magnitude) as plain integers', () => {
    expect(formatNumber(500)).toBe('500')
    expect(formatNumber(-500)).toBe('-500')
    expect(formatNumber(0)).toBe('0')
  })
})
