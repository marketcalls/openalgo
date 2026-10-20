/**
 * The instrument facts the chart hands the OpenScript engine.
 *
 * Four behaviours, each of which a chart depends on without being able to see:
 * one request per instrument however many studies ask at once; an answer kept
 * rather than fetched on every repaint; a failure that comes back as an absence
 * and is tried again later rather than thrown into a chart callback or retried
 * on every frame; and a way for code that cannot await to hear that the facts
 * have landed. The last group holds the record to what the engine will accept,
 * because a malformed session is refused at load and takes the study with it.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  cachedFacts,
  cachedToday,
  clearInstrumentFacts,
  factsFor,
  RETRY_AFTER_MS,
  subscribeFacts,
} from './instrumentFacts'

const SESSION = { start: '09:15', end: '15:30', days: [1, 2, 3, 4, 5] }

function answer(overrides: Record<string, unknown> = {}, today: unknown = undefined) {
  return {
    status: 'success',
    symbol: 'BHEL',
    contractFound: true,
    instrument: {
      exchange: 'NSE',
      timezone: 'Asia/Kolkata',
      tickSize: 0.05,
      lotSize: 1,
      instrumentType: 'equity',
      hasVolume: true,
      hasOpenInterest: false,
      session: SESSION,
      ...overrides,
    },
    today: today ?? {
      date: '2026-09-23',
      open: true,
      isSpecial: false,
      session: { start: '09:15', end: '15:30', days: [3] },
    },
  }
}

function respondWith(...bodies: unknown[]) {
  const queue = [...bodies]
  const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) => {
    const next = queue.length > 1 ? queue.shift() : queue[0]
    if (next instanceof Error) throw next
    if (next === 'down') return { ok: false, json: async () => ({}) } as unknown as Response
    return { ok: true, json: async () => next } as unknown as Response
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

beforeEach(() => {
  vi.useFakeTimers()
  // 11:00 in Mumbai on 2026-09-23, a Wednesday.
  vi.setSystemTime(new Date('2026-09-23T05:30:00Z'))
  clearInstrumentFacts()
})

afterEach(() => {
  clearInstrumentFacts()
  vi.useRealTimers()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('asking for an instrument', () => {
  it('asks the route once and answers in the engine shape, without symbol or interval', async () => {
    const fetchMock = respondWith(answer())

    const facts = await factsFor('BHEL', 'nse')

    expect(facts).toEqual({
      exchange: 'NSE',
      timezone: 'Asia/Kolkata',
      tickSize: 0.05,
      lotSize: 1,
      instrumentType: 'equity',
      hasVolume: true,
      hasOpenInterest: false,
      session: SESSION,
    })
    expect(facts).not.toHaveProperty('symbol')
    expect(facts).not.toHaveProperty('interval')
    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url, init] = fetchMock.mock.calls[0] ?? []
    expect(url).toBe('/openscript/instrument?symbol=BHEL&exchange=NSE')
    // JSON asked for, so an expired session is a 401 and not a login page.
    expect((init?.headers as Record<string, string>).Accept).toBe('application/json')
  })

  it('keeps the answer, so a second read asks nothing', async () => {
    const fetchMock = respondWith(answer())

    const first = await factsFor('BHEL', 'NSE')
    const second = await factsFor(' BHEL ', 'nse')

    expect(second).toBe(first)
    expect(cachedFacts('BHEL', 'NSE')).toBe(first)
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('shares one request among every caller asking at once', async () => {
    const fetchMock = respondWith(answer())

    const [a, b, c] = await Promise.all([
      factsFor('BHEL', 'NSE'),
      factsFor('BHEL', 'NSE'),
      Promise.resolve(cachedFacts('BHEL', 'NSE')).then(() => factsFor('BHEL', 'NSE')),
    ])

    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(a).toBeDefined()
    expect(b).toBe(a)
    expect(c).toBe(a)
  })

  it('keeps instruments apart, and keeps the case of a symbol', async () => {
    const fetchMock = respondWith(answer())

    await factsFor('BHEL', 'NSE')
    await factsFor('BHEL', 'BSE')
    await factsFor('NIFTY Alpha 50', 'NSE_INDEX')

    expect(fetchMock).toHaveBeenCalledTimes(3)
    expect(fetchMock.mock.calls[2]?.[0]).toBe(
      '/openscript/instrument?symbol=NIFTY+Alpha+50&exchange=NSE_INDEX'
    )
  })

  it('asks nothing for an empty symbol or exchange', async () => {
    const fetchMock = respondWith(answer())

    expect(await factsFor('', 'NSE')).toBeUndefined()
    expect(await factsFor('BHEL', '  ')).toBeUndefined()
    expect(cachedFacts('', '')).toBeUndefined()
    expect(fetchMock).not.toHaveBeenCalled()
  })
})

describe('when the request fails', () => {
  it.each([
    ['the network', new Error('Failed to fetch')],
    ['the server', 'down'],
    ['an answer that is not one', { status: 'error', message: 'nope' }],
    ['an answer missing the one required fact', answer({ hasVolume: undefined })],
  ])('resolves to undefined rather than throwing, when %s fails', async (_what, failure) => {
    respondWith(failure)

    await expect(factsFor('BHEL', 'NSE')).resolves.toBeUndefined()
    expect(cachedFacts('BHEL', 'NSE')).toBeUndefined()
  })

  it('waits before asking again, then asks and keeps the answer', async () => {
    const fetchMock = respondWith(new Error('Failed to fetch'), answer())

    expect(await factsFor('BHEL', 'NSE')).toBeUndefined()
    // Straight away: no second request, whichever way it is asked.
    expect(await factsFor('BHEL', 'NSE')).toBeUndefined()
    expect(cachedFacts('BHEL', 'NSE')).toBeUndefined()
    expect(fetchMock).toHaveBeenCalledTimes(1)

    vi.advanceTimersByTime(RETRY_AFTER_MS)

    const facts = await factsFor('BHEL', 'NSE')
    expect(facts?.lotSize).toBe(1)
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })
})

describe('code that cannot await', () => {
  it('gets nothing at first, hears when the facts land, then reads them', async () => {
    respondWith(answer())
    const heard: [string, string][] = []
    const stop = subscribeFacts((symbol, exchange) => heard.push([symbol, exchange]))

    expect(cachedFacts('BHEL', 'nse')).toBeUndefined()
    await vi.waitFor(() => expect(heard).toEqual([['BHEL', 'NSE']]))
    expect(cachedFacts('BHEL', 'NSE')?.lotSize).toBe(1)

    stop()
    await factsFor('SBIN', 'NSE')
    expect(heard).toEqual([['BHEL', 'NSE']])
  })

  it('a subscriber that throws does not keep the news from the rest', async () => {
    respondWith(answer())
    const heard: string[] = []
    const stopBroken = subscribeFacts(() => {
      throw new Error('broken subscriber')
    })
    const stop = subscribeFacts((symbol) => heard.push(symbol))

    await factsFor('BHEL', 'NSE')

    expect(heard).toEqual(['BHEL'])
    stopBroken()
    stop()
  })

  it('is not told about a failure, which is not an arrival', async () => {
    respondWith(new Error('Failed to fetch'))
    const listener = vi.fn()
    const stop = subscribeFacts(listener)

    await factsFor('BHEL', 'NSE')

    expect(listener).not.toHaveBeenCalled()
    stop()
  })
})

describe("today's window", () => {
  it('is carried beside the record, apart from it', async () => {
    respondWith(
      answer(
        {},
        {
          date: '2026-09-23',
          open: true,
          isSpecial: true,
          session: { start: '18:00', end: '19:15', days: [3] },
        }
      )
    )

    const facts = await factsFor('BHEL', 'NSE')

    expect(facts?.session).toEqual(SESSION)
    expect(cachedToday('BHEL', 'NSE')).toEqual({
      date: '2026-09-23',
      open: true,
      isSpecial: true,
      session: { start: '18:00', end: '19:15', days: [3] },
    })
  })

  it('stops being offered once the day is over, and the next day is fetched', async () => {
    const fetchMock = respondWith(
      answer(),
      answer({}, { date: '2026-09-24', open: true, isSpecial: false, session: SESSION })
    )
    await factsFor('BHEL', 'NSE')
    expect(cachedToday('BHEL', 'NSE')?.date).toBe('2026-09-23')

    // 00:30 in Mumbai the next day.
    vi.setSystemTime(new Date('2026-09-23T19:00:00Z'))

    expect(cachedToday('BHEL', 'NSE')).toBeUndefined()
    // The regular facts do not change with the date, and are still offered.
    expect(cachedFacts('BHEL', 'NSE')?.lotSize).toBe(1)
    await vi.waitFor(() => expect(cachedToday('BHEL', 'NSE')?.date).toBe('2026-09-24'))
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('is absent for an exchange the calendar does not hold', async () => {
    const body = answer({ session: undefined })
    ;(body as Record<string, unknown>).today = null
    respondWith(body)

    await factsFor('US30', 'GLOBAL_INDEX')

    expect(cachedToday('US30', 'GLOBAL_INDEX')).toBeUndefined()
  })
})

describe('what the engine will accept', () => {
  it('leaves a session behind when there is no zone to read it in', async () => {
    respondWith(answer({ timezone: undefined }))

    const facts = await factsFor('BHEL', 'NSE')

    expect(facts?.session).toBeUndefined()
    expect(facts?.hasVolume).toBe(true)
  })

  it.each([
    [{ start: '9:15', end: '15:30' }],
    [{ start: '09:15', end: '25:00' }],
    [{ start: '09:15', end: '15:30', days: [0, 1, 2] }],
    [{ start: '09:15', end: '15:30', days: [] }],
    ['09:15-15:30'],
  ])('leaves out a malformed session %j rather than have the study refused', async (session) => {
    respondWith(answer({ session }))

    const facts = await factsFor('BHEL', 'NSE')

    expect(facts).toBeDefined()
    expect(facts?.session).toBeUndefined()
  })

  it('keeps a session that ends at midnight or crosses it', async () => {
    respondWith(answer({ session: { start: '00:00', end: '24:00', days: [1, 2, 3, 4, 5, 6, 7] } }))
    expect((await factsFor('BTCUSD', 'CRYPTO'))?.session?.end).toBe('24:00')

    clearInstrumentFacts()
    respondWith(answer({ session: { start: '18:00', end: '00:15', days: [7] } }))
    expect((await factsFor('CRUDEOIL', 'MCX'))?.session?.end).toBe('00:15')
  })

  it('states nothing for a size of zero or a type outside the seven words', async () => {
    respondWith(answer({ tickSize: 0, lotSize: -1, instrumentType: 'FUTIDX' }))

    const facts = await factsFor('NIFTY', 'NSE_INDEX')

    expect(facts).not.toHaveProperty('tickSize')
    expect(facts).not.toHaveProperty('lotSize')
    expect(facts).not.toHaveProperty('instrumentType')
  })

  it('hands out a record no caller can change for the next one', async () => {
    respondWith(answer())

    const facts = await factsFor('BHEL', 'NSE')

    expect(Object.isFrozen(facts)).toBe(true)
    expect(Object.isFrozen(facts?.session)).toBe(true)
  })
})
