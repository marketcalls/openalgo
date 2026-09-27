// lib/flow/marginPositions.ts
// Pure parse / validate / serialize helpers for the Margin Calculator node's
// basket, kept out of the React component so the edge cases can be tested
// without mounting anything.
//
// The node stores its basket as a JSON string; the backend interpolates and
// parses it (flow_executor_service._parse_margin_positions) before handing the
// array to services/margin_service. The rules encoded here mirror that
// contract: margin_service.validate_position requires exchange, symbol, action,
// quantity, product and pricetype on every leg, and restx_api's
// MarginPositionSchema declares quantity and price as fields.Str, so numbers
// are rejected outright on the REST path.

import {
  EXCHANGES,
  ORDER_ACTIONS,
  PRICE_TYPES,
  PRODUCT_TYPES,
  defaultProductForExchange,
} from '@/lib/flow/constants'

export interface MarginLeg {
  symbol: string
  exchange: string
  action: string
  quantity: string
  product: string
  pricetype: string
  price: string
  trigger_price: string
  /**
   * Properties the editor does not model. Kept verbatim so a parse-edit-
   * serialize round trip cannot drop a broker-specific or future field that a
   * hand-written basket relied on.
   */
  extra: Record<string, unknown>
}

export const EMPTY_LEG: MarginLeg = {
  symbol: '',
  exchange: 'NSE',
  action: 'BUY',
  quantity: '1',
  product: defaultProductForExchange('NSE'),
  pricetype: 'MARKET',
  price: '0',
  trigger_price: '0',
  extra: {},
}

/** Price types whose leg carries a limit price / a stop trigger. */
export const NEEDS_PRICE = new Set(['LIMIT', 'SL'])
export const NEEDS_TRIGGER = new Set(['SL', 'SL-M'])

/** Exchanges whose quantity is entered in lots, matching the options tools. */
export const LOT_TRADED_EXCHANGES = new Set(['NFO', 'BFO'])

/** margin_service caps a basket at 50 positions. */
export const MAX_LEGS = 50

const MODELLED_KEYS = new Set([
  'symbol',
  'exchange',
  'action',
  'quantity',
  'product',
  'pricetype',
  'price',
  'trigger_price',
])

const VALID_EXCHANGES = new Set<string>(EXCHANGES.map((e) => e.value))
const VALID_ACTIONS = new Set<string>(ORDER_ACTIONS.map((a) => a.value))
const VALID_PRODUCTS = new Set<string>(PRODUCT_TYPES.map((p) => p.value))
const VALID_PRICE_TYPES = new Set<string>(PRICE_TYPES.map((p) => p.value))

function toLeg(entry: Record<string, unknown>): MarginLeg {
  const str = (key: string, fallback: string) => {
    const raw = entry[key]
    return raw === undefined || raw === null || raw === '' ? fallback : String(raw)
  }
  const extra: Record<string, unknown> = {}
  for (const [key, val] of Object.entries(entry)) {
    if (!MODELLED_KEYS.has(key)) extra[key] = val
  }
  const exchange = str('exchange', 'NSE')
  return {
    symbol: str('symbol', ''),
    exchange,
    action: str('action', 'BUY').toUpperCase(),
    quantity: str('quantity', '1'),
    // A leg that names no product follows its own exchange, so an NFO leg is
    // priced as the NRML carry position it is rather than as intraday margin.
    product: str('product', defaultProductForExchange(exchange)),
    pricetype: str('pricetype', 'MARKET'),
    price: str('price', '0'),
    trigger_price: str('trigger_price', '0'),
    extra,
  }
}

/**
 * Whether the raw basket references a workflow variable.
 *
 * The backend interpolates `{{name}}` before parsing, so the stored text is a
 * template rather than the basket that will actually be priced. Some templates
 * still parse as valid JSON - `{"quantity": "{{qty}}"}` is a well-formed string
 * - which would let the field editor open on them. It must not: the fields
 * would report `{{qty}}` as an invalid quantity, and serializing would drop a
 * `{{price}}` under a price type the template has not resolved yet.
 */
export function hasVariableReference(raw: string): boolean {
  return /\{\{[^}]*\}\}/.test(raw || '')
}

export interface ParseResult {
  legs: MarginLeg[]
  error: string | null
}

