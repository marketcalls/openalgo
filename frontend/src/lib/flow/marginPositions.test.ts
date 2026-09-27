/**
 * Margin basket parse / serialize / validate rules.
 *
 * These transformations decide what the Margin Calculator node actually sends
 * to the broker, and every rule here is pinned to a backend contract:
 * margin_service.validate_position requires six fields on every leg, and
 * restx_api's MarginPositionSchema declares quantity and price as fields.Str,
 * so a number is rejected outright on the REST path. The node's original
 * placeholder violated both, which is what this editor replaced.
 */

import { describe, expect, it } from 'vitest'
import {
  EMPTY_LEG,
  hasVariableReference,
  MAX_LEGS,
  type MarginLeg,
  parseLegs,
  roundUpToLot,
  serializeLegs,
  unitsToLots,
  validateBasket,
  validateLeg,
} from './marginPositions'

function leg(overrides: Partial<MarginLeg> = {}): MarginLeg {
  return { ...EMPTY_LEG, symbol: 'NIFTY25AUG26FUT', exchange: 'NFO', extra: {}, ...overrides }
}

describe('hasVariableReference', () => {
  it('detects a reference even when the template is valid JSON', () => {
    // The case that matters: this parses cleanly, so the parse error alone
    // would have let the field editor open on it.
    expect(hasVariableReference('[{"symbol":"SBIN","quantity":"{{qty}}"}]')).toBe(true)
    expect(JSON.parse('[{"symbol":"SBIN","quantity":"{{qty}}"}]')).toHaveLength(1)
  })

  it('detects a whole-basket reference', () => {
    expect(hasVariableReference('{{basket}}')).toBe(true)
  })

  it('is false for an ordinary basket and for empty input', () => {
    expect(hasVariableReference('[{"symbol":"SBIN","quantity":"1"}]')).toBe(false)
    expect(hasVariableReference('')).toBe(false)
  })

  it('does not fire on JSON braces alone', () => {
    expect(hasVariableReference('[{"a":{"b":1}}]')).toBe(false)
  })
})

describe('parseLegs', () => {
  it('treats empty input as an empty basket, not an error', () => {
    expect(parseLegs('')).toEqual({ legs: [], error: null })
    expect(parseLegs('   ')).toEqual({ legs: [], error: null })
  })

  it('accepts a lone object as a one-leg basket, matching the executor', () => {
    const { legs, error } = parseLegs('{"symbol":"SBIN","exchange":"NSE"}')
    expect(error).toBeNull()
    expect(legs).toHaveLength(1)
    expect(legs[0].symbol).toBe('SBIN')
  })

  it('reports malformed JSON instead of silently emptying the basket', () => {
    const { legs, error } = parseLegs('[{"symbol":]')
    expect(error).toBeTruthy()
    expect(legs).toEqual([])
  })

  it('rejects a basket containing a non-object rather than dropping it', () => {
    // Pricing only the valid subset would report a partial basket as the whole
    // estimate - the same reason _parse_margin_positions raises.
    const { legs, error } = parseLegs('[{"symbol":"SBIN"}, 42]')
    expect(error).toBe('Every position must be a JSON object')
    expect(legs).toEqual([])
  })

  it('normalizes action casing and fills defaults for absent fields', () => {
    const { legs } = parseLegs('[{"symbol":"SBIN","exchange":"NSE","action":"sell"}]')
    expect(legs[0].action).toBe('SELL')
    expect(legs[0].product).toBe('MIS')
    expect(legs[0].pricetype).toBe('MARKET')
    expect(legs[0].quantity).toBe('1')
  })

  it('coerces numeric quantity and price to the string form the API needs', () => {
    const { legs } = parseLegs('[{"symbol":"SBIN","exchange":"NSE","quantity":75,"price":12.5}]')
    expect(legs[0].quantity).toBe('75')
    expect(legs[0].price).toBe('12.5')
  })

  it('keeps properties the editor does not model', () => {
    const { legs } = parseLegs('[{"symbol":"SBIN","exchange":"NSE","broker_hint":"x","tag":7}]')
    expect(legs[0].extra).toEqual({ broker_hint: 'x', tag: 7 })
  })
})

