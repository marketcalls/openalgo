import { describe, expect, it } from 'vitest'
import {
  black76Greeks,
  black76Price,
  chainGreeks,
  forwardFromParity,
  impliedVolatility,
  legGreeks,
  normCdf,
  priceForGreeks,
  yearsToExpiry,
} from './optionGreeks'

/**
 * Reference values generated from the `opengreeks` Rust library (Black-76), the
 * same implementation `services/option_greeks_service.py` calls. These pin the
 * browser-side math to the server's so the option chain and
 * `/api/v1/optiongreeks` cannot silently drift apart.
 *
 * Regenerate with opengreeks.black76.{black,implied_volatility,delta,gamma,theta,vega}.
 */
const GOLDEN = [
  {
    label: 'atm 7d c',
    flag: 'c' as const,
    F: 24000.0,
    K: 24000.0,
    t: 0.019178082191780823,
    r: 0.0,
    price: 192.2580800966898,
    iv: 0.14499999999999694,
    delta: 0.5040053766686811,
    gamma: 0.0008277636376495706,
    theta: -13.732258571768984,
    vega: 13.258732414121775,
  },
  {
    label: 'atm 7d p',
    flag: 'p' as const,
    F: 24000.0,
    K: 24000.0,
    t: 0.019178082191780823,
    r: 0.0,
    price: 192.2580800966898,
    iv: 0.14499999999999694,
    delta: -0.49599462333131894,
    gamma: 0.0008277636376495706,
    theta: -13.732258571768984,
    vega: 13.258732414121775,
  },
  {
    label: 'otm 7d c',
    flag: 'c' as const,
    F: 24000.0,
    K: 25000.0,
    t: 0.019178082191780823,
    r: 0.0,
    price: 16.779852479276315,
    iv: 0.18999999999998973,
    delta: 0.06198827359123628,
    gamma: 0.00019350672320791714,
    theta: -5.5119197256111585,
    vega: 4.061414534660854,
  },
  {
    label: 'otm 7d p',
    flag: 'p' as const,
    F: 24000.0,
    K: 25000.0,
    t: 0.019178082191780823,
    r: 0.0,
    price: 1016.7798524792779,
    iv: 0.1900000000000082,
    delta: -0.9380117264087637,
    gamma: 0.00019350672320791714,
    theta: -5.5119197256111585,
    vega: 4.061414534660854,
  },
  {
    label: 'itm 7d c',
    flag: 'c' as const,
    F: 24000.0,
    K: 23000.0,
    t: 0.019178082191780823,
    r: 0.0,
    price: 1021.7517103513492,
    iv: 0.21000000000000466,
    delta: 0.930293954588756,
    gamma: 0.00019174878027418657,
    theta: -6.672227146592847,
    vega: 4.448151431061897,
  },
  {
    label: 'itm 7d p',
    flag: 'p' as const,
    F: 24000.0,
    K: 23000.0,
    t: 0.019178082191780823,
    r: 0.0,
    price: 21.75171035135031,
    iv: 0.21000000000001373,
    delta: -0.069706045411244,
    gamma: 0.00019174878027418657,
    theta: -6.672227146592847,
    vega: 4.448151431061897,
  },
  {
    label: 'deep otm 2d c',
    flag: 'c' as const,
    F: 24000.0,
    K: 26000.0,
    t: 0.005479452054794521,
    r: 0.0,
    price: 0.17965380649746265,
    iv: 0.3500000000000394,
    delta: 0.0010471461343988166,
    gamma: 5.648890879193433e-6,
    theta: -0.5460078636108062,
    vega: 0.06240089869837787,
  },
  {
    label: 'deep otm 2d p',
    flag: 'p' as const,
    F: 24000.0,
    K: 26000.0,
    t: 0.005479452054794521,
    r: 0.0,
    price: 2000.1796538064991,
    iv: 0.3500000000091711,
    delta: -0.9989528538656012,
    gamma: 5.648890879193433e-6,
    theta: -0.5460078636108062,
    vega: 0.06240089869837787,
  },
  {
    label: 'near expiry 4h c',
    flag: 'c' as const,
    F: 24000.0,
    K: 24050.0,
    t: 0.00045662100456621003,
    r: 0.0,
    price: 7.255138197684573,
    iv: 0.12000000000000843,
    delta: 0.20887577807036753,
    gamma: 0.004668247184536913,
    theta: -53.04151979099037,
    vega: 1.4733755497497325,
  },
  {
    label: 'near expiry 4h p',
    flag: 'p' as const,
    F: 24000.0,
    K: 24050.0,
    t: 0.00045662100456621003,
    r: 0.0,
    price: 57.25513819768457,
    iv: 0.12000000000019669,
    delta: -0.7911242219296325,
    gamma: 0.004668247184536913,
    theta: -53.04151979099037,
    vega: 1.4733755497497325,
  },
  {
    label: 'long 180d c',
    flag: 'c' as const,
    F: 24000.0,
    K: 24000.0,
    t: 0.4931506849315068,
    r: 0.0,
    price: 873.7831949727006,
    iv: 0.1300000000000002,
    delta: 0.5182038165619313,
    gamma: 0.0001818918381402533,
    theta: -2.425490286565043,
    vega: 67.16742332026274,
  },
  {
    label: 'long 180d p',
    flag: 'p' as const,
    F: 24000.0,
    K: 24000.0,
    t: 0.4931506849315068,
    r: 0.0,
    price: 873.7831949727006,
    iv: 0.1299999999999999,
    delta: -0.48179618343806874,
    gamma: 0.0001818918381402533,
    theta: -2.425490286565043,
    vega: 67.16742332026274,
  },
  {
    label: 'with rate c',
    flag: 'c' as const,
    F: 24000.0,
    K: 24500.0,
    t: 0.0821917808219178,
    r: 0.065,
    price: 224.11827128255712,
    iv: 0.15500000000000022,
    delta: 0.32756521735273736,
    gamma: 0.00033748145600977637,
    theta: -6.357627404902681,
    vega: 24.764666624016026,
  },
  {
    label: 'with rate p',
    flag: 'p' as const,
    F: 24000.0,
    K: 24500.0,
    t: 0.0821917808219178,
    r: 0.065,
    price: 721.4541612008545,
    iv: 0.1549999999999996,
    delta: -0.667106562483852,
    gamma: 0.00033748145600977637,
    theta: -6.269060739574764,
    vega: 24.764666624016026,
  },
  {
    label: 'bank 30d c',
    flag: 'c' as const,
    F: 52000.0,
    K: 52500.0,
    t: 0.0821917808219178,
    r: 0.0,
    price: 523.4310976594134,
    iv: 0.12500000000000977,
    delta: 0.4016364920696951,
    gamma: 0.0002075424269387043,
    theta: -12.011873339945556,
    vega: 57.65699203173867,
  },
  {
    label: 'bank 30d p',
    flag: 'p' as const,
    F: 52000.0,
    K: 52500.0,
    t: 0.0821917808219178,
    r: 0.0,
    price: 1023.4310976594134,
    iv: 0.125000000000001,
    delta: -0.5983635079303049,
    gamma: 0.0002075424269387043,
    theta: -12.011873339945556,
    vega: 57.65699203173867,
  },
  {
    label: 'mcx crude c',
    flag: 'c' as const,
    F: 6200.0,
    K: 6300.0,
    t: 0.0547945205479452,
    r: 0.0,
    price: 118.23788513784848,
    iv: 0.28000000000000175,
    delta: 0.41630783406695304,
    gamma: 0.0009600464456751342,
    theta: -3.963408401569,
    vega: 5.662012002241426,
  },
  {
    label: 'mcx crude p',
    flag: 'p' as const,
    F: 6200.0,
    K: 6300.0,
    t: 0.0547945205479452,
    r: 0.0,
    price: 218.23788513784848,
    iv: 0.2800000000000006,
    delta: -0.583692165933047,
    gamma: 0.0009600464456751342,
    theta: -3.963408401569,
    vega: 5.662012002241426,
  },
  {
    label: 'cds usdinr c',
    flag: 'c' as const,
    F: 88.5,
    K: 89.0,
    t: 0.0410958904109589,
    r: 0.0,
    price: 0.13269791501657124,
    iv: 0.04499999999999876,
    delta: 0.269932970947923,
    gamma: 0.40949980185408447,
    theta: -0.00889697570783575,
    vega: 0.05931317138557167,
  },
  {
    label: 'cds usdinr p',
    flag: 'p' as const,
    F: 88.5,
    K: 89.0,
    t: 0.0410958904109589,
    r: 0.0,
    price: 0.6326979150165641,
    iv: 0.04499999999999567,
    delta: -0.730067029052077,
    gamma: 0.40949980185408447,
    theta: -0.00889697570783575,
    vega: 0.05931317138557167,
  },
]

