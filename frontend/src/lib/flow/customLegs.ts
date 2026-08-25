// lib/flow/customLegs.ts
// Leg model for the Multi-Leg Options node's manually built ("custom") legs.
//
// The node stores `legs` as a real array on the node data, not a JSON string:
// the executor resolves it with RuntimeOrderResolver.value(), which only
// unwraps a whole-token `{{path}}` reference and never parses JSON. Keeping it
// an array is also what lets a single field inside one leg carry its own
// `{{webhook.strike}}` template.
//
// Parsing, defaults, validation and serialization live here so they can be
// tested without mounting React; the panel component owns rendering only.

/** How a leg picks its strike. */
export type StrikeMode = 'OFFSET' | 'STRIKE'

/** Where a leg's expiry comes from. */
export type ExpiryMode = 'INHERIT' | 'TYPE' | 'DATE'

export type LegOptionType = 'CE' | 'PE'
export type LegAction = 'BUY' | 'SELL'

/** Editor-side shape of one manually built leg. */
export interface CustomLeg {
  strikeMode: StrikeMode
  /** Used when strikeMode is OFFSET. May hold a `{{...}}` template. */
  offset: string
  /** Used when strikeMode is STRIKE. Empty string while the field is blank. */
  strike: string
  expiryMode: ExpiryMode
  /** Used when expiryMode is TYPE, e.g. `current_week`. */
  expiryType: string
  /** Used when expiryMode is DATE, in DDMMMYY, e.g. `28OCT25`. */
  expiry: string
  optionType: LegOptionType
  action: LegAction
  /** Quantity in lots. */
  quantity: string
  /** Empty means inherit the node's common product. */
  product: string
  /** Empty means inherit the node's common price type. */
  priceType: string
  price: string
  triggerPrice: string
  splitSize: string
}

/** A multi-leg basket the broker will accept without becoming unreviewable. */
export const MAX_CUSTOM_LEGS = 10

export const EXPIRY_DATE_PATTERN = /^\d{2}[A-Z]{3}\d{2}$/
export const OFFSET_PATTERN = /^(?:ATM|(?:ITM|OTM)(?:[1-9]|[1-4]\d|50))$/
/** A field holding a `{{variable}}` reference is resolved at run time, so the
 * editor validates its presence but never its shape. */
export const VARIABLE_PATTERN = /\{\{.*?\}\}/

export function hasVariableReference(value: string): boolean {
  return VARIABLE_PATTERN.test(value)
}

export const EMPTY_CUSTOM_LEG: CustomLeg = {
  strikeMode: 'OFFSET',
  offset: 'ATM',
  strike: '',
  expiryMode: 'INHERIT',
  expiryType: 'current_week',
  expiry: '',
  optionType: 'CE',
  action: 'BUY',
  quantity: '1',
  product: '',
  priceType: '',
  price: '',
  triggerPrice: '',
  splitSize: '',
}

/** Price types that require a positive limit price. */
export const NEEDS_PRICE = new Set(['LIMIT', 'SL'])
/** Price types that require a positive trigger price. */
export const NEEDS_TRIGGER = new Set(['SL', 'SL-M'])

function text(value: unknown): string {
  if (value === null || value === undefined) return ''
  if (typeof value === 'number') return Number.isFinite(value) ? String(value) : ''
  return typeof value === 'string' ? value.trim() : ''
}

/**
 * Read whatever the node currently holds into editor legs.
 *
 * Deliberately forgiving: a workflow may have been hand-written or imported,
 * and dropping a leg the editor does not recognise would silently change what
 * the workflow trades. Unknown values are carried through as text so the user
 * can see and correct them.
 */
export function parseCustomLegs(raw: unknown): CustomLeg[] {
  if (!Array.isArray(raw)) return []
  return raw.filter((entry) => entry && typeof entry === 'object').map((entry) => {
    const leg = entry as Record<string, unknown>
    const strike = text(leg.strike)
    const explicitMode = text(leg.strikeMode).toUpperCase()
    // A leg written by hand may carry a strike without naming the mode.
    const strikeMode: StrikeMode =
      explicitMode === 'STRIKE' || (explicitMode !== 'OFFSET' && strike !== '')
        ? 'STRIKE'
        : 'OFFSET'

    const expiry = text(leg.expiry).toUpperCase()
    const expiryType = text(leg.expiryType).toLowerCase()
    const expiryMode: ExpiryMode = expiry ? 'DATE' : expiryType ? 'TYPE' : 'INHERIT'

    const optionType = text(leg.optionType).toUpperCase()
    const action = text(leg.action).toUpperCase()

    return {
      strikeMode,
      offset: text(leg.offset).toUpperCase() || (strikeMode === 'OFFSET' ? 'ATM' : ''),
      strike,
      expiryMode,
      expiryType: expiryType || 'current_week',
      expiry,
      optionType: optionType === 'PE' ? 'PE' : 'CE',
      action: action === 'SELL' ? 'SELL' : 'BUY',
      quantity: text(leg.quantity) || '1',
      product: text(leg.product).toUpperCase(),
      priceType: text(leg.priceType ?? leg.pricetype).toUpperCase(),
      price: text(leg.price),
      triggerPrice: text(leg.triggerPrice ?? leg.trigger_price),
      splitSize: text(leg.splitSize ?? leg.splitsize),
    }
  })
}

