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
    // Pinned to an explicit expiry instant and clock. The old fixture carried
    // neither, so it read the real system date against an expiry string of
    // 14AUG26 and silently changed meaning depending on the day it ran.
    const expiryTs = NOW.getTime() / 1000 + 30 * 86_400
    const leg = futureLeg({ marketPrice: 25_120, referenceUnderlying: 25_000, expiryTs })

    // With a month to run the future holds its 120-point basis over spot.
    expect(legPnlAt(leg, 25_000, 0, undefined, NOW)).toBeCloseTo(500, 6)
    expect(legPnlAt(leg, 25_100, 0, undefined, NOW)).toBeCloseTo(3_012, 6)

    // At its own expiry it settles against spot and the basis is gone, so a
    // long entered at 25,100 is down 100 points a share with spot at 25,000.
    expect(legPnlAt(leg, 25_100, 30, undefined, NOW)).toBeCloseTo(0, 6)
    expect(legPnlAt(leg, 25_000, 30, undefined, NOW)).toBeCloseTo(-2_500, 6)
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
    const farExpiry = 1_817_956_800
    // A wide call vertical, both legs on the same expiry so they share one
    // carry curve. Deep in the money their slopes cancel exactly, which is the
    // flat right tail this exercises: the analysis has to widen its own window
    // past the supplied [80, 120] to find the root.
    //
    // A calendar cannot stand in here. Two expiries carry to different
    // forwards, so their deep-in-the-money slopes no longer cancel and the tail
    // is not flat -- it only looked flat while the basis was held constant at
    // every horizon, which is the bug this suite now guards against.
    const longCall = valuationOptionLeg({
      id: 'long-call',
      lotSize: 1,
      expiry: '12AUG26',
      expiryTs: farExpiry,
      strike: 100,
      price: 150,
      iv: 20,
      referenceUnderlying: 100,
      forwardPrice: 105,
    })
    const shortCall = {
      ...longCall,
      id: 'short-call',
      side: 'SELL' as const,
      strike: 300,
      price: 0,
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
      [longCall, shortCall, longFuture, shortFuture],
      100,
      0,
      0,
      [80, 120],
      10,
      0,
      20,
      now
    )

    // The two futures contribute their own market bases, a constant +10, and
    // the vertical is a 150 debit, so the root sits far outside the requested
    // window and the tail beyond the short strike is flat.
    expect(payoff.breakevens.at(-1)).toBeGreaterThan(200)
    expect(payoff.maxProfit).toBeLessThan(Infinity)
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

    // Hand-checked against an independent Black-76 at the carry rate the
    // snapshot implies, ln(25120/25000) / (3.25/365) = 0.53778726/yr.
    //   spot 25100, t = 3.25/365  -> F = 25100 * 1.0048   = 25220.4800
    //   spot 25000, t = 3.25/365  -> F = 25120 exactly (the snapshot forward)
    //   spot 25000, t = 2.25/365  -> F = 25000 * 1.003321 = 25083.0157
    // The third case is the one the old constant-basis model got wrong: a day
    // of decay pulls the forward toward spot, so the leg loses the carry as
    // well as the time value.
    expect(legPnlAt(leg, 25_100, 0, 15, now)).toBeCloseTo(3923.44, 1)
    expect(legPnlAt(leg, 25_000, 0, 20, now)).toBeCloseTo(2735.7, 1)
    expect(legPnlAt(leg, 25_000, 1, 15, now)).toBeCloseTo(-1810.41, 1)
  })
})

