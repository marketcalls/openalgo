import { type BarsRequest, SessionCalendar } from 'openalgo-charts'
import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  prepareSessionHours,
  resetSessionHours,
  sessionCalendar,
  sessionCalendarRevision,
} from '@/lib/trading/sessionHours'
import { createHistorifyTimeframes } from './timeframes'

const calendar = new SessionCalendar({ timezone: 'Asia/Kolkata', sessions: ['0915-1530:23456'] })
const first = Date.parse('2024-01-01T03:45:00Z') / 1000
const last = Date.parse('2026-10-16T03:45:00Z') / 1000
const symbols = [
  {
    symbol: 'TEST',
    exchange: 'NSE',
    sources: new Set<'1m' | 'D'>(['1m', 'D']),
    firstBySource: { '1m': first, D: first },
    lastBySource: { '1m': last, D: last },
    records: 1000,
  },
]

describe('Historify custom history', () => {
  it.each([
    ['2025-01-15T03:45:00Z', false],
    ['2025-01-31T03:45:00Z', true],
  ] as const)('confirms a stored calendar tail only when source coverage reaches its last session (%s)', async (lastStamp, confirmed) => {
    const sourceLast = Date.parse(lastStamp) / 1000
    const service = createHistorifyTimeframes(
      {
        getBars: async () => [
          {
            time: Date.parse('2025-01-01') / 1000,
            open: 10,
            high: 20,
            low: 5,
            close: 15,
          },
        ],
      },
      {
        symbols: [{ ...symbols[0], lastBySource: { D: sourceLast } }],
        calendar: () => calendar,
        calendarRevision: () => '1',
        now: () => Date.parse('2026-10-17') / 1000,
      }
    )
    const snapshot = await service.provider.requestSnapshot!({
      symbol: 'TEST',
      exchange: 'NSE',
      interval: 'M',
      from: Date.parse('2025-01-02') / 1000,
      to: Date.parse('2025-02-02') / 1000,
    })
    expect(snapshot.bars).toHaveLength(1)
    expect(snapshot.confirmed).toEqual([confirmed])
    service.destroy()
  })

  it('keeps database aggregation, expands whole calendar buckets and converts wall-clock labels', async () => {
    const getBars = vi.fn(async () => [
      {
        time: Date.parse('2026-10-01T00:00:00Z') / 1000,
        open: 10,
        high: 14,
        low: 9,
        close: 13,
        volume: 100,
      },
    ])
    const service = createHistorifyTimeframes(
      { getBars },
      { symbols, calendar: () => calendar, calendarRevision: () => '1' }
    )
    const bars = await service.feed.getBars({
      symbol: 'TEST',
      exchange: 'NSE',
      interval: 'M',
      from: Date.parse('2026-10-12') / 1000,
      to: Date.parse('2026-10-15') / 1000,
    })
    expect(getBars).toHaveBeenCalledWith(
      expect.objectContaining({
        interval: 'M',
        from: Date.parse('2026-09-30T18:30:00Z') / 1000,
        to: Date.parse('2026-10-31T18:30:00Z') / 1000,
      })
    )
    expect(bars[0].time).toBe(Date.parse('2026-09-30T18:30:00Z') / 1000)
    expect(service.supports('2D', { symbol: 'TEST', exchange: 'NSE' })).toBe(true)
    expect(service.supports('5s', { symbol: 'TEST', exchange: 'NSE' })).toBe(false)
    service.destroy()
  })

  it('resamples round-the-clock data using UTC rather than the database IST opening', async () => {
    const from = Date.parse('2026-10-16T00:00:00Z') / 1000
    const getBars = vi.fn(async () =>
      Array.from({ length: 120 }, (_, i) => ({
        time: from + i * 60,
        open: i,
        high: i + 2,
        low: i - 1,
        close: i + 1,
        volume: 1,
      }))
    )
    const service = createHistorifyTimeframes(
      { getBars },
      {
        symbols: [{ ...symbols[0], exchange: 'CRYPTO' }],
        calendar: () => new SessionCalendar({ timezone: 'UTC', sessions: ['0000-0000'] }),
        calendarRevision: () => '1',
      }
    )
    const bars = await service.feed.getBars({
      symbol: 'TEST',
      exchange: 'CRYPTO',
      interval: '2h',
      from,
      to: from + 7200,
    })
    expect(getBars).toHaveBeenCalledWith(expect.objectContaining({ interval: '1m' }))
    expect(bars).toEqual([{ time: from, open: 0, high: 121, low: -1, close: 120, volume: 120 }])
    getBars.mockClear()
    await service.feed.getBars({
      symbol: 'TEST',
      exchange: 'CRYPTO',
      interval: 'M',
      from,
      to: from + 7200,
    })
    expect(getBars).toHaveBeenCalledWith(expect.objectContaining({ interval: 'D' }))
    service.destroy()
  })

  it('stops paging at the actual stored horizon and never subscribes to a live feed', async () => {
    const getBars = vi.fn(async () => [])
    const service = createHistorifyTimeframes(
      { getBars },
      { symbols, calendar: () => calendar, calendarRevision: () => '1' }
    )
    expect(
      await service.feed.getBarsPage!({
        symbol: 'TEST',
        exchange: 'NSE',
        interval: 'D',
        before: first,
        countBack: 200,
      })
    ).toMatchObject({ bars: [], hasMore: false })
    expect(getBars).not.toHaveBeenCalled()
    expect(service.feed.subscribeBars).toBeUndefined()
    expect(service.provider.supportsWarmup).toBe(true)
    service.destroy()
  })
})

