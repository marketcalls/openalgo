/**
 * Strategy templates used by the Strategy Builder's template grid.
 *
 * Each template produces a list of legs with strikes expressed relative to ATM
 * (in "strike steps" — the strike interval in the option chain, e.g. 50 for
 * NIFTY, 100 for BANKNIFTY). The Strategy Builder resolves these offsets
 * against the nearest available strikes in the live option chain when the user
 * picks a template.
 */

import type { OptionType, Side } from './strategyMath'

export type Direction = 'BULLISH' | 'BEARISH' | 'NON_DIRECTIONAL'

export interface TemplateLeg {
  side: Side
  optionType: OptionType
  /** Offset in strike-steps from ATM. 0 = ATM, -1 = one strike ITM for calls, etc. */
  strikeOffset: number
  lots: number
  /**
   * Offset in expiries from the "near" expiry selected in the header.
   * 0 (default) = near expiry. 1 = next expiry in the list (farther out).
   * Used for calendar / diagonal spreads.
   */
  expiryOffset?: number
}

export interface StrategyTemplate {
  id: string
  name: string
  direction: Direction
  description: string
  legs: TemplateLeg[]
  /** Normalized spot used to resolve relative strikes in the mini preview. */
  referenceSpot: number
  /** Normalized strike interval used to resolve relative strikes in the mini preview. */
  strikeStep: number
  /** True when a multi-expiry preview is illustrative rather than terminal intrinsic payoff. */
  illustrativePreview: boolean
  /** Normalised viewBox-(0,0)-(100,40) SVG path for the mini payoff icon. */
  payoffPath: string
}

interface TemplateDefinition
  extends Omit<
    StrategyTemplate,
    'referenceSpot' | 'strikeStep' | 'illustrativePreview' | 'payoffPath'
  > {
  /** Multi-expiry calendars retain time value, so their topology cannot be intrinsic-only. */
  illustrativePath?: string
}

const PREVIEW_REFERENCE_SPOT = 100
const PREVIEW_STRIKE_STEP = 4

/**
 * Synthetic ATM time value, expressed in strike steps.
 *
 * The preview needs a premium, otherwise a long call, a vertical spread and a
 * butterfly all sit entirely on one side of the zero line and read as a step
 * rather than as profit versus loss.
 */
const PREVIEW_ATM_TIME_VALUE_STEPS = 1.2
/**
 * Decay width of the synthetic time value, in strike steps. Must stay at or
 * above twice PREVIEW_ATM_TIME_VALUE_STEPS so the modelled premium curve is
 * convex in the strike — see previewPremium.
 */
const PREVIEW_TIME_VALUE_WIDTH_STEPS = 3
/** Smallest preview window width, in strike steps, so a single-strike payoff still reads. */
const PREVIEW_MIN_WINDOW_STEPS = 3
/** Blank margin drawn on each side of the payoff features, as a fraction of the feature span. */
const PREVIEW_MARGIN_RATIO = 0.22
/** Vertical half-height of the drawn curve. */
const PREVIEW_AMPLITUDE = 16
/** Baseline y of the icon; TemplateGrid draws its dashed zero line here. */
const PREVIEW_ZERO_Y = 20
/** Smallest share of the amplitude the weaker side of the payoff may occupy. */
const PREVIEW_MIN_SIDE_SPAN = 0.35

type PreviewStrategy = Pick<StrategyTemplate, 'legs' | 'referenceSpot' | 'strikeStep'>

function previewStrike(template: PreviewStrategy, leg: TemplateLeg): number {
  return template.referenceSpot + leg.strikeOffset * template.strikeStep
}

/**
 * Deterministic synthetic premium for one preview leg.
 *
 * Time value decays exponentially with distance from the reference spot, and
 * the exponential kink at the money exactly offsets the intrinsic kink, so the
 * modelled premium is convex in the strike. Convexity is what makes derived
 * structures come out with the right sign: butterflies and condors as debits,
 * strangles and iron condors as credits. A concave model (a Gaussian, say)
 * prices a long call condor at a credit, which would draw an all-profit icon.
 */
