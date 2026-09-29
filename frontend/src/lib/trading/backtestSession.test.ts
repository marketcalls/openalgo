/**
 * A session strategy, backtested end to end on the real compiler and engine.
 *
 * **Why this is not mocked.** The defect it holds shut produced no error and
 * no odd number: the engine was handed the contract and nothing else, so it
 * had no interval, no zone and no session, and a strategy that entered on
 * `session.isFirstBar` after a daily read simply never traded. A mocked engine
 * accepts whatever it is given and cannot show that. So only the network is
 * replaced here: the history, the instrument facts route and the `/symbol`
 * fallback. The script is compiled by `compileSource`, facts are parsed by the
 * real helper, and the run goes through `runBacktest` on this thread, the path
 * that shares its engine call with the worker.
 *
 * The session and zone below are a fixture for what the facts route answers,
 * not a statement of any exchange's hours. The route reads those from the
 * market calendar.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const post = vi.fn()
vi.mock('@/api/client', () => ({
  apiClient: { post: (...args: unknown[]) => post(...args) },
  fetchCSRFToken: async () => '',
}))

// The run happens on this thread. The worker takes the same call, which the
// off-thread tests hold to stating the same facts.
vi.mock('./backtestWorker', () => ({
  runOnWorker: () => Promise.reject(new Error('no worker here')),
  workersAvailable: () => false,
}))

const { runBacktest } = await import('./backtestRun')
const { clearInstrumentFacts } = await import('./instrumentFacts')

/** Enters on the first bar of a session once a daily bar has closed, flat by the last. */
const SESSION_STRATEGY = `version 1
strategy("first bar after a daily read")
dayHigh = req.timeframe("1D", high)
if session.isLastBar
    close()
if session.isFirstBar and not isNone(dayHigh)
    buy(tag = "long")
`

/**
 * A daily chart that reads its own interval, a zoned date and a weekly read.
 *
 * Each of the three is absent without its fact: `chart.interval` without the
 * interval in the engine's spelling, `date.dayOfWeek` without a zone, and the
 * weekly read without a zone to date its buckets in.
 */
const DAILY_STRATEGY = `version 1
strategy("a daily chart")
weekHigh = req.timeframe("1W", high)
if chart.interval == "1D" and date.dayOfWeek(time) == 1 and not isNone(weekHigh) and pos.isFlat
    buy(tag = "long")
`

/** Enters on every session's first bar and never exits, so the second entry is refused. */
const STOPPING_STRATEGY = `version 1
strategy("stops on its second entry")
if session.isFirstBar
    buy(tag = "long")
`

const ZONE = 'UTC'
const OPENS = 9 * 60
const CLOSES = 17 * 60 + 30
const STEP = 30

/**
 * Five weekdays of thirty minute bars inside the fixture's session, in the
 * seconds the history API counts.
 */
function history() {
  const rows = []
  for (let day = 0; day < 5; day += 1) {
    // 2026-09-14 is a Monday.
    const midnight = Date.UTC(2026, 8, 14 + day) / 1000
    for (let minute = OPENS; minute < CLOSES; minute += STEP) {
      const price = 100 + day + minute / 1000
      rows.push({
        timestamp: midnight + minute * 60,
        open: price,
        high: price + 1,
        low: price - 1,
        close: price,
        volume: 10,
      })
    }
  }
  return rows
}

const BARS_PER_DAY = (CLOSES - OPENS) / STEP

/** Six weeks of daily bars, weekdays only, from a Monday. */
function dailyHistory() {
  const rows = []
  for (let day = 0; day < 42; day += 1) {
    // 2026-08-03 is a Monday.
    const midnight = Date.UTC(2026, 7, 3 + day)
    const weekday = new Date(midnight).getUTCDay()
    if (weekday === 0 || weekday === 6) continue
    const price = 100 + day
    rows.push({
      timestamp: midnight / 1000,
      open: price,
      high: price + 1,
      low: price - 1,
      close: price,
      volume: 10,
    })
  }
  return rows
}

function factsAnswer() {
  return {
    status: 'success',
    symbol: 'AAA',
    contractFound: true,
    instrument: {
      exchange: 'XX',
      timezone: ZONE,
      tickSize: 0.05,
      lotSize: 1,
      instrumentType: 'equity',
      hasVolume: true,
      hasOpenInterest: false,
      session: { start: '09:00', end: '17:30', days: [1, 2, 3, 4, 5] },
    },
    today: null,
  }
}

