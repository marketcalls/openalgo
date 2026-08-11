import { describe, expect, it } from 'vitest'
import {
  computePayoff,
  hasMultipleActiveExpiries,
  isLegExecutable,
  legPnlAt,
  lognormalPriceBand,
  nearestLegDays,
  normCdf,
  type OptionType,
  payoffPriceRange,
  probabilityOfProfit,
  type Side,
  type StrategyLeg,
  totalPnlAt,
  type ValuationClock,
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

function valuationOptionLeg(overrides: Partial<StrategyLeg> = {}): StrategyLeg {
  return {
    ...optionLeg('valuation-option', 'BUY', 'CE', 25_000, 200, 1, '14AUG26'),
    lotSize: 50,
    iv: 15,
    ...overrides,
  }
}

function futureLeg(overrides: Partial<StrategyLeg> = {}): StrategyLeg {
  return {
    id: 'valuation-future',
    segment: 'FUTURE',
    side: 'BUY',
    lots: 1,
    lotSize: 25,
    expiry: '14AUG26',
    price: 25_100,
    iv: 0,
    active: true,
    symbol: 'NIFTY14AUG26FUT',
    ...overrides,
  }
}

describe('per-leg market valuation', () => {
  it.each([
    ['zero lots', { lots: 0 }],
    ['fractional lots', { lots: 1.5 }],
    ['zero lot size', { lotSize: 0 }],
    ['fractional lot size', { lotSize: 12.5 }],
  ])('rejects an otherwise valid executable leg with %s', (_label, overrides) => {
    const candidate = valuationOptionLeg({
      contractValid: true,
      tickSize: 0.05,
      ...overrides,
    })

    expect(isLegExecutable(candidate)).toBe(false)
  })

  it('freezes a zero-exit leg at realised P&L and excludes it from open expiry horizons', () => {
    const leg = valuationOptionLeg({
      price: 100,
      exitPrice: 0,
      lotSize: 50,
      expiryTs: 1_789_012_800,
      referenceUnderlying: 25_000,
      forwardPrice: 25_120,
      marketPrice: 250,
    })
    const now = new Date('2026-08-11T04:00:00Z')

    expect(legPnlAt(leg, 20_000, 0, 15, now)).toBe(-5_000)
    expect(legPnlAt(leg, 30_000, 3, 40, now)).toBe(-5_000)
    expect(nearestLegDays([leg], now)).toBe(0)
  })

  it('reconciles a zero-shift option to its live Black-76 market price', () => {
    // Independently hand-calculated Black-76: F=25120, K=25000,
    // t=3.25/365, sigma=15% gives 209.5271, quoted at the ₹0.05 tick as 209.55.
    const leg = valuationOptionLeg({
      marketPrice: 209.55,
      forwardPrice: 25_120,
      referenceUnderlying: 25_000,
      expiryTs: 1_786_701_600,
      tickSize: 0.05,
    })

    expect(legPnlAt(leg, 25_000, 0, 15, new Date('2026-08-11T04:00:00Z'))).toBeCloseTo(477.5, 2)
  })

  it('values a selected future from its own market reference', () => {
    const leg = futureLeg({ marketPrice: 25_120, referenceUnderlying: 25_000 })

    expect(legPnlAt(leg, 25_000, 0)).toBe(500)
    expect(legPnlAt(leg, 25_100, 0)).toBe(3_000)
  })

  it('uses the server-adjusted authoritative expiry for sub-day valuation', () => {
    // The client is two minutes fast (04:02), while server time is 04:00 and
    // the authoritative epoch expiry is 04:30. The hand-calculated Black-76
    // call values for 30 and 15 minutes at F=K=100, sigma=20% are 0.06028 and
    // 0.04262 per unit, or 3.014 and 2.131 per 50-unit lot respectively.
    const serverClock: ValuationClock = {
      now: new Date('2026-08-11T04:02:00Z'),
      clockOffsetMs: -120_000,
    }
    const leg = valuationOptionLeg({
      expiry: 'NOT_A_LEGACY_DATE',
      expiryTs: 1_786_422_600,
      strike: 100,
      price: 0,
      iv: 20,
      referenceUnderlying: 100,
      forwardPrice: 100,
    })

    expect(legPnlAt(leg, 100, 0, 20, serverClock)).toBeCloseTo(3.014, 3)
    expect(legPnlAt(leg, 100, 0.010416666666666666, 20, serverClock)).toBeCloseTo(2.131, 3)
  })

  it('falls back to the legacy expiry string when no expiry timestamp is available', () => {
    const leg = valuationOptionLeg({
      expiry: '11AUG26',
      strike: 100,
      price: 0,
      iv: 20,
      referenceUnderlying: 100,
      forwardPrice: 100,
    })

    expect(legPnlAt(leg, 100, 0, 20, new Date('2026-08-11T09:30:00Z'))).toBeCloseTo(3.014, 3)
  })

  it('uses authoritative expiry metadata for aggregate horizons', () => {
    // At the server-corrected 04:00, the authoritative expiry is exactly 30
    // days away. A 30-day Black-76 call worth 1 at expiry crosses zero P&L at
    // the independently calculated forward of 96.79, not the parsed-expiry
    // terminal-analysis artefact.
    const serverClock: ValuationClock = {
      now: new Date('2026-08-11T04:02:00Z'),
      clockOffsetMs: -120_000,
    }
    const leg = valuationOptionLeg({
      lotSize: 1,
      expiry: 'NOT_A_LEGACY_DATE',
      expiryTs: 1_789_012_800,
      strike: 100,
      price: 1,
      iv: 20,
      referenceUnderlying: 100,
      forwardPrice: 100,
    })
    const payoff = computePayoff([leg], 100, 0, 0, [90, 110], 120, 0, 20, serverClock)

    expect(payoff.breakevens[0]).toBeCloseTo(96.79, 1)
    expect(nearestLegDays([leg], serverClock)).toBeCloseTo(30, 8)
  })

  it('uses forward and futures market bases for a flat-slope nonterminal tail', () => {
    const now = new Date('2026-08-11T04:00:00Z')
    const nearExpiry = 1_786_507_200
    const farExpiry = 1_817_956_800
    const neutralNearCall = {
      ...valuationOptionLeg({
        id: 'near-call',
        lotSize: 1,
        expiry: '12AUG26',
        expiryTs: nearExpiry,
        strike: 100,
        price: 0,
        iv: 100,
        referenceUnderlying: 100,
        forwardPrice: 95,
      }),
    }
    const neutralFarCall = {
      ...neutralNearCall,
      id: 'far-call',
      side: 'SELL' as const,
      // The display string is deliberately stale. The authoritative far expiry
      // keeps the calendar nonterminal and its time value negative at 200.
      expiry: '12AUG26',
      expiryTs: farExpiry,
      forwardPrice: 100,
    }
    const longFuture = futureLeg({
      id: 'long-future',
      lots: 1,
      lotSize: 1,
      price: 100,
      marketPrice: 110,
      referenceUnderlying: 100,
    })
    const shortFuture = futureLeg({
      id: 'short-future',
      side: 'SELL',
      lots: 1,
      lotSize: 1,
      price: 100,
      marketPrice: 100,
      referenceUnderlying: 100,
    })

    const payoff = computePayoff(
      [neutralNearCall, neutralFarCall, longFuture, shortFuture],
      100,
      0,
      0,
      [80, 120],
      10,
      0,
      20,
      now
    )

    expect(payoff.breakevens.at(-1)).toBeGreaterThan(200)
  })

  it('clamps a non-positive scenario forward to the Black-76 boundary', () => {
    const common = {
      lotSize: 1,
      expiryTs: 1_789_012_800,
      strike: 100,
      price: 0,
      iv: 20,
      referenceUnderlying: 100,
      forwardPrice: 50,
    }
    const call = valuationOptionLeg(common)
    const put = valuationOptionLeg({ ...common, optionType: 'PE' })
    const now = new Date('2026-08-11T04:00:00Z')

    expect(legPnlAt(call, -1, 0, 20, now)).toBe(0)
    expect(legPnlAt(put, -1, 0, 20, now)).toBe(100)
  })

  it('does not reconcile an out-of-tolerance live quote', () => {
    const leg = valuationOptionLeg({
      lotSize: 50,
      marketPrice: 210,
      forwardPrice: 25_120,
      referenceUnderlying: 25_000,
      expiryTs: 1_786_701_600,
      tickSize: 0.05,
    })

    expect(legPnlAt(leg, 25_000, 0, 15, new Date('2026-08-11T04:00:00Z'))).toBeCloseTo(476.36, 1)
  })

  it('keeps spot, IV, and time-shifted scenarios model-priced', () => {
    const leg = valuationOptionLeg({
      lotSize: 50,
      marketPrice: 209.55,
      forwardPrice: 25_120,
      referenceUnderlying: 25_000,
      expiryTs: 1_786_701_600,
      tickSize: 0.05,
    })
    const now = new Date('2026-08-11T04:00:00Z')

    expect(legPnlAt(leg, 25_100, 0, 15, now)).toBeCloseTo(3905.81, 1)
    expect(legPnlAt(leg, 25_000, 0, 20, now)).toBeCloseTo(2735.7, 1)
    expect(legPnlAt(leg, 25_000, 1, 15, now)).toBeCloseTo(-632.97, 1)
  })
})

describe('payoff geometry and structural risk', () => {
  it('finds terminal roots at the option kink expressed in underlying coordinates', () => {
    const shiftedForwardCall = valuationOptionLeg({
      lotSize: 1,
      strike: 100,
      price: 5,
      expiryTs: NOW.getTime() / 1000,
      referenceUnderlying: 100,
      forwardPrice: 110,
    })

    const payoff = computePayoff(
      [shiftedForwardCall],
      100,
      0,
      0,
      [80, 120],
      8,
      0,
      20,
      NOW
    )

    expect(payoff.breakevens).toEqual([95])
    expect(payoff.maxLoss).toBe(-5)
    expect(payoff.maxProfit).toBe(Infinity)
  })

  it('does not invent a breakeven for an empty strategy', () => {
    const payoff = computePayoff([], 100, EXPIRY_DAYS, 0, [90, 110], 10, 0, 20, NOW)

    expect(payoff.breakevens).toEqual([])
    expect(payoff.maxProfit).toBe(0)
    expect(payoff.maxLoss).toBe(0)
  })

  it('uses hand-derived lognormal quantiles for expected-move bands', () => {
    const oneSigma = lognormalPriceBand(110, 30, 0.25, 1)
    const twoSigma = lognormalPriceBand(110, 30, 0.25, 2)

    expect(oneSigma?.lower).toBeCloseTo(93.6187202159, 10)
    expect(oneSigma?.upper).toBeCloseTo(126.3720540374, 10)
    expect(twoSigma?.lower).toBeCloseTo(80.5783792325, 10)
    expect(twoSigma?.upper).toBeCloseTo(146.8233797046, 10)
  })

  it('rejects non-finite lognormal inputs instead of contaminating the chart domain', () => {
    expect(lognormalPriceBand(Number.NaN, 30, 0.25, 1)).toBeNull()
    expect(lognormalPriceBand(110, Number.POSITIVE_INFINITY, 0.25, 1)).toBeNull()
  })

  it('rejects finite IV and horizon values that overflow derived lognormal values', () => {
    expect(lognormalPriceBand(100, 1e308, 1e308, 2)).toBeNull()
  })

  it('rejects a finite spot when the returned lognormal band would overflow', () => {
    expect(lognormalPriceBand(1e308, 100, 1, 2)).toBeNull()
  })

  it('omits overflowed lognormal bands from the payoff range', () => {
    const range = payoffPriceRange(100, [], 1e308, 1e308)

    expect(range[0]).toBeCloseTo(90, 10)
    expect(range[1]).toBeCloseTo(110, 10)
  })

  it('keeps the payoff range finite when a finite spot overflows its upper baseline', () => {
    const range = payoffPriceRange(Number.MAX_VALUE, [], 100, 1)

    expect(range.every(Number.isFinite)).toBe(true)
    expect(range[1]).toBe(Number.MAX_VALUE)
  })

  it('PG-06 expands the shifted display range to include strikes and lognormal two sigma', () => {
    const legs = [optionLeg('put', 'SELL', 'PE', 70, 3), optionLeg('call', 'SELL', 'CE', 130, 3)]

    const range = payoffPriceRange(110, legs, 30, 0.25)

    expect(range[0]).toBeCloseTo(70, 10)
    expect(range[1]).toBeCloseTo(146.8233797046, 10)
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

  it('distinguishes a finite zero PoP from unavailable distribution inputs', () => {
    const alwaysLosing = [
      { underlying: 80, expiry: -1, tplus0: -1 },
      { underlying: 120, expiry: -1, tplus0: -1 },
    ]

    expect(probabilityOfProfit(alwaysLosing, 100, 20, 1)).toBe(0)
    expect(probabilityOfProfit(alwaysLosing, 100, 0, 1)).toBeNull()
    expect(probabilityOfProfit([], 100, 20, 1)).toBeNull()
    expect(probabilityOfProfit(alwaysLosing, Number.POSITIVE_INFINITY, 20, 1)).toBeNull()
    expect(
      probabilityOfProfit(
        [
          { underlying: Number.NaN, expiry: -1, tplus0: -1 },
          { underlying: 120, expiry: -1, tplus0: -1 },
        ],
        100,
        20,
        1
      )
    ).toBeNull()
  })

  it('returns unavailable when finite IV and horizon overflow derived PoP math', () => {
    const alwaysWinning = [
      { underlying: 80, expiry: 1, tplus0: 1 },
      { underlying: 120, expiry: 1, tplus0: 1 },
    ]

    expect(probabilityOfProfit(alwaysWinning, 100, 1e308, 1e308)).toBeNull()
  })

  it('treats mixed authoritative and legacy metadata for the same expiry as one event', () => {
    const expiryTs = Date.parse('2026-08-13T10:00:00.000Z') / 1000
    const sameExpiry = [
      { ...optionLeg('authoritative', 'BUY', 'CE', 100, 2, 1, '13AUG26'), expiryTs },
      optionLeg('legacy', 'SELL', 'CE', 105, 1, 1, '13AUG26'),
    ]
    const calendar = [...sameExpiry, optionLeg('far', 'BUY', 'CE', 110, 1, 1, '18AUG26')]

    expect(hasMultipleActiveExpiries(sameExpiry)).toBe(false)
    expect(hasMultipleActiveExpiries(calendar)).toBe(true)
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
