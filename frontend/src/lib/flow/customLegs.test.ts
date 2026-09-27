import { describe, expect, it } from 'vitest'
import {
  type CustomLeg,
  describeLeg,
  EMPTY_CUSTOM_LEG,
  MAX_CUSTOM_LEGS,
  parseCustomLegs,
  seedLegsFromStrategy,
  serializeCustomLegs,
  validateCustomLeg,
  validateCustomLegs,
} from './customLegs'

/**
 * The multi-leg node stores `legs` as a real array. Everything the editor knows
 * how to express has to survive the round trip through that array, because the
 * executor reads it directly -- a field the serializer drops is a leg the user
 * built and the broker never sees.
 */

const leg = (patch: Partial<CustomLeg> = {}): CustomLeg => ({ ...EMPTY_CUSTOM_LEG, ...patch })

describe('parseCustomLegs', () => {
  it('reads nothing out of a non-array', () => {
    expect(parseCustomLegs(undefined)).toEqual([])
    expect(parseCustomLegs(null)).toEqual([])
    expect(parseCustomLegs('[]')).toEqual([])
  })

  it('infers STRIKE mode from a leg that names a strike without saying so', () => {
    /** A hand-written workflow has no reason to include strikeMode. */
    const [parsed] = parseCustomLegs([
      { strike: 24500, optionType: 'CE', action: 'BUY', quantity: 2 },
    ])
    expect(parsed.strikeMode).toBe('STRIKE')
    expect(parsed.strike).toBe('24500')
  })

  it('keeps an explicit OFFSET mode even when a stale strike is present', () => {
    const [parsed] = parseCustomLegs([
      { strikeMode: 'OFFSET', offset: 'OTM2', strike: 24500, optionType: 'PE', action: 'SELL' },
    ])
    expect(parsed.strikeMode).toBe('OFFSET')
    expect(parsed.offset).toBe('OTM2')
  })

  it('derives the expiry mode from whichever expiry field is present', () => {
    expect(parseCustomLegs([{ offset: 'ATM' }])[0].expiryMode).toBe('INHERIT')
    expect(parseCustomLegs([{ offset: 'ATM', expiryType: 'next_month' }])[0].expiryMode).toBe('TYPE')
    expect(parseCustomLegs([{ offset: 'ATM', expiry: '28oct25' }])[0].expiryMode).toBe('DATE')
  })

  it('accepts the snake_case aliases the executor also accepts', () => {
    const [parsed] = parseCustomLegs([
      { offset: 'ATM', pricetype: 'LIMIT', trigger_price: 12, splitsize: 5 },
    ])
    expect(parsed.priceType).toBe('LIMIT')
    expect(parsed.triggerPrice).toBe('12')
    expect(parsed.splitSize).toBe('5')
  })

  it('carries an unrecognised value through as text rather than dropping the leg', () => {
    /** Silently discarding a leg would change what a saved workflow trades. */
    const [parsed] = parseCustomLegs([{ offset: 'WEIRD', optionType: 'XX', action: 'HOLD' }])
    expect(parsed.offset).toBe('WEIRD')
    // Unknown enums fall back to a valid value rather than an unsendable one.
    expect(parsed.optionType).toBe('CE')
    expect(parsed.action).toBe('BUY')
  })
})