describe('multi-expiry structures', () => {
  const SPOT = 24_800
  const AT = new Date('2026-08-14T05:00:00.000Z')
  const NEAR_TS = AT.getTime() / 1000 + 7 * 86_400
  const FAR_TS = AT.getTime() / 1000 + 35 * 86_400
  /** One carry curve for the chain, so the far expiry carries further. */
  const forwardFor = (expiryTs: number) =>
    SPOT * Math.exp((0.06 * (expiryTs * 1000 - AT.getTime())) / (365 * 86_400_000))

  function leg(
    id: string,
    side: Side,
    optionType: OptionType,
    strike: number,
    price: number,
    expiryTs: number,
    lots = 1
  ): StrategyLeg {
    return {
      id,
      segment: 'OPTION',
      side,
      optionType,
      strike,
      lots,
      lotSize: 75,
      expiry: expiryTs === FAR_TS ? '18SEP26' : '21AUG26',
      expiryTs,
      price,
      iv: 12,
      active: true,
      symbol: id,
      referenceUnderlying: SPOT,
      forwardPrice: forwardFor(expiryTs),
    }
  }

  function payoffFor(legs: StrategyLeg[]) {
    const nearest = nearestLegDays(legs, AT)
    const range = payoffPriceRange(SPOT, legs, 12, nearest / 365)
    return computePayoff(legs, SPOT, nearest, 0, range, 240, 0, 12, AT)
  }

  // The regression these guard: a tail slope summed on quantity alone cancels
  // for every one of these structures, so the analysis called the tail flat and
  // capped the extreme at whatever the sampled window happened to reach. The
  // legs carry to different forwards, so the slopes do not actually cancel.
  it('sees unbounded upside on a call calendar whose quantities cancel', () => {
    const payoff = payoffFor([
      leg('near', 'SELL', 'CE', 24_800, 150, NEAR_TS),
      leg('far', 'BUY', 'CE', 24_800, 300, FAR_TS),
    ])

    expect(payoff.maxProfit).toBe(Infinity)
    expect(Number.isFinite(payoff.maxLoss)).toBe(true)
  })

  it('sees unbounded upside on a diagonal', () => {
    const payoff = payoffFor([
      leg('near', 'SELL', 'CE', 24_800, 150, NEAR_TS),
      leg('far', 'BUY', 'CE', 24_900, 260, FAR_TS),
    ])

    expect(payoff.maxProfit).toBe(Infinity)
  })

  it('sees unbounded upside on a double diagonal', () => {
    const payoff = payoffFor([
      leg('near-call', 'SELL', 'CE', 24_900, 120, NEAR_TS),
      leg('far-call', 'BUY', 'CE', 25_000, 240, FAR_TS),
      leg('near-put', 'SELL', 'PE', 24_700, 120, NEAR_TS),
      leg('far-put', 'BUY', 'PE', 24_600, 240, FAR_TS),
    ])

    expect(payoff.maxProfit).toBe(Infinity)
    expect(payoff.breakevens).toEqual([...payoff.breakevens].sort((a, b) => a - b))
  })

  it('settles a covered call against spot on both legs', () => {
    // The future carries a 100-point basis over spot. Held to infinity it
    // inflated max profit by exactly that basis times the quantity, and moved
    // the breakeven 100 points down, because only the option was converging.
    const carry = Math.log(24_900 / 24_800) / (7 / 365)
    const future: StrategyLeg = {
      id: 'fut',
      segment: 'FUTURE',
      side: 'BUY',
      lots: 1,
      lotSize: 75,
      expiry: '21AUG26',
      expiryTs: NEAR_TS,
      price: 24_900,
      marketPrice: 24_900,
      referenceUnderlying: 24_800,
      iv: 0,
      active: true,
      symbol: 'NIFTY21AUG26FUT',
    }
    const shortCall: StrategyLeg = {
      ...leg('short-call', 'SELL', 'CE', 25_000, 120, NEAR_TS),
      forwardPrice: 24_800 * Math.exp((carry * 7) / 365),
    }

    const payoff = payoffFor([future, shortCall])

    expect(payoff.breakevens).toEqual([expect.closeTo(24_780, 4)])
    expect(payoff.maxProfit).toBeCloseTo(16_500, 4)
    expect(payoff.maxLoss).toBeCloseTo(-1_858_500, 4)
  })

  it('keeps an iron condor defined-risk when one wing has no forward', () => {
    // A chain fetched without Greeks reports no forward, and a leg outside the
    // loaded strike window keeps a stale snapshot. Inferring the carry per leg
    // then gives siblings on ONE expiry different factors, their slopes stop
    // cancelling, and a defined-risk position reports an unlimited loss.
    const condor = [
      leg('long-put', 'BUY', 'PE', 24_600, 30, NEAR_TS),
      leg('short-put', 'SELL', 'PE', 24_700, 60, NEAR_TS),
      leg('short-call', 'SELL', 'CE', 24_900, 60, NEAR_TS),
      { ...leg('long-call', 'BUY', 'CE', 25_000, 30, NEAR_TS), forwardPrice: undefined },
    ]

    const payoff = payoffFor(condor)

    expect(Number.isFinite(payoff.maxLoss)).toBe(true)
    expect(Number.isFinite(payoff.maxProfit)).toBe(true)
    expect(payoff.maxLoss).toBeCloseTo(-3_000, 4)
    expect(payoff.maxProfit).toBeCloseTo(4_500, 4)
  })

  it('reports calendar breakevens of the strategy, not of the analysis window', () => {
    // Equal premiums leave the far tail flat on exactly zero. The scan used to
    // report its own outermost grid point as a breakeven, so the number moved
    // whenever the requested window did.
    const legs = [
      leg('near', 'SELL', 'PE', 24_800, 40, NEAR_TS),
      leg('far', 'BUY', 'PE', 24_800, 40, FAR_TS),
    ]
    const nearest = nearestLegDays(legs, AT)
    const narrow = computePayoff(legs, SPOT, nearest, 0, [22_320, 27_280], 240, 0, 12, AT)
    const wide = computePayoff(legs, SPOT, nearest, 0, [22_320, 60_000], 240, 0, 12, AT)

    expect(narrow.breakevens.every((value) => value > 0)).toBe(true)
    expect(wide.breakevens.every((value) => value > 0)).toBe(true)
    expect(narrow.breakevens.every((value) => value < 40_000)).toBe(true)
    expect(wide.breakevens.every((value) => value < 40_000)).toBe(true)
  })

  it('caps a batman below and leaves its upside loss unbounded', () => {
    // Single expiry: a call ratio spread above and a put ratio spread below.
    // Short two calls against one long, so the right tail falls away without
    // limit; the put side is bounded because spot cannot go below zero.
    const payoff = payoffFor([
      leg('call-long', 'BUY', 'CE', 25_300, 40, NEAR_TS),
      leg('call-short', 'SELL', 'CE', 25_550, 20, NEAR_TS, 2),
      leg('put-long', 'BUY', 'PE', 24_300, 40, NEAR_TS),
      leg('put-short', 'SELL', 'PE', 24_050, 20, NEAR_TS, 2),
    ])

    expect(payoff.maxLoss).toBe(-Infinity)
    expect(Number.isFinite(payoff.maxProfit)).toBe(true)
  })
})

