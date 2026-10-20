/**
 * Drawings per instrument, at the storage level.
 *
 * Pinned against the installed library where the library has the same rule:
 * the key must be the one `instrumentDrawingsKey` gives, so the terminal and
 * any other host of the draw tier would file an instrument identically.
 */
import { instrumentDrawingsKey } from 'openalgo-charts/draw'
import { describe, expect, it } from 'vitest'
import {
  adoptUnscopedDrawings,
  DRAWINGS_SCOPED,
  drawingsKey,
  holdsDrawings,
  openingDrawings,
  savedInstrument,
  UNSCOPED_DRAWINGS,
} from './drawingScope'
import { createWorkspacePanePreferences } from './workspaceState'

function memory(seed: Record<string, string> = {}) {
  const values = new Map(Object.entries(seed))
  return {
    values,
    get: (key: string) => values.get(key) ?? null,
    set: (key: string, value: string) => {
      values.set(key, value)
    },
  }
}

const DOC = JSON.stringify({
  version: 2,
  drawings: [{ id: 'd1', tool: 'trend-line', paneIndex: 0, points: [], style: {}, zIndex: 0 }],
})

describe('the key an instrument is stored under', () => {
  it.each([
    { symbol: 'INFY', exchange: 'NSE' },
    { symbol: 'A:B', exchange: 'NSE' },
    { symbol: 'NIFTY 50', exchange: ' NSE_INDEX ' },
    { symbol: ' TCS ', exchange: 'NSE' },
    { symbol: 'X' },
    { symbol: 'ab', exchange: '' },
  ])('matches the library for %o', (instrument) => {
    expect(drawingsKey(instrument)).toBe(`draw:${instrumentDrawingsKey(instrument)}`)
  })

  it('is null without a symbol', () => {
    expect(drawingsKey(null)).toBeNull()
    expect(drawingsKey({ symbol: '  ', exchange: 'NSE' })).toBeNull()
    expect(instrumentDrawingsKey({ symbol: '  ', exchange: 'NSE' })).toBeNull()
  })

  it('reads the pane symbol entry, and nothing from a broken one', () => {
    expect(savedInstrument('{"symbol":"INFY","exchange":"NSE"}')).toEqual({
      symbol: 'INFY',
      exchange: 'NSE',
    })
    expect(savedInstrument('not json')).toBeNull()
    expect(savedInstrument('{"exchange":"NSE"}')).toBeNull()
    expect(savedInstrument(null)).toBeNull()
  })
})

describe('the one-time adoption of a pane-level save', () => {
  it('files it under the instrument byte for byte and leaves the old entry alone', () => {
    const store = memory({ [UNSCOPED_DRAWINGS]: DOC })
    expect(adoptUnscopedDrawings(store, 'draw:NSE:INFY')).toBe(true)
    expect(store.get('draw:NSE:INFY')).toBe(DOC)
    // An older build opened on this profile still finds its drawings.
    expect(store.get(UNSCOPED_DRAWINGS)).toBe(DOC)
    expect(store.get(DRAWINGS_SCOPED)).toBe('1')
  })

  it('happens once: a second instrument never gets a copy', () => {
    const store = memory({ [UNSCOPED_DRAWINGS]: DOC })
    adoptUnscopedDrawings(store, 'draw:NSE:INFY')
    expect(adoptUnscopedDrawings(store, 'draw:NSE:TCS')).toBe(false)
    expect(store.get('draw:NSE:TCS')).toBeNull()
    expect(openingDrawings(store, 'draw:NSE:TCS')).toBeNull()
  })

  it('keeps what an instrument already has, an emptied entry included', () => {
    const emptied = '{"version":2,"drawings":[]}'
    const store = memory({ [UNSCOPED_DRAWINGS]: DOC, 'draw:NSE:INFY': emptied })
    expect(adoptUnscopedDrawings(store, 'draw:NSE:INFY')).toBe(false)
    expect(store.get('draw:NSE:INFY')).toBe(emptied)
  })

  it('writes nothing for an empty or unreadable pane save', () => {
    for (const raw of ['{"version":2,"drawings":[]}', '[]', 'garbage']) {
      const store = memory({ [UNSCOPED_DRAWINGS]: raw })
      expect(adoptUnscopedDrawings(store, 'draw:NSE:INFY')).toBe(false)
      expect(store.get('draw:NSE:INFY')).toBeNull()
    }
  })

  it('holds the pane save while the pane has no symbol, and not after it is filed', () => {
    const store = memory({ [UNSCOPED_DRAWINGS]: DOC })
    expect(openingDrawings(store, null)).toBe(DOC)
    store.set(DRAWINGS_SCOPED, '1')
    expect(openingDrawings(store, null)).toBeNull()
  })

  it('reads both stored shapes as drawings', () => {
    expect(holdsDrawings(DOC)).toBe(true)
    expect(holdsDrawings('[{"id":"a"}]')).toBe(true)
    expect(holdsDrawings('{"version":2,"drawings":[]}')).toBe(false)
    expect(holdsDrawings(null)).toBe(false)
  })

  it('migrates a saved workspace pane the moment it opens', () => {
    // A workspace pane's storage is built in memory from the workspace itself,
    // with its drawings under the pane-level key, as every earlier build saved.
    const prefs = createWorkspacePanePreferences(
      {
        id: 'p0',
        symbol: 'INFY',
        exchange: 'NSE',
        interval: '5m',
        chartType: 'candlestick',
        chart: { version: 1, drawings: JSON.parse(DOC) },
        settings: {},
        volume: true,
        magnet: 'off',
        stay: false,
        comparisons: [],
        comparisonMode: 'price',
      },
      'ws-p0'
    )
    const store = {
      get: (key: string) => prefs.getItem(`ws-p0-${key}`),
      set: (key: string, value: string) => prefs.setItem(`ws-p0-${key}`, value),
    }
    const key = drawingsKey(savedInstrument(store.get('symbol')))
    expect(key).toBe('draw:NSE:INFY')
    expect(JSON.parse(openingDrawings(store, key) ?? 'null')).toEqual(JSON.parse(DOC))
  })
})