/** Relative comparison, so gamma at 5e-6 is held to the same standard as vega at 67. */
function expectClose(actual: number, expected: number, rtol: number, label: string) {
  const scale = Math.max(Math.abs(expected), 1e-12)
  const relErr = Math.abs(actual - expected) / scale
  expect(relErr, `${label}: got ${actual}, expected ${expected}`).toBeLessThan(rtol)
}

describe('normCdf', () => {
  it('matches known values to double precision', () => {
    expect(normCdf(0)).toBeCloseTo(0.5, 15)
    expect(normCdf(1)).toBeCloseTo(0.841344746068543, 14)
    expect(normCdf(-1)).toBeCloseTo(0.158655253931457, 14)
    expect(normCdf(1.96)).toBeCloseTo(0.9750021048517795, 14)
    expect(normCdf(-3)).toBeCloseTo(0.0013498980316300933, 14)
    // Hart's rational approximation lands within a few ULP of 1 in the far tail.
    expect(normCdf(8)).toBeCloseTo(1, 14)
    expect(normCdf(-8)).toBeCloseTo(6.220960574271786e-16, 20)
  })

  it('is symmetric', () => {
    for (const x of [0.1, 0.5, 1.3, 2.7, 4.2, 6.9, 7.5]) {
      expect(normCdf(x) + normCdf(-x)).toBeCloseTo(1, 14)
    }
  })
})