/** The facts route answering, or not, and the history always answering. */
function platform(factsUp: boolean, bars: () => unknown[] = history) {
  const fetchMock = vi.fn(async (url: string) => {
    if (factsUp && url.startsWith('/openscript/instrument')) {
      return { ok: true, json: async () => factsAnswer() } as unknown as Response
    }
    return { ok: false, json: async () => ({}) } as unknown as Response
  })
  vi.stubGlobal('fetch', fetchMock)
  post.mockImplementation(async (url: string) => {
    if (url === '/history') return { data: { status: 'success', data: bars() } }
    if (url === '/symbol') {
      return { data: { status: 'success', data: { lotsize: 1, tick_size: 0.05 } } }
    }
    return { data: { status: 'error' } }
  })
  return fetchMock
}

function request(source: string, interval = '30m') {
  return {
    file: 'probe.oscript',
    source,
    symbol: 'AAA',
    exchange: 'XX',
    interval,
    startDate: '2026-09-14',
    endDate: '2026-09-18',
    apiKey: 'key',
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  clearInstrumentFacts()
})

afterEach(() => {
  clearInstrumentFacts()
  vi.unstubAllGlobals()
})

describe('a session strategy against the real engine', () => {
  it('trades when the run states the interval, the zone and the session', async () => {
    // THE DEFECT, from the trader's side. The first session gives the daily
    // read nothing closed to read, so the four sessions after it each enter
    // on their first bar. Each exit is sent on its session's last bar.
    platform(true)

    const out = await runBacktest(request(SESSION_STRATEGY))

    expect(out.problem).toBeUndefined()
    expect(out.ok).toBe(true)
    expect(out.trades?.length).toBe(4)
    expect(out.stopped).toBeUndefined()
    expect(out.instrument).toEqual(
      expect.objectContaining({ interval: '30m', timezone: ZONE, hasVolume: true })
    )
  })

  it('does not trade when the facts could not be had', async () => {
    // The other half, and the reason the first is not vacuous: the same run
    // with no zone and no session has nothing for either condition to read.
    platform(false)

    const out = await runBacktest(request(SESSION_STRATEGY))

    expect(out.ok).toBe(true)
    expect(out.trades?.length).toBe(0)
    expect(out.instrument).toEqual({ interval: '30m' })
    // The money is still priced on the stored sizes, through the fallback.
    expect(post.mock.calls.map((call) => call[0])).toContain('/symbol')
    expect(out.contract?.usedFallback).toBe(false)
  })

  it('reads a daily chart as one day, in the zone the calendar states', async () => {
    // The chart spells a day `D` and the engine reads `1D`. Handed as the chart
    // writes it, the engine holds an interval it cannot read and the first
    // condition is absent on every bar; with no zone, so are the other two.
    platform(true, dailyHistory)

    const out = await runBacktest(request(DAILY_STRATEGY, 'D'))

    expect(out.ok).toBe(true)
    expect(out.trades?.length).toBe(1)
    expect(out.instrument?.interval).toBe('1D')
  })

  it('asks the master contract once when the facts route answers', async () => {
    platform(true)

    await runBacktest(request(SESSION_STRATEGY))

    expect(post.mock.calls.map((call) => call[0])).toEqual(['/history'])
  })
})

describe('a run the script stops part way', () => {
  it('reports the stopping diagnostic with its bar and time', async () => {
    // THE SILENT STOP. An order refused on a bar ends the run there, and the
    // record carries the code that did it. The panel ignored it, so the run
    // simply ended with a report of fewer trades and no word about why.
    platform(true)

    const out = await runBacktest(request(STOPPING_STRATEGY))

    expect(out.ok).toBe(true)
    expect(out.stopped).toEqual({
      code: 'OS7008',
      title: 'The entry was refused by pyramiding',
      fix: 'Raise pyramiding in the declaration, or test pos.size before entering again.',
      line: 4,
      column: 5,
      // The first bar of the second session.
      barIndex: BARS_PER_DAY,
      barTime: Date.UTC(2026, 8, 15, 9, 0),
    })
    // What it did before the stop is still reported.
    expect(out.trades?.length).toBe(1)
  })
})
