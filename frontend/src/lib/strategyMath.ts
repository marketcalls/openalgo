/**
 * Options math for the Strategy Builder.
 *
 * Uses the Black-Scholes model on spot (for intra-expiry "T+0" pricing in the
 * payoff simulator) and a simple intrinsic payoff at expiry. IV / live prices
 * come from the server's Black-76 greeks service — this file only re-prices
 * the same legs under what-if shifts (spot %, IV %, days).
 */

export type OptionType = 'CE' | 'PE'
export type Side = 'BUY' | 'SELL'
export type Segment = 'OPTION' | 'FUTURE'

export interface StrategyLeg {
  id: string
  segment: Segment
  side: Side
  lots: number
  lotSize: number
  expiry: string // OpenAlgo format, e.g. 28APR26
  strike?: number // required for options
  optionType?: OptionType // required for options
  /** Live / entry premium (per share, not per lot). 0 if unknown. */
  price: number
  /** Live IV (%) at the time of building. 0 if unknown. */
  iv: number
  active: boolean
  /** Symbol for display / Greeks lookup */
  symbol: string
  /**
   * Exit price (per share). When > 0 the leg is treated as "closed":
   * P&L is frozen at (exitPrice - entryPrice) * qty * sign for every
   * underlying value, and it no longer responds to spot/IV/time shifts.
   */
  exitPrice?: number
}

const SQRT2 = Math.SQRT2
const SQRT2PI = Math.sqrt(2 * Math.PI)

/** Error function approximation (Abramowitz & Stegun 7.1.26, max error ~1.5e-7). */
function erf(x: number): number {
  const sign = Math.sign(x) || 1
  const ax = Math.abs(x)
  const t = 1 / (1 + 0.3275911 * ax)
  const y =
    1 -
    ((((1.061405429 * t - 1.453152027) * t + 1.421413741) * t - 0.284496736) * t + 0.254829592) *
      t *
      Math.exp(-ax * ax)
  return sign * y
}

/** Standard normal CDF. */
export function normCdf(x: number): number {
  return 0.5 * (1 + erf(x / SQRT2))
}

/** Standard normal PDF. */
export function normPdf(x: number): number {
  return Math.exp(-0.5 * x * x) / SQRT2PI
}

export interface BsInputs {
  spot: number
  strike: number
  /** Time to expiry in years. Must be > 0 for the formula; we floor at a tiny epsilon. */
  t: number
  /** Implied volatility as decimal (0.15 = 15%). */
  iv: number
  /** Risk-free rate as decimal (0.0 default for INR index options). */
  r?: number
  /** Dividend yield as decimal. */
  q?: number
}

/** Black-Scholes price for a European option on spot. */
export function bsPrice(type: OptionType, inp: BsInputs): number {
  const { spot, strike, iv } = inp
  const r = inp.r ?? 0
  const q = inp.q ?? 0
  const t = Math.max(inp.t, 1e-8)

  // Intrinsic fallback for zero-vol or zero-time.
  if (iv <= 0 || t <= 1e-8) {
    return intrinsic(type, spot, strike)
  }

  const d1 = (Math.log(spot / strike) + (r - q + 0.5 * iv * iv) * t) / (iv * Math.sqrt(t))
  const d2 = d1 - iv * Math.sqrt(t)

  if (type === 'CE') {
    return spot * Math.exp(-q * t) * normCdf(d1) - strike * Math.exp(-r * t) * normCdf(d2)
  }
  return strike * Math.exp(-r * t) * normCdf(-d2) - spot * Math.exp(-q * t) * normCdf(-d1)
}

export function intrinsic(type: OptionType, spot: number, strike: number): number {
  return type === 'CE' ? Math.max(spot - strike, 0) : Math.max(strike - spot, 0)
}

/**
 * Payoff of a single leg at a given underlying price, advanced `daysElapsed`
 * from `now`.
 *
 * Each leg computes its OWN remaining time from its own expiry, which is
 * critical for calendar/diagonal spreads where legs have different expiries.
 * The caller only specifies how far forward in calendar time to move from now;
 * the leg-specific remaining time is derived from that.
 */
