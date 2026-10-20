/**
 * Every strategy template's breakevens, checked against an independent
 * calculation rather than against the implementation that produced them.
 *
 * The terminal payoff of an option strategy is piecewise linear in SPOT, with
 * kinks only at the strikes, so it can be solved exactly in a few lines that
 * share no code with `strategyMath`. That independence is the point: a bug in
 * the forward handling shifted every breakeven by the spot-to-forward basis and
 * the suite stayed green, because the fixtures carried no forward at all. These
 * fixtures do carry one, in contango, as production does.
 */

import { describe, expect, it } from 'vitest'
import { computePayoff, nearestLegDays, payoffPriceRange, type StrategyLeg } from './strategyMath'
import { STRATEGY_TEMPLATES } from './strategyTemplates'
import { resolveStrikeOffset } from './templateResolution'

const SPOT = 24_350
/**
 * One carry curve for the chain: the parity forward sits above spot on an
 * Indian index, and a further expiry carries further. Pinning every expiry to
 * the same forward would imply a near leg carrying several times as fast as a
 * far one, which is not a shape any book quotes.
 */
const CARRY_RATE = 0.06
const NOW = new Date('2026-08-14T05:00:00.000Z')
const NEAR_DAYS = 11
const FAR_DAYS = 39
const STRIKES = Array.from({ length: 61 }, (_, index) => SPOT + (index - 30) * 50)

/** Terminal value per share, struck against spot. Independent of strategyMath. */
function independentPayoff(legs: StrategyLeg[], spot: number): number {
  let total = 0
  for (const leg of legs) {
    const sign = leg.side === 'BUY' ? 1 : -1
    const quantity = leg.lots * leg.lotSize
    const strike = leg.strike as number
    const intrinsic =
      leg.optionType === 'CE' ? Math.max(0, spot - strike) : Math.max(0, strike - spot)
    total += sign * quantity * (intrinsic - leg.price)
  }
  return total
}

/** Exact roots of that piecewise-linear payoff, including the right ray. */
function independentBreakevens(legs: StrategyLeg[]): number[] {
  const strikes = Array.from(new Set(legs.map((leg) => leg.strike as number))).sort((a, b) => a - b)
  const points = [0, ...strikes]
  const values = points.map((point) => independentPayoff(legs, point))
  const roots: number[] = []
  const isZero = (value: number) => Math.abs(value) < 1e-6

  // Crossings strictly between two non-zero vertices.
  for (let index = 0; index < points.length - 1; index++) {
    const left = values[index]
    const right = values[index + 1]
    if (isZero(left) || isZero(right)) continue
    if (left * right < 0) {
      roots.push(
        points[index] + ((0 - left) * (points[index + 1] - points[index])) / (right - left)
      )
    }
  }

  // A vertex sitting exactly on zero. A long synthetic crosses at its strike,
  // and a costless collar is flat on zero between its strikes; the edges of
  // such a run are the breakevens, the interior is not.
  for (let index = 1; index < points.length; index++) {
    if (!isZero(values[index])) continue
    const previousZero = isZero(values[index - 1])
    const nextZero = index + 1 < values.length && isZero(values[index + 1])
    if (previousZero && nextZero) continue
    roots.push(points[index])
  }

  let slope = 0
  for (const leg of legs) {
    if (leg.optionType !== 'CE') continue
    slope += (leg.side === 'BUY' ? 1 : -1) * leg.lots * leg.lotSize
  }
  const last = points[points.length - 1]
  const lastValue = values[values.length - 1]
  if (Math.abs(slope) > 1e-9) {
    const root = last - lastValue / slope
    if (root > last + 1e-9) roots.push(root)
  }
  return roots.sort((a, b) => a - b)
}

function buildLegs(template: (typeof STRATEGY_TEMPLATES)[number]): StrategyLeg[] {
  return template.legs.map((leg, index) => {
    const strike = resolveStrikeOffset(STRIKES, SPOT, leg.strikeOffset)
    if (strike === null) throw new Error(`Fixture cannot resolve ${template.id}`)
    const isFar = leg.expiryOffset === 1
    // Intrinsic plus a time value that decays away from spot and grows with the
    // square root of remaining life. A premium rising with distance from spot
    // would turn every vertical into a credit and every butterfly costless,
    // and the breakevens would disappear rather than being verified.
    const intrinsic =
      leg.optionType === 'CE' ? Math.max(0, SPOT - strike) : Math.max(0, strike - SPOT)
    const days = isFar ? FAR_DAYS : NEAR_DAYS
    const timeValue = 120 * Math.sqrt(days / NEAR_DAYS) * Math.exp(-Math.abs(strike - SPOT) / 300)
    return {
      id: `${template.id}-${index}`,
      segment: 'OPTION',
      side: leg.side,
      optionType: leg.optionType,
      strike,
      lots: leg.lots,
      lotSize: 65,
      expiry: isFar ? '22SEP26' : '25AUG26',
      expiryTs: NOW.getTime() / 1000 + days * 86_400,
      price: intrinsic + timeValue,
      iv: 12,
      active: true,
      symbol: `${template.id}-${index}`,
      referenceUnderlying: SPOT,
      forwardPrice: SPOT * Math.exp((CARRY_RATE * days) / 365),
    }
  })
}

describe('strategy template payoff', () => {
  it.each(
    STRATEGY_TEMPLATES
  )('$id breaks even where spot settlement says it should', (template) => {
    const legs = buildLegs(template)
    const nearest = nearestLegDays(legs, NOW)
    const range = payoffPriceRange(SPOT, legs, 12, nearest / 365)
    const payoff = computePayoff(legs, SPOT, nearest, 0, range, 240, 0, 12, NOW)

    if (template.legs.some((leg) => leg.expiryOffset === 1)) {
      // A calendar's far leg is still alive at the first expiry, so the curve
      // is not piecewise linear and cannot be solved this way. Assert only that
      // the window is sane and the roots are ordered.
      expect(payoff.samples[0].underlying).toBeGreaterThan(0)
      expect(payoff.breakevens).toEqual([...payoff.breakevens].sort((a, b) => a - b))
      return
    }

    const expected = independentBreakevens(legs)
    expect(payoff.breakevens).toHaveLength(expected.length)
    for (let index = 0; index < expected.length; index++) {
      expect(payoff.breakevens[index]).toBeCloseTo(expected[index], 2)
    }
    // No breakeven may be reported at an unreachable underlying of zero.
    expect(payoff.breakevens.every((value) => value > 0)).toBe(true)
  })
})
