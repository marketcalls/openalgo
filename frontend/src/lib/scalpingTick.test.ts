import { describe, expect, it } from 'vitest'
import type { QuotesData } from '@/api/trading'
import { type FeedEntry, mergeTick, needsQuotePoll, type TickView } from './scalpingTick'

const NOW = 1_000_000
const FRESH = NOW - 1000 // within stale window
const STALE = NOW - 9000 // beyond stale window
const STALE_MS = 5000

const mq = (o: Partial<QuotesData>): QuotesData => ({
  ask: 0,
  bid: 0,
  high: 0,
  low: 0,
  ltp: 0,
  oi: 0,
  open: 0,
  prev_close: 0,
  volume: 0,
  ...o,
})

describe('mergeTick', () => {
  it('returns undefined when neither source has data', () => {
    expect(mergeTick(undefined, undefined, undefined, NOW, STALE_MS)).toBeUndefined()
  })

  it('uses FRESH WebSocket values when present', () => {
    const ws: TickView = { ltp: 179.3, open: 70, high: 191, low: 31, change: 5, change_percent: 2 }
    const t = mergeTick(ws, FRESH, undefined, NOW, STALE_MS)
    expect(t?.ltp).toBe(179.3)
    expect(t?.high).toBe(191)
    expect(t?.change).toBe(5)
  })

  it('falls back to MultiQuotes for ltp/OHLC when WS is stale', () => {
    const ws: TickView = { ltp: 100 } // stale snapshot
    const m = mq({ ltp: 179.3, open: 70, high: 191, low: 31, prev_close: 174.3 })
    const t = mergeTick(ws, STALE, m, NOW, STALE_MS)
    expect(t?.ltp).toBe(179.3)
    expect(t?.high).toBe(191)
    expect(t?.change).toBeCloseTo(5) // 179.3 - 174.3
  })

  it('fills change from MultiQuotes even when WS is FRESH but lacks it (flicker fix)', () => {
    // The WS Quote tick often omits change/change_percent; they must NOT blank.
    const ws: TickView = { ltp: 179.3, open: 70, high: 191, low: 31 }
    const m = mq({ ltp: 0, prev_close: 174.3 })
    const t = mergeTick(ws, FRESH, m, NOW, STALE_MS)
    expect(t?.ltp).toBe(179.3) // fresh WS ltp still wins
    expect(t?.change).toBeCloseTo(5) // computed from MQ prev_close, not blanked
    expect(t?.change_percent).toBeCloseTo((5 / 174.3) * 100)
  })

  it('keeps the WS change when MQ has no prev_close (no blank)', () => {
    const ws: TickView = { ltp: 179.3, change: 5, change_percent: 2 }
    const m = mq({ ltp: 179.3, prev_close: 0 })
    const t = mergeTick(ws, FRESH, m, NOW, STALE_MS)
    expect(t?.change).toBe(5)
    expect(t?.change_percent).toBe(2)
  })

  it('uses MultiQuotes when there is no WS data at all', () => {
    const m = mq({ ltp: 50, open: 48, high: 55, low: 45, prev_close: 49 })
    const t = mergeTick(undefined, undefined, m, NOW, STALE_MS)
    expect(t?.ltp).toBe(50)
    expect(t?.high).toBe(55)
    expect(t?.change).toBeCloseTo(1)
  })

  it('prefers a stale WS snapshot that is newer than the MultiQuotes answer', () => {
    const ws: TickView = { ltp: 180, open: 70, high: 192, low: 31 }
    const m = mq({ ltp: 179.3, open: 70, high: 191, low: 31, prev_close: 174.3 })
    const t = mergeTick(ws, STALE, m, NOW, STALE_MS, STALE - 60_000)
    expect(t?.ltp).toBe(180)
    expect(t?.high).toBe(192)
    expect(t?.change).toBeCloseTo(5.7) // WS ltp 180 - MQ prev_close 174.3
  })

  it('keeps the MultiQuotes values when the stale WS snapshot is older than the answer (after hours)', () => {
    const ws: TickView = { ltp: 180, open: 70, high: 192, low: 31 }
    const m = mq({ ltp: 179.3, open: 70, high: 191, low: 31, prev_close: 174.3 })
    const t = mergeTick(ws, STALE, m, NOW, STALE_MS, STALE + 1000)
    expect(t?.ltp).toBe(179.3)
    expect(t?.high).toBe(191)
    expect(t?.change).toBeCloseTo(5)
  })

  it('keeps the MultiQuotes values when the snapshot and the answer have the same time', () => {
    const ws: TickView = { ltp: 180 }
    const m = mq({ ltp: 179.3, prev_close: 174.3 })
    expect(mergeTick(ws, STALE, m, NOW, STALE_MS, STALE)?.ltp).toBe(179.3)
  })

  it('takes fields a newer snapshot lacks (index high/low) from MultiQuotes', () => {
    const ws: TickView = { ltp: 24_100, open: 24_000 }
    const m = mq({ ltp: 24_050, open: 24_000, high: 24_200, low: 23_900, prev_close: 24_010 })
    const t = mergeTick(ws, STALE, m, NOW, STALE_MS, STALE - 60_000)
    expect(t?.ltp).toBe(24_100)
    expect(t?.high).toBe(24_200)
    expect(t?.low).toBe(23_900)
  })

  it('does not prefer a newer snapshot that has no ltp', () => {
    const ws: TickView = { high: 192 }
    const m = mq({ ltp: 179.3, high: 191, prev_close: 174.3 })
    const t = mergeTick(ws, STALE, m, NOW, STALE_MS, STALE - 60_000)
    expect(t?.ltp).toBe(179.3)
    expect(t?.high).toBe(191)
  })
})

