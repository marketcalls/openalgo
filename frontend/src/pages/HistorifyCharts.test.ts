import { describe, expect, it } from 'vitest'
import { historifyError } from '@/api/historify'
import { toPaneState } from './HistorifyCharts'

/**
 * The page's own pure helpers. Both of these exist because of a defect found
 * while reviewing this change rather than because the happy path needed them,
 * so they are pinned here.
 */

describe('toPaneState', () => {
  it('reads a well-formed stored pane unchanged', () => {
    expect(
      toPaneState({ symbol: 'RELIANCE', exchange: 'NSE', interval: '25m', chartType: 'line' })
    ).toEqual({ symbol: 'RELIANCE', exchange: 'NSE', interval: '25m', chartType: 'line' })
  })

  it('replaces a non-string field rather than passing it on', () => {
    // A number here reaches symbol.toUpperCase() in the API layer and throws
    // from a place that is not expecting one.
    expect(toPaneState({ symbol: 42, exchange: null, interval: {}, chartType: [] })).toEqual({
      symbol: '',
      exchange: 'NSE',
      interval: 'D',
      chartType: 'candlestick',
    })
  })

  it('survives junk, null and a missing object', () => {
    const blank = { symbol: '', exchange: 'NSE', interval: 'D', chartType: 'candlestick' }
    expect(toPaneState(null)).toEqual(blank)
    expect(toPaneState(undefined)).toEqual(blank)
    expect(toPaneState('nonsense')).toEqual(blank)
    expect(toPaneState({})).toEqual(blank)
  })

  it('refuses an absurdly long value', () => {
    expect(toPaneState({ symbol: 'A'.repeat(500) }).symbol).toBe('')
  })

  it('does not let a stored __proto__ key reach the prototype', () => {
    const parsed = JSON.parse('{"symbol":"X","__proto__":{"polluted":true}}')
    toPaneState(parsed)
    expect(({} as Record<string, unknown>).polluted).toBeUndefined()
  })
})

describe('historifyError', () => {
  it('never shows the server text, because these routes only send exceptions', () => {
    // Every read route answers a failure with str(e) and a 500. This is the
    // exact string a bad date produces: 48 characters, no exception class, no
    // status code. A filter based on shape passed it straight through.
    const leak = new Error("time data 'abc' does not match format '%Y-%m-%d'")
    expect(historifyError(leak, 'Could not read your local data.')).toBe(
      'Could not read your local data.'
    )
  })

  it('uses the fallback for every failure shape', () => {
    for (const error of [
      new Error('KeyError: symbol'),
      new Error('Request failed with status code 500'),
      new Error(''),
      'not an error',
      null,
      undefined,
    ]) {
      expect(historifyError(error, 'fallback')).toBe('fallback')
    }
  })
})
