import { describe, expect, it } from 'vitest'
import { fmtPrice, groupIndian, money, priceDp, snapTick, tickDecimals, tickSize } from './format'

/**
 * Every expectation here is a literal, worked out from the trading rule rather
 * than from the code: restating the arithmetic would make these pass for any
 * implementation, including a broken one.
 *
 * The values are the ticks Indian exchanges actually quote -- 0.05 on equity
 * and index options, 0.01 where a finer tick applies, 0.25 and 0.0025 on
 * currency, 1 on a high-priced scrip -- so a regression shows up as a price a
 * trader would recognise as wrong.
 */

describe('tickSize', () => {
  it('keeps a plausible tick', () => {
    expect(tickSize(0.05, 100)).toBe(0.05)
    expect(tickSize(0.01, 100)).toBe(0.01)
    expect(tickSize(1, 500)).toBe(1)
  })

  it('falls back to 0.05 when the feed sends no usable tick', () => {
    expect(tickSize(undefined, 100)).toBe(0.05)
    expect(tickSize(0, 100)).toBe(0.05)
    expect(tickSize(-0.05, 100)).toBe(0.05)
    expect(tickSize(Number.NaN, 100)).toBe(0.05)
  })

  /**
   * The guard that matters: a tick above one percent of the price cannot be
   * real, and usually means paise arrived where rupees were expected. Left
   * alone it would snap every order to a whole number.
   */
  it('rejects a tick too coarse to be real', () => {
    expect(tickSize(1, 23)).toBe(0.05)
    expect(tickSize(5, 100)).toBe(0.05)
  })

  it('accepts a coarse tick when the price is high enough to justify it', () => {
    expect(tickSize(1, 500)).toBe(1)
    // Exactly one percent is not "greater than", so it survives.
    expect(tickSize(1, 100)).toBe(1)
    expect(tickSize(1.01, 100)).toBe(0.05)
  })

  /**
   * With no reference price there is nothing to compare against, so the
   * plausibility check cannot run and the feed's tick is taken as given.
   */
  it('skips the plausibility check when there is no reference price', () => {
    expect(tickSize(1, 0)).toBe(1)
  })
})

describe('tickDecimals', () => {
  it.each([
    [1, 500, 0],
    [0.5, 500, 1],
    [0.25, 500, 2],
    [0.1, 500, 1],
    [0.05, 500, 2],
    [0.01, 500, 2],
    // Currency derivatives genuinely quote to four decimals.
    [0.0025, 500, 4],
  ])('derives %s -> %s decimals', (tick, ref, expected) => {
    expect(tickDecimals(tick, ref)).toBe(expected)
  })

  it('derives decimals from the fallback when the tick is unusable', () => {
    expect(tickDecimals(undefined, 100)).toBe(2)
    expect(tickDecimals(0, 100)).toBe(2)
  })
})

describe('priceDp', () => {
  /**
   * A whole-rupee tick implies zero decimals, but a price column that switches
   * between "1050" and "1050.25" between rows is unreadable, so display is
   * floored at two.
   */
  it('never shows fewer than two decimals', () => {
    expect(priceDp(1, 500)).toBe(2)
    expect(priceDp(0.5, 500)).toBe(2)
    expect(priceDp(0.05, 500)).toBe(2)
  })

  it('keeps the extra precision a finer tick needs', () => {
    expect(priceDp(0.0025, 500)).toBe(4)
  })
})