describe('serializeCustomLegs', () => {
  it('sends exactly one strike selector', () => {
    const [offsetLeg] = serializeCustomLegs([leg({ strikeMode: 'OFFSET', offset: 'OTM2' })])
    expect(offsetLeg.offset).toBe('OTM2')
    expect(offsetLeg).not.toHaveProperty('strike')

    const [strikeLeg] = serializeCustomLegs([leg({ strikeMode: 'STRIKE', strike: '24500' })])
    expect(strikeLeg.strike).toBe(24500)
    expect(strikeLeg).not.toHaveProperty('offset')
  })

  it('omits an inherited field entirely instead of writing an empty string', () => {
    /** The executor reads an absent key as "use the node's value"; an empty
     * string is a value, and a rejected one. */
    const [out] = serializeCustomLegs([leg({ expiryMode: 'INHERIT', product: '', priceType: '' })])
    expect(out).not.toHaveProperty('expiry')
    expect(out).not.toHaveProperty('expiryType')
    expect(out).not.toHaveProperty('product')
    expect(out).not.toHaveProperty('priceType')
  })

  it('emits only the expiry field the chosen mode means', () => {
    const [byType] = serializeCustomLegs([leg({ expiryMode: 'TYPE', expiryType: 'next_month' })])
    expect(byType.expiryType).toBe('next_month')
    expect(byType).not.toHaveProperty('expiry')

    const [byDate] = serializeCustomLegs([leg({ expiryMode: 'DATE', expiry: '28OCT25' })])
    expect(byDate.expiry).toBe('28OCT25')
    expect(byDate).not.toHaveProperty('expiryType')
  })

  it('keeps a variable reference as text so the executor can resolve it', () => {
    const [out] = serializeCustomLegs([
      leg({ strikeMode: 'STRIKE', strike: '{{webhook.strike}}', quantity: '{{webhook.lots}}' }),
    ])
    expect(out.strike).toBe('{{webhook.strike}}')
    expect(out.quantity).toBe('{{webhook.lots}}')
  })

  it('drops a zero split size, which means no split', () => {
    expect(serializeCustomLegs([leg({ splitSize: '0' })])[0]).not.toHaveProperty('splitSize')
    expect(serializeCustomLegs([leg({ splitSize: '5' })])[0].splitSize).toBe(5)
  })

  it('round-trips a fully specified leg', () => {
    const original = leg({
      strikeMode: 'STRIKE',
      strike: '24500',
      expiryMode: 'DATE',
      expiry: '28OCT25',
      optionType: 'PE',
      action: 'SELL',
      quantity: '3',
      product: 'NRML',
      priceType: 'SL',
      price: '10',
      triggerPrice: '9',
      splitSize: '2',
    })
    const [reparsed] = parseCustomLegs(serializeCustomLegs([original]))
    expect(reparsed).toEqual({ ...original, offset: '' })
  })
})

describe('seedLegsFromStrategy', () => {
  const options = { action: 'SELL' as const, quantity: '2', strangleWidth: 'OTM3' }

  it('expands a straddle to two ATM legs on the common action', () => {
    const legs = seedLegsFromStrategy('straddle', options)
    expect(legs.map((l) => [l.offset, l.optionType, l.action])).toEqual([
      ['ATM', 'CE', 'SELL'],
      ['ATM', 'PE', 'SELL'],
    ])
    expect(legs.every((l) => l.quantity === '2')).toBe(true)
  })

  it('uses the configured strangle width', () => {
    expect(seedLegsFromStrategy('strangle', options).map((l) => l.offset)).toEqual([
      'OTM3',
      'OTM3',
    ])
  })

  it('falls back to OTM2 when no width is set', () => {
    const legs = seedLegsFromStrategy('strangle', { ...options, strangleWidth: '' })
    expect(legs.map((l) => l.offset)).toEqual(['OTM2', 'OTM2'])
  })

  it('gives an iron condor its own per-leg sides regardless of the common action', () => {
    /** The generator ignores the common action for this shape; so must we, or
     * loading the template would trade the inverse position. */
    const legs = seedLegsFromStrategy('iron_condor', { ...options, action: 'BUY' })
    expect(legs.map((l) => [l.offset, l.optionType, l.action])).toEqual([
      ['OTM2', 'CE', 'SELL'],
      ['OTM4', 'CE', 'BUY'],
      ['OTM2', 'PE', 'SELL'],
      ['OTM4', 'PE', 'BUY'],
    ])
  })

  it('expands both vertical spreads', () => {
    expect(seedLegsFromStrategy('bull_call_spread', options).map((l) => [l.offset, l.action]))
      .toEqual([
        ['ATM', 'BUY'],
        ['OTM2', 'SELL'],
      ])
    expect(seedLegsFromStrategy('bear_put_spread', options).map((l) => [l.offset, l.action]))
      .toEqual([
        ['ATM', 'BUY'],
        ['OTM2', 'SELL'],
      ])
  })

  it('seeds legs that inherit the node expiry, so a template is unchanged until edited', () => {
    expect(seedLegsFromStrategy('straddle', options).every((l) => l.expiryMode === 'INHERIT')).toBe(
      true
    )
  })

  it('returns nothing for a strategy with no fixed legs', () => {
    expect(seedLegsFromStrategy('custom', options)).toEqual([])
    expect(seedLegsFromStrategy('not_a_strategy', options)).toEqual([])
  })

  it('produces legs that pass validation as they come', () => {
    for (const strategy of ['straddle', 'strangle', 'iron_condor', 'bull_call_spread']) {
      expect(validateCustomLegs(seedLegsFromStrategy(strategy, options), 'MARKET')).toBeNull()
    }
  })
})

