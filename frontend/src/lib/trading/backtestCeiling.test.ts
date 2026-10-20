/**
 * The bar ceiling, and the default range that has to fit under it.
 *
 * Two numbers decided in different files govern whether the panel works the
 * moment it is opened: how far back a run reaches by default, and the most bars
 * a run may cover. They are set independently and are not independent, so this
 * holds them against each other.
 */

import { describe, expect, it } from 'vitest'
import { DEFAULT_DAYS } from '@/components/trading/BacktestPanel'
import { MAX_BARS } from './backtestRun'

/** An Indian equity session, 09:15 to 15:30. */
const MINUTES_PER_SESSION = 375

/**
 * Trading sessions in a span of calendar days.
 *
 * Five days in seven, less a rough allowance for the roughly fifteen trading
 * holidays in a year. Deliberately an estimate: the point is the order of
 * magnitude, and a test that read the real holiday calendar would be testing
 * the calendar rather than the coupling.
 */
function sessionsIn(days: number): number {
  return Math.floor(days * (5 / 7) * 0.96)
}

describe('the default range and the ceiling', () => {
  it('lets the panel run its own default range at the finest interval', () => {
    // THE ONE THAT MATTERS. The first thing a trader does is open the panel and
    // press run on whatever it came up with. If the default range asks for more
    // bars than the ceiling allows, the answer to that press is a refusal, and
    // the feature looks broken before they have configured anything.
    const bars = sessionsIn(DEFAULT_DAYS) * MINUTES_PER_SESSION

    expect(bars).toBeLessThanOrEqual(MAX_BARS)
  })

  it('keeps the default well under the ceiling rather than spending it', () => {
    // The other side of it, and the reason the two numbers are not the same.
    // A run now starts on its own when the instrument or the interval changes,
    // so whatever the default range costs is paid every time a trader switches
    // symbol. The ceiling is headroom for somebody who widens the dates on
    // purpose; a default that reached it would put the ceiling's whole cost
    // behind an ordinary click.
    const bars = sessionsIn(DEFAULT_DAYS) * MINUTES_PER_SESSION

    expect(bars).toBeLessThan(MAX_BARS * 0.75)
  })

  it('still reaches a useful range by default', () => {
    // And not so far under that the panel is useless until the dates are
    // changed by hand. Six months of one minute bars is a real backtest.
    const bars = sessionsIn(DEFAULT_DAYS) * MINUTES_PER_SESSION

    expect(bars).toBeGreaterThan(20000)
  })

  it('states a ceiling the engine can actually reach in a click', () => {
    // A guard on the number itself, because it governs how much work one run
    // is and the cost is close to linear in it. Measured in a browser on a
    // supertrend that trades: 335ms at twenty thousand and 2.3 seconds at a
    // hundred thousand. A run goes to a worker where there is one, so the
    // question at the ceiling is how long a trader waits rather than how long
    // the terminal is frozen, but it is still a wait somebody is having.
    expect(MAX_BARS).toBeGreaterThanOrEqual(20000)
    expect(MAX_BARS).toBeLessThanOrEqual(200000)
  })
})
