import { registerInterval } from 'openalgo-charts'
import { describe, expect, it } from 'vitest'
import { replayTiming } from './replayTiming'

const bar = (time: number) => ({ time, open: 1, high: 2, low: 0, close: 1 })
const utc = (value: string) => Date.parse(value) / 1000

describe('workspace replay availability', () => {
  it('uses each opening plus the intraday duration, including session offsets', () => {
    const start = utc('2026-09-18T03:45:00Z')
    const timing = replayTiming('1h', 'Asia/Kolkata', '15m')
    expect(timing.barEndTime(bar(start), 0)).toBe(start + 3600)
    expect(timing.subBarEndTime?.(bar(start), 0)).toBe(start + 900)
    expect(timing.barEndTime(bar(start), 100)).toBe(start + 3600)
  })

  it.each(['D', '1d'])('keeps %s on calendar dates across short and long days', (interval) => {
    const timing = replayTiming(interval, 'America/New_York')
    expect(timing.barEndTime(bar(utc('2026-03-08T05:00:00Z')), 0)).toBe(utc('2026-03-09T04:00:00Z'))
    expect(timing.barEndTime(bar(utc('2026-11-01T04:00:00Z')), 0)).toBe(utc('2026-11-02T05:00:00Z'))
  })

  it.each(['W', '1w', '1wk'])('preserves the local opening hour for %s', (interval) => {
    const timing = replayTiming(interval, 'America/New_York')
    expect(timing.barEndTime(bar(utc('2026-03-06T14:30:00Z')), 0)).toBe(utc('2026-03-13T13:30:00Z'))
  })

  it.each([
    'M',
    '1M',
    '1mo',
  ])('handles the monthly alias %s without guessing minutes', (interval) => {
    const timing = replayTiming(interval, 'Asia/Kolkata')
    expect(timing.barEndTime(bar(utc('2024-01-31T18:30:00Z')), 0)).toBe(utc('2024-02-29T18:30:00Z'))
    expect(replayTiming('1m', 'Asia/Kolkata').barEndTime(bar(100), 0)).toBe(160)
  })

  it('honors a registered calendar and captures its rule before unregistration', () => {
    const dispose = registerInterval({
      code: 'replay-quarter',
      bucketing: { mode: 'calendar', unit: 'quarter', timezone: 'Asia/Kolkata' },
    })
    const timing = replayTiming('replay-quarter', 'UTC')
    dispose()
    expect(timing.barEndTime(bar(utc('2026-06-30T18:30:00Z')), 0)).toBe(utc('2026-09-30T18:30:00Z'))
  })

  it('does not invent availability for unknown or count-driven intervals', () => {
    const dispose = registerInterval({
      code: 'replay-ticks',
      bucketing: { mode: 'ticks', count: 10 },
    })
    try {
      expect(() => replayTiming('replay-ticks', 'UTC')).toThrow(/time-based/i)
      expect(() => replayTiming('unlisted', 'UTC')).toThrow(/interval/i)
      expect(() => replayTiming('0m', 'UTC')).toThrow(/interval/i)
      expect(() => replayTiming('1m', 'UTC', 'unlisted')).toThrow(/interval/i)
    } finally {
      dispose()
    }
  })

  it('rejects invalid zones and bar timestamps instead of changing time policy', () => {
    expect(() => replayTiming('D', 'Unlisted/Zone')).toThrow(/timezone/i)
    const timing = replayTiming('1m', 'UTC')
    expect(() => timing.barEndTime(bar(Number.NaN), 0)).toThrow(/time/i)
    expect(timing.subBarEndTime).toBeUndefined()
  })
})
