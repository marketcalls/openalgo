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

import { hasIndicator } from 'openalgo-charts'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  calcOutputError,
  descriptorErrors,
  ensureCustomIndicators,
  loadCustomIndicators,
} from './customIndicators'

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
  it('waits for registration already in flight before another caller can use the indicator', async () => {
    let release!: () => void
    let started!: () => void
    const gate = new Promise<void>((resolve) => {
      release = resolve
    })
    const registering = new Promise<void>((resolve) => {
      started = resolve
    })
    vi.doMock('/custom-indicators/concurrent.js?v=1', () => ({
      default: async ({
        registerIndicator,
      }: {
        registerIndicator: (descriptor: unknown) => void
      }) => {
        started()
        await gate
        registerIndicator({
          id: 'concurrent-close',
          name: 'Concurrent Close',
          placement: 'onchart',
          inputs: [],
          plots: [{ key: 'close', type: 'line' }],
          calc: (bars: { close: number }[]) => ({ close: bars.map((bar) => bar.close) }),
        })
      },
    }))
    mockIndex([{ file: 'concurrent.js', mtime: 1 }])
    const first = loadCustomIndicators()
    await registering
    let returnedBeforeRegistration = false
    const second = loadCustomIndicators().then(() => {
      returnedBeforeRegistration = !hasIndicator('concurrent-close')
    })
    await new Promise((resolve) => setTimeout(resolve, 0))
    release()
    await Promise.all([first, second])

    expect(returnedBeforeRegistration).toBe(false)
    expect(hasIndicator('concurrent-close')).toBe(true)
  })

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

/**
 * A folder of hundreds of modules.
 *
 * Imported one after another, 500 files held every saved indicator back for
 * about three seconds on each reload. These pin the three things that fixed it:
 * the fetches overlap, the order that decides which module wins an id does not
 * change, and a restore imports only the files its layout uses.
 */
describe('loading at scale', () => {
  const MANIFEST = 'openalgo.customIndicators.manifest.v1'
  type Registrar = { registerIndicator: (descriptor: unknown) => void }

  function descriptor(id: string) {
    return {
      id,
      name: id,
      placement: 'onchart',
      inputs: [],
      plots: [{ key: 'close', type: 'line' }],
      calc: (bars: { close: number }[]) => ({ close: bars.map((bar) => bar.close) }),
    }
  }

  function moduleRegistering(...ids: string[]) {
    return {
      default: ({ registerIndicator }: Registrar) => {
        for (const id of ids) registerIndicator(descriptor(id))
      },
    }
  }

  beforeEach(() => {
    localStorage.clear()
  })

  it('fetches modules in parallel rather than one after another', async () => {
    let started = 0
    const release: (() => void)[] = []
    for (const name of ['par-a', 'par-b', 'par-c']) {
      vi.doMock(`/custom-indicators/${name}.js?v=1`, async () => {
        started += 1
        await new Promise<void>((resolve) => release.push(resolve))
        return moduleRegistering(`${name}-id`)
      })
    }
    mockIndex([
      { file: 'par-a.js', mtime: 1 },
      { file: 'par-b.js', mtime: 1 },
      { file: 'par-c.js', mtime: 1 },
    ])
    const load = loadCustomIndicators()
    // Sequential loading would start the second fetch only after the first
    // module arrived, so this would never reach three.
    await vi.waitFor(() => expect(started).toBe(3))
    for (const go of release) go()
    expect((await load).loaded).toEqual(['par-a.js', 'par-b.js', 'par-c.js'])
  })

  it('still registers in index order when later files arrive first', async () => {
    const order: string[] = []
    const arrive: Record<string, () => void> = {}
    for (const name of ['order-a', 'order-b', 'order-c']) {
      const gate = new Promise<void>((resolve) => {
        arrive[name] = resolve
      })
      vi.doMock(`/custom-indicators/${name}.js?v=1`, async () => {
        await gate
        return {
          default: ({ registerIndicator }: Registrar) => {
            order.push(name)
            registerIndicator(descriptor(`${name}-id`))
          },
        }
      })
    }
    mockIndex([
      { file: 'order-a.js', mtime: 1 },
      { file: 'order-b.js', mtime: 1 },
      { file: 'order-c.js', mtime: 1 },
    ])
    const load = loadCustomIndicators()
    await vi.waitFor(() => expect(Object.keys(arrive)).toHaveLength(3))
    arrive['order-c']()
    arrive['order-b']()
    await new Promise((resolve) => setTimeout(resolve, 0))
    arrive['order-a']()
    await load
    // Order is what decides which of two modules registering one id wins.
    expect(order).toEqual(['order-a', 'order-b', 'order-c'])
  })

  it('restores from the manifest without importing modules the layout does not use', async () => {
    const imported: string[] = []
    for (const name of ['lazy-used', 'lazy-other']) {
      vi.doMock(`/custom-indicators/${name}.js?v=3`, () => {
        imported.push(name)
        return moduleRegistering(`${name}-id`)
      })
    }
    localStorage.setItem(
      MANIFEST,
      JSON.stringify({ 'lazy-used.js@3': ['lazy-used-id'], 'lazy-other.js@3': ['lazy-other-id'] })
    )
    mockIndex([
      { file: 'lazy-other.js', mtime: 3 },
      { file: 'lazy-used.js', mtime: 3 },
    ])

    const res = await ensureCustomIndicators(['lazy-used-id'])

    expect(res.loaded).toEqual(['lazy-used.js'])
    expect(imported).toEqual(['lazy-used'])
    expect(hasIndicator('lazy-used-id')).toBe(true)
    expect(hasIndicator('lazy-other-id')).toBe(false)
  })

  it('imports nothing for a layout of built-in indicators', async () => {
    const { registeredIndicators } = await import('openalgo-charts')
    await import('openalgo-charts/indicators')
    const builtin = registeredIndicators()[0].id
    const imported: string[] = []
    vi.doMock('/custom-indicators/lazy-unused.js?v=4', () => {
      imported.push('lazy-unused')
      return moduleRegistering('lazy-unused-id')
    })
    localStorage.setItem(MANIFEST, JSON.stringify({ 'lazy-unused.js@4': ['lazy-unused-id'] }))
    mockIndex([{ file: 'lazy-unused.js', mtime: 4 }])

    await ensureCustomIndicators([builtin])

    expect(imported).toEqual([])
  })

  it('falls back to the full load when a saved indicator may be in a file it has not seen', async () => {
    // A new or edited file is not in the manifest yet, so it may be the one
    // that registers what the layout holds. Restoring without it would drop
    // that indicator from the chart.
    vi.doMock('/custom-indicators/lazy-new.js?v=5', () => moduleRegistering('lazy-new-id'))
    mockIndex([{ file: 'lazy-new.js', mtime: 5 }])

    await ensureCustomIndicators(['lazy-new-id'])

    expect(hasIndicator('lazy-new-id')).toBe(true)
  })

  it('remembers which ids each module registers, and forgets removed modules', async () => {
    localStorage.setItem(MANIFEST, JSON.stringify({ 'gone.js@1': ['gone-id'] }))
    vi.doMock('/custom-indicators/remembered.js?v=6', () =>
      moduleRegistering('remembered-a', 'remembered-b')
    )
    mockIndex([{ file: 'remembered.js', mtime: 6 }])

    await loadCustomIndicators()

    expect(JSON.parse(localStorage.getItem(MANIFEST) ?? '{}')).toEqual({
      'remembered.js@6': ['remembered-a', 'remembered-b'],
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
