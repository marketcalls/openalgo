import { describe, expect, it } from 'vitest'
import {
  COMPARISON_SCALES,
  comparisonReading,
  comparisonScaleOf,
  rebasingMode,
  storedComparisonMode,
  unionRange,
} from './comparisonScale'

describe('comparison scales', () => {
  it('offers four choices in menu order', () => {
    expect(COMPARISON_SCALES.map((item) => item.label)).toEqual([
      'Price',
      'Percentage',
      'Indexed to 100',
      'Own scale',
    ])
  })

  it('writes each choice into the two values a saved chart has room for', () => {
    expect(storedComparisonMode('price')).toBe('price')
    expect(storedComparisonMode('own')).toBe('price')
    expect(storedComparisonMode('percent')).toBe('percent')
    expect(storedComparisonMode('indexed')).toBe('percent')
  })

  it('reads a chart saved before the choice existed as it was drawn', () => {
    expect(comparisonScaleOf('price')).toBe('own')
    expect(comparisonScaleOf('percent')).toBe('percent')
    expect(comparisonScaleOf('price', 'price')).toBe('price')
    expect(comparisonScaleOf('percent', 'indexed')).toBe('indexed')
    expect(comparisonScaleOf('percent', 'own')).toBe('percent')
    expect(comparisonScaleOf('price', 'nonsense')).toBe('own')
  })

  it('rebases the pane only for Percentage and Indexed to 100', () => {
    expect(rebasingMode('percent')).toBe('percentage')
    expect(rebasingMode('indexed')).toBe('indexed-to-100')
    expect(rebasingMode('price')).toBeNull()
    expect(rebasingMode('own')).toBeNull()
  })
})

describe('the shared price axis range', () => {
  it('widens the chart range to hold every finite value', () => {
    expect(unionRange({ min: 100, max: 120 }, [90, 240, Number.NaN])).toEqual({ min: 90, max: 240 })
    expect(unionRange(null, [5])).toEqual({ min: 5, max: 5 })
    expect(unionRange(null, [])).toBeNull()
  })
})

describe('a comparison reading', () => {
  it('gives the close and the change from the bar before', () => {
    expect(comparisonReading(110, 100)?.change).toBeCloseTo(10, 9)
    expect(comparisonReading(110, null)).toEqual({ close: 110, change: null })
    expect(comparisonReading(110, 0)).toEqual({ close: 110, change: null })
    expect(comparisonReading(null, 100)).toBeNull()
  })
})
