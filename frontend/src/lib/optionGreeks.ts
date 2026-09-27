/**
 * Black-76 option pricing, implied volatility and Greeks.
 *
 * This mirrors the server's `services/option_greeks_service.py`, which wraps the
 * `opengreeks` Rust library. It exists so the option chain can recompute Greeks
 * on every WebSocket tick without a round trip: the chain already streams LTP,
 * bid and ask for every leg, and a full 80-leg chain costs well under a
 * millisecond here.
 *
 * Conventions are matched to opengreeks so the two surfaces agree:
 *   - vega is per 1% change in volatility (raw vega x 0.01)
 *   - theta is per calendar day (raw theta / 365)
 *   - implied volatility is returned as a percentage, not a decimal
 *
 * Black-76 prices off the forward rather than spot, which is the correct model
 * for Indian F&O. See `forwardFromParity` for how the forward is derived.
 */

export type OptionFlag = 'c' | 'p'

export interface Greeks {
  /** Implied volatility as a percentage, e.g. 14.5 for 14.5% */
  iv: number
  delta: number
  gamma: number
  /** Per calendar day */
  theta: number
  /** Per 1% change in implied volatility */
  vega: number
}

export interface ChainLegInput {
  strike: number
  /** Call price to invert, 0 when there is no usable quote */
  cePrice: number
  /** Put price to invert, 0 when there is no usable quote */
  pePrice: number
}

export interface ChainLegGreeks {
  ce: Greeks | null
  pe: Greeks | null
}

/** Below this many years to expiry the model output is meaningless. */
const MIN_TIME_TO_EXPIRY = 1e-8

/** Volatility search bracket for the implied-volatility solver. */
const MIN_VOL = 1e-4
const MAX_VOL = 5.0

const SQRT_2PI = Math.sqrt(2 * Math.PI)

/**
 * Cumulative standard normal distribution (Hart 1968, as popularised by West).
 *
 * Accurate to roughly double precision across the whole range. The usual
 * Abramowitz-Stegun 7.1.26 approximation is only good to about 1e-7, which is
 * not enough to keep an implied-volatility solve in agreement with the server.
 */
export function normCdf(x: number): number {
  const z = Math.abs(x)
  let c = 0

  if (z <= 37) {
    const e = Math.exp((-z * z) / 2)
    if (z < 7.07106781186547) {
      let b = 3.52624965998911e-2 * z + 0.700383064443688
      b = b * z + 6.37396220353165
      b = b * z + 33.912866078383
      b = b * z + 112.079291497871
      b = b * z + 221.213596169931
      b = b * z + 220.206867912376
      let d = 8.83883476483184e-2 * z + 1.75566716318264
      d = d * z + 16.064177579207
      d = d * z + 86.7807322029461
      d = d * z + 296.564248779674
      d = d * z + 637.333633378831
      d = d * z + 793.826512519948
      d = d * z + 440.413735824752
      c = (e * b) / d
    } else {
      let b = z + 0.65
      b = z + 4 / b
      b = z + 3 / b
      b = z + 2 / b
      b = z + 1 / b
      c = e / (b * 2.506628274631)
    }
  }

  return x > 0 ? 1 - c : c
}

/** Standard normal probability density. */
export function normPdf(x: number): number {
  return Math.exp((-x * x) / 2) / SQRT_2PI
}

function d1d2(F: number, K: number, t: number, sigma: number): [number, number] {
  const vol = sigma * Math.sqrt(t)
  const d1 = (Math.log(F / K) + (sigma * sigma * t) / 2) / vol
  return [d1, d1 - vol]
}

/**
 * Black-76 option price.
 *
 * @param flag - 'c' for call, 'p' for put
 * @param F - Forward price
 * @param K - Strike
 * @param t - Time to expiry in years
 * @param r - Risk-free rate as a decimal, e.g. 0.065 for 6.5%
 * @param sigma - Volatility as a decimal
 */
export function black76Price(
  flag: OptionFlag,
  F: number,
  K: number,
  t: number,
  r: number,
  sigma: number
): number {
  const [d1, d2] = d1d2(F, K, t, sigma)
  const df = Math.exp(-r * t)
  return flag === 'c'
    ? df * (F * normCdf(d1) - K * normCdf(d2))
    : df * (K * normCdf(-d2) - F * normCdf(-d1))
}