export function legPnlAt(
  leg: StrategyLeg,
  underlying: number,
  daysElapsed: number,
  ivOverride?: number,
  now: Date = new Date()
): number {
  if (!leg.active) return 0
  const sign = leg.side === 'BUY' ? 1 : -1
  const qty = leg.lots * leg.lotSize

  // Closed leg: P&L is locked at the realised exit level and no longer
  // responds to spot / IV / time changes.
  if (leg.exitPrice !== undefined && leg.exitPrice > 0) {
    return sign * (leg.exitPrice - leg.price) * qty
  }

  if (leg.segment === 'FUTURE') {
    return sign * (underlying - leg.price) * qty
  }
  if (leg.strike === undefined || !leg.optionType) return 0

  // Days of life remaining for THIS leg after advancing calendar time.
  const legDaysNow = daysToExpiry(leg.expiry, now)
  const legRemainingDays = Math.max(legDaysNow - daysElapsed, 0)
  const tLeg = daysToYears(legRemainingDays)

  // At expiry (t=0) use intrinsic value; before that use Black-Scholes.
  const iv = (ivOverride ?? leg.iv) / 100
  const valueNow =
    tLeg <= 1e-6
      ? intrinsic(leg.optionType, underlying, leg.strike)
      : bsPrice(leg.optionType, { spot: underlying, strike: leg.strike, t: tLeg, iv })

  return sign * (valueNow - leg.price) * qty
}

export function totalPnlAt(
  legs: StrategyLeg[],
  underlying: number,
  daysElapsed: number,
  ivShiftPct: number = 0,
  /**
   * Fallback IV (%) used when a leg's own IV hasn't been fetched yet. Without
   * this, legs default to 0 IV and the T+0 curve collapses onto the expiry
   * curve on first paint. Typically the ATM IV from the option chain.
   */
  fallbackIv: number = 0,
  now: Date = new Date()
): number {
  let total = 0
  for (const leg of legs) {
    const baseIv = leg.iv > 0 ? leg.iv : fallbackIv
    const legIv = baseIv * (1 + ivShiftPct / 100)
    total += legPnlAt(leg, underlying, daysElapsed, legIv, now)
  }
  return total
}

/**
 * Net credit (+) / debit (-) collected when opening the strategy.
 * Futures legs contribute 0 (no premium).
 */
export function netCredit(legs: StrategyLeg[]): number {
  let credit = 0
  for (const leg of legs) {
    if (!leg.active) continue
    if (leg.segment !== 'OPTION') continue
    const qty = leg.lots * leg.lotSize
    credit += (leg.side === 'SELL' ? 1 : -1) * leg.price * qty
  }
  return credit
}

/** Total premium outlay (absolute). */
export function totalPremium(legs: StrategyLeg[]): number {
  let total = 0
  for (const leg of legs) {
    if (!leg.active || leg.segment !== 'OPTION') continue
    const qty = leg.lots * leg.lotSize
    total += leg.price * qty
  }
  return total
}

export interface PayoffSample {
  underlying: number
  expiry: number
  tplus0: number
}

export interface PayoffResult {
  samples: PayoffSample[]
  maxProfit: number
  maxLoss: number
  breakevens: number[]
  /** Indexes of samples where expiry crosses zero, used for shading. */
  zeroCrossings: number[]
}

