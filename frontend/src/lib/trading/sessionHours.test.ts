import type { Chart } from 'openalgo-charts'
import { SessionCalendar } from 'openalgo-charts'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  applySessionHours,
  calendarSpec,
  type HolidayRow,
  resetSessionHours,
  type TimingRow,
} from './sessionHours'

/** Epoch milliseconds of an IST wall-clock time, whatever zone the test runs in. */
const ist = (date: string, hh: number, mm: number) => {
  const [y, m, d] = date.split('-').map(Number)
  return Date.UTC(y, m - 1, d, hh, mm) - 19_800_000
}
const secs = (ms: number) => ms / 1000

const TIMINGS: TimingRow[] = [
  { exchange: 'NSE', start_offset: 33_300_000, end_offset: 55_800_000 },
  { exchange: 'BSE', start_offset: 33_300_000, end_offset: 55_800_000 },
  { exchange: 'MCX', start_offset: 32_400_000, end_offset: 86_100_000 },
  { exchange: 'CRYPTO', start_offset: 0, end_offset: 86_399_000 },
]
const CASH = ['NSE', 'BSE', 'NFO', 'BFO', 'CDS', 'BCD']
const HOLIDAYS: HolidayRow[] = [
  {
    date: '2026-10-02',
    holiday_type: 'TRADING_HOLIDAY',
    closed_exchanges: [...CASH, 'MCX'],
    open_exchanges: [],
  },
  {
    date: '2026-10-20',
    holiday_type: 'TRADING_HOLIDAY',
    closed_exchanges: CASH,
    open_exchanges: [
      {
        exchange: 'MCX',
        start_time: ist('2026-10-20', 17, 0),
        end_time: ist('2026-10-20', 23, 55),
      },
    ],
  },
  {
    date: '2026-10-21',
    holiday_type: 'SETTLEMENT_HOLIDAY',
    closed_exchanges: ['NSE'],
    open_exchanges: [],
  },
  {
    date: '2026-11-08',
    holiday_type: 'SPECIAL_SESSION',
    closed_exchanges: [],
    open_exchanges: [
      {
        exchange: 'NSE',
        start_time: ist('2026-11-08', 18, 0),
        end_time: ist('2026-11-08', 19, 15),
      },
      { exchange: 'MCX', start_time: ist('2026-11-08', 18, 0), end_time: ist('2026-11-09', 0, 15) },
    ],
  },
]

describe('calendarSpec', () => {
  it('builds NSE hours from the backend with the pre-open, holidays and special sessions', () => {
    expect(calendarSpec('NSE', TIMINGS, HOLIDAYS)).toEqual({
      timezone: 'Asia/Kolkata',
      sessions: ['0915-1530:23456'],
      preMarketMinutes: 15,
      exceptions: { '2026-10-02': [], '2026-10-20': [], '2026-11-08': ['1800-1915'] },
    })
  })

  it('gives an index the hours of its exchange', () => {
    expect(calendarSpec('NSE_INDEX', TIMINGS, HOLIDAYS)).toEqual(
      calendarSpec('NSE', TIMINGS, HOLIDAYS)
    )
  })

  it('keeps the MCX evening session on a cash holiday and an overnight Muhurat window', () => {
    expect(calendarSpec('MCX', TIMINGS, HOLIDAYS)).toEqual({
      timezone: 'Asia/Kolkata',
      sessions: ['0900-2355:23456'],
      exceptions: { '2026-10-02': [], '2026-10-20': ['1700-2355'], '2026-11-08': ['1800-0015'] },
    })
  })

  it('reads crypto as round the clock with no holidays', () => {
    expect(calendarSpec('CRYPTO', TIMINGS, HOLIDAYS)).toEqual({
      timezone: 'Asia/Kolkata',
      sessions: ['0000-0000'],
      exceptions: {},
    })
  })

  it('has no calendar for an exchange the backend keeps no hours for, or for bad rows', () => {
    expect(calendarSpec('NCDEX', TIMINGS, HOLIDAYS)).toBeNull()
    expect(
      calendarSpec('NSE', [{ exchange: 'NSE', start_offset: 55_800_000, end_offset: 0 }], [])
    ).toBeNull()
  })

  it('answers the market status a trader expects', () => {
    const nse = new SessionCalendar(calendarSpec('NSE', TIMINGS, HOLIDAYS))
    expect(nse.phaseAt(secs(ist('2026-10-01', 9, 5)))).toBe('pre')
    expect(nse.phaseAt(secs(ist('2026-10-01', 10, 0)))).toBe('regular')
    expect(nse.phaseAt(secs(ist('2026-10-01', 16, 0)))).toBe('closed')
    expect(nse.phaseAt(secs(ist('2026-10-02', 10, 0)))).toBe('holiday')
    expect(nse.phaseAt(secs(ist('2026-10-21', 10, 0)))).toBe('regular')
    const mcx = new SessionCalendar(calendarSpec('MCX', TIMINGS, HOLIDAYS))
    expect(mcx.phaseAt(secs(ist('2026-10-20', 18, 0)))).toBe('regular')
    expect(mcx.phaseAt(secs(ist('2026-11-09', 0, 10)))).toBe('regular')
    const crypto = new SessionCalendar(calendarSpec('CRYPTO', TIMINGS, HOLIDAYS))
    expect(crypto.phaseAt(secs(ist('2026-10-04', 3, 0)))).toBe('regular')
  })
})