/** Raw Black-76 vega, before the per-1% scaling. */
function rawVega(F: number, K: number, t: number, r: number, sigma: number): number {
  const [d1] = d1d2(F, K, t, sigma)
  return Math.exp(-r * t) * F * normPdf(d1) * Math.sqrt(t)
}

/**
 * Solve for implied volatility from an option price.
 *
 * Newton-Raphson using vega, falling back to bisection when Newton leaves the
 * search bracket or stalls. Deep out-of-the-money legs have near-zero vega and
 * make Newton alone unreliable, which is exactly where a chain shows its most
 * jagged numbers, so the bisection safety net matters.
 *
 * @returns Volatility as a decimal, or null when the price is not invertible
 */
export function impliedVolatility(
  price: number,
  flag: OptionFlag,
  F: number,
  K: number,
  t: number,
  r: number
): number | null {
  if (!(price > 0) || !(F > 0) || !(K > 0) || !(t > MIN_TIME_TO_EXPIRY)) return null

  const df = Math.exp(-r * t)
  // No volatility can price an option below its discounted intrinsic value, and
  // the forward bounds it from above.
  const intrinsic = df * (flag === 'c' ? Math.max(F - K, 0) : Math.max(K - F, 0))
  const upperBound = df * (flag === 'c' ? F : K)
  if (price <= intrinsic || price >= upperBound) return null

  let sigma = 0.25
  for (let i = 0; i < 20; i++) {
    const diff = black76Price(flag, F, K, t, r, sigma) - price
    if (Math.abs(diff) < 1e-8) return sigma

    const v = rawVega(F, K, t, r, sigma)
    if (!(v > 1e-10)) break

    const next = sigma - diff / v
    if (!Number.isFinite(next) || next <= MIN_VOL || next >= MAX_VOL) break
    if (Math.abs(next - sigma) < 1e-10) return next
    sigma = next
  }

  // Newton did not settle; bisect, which cannot diverge given the bracket above.
  let lo = MIN_VOL
  let hi = MAX_VOL
  for (let i = 0; i < 100; i++) {
    const mid = (lo + hi) / 2
    const diff = black76Price(flag, F, K, t, r, mid) - price
    if (Math.abs(diff) < 1e-8 || hi - lo < 1e-10) return mid
    if (diff > 0) hi = mid
    else lo = mid
  }

  return null
}

/**
 * Black-76 Greeks at a known volatility, in the same units opengreeks returns.
 *
 * @param sigma - Volatility as a decimal
 */
export function black76Greeks(
  flag: OptionFlag,
  F: number,
  K: number,
  t: number,
  r: number,
  sigma: number
): Omit<Greeks, 'iv'> {
  const [d1, d2] = d1d2(F, K, t, sigma)
  const df = Math.exp(-r * t)
  const sqrtT = Math.sqrt(t)
  const pdf = normPdf(d1)

  const price =
    flag === 'c'
      ? df * (F * normCdf(d1) - K * normCdf(d2))
      : df * (K * normCdf(-d2) - F * normCdf(-d1))

  // Theta carries a discounting term that vanishes at r = 0, which is the
  // platform default, so calls and puts then share one theta.
  const thetaRaw = (-F * df * pdf * sigma) / (2 * sqrtT) + r * price

  return {
    delta: flag === 'c' ? df * normCdf(d1) : -df * normCdf(-d1),
    gamma: (df * pdf) / (F * sigma * sqrtT),
    theta: thetaRaw / 365,
    vega: df * F * pdf * sqrtT * 0.01,
  }
}

/**
 * Greeks for a single leg, inverting implied volatility from its price.
 *
 * Mirrors the server's fallbacks so the two never disagree on an edge case:
 * a leg with no time value, or one whose volatility will not converge, returns
 * theoretical Greeks rather than noise. An in-the-money leg collapses to a
 * delta of +/-1; an out-of-the-money one to 0.
 *
 * @param ratePct - Risk-free rate as an annualized percentage
 * @returns Greeks, or null when the leg has no usable price at all
 */
