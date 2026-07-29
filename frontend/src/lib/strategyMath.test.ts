import { describe, expect, it } from 'vitest'
import {
  computePayoff,
  normCdf,
  payoffPriceRange,
  probabilityOfProfit,
  totalPnlAt,
  type OptionType,
  type Side,
  type StrategyLeg,
} from './strategyMath'

const NOW = new Date('2026-07-28T10:00:00.000Z')
const EXPIRY_DAYS = 7

function optionLeg(
  id: string,
  side: Side,
  optionType: OptionType,
  strike: number,
  price: number,
  lots = 1,
  expiry = '04AUG26'
): StrategyLeg {
  return {
    id,
    segment: 'OPTION',
    side,
    lots,
    lotSize: 1,
    expiry,
    strike,
    optionType,
    price,
    iv: 20,
    active: true,
    symbol: `NIFTY04AUG26${strike}${optionType}`,
  }
}

function ironCondor(): StrategyLeg[] {
  return [
    optionLeg('lp', 'BUY', 'PE', 90, 0.5),
    optionLeg('sp', 'SELL', 'PE', 95, 2),
    optionLeg('sc', 'SELL', 'CE', 105, 2),
    optionLeg('lc', 'BUY', 'CE', 110, 0.5),
  ]
}

describe('payoff geometry and structural risk', () => {
  it('does not invent a breakeven for an empty strategy', () => {
    const payoff = computePayoff([], 100, EXPIRY_DAYS, 0, [90, 110], 10, 0, 20, NOW)

    expect(payoff.breakevens).toEqual([])
    expect(payoff.maxProfit).toBe(0)
    expect(payoff.maxLoss).toBe(0)
  })

  it('PG-06 expands the display range to include strikes and two sigma', () => {
    const legs = [optionLeg('put', 'SELL', 'PE', 70, 3), optionLeg('call', 'SELL', 'CE', 130, 3)]

    expect(payoffPriceRange(100, legs, 30, 1)).toEqual([40, 160])
  })

  it('PG-25 includes every Iron Condor strike and breakeven as an exact sample', () => {
    const payoff = computePayoff(ironCondor(), 100, EXPIRY_DAYS, 0, [90, 110], 7, 0, 20, NOW)
    const xs = payoff.samples.map((sample) => sample.underlying)

    expect(xs).toEqual(expect.arrayContaining([90, 92, 95, 105, 108, 110]))
    expect(payoff.breakevens).toEqual([92, 108])
    expect(payoff.maxProfit).toBeCloseTo(3, 10)
    expect(payoff.maxLoss).toBeCloseTo(-2, 10)
  })

  it('PG-07 emits an exact-grid breakeven once', () => {
    const synthetic = [
      optionLeg('call', 'BUY', 'CE', 100, 5),
      optionLeg('put', 'SELL', 'PE', 100, 5),
    ]

    const payoff = computePayoff(synthetic, 100, EXPIRY_DAYS, 0, [90, 110], 2, 0, 20, NOW)

    expect(payoff.breakevens).toEqual([100])
  })

  it('PG-01 finds wide-strangle breakevens outside the supplied chart window', () => {
    const wideStrangle = [
      optionLeg('put', 'SELL', 'PE', 70, 3),
      optionLeg('call', 'SELL', 'CE', 130, 3),
    ]

    const payoff = computePayoff(wideStrangle, 100, EXPIRY_DAYS, 0, [90, 110], 20, 0, 20, NOW)

    expect(payoff.breakevens).toEqual([64, 136])
    expect(payoff.samples[0].underlying).toBeLessThanOrEqual(64)
    expect(payoff.samples.at(-1)?.underlying).toBeGreaterThanOrEqual(136)
  })

  it('PG-01 computes PoP from the wide strategy roots rather than sample endpoints', () => {
    const wideStrangle = [
      optionLeg('put', 'SELL', 'PE', 70, 3),
      optionLeg('call', 'SELL', 'CE', 130, 3),
    ]
    const payoff = computePayoff(wideStrangle, 100, EXPIRY_DAYS, 0, [90, 110], 20, 0, 20, NOW)
    const probability = probabilityOfProfit(payoff.samples, 100, 20, 1)
    const sigma = 0.2
    const mu = -0.5 * sigma * sigma
    const cdf = (x: number) => normCdf((Math.log(x / 100) - mu) / sigma)

    expect(probability).toBeCloseTo(cdf(136) - cdf(64), 5)
    expect(probability).toBeLessThan(1)
  })

  it('PG-15 numerically refines a smooth multi-expiry extremum and preserves unlimited risk', () => {
    const legs = [
      // Equal near-expiry legs cancel economically but establish the payoff
      // horizon while the far-dated strangle retains smooth time value.
      optionLeg('near-buy', 'BUY', 'CE', 100, 5),
      optionLeg('near-sell', 'SELL', 'CE', 100, 5),
      optionLeg('far-put', 'BUY', 'PE', 90, 3, 1, '28AUG26'),
      optionLeg('far-call', 'BUY', 'CE', 110, 3, 1, '28AUG26'),
    ]
    const denseMinimum = Array.from({ length: 20_001 }, (_, index) => 70 + index * 0.0035)
      .map((underlying) => totalPnlAt(legs, underlying, EXPIRY_DAYS, 0, 20, NOW))
      .reduce((minimum, value) => Math.min(minimum, value), Infinity)

    const payoff = computePayoff(legs, 100, EXPIRY_DAYS, 0, [73, 141], 3, 0, 20, NOW)

    expect(payoff.maxProfit).toBe(Infinity)
    expect(payoff.maxLoss).toBeCloseTo(denseMinimum, 4)
  })

  it('PG-01 expands multi-expiry tail analysis until a distant root is found', () => {
    const legs = [
      optionLeg('near-buy', 'BUY', 'CE', 100, 5),
      optionLeg('near-sell', 'SELL', 'CE', 100, 5),
      optionLeg('far-call', 'BUY', 'CE', 110, 300, 1, '28AUG26'),
    ]

    const payoff = computePayoff(legs, 100, EXPIRY_DAYS, 0, [90, 110], 10, 0, 20, NOW)

    expect(payoff.breakevens).toHaveLength(1)
    expect(payoff.breakevens[0]).toBeGreaterThan(400)
    expect(payoff.samples.at(-1)?.underlying).toBeGreaterThanOrEqual(payoff.breakevens[0])
  })

  it('PG-01 expands a zero-slope calendar tail when its limiting payoff changes sign', () => {
    const legs = [
      optionLeg('near-call', 'SELL', 'CE', 100, 0),
      {
        ...optionLeg('far-call', 'BUY', 'CE', 100, 1, 1, '28JUL27'),
        iv: 200,
      },
    ]

    const payoff = computePayoff(legs, 100, EXPIRY_DAYS, 0, [90, 110], 10, 0, 20, NOW)

    expect(payoff.maxProfit).toBeGreaterThan(0)
    expect(payoff.breakevens).toHaveLength(2)
    expect(payoff.breakevens.at(-1)).toBeGreaterThan(30_000)
    expect(payoff.samples.at(-1)?.underlying).toBeGreaterThanOrEqual(
      payoff.breakevens.at(-1) ?? Infinity
    )
  })
})
