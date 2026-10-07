/**
 * Trading hours for the chart, read from OpenAlgo's own market calendar.
 *
 * The admin's market timings (`/admin/api/timings`) give each exchange its
 * weekly hours and the holiday list (`/api/v1/market/holidays`) gives the
 * closed dates and the special sessions (an MCX evening on an NSE holiday,
 * Muhurat trading). Together they become one `SessionCalendar` per exchange,
 * which the chart uses for the time axis past the last bar, the session
 * shading and the bottom bar's market status.
 *
 * Nothing here is allowed to stop a chart drawing. Both requests time out,
 * either failing leaves every chart without a calendar (which is how the
 * chart behaved before), and the answer is fetched once per IST day for the
 * whole page rather than per pane, per symbol or per render.
 */
import {
  attachSessionShading,
  type Chart,
  SessionCalendar,
  type SessionCalendarSpec,
} from 'openalgo-charts'
import type { MarketTiming } from '@/types/admin'

const ZONE = 'Asia/Kolkata'
const IST_OFFSET_MS = 19_800_000
const DAY_MS = 86_400_000
const TIMEOUT_MS = 8_000
/** A failed fetch is tried again no sooner than this, so a broken endpoint costs one request per chart build at most every few minutes. */
const RETRY_AFTER_MS = 5 * 60_000
/** Exchanges that trade round the clock, every day, with no holidays. */
const ROUND_THE_CLOCK = new Set(['CRYPTO'])
/**
 * Minutes of pre-open before the regular open. The backend keeps the regular
 * hours only, and the cash market's pre-open (09:00 to 09:15, orders until
 * 09:08) is a fixed exchange rule rather than something an admin edits.
 */
const PRE_OPEN_MINUTES: Record<string, number> = { NSE: 15, BSE: 15 }

/** One row of the holiday list, as `/api/v1/market/holidays` returns it. */
export interface HolidayRow {
  date: string
  holiday_type: string
  closed_exchanges: string[]
  open_exchanges: { exchange: string; start_time: number; end_time: number }[]
}

export type TimingRow = Pick<MarketTiming, 'exchange' | 'start_offset' | 'end_offset'>

/** The exchange whose calendar an instrument follows: an index trades the hours of its exchange. */
export function calendarExchange(exchange: string): string {
  return exchange.endsWith('_INDEX') ? exchange.slice(0, -'_INDEX'.length) : exchange
}

const pad = (n: number) => String(n).padStart(2, '0')
const hhmm = (minutes: number) => `${pad(Math.floor(minutes / 60) % 24)}${pad(minutes % 60)}`

/** Minutes after IST midnight and the IST date of an epoch in milliseconds. */
function istClock(ms: number): { date: string; minutes: number } {
  const shifted = new Date(ms + IST_OFFSET_MS)
  return {
    date: shifted.toISOString().slice(0, 10),
    minutes: shifted.getUTCHours() * 60 + shifted.getUTCMinutes(),
  }
}

/** A special session's window on its own date, or null when the row does not describe one. */
function sessionWindow(start: unknown, end: unknown, date: string): string | null {
  if (typeof start !== 'number' || typeof end !== 'number' || !(end > start)) return null
  const open = istClock(start)
  if (open.date !== date) return null
  const close = istClock(end)
  if (open.minutes === close.minutes) return null
  return `${hhmm(open.minutes)}-${hhmm(close.minutes)}`
}

/**
 * The calendar spec for one exchange, or null when the backend has no hours
 * for it (NCDEX and the global indices, for instance), in which case the
 * chart keeps working without a calendar.
 */
export function calendarSpec(
  exchange: string,
  timings: readonly TimingRow[],
  holidays: readonly HolidayRow[]
): SessionCalendarSpec | null {
  const code = calendarExchange(exchange)
  const row = timings.find((t) => t.exchange === code)
  if (!row) return null
  const start = Number(row.start_offset)
  const end = Number(row.end_offset)
  if (!Number.isFinite(start) || !Number.isFinite(end) || start < 0 || end > DAY_MS || end <= start)
    return null
  const allDay = ROUND_THE_CLOCK.has(code)
  // 00:00 to 23:59:59 is how the backend writes a day without a close.
  const window =
    start === 0 && end >= DAY_MS - 60_000
      ? '0000-0000'
      : `${hhmm(Math.floor(start / 60_000))}-${hhmm(Math.floor(end / 60_000))}`
  const exceptions: Record<string, string[]> = {}
  if (!allDay) {
    for (const h of holidays) {
      if (!/^\d{4}-\d{2}-\d{2}$/.test(h.date) || h.holiday_type === 'SETTLEMENT_HOLIDAY') continue
      const open = (h.open_exchanges ?? [])
        .filter((o) => o.exchange === code)
        .map((o) => sessionWindow(o.start_time, o.end_time, h.date))
        .filter((w): w is string => w !== null)
      // A special session lists the exchanges that open; the others stay
      // shut that day, as the backend's own timings answer it.
      if (open.length) exceptions[h.date] = open
      else if (h.closed_exchanges?.includes(code) || h.holiday_type === 'SPECIAL_SESSION')
        exceptions[h.date] = []
    }
  }
  return {
    timezone: ZONE,
    sessions: [allDay ? window : `${window}:23456`],
    exceptions,
    ...(PRE_OPEN_MINUTES[code] ? { preMarketMinutes: PRE_OPEN_MINUTES[code] } : {}),
  }
}

