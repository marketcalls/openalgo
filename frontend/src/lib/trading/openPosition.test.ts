/**
 * The position a run finished holding, and what it is worth right now.
 *
 * The valuation tests are the ones that matter: a sign the wrong way round
 * reports a loss as a profit, and a point value assumed reports a fraction of
 * the real exposure. Both render as a perfectly ordinary number.
 */

import { describe, expect, it } from 'vitest'
import { markToPrice, openCountOf, openPositionOf } from './openPosition'

function trade(over: Record<string, unknown> = {}) {
  return {
    index: 1,
    side: 'long',
    units: 2,
    entryPrice: 100,
    openedAt: 1_700_000_000_000,
    barsHeld: 4,
    maxFavourable: 8,
    maxAdverse: -3,
    isOpen: true,
    ...over,
  }
}

describe('finding what is open', () => {
  it('answers nothing when the run ended flat, which is the ordinary case', () => {
    expect(openPositionOf([trade({ isOpen: false })])).toBeNull()
    expect(openPositionOf([])).toBeNull()
    expect(openPositionOf(undefined)).toBeNull()
  })

  it('reads the open trade the engine flagged rather than refolding the fills', () => {
    const open = openPositionOf([trade({ isOpen: false }), trade({ index: 2, side: 'short' })])

    expect(open?.side).toBe('short')
    expect(open?.units).toBe(2)
    expect(open?.entryPrice).toBe(100)
  })

  it('keeps size positive and puts the direction in the side', () => {
    // Catches a short carried as a negative size. Every figure downstream
    // multiplies by it, so one place treating the sign as direction and another
    // as size flips the profit.
    const open = openPositionOf([trade({ side: 'short', units: 2 })])

    expect(open?.units).toBe(2)
    expect(open?.side).toBe('short')
  })

  it('skips a trade with no size or no entry rather than valuing it at zero', () => {
    // Catches a defensive default. A position shown at zero is a position a
    // trader believes is real and flat.
    expect(openPositionOf([trade({ units: 0 })])).toBeNull()
    expect(openPositionOf([trade({ units: null })])).toBeNull()
    expect(openPositionOf([trade({ entryPrice: null })])).toBeNull()
  })

  it('counts every open trade, so a pyramided run is not shown as one', () => {
    const trades = [trade(), trade({ index: 2 }), trade({ index: 3, isOpen: false })]

    expect(openCountOf(trades)).toBe(2)
    expect(openPositionOf(trades)?.index ?? 1).toBeTruthy()
  })
})

describe('what it is worth', () => {
  const long = { side: 'long', units: 2, entryPrice: 100, openedAt: null, barsHeld: null, maxFavourable: null, maxAdverse: null } as const
  const short = { ...long, side: 'short' } as const

  it('values a long up and a short down as profit', () => {
    // THE SIGN. Reversed, a short in a rising market reads as a profit while the
    // trader is losing money on every tick.
    expect(markToPrice(long, 105)?.profit).toBe(10)
    expect(markToPrice(short, 105)?.profit).toBe(-10)
    expect(markToPrice(short, 95)?.profit).toBe(10)
    expect(markToPrice(long, 95)?.profit).toBe(-10)
  })

  it('multiplies by the point value, which is not always one', () => {
    // Catches a contract multiplier assumed. On an instrument where a point is
    // worth 50, assuming 1 reports a fiftieth of the real exposure.
    expect(markToPrice(long, 105, 50)?.profit).toBe(500)
  })

  it('states the percentage against what the position cost', () => {
    const marked = markToPrice(long, 110)
    expect(marked?.profitPercent).toBeCloseTo(10, 6)
  })

  it('answers no percentage rather than infinity on an entry at zero', () => {
    expect(markToPrice({ ...long, entryPrice: 0 }, 5)?.profitPercent).toBeNull()
  })

  it('answers nothing for a price it cannot read', () => {
    // Catches NaN propagating into the panel, where it renders as "NaN" beside a
    // position a trader is deciding what to do about.
    expect(markToPrice(long, Number.NaN)).toBeNull()
    expect(markToPrice(long, 100, Number.NaN)).toBeNull()
  })

  it('carries the price it valued at, so the panel can say what it used', () => {
    expect(markToPrice(long, 103.5)?.price).toBe(103.5)
  })
})
