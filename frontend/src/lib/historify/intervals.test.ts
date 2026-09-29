import { describe, expect, it } from 'vitest'
import {
  availableIntervals,
  CUSTOM_UNITS,
  composeInterval,
  isIntervalAvailable,
  isIntradayInterval,
  parseInterval,
  STANDARD_INTERVALS,
  storedSources,
  unavailableReason,
} from './intervals'

/**
 * These tests are pinned to the server grammar in
 * `database/historify_db.py:659-734`, not to what feels reasonable. Two of them
 * exist because the page this replaces got them wrong and nothing caught it:
 * the store answers an unknown token with an empty 200, so a broken timeframe
 * looks exactly like a symbol with no data.
 */

describe('parseInterval', () => {
  it('reads the bare daily token from storage and aggregates the rest from it', () => {
    expect(parseInterval('D')).toEqual({ unit: 'D', value: 1, source: 'D' })
    expect(parseInterval('W')).toEqual({ unit: 'W', value: 1, source: 'D' })
    expect(parseInterval('M')).toEqual({ unit: 'M', value: 1, source: 'D' })
    expect(parseInterval('Q')).toEqual({ unit: 'Q', value: 1, source: 'D' })
    expect(parseInterval('Y')).toEqual({ unit: 'Y', value: 1, source: 'D' })
  })

  it('builds every intraday token from stored 1m', () => {
    expect(parseInterval('1m')).toEqual({ unit: 'm', value: 1, source: '1m' })
    expect(parseInterval('25m')).toEqual({ unit: 'm', value: 25, source: '1m' })
    expect(parseInterval('2h')).toEqual({ unit: 'h', value: 2, source: '1m' })
  })

  it('accepts arbitrary multiples, not only the six the server advertises', () => {
    // /historify/api/historify-intervals lists 1m, 5m, 15m, 30m, 1h, D. The
    // data route serves far more than that.
    for (const token of ['2m', '4m', '45m', '75m', '240m', '3h', '2W', '3M', '2Q', '2Y']) {
      expect(parseInterval(token), token).not.toBeNull()
    }
  })

  it('rejects <n>D, which parses on the server and then returns nothing', () => {
    // It types as "daily", which is neither the intraday branch nor the
    // daily-aggregated one, so the query reads a stored row named "1D" that is
    // never written. D is the only daily token.
    expect(parseInterval('1D')).toBeNull()
    expect(parseInterval('2D')).toBeNull()
    expect(parseInterval('3D')).toBeNull()
  })

  it('rejects seconds, which the store has no rows for', () => {
    expect(parseInterval('1s')).toBeNull()
    expect(parseInterval('30s')).toBeNull()
    expect(parseInterval('45s')).toBeNull()
  })

  it('honours case, because lowercase m is minutes and uppercase M is months', () => {
    expect(parseInterval('5m')?.source).toBe('1m')
    expect(parseInterval('5M')?.source).toBe('D')
    expect(parseInterval('d')).toBeNull()
    expect(parseInterval('w')).toBeNull()
    expect(parseInterval('1H')).toBeNull()
  })

  it('rejects junk, zero and empty input', () => {
    expect(parseInterval('')).toBeNull()
    expect(parseInterval('   ')).toBeNull()
    expect(parseInterval('0m')).toBeNull()
    expect(parseInterval('MO')).toBeNull()
    expect(parseInterval('abc')).toBeNull()
    expect(parseInterval('5')).toBeNull()
    expect(parseInterval('m')).toBeNull()
  })
})

describe('composeInterval', () => {
  it('emits M for months, never MO', () => {
    // The replaced page's Select wrote "MO", which fails ^(\d+)([mhDWMQY])$
    // outright, so its custom monthly option never drew a candle.
    expect(composeInterval(1, 'M')).toBe('M')
    expect(composeInterval(3, 'M')).toBe('3M')
    expect(composeInterval(1, 'M')).not.toBe('MO')
    expect(composeInterval(25, 'M')).not.toBe('25MO')
  })

  it('collapses a single week, month, quarter or year to the bare letter', () => {
    expect(composeInterval(1, 'W')).toBe('W')
    expect(composeInterval(1, 'Q')).toBe('Q')
    expect(composeInterval(1, 'Y')).toBe('Y')
    expect(composeInterval(2, 'W')).toBe('2W')
  })

  it('keeps the number on minutes and hours, including one', () => {
    expect(composeInterval(1, 'm')).toBe('1m')
    expect(composeInterval(25, 'm')).toBe('25m')
    expect(composeInterval(1, 'h')).toBe('1h')
    expect(composeInterval(4, 'h')).toBe('4h')
  })

  it('accepts the string a number input actually hands back', () => {
    expect(composeInterval('25', 'm')).toBe('25m')
    expect(composeInterval('1', 'W')).toBe('W')
  })

  it('refuses a pair it cannot express rather than emitting a silent blank', () => {
    expect(composeInterval(0, 'm')).toBeNull()
    expect(composeInterval(-5, 'm')).toBeNull()
    expect(composeInterval('', 'm')).toBeNull()
    expect(composeInterval('abc', 'm')).toBeNull()
  })

  it('composes only tokens the parser accepts', () => {
    for (const unit of CUSTOM_UNITS) {
      for (const value of [1, 2, 25]) {
        const token = composeInterval(value, unit.value)
        expect(token, `${value}${unit.value}`).not.toBeNull()
        expect(parseInterval(token as string), token as string).not.toBeNull()
      }
    }
  })

  it('offers no day unit, because no multi-day token works', () => {
    expect(CUSTOM_UNITS.some((u) => (u.value as string) === 'D')).toBe(false)
  })
})