function previewPremium(template: PreviewStrategy, leg: TemplateLeg): number {
  const strike = previewStrike(template, leg)
  const intrinsic =
    leg.optionType === 'CE'
      ? Math.max(0, template.referenceSpot - strike)
      : Math.max(0, strike - template.referenceSpot)
  const width = PREVIEW_TIME_VALUE_WIDTH_STEPS * template.strikeStep
  const decay = Math.exp(-Math.abs(strike - template.referenceSpot) / width)
  return intrinsic + PREVIEW_ATM_TIME_VALUE_STEPS * template.strikeStep * decay
}

/** Terminal profit and loss of the normalized template legs, net of the synthetic premium. */
export function previewValue(template: PreviewStrategy, spot: number): number {
  const physicalSpot = Math.max(0, spot)
  return template.legs.reduce((total, leg) => {
    const strike = previewStrike(template, leg)
    const intrinsic =
      leg.optionType === 'CE'
        ? Math.max(0, physicalSpot - strike)
        : Math.max(0, strike - physicalSpot)
    const direction = leg.side === 'BUY' ? 1 : -1
    return total + direction * leg.lots * (intrinsic - previewPremium(template, leg))
  }, 0)
}

/** Distinct leg strikes of the normalized template, ascending. */
function previewStrikes(template: PreviewStrategy): number[] {
  return Array.from(new Set(template.legs.map((leg) => previewStrike(template, leg)))).sort(
    (left, right) => left - right
  )
}

/**
 * Slope of the payoff outside the outermost strikes.
 *
 * Below every strike only puts carry intrinsic, and each unit loses one point
 * of value per point of spot. Above every strike only calls carry intrinsic.
 */
function previewTailSlopes(template: PreviewStrategy): { left: number; right: number } {
  let left = 0
  let right = 0
  for (const leg of template.legs) {
    const direction = leg.side === 'BUY' ? 1 : -1
    if (leg.optionType === 'CE') right += direction * leg.lots
    else left -= direction * leg.lots
  }
  return { left, right }
}

/** Spots at which the payoff crosses zero, including the unbounded outer rays. */
function previewBreakevens(template: PreviewStrategy, strikes: number[]): number[] {
  const values = strikes.map((strike) => previewValue(template, strike))
  const crossings: number[] = []
  for (let index = 0; index < strikes.length - 1; index++) {
    const lower = values[index]
    const upper = values[index + 1]
    if ((lower < 0 && upper > 0) || (lower > 0 && upper < 0)) {
      const ratio = lower / (lower - upper)
      crossings.push(strikes[index] + ratio * (strikes[index + 1] - strikes[index]))
    }
  }
  const slopes = previewTailSlopes(template)
  const firstStrike = strikes[0]
  const lastStrike = strikes[strikes.length - 1]
  if (slopes.left !== 0) {
    const crossing = firstStrike - values[0] / slopes.left
    if (crossing >= 0 && crossing < firstStrike) crossings.push(crossing)
  }
  if (slopes.right !== 0) {
    const crossing = lastStrike - values[values.length - 1] / slopes.right
    if (crossing > lastStrike) crossings.push(crossing)
  }
  return crossings
}

/**
 * Spot range the icon spans, derived from the template's own strikes.
 *
 * A fixed window cannot serve every template: a bullish butterfly sits inside
 * eight normalized points while the Batman spans a hundred and twenty, so a
 * shared window collapses one to a spike and leaves the other cramped. The
 * window therefore starts at the strike range and, only when the payoff never
 * changes sign across the strikes, widens to take in the nearest breakeven so
 * the drawn curve still shows both profit and loss.
 */
function previewWindow(
  template: PreviewStrategy,
  strikes: number[]
): { low: number; high: number } {
  const values = strikes.map((strike) => previewValue(template, strike))
  let low = strikes[0]
  let high = strikes[strikes.length - 1]
  const changesSign = values.some((value) => value > 0) && values.some((value) => value < 0)
  if (!changesSign) {
    for (const crossing of previewBreakevens(template, strikes)) {
      low = Math.min(low, crossing)
      high = Math.max(high, crossing)
    }
  }
  const centre = (low + high) / 2
  const span = Math.max(high - low, PREVIEW_MIN_WINDOW_STEPS * template.strikeStep)
  const half = span / 2 + span * PREVIEW_MARGIN_RATIO
  return { low: Math.max(0, centre - half), high: centre + half }
}

