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
 * Slope contributions at S → +∞:
 *   BUY  CE  → +qty    (call goes ITM, gains ₹1 per ₹1 spot rise)
 *   SELL CE  → −qty
 *   BUY  PE  →  0      (put worthless at high spot)
 *   SELL PE  →  0
 *   BUY  FUT → +qty
 *   SELL FUT → −qty
 *
 * Slope contributions at S → 0+ (slope w.r.t. S, so a put gaining value as
 * S drops gives a NEGATIVE slope):
 *   BUY  CE  →  0
 *   SELL CE  →  0
 *   BUY  PE  → −qty
 *   SELL PE  → +qty
 *   BUY  FUT → +qty
 *   SELL FUT → −qty
 */
function asymptoticSlopes(legs: StrategyLeg[]): { right: number; left: number } {
  let right = 0
  let left = 0
  for (const leg of legs) {
    if (!leg.active) continue
    if (leg.exitPrice !== undefined && leg.exitPrice > 0) continue
    const qty = leg.lots * leg.lotSize
    const sign = leg.side === 'BUY' ? 1 : -1

    if (leg.segment === 'FUTURE') {
      right += sign * qty
      left += sign * qty
      continue
    }

    if (leg.segment === 'OPTION') {
      if (leg.optionType === 'CE') {
        right += sign * qty
      } else if (leg.optionType === 'PE') {
        left -= sign * qty
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
      leg.active &&
      !(leg.exitPrice !== undefined && leg.exitPrice > 0) &&
      leg.segment === 'OPTION' &&
      leg.strike !== undefined
        ? [leg.strike]
        : []
    )
  )
}

function hasResponsiveExposure(legs: StrategyLeg[]): boolean {
  return legs.some(
    (leg) =>
      leg.active &&
      !(leg.exitPrice !== undefined && leg.exitPrice > 0) &&
      (leg.segment === 'FUTURE' ||
        (leg.segment === 'OPTION' && leg.strike !== undefined && leg.optionType !== undefined))
  )
}

function isTerminalHorizon(legs: StrategyLeg[], daysAtExpiry: number, now: Date): boolean {
  return legs.every((leg) => {
    if (!leg.active || (leg.exitPrice !== undefined && leg.exitPrice > 0)) return true
    if (leg.segment !== 'OPTION') return true
    return daysToExpiry(leg.expiry, now) - daysAtExpiry <= 1e-6
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
  const sigmaMove =
    spot > 0 && atmIv > 0 && tYears > 0 ? spot * (atmIv / 100) * Math.sqrt(tYears) : 0
  const lowerCandidates = [spot * 0.9, spot - 2 * sigmaMove, ...strikes]
  const upperCandidates = [spot * 1.1, spot + 2 * sigmaMove, ...strikes]
  return [Math.max(0, Math.min(...lowerCandidates)), Math.max(...upperCandidates)]
}

function analyzeTerminalPayoff(
  legs: StrategyLeg[],
  daysAtExpiry: number,
  ivShiftPct: number,
  fallbackIv: number,
  now: Date
): TerminalAnalysis {
  const strikes = responsiveStrikes(legs)
  const candidates = uniqueSorted([0, ...strikes])
  const valueAt = (underlying: number) =>
    normalizePayoff(totalPnlAt(legs, underlying, daysAtExpiry, ivShiftPct, fallbackIv, now))
  if (!hasResponsiveExposure(legs)) {
    const constantPayoff = valueAt(0)
    return { breakevens: [], maxProfit: constantPayoff, maxLoss: constantPayoff }
  }
  const roots: number[] = []

  for (let i = 0; i < candidates.length - 1; i++) {
    const left = candidates[i]
    const right = candidates[i + 1]
    const leftValue = valueAt(left)
    const rightValue = valueAt(right)
    if (leftValue === 0) roots.push(left)
    if (leftValue * rightValue < 0) {
      roots.push(left + ((0 - leftValue) * (right - left)) / (rightValue - leftValue))
    }
  }

  const last = candidates.at(-1) ?? 0
  const lastValue = valueAt(last)
  if (lastValue === 0) roots.push(last)

  const slopes = asymptoticSlopes(legs)
  if (Math.abs(slopes.right) > PAYOFF_EPSILON) {
    const tailRoot = last - lastValue / slopes.right
    if (tailRoot > last + PAYOFF_EPSILON) roots.push(tailRoot)
  }

  const candidateValues = candidates.map(valueAt)
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
    if (leg.exitPrice !== undefined && leg.exitPrice > 0) {
      value += sign * (leg.exitPrice - leg.price) * qty
    } else if (
      leg.segment === 'OPTION' &&
      leg.strike !== undefined &&
      leg.optionType !== undefined
    ) {
      value += sign * ((leg.optionType === 'CE' ? -leg.strike : 0) - leg.price) * qty
    } else if (leg.segment === 'FUTURE') {
      value += sign * -leg.price * qty
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
  now: Date
): TerminalAnalysis {
  const strikes = responsiveStrikes(legs)
  const maxStrike = Math.max(spot, ...strikes)
  const maxRemainingYears = Math.max(
    0,
    ...legs.map((leg) => daysToYears(Math.max(daysToExpiry(leg.expiry, now) - daysAtExpiry, 0)))
  )
  const maxIv =
    Math.max(fallbackIv, ...legs.map((leg) => (leg.iv > 0 ? leg.iv : fallbackIv))) *
    (1 + ivShiftPct / 100)
  const sigmaMove = spot > 0 && maxIv > 0 ? spot * (maxIv / 100) * Math.sqrt(maxRemainingYears) : 0
  const valueAt = (underlying: number) =>
    normalizePayoff(totalPnlAt(legs, underlying, daysAtExpiry, ivShiftPct, fallbackIv, now))
  const slopes = asymptoticSlopes(legs)
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

  for (let index = 0; index < xs.length - 1; index++) {
    const leftValue = values[index]
    const rightValue = values[index + 1]
    if (leftValue === 0) roots.push(xs[index])
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
  if (values.at(-1) === 0) roots.push(xs.at(-1) as number)

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
  now: Date = new Date()
): PayoffResult {
  const terminal = isTerminalHorizon(legs, daysAtExpiry, now)
  const terminalAnalysis = terminal
    ? analyzeTerminalPayoff(legs, daysAtExpiry, ivShiftPct, fallbackIv, now)
    : analyzeNonTerminalPayoff(legs, spot, daysAtExpiry, priceRange, ivShiftPct, fallbackIv, now)
  const strikes = responsiveStrikes(legs)
  const initialBreakevens = terminalAnalysis.breakevens
  const [requestedLo, requestedHi] = priceRange
  const lo = Math.max(0, Math.min(requestedLo, ...strikes, ...initialBreakevens))
  const hi = Math.max(requestedHi, ...strikes, ...initialBreakevens)
  const safeSteps = Math.max(1, Math.floor(steps))
  const step = (hi - lo) / safeSteps
  const uniform = Array.from({ length: safeSteps + 1 }, (_, index) => lo + index * step)
  const sampleXs = uniqueSorted([...uniform, ...strikes, ...initialBreakevens])

  const makeSample = (underlying: number): PayoffSample => ({
    underlying,
    expiry: normalizePayoff(
      totalPnlAt(legs, underlying, daysAtExpiry, ivShiftPct, fallbackIv, now)
    ),
    tplus0: normalizePayoff(totalPnlAt(legs, underlying, daysAtT0, ivShiftPct, fallbackIv, now)),
  })
  let samples = sampleXs.map(makeSample)
  const breakevens = terminalAnalysis.breakevens

  if (breakevens.length > 0) {
    samples = uniqueSorted([...sampleXs, ...breakevens]).map(makeSample)
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
