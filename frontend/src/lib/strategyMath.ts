/**
 * Options math for the Strategy Builder.
 *
 * Re-prices per-leg market snapshots under what-if shifts. Options use the
 * same Black-76 model as the live Greeks service; futures use their selected
 * contract's live reference price.
 */

import { black76Price } from './optionGreeks'

export type OptionType = 'CE' | 'PE'
export type Side = 'BUY' | 'SELL'
export type Segment = 'OPTION' | 'FUTURE'

/**
 * Valuation time corrected to the latest server clock.
 *
 * `clockOffsetMs` is `serverNow - clientNow`; a plain `Date` remains accepted
 * by valuation callers while the Strategy Builder migration is in progress.
 */
export interface ValuationClock {
  now: Date
  clockOffsetMs: number
}

export type ValuationTime = Date | ValuationClock

/** One coherent what-if state shared by every scenario output. */
export interface ScenarioState {
  spot: number
  iv: number
  daysElapsed: number
  valuationTime: Date
}

/**
 * Classify a strike's moneyness relative to the ATM strike.
 *
 * Returns a short label like "ATM", "ITM1", "ITM2", "OTM1", "OTM3" where the
 * number is how many strike-steps away from ATM the strike is.
 *
 * Call (CE):  strike < ATM → ITM    ·    strike > ATM → OTM
 * Put (PE):   strike > ATM → ITM    ·    strike < ATM → OTM
 *
 * Returns null when inputs are insufficient (missing ATM, non-positive step).
 */
export function strikeMoneyness(
  strike: number | undefined,
  atmStrike: number | null,
  strikeStep: number,
  optionType: OptionType | undefined
): { label: string; kind: 'ATM' | 'ITM' | 'OTM'; steps: number } | null {
  if (strike === undefined || atmStrike === null || !optionType) return null
  if (!Number.isFinite(strikeStep) || strikeStep <= 0) return null
  const rawSteps = (strike - atmStrike) / strikeStep
  const steps = Math.round(rawSteps)
  if (steps === 0) return { label: 'ATM', kind: 'ATM', steps: 0 }
  const isCallITM = optionType === 'CE' && steps < 0
  const isPutITM = optionType === 'PE' && steps > 0
  const kind: 'ITM' | 'OTM' = isCallITM || isPutITM ? 'ITM' : 'OTM'
  return { label: `${kind}${Math.abs(steps)}`, kind, steps }
}

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
  /** Canonical exchange for the resolved contract. */
  exchange?: string
  /** Authoritative expiry instant from the option-chain response, in epoch seconds. */
  expiryTs?: number | null
  /** Minimum price increment for this contract. */
  tickSize?: number
  /**
   * Set only when this exact contract was resolved from the current canonical
   * broker listing. Persisted legs intentionally rehydrate without it.
   */
  contractValid?: boolean
  /** Latest streamed contract price, per share. */
  marketPrice?: number
  /** Underlying price at which the per-leg market snapshot was formed. */
  referenceUnderlying?: number
  /** Per-expiry forward at which the option IV was solved. */
  forwardPrice?: number
  /** Last per-contract Greeks snapshot for legs outside the active expiry chain. */
  marketGreeks?: {
    delta: number | null
    gamma: number | null
    theta: number | null
    vega: number | null
  }
  /**
   * Exit price (per share). Any finite value >= 0 treats the leg as "closed":
   * P&L is frozen at (exitPrice - entryPrice) * qty * sign for every
   * underlying value, and it no longer responds to spot/IV/time shifts.
   */
  exitPrice?: number
}

/** Undefined is the only open exit state; explicit finite non-negative exits are closed. */
export function isLegClosed<T extends { exitPrice?: number }>(
  leg: T
): leg is T & { exitPrice: number } {
  return leg.exitPrice !== undefined && Number.isFinite(leg.exitPrice) && leg.exitPrice >= 0
}

export type ExecutableStrategyLeg = StrategyLeg & { contractValid: true; tickSize: number }

