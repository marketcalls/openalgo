import { describe, expect, it, vi } from 'vitest'
import type { HistorifyCandle } from '@/api/historify'
import { createHistorifyFeed, dateWindow, toBar, toBars, toDateString } from './historifyFeed'

const candle = (over: Partial<HistorifyCandle> = {}): HistorifyCandle => ({
  timestamp: 1_718_000_100,
  open: 100,
  high: 101,
  low: 99,
  close: 100.5,
  volume: 1000,
  oi: 0,
  ...over,
})

describe('toDateString', () => {
  it('reads epoch seconds as UTC, so the browser timezone cannot move a window', () => {
    expect(toDateString(1_718_000_100)).toBe('2024-06-10')
    expect(toDateString(0)).toBe('1970-01-01')
  })
})

describe('dateWindow', () => {
  it('pads a day at each end against the server computing its window locally', () => {
    // The route converts dates with a naive strptime().timestamp(), i.e. in the
    // server's own timezone. Without padding, a host that is not IST clips the
    // first or last candle and it looks like the download stopped there.
    const window = dateWindow(1_718_000_100, 1_718_600_100)
    expect(window.startDate).toBe('2024-06-09')
    expect(window.endDate).toBe('2024-06-18')
  })

  it('omits an end it was not given, which asks for the whole stored history', () => {
    expect(dateWindow(undefined, undefined)).toEqual({})
    expect(dateWindow(1_718_000_100, undefined).endDate).toBeUndefined()
    expect(dateWindow(undefined, 1_718_000_100).startDate).toBeUndefined()
  })
})

describe('toBar', () => {
  it('rounds the float timestamp and volume every computed interval returns', () => {
    // 1m and D come back as integers; an aggregated interval is built with a
    // DuckDB FLOOR() that yields a DOUBLE, so the same fields arrive as floats.
    const bar = toBar(candle({ timestamp: 1_718_000_100.0, volume: 300.0000001 }))
    expect(bar?.time).toBe(1_718_000_100)
    expect(Number.isInteger(bar?.time)).toBe(true)
    expect(bar?.volume).toBe(300)
  })

  it('keeps a bar with no volume, because index series carry none', () => {
    const bar = toBar(candle({ volume: undefined as unknown as number }))
    expect(bar).not.toBeNull()
    expect(bar?.volume).toBeUndefined()
  })

  it('drops a row with no usable time or close rather than drawing a NaN', () => {
    expect(toBar(candle({ timestamp: Number.NaN }))).toBeNull()
    expect(toBar(candle({ close: Number.NaN }))).toBeNull()
    expect(toBar(undefined as unknown as HistorifyCandle)).toBeNull()
  })

  it('falls back to close for a missing open, high or low', () => {
    const bar = toBar(candle({ open: Number.NaN, high: Number.NaN, low: Number.NaN, close: 42 }))
    expect(bar).toEqual(expect.objectContaining({ open: 42, high: 42, low: 42, close: 42 }))
  })
})

describe('toBars', () => {
  it('sorts oldest first and skips the unusable rows', () => {
    const bars = toBars([
      candle({ timestamp: 300 }),
      candle({ timestamp: Number.NaN }),
      candle({ timestamp: 100 }),
      candle({ timestamp: 200 }),
    ])
    expect(bars.map((b) => b.time)).toEqual([100, 200, 300])
  })

  it('returns an empty array for an empty response, not an error', () => {
    expect(toBars([])).toEqual([])
  })
})

describe('createHistorifyFeed', () => {
  it('implements no subscription, so a chart on it cannot go live', () => {
    // This is the whole no-websocket guarantee. subscribeBars is optional on
    // DataFeed; not having it means there is no switch to leave on by mistake.
    const feed = createHistorifyFeed({ fetchCandles: vi.fn() })
    expect(feed.subscribeBars).toBeUndefined()
    expect(feed.subscribeDepth).toBeUndefined()
    expect(typeof feed.getBars).toBe('function')
  })

  it('omits getBarsPage, leaving the controller to page by date window', () => {
    // The store has no epoch cursor, only start_date and end_date.
    const feed = createHistorifyFeed({ fetchCandles: vi.fn() })
    expect(feed.getBarsPage).toBeUndefined()
  })

  it('passes the symbol, interval, padded window and abort signal through', async () => {
    const fetchCandles = vi.fn().mockResolvedValue([candle()])
    const feed = createHistorifyFeed({ fetchCandles })
    const controller = new AbortController()

    await feed.getBars({
      symbol: 'RELIANCE',
      exchange: 'NSE',
      interval: '25m',
      from: 1_718_000_100,
      to: 1_718_600_100,
      signal: controller.signal,
    })

    expect(fetchCandles).toHaveBeenCalledWith({
      symbol: 'RELIANCE',
      exchange: 'NSE',
      interval: '25m',
      startDate: '2024-06-09',
      endDate: '2024-06-18',
      signal: controller.signal,
    })
  })

  it('asks for nothing when there is no symbol to ask about', async () => {
    const fetchCandles = vi.fn()
    const feed = createHistorifyFeed({ fetchCandles })
    expect(await feed.getBars({ symbol: '', exchange: 'NSE', interval: 'D' })).toEqual([])
    expect(fetchCandles).not.toHaveBeenCalled()
  })

  it('treats an empty result as the end of history, not a failure', async () => {
    const feed = createHistorifyFeed({ fetchCandles: vi.fn().mockResolvedValue([]) })
    await expect(feed.getBars({ symbol: 'X', exchange: 'NSE', interval: 'D' })).resolves.toEqual([])
  })
})
