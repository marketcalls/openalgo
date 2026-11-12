import { type BarsRequest, CandleBuilder, SessionCalendar } from 'openalgo-charts'
import { describe, expect, it, vi } from 'vitest'
import { lookbackDays } from './intervals'
import { createTradingTimeframes, sourceSpanSeconds } from './timeframeFeed'

const start = Date.parse('2026-10-01T03:45:00Z') / 1000
const calendar = new SessionCalendar({ timezone: 'Asia/Kolkata', sessions: ['0915-1530:23456'] })
const request = {
  symbol: 'RELIANCE',
  exchange: 'NSE',
  interval: '7m',
  from: start,
  to: start + 14 * 60,
}
const options = (nativeIntervals = ['1m', '5m', 'D']) => ({
  providerId: 'test',
  nativeIntervals,
  calendar: () => calendar,
  calendarRevision: () => '1',
  now: () => start + 15 * 60,
})

describe('broker custom timeframes', () => {
  it('uses the source exchange timezone for a complete UTC month', async () => {
    const from = Date.parse('2026-10-01T00:00:00Z') / 1000
    const daily = Array.from({ length: 31 }, (_, i) => ({
      time: from + i * 86400,
      open: i,
      high: i + 2,
      low: i - 1,
      close: i + 1,
      volume: 1,
    }))
    const service = createTradingTimeframes(
      {
        getBars: async (req) => daily.filter((bar) => bar.time >= req.from! && bar.time < req.to!),
      },
      {
        ...options(['D']),
        calendar: () => new SessionCalendar({ timezone: 'UTC', sessions: ['0000-0000'] }),
      }
    )
    const result = await service.feed.getBars({
      symbol: 'TEST',
      exchange: 'CRYPTO',
      interval: 'M',
      from,
      to: from + 31 * 86400,
    })
    expect(result).toEqual([{ time: from, open: 0, high: 32, low: -1, close: 31, volume: 31 }])
    service.destroy()
  })

  it('derives only compatible choices and preserves the native wire token', async () => {
    const getBars = vi.fn(async (_req: BarsRequest) =>
      Array.from({ length: 14 }, (_, i) => ({
        time: start + i * 60,
        open: i,
        high: i + 2,
        low: i - 1,
        close: i + 1,
        volume: 10,
      }))
    )
    const service = createTradingTimeframes({ getBars }, options())
    for (const interval of ['7m', '1h', '2h', 'W', 'M', 'Q'])
      expect(service.supports(interval, request)).toBe(true)
    expect(service.supports('5s', request)).toBe(false)
    const bars = await service.feed.getBars(request)
    expect(getBars.mock.calls[0][0].interval).toBe('1m')
    expect(bars).toEqual([
      { time: start, open: 0, high: 8, low: -1, close: 7, volume: 70 },
      { time: start + 420, open: 7, high: 15, low: 6, close: 14, volume: 70 },
    ])
    await service.feed.getBars({ ...request, interval: '1d' })
    expect(getBars.mock.calls.at(-1)?.[0].interval).toBe('D')
    service.destroy()
  })

  it('uses seconds only when supplied, and never assumes unknown exchange alignment', () => {
    const seconds = createTradingTimeframes({ getBars: async () => [] }, options(['1s']))
    expect(seconds.supports('5s', request)).toBe(true)
    const unknown = createTradingTimeframes(
      { getBars: async () => [] },
      { ...options(), calendar: () => null }
    )
    expect(unknown.supports('1m', request)).toBe(true)
    expect(unknown.supports('7m', request)).toBe(false)
    seconds.destroy()
    unknown.destroy()
  })

  it('anchors history and live seven-minute bars to each session, including the next day', async () => {
    const service = createTradingTimeframes({ getBars: async () => [] }, options())
    const builder = new CandleBuilder({
      intervalSec: 420,
      bucketStart: (time) => service.bucketStart(request, time),
    })
    const next = start + 86400
    expect(builder.onTick({ time: start + 8 * 60, price: 100 })?.bar.time).toBe(start + 420)
    expect(builder.onTick({ time: next + 8 * 60, price: 101 })?.bar.time).toBe(next + 420)
    service.destroy()
  })

  it('passes cancellation and variants through preparation and cancels owned pending history on destroy', async () => {
    let signal: AbortSignal | undefined
    const prepare = vi.fn(async () => {})
    const service = createTradingTimeframes(
      {
        getBars: (req) =>
          new Promise((_resolve, reject) => {
            signal = req.signal
            signal?.addEventListener('abort', () =>
              reject(new DOMException('cancelled', 'AbortError'))
            )
          }),
      },
      { ...options(), prepare }
    )
    const pending = service.feed.getBars({ ...request, variant: { adjustment: 'adjusted' } })
    const rejected = expect(pending).rejects.toThrow()
    await vi.waitFor(() => expect(signal).toBeDefined())
    service.destroy()
    await rejected
    expect(signal?.aborted).toBe(true)
    expect(prepare).toHaveBeenCalled()
  })

  it('warms daily history independently and withholds the current unfinished daily value', async () => {
    const now = Date.parse('2026-10-01T06:00:00Z') / 1000
    const daily = Array.from({ length: 450 }, (_, i) => {
      const time = start - (449 - i) * 86400 - 33300
      return { time, open: i + 1, high: i + 3, low: i, close: i + 2 }
    }).filter((bar) => {
      const session = calendar.sessionFrom(bar.time)
      return session && session.open < bar.time + 86400
    })
    const wires: string[] = []
    const service = createTradingTimeframes(
      {
        getBars: async (req) => {
          wires.push(req.interval)
          return daily.filter((bar) => bar.time >= req.from! && bar.time < req.to!)
        },
      },
      { ...options(), now: () => now }
    )
    const snapshot = await service.provider.requestSnapshot!({
      symbol: 'RELIANCE',
      exchange: 'NSE',
      interval: 'D',
      from: start - 2 * 86400,
      to: now,
      warmupBars: 200,
    })
    expect(
      snapshot.bars.filter(
        (_, i) => snapshot.confirmed[i] && snapshot.availableAt[i]! <= start - 2 * 86400
      ).length
    ).toBeGreaterThanOrEqual(200)
    expect(snapshot.confirmed.at(-1)).toBe(false)
    expect(new Set(wires)).toEqual(new Set(['D']))
    await expect(
      service.provider.requestSnapshot!({
        symbol: 'RELIANCE',
        exchange: 'NSE',
        interval: 'D',
        from: start,
        to: now,
        asOf: start,
      })
    ).rejects.toThrow(/Historical/)
    service.destroy()
  })

  // #2384: W and M derive from D one window after another under the chart's
  // 15 s deadline, and the server spaces broker history calls 0.35 s apart.
  it('builds weekly and monthly from a daily-only feed in few history calls', async () => {
    expect(sourceSpanSeconds('1m')).toBe(30 * 86400)
    expect(sourceSpanSeconds('1h')).toBe(30 * 86400)
    expect(sourceSpanSeconds('D')).toBe(2000 * 86400)
    const to = Date.parse('2026-11-12T00:00:00Z') / 1000
    for (const interval of ['W', 'M', '2W', '3M']) {
      // One daily bar per window, so a derived result proves the windows were read.
      const getBars = vi.fn(async (req: BarsRequest) => [
        { time: req.from!, open: 1, high: 2, low: 1, close: 2, volume: 1 },
      ])
      const service = createTradingTimeframes({ getBars }, { ...options(['D']), now: () => to })
      const from = to - lookbackDays(interval) * 86400
      const bars = await service.feed.getBars({
        symbol: 'NIFTY',
        exchange: 'NSE',
        interval,
        from,
        to,
      })
      expect(bars.length).toBeGreaterThan(0)
      const calls = getBars.mock.calls.map(([req]) => req)
      expect(calls.length).toBeGreaterThan(0)
      expect(calls.every((req) => req.interval === 'D')).toBe(true)
      expect(calls.every((req) => req.to! - req.from! <= 2000 * 86400)).toBe(true)
      // At the server's 0.35 s spacing the whole derived load fits well inside 15 s.
      expect(calls.length * 0.35).toBeLessThan(5)
      service.destroy()
    }
  })

  // A Sunday special session in a year with no holiday list is still that day's bar.
  it('places a daily bar on a day the calendar shows closed on its own date', async () => {
    const sunday = Date.parse('2019-10-27T00:00:00+05:30') / 1000
    const daily = [sunday - 2 * 86400, sunday, sunday + 86400].map((time, i) => ({
      time,
      open: i,
      high: i + 1,
      low: i,
      close: i + 1,
      volume: 1,
    }))
    const service = createTradingTimeframes(
      { getBars: async (req) => daily.filter((b) => b.time >= req.from! && b.time < req.to!) },
      { ...options(['D']), now: () => sunday + 30 * 86400 }
    )
    const from = Date.parse('2019-10-01T00:00:00+05:30') / 1000
    const bars = await service.feed.getBars({
      symbol: 'SBIN',
      exchange: 'NSE',
      interval: 'M',
      from,
      to: from + 31 * 86400,
    })
    expect(bars).toHaveLength(1)
    expect(bars[0]).toMatchObject({ open: 0, close: 3, volume: 3 })
    service.destroy()
  })
})
