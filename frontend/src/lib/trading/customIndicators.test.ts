/**
 * The custom indicator loader.
 *
 * Everything here is about isolation. A user's indicator file is code the app
 * has never seen, fetched from disk at runtime, and the one thing it must never
 * do is take the other 91 indicators down with it. So the cases that matter are
 * the failures: no route, no session, a malformed index, and a module that
 * cannot be imported. None of them may throw, and none may leave the picker
 * empty.
 */

import { afterEach, describe, expect, it, vi } from 'vitest'

import { loadCustomIndicators } from './customIndicators'

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
      { file: 'broken.js', mtime: 1 },
      { file: 'alsobroken.js', mtime: 2 },
    ])
    const res = await loadCustomIndicators()
    expect(res.loaded).toEqual([])
    expect(res.errors.map((e) => e.file)).toEqual(['broken.js', 'alsobroken.js'])
    expect(res.errors[0].message).toBeTruthy()
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
