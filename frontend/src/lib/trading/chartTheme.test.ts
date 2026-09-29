/**
 * The disarmed Buy and Sell colours. The panel derives its label colour from
 * the fill's luminance, so the muted pair has to stay opaque and parseable;
 * and it has to be a blend of the theme's own pair, not a fixed grey, or the
 * buttons stop saying which is which.
 */
import { describe, expect, it } from 'vitest'

import { mixColors, mutedTradeColors } from './chartTheme'

describe('mixColors', () => {
  it('returns the colour itself at 0 and the target at 1', () => {
    expect(mixColors('#26a69a', 'rgb(0,0,0)', 0)).toBe('rgb(38,166,154)')
    expect(mixColors('#26a69a', 'rgb(0,0,0)', 1)).toBe('rgb(0,0,0)')
  })

  it('blends both forms this module meets: hex and rgb()', () => {
    expect(mixColors('#ffffff', 'rgb(0,0,0)', 0.5)).toBe('rgb(128,128,128)')
    expect(mixColors('rgb(255, 255, 255)', '#000000', 0.5)).toBe('rgb(128,128,128)')
  })

  it('clamps the amount', () => {
    expect(mixColors('#ffffff', '#000000', 2)).toBe('rgb(0,0,0)')
    expect(mixColors('#ffffff', '#000000', -1)).toBe('rgb(255,255,255)')
  })

  it('keeps a colour it cannot read rather than painting a guess', () => {
    expect(mixColors('oklch(0.5 0.1 200)', '#000000', 0.5)).toBe('oklch(0.5 0.1 200)')
    expect(mixColors('#ffffff', 'var(--background)', 0.5)).toBe('#ffffff')
  })
})

describe('mutedTradeColors', () => {
  const theme = { buy: '#26a69a', sell: '#ef5350', background: 'rgb(255,255,255)' }

  it('stays opaque, so the panel can still read a label colour off the fill', () => {
    const m = mutedTradeColors(theme)
    expect(m.buy).toMatch(/^rgb\(\d+,\d+,\d+\)$/)
    expect(m.sell).toMatch(/^rgb\(\d+,\d+,\d+\)$/)
  })

  it('moves each towards the background without reaching it', () => {
    const m = mutedTradeColors(theme)
    expect(m.buy).not.toBe('rgb(38,166,154)')
    expect(m.buy).not.toBe('rgb(255,255,255)')
    expect(m.sell).not.toBe('rgb(239,83,80)')
    expect(m.sell).not.toBe('rgb(255,255,255)')
  })

  it('keeps buy and sell apart, so the muted panel still says which is which', () => {
    const m = mutedTradeColors(theme)
    expect(m.buy).not.toBe(m.sell)
  })

  it('follows the theme it is given, not a fixed palette', () => {
    const dark = mutedTradeColors({ ...theme, background: 'rgb(0,0,0)' })
    const light = mutedTradeColors(theme)
    expect(dark.buy).not.toBe(light.buy)
  })
})
