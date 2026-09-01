/**
 * The custom indicator loader.
 *
 * Two jobs, both tested here. It must isolate: a user's indicator file is code
 * the app has never seen, fetched from disk at runtime, and it must never take
 * the other 102 indicators down with it. And it must validate: the chart runtime
 * swallows a short column or a mismatched plot key, drawing nothing and raising
 * nothing, so a trader with no build step needs the loader itself to say what is
 * wrong.
 */

import { afterEach, describe, expect, it, vi } from 'vitest'

import { calcOutputError, descriptorErrors, loadCustomIndicators } from './customIndicators'

function mockIndex(body: unknown, ok = true) {
  const fetchMock = vi.fn(async () => ({ ok, json: async () => body }) as unknown as Response)
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('loadCustomIndicators', () => {
  it('loads nothing when the index route is not there', async () => {
    mockIndex(null, false)
    expect(await loadCustomIndicators()).toEqual({ loaded: [], errors: [] })
  })

  it('stays quiet when the fetch itself throws', async () => {
    // Logged out, offline, or the blueprint is not registered. Having no custom
    // indicators is a normal state, not something to put in front of anyone.
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new Error('network down')
      })
    )
    expect(await loadCustomIndicators()).toEqual({ loaded: [], errors: [] })
  })

  it('ignores an index that is not a list of modules', async () => {
    mockIndex({ file: 'not-an-array.js' })
    expect(await loadCustomIndicators()).toEqual({ loaded: [], errors: [] })
  })

  it('does not touch the chart library for an empty folder', async () => {
    const fetchMock = mockIndex([])
    expect(await loadCustomIndicators()).toEqual({ loaded: [], errors: [] })
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('reports a module it cannot import instead of throwing', async () => {
    // Nothing resolves these URLs here, which is the same shape of failure as a
    // syntax error in a user file: the import rejects. Both modules have to be
    // attempted, so one bad file does not hide the next.
    mockIndex([
      { file: 'broken-a.js', mtime: 1 },
      { file: 'broken-b.js', mtime: 1 },
    ])
    const res = await loadCustomIndicators()
    expect(res.loaded).toEqual([])
    expect(res.errors.map((e) => e.file)).toEqual(['broken-a.js', 'broken-b.js'])
    expect(res.errors[0].message).toBeTruthy()
  })

  it('does not re-report a module it has already seen', async () => {
    // The catalogue re-reads the index on every picker open so a newly added
    // file appears without a page reload. That would repeat every warning on
    // every open if unchanged modules were not skipped.
    mockIndex([{ file: 'seen-once.js', mtime: 7 }])
    const first = await loadCustomIndicators()
    expect(first.errors).toHaveLength(1)

    const second = await loadCustomIndicators()
    expect(second.errors).toHaveLength(0)
    expect(second.loaded).toHaveLength(0)
  })

  it('treats an edited file as new, so a fix is picked up', async () => {
    mockIndex([{ file: 'edited.js', mtime: 1 }])
    await loadCustomIndicators()
    // Same filename, new mtime: a different cache-busted URL and a fresh import.
    mockIndex([{ file: 'edited.js', mtime: 2 }])
    const res = await loadCustomIndicators()
    expect(res.errors.map((e) => e.file)).toEqual(['edited.js'])
  })

  it('asks the server for the index with the session cookie', async () => {
    const fetchMock = mockIndex([])
    await loadCustomIndicators()
    // The Accept header is what turns a logged-out request into a 401 instead
    // of a 302 that fetch follows into the login page's HTML.
    expect(fetchMock).toHaveBeenCalledWith('/custom-indicators/index.json', {
      credentials: 'same-origin',
      headers: { Accept: 'application/json' },
    })
  })
})

describe('descriptorErrors', () => {
  const good = {
    id: 'my-thing',
    name: 'My Thing',
    placement: 'pane',
    inputs: [{ key: 'length', type: 'number', label: 'Length', default: 20 }],
    plots: [{ key: 'x', type: 'line', title: 'X' }],
    calc: () => ({}),
  }

  it('accepts a well-formed descriptor', () => {
    expect(descriptorErrors(good)).toEqual([])
  })

  it.each([
    ['a missing id', { id: '' }, /id must be a non-empty string/],
    ['an id with whitespace', { id: 'my thing' }, /contains whitespace/],
    ['a missing name', { name: '' }, /name is required/],
    ['a bad placement', { placement: 'overlay' }, /placement must be/],
    ['a non-function calc', { calc: 'nope' }, /calc must be a function/],
    ['no plots', { plots: [] }, /plots must be a non-empty array/],
    [
      'duplicate plot keys',
      {
        plots: [
          { key: 'x', type: 'line' },
          { key: 'x', type: 'line' },
        ],
      },
      /duplicate plot key/,
    ],
    [
      'an unsupported input type',
      { inputs: [{ key: 'a', type: 'slider', default: 1 }] },
      /unsupported type/,
    ],
    ['an input with no default', { inputs: [{ key: 'a', type: 'number' }] }, /has no default/],
    ['inputs that are not an array', { inputs: null }, /inputs must be an array/],
  ])('rejects %s', (_label, patch, pattern) => {
    const errors = descriptorErrors({ ...good, ...patch })
    expect(errors.join('; ')).toMatch(pattern)
  })
})

describe('calcOutputError', () => {
  const plots = [{ key: 'a' }, { key: 'b' }]

  it('accepts columns that line up with the bars', () => {
    expect(calcOutputError({ a: [1, 2, 3], b: [null, 2, 3] }, 3, plots)).toBeNull()
  })

  it('catches a column that is one short', () => {
    // The exact silent failure: the runtime reads undefined past the end and
    // draws a gap, so the plot just stops partway with no error anywhere.
    expect(calcOutputError({ a: [1, 2], b: [1, 2, 3] }, 3, plots)).toMatch(
      /column 'a' returned 2 values for 3 bars/
    )
  })

  it('catches a plot key that calc never filled', () => {
    expect(calcOutputError({ a: [1, 2, 3] }, 3, plots)).toMatch(/no column 'b' for plot 'b'/)
  })

  it('catches a column that is not an array', () => {
    expect(calcOutputError({ a: 5, b: [1, 2, 3] }, 3, plots)).toMatch(/column 'a' is a number/)
  })

  it('checks all four columns of a candle plot', () => {
    // A plot fed by an ohlc group is not keyed by the plot itself, so the four
    // named columns are what must exist and line up.
    const candle = [{ key: 'c', ohlc: { open: 'o', high: 'h', low: 'l', close: 'cl' } }]
    const good = { o: [1, 2, 3], h: [1, 2, 3], l: [1, 2, 3], cl: [1, 2, 3] }
    expect(calcOutputError(good, 3, candle)).toBeNull()
    expect(calcOutputError({ ...good, h: [1, 2] }, 3, candle)).toMatch(
      /column 'h' returned 2 values/
    )
    const { l, ...missingLow } = good
    expect(calcOutputError(missingLow, 3, candle)).toMatch(/no column 'l'/)
  })

  it('catches calc returning something that is not an object', () => {
    expect(calcOutputError([1, 2, 3], 3, plots)).toMatch(/must return an object/)
    expect(calcOutputError(null, 3, plots)).toMatch(/must return an object/)
  })
})
