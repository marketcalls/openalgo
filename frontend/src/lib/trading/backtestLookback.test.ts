/**
 * How far back a backtest reaches by default, per interval.
 *
 * Two things this has to get right, and they pull against each other: a range
 * long enough that the run says something about the strategy, and short enough
 * that an ordinary run does not fetch tens of megabytes. A run now also starts
 * on its own when the instrument or the interval changes, so whatever this
 * returns is paid every time a trader switches symbol.
 */

import { describe, expect, it } from 'vitest'
import { backtestLookbackDays, lookbackDays } from './intervals'

const SESSION_MINUTES = 375
const SESSIONS_PER_DAY = (5 / 7) * 0.96

/** Roughly how many bars a range of days yields at an intraday interval. */
function barsFor(interval: string, days: number): number {
  const minutes = Number(/^(\d+)m$/.exec(interval)?.[1] ?? 0)
  if (!minutes) return 0
  return Math.round((days * SESSIONS_PER_DAY * SESSION_MINUTES) / minutes)
}

describe('the default range', () => {
  it('reaches two months on an intraday frame', () => {
    for (const interval of ['1s', '15s', '1m', '3m', '5m', '15m', '30m', '45m']) {
      expect(backtestLookbackDays(interval)).toBe(60)
    }
  })

  it('reaches two years on an hourly or daily frame', () => {
    for (const interval of ['1h', '2h', '4h', 'D']) {
      expect(backtestLookbackDays(interval)).toBe(730)
    }
  })

  it('reaches further than two years on weekly and monthly', () => {
    // Two years of monthly bars is twenty four of them, which is a table and
    // not a backtest. For these the scarce thing is the bar count, not memory.
    expect(backtestLookbackDays('W')).toBeGreaterThan(730)
    expect(backtestLookbackDays('M')).toBeGreaterThan(backtestLookbackDays('W'))
  })

  it('takes the smaller fetch for an interval it does not recognise', () => {
    // A broker naming an interval its own way. The cautious answer is the
    // cheaper one; a trader who wants more moves the date box.
    for (const odd of ['', 'weird', '1y', '2D', 'D1']) {
      expect(backtestLookbackDays(odd)).toBe(60)
    }
  })
})

describe('what that costs in bars', () => {
  it('keeps every intraday default well under the engine ceiling', () => {
    // THE POINT OF THE RULE. A year of one minute bars is near a hundred
    // thousand, which is seconds of folding on every symbol change. Two months
    // is a sixth of that and still forty sessions of trading.
    expect(barsFor('1m', backtestLookbackDays('1m'))).toBeLessThan(20000)
    expect(barsFor('5m', backtestLookbackDays('5m'))).toBeLessThan(5000)
  })

  it('still gives a minute strategy enough sessions to mean something', () => {
    // The other side of it. A default so small that every run has to be
    // widened by hand is a default that is not doing its job.
    expect(barsFor('1m', backtestLookbackDays('1m'))).toBeGreaterThan(8000)
  })
})

describe('it is not the chart lookback', () => {
  it('reaches much further than the chart does on a minute frame', () => {
    // THE DISTINCTION. The chart wants a week of one minute bars because nobody
    // scrolls back further. A backtest over a week is a backtest over four
    // sessions, which says nothing about a strategy. Sharing one function is
    // how a backtest ends up sized for a scrollbar.
    expect(backtestLookbackDays('1m')).toBeGreaterThan(lookbackDays('1m'))
    expect(backtestLookbackDays('5m')).toBeGreaterThan(lookbackDays('5m'))
  })
})