/** Problems found on one leg, keyed by field. */
export type LegProblems = Partial<Record<keyof CustomLeg, string>>

function numberProblem(value: string, label: string, { min }: { min: number }): string | null {
  if (hasVariableReference(value)) return null
  const parsed = Number(value)
  if (value.trim() === '' || !Number.isFinite(parsed)) return `${label} must be a number`
  if (parsed < min) return `${label} must be at least ${min}`
  return null
}

/**
 * Validate one leg against what the executor will accept.
 *
 * Mirrors the checks in flow_executor_service.execute_options_multi_order so a
 * leg that looks valid here is not rejected at run time. A field holding a
 * variable reference is left alone - only the run-time value can be checked.
 */
export function validateCustomLeg(leg: CustomLeg, commonPriceType: string): LegProblems {
  const problems: LegProblems = {}

  if (leg.strikeMode === 'STRIKE') {
    const problem = numberProblem(leg.strike, 'Strike', { min: 0 })
    if (problem) problems.strike = problem
    else if (!hasVariableReference(leg.strike) && Number(leg.strike) <= 0) {
      problems.strike = 'Strike must be greater than 0'
    }
  } else if (!leg.offset.trim()) {
    problems.offset = 'Offset is required'
  } else if (!hasVariableReference(leg.offset) && !OFFSET_PATTERN.test(leg.offset)) {
    problems.offset = 'Use ATM, ITM1-ITM50 or OTM1-OTM50'
  }

  if (leg.expiryMode === 'DATE') {
    if (!leg.expiry.trim()) problems.expiry = 'Expiry is required'
    else if (!hasVariableReference(leg.expiry) && !EXPIRY_DATE_PATTERN.test(leg.expiry)) {
      problems.expiry = 'Use DDMMMYY, e.g. 28OCT25'
    }
  }

  const quantityProblem = numberProblem(leg.quantity, 'Quantity', { min: 1 })
  if (quantityProblem) problems.quantity = quantityProblem

  if (leg.splitSize.trim() !== '') {
    const problem = numberProblem(leg.splitSize, 'Split size', { min: 0 })
    if (problem) problems.splitSize = problem
  }

  // An omitted leg price type inherits the node's, so the price requirement
  // follows whichever one will actually be sent.
  const effectivePriceType = leg.priceType || commonPriceType
  if (NEEDS_PRICE.has(effectivePriceType)) {
    const problem = numberProblem(leg.price, 'Price', { min: 0 })
    if (problem) problems.price = problem
    else if (!hasVariableReference(leg.price) && Number(leg.price) <= 0) {
      problems.price = `${effectivePriceType} needs a price above 0`
    }
  }
  if (NEEDS_TRIGGER.has(effectivePriceType)) {
    const problem = numberProblem(leg.triggerPrice, 'Trigger price', { min: 0 })
    if (problem) problems.triggerPrice = problem
    else if (!hasVariableReference(leg.triggerPrice) && Number(leg.triggerPrice) <= 0) {
      problems.triggerPrice = `${effectivePriceType} needs a trigger price above 0`
    }
  }

  return problems
}

export function validateCustomLegs(legs: CustomLeg[], commonPriceType: string): string | null {
  if (!legs.length) return 'Add at least one leg'
  if (legs.length > MAX_CUSTOM_LEGS) return `At most ${MAX_CUSTOM_LEGS} legs`
  const firstBad = legs.findIndex(
    (leg) => Object.keys(validateCustomLeg(leg, commonPriceType)).length > 0
  )
  return firstBad === -1 ? null : `Leg ${firstBad + 1} is incomplete`
}

/** One leg as the executor reads it. Inherited fields are omitted entirely. */
export type SerializedLeg = Record<string, string | number>

