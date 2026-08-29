import { beforeEach, describe, expect, it, vi } from 'vitest'
import { needsPreviousClose, previousClose } from './previousClose'

const post = vi.fn()
vi.mock('@/api/client', () => ({
  apiClient: { post: (...a: unknown[]) => post(...a) },
}))

const DAY = 86400

/** Epoch seconds for midnight, `daysAgo` days before the mocked clock. */
function stamp(daysAgo: number): number {
  const d = new Date()
  d.setHours(0, 0, 0, 0)
  return Math.floor(d.getTime() / 1000) - daysAgo * DAY
}

/** Two daily bars: the session in progress, and the one before it. */
function history(prev: number, current: number) {
  return {
    data: {
      status: 'success',
      data: [
        { close: prev, timestamp: stamp(1) },
        { close: current, timestamp: stamp(0) },
      ],
    },
  }
}

/**
 * A broker that does not publish today's daily bar intraday, so the last bar
 * IS the previous close and taking the one before it would measure against a
 * two-day-old figure for the whole session.
 */
function historyWithoutToday(dayBefore: number, prev: number) {
  return {
    data: {
      status: 'success',
      data: [
        { close: dayBefore, timestamp: stamp(2) },
        { close: prev, timestamp: stamp(1) },
      ],
    },
  }
}

const STORE_KEY = 'oa-trading-prev-close'

describe('needsPreviousClose', () => {
  it('rejects a missing or zero value', () => {
    expect(needsPreviousClose(undefined, 1287)).toBe(true)
    expect(needsPreviousClose(0, 1287)).toBe(true)
  })

  it('rejects a value equal to the last traded price', () => {
    // The signature of a broker reporting the CURRENT session's close, which is
    // what produced a confident +0.00% on every row.
    expect(needsPreviousClose(1287, 1287)).toBe(true)
  })

  it('accepts a real previous close', () => {
    expect(needsPreviousClose(1282.2, 1287)).toBe(false)
  })
})