function clamp(value: number, lower: number, upper: number): number {
  return Math.min(upper, Math.max(lower, value))
}

/**
 * Build an SVG topology from the actual normalized legs and their strike kinks.
 *
 * Vertices are the window edges plus every strike, which is exact: the payoff
 * is piecewise linear and kinks only at strikes. Profit and loss are scaled
 * independently, but neither side is stretched past the shared scale, so the
 * weaker side stays visible without a lopsided payoff being drawn as balanced.
 */
export function templatePreviewPath(template: PreviewStrategy): string {
  const strikes = previewStrikes(template)
  const window = previewWindow(template, strikes)
  const width = window.high - window.low
  const spots = Array.from(new Set([window.low, ...strikes, window.high])).sort(
    (left, right) => left - right
  )
  const values = spots.map((spot) => previewValue(template, spot))
  const maxProfit = Math.max(0, ...values)
  const maxLoss = Math.max(0, ...values.map((value) => -value))
  const scale = Math.max(maxProfit, maxLoss)
  const profitScale = maxProfit > 0 ? Math.min(scale, maxProfit / PREVIEW_MIN_SIDE_SPAN) : scale
  const lossScale = maxLoss > 0 ? Math.min(scale, maxLoss / PREVIEW_MIN_SIDE_SPAN) : scale
  const points = spots.map((spot, index) => {
    const value = values[index]
    const x = width > 0 ? ((spot - window.low) / width) * 100 : 50
    const offset =
      scale === 0
        ? 0
        : value >= 0
          ? -(value / profitScale) * PREVIEW_AMPLITUDE
          : (-value / lossScale) * PREVIEW_AMPLITUDE
    const y = PREVIEW_ZERO_Y + clamp(offset, -PREVIEW_AMPLITUDE, PREVIEW_AMPLITUDE)
    const command = index === 0 ? 'M' : 'L'
    return `${command}${Number(clamp(x, 0, 100).toFixed(2))},${Number(y.toFixed(2))}`
  })
  return points.join(' ')
}

/**
 * Icons are drawn so that:
 *   x = 0 .. 100 spans the template's own strike window, not a fixed spot range,
 *   y = 4 (top, max profit) .. 36 (bottom, max loss),
 *   the zero line sits at y = 20.
 */