function numeric(value: string): string | number {
  // A variable reference has to survive as text; the executor resolves it.
  if (hasVariableReference(value)) return value
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : value
}

/**
 * Write editor legs back to node data.
 *
 * Only the keys that carry meaning are emitted. An omitted product, price type
 * or expiry is how the executor is told to inherit the node's common value, so
 * writing an empty string instead would turn "inherit" into a rejected value.
 */
export function serializeCustomLegs(legs: CustomLeg[]): SerializedLeg[] {
  return legs.map((leg) => {
    const out: SerializedLeg = {
      strikeMode: leg.strikeMode,
      optionType: leg.optionType,
      action: leg.action,
      quantity: numeric(leg.quantity),
    }

    if (leg.strikeMode === 'STRIKE') out.strike = numeric(leg.strike)
    else out.offset = leg.offset.toUpperCase()

    if (leg.expiryMode === 'DATE') out.expiry = leg.expiry.toUpperCase()
    else if (leg.expiryMode === 'TYPE') out.expiryType = leg.expiryType

    if (leg.product) out.product = leg.product
    if (leg.priceType) out.priceType = leg.priceType
    if (leg.price.trim() !== '') out.price = numeric(leg.price)
    if (leg.triggerPrice.trim() !== '') out.triggerPrice = numeric(leg.triggerPrice)
    if (leg.splitSize.trim() !== '' && Number(leg.splitSize) !== 0) {
      out.splitSize = numeric(leg.splitSize)
    }

    return out
  })
}

/** Readymade strategies whose legs can be loaded into the manual builder. */
export const SEEDABLE_STRATEGIES = [
  'straddle',
  'strangle',
  'iron_condor',
  'bull_call_spread',
  'bear_put_spread',
] as const

export type SeedableStrategy = (typeof SEEDABLE_STRATEGIES)[number]

export function isSeedableStrategy(value: string): value is SeedableStrategy {
  return (SEEDABLE_STRATEGIES as readonly string[]).includes(value)
}

interface SeedOptions {
  /** The node's common action, used by the strategies that follow it. */
  action: LegAction
  /** The node's common quantity, in lots. */
  quantity: string
  /** Width for a strangle, e.g. `OTM2`. */
  strangleWidth: string
}

/**
 * Expand a readymade strategy into editable legs.
 *
 * This is the bridge between the two ways of building a basket: pick a
 * template, load it, then change the strikes, expiries or sides that the
 * template cannot express. It mirrors
 * flow_executor_service._generate_strategy_legs exactly, so loading a template
 * and saving it without edits trades what the generated strategy would have
 * traded -- if the two drift apart, "load and tweak" silently becomes a
 * different position than the one previewed.
 *
 * Iron condor and the two spreads have fixed per-leg sides, so they ignore the
 * common action the same way the generator does.
 */
export function seedLegsFromStrategy(strategy: string, options: SeedOptions): CustomLeg[] {
  const { action, quantity, strangleWidth } = options
  const leg = (offset: string, optionType: LegOptionType, legAction: LegAction): CustomLeg => ({
    ...EMPTY_CUSTOM_LEG,
    offset,
    optionType,
    action: legAction,
    quantity,
  })

  switch (strategy) {
    case 'straddle':
      return [leg('ATM', 'CE', action), leg('ATM', 'PE', action)]
    case 'strangle': {
      const width = strangleWidth || 'OTM2'
      return [leg(width, 'CE', action), leg(width, 'PE', action)]
    }
    case 'iron_condor':
      return [
        leg('OTM2', 'CE', 'SELL'),
        leg('OTM4', 'CE', 'BUY'),
        leg('OTM2', 'PE', 'SELL'),
        leg('OTM4', 'PE', 'BUY'),
      ]
    case 'bull_call_spread':
      return [leg('ATM', 'CE', 'BUY'), leg('OTM2', 'CE', 'SELL')]
    case 'bear_put_spread':
      return [leg('ATM', 'PE', 'BUY'), leg('OTM2', 'PE', 'SELL')]
    default:
      return []
  }
}

/** A short one-line description of a leg, for the collapsed row header. */
export function describeLeg(leg: CustomLeg): string {
  const selector = leg.strikeMode === 'STRIKE' ? leg.strike || 'strike?' : leg.offset || 'offset?'
  const expiry =
    leg.expiryMode === 'DATE'
      ? ` ${leg.expiry || 'expiry?'}`
      : leg.expiryMode === 'TYPE'
        ? ` ${leg.expiryType}`
        : ''
  return `${leg.action} ${leg.quantity}x ${selector}${expiry} ${leg.optionType}`
}