describe('previousClose', () => {
  beforeEach(() => {
    post.mockReset()
    localStorage.clear()
    vi.setSystemTime(new Date('2026-08-30T10:00:00'))
    // The day-stamped cache is module state, so every test needs its own
    // instance or the first one to run leaves the rest asserting nothing. The
    // stale-day test in particular could not reach the branch it was named for.
    vi.resetModules()
  })

  /** A fresh copy of the module, with its cache and day stamp unset. */
  async function load() {
    return (await import('./previousClose')).previousClose
  }

  it('reads the second-to-last bar when the market is shut', async () => {
    // The last bar is the most recent completed session, which is the one the
    // current price came from, so the previous close is the bar before it.
    post.mockResolvedValue(history(1282.2, 1287))
    const resolve = await load()

    await expect(resolve('k', 'RELIANCE', 'NSE', false)).resolves.toBe(1282.2)
    expect(post).toHaveBeenCalledWith(
      '/history',
      expect.objectContaining({ symbol: 'RELIANCE', exchange: 'NSE', interval: 'D' })
    )
  })

  it('reads the second-to-last bar when the in-progress bar is published', async () => {
    // Market open and the last bar is today: that bar is the session in
    // progress, so the previous close is again the one before it. Comparing
    // the bar's close to the live price got this wrong, because a daily bar
    // and a tick are snapshots moments apart and never exactly equal.
    post.mockResolvedValue(history(1282.2, 1287))
    const resolve = await load()

    await expect(resolve('k', 'RELIANCE', 'NSE', true)).resolves.toBe(1282.2)
  })

  it('reads the LAST bar when the broker has not published today yet', async () => {
    // Market open but the last bar is yesterday, so that bar IS the previous
    // close. Taking the one before it would measure against a two-day-old
    // figure for the whole session.
    post.mockResolvedValue(historyWithoutToday(1250, 1282.2))
    const resolve = await load()

    await expect(resolve('k', 'RELIANCE', 'NSE', true)).resolves.toBe(1282.2)
  })

  it('reads the second-to-last bar on a non-trading day', async () => {
    // The Sunday case: the last bar is Friday's, the market is shut, and the
    // price IS Friday's close. A date-based rule answered "not today" here and
    // picked that bar, so every row read +0.00% against its own price.
    post.mockResolvedValue(historyWithoutToday(1282.2, 1287))
    const resolve = await load()

    await expect(resolve('k', 'RELIANCE', 'NSE', false)).resolves.toBe(1282.2)
  })
  it('asks once for an instrument, however many rows want it', async () => {
    post.mockResolvedValue(history(1282.2, 1287))
    const resolve = await load()

    const results = await Promise.all([
      resolve('k', 'TCS', 'NSE', false),
      resolve('k', 'TCS', 'NSE', false),
      resolve('k', 'TCS', 'NSE', false),
    ])

    expect(results).toEqual([1282.2, 1282.2, 1282.2])
    expect(post).toHaveBeenCalledTimes(1)
  })

  it('asks once for a symbol history cannot answer, not once per render', async () => {
    // The caller re-runs on every tick. Leaving a failure uncached meant a
    // fresh POST per symbol per tick, each preceded by a CSRF fetch.
    post.mockResolvedValue({ data: { status: 'success', data: [] } })
    const resolve = await load()

    for (let i = 0; i < 5; i++) {
      await expect(resolve('k', 'ILLIQUID', 'NSE')).resolves.toBeNull()
    }
    expect(post).toHaveBeenCalledTimes(1)
  })

  it('does not persist a failure, so it is retried on the next page load', async () => {
    post.mockResolvedValue({ data: { status: 'success', data: [] } })
    const resolve = await load()
    await resolve('k', 'ILLIQUID', 'NSE')

    const stored = JSON.parse(localStorage.getItem(STORE_KEY) || '{}')
    expect(stored.values?.['NSE:ILLIQUID']).toBeUndefined()
  })

  it('costs nothing on a reload, because the day is already in the store', async () => {
    post.mockResolvedValue(history(1282.2, 1287))
    const first = await load()
    await first('k', 'INFY', 'NSE', false)
    expect(post).toHaveBeenCalledTimes(1)

    const stored = JSON.parse(localStorage.getItem(STORE_KEY) || '{}')
    expect(stored.values['NSE:INFY']).toBe(1282.2)

    // What a page load looks like: a fresh module against the same store.
    vi.resetModules()
    post.mockClear()
    const second = await load()
    await expect(second('k', 'INFY', 'NSE', false)).resolves.toBe(1282.2)
    expect(post).not.toHaveBeenCalled()
  })

  it('discards a store from a previous trading day rather than trusting it', async () => {
    // Yesterday's close would produce a wrong change for the whole session.
    localStorage.setItem(
      STORE_KEY,
      JSON.stringify({ day: 'Fri Aug 28 2026', values: { 'NSE:SBIN': 999 } })
    )
    post.mockResolvedValue(history(1282.2, 1287))
    const resolve = await load()

    await expect(resolve('k', 'SBIN', 'NSE', false)).resolves.toBe(1282.2)
    expect(post).toHaveBeenCalledTimes(1)
  })

  it('uses a store stamped with today', async () => {
    localStorage.setItem(
      STORE_KEY,
      JSON.stringify({ day: new Date().toDateString(), values: { 'NSE:SBIN': 999 } })
    )
    const resolve = await load()

    await expect(resolve('k', 'SBIN', 'NSE')).resolves.toBe(999)
    expect(post).not.toHaveBeenCalled()
  })

  it('ignores a stored value that is not a usable price', async () => {
    localStorage.setItem(
      STORE_KEY,
      JSON.stringify({
        day: new Date().toDateString(),
        values: { 'NSE:A': 0, 'NSE:B': -5, 'NSE:C': 'nonsense', 'NSE:D': null },
      })
    )
    post.mockResolvedValue(history(1282.2, 1287))
    const resolve = await load()

    for (const sym of ['A', 'B', 'C', 'D']) {
      await expect(resolve('k', sym, 'NSE', false)).resolves.toBe(1282.2)
    }
    expect(post).toHaveBeenCalledTimes(4)
  })

  it('returns null rather than throwing when history is unavailable', async () => {
    post.mockRejectedValue(new Error('network down'))
    const resolve = await load()
    await expect(resolve('k', 'BADSYM', 'NSE')).resolves.toBeNull()
  })

  it('treats a 200 carrying status error as no answer', async () => {
    post.mockResolvedValue({ data: { status: 'error', message: 'no data' } })
    const resolve = await load()
    await expect(resolve('k', 'ERRSYM', 'NSE')).resolves.toBeNull()
  })

  it('rejects a bar whose close is not a usable price', async () => {
    post.mockResolvedValue({
      data: {
        status: 'success',
        data: [
          { close: 0, timestamp: stamp(1) },
          { close: 1287, timestamp: stamp(0) },
        ],
      },
    })
    const resolve = await load()
    await expect(resolve('k', 'ZEROSYM', 'NSE', false)).resolves.toBeNull()
  })

  it('asks for a window wide enough to clear a long weekend', async () => {
    post.mockResolvedValue(history(1282.2, 1287))
    const resolve = await load()
    await resolve('k', 'RELIANCE', 'NSE', false)

    const body = post.mock.calls[0][1] as { start_date: string; end_date: string }
    expect(body.end_date).toBe('2026-08-30')
    expect(body.start_date).toBe('2026-08-10')
  })
})