const TEMPLATE_DEFINITIONS: TemplateDefinition[] = [
  // ──────────────────────────────────────────────────────────────────────
  // BULLISH (9)
  // ──────────────────────────────────────────────────────────────────────
  {
    id: 'long_call',
    name: 'Long Call',
    direction: 'BULLISH',
    description: 'Unlimited upside, limited downside. Best for strong bullish view.',
    legs: [{ side: 'BUY', optionType: 'CE', strikeOffset: 0, lots: 1 }],
  },
  {
    id: 'short_put',
    name: 'Short Put',
    direction: 'BULLISH',
    description: 'Collect premium; profit if price stays above strike.',
    legs: [{ side: 'SELL', optionType: 'PE', strikeOffset: 0, lots: 1 }],
  },
  {
    id: 'bull_call_spread',
    name: 'Bull Call Spread',
    direction: 'BULLISH',
    description: 'Buy ATM call, sell OTM call. Capped profit & loss.',
    legs: [
      { side: 'BUY', optionType: 'CE', strikeOffset: 0, lots: 1 },
      { side: 'SELL', optionType: 'CE', strikeOffset: 2, lots: 1 },
    ],
  },
  {
    id: 'bull_put_spread',
    name: 'Bull Put Spread',
    direction: 'BULLISH',
    description: 'Sell ATM put, buy OTM put. Typically opened for a net credit.',
    legs: [
      { side: 'SELL', optionType: 'PE', strikeOffset: 0, lots: 1 },
      { side: 'BUY', optionType: 'PE', strikeOffset: -2, lots: 1 },
    ],
  },
  {
    id: 'call_ratio_back_spread',
    name: 'Call Ratio Back Spread',
    direction: 'BULLISH',
    description:
      'Sell 1 ATM call, buy 2 OTM calls. Entry may be a credit or debit; upside is unlimited if the market rallies hard.',
    legs: [
      { side: 'SELL', optionType: 'CE', strikeOffset: 0, lots: 1 },
      { side: 'BUY', optionType: 'CE', strikeOffset: 2, lots: 2 },
    ],
  },
  {
    id: 'long_synthetic',
    name: 'Long Synthetic',
    direction: 'BULLISH',
    description:
      'Buy ATM call + sell ATM put (same strike). Synthetic long futures — unlimited upside, with downside bounded when spot reaches zero.',
    legs: [
      { side: 'BUY', optionType: 'CE', strikeOffset: 0, lots: 1 },
      { side: 'SELL', optionType: 'PE', strikeOffset: 0, lots: 1 },
    ],
  },
  {
    id: 'range_forward',
    name: 'Range Forward',
    direction: 'BULLISH',
    description:
      'Sell OTM put + buy OTM call. Bullish collar-style structure — limited downside via short put, unlimited upside via long call.',
    legs: [
      { side: 'SELL', optionType: 'PE', strikeOffset: -2, lots: 1 },
      { side: 'BUY', optionType: 'CE', strikeOffset: 2, lots: 1 },
    ],
  },
  {
    id: 'bullish_butterfly',
    name: 'Bullish Butterfly',
    direction: 'BULLISH',
    description:
      'Call butterfly centred above spot — buy 1 ATM CE, sell 2 OTM CE, buy 1 further OTM CE. Max profit if spot rallies to the body strike.',
    legs: [
      { side: 'BUY', optionType: 'CE', strikeOffset: 0, lots: 1 },
      { side: 'SELL', optionType: 'CE', strikeOffset: 2, lots: 2 },
      { side: 'BUY', optionType: 'CE', strikeOffset: 4, lots: 1 },
    ],
  },
  {
    id: 'bullish_condor',
    name: 'Bullish Condor',
    direction: 'BULLISH',
    description:
      'Call condor above spot — profit zone sits over a range of higher strikes. Defined risk on both ends.',
    legs: [
      { side: 'BUY', optionType: 'CE', strikeOffset: 0, lots: 1 },
      { side: 'SELL', optionType: 'CE', strikeOffset: 1, lots: 1 },
      { side: 'SELL', optionType: 'CE', strikeOffset: 3, lots: 1 },
      { side: 'BUY', optionType: 'CE', strikeOffset: 4, lots: 1 },
    ],
  },

  // ──────────────────────────────────────────────────────────────────────
  // BEARISH (9)
  // ──────────────────────────────────────────────────────────────────────
  {
    id: 'short_call',
    name: 'Short Call',
    direction: 'BEARISH',
    description: 'Collect premium; profit if price stays below strike.',
    legs: [{ side: 'SELL', optionType: 'CE', strikeOffset: 0, lots: 1 }],
  },
  {
    id: 'long_put',
    name: 'Long Put',
    direction: 'BEARISH',
    description: 'Profit grows as spot falls but is capped at zero; loss is limited.',
    legs: [{ side: 'BUY', optionType: 'PE', strikeOffset: 0, lots: 1 }],
  },
  {
    id: 'bear_call_spread',
    name: 'Bear Call Spread',
    direction: 'BEARISH',
    description: 'Sell ATM call, buy OTM call. Typically opened for a net credit.',
    legs: [
      { side: 'SELL', optionType: 'CE', strikeOffset: 0, lots: 1 },
      { side: 'BUY', optionType: 'CE', strikeOffset: 2, lots: 1 },
    ],
  },
  {
    id: 'bear_put_spread',
    name: 'Bear Put Spread',
    direction: 'BEARISH',
    description: 'Buy ATM put, sell OTM put. Capped profit & loss.',
    legs: [
      { side: 'BUY', optionType: 'PE', strikeOffset: 0, lots: 1 },
      { side: 'SELL', optionType: 'PE', strikeOffset: -2, lots: 1 },
    ],
  },
  {
    id: 'put_ratio_back_spread',
    name: 'Put Ratio Back Spread',
    direction: 'BEARISH',
    description:
      'Sell 1 ATM put, buy 2 OTM puts. Entry may be a credit or debit; profit grows as spot falls but is capped at zero.',
    legs: [
      { side: 'SELL', optionType: 'PE', strikeOffset: 0, lots: 1 },
      { side: 'BUY', optionType: 'PE', strikeOffset: -2, lots: 2 },
    ],
  },
  {
    id: 'short_synthetic',
    name: 'Short Synthetic',
    direction: 'BEARISH',
    description:
      'Sell ATM call + buy ATM put (same strike). Synthetic short futures — downside profit is capped at zero and upside loss is unlimited.',
    legs: [
      { side: 'SELL', optionType: 'CE', strikeOffset: 0, lots: 1 },
      { side: 'BUY', optionType: 'PE', strikeOffset: 0, lots: 1 },
    ],
  },
  {
    id: 'risk_reversal',
    name: 'Risk Reversal',
    direction: 'BEARISH',
    description:
      'Buy OTM put + sell OTM call. Bearish collar — profits on downside, unlimited upside loss.',
    legs: [
      { side: 'BUY', optionType: 'PE', strikeOffset: -2, lots: 1 },
      { side: 'SELL', optionType: 'CE', strikeOffset: 2, lots: 1 },
    ],
  },
  {
    id: 'bearish_butterfly',
    name: 'Bearish Butterfly',
    direction: 'BEARISH',
    description:
      'Put butterfly centred below spot — buy 1 ATM PE, sell 2 OTM PE, buy 1 further OTM PE. Max profit if spot falls to the body strike.',
    legs: [
      { side: 'BUY', optionType: 'PE', strikeOffset: 0, lots: 1 },
      { side: 'SELL', optionType: 'PE', strikeOffset: -2, lots: 2 },
      { side: 'BUY', optionType: 'PE', strikeOffset: -4, lots: 1 },
    ],
  },
  {
    id: 'bearish_condor',
    name: 'Bearish Condor',
    direction: 'BEARISH',
    description:
      'Put condor below spot — profit zone sits over a range of lower strikes. Defined risk on both ends.',
    legs: [
      { side: 'BUY', optionType: 'PE', strikeOffset: 0, lots: 1 },
      { side: 'SELL', optionType: 'PE', strikeOffset: -1, lots: 1 },
      { side: 'SELL', optionType: 'PE', strikeOffset: -3, lots: 1 },
      { side: 'BUY', optionType: 'PE', strikeOffset: -4, lots: 1 },
    ],
  },

  // ──────────────────────────────────────────────────────────────────────
  // NON-DIRECTIONAL (20)
  // ──────────────────────────────────────────────────────────────────────
  {
    id: 'long_straddle',
    name: 'Long Straddle',
    direction: 'NON_DIRECTIONAL',
    description: 'Buy ATM call + put. Profits from a large move either way.',
    legs: [
      { side: 'BUY', optionType: 'CE', strikeOffset: 0, lots: 1 },
      { side: 'BUY', optionType: 'PE', strikeOffset: 0, lots: 1 },
    ],
  },
  {
    id: 'short_straddle',
    name: 'Short Straddle',
    direction: 'NON_DIRECTIONAL',
    description: 'Sell ATM call + put. Profits if price stays pinned near strike.',
    legs: [
      { side: 'SELL', optionType: 'CE', strikeOffset: 0, lots: 1 },
      { side: 'SELL', optionType: 'PE', strikeOffset: 0, lots: 1 },
    ],
  },
  {
    id: 'long_strangle',
    name: 'Long Strangle',
    direction: 'NON_DIRECTIONAL',
    description: 'Buy OTM call + OTM put. Cheaper than straddle; needs bigger move.',
    legs: [
      { side: 'BUY', optionType: 'PE', strikeOffset: -2, lots: 1 },
      { side: 'BUY', optionType: 'CE', strikeOffset: 2, lots: 1 },
    ],
  },
  {
    id: 'short_strangle',
    name: 'Short Strangle',
    direction: 'NON_DIRECTIONAL',
    description: 'Sell OTM call + OTM put. Wider profit zone than short straddle.',
    legs: [
      { side: 'SELL', optionType: 'PE', strikeOffset: -2, lots: 1 },
      { side: 'SELL', optionType: 'CE', strikeOffset: 2, lots: 1 },
    ],
  },
  {
    id: 'jade_lizard',
    name: 'Jade Lizard',
    direction: 'NON_DIRECTIONAL',
    description:
      'Sell OTM put + short OTM call spread. No risk on upside if credit exceeds call-spread width.',
    legs: [
      { side: 'SELL', optionType: 'PE', strikeOffset: -2, lots: 1 },
      { side: 'SELL', optionType: 'CE', strikeOffset: 2, lots: 1 },
      { side: 'BUY', optionType: 'CE', strikeOffset: 4, lots: 1 },
    ],
  },
  {
    id: 'reverse_jade_lizard',
    name: 'Reverse Jade Lizard',
    direction: 'NON_DIRECTIONAL',
    description:
      'Sell OTM call + short OTM put spread. No risk on downside if credit exceeds put-spread width.',
    legs: [
      { side: 'SELL', optionType: 'CE', strikeOffset: 2, lots: 1 },
      { side: 'SELL', optionType: 'PE', strikeOffset: -2, lots: 1 },
      { side: 'BUY', optionType: 'PE', strikeOffset: -4, lots: 1 },
    ],
  },
  {
    id: 'call_ratio_spread',
    name: 'Call Ratio Spread',
    direction: 'NON_DIRECTIONAL',
    description:
      'Buy 1 ATM call, sell 2 OTM calls. Peak profit at short strike; unlimited upside loss above.',
    legs: [
      { side: 'BUY', optionType: 'CE', strikeOffset: 0, lots: 1 },
      { side: 'SELL', optionType: 'CE', strikeOffset: 2, lots: 2 },
    ],
  },
  {
    id: 'put_ratio_spread',
    name: 'Put Ratio Spread',
    direction: 'NON_DIRECTIONAL',
    description:
      'Buy 1 ATM put, sell 2 OTM puts. Peak profit at the short strike; loss below it is substantial but bounded at spot zero.',
    legs: [
      { side: 'BUY', optionType: 'PE', strikeOffset: 0, lots: 1 },
      { side: 'SELL', optionType: 'PE', strikeOffset: -2, lots: 2 },
    ],
  },
  {
    id: 'batman_strategy',
    name: 'Batman Strategy',
    direction: 'NON_DIRECTIONAL',
    description:
      'Call ratio spread (1×2) above + Put ratio spread (1×2) below. Two-eared "Batman" profile — peaks at the short strikes, with bounded left-tail loss at spot zero and unlimited right-tail loss.',
    legs: [
      // ── CE side: call ratio spread — long 1, short 2 ──
      { side: 'BUY', optionType: 'CE', strikeOffset: 10, lots: 1 },
      { side: 'SELL', optionType: 'CE', strikeOffset: 15, lots: 2 },
      // ── PE side: put ratio spread — long 1, short 2 ──
      { side: 'BUY', optionType: 'PE', strikeOffset: -10, lots: 1 },
      { side: 'SELL', optionType: 'PE', strikeOffset: -15, lots: 2 },
    ],
  },
  {
    id: 'long_iron_fly',
    name: 'Long Iron Fly',
    direction: 'NON_DIRECTIONAL',
    description: 'Short ATM straddle + long OTM wings. Max profit pinned at ATM.',
    legs: [
      { side: 'BUY', optionType: 'PE', strikeOffset: -2, lots: 1 },
      { side: 'SELL', optionType: 'PE', strikeOffset: 0, lots: 1 },
      { side: 'SELL', optionType: 'CE', strikeOffset: 0, lots: 1 },
      { side: 'BUY', optionType: 'CE', strikeOffset: 2, lots: 1 },
    ],
  },
  {
    id: 'short_iron_fly',
    name: 'Short Iron Fly',
    direction: 'NON_DIRECTIONAL',
    description:
      'Long ATM straddle + short OTM wings. Max profit on a big move either way; max loss pinned at ATM.',
    legs: [
      { side: 'SELL', optionType: 'PE', strikeOffset: -2, lots: 1 },
      { side: 'BUY', optionType: 'PE', strikeOffset: 0, lots: 1 },
      { side: 'BUY', optionType: 'CE', strikeOffset: 0, lots: 1 },
      { side: 'SELL', optionType: 'CE', strikeOffset: 2, lots: 1 },
    ],
  },
  {
    id: 'double_fly',
    name: 'Double Fly',
    direction: 'NON_DIRECTIONAL',
    description:
      'Two iron butterflies — one centred below spot, one above. Eight legs total: short straddle at each body strike, long CE wing above and long PE wing below. Two profit peaks at the body strikes, defined risk on both ends.',
    legs: [
      // ── CE legs (grouped first) ──
      // Lower iron fly body @ ATM − 8, CE wing @ ATM − 4 (4 strikes above body)
      { side: 'SELL', optionType: 'CE', strikeOffset: -8, lots: 1 },
      { side: 'BUY', optionType: 'CE', strikeOffset: -4, lots: 1 },
      // Upper iron fly body @ ATM + 8, CE wing @ ATM + 12 (4 strikes above body)
      { side: 'SELL', optionType: 'CE', strikeOffset: 8, lots: 1 },
      { side: 'BUY', optionType: 'CE', strikeOffset: 12, lots: 1 },
      // ── PE legs ──
      // Lower iron fly PE wing @ ATM − 12 (4 strikes below body), body @ ATM − 8
      { side: 'BUY', optionType: 'PE', strikeOffset: -12, lots: 1 },
      { side: 'SELL', optionType: 'PE', strikeOffset: -8, lots: 1 },
      // Upper iron fly PE wing @ ATM + 4 (4 strikes below body), body @ ATM + 8
      { side: 'BUY', optionType: 'PE', strikeOffset: 4, lots: 1 },
      { side: 'SELL', optionType: 'PE', strikeOffset: 8, lots: 1 },
    ],
  },
  {
    id: 'long_iron_condor',
    name: 'Long Iron Condor',
    direction: 'NON_DIRECTIONAL',
    description: 'Bull put spread + bear call spread. Defined-risk range play.',
    legs: [
      { side: 'BUY', optionType: 'PE', strikeOffset: -4, lots: 1 },
      { side: 'SELL', optionType: 'PE', strikeOffset: -2, lots: 1 },
      { side: 'SELL', optionType: 'CE', strikeOffset: 2, lots: 1 },
      { side: 'BUY', optionType: 'CE', strikeOffset: 4, lots: 1 },
    ],
  },
  {
    id: 'short_iron_condor',
    name: 'Short Iron Condor',
    direction: 'NON_DIRECTIONAL',
    description:
      'Reverse of long iron condor — long wings pay off on a big move either way, short body caps upside if spot pins in the middle.',
    legs: [
      { side: 'SELL', optionType: 'PE', strikeOffset: -4, lots: 1 },
      { side: 'BUY', optionType: 'PE', strikeOffset: -2, lots: 1 },
      { side: 'BUY', optionType: 'CE', strikeOffset: 2, lots: 1 },
      { side: 'SELL', optionType: 'CE', strikeOffset: 4, lots: 1 },
    ],
  },
  {
    id: 'double_condor',
    name: 'Double Condor',
    direction: 'NON_DIRECTIONAL',
    description:
      'Call condor + put condor at different strikes. Two wide profit plateaus on either side of spot.',
    legs: [
      { side: 'BUY', optionType: 'PE', strikeOffset: -5, lots: 1 },
      { side: 'SELL', optionType: 'PE', strikeOffset: -4, lots: 1 },
      { side: 'SELL', optionType: 'PE', strikeOffset: -2, lots: 1 },
      { side: 'BUY', optionType: 'PE', strikeOffset: -1, lots: 1 },
      { side: 'BUY', optionType: 'CE', strikeOffset: 1, lots: 1 },
      { side: 'SELL', optionType: 'CE', strikeOffset: 2, lots: 1 },
      { side: 'SELL', optionType: 'CE', strikeOffset: 4, lots: 1 },
      { side: 'BUY', optionType: 'CE', strikeOffset: 5, lots: 1 },
    ],
  },
  {
    id: 'call_calendar',
    name: 'Call Calendar',
    direction: 'NON_DIRECTIONAL',
    description:
      'Sell near-expiry ATM CE, buy far-expiry ATM CE (same strike). The preview is illustrative: outcome depends on premiums, volatility, and the far leg’s residual time value.',
    legs: [
      { side: 'SELL', optionType: 'CE', strikeOffset: 0, lots: 1, expiryOffset: 0 },
      { side: 'BUY', optionType: 'CE', strikeOffset: 0, lots: 1, expiryOffset: 1 },
    ],
    // Asymmetric — steep left-side rise to a sharp peak, gentle fall off
    // to the right (calls lose value as spot drops; the far leg retains
    // value as spot rises so right-side decay is slower).
    illustrativePath: 'M0,32 L25,28 L42,6 L65,18 L100,28',
  },
  {
    id: 'put_calendar',
    name: 'Put Calendar',
    direction: 'NON_DIRECTIONAL',
    description:
      'Sell near-expiry ATM PE, buy far-expiry ATM PE (same strike). The preview is illustrative because premiums, volatility, and residual time value determine the first-expiry result.',
    legs: [
      { side: 'SELL', optionType: 'PE', strikeOffset: 0, lots: 1, expiryOffset: 0 },
      { side: 'BUY', optionType: 'PE', strikeOffset: 0, lots: 1, expiryOffset: 1 },
    ],
    // Mirror of the call calendar — gentle left-side rise, steep fall on
    // the right (puts lose value as spot rises; the far leg retains value
    // as spot falls).
    illustrativePath: 'M0,28 L35,18 L58,6 L75,28 L100,32',
  },
  {
    id: 'diagonal_calendar',
    name: 'Diagonal Calendar',
    direction: 'NON_DIRECTIONAL',
    description:
      'Sell near ATM CE and buy far OTM CE. The preview is illustrative because the far call retains residual time value at the first expiry.',
    legs: [
      { side: 'SELL', optionType: 'CE', strikeOffset: 0, lots: 1, expiryOffset: 0 },
      { side: 'BUY', optionType: 'CE', strikeOffset: 2, lots: 1, expiryOffset: 1 },
    ],
    // Diagonals show a widened peak — two small humps and a plateau
    // between the near-leg strike and the far-leg strike.
    illustrativePath: 'M0,32 L20,28 L38,14 L50,10 L62,14 L78,22 L100,28',
  },
  {
    id: 'call_butterfly',
    name: 'Call Butterfly',
    direction: 'NON_DIRECTIONAL',
    description: 'Long call butterfly centred at ATM. Max profit if spot pins at the body strike.',
    legs: [
      { side: 'BUY', optionType: 'CE', strikeOffset: -2, lots: 1 },
      { side: 'SELL', optionType: 'CE', strikeOffset: 0, lots: 2 },
      { side: 'BUY', optionType: 'CE', strikeOffset: 2, lots: 1 },
    ],
  },
  {
    id: 'put_butterfly',
    name: 'Put Butterfly',
    direction: 'NON_DIRECTIONAL',
    description: 'Long put butterfly centred at ATM. Put-side mirror of the call butterfly.',
    legs: [
      { side: 'BUY', optionType: 'PE', strikeOffset: 2, lots: 1 },
      { side: 'SELL', optionType: 'PE', strikeOffset: 0, lots: 2 },
      { side: 'BUY', optionType: 'PE', strikeOffset: -2, lots: 1 },
    ],
  },
]

export const STRATEGY_TEMPLATES: StrategyTemplate[] = TEMPLATE_DEFINITIONS.map((definition) => {
  const { illustrativePath, ...template } = definition
  const normalized = {
    ...template,
    referenceSpot: PREVIEW_REFERENCE_SPOT,
    strikeStep: PREVIEW_STRIKE_STEP,
    illustrativePreview: illustrativePath !== undefined,
  }
  return {
    ...normalized,
    payoffPath: illustrativePath ?? templatePreviewPath(normalized),
  }
})

export function templatesByDirection(direction: Direction | 'ALL'): StrategyTemplate[] {
  if (direction === 'ALL') return STRATEGY_TEMPLATES
  return STRATEGY_TEMPLATES.filter((t) => t.direction === direction)
}