// Tolerances are set just above the floor where this normal CDF and the Rust
// library's diverge on deep-tail values -- around 1e-12 relative on price and
// 1e-9 on the smallest gammas. Both are many orders tighter than the 2 to 4
// decimal places the chain actually renders.
const PRICE_RTOL = 1e-10
const GREEK_RTOL = 1e-8

describe('parity with the opengreeks Rust library', () => {
  it.each(GOLDEN)('prices $label identically', ({ label, flag, F, K, t, r, iv, price }) => {
    expectClose(black76Price(flag, F, K, t, r, iv), price, PRICE_RTOL, `${label} price`)
  })

  it.each(GOLDEN)('recovers implied volatility for $label', ({
    label,
    flag,
    F,
    K,
    t,
    r,
    price,
    iv,
  }) => {
    const solved = impliedVolatility(price, flag, F, K, t, r)
    expect(solved, `${label}: solver returned null`).not.toBeNull()
    expect(Math.abs((solved as number) - iv), `${label} iv`).toBeLessThan(1e-6)
  })

  it.each(GOLDEN)('matches Greeks for $label', ({
    label,
    flag,
    F,
    K,
    t,
    r,
    iv,
    delta,
    gamma,
    theta,
    vega,
  }) => {
    const g = black76Greeks(flag, F, K, t, r, iv)
    expectClose(g.delta, delta, GREEK_RTOL, `${label} delta`)
    expectClose(g.gamma, gamma, GREEK_RTOL, `${label} gamma`)
    expectClose(g.theta, theta, GREEK_RTOL, `${label} theta`)
    expectClose(g.vega, vega, GREEK_RTOL, `${label} vega`)
  })

  it.each(GOLDEN)('legGreeks reproduces $label end to end from price alone', ({
    label,
    flag,
    F,
    K,
    t,
    r,
    price,
    delta,
    gamma,
    theta,
    vega,
    iv,
  }) => {
    const g = legGreeks(flag, F, K, t, r * 100, price)
    expect(g, `${label}: legGreeks returned null`).not.toBeNull()
    const got = g as NonNullable<typeof g>
    expectClose(got.iv, iv * 100, 1e-6, `${label} iv`)
    expectClose(got.delta, delta, 1e-6, `${label} delta`)
    expectClose(got.gamma, gamma, 1e-6, `${label} gamma`)
    expectClose(got.theta, theta, 1e-6, `${label} theta`)
    expectClose(got.vega, vega, 1e-6, `${label} vega`)
  })
})