export function parseLegs(raw: string): ParseResult {
  const text = (raw || '').trim()
  if (!text) return { legs: [], error: null }
  let parsed: unknown
  try {
    parsed = JSON.parse(text)
  } catch (e) {
    return { legs: [], error: e instanceof Error ? e.message : 'Invalid JSON' }
  }
  // The executor accepts a lone object as a one-leg basket, so the editor does
  // too rather than pushing the user into JSON mode over it.
  const list = Array.isArray(parsed) ? parsed : [parsed]
  if (list.some((e) => e === null || typeof e !== 'object' || Array.isArray(e))) {
    // Never drop the bad entries: pricing the valid subset would report a
    // partial basket as the whole estimate, which is what the executor's own
    // _parse_margin_positions refuses to do.
    return { legs: [], error: 'Every position must be a JSON object' }
  }
  return { legs: list.map((e) => toLeg(e as Record<string, unknown>)), error: null }
}

/**
 * Serialize to the exact shape both validators accept. quantity and price go
 * out as strings because MarginPositionSchema rejects numbers; trigger_price is
 * emitted only for the price types that use it. Unknown properties are written
 * back first so a modelled field always wins a name collision.
 */
export function serializeLegs(legs: MarginLeg[]): string {
  if (!legs.length) return ''
  return JSON.stringify(
    legs.map((leg) => ({
      ...leg.extra,
      symbol: leg.symbol,
      exchange: leg.exchange,
      action: leg.action,
      quantity: String(leg.quantity || '0'),
      product: leg.product,
      pricetype: leg.pricetype,
      price: String(NEEDS_PRICE.has(leg.pricetype) ? leg.price || '0' : '0'),
      ...(NEEDS_TRIGGER.has(leg.pricetype)
        ? { trigger_price: String(leg.trigger_price || '0') }
        : {}),
    }))
  )
}

export type LegProblems = Partial<Record<keyof MarginLeg, string>>

function positive(value: string): number | null {
  const n = Number(value)
  return Number.isFinite(n) && n > 0 ? n : null
}

/**
 * Field-level problems for one leg, mirroring margin_service.validate_position
 * plus the two price rules it does not cover (it only rejects a negative
 * price, so a LIMIT leg priced at 0 reaches the broker).
 */
export function validateLeg(leg: MarginLeg): LegProblems {
  const problems: LegProblems = {}
  if (!leg.symbol.trim()) problems.symbol = 'Symbol is required'
  if (!VALID_EXCHANGES.has(leg.exchange)) problems.exchange = 'Unsupported exchange'
  if (!VALID_ACTIONS.has(leg.action)) problems.action = 'Action must be BUY or SELL'
  if (!VALID_PRODUCTS.has(leg.product)) problems.product = 'Unsupported product'
  if (!VALID_PRICE_TYPES.has(leg.pricetype)) problems.pricetype = 'Unsupported price type'

  const qty = Number(leg.quantity)
  if (!Number.isInteger(qty) || qty <= 0) {
    problems.quantity = 'Quantity must be a positive whole number'
  }
  if (NEEDS_PRICE.has(leg.pricetype) && positive(leg.price) === null) {
    problems.price = `${leg.pricetype} needs a price above 0`
  }
  if (NEEDS_TRIGGER.has(leg.pricetype) && positive(leg.trigger_price) === null) {
    problems.trigger_price = `${leg.pricetype} needs a trigger price above 0`
  }
  return problems
}

/** Basket-level problems, or an empty array when the basket is submittable. */
export function validateBasket(legs: MarginLeg[]): string[] {
  const problems: string[] = []
  if (!legs.length) problems.push('Add at least one position')
  if (legs.length > MAX_LEGS) problems.push(`A basket can hold at most ${MAX_LEGS} positions`)
  const bad = legs.reduce((count, leg) => count + (Object.keys(validateLeg(leg)).length ? 1 : 0), 0)
  if (bad) {
    problems.push(bad === 1 ? '1 position needs attention' : `${bad} positions need attention`)
  }
  return problems
}

/** Cache/lookup key for one contract's lot size. */
export function lotKey(symbol: string, exchange: string): string {
  return `${exchange}:${symbol}`.toUpperCase()
}

/** Whole lots the stored unit quantity represents, or null when it is not a
 * clean multiple - the caller shows units and offers to round rather than
 * silently rewriting what the user saved. */
export function unitsToLots(units: number, lotSize: number): number | null {
  if (!Number.isFinite(units) || units <= 0 || lotSize <= 0) return null
  return units % lotSize === 0 ? units / lotSize : null
}

/** Nearest whole-lot unit count, at least one lot. */
export function roundUpToLot(units: number, lotSize: number): number {
  if (lotSize <= 0) return units
  return Math.max(1, Math.round(units / lotSize)) * lotSize
}