describe('serializeLegs', () => {
  it('emits every field both validators require', () => {
    const out = JSON.parse(serializeLegs([leg({ quantity: '65' })]))
    expect(out[0]).toEqual({
      symbol: 'NIFTY25AUG26FUT',
      exchange: 'NFO',
      action: 'BUY',
      quantity: '65',
      product: 'MIS',
      pricetype: 'MARKET',
      price: '0',
    })
  })

  it('writes quantity and price as strings', () => {
    const out = JSON.parse(
      serializeLegs([leg({ quantity: '65', pricetype: 'LIMIT', price: '12' })])
    )
    expect(typeof out[0].quantity).toBe('string')
    expect(typeof out[0].price).toBe('string')
  })

  it('zeroes the price for MARKET and keeps it for LIMIT', () => {
    const market = JSON.parse(serializeLegs([leg({ pricetype: 'MARKET', price: '99' })]))
    expect(market[0].price).toBe('0')
    const limit = JSON.parse(serializeLegs([leg({ pricetype: 'LIMIT', price: '99' })]))
    expect(limit[0].price).toBe('99')
  })

  it.each([
    ['MARKET', false],
    ['LIMIT', false],
    ['SL', true],
    ['SL-M', true],
  ])('emits trigger_price for %s only when it applies', (pricetype, expected) => {
    const out = JSON.parse(serializeLegs([leg({ pricetype, trigger_price: '799' })]))
    expect('trigger_price' in out[0]).toBe(expected)
  })

  it('round-trips unknown properties instead of dropping them', () => {
    const original =
      '[{"symbol":"SBIN","exchange":"NSE","quantity":"5","product":"MIS","pricetype":"MARKET","price":"0","broker_hint":"keep-me"}]'
    const { legs } = parseLegs(original)
    const out = JSON.parse(serializeLegs(legs))
    expect(out[0].broker_hint).toBe('keep-me')
  })

  it('lets a modelled field win a collision with an unknown one', () => {
    const withClash = leg({ quantity: '65', extra: { quantity: 'stale' } })
    expect(JSON.parse(serializeLegs([withClash]))[0].quantity).toBe('65')
  })

  it('serializes an empty basket as an empty string, not "[]"', () => {
    // The executor treats a blank positionsJson as "no basket"; "[]" would be
    // an empty array it then has to reject.
    expect(serializeLegs([])).toBe('')
  })
})

describe('validateLeg', () => {
  it('passes a complete MARKET leg', () => {
    expect(validateLeg(leg({ quantity: '65' }))).toEqual({})
  })

  it('requires a symbol', () => {
    expect(validateLeg(leg({ symbol: '   ' })).symbol).toBeTruthy()
  })

  it.each(['0', '-5', '', '1.5', 'abc'])('rejects quantity %s', (quantity) => {
    expect(validateLeg(leg({ quantity })).quantity).toBeTruthy()
  })

  it.each(['LIMIT', 'SL'])('requires a positive price for %s', (pricetype) => {
    // margin_service only rejects a negative price, so a zero-priced LIMIT leg
    // would otherwise reach the broker.
    expect(validateLeg(leg({ pricetype, price: '0', trigger_price: '1' })).price).toBeTruthy()
    expect(validateLeg(leg({ pricetype, price: '10', trigger_price: '1' })).price).toBeUndefined()
  })

  it.each(['SL', 'SL-M'])('requires a positive trigger price for %s', (pricetype) => {
    const problems = validateLeg(leg({ pricetype, price: '10', trigger_price: '0' }))
    expect(problems.trigger_price).toBeTruthy()
  })

  it('rejects values outside the supported enumerations', () => {
    expect(validateLeg(leg({ exchange: 'LSE' })).exchange).toBeTruthy()
    expect(validateLeg(leg({ action: 'HOLD' })).action).toBeTruthy()
    expect(validateLeg(leg({ product: 'XYZ' })).product).toBeTruthy()
    expect(validateLeg(leg({ pricetype: 'ICEBERG' })).pricetype).toBeTruthy()
  })
})

describe('validateBasket', () => {
  it('requires at least one position', () => {
    expect(validateBasket([])).toContain('Add at least one position')
  })

  it('accepts a basket at the 50-leg cap and rejects one past it', () => {
    const good = Array.from({ length: MAX_LEGS }, () => leg({ quantity: '65' }))
    expect(validateBasket(good)).toEqual([])
    expect(validateBasket([...good, leg({ quantity: '65' })])).toContain(
      `A basket can hold at most ${MAX_LEGS} positions`
    )
  })

  it('counts the legs needing attention', () => {
    const problems = validateBasket([leg({ quantity: '65' }), leg({ symbol: '' })])
    expect(problems).toContain('1 position needs attention')
  })
})

describe('lot arithmetic', () => {
  it('converts a clean multiple to whole lots', () => {
    expect(unitsToLots(130, 65)).toBe(2)
    expect(unitsToLots(65, 65)).toBe(1)
  })

  it('refuses to invent lots for an irregular quantity', () => {
    // Returning a rounded value here is what would let the editor rewrite a
    // saved quantity on mount.
    expect(unitsToLots(1, 65)).toBeNull()
    expect(unitsToLots(100, 65)).toBeNull()
  })

  it('returns null for degenerate input', () => {
    expect(unitsToLots(0, 65)).toBeNull()
    expect(unitsToLots(-65, 65)).toBeNull()
    expect(unitsToLots(65, 0)).toBeNull()
  })

  it('rounds up to at least one whole lot', () => {
    expect(roundUpToLot(1, 65)).toBe(65)
    expect(roundUpToLot(100, 65)).toBe(130)
    expect(roundUpToLot(130, 65)).toBe(130)
  })
})
