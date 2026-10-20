import { describe, expect, it } from 'vitest'
import { lookbackDays } from './intervals'

describe('custom chart initial history', () => {
  it('gives quarter, year and multi-day charts enough history to render several candles', () => {
    expect(lookbackDays('Q')).toBeGreaterThanOrEqual(3650)
    expect(lookbackDays('3M')).toBe(lookbackDays('Q'))
    expect(lookbackDays('Y')).toBeGreaterThanOrEqual(10 * 365)
    expect(lookbackDays('2D')).toBeGreaterThanOrEqual(3 * 365)
    expect(lookbackDays('100000Y')).toBeLessThanOrEqual(30 * 365)
  })
  it('preserves native defaults and equivalent day/week tokens', () => {
    expect(['1m', '5m', '15m', '1h', 'D', 'W', 'M'].map(lookbackDays)).toEqual([
      7, 30, 60, 180, 1095, 1825, 3650,
    ])
    expect(lookbackDays('1D')).toBe(lookbackDays('D'))
    expect(lookbackDays('1W')).toBe(lookbackDays('W'))
  })
})