export function legGreeks(
  flag: OptionFlag,
  F: number,
  K: number,
  t: number,
  ratePct: number,
  price: number
): Greeks | null {
  if (!(price > 0) || !(K > 0) || !(F > 0) || !(t > MIN_TIME_TO_EXPIRY)) return null

  const r = (ratePct || 0) / 100
  const intrinsic = flag === 'c' ? Math.max(F - K, 0) : Math.max(K - F, 0)
  const timeValue = price - intrinsic

  const theoretical = (): Greeks => ({
    iv: 0,
    delta: intrinsic > 0 ? (flag === 'c' ? 1 : -1) : 0,
    gamma: 0,
    theta: 0,
    vega: 0,
  })

  if (timeValue <= 0 || (intrinsic > 0 && timeValue < 0.01)) return theoretical()

  const sigma = impliedVolatility(price, flag, F, K, t, r)
  if (sigma === null || !Number.isFinite(sigma) || sigma <= 0) return theoretical()

  const g = black76Greeks(flag, F, K, t, r, sigma)
  if (!Number.isFinite(g.delta) || !Number.isFinite(g.gamma)) return theoretical()

  return { iv: sigma * 100, ...g }
}

/**
 * Pick the price to invert implied volatility from.
 *
 * The mid is preferred over LTP: on an illiquid strike the last trade can be
 * minutes stale while the book is still live, and a stale price makes IV and
 * every Greek derived from it jump around. Falls back to LTP when the book is
 * missing or crossed.
 */
export function priceForGreeks(
  ltp: number | undefined,
  bid: number | undefined,
  ask: number | undefined
): number {
  if (bid !== undefined && ask !== undefined && bid > 0 && ask > 0 && ask >= bid) {
    return (bid + ask) / 2
  }
  return ltp && ltp > 0 ? ltp : 0
}

/**
 * Derive the forward price from the ATM call and put via put-call parity.
 *
 * Black-76 prices off the forward, and Indian index futures trade at a premium
 * to spot. Using the spot LTP instead would bias every delta in the chain, so
 * the synthetic future built from the ATM legs (which are already streaming) is
 * used whenever both are priced.
 *
 * @param fallback - Underlying LTP, used when the ATM legs are unpriced
 */
export function forwardFromParity(
  atmStrike: number | undefined,
  atmCePrice: number | undefined,
  atmPePrice: number | undefined,
  fallback: number
): number {
  if (atmStrike && atmCePrice && atmPePrice && atmCePrice > 0 && atmPePrice > 0) {
    return atmStrike + atmCePrice - atmPePrice
  }
  return fallback
}

/**
 * Time to expiry in years.
 *
 * `clockOffsetMs` corrects the browser clock against the server's, since a
 * skewed client clock would otherwise silently bias every Greek on the page.
 *
 * @param expiryTs - Expiry instant as epoch seconds
 * @param clockOffsetMs - serverNow - clientNow, in milliseconds
 */
export function yearsToExpiry(expiryTs: number | undefined | null, clockOffsetMs = 0): number {
  if (!expiryTs) return 0
  const nowMs = Date.now() + clockOffsetMs
  const seconds = expiryTs * 1000 - nowMs
  if (seconds <= 0) return 0
  return seconds / 1000 / 86400 / 365
}

/**
 * Compute Greeks for a whole strike ladder in one pass.
 *
 * @param legs - Strike ladder with the price to invert for each side
 * @param forward - Forward price, from `forwardFromParity`
 * @param t - Time to expiry in years, from `yearsToExpiry`
 * @param ratePct - Risk-free rate as an annualized percentage
 */
export function chainGreeks(
  legs: ChainLegInput[],
  forward: number,
  t: number,
  ratePct = 0
): ChainLegGreeks[] {
  if (!(forward > 0) || !(t > MIN_TIME_TO_EXPIRY)) {
    return legs.map(() => ({ ce: null, pe: null }))
  }

  return legs.map((leg) => ({
    ce: legGreeks('c', forward, leg.strike, t, ratePct, leg.cePrice),
    pe: legGreeks('p', forward, leg.strike, t, ratePct, leg.pePrice),
  }))
}