/** A leg may be sent to the broker only after its exact contract was resolved. */
export function isLegExecutable(leg: StrategyLeg): leg is ExecutableStrategyLeg {
  return (
    leg.active &&
    !isLegClosed(leg) &&
    leg.contractValid === true &&
    Number.isInteger(leg.lots) &&
    leg.lots > 0 &&
    Number.isInteger(leg.lotSize) &&
    leg.lotSize > 0 &&
    typeof leg.tickSize === 'number' &&
    Number.isFinite(leg.tickSize) &&
    leg.tickSize > 0
  )
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

const DAY_MS = 24 * 60 * 60 * 1000
const YEAR_MS = 365 * DAY_MS

function isFiniteNumber(value: number | undefined | null): value is number {
  return value !== undefined && value !== null && Number.isFinite(value)
}

function valuationNow(value: ValuationTime): Date {
  if (value instanceof Date) return value
  return new Date(value.now.getTime() + value.clockOffsetMs)
}

function remainingDays(leg: StrategyLeg, daysElapsed: number, now: ValuationTime): number {
  const currentNow = valuationNow(now)
  const valuationMs = currentNow.getTime() + daysElapsed * DAY_MS
  if (isFiniteNumber(leg.expiryTs) && leg.expiryTs > 0) {
    return Math.max(0, leg.expiryTs * 1000 - valuationMs) / DAY_MS
  }
  return Math.max(daysToExpiry(leg.expiry, currentNow) - daysElapsed, 0)
}

function remainingYears(leg: StrategyLeg, daysElapsed: number, now: ValuationTime): number {
  return (remainingDays(leg, daysElapsed, now) * DAY_MS) / YEAR_MS
}

/**
 * One continuous annual carry rate for the whole strategy.
 *
 * Every leg reports a spot and a forward, and dividing that ratio by the leg's
 * remaining life recovers a rate. Inferring it per leg does not survive real
 * data. The forward is a put-call-parity synthetic built from two live quotes
 * and the reference is a separately streamed last price, so the ratio is noisy,
 * and a short-dated leg divides that noise by a very small number. Worse, legs
 * disagree: a chain fetched without Greeks reports no forward at all, and a leg
 * whose contract falls outside the loaded strike window keeps a stale snapshot
 * while its siblings refresh on every tick.
 *
 * Two legs on ONE expiry that disagree about the forward is the damaging case.
 * Their carry factors no longer cancel, so a defined-risk position acquires a
 * tail slope it does not have, and an iron condor with one unrefreshed wing
 * reports an unlimited loss.
 *
 * The underlying has a single carry curve, so the strategy takes a single rate.
 * The median makes one stale or unpriced leg unable to move it.
 */
function resolveCarryRate(legs: StrategyLeg[], now: ValuationTime): number | null {
  const rates: number[] = []
  for (const leg of legs) {
    if (!leg.active || isLegClosed(leg)) continue
    const reference = isFiniteNumber(leg.referenceUnderlying) ? leg.referenceUnderlying : undefined
    // A future quotes its own basis directly; an option carries a parity forward.
    const carried =
      leg.segment === 'FUTURE'
        ? isFiniteNumber(leg.marketPrice)
          ? leg.marketPrice
          : undefined
        : isFiniteNumber(leg.forwardPrice)
          ? leg.forwardPrice
          : undefined
    if (reference === undefined || carried === undefined || reference <= 0 || carried <= 0) {
      continue
    }
    const snapshotYears = remainingYears(leg, 0, now)
    if (snapshotYears <= 0) continue
    const rate = Math.log(carried / reference) / snapshotYears
    if (Number.isFinite(rate)) rates.push(rate)
  }
  if (rates.length === 0) return null
  rates.sort((left, right) => left - right)
  const middle = Math.floor(rates.length / 2)
  return rates.length % 2 === 1 ? rates[middle] : (rates[middle - 1] + rates[middle]) / 2
}

/**
 * Growth factor from the scenario underlying to a leg's own carried price at
 * `tYears` of remaining life. Returns 1 at expiry, where everything settles
 * against spot, and 1 when no rate could be inferred.
 */
function carryFactorAt(carryRate: number | null, tYears: number): number {
  if (carryRate === null || tYears <= 0) return 1
  const factor = Math.exp(carryRate * tYears)
  return Number.isFinite(factor) && factor > 0 ? factor : 1
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
  now: ValuationTime = new Date(),
  carryRate: number | null = resolveCarryRate([leg], now)
): number {
  if (!leg.active) return 0
  const sign = leg.side === 'BUY' ? 1 : -1
  const qty = leg.lots * leg.lotSize

  // Closed leg: P&L is locked at the realised exit level and no longer
  // responds to spot / IV / time changes.
  if (isLegClosed(leg)) {
    return sign * (leg.exitPrice - leg.price) * qty
  }

  if (leg.segment === 'FUTURE') {
    if (isFiniteNumber(leg.marketPrice) && isFiniteNumber(leg.referenceUnderlying)) {
      // A future converges on its own expiry for the same reason an option
      // does, so its basis decays rather than being carried to infinity. Held
      // constant, a covered call reported a max profit inflated by exactly the
      // basis times the quantity.
      const futureValue =
        underlying * carryFactorAt(carryRate, remainingYears(leg, daysElapsed, now))
      return sign * (futureValue - leg.price) * qty
    }
    return sign * (underlying - leg.price) * qty
  }
  if (leg.strike === undefined || !leg.optionType) return 0

  const tLeg = remainingYears(leg, daysElapsed, now)
  const iv = (ivOverride ?? leg.iv) / 100
  const referenceUnderlying = isFiniteNumber(leg.referenceUnderlying)
    ? leg.referenceUnderlying
    : undefined
  const forwardPrice = isFiniteNumber(leg.forwardPrice) ? leg.forwardPrice : undefined
  const hasForwardReference = referenceUnderlying !== undefined && forwardPrice !== undefined
  const scenarioForward = underlying * carryFactorAt(carryRate, tLeg)
  // Black-76 is defined only for positive forwards. Its F -> 0 limit is the
  // undiscounted intrinsic value, so clamp a crossed scenario to that boundary
  // instead of sending a non-positive ratio into log(F / K).
  const pricingForward = Number.isFinite(scenarioForward) ? Math.max(0, scenarioForward) : 0
  const modelValue =
    tLeg <= 1e-8 || iv <= 0 || pricingForward <= 0
      ? intrinsic(leg.optionType, pricingForward, leg.strike)
      : black76Price(leg.optionType === 'CE' ? 'c' : 'p', pricingForward, leg.strike, tLeg, 0, iv)
  const isUnshiftedLiveSnapshot =
    hasForwardReference &&
    Math.abs(underlying - referenceUnderlying) <= 1e-8 &&
    daysElapsed === 0 &&
    Math.abs((ivOverride ?? leg.iv) - leg.iv) <= 1e-8
  const valueNow =
    isUnshiftedLiveSnapshot &&
    isFiniteNumber(leg.marketPrice) &&
    isFiniteNumber(leg.tickSize) &&
    leg.tickSize > 0 &&
    Math.abs(modelValue - leg.marketPrice) <= leg.tickSize
      ? leg.marketPrice
      : modelValue

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
  now: ValuationTime = new Date(),
  carryRate: number | null = resolveCarryRate(legs, now)
): number {
  let total = 0
  for (const leg of legs) {
    const baseIv = leg.iv > 0 ? leg.iv : fallbackIv
    const legIv = baseIv * (1 + ivShiftPct / 100)
    total += legPnlAt(leg, underlying, daysElapsed, legIv, now, carryRate)
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
  /**
   * True mathematical maximum profit of the strategy at expiry.
   * May be ``+Infinity`` for strategies with unlimited upside
   * (e.g. Long Call, Long Synthetic, Call Ratio Back Spread).
   */
  maxProfit: number
  /**
   * True mathematical maximum loss of the strategy at expiry.
   * May be ``-Infinity`` for strategies with unlimited downside
   * (e.g. Short Call, Short Synthetic, Short Straddle).
   */
  maxLoss: number
  breakevens: number[]
  /** Indexes of samples where expiry crosses zero, used for shading. */
  zeroCrossings: number[]
}

/**
 * Asymptotic slopes of the expiry payoff:
 *   right = dP/dS as S → +∞  (sensitivity to far-upside moves)
 *   left  = dP/dS as S → 0+  (sensitivity to far-downside moves)
 *
 * Used to detect unlimited-profit / unlimited-loss strategies that a finite
 * sample window would otherwise report as capped. Closed / inactive legs
 * contribute 0 (their P&L is locked or excluded).
 *
 * An option is priced off its own forward, and that forward moves with the
 * scenario underlying by the leg's carry factor, so a deep in-the-money call is
 * worth `S x factor - K` and contributes `qty x factor` rather than plain
 * `qty`. At the terminal horizon every factor is 1 and this reduces to the
 * familiar per-lot slopes.
 *
 * The distinction matters for anything spanning two expiries. A calendar's legs
 * carry to different forwards, so contributions that would cancel on quantity
 * alone do not actually cancel, and the tail has a real slope. Reporting it as
 * flat would cap an unbounded loss at whatever the sampled window happened to
 * reach.
 *
 * Slope contributions at S → +∞:
 *   BUY  CE  → +qty x factor   (call goes ITM, gains with the forward)
 *   SELL CE  → −qty x factor
 *   BUY  PE  →  0              (put worthless at high spot)
 *   SELL PE  →  0
 *   BUY  FUT → +qty            (futures track the underlying one for one)
 *   SELL FUT → −qty
 *
 * Slope contributions at S → 0+ (slope w.r.t. S, so a put gaining value as
 * S drops gives a NEGATIVE slope):
 *   BUY  CE  →  0
 *   SELL CE  →  0
 *   BUY  PE  → −qty x factor
 *   SELL PE  → +qty x factor
 *   BUY  FUT → +qty
 *   SELL FUT → −qty
 */
function asymptoticSlopes(
  legs: StrategyLeg[],
  daysElapsed: number,
  now: ValuationTime,
  carryRate: number | null
): { right: number; left: number } {
  let right = 0
  let left = 0
  for (const leg of legs) {
    if (!leg.active) continue
    if (isLegClosed(leg)) continue
    const qty = leg.lots * leg.lotSize
    const sign = leg.side === 'BUY' ? 1 : -1
    const factor = carryFactorAt(carryRate, remainingYears(leg, daysElapsed, now))

    if (leg.segment === 'FUTURE') {
      right += sign * qty * factor
      left += sign * qty * factor
      continue
    }

    if (leg.segment === 'OPTION') {
      if (leg.optionType === 'CE') {
        right += sign * qty * factor
      } else if (leg.optionType === 'PE') {
        left -= sign * qty * factor
      }
    }
  }
  return { right, left }
}

const PAYOFF_EPSILON = 1e-8

function normalizePayoff(value: number): number {
  return Math.abs(value) <= PAYOFF_EPSILON ? 0 : value
}

function uniqueSorted(values: number[], tolerance = PAYOFF_EPSILON): number[] {
  const sorted = values.filter(Number.isFinite).sort((a, b) => a - b)
  const result: number[] = []
  for (const value of sorted) {
    const previous = result.at(-1)
    if (previous === undefined || Math.abs(value - previous) > tolerance) {
      result.push(value)
    }
  }
  return result
}

function responsiveStrikes(legs: StrategyLeg[]): number[] {
  return uniqueSorted(
    legs.flatMap((leg) =>
      leg.active && !isLegClosed(leg) && leg.segment === 'OPTION' && leg.strike !== undefined
        ? [leg.strike]
        : []
    )
  )
}

function hasResponsiveExposure(legs: StrategyLeg[]): boolean {
  return legs.some(
    (leg) =>
      leg.active &&
      !isLegClosed(leg) &&
      (leg.segment === 'FUTURE' ||
        (leg.segment === 'OPTION' && leg.strike !== undefined && leg.optionType !== undefined))
  )
}

function isTerminalHorizon(legs: StrategyLeg[], daysAtExpiry: number, now: Date): boolean {
  return legs.every((leg) => {
    if (!leg.active || isLegClosed(leg)) return true
    if (leg.segment !== 'OPTION') return true
    return remainingDays(leg, daysAtExpiry, now) <= 1e-6
  })
}

interface TerminalAnalysis {
  breakevens: number[]
  maxProfit: number
  maxLoss: number
}

export function payoffPriceRange(
  spot: number,
  legs: StrategyLeg[],
  atmIv: number,
  tYears: number
): [number, number] {
  const strikes = responsiveStrikes(legs)
  const expectedMove = lognormalPriceBand(spot, atmIv, tYears, 2)
  const lowerBaseline = spot * 0.9
  const scaledUpperBaseline = spot * 1.1
  const upperBaseline = Number.isFinite(scaledUpperBaseline)
    ? scaledUpperBaseline
    : Number.MAX_VALUE
  const lowerCandidates = [lowerBaseline, expectedMove?.lower ?? spot, ...strikes]
  const upperCandidates = [upperBaseline, expectedMove?.upper ?? spot, ...strikes]
  return [Math.max(0, Math.min(...lowerCandidates)), Math.max(...upperCandidates)]
}

/**
 * Lognormal price boundaries used by both PoP and expected-move overlays.
 * The zero-rate convention is ln(S_T / S_0) ~ N(-0.5 sigma^2 T, sigma^2 T).
 */
export function lognormalPriceBand(
  spot: number,
  atmIv: number,
  tYears: number,
  standardDeviations: number
): { lower: number; upper: number } | null {
  if (
    !Number.isFinite(spot) ||
    !Number.isFinite(atmIv) ||
    !Number.isFinite(tYears) ||
    !Number.isFinite(standardDeviations) ||
    spot <= 0 ||
    atmIv <= 0 ||
    tYears <= 0 ||
    standardDeviations <= 0
  ) {
    return null
  }
  const sigma = atmIv / 100
  const sqrtT = Math.sqrt(tYears)
  const variance = sigma * sigma * tYears
  const sigmaT = sigma * sqrtT
  const drift = -0.5 * variance
  const spread = standardDeviations * sigmaT
  const lowerExponent = drift - spread
  const upperExponent = drift + spread
  if (
    ![sigma, sqrtT, variance, sigmaT, drift, spread, lowerExponent, upperExponent].every(
      Number.isFinite
    )
  ) {
    return null
  }
  const lower = spot * Math.exp(lowerExponent)
  const upper = spot * Math.exp(upperExponent)
  return Number.isFinite(lower) && Number.isFinite(upper) ? { lower, upper } : null
}

function analyzeTerminalPayoff(
  legs: StrategyLeg[],
  daysAtExpiry: number,
  ivShiftPct: number,
  fallbackIv: number,
  now: Date,
  carryRate: number | null
): TerminalAnalysis {
  // The terminal horizon prices every option against spot, so its only kinks
  // are the strikes themselves. Zero is kept because it bounds the left tail,
  // where a short put reaches its worst case.
  const candidates = uniqueSorted([0, ...responsiveStrikes(legs)])
  const valueAt = (underlying: number) =>
    normalizePayoff(
      totalPnlAt(legs, underlying, daysAtExpiry, ivShiftPct, fallbackIv, now, carryRate)
    )
  if (!hasResponsiveExposure(legs)) {
    const constantPayoff = valueAt(0)
    return { breakevens: [], maxProfit: constantPayoff, maxLoss: constantPayoff }
  }
  const roots: number[] = []
  const candidateValues = candidates.map(valueAt)
  // Same rule as the non-terminal scan: a span sitting flat on zero is one
  // plateau, not a breakeven at each of its vertices. A costless butterfly is
  // worth exactly nothing below its lowest strike, and reporting a "breakeven"
  // at an underlying of 0 there is noise, not information.
  const isPlateauEdge = (index: number) =>
    index === 0 ||
    index === candidateValues.length - 1 ||
    candidateValues[index - 1] !== 0 ||
    candidateValues[index + 1] !== 0

  for (let i = 0; i < candidates.length - 1; i++) {
    const left = candidates[i]
    const right = candidates[i + 1]
    const leftValue = candidateValues[i]
    const rightValue = candidateValues[i + 1]
    if (leftValue === 0 && isPlateauEdge(i) && i > 0) roots.push(left)
    if (leftValue * rightValue < 0) {
      roots.push(left + ((0 - leftValue) * (right - left)) / (rightValue - leftValue))
    }
  }

  const last = candidates.at(-1) ?? 0
  const lastIndex = candidateValues.length - 1
  const lastValue = candidateValues[lastIndex]
  if (lastValue === 0 && isPlateauEdge(lastIndex)) roots.push(last)

  const slopes = asymptoticSlopes(legs, daysAtExpiry, now, carryRate)
  if (Math.abs(slopes.right) > PAYOFF_EPSILON) {
    const tailRoot = last - lastValue / slopes.right
    if (tailRoot > last + PAYOFF_EPSILON) roots.push(tailRoot)
  }

  let maxProfit = candidateValues.length > 0 ? Math.max(...candidateValues) : 0
  let maxLoss = candidateValues.length > 0 ? Math.min(...candidateValues) : 0
  if (slopes.right > PAYOFF_EPSILON) maxProfit = Infinity
  if (slopes.right < -PAYOFF_EPSILON) maxLoss = -Infinity

  return {
    breakevens: uniqueSorted(roots),
    maxProfit,
    maxLoss,
  }
}

function refineExtremum(
  valueAt: (underlying: number) => number,
  left: number,
  right: number,
  maximize: boolean
): number {
  const ratio = (Math.sqrt(5) - 1) / 2
  let lo = left
  let hi = right
  let x1 = hi - ratio * (hi - lo)
  let x2 = lo + ratio * (hi - lo)
  let y1 = valueAt(x1)
  let y2 = valueAt(x2)
  for (let iteration = 0; iteration < 64; iteration++) {
    const keepLeft = maximize ? y1 > y2 : y1 < y2
    if (keepLeft) {
      hi = x2
      x2 = x1
      y2 = y1
      x1 = hi - ratio * (hi - lo)
      y1 = valueAt(x1)
    } else {
      lo = x1
      x1 = x2
      y1 = y2
      x2 = lo + ratio * (hi - lo)
      y2 = valueAt(x2)
    }
  }
  return valueAt((lo + hi) / 2)
}

function rightTailValue(legs: StrategyLeg[]): number {
  let value = 0
  for (const leg of legs) {
    if (!leg.active) continue
    const sign = leg.side === 'BUY' ? 1 : -1
    const qty = leg.lots * leg.lotSize
    if (isLegClosed(leg)) {
      value += sign * (leg.exitPrice - leg.price) * qty
    } else if (
      leg.segment === 'OPTION' &&
      leg.strike !== undefined &&
      leg.optionType !== undefined
    ) {
      // Deep in the money a call is worth `S x factor - K`. The `S x factor`
      // part is what the flat-slope test just established sums to zero, so the
      // constant this returns is the strike alone. Carrying a basis term here
      // was the additive model's constant, and is wrong once the forward scales
      // with the underlying rather than sitting a fixed distance above it.
      const terminalValue = leg.optionType === 'CE' ? -leg.strike : 0
      value += sign * (terminalValue - leg.price) * qty
    } else if (leg.segment === 'FUTURE') {
      // A future is worth `S x factor`, so once the flat-slope test has
      // established the scaled terms cancel, only the entry price is left.
      value += sign * (0 - leg.price) * qty
    }
  }
  return normalizePayoff(value)
}

function analyzeNonTerminalPayoff(
  legs: StrategyLeg[],
  spot: number,
  daysAtExpiry: number,
  priceRange: [number, number],
  ivShiftPct: number,
  fallbackIv: number,
  now: Date,
  carryRate: number | null
): TerminalAnalysis {
  const strikes = responsiveStrikes(legs)
  const maxStrike = Math.max(spot, ...strikes)
  const maxRemainingYears = Math.max(
    0,
    ...legs.map((leg) => remainingYears(leg, daysAtExpiry, now))
  )
  const maxIv =
    Math.max(fallbackIv, ...legs.map((leg) => (leg.iv > 0 ? leg.iv : fallbackIv))) *
    (1 + ivShiftPct / 100)
  const sigmaMove = spot > 0 && maxIv > 0 ? spot * (maxIv / 100) * Math.sqrt(maxRemainingYears) : 0
  const valueAt = (underlying: number) =>
    normalizePayoff(
      totalPnlAt(legs, underlying, daysAtExpiry, ivShiftPct, fallbackIv, now, carryRate)
    )
  const slopes = asymptoticSlopes(legs, daysAtExpiry, now, carryRate)
  const tailLimit = rightTailValue(legs)
  let analysisHi = Math.max(priceRange[1], maxStrike * 2, spot + 6 * sigmaMove)
  for (let expansion = 0; expansion < 20; expansion++) {
    const tailValue = valueAt(analysisHi)
    const rootStillAhead =
      (slopes.right > PAYOFF_EPSILON && tailValue < 0) ||
      (slopes.right < -PAYOFF_EPSILON && tailValue > 0) ||
      (Math.abs(slopes.right) <= PAYOFF_EPSILON && tailValue * tailLimit < 0)
    if (!rootStillAhead) break
    analysisHi *= 2
  }
  const intervals = 1024
  const grid = Array.from({ length: intervals + 1 }, (_, index) => (analysisHi * index) / intervals)
  const xs = uniqueSorted([...grid, ...strikes])
  const values = xs.map(valueAt)
  const roots: number[] = []
  const extrema = [...values]
  if (Math.abs(slopes.right) <= PAYOFF_EPSILON) {
    extrema.push(tailLimit)
  }

  // A payoff can sit exactly on zero across a whole span rather than crossing
  // it at a point - a zero-cost collar between its strikes, or a calendar whose
  // legs were entered at the same premium, whose far tail is flat at zero. That
  // is one plateau, not a breakeven at every sampled point: recording each grid
  // point would return hundreds of "breakevens" and, because the framing takes
  // the outermost of them, would stretch the chart far past the strategy.
  // Only the interior counts. Index 0 is an underlying of zero and the last
  // index is `analysisHi`, a window this function chose for itself; neither is
  // a price a trader can break even at. Reporting the far end also made the
  // "breakeven" track the window - widen the request and the number moved with
  // it - and planted a chart marker on the frame edge.
  for (let index = 1; index < values.length - 1; index++) {
    if (values[index] !== 0) continue
    if (values[index - 1] === 0 && values[index + 1] === 0) continue
    roots.push(xs[index])
  }

  for (let index = 0; index < xs.length - 1; index++) {
    const leftValue = values[index]
    const rightValue = values[index + 1]
    if (leftValue * rightValue >= 0) continue

    let lo = xs[index]
    let hi = xs[index + 1]
    for (let iteration = 0; iteration < 64; iteration++) {
      const mid = (lo + hi) / 2
      const midValue = valueAt(mid)
      if (midValue === 0) {
        lo = mid
        hi = mid
        break
      }
      if (leftValue * midValue < 0) hi = mid
      else lo = mid
    }
    roots.push((lo + hi) / 2)
  }

  for (let index = 1; index < xs.length - 1; index++) {
    const previous = values[index - 1]
    const current = values[index]
    const next = values[index + 1]
    if (current >= previous && current >= next) {
      extrema.push(refineExtremum(valueAt, xs[index - 1], xs[index + 1], true))
    }
    if (current <= previous && current <= next) {
      extrema.push(refineExtremum(valueAt, xs[index - 1], xs[index + 1], false))
    }
  }

  return {
    breakevens: uniqueSorted(roots, 1e-6),
    maxProfit: slopes.right > PAYOFF_EPSILON ? Infinity : Math.max(...extrema),
    maxLoss: slopes.right < -PAYOFF_EPSILON ? -Infinity : Math.min(...extrema),
  }
}

export function computePayoff(
  legs: StrategyLeg[],
  spot: number,
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
  now: ValuationTime = new Date()
): PayoffResult {
  const currentNow = valuationNow(now)
  const terminal = isTerminalHorizon(legs, daysAtExpiry, currentNow)
  const carryRate = resolveCarryRate(legs, currentNow)
  const terminalAnalysis = terminal
    ? analyzeTerminalPayoff(legs, daysAtExpiry, ivShiftPct, fallbackIv, currentNow, carryRate)
    : analyzeNonTerminalPayoff(
        legs,
        spot,
        daysAtExpiry,
        priceRange,
        ivShiftPct,
        fallbackIv,
        currentNow,
        carryRate
      )
  // Every option kink lands on its strike: the terminal curve prices against
  // spot, and the pre-expiry curve is smooth between them.
  const strikes = responsiveStrikes(legs)
  const initialBreakevens = terminalAnalysis.breakevens
  // A root at zero is the far-tail artefact of a structure that expires
  // worthless at S = 0, not a breakeven anyone trades around.
  const framingBreakevens = initialBreakevens.filter((value) => value > 0)
  const [requestedLo, requestedHi] = priceRange
  const lo = Math.max(0, Math.min(requestedLo, ...strikes, ...framingBreakevens))
  const hi = Math.max(requestedHi, ...strikes, ...framingBreakevens)
  const safeSteps = Math.max(1, Math.floor(steps))
  const step = (hi - lo) / safeSteps
  const uniform = Array.from({ length: safeSteps + 1 }, (_, index) => lo + index * step)
  // Kinks and roots outside the framed window would otherwise re-extend the
  // plotted series back to the bound the framing just excluded.
  const inFrame = (value: number) => value >= lo && value <= hi
  const sampleXs = uniqueSorted([...uniform, ...strikes, ...initialBreakevens]).filter(inFrame)

  const makeSample = (underlying: number): PayoffSample => ({
    underlying,
    expiry: normalizePayoff(
      totalPnlAt(legs, underlying, daysAtExpiry, ivShiftPct, fallbackIv, currentNow, carryRate)
    ),
    tplus0: normalizePayoff(
      totalPnlAt(legs, underlying, daysAtT0, ivShiftPct, fallbackIv, currentNow, carryRate)
    ),
  })
  let samples = sampleXs.map(makeSample)
  const breakevens = terminalAnalysis.breakevens

  if (breakevens.length > 0) {
    samples = uniqueSorted([...sampleXs, ...breakevens.filter(inFrame)]).map(makeSample)
  }

  const zeroCrossings = samples.flatMap((sample, index) => (sample.expiry === 0 ? [index] : []))

  return {
    samples,
    maxProfit: terminalAnalysis.maxProfit,
    maxLoss: terminalAnalysis.maxLoss,
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
): number | null {
  if (
    samples.length < 2 ||
    !Number.isFinite(spot) ||
    !Number.isFinite(atmIv) ||
    !Number.isFinite(tYears) ||
    spot <= 0 ||
    atmIv <= 0 ||
    tYears <= 0 ||
    samples.some((sample) => !Number.isFinite(sample.underlying) || !Number.isFinite(sample.expiry))
  ) {
    return null
  }
  const sigma = atmIv / 100
  const sqrtT = Math.sqrt(tYears)
  const variance = sigma * sigma * tYears
  const sigmaT = sigma * sqrtT
  const mu = -0.5 * variance
  if (![sigma, sqrtT, variance, sigmaT, mu].every(Number.isFinite) || sigmaT <= 0) return null

  // F(x) = P(S_T <= x) = Phi((ln(x/S0) - (-sigma^2/2) T) / (sigma sqrt T))  (risk-free drift = 0)
  const cdf = (x: number): number | null => {
    if (x <= 0) return 0
    const ratio = x / spot
    const logReturn = Math.log(ratio)
    const numerator = logReturn - mu
    const z = numerator / sigmaT
    if (![ratio, logReturn, numerator, z].every(Number.isFinite)) return null
    const probability = normCdf(z)
    return Number.isFinite(probability) ? probability : null
  }

  let prob = 0
  for (let i = 0; i < samples.length - 1; i++) {
    const a = samples[i]
    const b = samples[i + 1]
    const mid = a.expiry / 2 + b.expiry / 2
    if (!Number.isFinite(mid)) return null
    if (mid > 0) {
      const upperCdf = cdf(b.underlying)
      const lowerCdf = cdf(a.underlying)
      if (upperCdf === null || lowerCdf === null) return null
      const probabilityMass = upperCdf - lowerCdf
      if (!Number.isFinite(probabilityMass)) return null
      prob += probabilityMass
      if (!Number.isFinite(prob)) return null
    }
  }
  // Tail beyond last sample: assume same sign as last point.
  const last = samples[samples.length - 1]
  if (last.expiry > 0) {
    const lastCdf = cdf(last.underlying)
    if (lastCdf === null) return null
    prob += 1 - lastCdf
  }
  const first = samples[0]
  if (first.expiry > 0) {
    const firstCdf = cdf(first.underlying)
    if (firstCdf === null) return null
    prob += firstCdf
  }

  if (!Number.isFinite(prob)) return null
  const clampedProbability = Math.max(0, Math.min(1, prob))
  return Number.isFinite(clampedProbability) ? clampedProbability : null
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

function legExpiryIdentity(leg: StrategyLeg): string {
  if (isFiniteNumber(leg.expiryTs) && leg.expiryTs > 0) {
    const authoritative = new Date(leg.expiryTs * 1000)
    if (Number.isFinite(authoritative.getTime())) return authoritative.toISOString().slice(0, 10)
  }
  const parsed = parseExpiryDate(leg.expiry)
  if (parsed) return parsed.toISOString().slice(0, 10)
  return leg.expiry
    .trim()
    .toUpperCase()
    .replace(/[^A-Z0-9]/g, '')
}

/** True when responsive open legs reach more than one calendar expiry event. */
export function hasMultipleActiveExpiries(legs: StrategyLeg[]): boolean {
  const expiries = new Set(
    legs
      .filter((leg) => leg.active && !isLegClosed(leg))
      .map(legExpiryIdentity)
      .filter(Boolean)
  )
  return expiries.size > 1
}

/**
 * Days to the nearest leg's expiry among a set of legs. Used by the payoff
 * chart's "At Expiry" curve for calendar / diagonal strategies where
 * multiple expiries are in play.
 */
export function nearestLegDays(legs: StrategyLeg[], now: ValuationTime = new Date()): number {
  let best = Infinity
  for (const leg of legs) {
    if (!leg.active) continue
    if (isLegClosed(leg)) continue
    const d = remainingDays(leg, 0, now)
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