describe('legGreeks fallbacks', () => {
  const F = 24000
  const t = 7 / 365

  it('returns null when the leg has no price', () => {
    expect(legGreeks('c', F, 24000, t, 0, 0)).toBeNull()
  })

  it('returns null when the chain has expired', () => {
    expect(legGreeks('c', F, 24000, 0, 0, 100)).toBeNull()
  })

  it('collapses an in-the-money leg priced at intrinsic to delta 1', () => {
    const g = legGreeks('c', F, 23000, t, 0, 1000)
    expect(g).toEqual({ iv: 0, delta: 1, gamma: 0, theta: 0, vega: 0 })
  })

  it('collapses an in-the-money put priced at intrinsic to delta -1', () => {
    const g = legGreeks('p', F, 25000, t, 0, 1000)
    expect(g).toEqual({ iv: 0, delta: -1, gamma: 0, theta: 0, vega: 0 })
  })

  it('collapses a leg priced below intrinsic rather than emitting noise', () => {
    const g = legGreeks('c', F, 23000, t, 0, 500)
    expect(g).toEqual({ iv: 0, delta: 1, gamma: 0, theta: 0, vega: 0 })
  })

  it('gives an unconvergeable out-of-the-money leg delta 0, not delta 1', () => {
    // Priced at or above the forward, so no volatility can reproduce it. An OTM
    // leg is worth ~0 and has ~0 delta; keying the fallback off the option type
    // alone would wrongly report a full-delta position.
    const g = legGreeks('c', F, 26000, t, 0, 25000)
    expect(g).toEqual({ iv: 0, delta: 0, gamma: 0, theta: 0, vega: 0 })
  })
})

describe('priceForGreeks', () => {
  it('prefers the mid when the book is two-sided', () => {
    expect(priceForGreeks(100, 99, 101)).toBe(100)
    expect(priceForGreeks(100, 98, 102)).toBe(100)
    expect(priceForGreeks(90, 99, 101)).toBe(100)
  })

  it('falls back to LTP when the book is missing or one-sided', () => {
    expect(priceForGreeks(95, 0, 0)).toBe(95)
    expect(priceForGreeks(95, 99, 0)).toBe(95)
    expect(priceForGreeks(95, 0, 101)).toBe(95)
    expect(priceForGreeks(95, undefined, undefined)).toBe(95)
  })

  it('falls back to LTP when the book is crossed', () => {
    expect(priceForGreeks(95, 102, 98)).toBe(95)
  })

  it('returns 0 when there is nothing usable', () => {
    expect(priceForGreeks(0, 0, 0)).toBe(0)
    expect(priceForGreeks(undefined, undefined, undefined)).toBe(0)
  })
})

describe('forwardFromParity', () => {
  it('recovers the forward from the ATM legs', () => {
    // A NIFTY future 80 points over spot: parity must find it, not the spot LTP.
    expect(forwardFromParity(24000, 350, 270, 23950)).toBeCloseTo(24080, 10)
  })

  it('falls back to the underlying LTP when an ATM leg is unpriced', () => {
    expect(forwardFromParity(24000, 0, 270, 23950)).toBe(23950)
    expect(forwardFromParity(24000, 350, 0, 23950)).toBe(23950)
    expect(forwardFromParity(undefined, 350, 270, 23950)).toBe(23950)
  })
})