describe('applySessionHours', () => {
  const fetchMock = vi.fn()
  const chart = () =>
    ({ isDestroyed: false, setSessionCalendar: vi.fn() }) as unknown as Chart & {
      setSessionCalendar: ReturnType<typeof vi.fn>
    }
  const answer = (data: unknown) =>
    Promise.resolve({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ status: 'success', data }),
    })
  const settle = async () => {
    for (let i = 0; i < 20; i++) await Promise.resolve()
  }

  beforeEach(() => {
    resetSessionHours()
    vi.useFakeTimers({ toFake: ['Date', 'setTimeout', 'clearTimeout'] })
    vi.setSystemTime(new Date('2026-10-01T05:00:00Z'))
    fetchMock.mockReset()
    fetchMock.mockImplementation((url: string) =>
      answer(url.includes('timings') ? TIMINGS : HOLIDAYS)
    )
    vi.stubGlobal('fetch', fetchMock)
  })
  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('fetches once for every pane and hands each chart its exchange hours', async () => {
    const a = chart()
    const b = chart()
    applySessionHours(a, 'NSE', 'key')
    applySessionHours(b, 'MCX', 'key')
    await settle()
    expect(fetchMock).toHaveBeenCalledTimes(2)
    const [, holidays] = fetchMock.mock.calls.map((call) => call[0])
    expect(holidays).toBe('/api/v1/market/holidays')
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({ apikey: 'key', year: 2026 })
    expect(a.setSessionCalendar).toHaveBeenCalledTimes(1)
    expect(b.setSessionCalendar).toHaveBeenCalledTimes(1)
    // A later build the same day is answered from memory.
    const c = chart()
    applySessionHours(c, 'NSE', 'key')
    expect(c.setSessionCalendar).toHaveBeenCalledTimes(1)
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('fetches again when the IST day turns, whatever the browser zone', async () => {
    vi.setSystemTime(new Date('2026-09-30T18:00:00Z')) // 23:30 IST
    applySessionHours(chart(), 'NSE', 'key')
    await settle()
    vi.setSystemTime(new Date('2026-09-30T18:40:00Z')) // 00:10 IST the next day
    applySessionHours(chart(), 'NSE', 'key')
    await settle()
    expect(fetchMock).toHaveBeenCalledTimes(4)
  })

  it('leaves the chart without hours when a request fails, and retries only after a pause', async () => {
    fetchMock.mockImplementation(() => Promise.reject(new TypeError('offline')))
    const a = chart()
    applySessionHours(a, 'NSE', 'key')
    await settle()
    expect(a.setSessionCalendar).not.toHaveBeenCalled()
    applySessionHours(chart(), 'NSE', 'key')
    expect(fetchMock).toHaveBeenCalledTimes(2)
    vi.setSystemTime(new Date('2026-10-01T05:06:00Z'))
    fetchMock.mockImplementation((url: string) =>
      answer(url.includes('timings') ? TIMINGS : HOLIDAYS)
    )
    const b = chart()
    applySessionHours(b, 'NSE', 'key')
    await settle()
    expect(fetchMock).toHaveBeenCalledTimes(4)
    expect(b.setSessionCalendar).toHaveBeenCalledTimes(1)
  })

  it('gives up on a request that does not answer', async () => {
    fetchMock.mockImplementation(
      (_url: string, init: RequestInit) =>
        new Promise((_resolve, reject) =>
          init.signal?.addEventListener('abort', () => reject(new Error('aborted')))
        )
    )
    const a = chart()
    applySessionHours(a, 'NSE', 'key')
    vi.advanceTimersByTime(8_000)
    await settle()
    expect(a.setSessionCalendar).not.toHaveBeenCalled()
  })

  it('does not touch a chart that was replaced before the hours arrived', async () => {
    const a = chart()
    applySessionHours(a, 'NSE', 'key')
    ;(a as { isDestroyed: boolean }).isDestroyed = true
    await settle()
    expect(a.setSessionCalendar).not.toHaveBeenCalled()
  })
})