describe('validateCustomLeg', () => {
  it('accepts a plain offset leg', () => {
    expect(validateCustomLeg(leg(), 'MARKET')).toEqual({})
  })

  it('rejects an offset that names no strike', () => {
    expect(validateCustomLeg(leg({ offset: 'OTM99' }), 'MARKET').offset).toBeTruthy()
    expect(validateCustomLeg(leg({ offset: '' }), 'MARKET').offset).toBeTruthy()
  })

  it('rejects a non-positive strike', () => {
    const strikeLeg = (strike: string) => leg({ strikeMode: 'STRIKE', strike })
    expect(validateCustomLeg(strikeLeg('0'), 'MARKET').strike).toBeTruthy()
    expect(validateCustomLeg(strikeLeg('-100'), 'MARKET').strike).toBeTruthy()
    expect(validateCustomLeg(strikeLeg(''), 'MARKET').strike).toBeTruthy()
    expect(validateCustomLeg(strikeLeg('24500'), 'MARKET').strike).toBeUndefined()
  })

  it('rejects a malformed exact expiry', () => {
    const dated = (expiry: string) => leg({ expiryMode: 'DATE', expiry })
    expect(validateCustomLeg(dated('2025-10-28'), 'MARKET').expiry).toBeTruthy()
    expect(validateCustomLeg(dated(''), 'MARKET').expiry).toBeTruthy()
    expect(validateCustomLeg(dated('28OCT25'), 'MARKET').expiry).toBeUndefined()
  })

  it('does not check the expiry text when the leg inherits', () => {
    expect(validateCustomLeg(leg({ expiryMode: 'INHERIT', expiry: 'junk' }), 'MARKET')).toEqual({})
  })

  it('applies the price requirement of whichever price type will be sent', () => {
    /** An omitted leg price type inherits the node's, so a node-level LIMIT
     * makes the leg price required even though the leg names no type. */
    expect(validateCustomLeg(leg(), 'LIMIT').price).toBeTruthy()
    expect(validateCustomLeg(leg({ price: '100' }), 'LIMIT').price).toBeUndefined()
    expect(validateCustomLeg(leg({ priceType: 'MARKET' }), 'LIMIT').price).toBeUndefined()
  })

  it('requires a trigger for the stop types', () => {
    expect(validateCustomLeg(leg({ priceType: 'SL-M' }), 'MARKET').triggerPrice).toBeTruthy()
    expect(
      validateCustomLeg(leg({ priceType: 'SL-M', triggerPrice: '95' }), 'MARKET').triggerPrice
    ).toBeUndefined()
  })

  it('leaves a variable reference to the executor', () => {
    expect(validateCustomLeg(leg({ price: '{{wh.px}}', priceType: 'LIMIT' }), 'MARKET')).toEqual({})
    expect(validateCustomLeg(leg({ offset: '{{wh.offset}}' }), 'MARKET')).toEqual({})
  })

  it('requires at least one lot', () => {
    expect(validateCustomLeg(leg({ quantity: '0' }), 'MARKET').quantity).toBeTruthy()
    expect(validateCustomLeg(leg({ quantity: '' }), 'MARKET').quantity).toBeTruthy()
  })
})

describe('validateCustomLegs', () => {
  it('needs at least one leg', () => {
    expect(validateCustomLegs([], 'MARKET')).toBe('Add at least one leg')
  })

  it('names the first incomplete leg', () => {
    expect(validateCustomLegs([leg(), leg({ offset: '' })], 'MARKET')).toBe('Leg 2 is incomplete')
  })

  it('caps the basket', () => {
    const many = Array.from({ length: MAX_CUSTOM_LEGS + 1 }, () => leg())
    expect(validateCustomLegs(many, 'MARKET')).toContain(String(MAX_CUSTOM_LEGS))
  })
})

describe('describeLeg', () => {
  it('summarises an offset leg', () => {
    expect(describeLeg(leg({ action: 'SELL', quantity: '2', offset: 'OTM2', optionType: 'PE' })))
      .toBe('SELL 2x OTM2 PE')
  })

  it('shows the strike and expiry a leg overrides', () => {
    expect(
      describeLeg(
        leg({ strikeMode: 'STRIKE', strike: '24500', expiryMode: 'DATE', expiry: '28OCT25' })
      )
    ).toBe('BUY 1x 24500 28OCT25 CE')
  })
})
