import { describe, expect, it } from 'vitest'
import { computePayoff, nearestLegDays, payoffPriceRange, type StrategyLeg } from './strategyMath'
import { STRATEGY_TEMPLATES } from './strategyTemplates'
import {
  canReuseChainContract,
  normalizeExpiryCode,
  resolveExpiryOffset,
  resolveListedContract,
  resolveStrikeOffset,
  validateTemplateStrikeTopology,
} from './templateResolution'

describe('template payoff topology', () => {
  it('PB-H4 walks actual irregular strike indexes from ATM', () => {
    const strikes = [80, 90, 100, 110, 130]

    expect(resolveStrikeOffset(strikes, 100, -2)).toBe(80)
    expect(resolveStrikeOffset(strikes, 100, 2)).toBe(130)
  })

  it('PB-H6 rejects a truncated-chain offset instead of clamping', () => {
    expect(resolveStrikeOffset([90, 100, 110], 100, 2)).toBeNull()
  })

  it('PG-21 sorts expiries and refuses to collapse a calendar', () => {
    const expiries = ['28-AUG-2026', '04-AUG-2026']

    expect(resolveExpiryOffset(expiries, '04-AUG-2026', 1)).toBe('28-AUG-2026')
    expect(resolveExpiryOffset(['04-AUG-2026'], '04-AUG-2026', 1)).toBeNull()
  })

  it('PG-13 normalizes expiry formats before deciding whether a chain symbol is reusable', () => {
    expect(normalizeExpiryCode('04-AUG-2026')).toBe('04AUG26')
    expect(normalizeExpiryCode('04-AUG-26')).toBe('04AUG26')
    expect(canReuseChainContract('11AUG26', '04-AUG-26')).toBe(false)
    expect(canReuseChainContract('04AUG26', '04-AUG-26')).toBe(true)
  })

  it('PG-22 rejects a listed strike when the required option contract is absent', () => {
    const chain = [{ strike: 100, ce: null, pe: null }]

    expect(resolveListedContract(chain, 100, 'CE')).toBeNull()
    expect(resolveListedContract(chain, 100, 'PE')).toBeNull()
  })

  it.each(
    STRATEGY_TEMPLATES
  )('$id keeps every distinct offset distinct on an irregular chain', (template) => {
    const strikes = Array.from({ length: 41 }, (_, index) => {
      const distance = index - 20
      return 1000 + distance * 10 + Math.sign(distance) * Math.floor(Math.abs(distance) / 4) * 5
    })
    const resolved = template.legs.map((leg) => ({
      ...leg,
      resolvedStrike: resolveStrikeOffset(strikes, 1000, leg.strikeOffset),
    }))

    expect(resolved.every((leg) => leg.resolvedStrike !== null)).toBe(true)
    expect(validateTemplateStrikeTopology(resolved)).toEqual([])

    const strikeByOffset = new Map<number, number>()
    for (const leg of resolved) {
      const strike = leg.resolvedStrike as number
      const previous = strikeByOffset.get(leg.strikeOffset)
      if (previous === undefined) strikeByOffset.set(leg.strikeOffset, strike)
      else expect(strike).toBe(previous)
    }
    expect(new Set(strikeByOffset.values()).size).toBe(strikeByOffset.size)
  })

  it.each(STRATEGY_TEMPLATES)('$id produces finite, exact payoff vertices', (template) => {
    const strikes = Array.from({ length: 41 }, (_, index) => 800 + index * 10)
    const legs: StrategyLeg[] = template.legs.map((leg, index) => {
      const strike = resolveStrikeOffset(strikes, 1000, leg.strikeOffset)
      if (strike === null) throw new Error(`Fixture cannot resolve ${template.id}`)
      return {
        id: `${template.id}-${index}`,
        segment: 'OPTION',
        side: leg.side,
        optionType: leg.optionType,
        strike,
        lots: leg.lots,
        lotSize: 1,
        expiry: leg.expiryOffset === 1 ? '28AUG26' : '04AUG26',
        price: 5 + Math.abs(strike - 1000) * 0.01,
        iv: 20,
        active: true,
        symbol: `${template.id}-${index}`,
      }
    })
    const range = payoffPriceRange(1000, legs, 20, 7 / 365)
    const payoff = computePayoff(
      legs,
      1000,
      7,
      0,
      range,
      48,
      0,
      20,
      new Date('2026-07-28T10:00:00.000Z')
    )
    const xs = payoff.samples.map((sample) => sample.underlying)

    for (const leg of legs) {
      expect(xs).toContain(leg.strike)
    }
    expect(payoff.samples.every((sample) => Number.isFinite(sample.expiry))).toBe(true)
    expect(payoff.samples.every((sample) => Number.isFinite(sample.tplus0))).toBe(true)
    expect(Number.isNaN(payoff.maxProfit)).toBe(false)
    expect(Number.isNaN(payoff.maxLoss)).toBe(false)
    expect(payoff.maxProfit).toBeGreaterThanOrEqual(payoff.maxLoss)
    expect(payoff.breakevens).toEqual(
      Array.from(new Set(payoff.breakevens)).sort((left, right) => left - right)
    )
  })

  // The fixture above carries no forward basis, which is precisely why it
  // stayed green while the plotted domain collapsed to zero in production.
  // Every live leg gets referenceUnderlying and forwardPrice from the chain,
  // and Indian index options trade in contango, so that is the case to cover.
  it.each(STRATEGY_TEMPLATES)('$id frames a contango payoff around spot', (template) => {
    const spot = 24_800
    const now = new Date('2026-07-28T10:00:00.000Z')
    const nearExpiryTs = now.getTime() / 1000 + 7 * 86_400
    const farExpiryTs = now.getTime() / 1000 + 35 * 86_400
    const strikes = Array.from({ length: 41 }, (_, index) => spot + (index - 20) * 50)
    // One carry curve for the whole chain, as a real book quotes it: the far
    // expiry carries further, so its forward is higher. Giving both expiries
    // the same forward would imply the near leg carries five times as fast as
    // the far one, and a calendar built on that inconsistency shows a tail
    // slope the market does not have.
    const CARRY_RATE = 0.06
    const forwardFor = (expiryTs: number) =>
      spot * Math.exp((CARRY_RATE * (expiryTs * 1000 - now.getTime())) / (365 * 86_400_000))

    const legs: StrategyLeg[] = template.legs.map((leg, index) => {
      const strike = resolveStrikeOffset(strikes, spot, leg.strikeOffset)
      if (strike === null) throw new Error(`Fixture cannot resolve ${template.id}`)
      const isFar = leg.expiryOffset === 1
      const expiryTs = isFar ? farExpiryTs : nearExpiryTs
      return {
        id: `${template.id}-${index}`,
        segment: 'OPTION',
        side: leg.side,
        optionType: leg.optionType,
        strike,
        lots: leg.lots,
        lotSize: 75,
        expiry: isFar ? '28AUG26' : '04AUG26',
        expiryTs,
        // A far-expiry leg carries more time value, so a calendar is a real
        // net debit rather than a costless pair.
        price: (40 + Math.abs(strike - spot) * 0.02) * (isFar ? 2.2 : 1),
        iv: 12,
        active: true,
        symbol: `${template.id}-${index}`,
        referenceUnderlying: spot,
        forwardPrice: forwardFor(expiryTs),
      }
    })

    const nearestDays = nearestLegDays(legs, now)
    const range = payoffPriceRange(spot, legs, 12, nearestDays / 365)
    const payoff = computePayoff(legs, spot, nearestDays, 0, range, 240, 0, 12, now)
    const low = payoff.samples[0].underlying
    const high = payoff.samples[payoff.samples.length - 1].underlying

    // The regression: the forward-zero vertex clamps to 0 in contango, and
    // framing the chart with it made every template span 0 to roughly spot.
    expect(low).toBeGreaterThan(0)
    expect(high - low).toBeLessThan(spot)
    // Spot must stay inside the drawn window, or the trader cannot see where
    // the strategy actually sits.
    expect(low).toBeLessThanOrEqual(spot)
    expect(high).toBeGreaterThanOrEqual(spot)

    expect(payoff.samples.every((sample) => Number.isFinite(sample.expiry))).toBe(true)
    expect(payoff.samples.every((sample) => Number.isFinite(sample.tplus0))).toBe(true)
    expect(payoff.samples.every((sample) => sample.underlying >= low)).toBe(true)
    expect(Number.isNaN(payoff.maxProfit)).toBe(false)
    expect(Number.isNaN(payoff.maxLoss)).toBe(false)
    expect(payoff.maxProfit).toBeGreaterThanOrEqual(payoff.maxLoss)
    expect(payoff.breakevens).toEqual(
      Array.from(new Set(payoff.breakevens)).sort((left, right) => left - right)
    )
  })
})