describe('payoff geometry and structural risk', () => {
  it('strikes the terminal payoff against spot, not the carried forward', () => {
    const shiftedForwardCall = valuationOptionLeg({
      lotSize: 1,
      strike: 100,
      price: 5,
      expiryTs: NOW.getTime() / 1000,
      referenceUnderlying: 100,
      forwardPrice: 110,
    })

    const payoff = computePayoff([shiftedForwardCall], 100, 0, 0, [80, 120], 8, 0, 20, NOW)

    // A forward 10 points over spot does not survive to expiry: the option
    // settles against the index, so a long 100 call bought for 5 breaks even at
    // 105, not at 95.
    expect(payoff.breakevens).toEqual([105])
    expect(payoff.maxLoss).toBe(-5)
    expect(payoff.maxProfit).toBe(Infinity)
  })

  it('breaks a long put even at strike minus premium, not below the basis', () => {
    // The reported case: long 1 lot of NIFTY 24000PE at 34.15, lot 65, on a
    // chain whose parity forward sat 79.275 over spot. The chart showed a
    // breakeven of 23,886.58 and a max profit of 15,52,627.38 - both exactly
    // one basis below the truth, because the terminal payoff was struck against
    // the carried forward instead of spot.
    const now = new Date('2026-08-14T05:00:00.000Z')
    const spot = 24_350
    const expiryTs = now.getTime() / 1000 + 11 * 86_400
    const leg = valuationOptionLeg({
      side: 'BUY',
      optionType: 'PE',
      strike: 24_000,
      price: 34.15,
      lotSize: 65,
      iv: 12,
      expiryTs,
      referenceUnderlying: spot,
      forwardPrice: spot + 79.275,
    })

    const payoff = computePayoff([leg], spot, 11, 0, [22_320, 27_280], 240, 0, 12, now)

    expect(payoff.breakevens).toEqual([expect.closeTo(23_965.85, 6)])
    expect(payoff.maxProfit).toBeCloseTo(1_557_780.25, 4)
    expect(payoff.maxLoss).toBeCloseTo(-2_219.75, 6)
  })

  it('does not pin the plotted domain to zero for a leg in contango', () => {
    // Regression: the forward-zero vertex is `referenceUnderlying -
    // forwardPrice`, which is negative whenever the forward trades above spot
    // and so clamps to 0. Framing the chart with it collapsed the x-axis to
    // [0, hi] for every ordinary index strategy.
    const shortPut = valuationOptionLeg({
      side: 'SELL',
      optionType: 'PE',
      strike: 24_800,
      price: 150,
      lotSize: 75,
      expiryTs: NOW.getTime() / 1000,
      referenceUnderlying: 24_800,
      forwardPrice: 24_850,
    })

    const payoff = computePayoff([shortPut], 24_800, 0, 0, [22_320, 27_280], 60, 0, 12, NOW)

    // The requested lower bound survives instead of being dragged to zero.
    expect(payoff.samples[0].underlying).toBeCloseTo(22_320, 6)
    expect(payoff.samples.every((sample) => sample.underlying >= 22_320)).toBe(true)
    // Struck against spot at expiry: 24800 - 150.
    expect(payoff.breakevens).toEqual([24_650])

    // Max loss is still evaluated at S = 0, where the put is worth its full
    // strike: (24800 - 150) * 75.
    expect(payoff.maxLoss).toBeCloseTo(-1_848_750, 6)
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

  it('reports a flat-zero span as its edges, not a breakeven at every sample', () => {
    // A calendar whose legs were entered at the same premium is worth exactly
    // zero far from the strike, because both legs are deep in the money and the
    // far leg has no time value left. Sampling that tail once per grid point
    // used to emit hundreds of roots, and since the chart frames the outermost
    // breakeven it stretched the domain to twice spot.
    const now = new Date('2026-07-28T10:00:00.000Z')
    const nearExpiryTs = now.getTime() / 1000 + 7 * 86_400
    const farExpiryTs = now.getTime() / 1000 + 35 * 86_400
    const shared = {
      lotSize: 75,
      strike: 24_800,
      price: 40,
      iv: 12,
      referenceUnderlying: 24_800,
      forwardPrice: 24_850,
    }
    const legs = [
      valuationOptionLeg({ ...shared, id: 'near', side: 'SELL', expiryTs: nearExpiryTs }),
      valuationOptionLeg({ ...shared, id: 'far', side: 'BUY', expiryTs: farExpiryTs }),
    ]

    const nearest = nearestLegDays(legs, now)
    const payoff = computePayoff(legs, 24_800, nearest, 0, [22_320, 27_280], 240, 0, 12, now)

    expect(payoff.breakevens.length).toBeLessThanOrEqual(4)
    expect(payoff.samples.at(-1)?.underlying).toBeLessThan(50_000)
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