export function computePayoff(
  legs: StrategyLeg[],
  _spot: number,
  /**
   * Calendar days to advance for the **Expiry** curve. For same-expiry
   * strategies this is the days to that single expiry. For calendars /
   * diagonals, pass the days to the NEAREST leg expiry — the remaining
   * legs will still be priced via Black-Scholes at their own remaining time.
   */
  daysAtExpiry: number,
  /**
   * Calendar days to advance for the **T+0** curve (simulator). 0 = now.
   */
  daysAtT0: number,
  priceRange: [number, number],
  steps: number = 240,
  ivShiftPct: number = 0,
  /** Fallback IV (%) for legs that haven't received their own IV yet. */
  fallbackIv: number = 0,
  now: Date = new Date()
): PayoffResult {
  const [lo, hi] = priceRange
  const step = (hi - lo) / steps
  const samples: PayoffSample[] = []
  let maxProfit = -Infinity
  let maxLoss = Infinity
  const zeroCrossings: number[] = []

  let prevExpiry: number | null = null
  for (let i = 0; i <= steps; i++) {
    const x = lo + i * step
    const atExpiry = totalPnlAt(legs, x, daysAtExpiry, ivShiftPct, fallbackIv, now)
    const atT0 = totalPnlAt(legs, x, daysAtT0, ivShiftPct, fallbackIv, now)
    samples.push({ underlying: x, expiry: atExpiry, tplus0: atT0 })
    if (atExpiry > maxProfit) maxProfit = atExpiry
    if (atExpiry < maxLoss) maxLoss = atExpiry
    if (prevExpiry !== null && Math.sign(prevExpiry) !== Math.sign(atExpiry)) {
      zeroCrossings.push(i - 1)
    }
    prevExpiry = atExpiry
  }

  // Linearly interpolate breakevens at zero crossings.
  const breakevens: number[] = []
  for (const idx of zeroCrossings) {
    const a = samples[idx]
    const b = samples[idx + 1]
    if (!a || !b) continue
    const dy = b.expiry - a.expiry
    if (Math.abs(dy) < 1e-9) continue
    const frac = -a.expiry / dy
    breakevens.push(a.underlying + frac * (b.underlying - a.underlying))
  }

  // Handle infinities / NaN so downstream formatters are safe.
  if (!isFinite(maxProfit)) maxProfit = 0
  if (!isFinite(maxLoss)) maxLoss = 0

  return {
    samples,
    maxProfit,
    maxLoss,
    breakevens,
    zeroCrossings,
  }
}

/**
 * Probability of profit using lognormal spot distribution.
 *
 * Models spot at expiry as lognormal with drift (r - q - σ²/2)·T and volatility σ√T
 * using the ATM IV. We then sum the probability mass over underlying ranges where
 * the expiry payoff is positive.
 */
export function probabilityOfProfit(
  samples: PayoffSample[],
  spot: number,
  atmIv: number,
  tYears: number
): number {
  if (samples.length < 2 || atmIv <= 0 || tYears <= 0 || spot <= 0) return 0
  const sigmaT = (atmIv / 100) * Math.sqrt(tYears)
  if (sigmaT <= 0) return 0

  // F(x) = P(S_T <= x) = Phi((ln(x/S0) - (-sigma^2/2) T) / (sigma sqrt T))  (risk-free drift = 0)
  const cdf = (x: number) => {
    if (x <= 0) return 0
    const mu = -0.5 * (atmIv / 100) * (atmIv / 100) * tYears
    return normCdf((Math.log(x / spot) - mu) / sigmaT)
  }

  let prob = 0
  for (let i = 0; i < samples.length - 1; i++) {
    const a = samples[i]
    const b = samples[i + 1]
    const mid = 0.5 * (a.expiry + b.expiry)
    if (mid > 0) {
      prob += cdf(b.underlying) - cdf(a.underlying)
    }
  }
  // Tail beyond last sample: assume same sign as last point.
  const last = samples[samples.length - 1]
  if (last.expiry > 0) prob += 1 - cdf(last.underlying)
  const first = samples[0]
  if (first.expiry > 0) prob += cdf(first.underlying)

  return Math.max(0, Math.min(1, prob))
}

