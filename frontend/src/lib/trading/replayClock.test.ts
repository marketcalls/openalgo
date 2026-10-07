import { describe, expect, it } from 'vitest'
import { formatBarStamp } from './replayClock'

// 1 Oct 2026 04:45:30 UTC is 10:15:30 IST.
const T = Date.UTC(2026, 9, 1, 4, 45, 30) / 1000

describe('replay clock', () => {
  it('reads an intraday bar in IST', () => {
    expect(formatBarStamp(T, '5m')).toBe('01 Oct 2026 10:15 IST')
    expect(formatBarStamp(T, '1h')).toBe('01 Oct 2026 10:15 IST')
  })

  it('shows seconds on a seconds chart', () => {
    expect(formatBarStamp(T, '15s')).toBe('01 Oct 2026 10:15:30 IST')
  })

  it('shows only the date for a daily or longer bar', () => {
    expect(formatBarStamp(T, 'D')).toBe('01 Oct 2026')
    expect(formatBarStamp(T, 'W')).toBe('01 Oct 2026')
  })

  it('keeps the time when the interval is unknown, and is empty with no time', () => {
    expect(formatBarStamp(T, '')).toBe('01 Oct 2026 10:15 IST')
    expect(formatBarStamp(null, '5m')).toBe('')
    expect(formatBarStamp(Number.NaN, '5m')).toBe('')
  })
})