describe('Historify older history pages', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    resetSessionHours()
  })

  // #2310: a page that ends at a session open was planned with no start date,
  // so the calendar lookup found no years and derived intervals were refused.
  it.each([
    ['1m', '2026-10-26T03:45:00Z'],
    ['3m', '2026-10-26T03:45:00Z'],
    ['5m', '2026-10-23T03:45:00Z'],
    ['15m', '2026-10-27T03:45:00Z'],
    ['1h', '2026-10-26T03:45:00Z'],
  ])('pages %s back from the session open at %s with the real exchange calendar', async (interval, stamp) => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => ({
        ok: true,
        json: async () => ({
          status: 'success',
          data: url.includes('timings')
            ? [{ exchange: 'NSE', start_offset: 33_300_000, end_offset: 55_800_000 }]
            : [],
        }),
      }))
    )
    const start = Date.parse('2026-10-01T03:45:00Z') / 1000
    const end = Date.parse('2026-10-27T09:59:00Z') / 1000
    const getBars = vi.fn(async () => [])
    const service = createHistorifyTimeframes(
      { getBars },
      {
        symbols: [
          {
            ...symbols[0],
            exchange: 'NSE_INDEX',
            firstBySource: { '1m': start, D: start },
            lastBySource: { '1m': end, D: end },
          },
        ],
        calendar: sessionCalendar,
        calendarRevision: sessionCalendarRevision,
        prepare: (request) => prepareSessionHours('key', request),
      }
    )
    const before = Date.parse(stamp) / 1000
    await expect(
      service.feed.getBarsPage!({
        symbol: 'TEST',
        exchange: 'NSE_INDEX',
        interval,
        before,
        countBack: 500,
      })
    ).resolves.toMatchObject({ bars: [] })
    // Pin the page's range, not only that a request went out: it ends at the
    // oldest bar on screen and never reaches before the stored history.
    expect(getBars).toHaveBeenCalled()
    for (const [request] of getBars.mock.calls as unknown as [BarsRequest][]) {
      expect(request.interval).toBe(interval)
      expect(request.to).toBe(before)
      expect(request.from).toBeGreaterThanOrEqual(start)
      expect(request.from).toBeLessThanOrEqual(before)
    }
    service.destroy()
  })
})