describe('needsQuotePoll', () => {
  const FULL: TickView = { ltp: 179.3, open: 70, high: 191, low: 31 }
  const sym = (symbol: string, exchange = 'NFO') => ({ symbol, exchange })
  const feedOf = (entries: Record<string, FeedEntry>) => new Map(Object.entries(entries))
  const fresh = (data: TickView = FULL): FeedEntry => ({ data, lastUpdate: FRESH })

  it('returns false for an empty symbol list', () => {
    expect(needsQuotePoll([], new Map(), NOW, STALE_MS)).toBe(false)
  })

  it('returns false when every symbol has a fresh, full tick (no poll while the feed is live)', () => {
    const feed = feedOf({ 'NFO:CE1': fresh(), 'NFO:PE1': fresh() })
    expect(needsQuotePoll([sym('CE1'), sym('PE1')], feed, NOW, STALE_MS)).toBe(false)
  })

  it('returns true when one symbol is missing from the feed', () => {
    const feed = feedOf({ 'NFO:CE1': fresh() })
    expect(needsQuotePoll([sym('CE1'), sym('PE1')], feed, NOW, STALE_MS)).toBe(true)
  })

  it('treats a tick exactly staleMs old as stale', () => {
    const feed = feedOf({ 'NFO:CE1': { data: FULL, lastUpdate: NOW - STALE_MS } })
    expect(needsQuotePoll([sym('CE1')], feed, NOW, STALE_MS)).toBe(true)
  })

  it('treats a tick staleMs - 1 old as fresh', () => {
    const feed = feedOf({ 'NFO:CE1': { data: FULL, lastUpdate: NOW - (STALE_MS - 1) } })
    expect(needsQuotePoll([sym('CE1')], feed, NOW, STALE_MS)).toBe(false)
  })

  it('returns true when one of several ticks is stale', () => {
    const feed = feedOf({ 'NFO:CE1': fresh(), 'NFO:PE1': { data: FULL, lastUpdate: STALE } })
    expect(needsQuotePoll([sym('CE1'), sym('PE1')], feed, NOW, STALE_MS)).toBe(true)
  })

  it('returns true for a fresh tick without high/low (index ticks)', () => {
    const feed = feedOf({ 'NSE_INDEX:NIFTY': fresh({ ltp: 24000, open: 23900 }) })
    expect(needsQuotePoll([sym('NIFTY', 'NSE_INDEX')], feed, NOW, STALE_MS)).toBe(true)
  })

  it('returns false for a fresh tick without change/change_percent', () => {
    const feed = feedOf({ 'NFO:CE1': fresh({ ltp: 10, open: 9, high: 12, low: 8 }) })
    expect(needsQuotePoll([sym('CE1')], feed, NOW, STALE_MS)).toBe(false)
  })

  it('returns true when lastUpdate is undefined', () => {
    const feed = feedOf({ 'NFO:CE1': { data: FULL } })
    expect(needsQuotePoll([sym('CE1')], feed, NOW, STALE_MS)).toBe(true)
  })

  it('keys the feed by exchange:symbol, so the same symbol on another exchange does not count', () => {
    const feed = feedOf({ 'BFO:CE1': fresh() })
    expect(needsQuotePoll([sym('CE1', 'NFO')], feed, NOW, STALE_MS)).toBe(true)
  })
})