/** Days to expiry (approximate, at 15:30 IST expiry close). */
export function parseExpiryDate(expiry: string): Date | null {
  // Format: DDMMMYY e.g. 28APR26
  const m = /^(\d{1,2})([A-Z]{3})(\d{2})$/.exec(expiry)
  if (!m) return null
  const day = parseInt(m[1], 10)
  const monthName = m[2]
  const year = 2000 + parseInt(m[3], 10)
  const months: Record<string, number> = {
    JAN: 0,
    FEB: 1,
    MAR: 2,
    APR: 3,
    MAY: 4,
    JUN: 5,
    JUL: 6,
    AUG: 7,
    SEP: 8,
    OCT: 9,
    NOV: 10,
    DEC: 11,
  }
  if (!(monthName in months)) return null
  // 15:30 IST = 10:00 UTC for Indian markets.
  return new Date(Date.UTC(year, months[monthName], day, 10, 0, 0))
}

export function daysToExpiry(expiry: string, now: Date = new Date()): number {
  const d = parseExpiryDate(expiry)
  if (!d) return 0
  const ms = d.getTime() - now.getTime()
  return Math.max(0, ms / (1000 * 60 * 60 * 24))
}

/**
 * Days to the nearest leg's expiry among a set of legs. Used by the payoff
 * chart's "At Expiry" curve for calendar / diagonal strategies where
 * multiple expiries are in play.
 */
export function nearestLegDays(legs: StrategyLeg[], now: Date = new Date()): number {
  let best = Infinity
  for (const leg of legs) {
    if (!leg.active) continue
    if (leg.exitPrice !== undefined && leg.exitPrice > 0) continue
    const d = daysToExpiry(leg.expiry, now)
    if (d < best) best = d
  }
  return best === Infinity ? 0 : best
}

/** Convert days to year-fraction (365 calendar days). */
export function daysToYears(days: number): number {
  return Math.max(0, days) / 365
}

/** Format symbol per OpenAlgo standard: BASE[DDMMMYY][STRIKE][CE|PE]. */
export function buildOptionSymbol(
  base: string,
  expiry: string,
  strike: number,
  type: OptionType
): string {
  const strikeStr =
    Number.isInteger(strike) || Math.abs(strike - Math.round(strike)) < 1e-6
      ? String(Math.round(strike))
      : String(strike)
  return `${base}${expiry}${strikeStr}${type}`
}

export function buildFutureSymbol(base: string, expiry: string): string {
  return `${base}${expiry}FUT`
}

/** Greek-level utilities for the Greeks tab. */
export function bsGreeks(
  type: OptionType,
  inp: BsInputs
): { delta: number; gamma: number; theta: number; vega: number } {
  const r = inp.r ?? 0
  const q = inp.q ?? 0
  const t = Math.max(inp.t, 1e-8)
  const iv = Math.max(inp.iv, 1e-8)
  const sqrtT = Math.sqrt(t)
  const d1 = (Math.log(inp.spot / inp.strike) + (r - q + 0.5 * iv * iv) * t) / (iv * sqrtT)
  const d2 = d1 - iv * sqrtT
  const pdf = normPdf(d1)
  const delta =
    type === 'CE' ? Math.exp(-q * t) * normCdf(d1) : Math.exp(-q * t) * (normCdf(d1) - 1)
  const gamma = (Math.exp(-q * t) * pdf) / (inp.spot * iv * sqrtT)
  const vega = inp.spot * Math.exp(-q * t) * pdf * sqrtT * 0.01 // per 1%
  const thetaCommon = -(inp.spot * pdf * iv * Math.exp(-q * t)) / (2 * sqrtT)
  let theta: number
  if (type === 'CE') {
    theta =
      thetaCommon -
      r * inp.strike * Math.exp(-r * t) * normCdf(d2) +
      q * inp.spot * Math.exp(-q * t) * normCdf(d1)
  } else {
    theta =
      thetaCommon +
      r * inp.strike * Math.exp(-r * t) * normCdf(-d2) -
      q * inp.spot * Math.exp(-q * t) * normCdf(-d1)
  }
  return { delta, gamma, theta: theta / 365, vega }
}