describe('snapTick', () => {
  it('lands on the tick below and the tick above a boundary', () => {
    expect(snapTick(100.0249, 0.05, 100)).toBe(100)
    expect(snapTick(100.0251, 0.05, 100)).toBe(100.05)
  })

  it('rounds an exact half up', () => {
    expect(snapTick(100.025, 0.05, 100)).toBe(100.05)
  })

  it('leaves a price already on the tick untouched', () => {
    expect(snapTick(100.05, 0.05, 100)).toBe(100.05)
    expect(snapTick(100, 0.05, 100)).toBe(100)
  })

  it('snaps to a whole rupee when the instrument trades that way', () => {
    expect(snapTick(102.6, 1, 500)).toBe(103)
    expect(snapTick(102.4, 1, 500)).toBe(102)
  })

  it('snaps through the fallback when the tick is unusable', () => {
    expect(snapTick(100.03, undefined, 100)).toBe(100.05)
  })

  /**
   * Binary floating point cannot represent 0.05, so the multiply back out
   * lands on 100.05000000000001 before it is fixed to the tick's decimals.
   * This asserts the cleanup, not the arithmetic.
   */
  it('returns a clean decimal rather than a float artefact', () => {
    expect(snapTick(100.03, 0.05, 100).toString()).toBe('100.05')
  })
})

describe('groupIndian', () => {
  it('leaves anything up to three digits alone', () => {
    expect(groupIndian('1')).toBe('1')
    expect(groupIndian('123')).toBe('123')
  })

  /** Thousands, then two-digit groups: lakh and crore, not millions. */
  it('groups in the Indian system', () => {
    expect(groupIndian('1234')).toBe('1,234')
    expect(groupIndian('12345')).toBe('12,345')
    expect(groupIndian('100000')).toBe('1,00,000')
    expect(groupIndian('1234567')).toBe('12,34,567')
    expect(groupIndian('10000000')).toBe('1,00,00,000')
  })
})

describe('fmtPrice', () => {
  it('groups and fixes decimals from the tick', () => {
    expect(fmtPrice(1234567.891, 0.05, 100000)).toBe('12,34,567.89')
    expect(fmtPrice(1050, 1, 500)).toBe('1,050.00')
  })

  it('keeps the minus sign outside the grouping', () => {
    expect(fmtPrice(-1234.5, 0.05, 1000)).toBe('-1,234.50')
  })

  it('shows four decimals for a four-decimal tick', () => {
    expect(fmtPrice(83.2575, 0.0025, 83)).toBe('83.2575')
  })
})

describe('money', () => {
  it('always shows paise', () => {
    expect(money(0.05)).toBe('0.05')
    expect(money(1200)).toBe('1,200.00')
  })

  it('groups large rupee values', () => {
    expect(money(12345678.9)).toBe('1,23,45,678.90')
  })

  /**
   * A P&L figure is rendered next to its own sign or colour, so this returns
   * the magnitude only. Pinning it means a caller cannot start relying on a
   * minus sign that was never there.
   */
  it('returns the magnitude, without a sign', () => {
    expect(money(-1234.5)).toBe('1,234.50')
    expect(money(1234.5)).toBe('1,234.50')
  })
})

/**
 * These helpers exist because Intl 'en-IN' grouping and minMove auto-precision
 * differ across operating systems, which put different decimals on Windows and
 * macOS for the same instrument. Output must therefore be byte-identical
 * everywhere, so it may never contain a locale-chosen separator or digit.
 */
describe('platform independence', () => {
  it('emits only ASCII digits, commas, dots and a minus', () => {
    const samples = [
      fmtPrice(1234567.891, 0.05, 100000),
      fmtPrice(-1234.5, 0.05, 1000),
      money(12345678.9),
      groupIndian('10000000'),
    ]
    for (const s of samples) {
      expect(s).toMatch(/^-?[0-9,]+(\.[0-9]+)?$/)
    }
  })

  /**
   * Not a locale switch: ICU resolves its locale when the process starts, so
   * reassigning an env var mid-run would prove nothing. This instead pins that
   * the helpers do not delegate to the platform formatter, whose grouping and
   * decimal count both vary with the machine's locale.
   */
  it('does not delegate to the platform number formatter', () => {
    expect(fmtPrice(1234567.891, 0.05, 100000)).toBe('12,34,567.89')
    expect(fmtPrice(1234567.891, 0.05, 100000)).not.toBe((1234567.891).toLocaleString())
  })
})
