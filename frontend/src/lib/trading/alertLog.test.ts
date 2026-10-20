/**
 * Reporting a firing, and reading the history back.
 *
 * The rule worth pinning is that none of this may ever become the trader's
 * problem. By the time any of it runs the alert has already fired and they have
 * already been told, on the channels they chose. A log write that fails is a
 * missing row; it is not a second message contradicting the one they just read,
 * and it is certainly not an exception thrown out of the alert handler.
 *
 * Clearing is the exception, because that one is a button somebody pressed.
 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { clearLog, fetchLog, reportFire } from './alertLog'

const FIRE = {
  alertId: 'a1',
  title: 'RELIANCE crossing 1264.7',
  kind: 'price',
  condition: 'crossesAbove',
  symbol: 'RELIANCE',
  exchange: 'NSE',
  interval: '1h',
  price: 1264.7,
  message: 'crossed 1264.70',
  delivered: ['sound', 'telegram'],
}

const ROW = {
  id: 7,
  alertId: 'a1',
  title: 'RELIANCE crossing 1264.7',
  kind: 'price',
  condition: 'crossesAbove',
  symbol: 'RELIANCE',
  exchange: 'NSE',
  interval: '1h',
  price: 1264.7,
  message: 'crossed 1264.70',
  delivered: ['telegram'],
  firedAt: 1_758_441_600,
}

/** A fetch that answers with one body, recording what it was asked. */
function fetchWith(answer: { ok?: boolean; body?: unknown; throws?: boolean }) {
  const calls: { url: string; method: string; body: unknown }[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (answer.throws) throw new Error('offline')
      calls.push({
        url,
        method: init?.method ?? 'GET',
        body: init?.body ? JSON.parse(String(init.body)) : undefined,
      })
      return {
        ok: answer.ok ?? true,
        json: async () => answer.body ?? {},
      } as Response
    })
  )
  return calls
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('reporting a firing', () => {
  it('posts it to the log with everything the row needs', async () => {
    const calls = fetchWith({ body: { status: 'success', fire: ROW } })
    await reportFire(FIRE)

    expect(calls).toHaveLength(1)
    expect(calls[0]?.url).toBe('/alerts/fired')
    expect(calls[0]?.method).toBe('POST')
    expect(calls[0]?.body).toMatchObject({
      alertId: 'a1',
      symbol: 'RELIANCE',
      exchange: 'NSE',
      interval: '1h',
      delivered: ['sound', 'telegram'],
    })
  })

  it('returns the stored row so the caller need not guess its id', async () => {
    fetchWith({ body: { status: 'success', fire: ROW } })
    expect(await reportFire(FIRE)).toMatchObject({ id: 7, delivered: ['telegram'] })
  })

  it('reports nothing rather than throwing when the server refuses', async () => {
    // The alert has already fired and the trader has already been told.
    fetchWith({ ok: false })
    await expect(reportFire(FIRE)).resolves.toBeNull()
  })

  it('reports nothing rather than throwing when the network is gone', async () => {
    fetchWith({ throws: true })
    await expect(reportFire(FIRE)).resolves.toBeNull()
  })

  it('believes the status rather than the payload beside it', async () => {
    // A body that declares failure and carries a row anyway is not a row. The
    // status is the answer; taking the payload because it happens to be there
    // is how a caller ends up holding a record the server did not keep.
    fetchWith({ body: { status: 'error', message: 'nope', fire: ROW } })
    expect(await reportFire(FIRE)).toBeNull()
  })
})

describe('reading the history back', () => {
  it('returns the rows the server sent', async () => {
    fetchWith({ body: { status: 'success', fires: [ROW] } })
    expect(await fetchLog()).toEqual([ROW])
  })

  it('reads an unreachable server as an empty history, not an error', async () => {
    // An empty Log tab is a true statement about what this page can show.
    fetchWith({ throws: true })
    await expect(fetchLog()).resolves.toEqual([])
  })

  it('reads a malformed answer as empty rather than handing it on', async () => {
    fetchWith({ body: { status: 'success', fires: 'lots' } })
    expect(await fetchLog()).toEqual([])
  })
})

describe('clearing the log', () => {
  it('asks the server to delete it', async () => {
    const calls = fetchWith({ body: { status: 'success', removed: 3 } })
    expect(await clearLog()).toBe(true)
    expect(calls[0]?.url).toBe('/alerts/log')
    expect(calls[0]?.method).toBe('DELETE')
  })

  it('says so when it did not work', async () => {
    // Unlike a report, this is a button somebody pressed: silence would have
    // them press it again and conclude the platform is ignoring them.
    fetchWith({ ok: false })
    expect(await clearLog()).toBe(false)
  })

  it('says so when the network is gone', async () => {
    fetchWith({ throws: true })
    expect(await clearLog()).toBe(false)
  })
})
