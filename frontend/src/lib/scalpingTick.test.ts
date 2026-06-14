import { describe, expect, it } from 'vitest'
import type { QuotesData } from '@/api/trading'
import { mergeTick, type TickView } from './scalpingTick'

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
})
