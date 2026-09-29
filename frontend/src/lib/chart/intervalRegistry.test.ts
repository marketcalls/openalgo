import { isKnownInterval, registeredIntervals, unregisterInterval } from 'openalgo-charts'
import { afterEach, describe, expect, it } from 'vitest'
import { ensureInterval } from './intervalRegistry'

/**
 * The defect this pins, found while testing the page rather than by any test:
 *
 *   UnknownIntervalError: openalgo-charts: unknown interval "M".
 *
 * The Historify store serves M, Q and Y by aggregating stored daily candles,
 * so the timeframe list offered them. The chart engine has a separate
 * vocabulary whose built-in tokens stop at weeks, and `resolveInterval` throws
 * rather than guessing. The throw came out of a React effect and took the page
 * to its error boundary.
 *
 * Every test here uses the real engine registry. Stubbing it would have let
 * the original bug through, since the whole mistake was believing the engine
 * accepted these codes.
 */

const registered = () => registeredIntervals().map((d) => d.code)

afterEach(() => {
  for (const code of registered()) unregisterInterval(code)
})

describe('ensureInterval', () => {
  it('registers the three calendar timeframes the engine does not ship', () => {
    for (const code of ['M', 'Q', 'Y']) {
      expect(isKnownInterval(code), `${code} before`).toBe(false)
      expect(ensureInterval(code), `${code} ensure`).toBe(true)
      expect(isKnownInterval(code), `${code} after`).toBe(true)
    }
  })

  it('buckets each one by its own calendar unit, not an approximation in seconds', () => {
    // A month is not 30 days and a year is not 365, which is exactly why these
    // cannot be built-in interval tokens.
    ensureInterval('M')
    ensureInterval('Q')
    ensureInterval('Y')
    const byCode = Object.fromEntries(registeredIntervals().map((d) => [d.code, d.bucketing]))
    expect(byCode.M).toMatchObject({ mode: 'calendar', unit: 'month', count: 1 })
    expect(byCode.Q).toMatchObject({ mode: 'calendar', unit: 'quarter', count: 1 })
    expect(byCode.Y).toMatchObject({ mode: 'calendar', unit: 'year', count: 1 })
  })

  it('opens a calendar bar in IST, which decides what day a month starts on', () => {
    ensureInterval('M')
    expect(registeredIntervals()[0].bucketing).toMatchObject({ timezone: 'Asia/Kolkata' })
  })

  it('handles the multiples the custom interval builder can compose', () => {
    for (const code of ['3M', '2Q', '2Y', '12M']) {
      expect(ensureInterval(code), code).toBe(true)
      expect(isKnownInterval(code), code).toBe(true)
    }
    const byCode = Object.fromEntries(registeredIntervals().map((d) => [d.code, d.bucketing]))
    expect(byCode['3M']).toMatchObject({ unit: 'month', count: 3 })
    expect(byCode['2Q']).toMatchObject({ unit: 'quarter', count: 2 })
  })

  it('leaves a built-in token alone rather than shadowing it', () => {
    // A registered code overrides a built-in of the same name, so registering
    // D or W would quietly redefine what the engine already does correctly.
    for (const code of ['1m', '25m', '1h', '4h', 'D', 'W', '2W']) {
      expect(ensureInterval(code), code).toBe(true)
    }
    expect(registered()).toEqual([])
  })

  it('declines a code nothing can resolve instead of registering nonsense', () => {
    // MO is the spelling the replaced page emitted for months, and neither the
    // engine nor the store has ever accepted it.
    for (const code of ['MO', '0M', 'X', '', '   ', '1.5M', '-2Q']) {
      expect(ensureInterval(code), code).toBe(false)
    }
    expect(registered()).toEqual([])
  })

  it('reports a bare unit letter as known, because the engine reads it as one', () => {
    // The two vocabularies disagree here and the engine is the one being asked:
    // it resolves a bare `m` as sixty seconds, the way it reads `D` as one day,
    // while the store's grammar requires a digit and would return nothing. The
    // page never composes this shape, and nothing should start: `composeInterval`
    // always emits a count for minutes and hours.
    expect(ensureInterval('m')).toBe(true)
    expect(registered()).toEqual([])
  })

  it('is idempotent, so repeated selection does not stack registrations', () => {
    ensureInterval('M')
    ensureInterval('M')
    ensureInterval('M')
    expect(registered().filter((c) => c === 'M')).toHaveLength(1)
  })
})
