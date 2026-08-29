/**
 * The previous session's close for an instrument, from daily history.
 *
 * Why this exists. The change percentage needs yesterday's close, and the
 * quote's `prev_close` does not reliably carry it: what each broker puts in
 * that field is the broker's own convention, and some report the CURRENT
 * session's close there, which during and after a session is simply the last
 * traded price. Every row then reads a confident +0.00%.
 *
 * Nothing here changes the API. `/api/v1/history` is a standard OpenAlgo
 * endpoint that every broker plugin implements, and the second-to-last daily
 * bar is the same thing the chart itself uses for the figure in its legend
 * (`terminal.ts`, `this.prevClose`). Reading it the same way is what makes a
 * watchlist row agree with the chart it opens.
 *
 * It is cheap because the number is fixed for the whole session: one request
 * per instrument per trading day, and only for instruments whose quote did not
 * already carry a usable value. The cache is written through to localStorage
 * under the trading day, so a reload costs nothing rather than re-fetching
 * every row, and a stale day is discarded rather than trusted.
 */

import { apiClient } from '@/api/client'

interface DailyBar {
  close: number
  timestamp: number
}

/** Where the day's resolved closes are kept between page loads. */
const STORE_KEY = 'oa-trading-prev-close'

/**
 * Resolved values, keyed `EXCHANGE:SYMBOL`. Cleared when the day rolls over.
 *
 * A failure is cached as UNAVAILABLE rather than left absent. The caller
 * re-renders on every tick, and an absent key reads as "not asked yet", so a
 * symbol whose history is missing or rate-limited was re-requested several
 * times a second, each attempt costing a CSRF fetch as well. Twenty such rows
 * is a self-inflicted denial of service against the app's own limiter.
 */
const cache = new Map<string, number>()

/** Cached marker for "asked, and history cannot supply it". */
const UNAVAILABLE = 0

/** In-flight requests, so twenty rows mounting together make one call each. */
const inflight = new Map<string, Promise<number | null>>()

/** The day the cache belongs to, as a local date string. */
let cachedDay = ''

/** Enough calendar days to clear a long weekend plus a holiday cluster. */
const LOOKBACK_DAYS = 20

function today(): string {
  return new Date().toDateString()
}

/** Load the day's cache from the previous page load, if it is still today's. */
function hydrate(day: string): void {
  try {
    const saved = JSON.parse(localStorage.getItem(STORE_KEY) || '{}')
    if (saved?.day !== day || typeof saved.values !== 'object') return
    for (const [key, value] of Object.entries(saved.values as Record<string, unknown>)) {
      // > 0 also rejects the UNAVAILABLE marker, so a failure is retried once
      // per page load rather than being persisted as a permanent verdict.
      if (typeof value === 'number' && Number.isFinite(value) && value > 0) {
        cache.set(key, value)
      }
    }
  } catch {
    // A corrupt or unavailable store just means a cold cache, not a failure.
  }
}

/** Write the cache through, stamped with the day it belongs to. */
function save(day: string): void {
  try {
    localStorage.setItem(STORE_KEY, JSON.stringify({ day, values: Object.fromEntries(cache) }))
  } catch {
    // Private mode, or a full quota. The in-memory cache still works.
  }
}

function isoDaysAgo(days: number): string {
  return localIso(new Date(Date.now() - days * 86400000))
}

/** `YYYY-MM-DD` in the viewer's own timezone, matching how `today()` works. */
function localIso(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

/** Whether a daily bar's epoch-second stamp falls on today, locally. */
function isToday(timestamp: number | undefined): boolean {
  if (typeof timestamp !== 'number' || !Number.isFinite(timestamp)) return false
  return new Date(timestamp * 1000).toDateString() === today()
}

/**
 * Which bar carries the previous close, given the last two.
 *
 * The question is whether the LAST bar is the same session the current price
 * belongs to. If it is, the previous close is the bar before it; if it is not,
 * the last bar is itself the previous close.
 *
 * Two earlier rules both got this wrong, from opposite sides, and each read
 * +0.00% against a price's own session:
 *
 *  - `bars[length - 2]` unconditionally broke where a broker does not publish
 *    today's bar intraday, measuring against a two-day-old close.
 *  - "is the last bar dated today" broke every non-trading day: on a Sunday
 *    the last bar is Friday's, the market is shut, and the price IS Friday's
 *    close, so the answer is no and that bar got picked.
 *  - comparing the bar's close to the price broke during market hours, which
 *    is when it matters: a daily bar and a websocket tick are snapshots taken
 *    moments apart and never exactly equal on a liquid instrument.
 *
 * Session state decides it without arithmetic on prices:
 *  - market shut: the last bar is the most recent completed session, which is
 *    the one the price came from, so take the bar before it
 *  - market open, today's bar published: the last bar is the session in
 *    progress, so again take the bar before it
 *  - market open, today's bar not published: the last bar is the previous
 *    session, so it IS the previous close
 */
function previousCloseBar(bars: DailyBar[], marketOpen: boolean): DailyBar | undefined {
  const last = bars[bars.length - 1]
  if (marketOpen && !isToday(last?.timestamp)) return last
  return bars[bars.length - 2]
}

/** Record that history cannot answer for this key, and say so. */
function fail(key: string): null {
  cache.set(key, UNAVAILABLE)
  return null
}

/**
 * Resolve one instrument's previous close, or null when history cannot supply
 * it. Never throws: a missing figure renders as a dash, which is honest, and a
 * failure here must not take the row's price down with it.
 */
export async function previousClose(
  apiKey: string,
  symbol: string,
  exchange: string,
  /**
   * Whether the instrument's exchange is trading right now. It is the only
   * thing that distinguishes "the last bar is the session in progress" from
   * "the broker has not published today's bar yet".
   */
  marketOpen = false
): Promise<number | null> {
  const day = today()
  if (cachedDay !== day) {
    cache.clear()
    inflight.clear()
    cachedDay = day
    // A close from yesterday would silently produce a wrong change all day,
    // so the store is only read when it carries today's stamp.
    hydrate(day)
  }

  const key = `${exchange}:${symbol}`
  const hit = cache.get(key)
  if (hit !== undefined) return hit === UNAVAILABLE ? null : hit

  const pending = inflight.get(key)
  if (pending) return pending

  const request = (async (): Promise<number | null> => {
    try {
      const res = await apiClient.post<{ status: string; data?: DailyBar[] }>('/history', {
        apikey: apiKey,
        symbol,
        exchange,
        interval: 'D',
        start_date: isoDaysAgo(LOOKBACK_DAYS),
        end_date: localIso(new Date()),
      })

      const bars = res.data?.status === 'success' ? (res.data?.data ?? []) : []
      if (bars.length === 0) return fail(key)

      const bar = previousCloseBar(bars, marketOpen)

      const value = bar?.close
      if (typeof value !== 'number' || !Number.isFinite(value) || value <= 0) {
        return fail(key)
      }

      cache.set(key, value)
      save(day)
      return value
    } catch {
      return fail(key)
    } finally {
      inflight.delete(key)
    }
  })()

  inflight.set(key, request)
  return request
}

/**
 * Whether a quote's own `prev_close` can be trusted for a change calculation.
 *
 * Zero means the broker did not send one. Exactly equal to the last traded
 * price means the field is carrying the current session's close rather than
 * the previous one: a real instrument can close flat, but then history returns
 * that same number anyway, so treating it as unusable costs one request and is
 * never wrong.
 */
export function needsPreviousClose(prevClose: number | undefined, ltp: number): boolean {
  return !prevClose || prevClose <= 0 || prevClose === ltp
}