describe('STANDARD_INTERVALS', () => {
  it('is entirely parseable', () => {
    for (const token of STANDARD_INTERVALS) {
      expect(parseInterval(token), token).not.toBeNull()
    }
  })

  it('spells the daily timeframe D rather than 1D', () => {
    expect(STANDARD_INTERVALS).toContain('D')
    expect(STANDARD_INTERVALS).not.toContain('1D')
  })
})

describe('isIntradayInterval', () => {
  it('separates minute and hour tokens from daily and above', () => {
    expect(isIntradayInterval('1m')).toBe(true)
    expect(isIntradayInterval('25m')).toBe(true)
    expect(isIntradayInterval('4h')).toBe(true)
    expect(isIntradayInterval('D')).toBe(false)
    expect(isIntradayInterval('W')).toBe(false)
    expect(isIntradayInterval('M')).toBe(false)
  })

  it('is false for a token that would return nothing', () => {
    expect(isIntradayInterval('1D')).toBe(false)
    expect(isIntradayInterval('MO')).toBe(false)
  })
})

describe('availability against what has been downloaded', () => {
  it('keeps only 1m and D from a catalog, since nothing else is stored', () => {
    expect(storedSources(['1m', 'D', '5m', 'W'])).toEqual(new Set(['1m', 'D']))
    expect(storedSources([])).toEqual(new Set())
  })

  it('charts nothing above daily from a symbol downloaded at 1m only', () => {
    // The aggregation for W/M/Q/Y reads stored D rows exclusively, so minute
    // data however deep produces an empty weekly chart.
    const stored = storedSources(['1m'])
    expect(isIntervalAvailable('25m', stored)).toBe(true)
    expect(isIntervalAvailable('4h', stored)).toBe(true)
    expect(isIntervalAvailable('D', stored)).toBe(false)
    expect(isIntervalAvailable('W', stored)).toBe(false)
    expect(availableIntervals(stored)).toEqual([
      '1m',
      '3m',
      '5m',
      '10m',
      '15m',
      '30m',
      '1h',
      '2h',
      '4h',
    ])
  })

  it('charts nothing intraday from a symbol downloaded at D only', () => {
    const stored = storedSources(['D'])
    expect(isIntervalAvailable('5m', stored)).toBe(false)
    expect(availableIntervals(stored)).toEqual(['D', 'W', 'M', 'Q', 'Y'])
  })

  it('offers everything when both are stored', () => {
    expect(availableIntervals(storedSources(['1m', 'D']))).toEqual([...STANDARD_INTERVALS])
  })
})

describe('unavailableReason', () => {
  it('says nothing when the timeframe works', () => {
    expect(unavailableReason('5m', storedSources(['1m']))).toBeNull()
    expect(unavailableReason('W', storedSources(['D']))).toBeNull()
  })

  it('names the missing download and the next action, not the mechanism', () => {
    const weekly = unavailableReason('W', storedSources(['1m']))
    expect(weekly).toContain('daily data')
    expect(weekly).toContain('Download')
    expect(weekly).not.toMatch(/\b(200|404|500|aggregat|DuckDB|endpoint|API)\b/i)

    const intraday = unavailableReason('5m', storedSources(['D']))
    expect(intraday).toContain('1 minute data')
    expect(intraday).toContain('Download')
  })

  it('explains an unusable token rather than reporting silence', () => {
    const reason = unavailableReason('1D', storedSources(['1m', 'D']))
    expect(reason).toBeTruthy()
    expect(reason).toContain('1D')
  })
})