describe('yearsToExpiry', () => {
  it('returns 0 for a missing or past expiry', () => {
    expect(yearsToExpiry(undefined)).toBe(0)
    expect(yearsToExpiry(null)).toBe(0)
    expect(yearsToExpiry(Math.floor(Date.now() / 1000) - 60)).toBe(0)
  })

  it('measures a week out in years', () => {
    const weekAway = Math.floor(Date.now() / 1000) + 7 * 86400
    expect(yearsToExpiry(weekAway)).toBeCloseTo(7 / 365, 5)
  })

  it('applies the server clock offset', () => {
    // The offset is serverNow - clientNow. A negative offset means the client
    // clock runs fast, so the corrected "now" moves earlier and more time
    // remains to expiry, not less.
    const expiry = Math.floor(Date.now() / 1000) + 7 * 86400
    expect(yearsToExpiry(expiry, -86400 * 1000)).toBeCloseTo(8 / 365, 5)
    expect(yearsToExpiry(expiry, 86400 * 1000)).toBeCloseTo(6 / 365, 5)
    expect(yearsToExpiry(expiry, 0)).toBeCloseTo(7 / 365, 5)
  })
})

describe('chainGreeks', () => {
  const F = 24000
  const t = 30 / 365

  it('computes both sides of a ladder', () => {
    const legs = [23800, 24000, 24200].map((strike) => ({
      strike,
      cePrice: black76Price('c', F, strike, t, 0, 0.15),
      pePrice: black76Price('p', F, strike, t, 0, 0.15),
    }))

    const out = chainGreeks(legs, F, t, 0)
    expect(out).toHaveLength(3)
    for (const row of out) {
      expect(row.ce?.iv).toBeCloseTo(15, 4)
      expect(row.pe?.iv).toBeCloseTo(15, 4)
    }
    // Both deltas fall as strikes rise: the call moves out of the money toward
    // 0, and the put moves into the money toward -1.
    expect(out[0].ce?.delta).toBeGreaterThan(out[2].ce?.delta as number)
    expect(out[0].pe?.delta).toBeGreaterThan(out[2].pe?.delta as number)
    expect(out[2].pe?.delta).toBeLessThan(-0.5)
    expect(out[0].pe?.delta).toBeGreaterThan(-0.5)
  })

  it('holds put-call parity: call delta minus put delta is the discount factor', () => {
    const legs = [{ strike: 24200, cePrice: 0, pePrice: 0 }]
    legs[0].cePrice = black76Price('c', F, 24200, t, 0, 0.15)
    legs[0].pePrice = black76Price('p', F, 24200, t, 0, 0.15)
    const [row] = chainGreeks(legs, F, t, 0)
    expect((row.ce as { delta: number }).delta - (row.pe as { delta: number }).delta).toBeCloseTo(
      1,
      9
    )
    expect(row.ce?.gamma).toBeCloseTo(row.pe?.gamma as number, 12)
    expect(row.ce?.vega).toBeCloseTo(row.pe?.vega as number, 10)
  })

  it('returns nulls rather than throwing when the forward or tenor is unusable', () => {
    const legs = [{ strike: 24000, cePrice: 100, pePrice: 100 }]
    expect(chainGreeks(legs, 0, t, 0)).toEqual([{ ce: null, pe: null }])
    expect(chainGreeks(legs, F, 0, 0)).toEqual([{ ce: null, pe: null }])
  })

  it('leaves unpriced legs null without disturbing their neighbours', () => {
    const legs = [
      { strike: 23800, cePrice: black76Price('c', F, 23800, t, 0, 0.15), pePrice: 0 },
      { strike: 24000, cePrice: 0, pePrice: black76Price('p', F, 24000, t, 0, 0.15) },
    ]
    const out = chainGreeks(legs, F, t, 0)
    expect(out[0].ce).not.toBeNull()
    expect(out[0].pe).toBeNull()
    expect(out[1].ce).toBeNull()
    expect(out[1].pe).not.toBeNull()
  })
})
