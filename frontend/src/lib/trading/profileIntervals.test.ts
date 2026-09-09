import { describe, expect, it } from 'vitest'
import { profileIntervalSupported, selectProfileInterval } from './profileIntervals'

describe('profile source intervals', () => {
  it('requires intraday bars for session distributions', () => {
    expect(profileIntervalSupported('session-volume-profile', 'D', 30)).toBe(false)
    expect(profileIntervalSupported('session-volume-profile', '1h', 30)).toBe(true)
    expect(profileIntervalSupported('session-volume-profile', '0m', 30)).toBe(false)
  })
  it('rejects bars that straddle TPO blocks or exceed a block', () => {
    expect(profileIntervalSupported('tpo', '1h', 30)).toBe(false)
    expect(profileIntervalSupported('tpo', '20m', 30)).toBe(false)
    expect(profileIntervalSupported('tpo', '15m', 30)).toBe(true)
    expect(profileIntervalSupported('tpo', '30m', 15)).toBe(false)
  })
  it('keeps a valid selection and uses supported 5m bars for a coarse selection', () => {
    const intervals = ['1m', '5m', '15m', '1h', 'D']
    expect(selectProfileInterval('tpo', '15m', 30, intervals)).toBe('15m')
    expect(selectProfileInterval('tpo', 'D', 30, intervals)).toBe('5m')
    expect(selectProfileInterval('tpo', 'D', 30, ['1h', 'D'])).toBeNull()
    expect(selectProfileInterval('tpo', 'D', 30, ['10m', 'D'])).toBe('10m')
  })
})