interface Book {
  day: string
  timings: TimingRow[] | null
  holidays: HolidayRow[] | null
  failedAt: number | null
  pending: Promise<void> | null
  calendars: Map<string, SessionCalendar | null>
}

let book: Book | null = null

async function getJson(url: string, init: RequestInit): Promise<unknown> {
  const abort = new AbortController()
  const timer = setTimeout(() => abort.abort(), TIMEOUT_MS)
  try {
    const res = await fetch(url, { ...init, credentials: 'same-origin', signal: abort.signal })
    const body = (await res.json()) as { status?: string; data?: unknown }
    if (!res.ok || body?.status !== 'success' || !Array.isArray(body.data))
      throw new Error(`${url} answered ${res.status}`)
    return body.data
  } finally {
    clearTimeout(timer)
  }
}

/** The years whose holidays the axis and a five-day range can reach from `day`. */
function yearsAround(day: string): number[] {
  const year = Number(day.slice(0, 4))
  const month = Number(day.slice(5, 7))
  return month === 1 ? [year - 1, year] : month === 12 ? [year, year + 1] : [year]
}

async function load(target: Book, apiKey: string): Promise<void> {
  try {
    const [timings, ...years] = await Promise.all([
      getJson('/admin/api/timings', {}),
      ...yearsAround(target.day).map((year) =>
        getJson('/api/v1/market/holidays', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ apikey: apiKey, year }),
        })
      ),
    ])
    target.timings = timings as TimingRow[]
    target.holidays = (years as HolidayRow[][]).flat()
    target.failedAt = null
  } catch {
    // No calendar is the chart as it always was; the next build tries again later.
    target.failedAt = Date.now()
  } finally {
    target.pending = null
  }
}

/** Today's book, fetching it when the day has turned or a failure has cooled off. */
function currentBook(apiKey: string, now = Date.now()): Book {
  const day = istClock(now).date
  if (!book || book.day !== day)
    book = {
      day,
      timings: null,
      holidays: null,
      failedAt: null,
      pending: null,
      calendars: new Map(),
    }
  const ready = book.timings !== null
  const cooling = book.failedAt !== null && now - book.failedAt < RETRY_AFTER_MS
  if (!ready && !book.pending && !cooling && apiKey) book.pending = load(book, apiKey)
  return book
}

function calendarOf(source: Book, exchange: string): SessionCalendar | null {
  if (source.timings === null || source.holidays === null) return null
  const cached = source.calendars.get(exchange)
  if (cached !== undefined) return cached
  let calendar: SessionCalendar | null = null
  try {
    const spec = calendarSpec(exchange, source.timings, source.holidays)
    calendar = spec ? new SessionCalendar(spec) : null
  } catch {
    calendar = null
  }
  source.calendars.set(exchange, calendar)
  return calendar
}

/**
 * Give a freshly built chart its exchange's hours and the session shading.
 * Synchronous when today's calendar is already here; otherwise the chart is
 * left as it is and gets its hours when they arrive, unless it has been
 * replaced or torn down by then.
 */
export function applySessionHours(chart: Chart, exchange: string, apiKey: string): void {
  if (!exchange) return
  // Hours are a refinement: whatever fails here, the chart draws as it did without them.
  try {
    attachSessionShading(chart)
  } catch {
    /* no shading on this chart */
  }
  const source = currentBook(apiKey)
  const apply = () => {
    try {
      const calendar = calendarOf(source, exchange)
      if (calendar && !chart.isDestroyed) chart.setSessionCalendar(calendar)
    } catch {
      /* no calendar on this chart */
    }
  }
  if (source.pending) void source.pending.then(apply)
  else apply()
}

/** Forget today's calendar. For tests. */
export function resetSessionHours(): void {
  book = null
}
