/**
 * What the platform knows about an instrument, in the shape the OpenScript
 * engine reads.
 *
 * The engine takes one record about the instrument a script runs on
 * (`Instrument` in openalgo-script, `host-interface.md` 4.1): tick size, lot
 * size, what kind of instrument it is, whether it reports volume and open
 * interest, the zone its clock is read in, and its trading session. Every
 * session fact a script reads (`session.isFirstBar`, `session.isLastBar`, the
 * bar `vwap` restarts on) is derived from that session and that zone and from
 * nothing else, so a chart that states neither gets all of them absent, with
 * nothing on screen to say why. The page cannot know any of this on its own;
 * `/openscript/instrument` answers it from the master contract and the market
 * calendar, whose timings an admin can edit.
 *
 * `symbol` and `interval` are left off, because the chart supplies both and a
 * second copy of either could only ever disagree with it.
 *
 * **Two ways in, because not every caller can wait.** `factsFor` is for code
 * that can await. `cachedFacts` is for code that cannot, such as a study being
 * built inside a synchronous chart callback: it answers from what is already
 * here, starts the request when nothing is, and `subscribeFacts` tells the
 * caller when the answer lands so it can build again with it.
 *
 * **A failure is an absence, never an exception.** A study with no instrument
 * facts still draws; its session facts are absent until they arrive. So a
 * failed request resolves to undefined and is tried again after a pause, rather
 * than throwing into a chart callback or being asked again on every repaint.
 *
 * **The regular window, and today's beside it.** The engine holds one session
 * for a whole run, so a day whose hours differ from the rest (Muhurat on a
 * Sunday evening, MCX trading an evening session on an equity holiday) cannot
 * be written into the record without moving every other day on the chart
 * outside it. The record carries the regular window, which is what history is
 * read against; `cachedToday` carries the calendar's window for today, for a
 * caller running live that has reason to prefer it.
 */

import type { Instrument } from 'openalgo-script'

/** The engine's record, less the two facts the chart supplies itself. */
export type InstrumentFacts = Omit<Instrument, 'symbol' | 'interval'>

/** The engine's session shape, taken off the record since the package does not export it. */
export type SessionHours = NonNullable<Instrument['session']>

/** The market calendar's window for one date. */
export interface TodayWindow {
  /** The date it describes, `YYYY-MM-DD` in the instrument's zone. */
  readonly date: string
  readonly open: boolean
  /** A special session or a holiday evening window rather than the regular hours. */
  readonly isSpecial: boolean
  /** That day's window, stated for that one weekday. Absent when the exchange is shut. */
  readonly session?: SessionHours
}

/** Told which instrument's facts have just arrived. */
export type FactsListener = (symbol: string, exchange: string) => void

/** How long a failed request is left before it is tried again. */
export const RETRY_AFTER_MS = 30_000

/** A request that has not answered by now is treated as failed, so it can be retried. */
const REQUEST_TIMEOUT_MS = 15_000

const URL_BASE = '/openscript/instrument'

/** `host-interface.md` 4.1: the seven words, and a host with none of them states nothing. */
const INSTRUMENT_TYPES = new Set([
  'equity',
  'future',
  'option',
  'index',
  'currency',
  'commodity',
  'other',
])

/** `"HH:MM"`, with `"24:00"` for midnight at the end of the day (4.3). */
const CLOCK = /^(?:[01]\d|2[0-3]):[0-5]\d$|^24:00$/

interface Entry {
  readonly facts: InstrumentFacts
  readonly today: TodayWindow | undefined
}

interface Identity {
  readonly key: string
  readonly symbol: string
  readonly exchange: string
}

type Writable<T> = { -readonly [K in keyof T]: T[K] }

const entries = new Map<string, Entry>()
const inflight = new Map<string, Promise<Entry | undefined>>()
const failedAt = new Map<string, number>()
const listeners = new Set<FactsListener>()

// Bumped by `clearInstrumentFacts`, so a request that was already out when the
// cache was cleared does not put its answer back afterwards.
let generation = 0

function identify(symbol: string, exchange: string): Identity | undefined {
  const s = symbol.trim()
  const x = exchange.trim().toUpperCase()
  if (!s || !x) return undefined
  // The case of a symbol is kept: the master contract holds "NIFTY Alpha 50".
  return { key: `${x}|${s}`, symbol: s, exchange: x }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function positive(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) && value > 0 ? value : undefined
}

/**
 * A session the engine will accept, or nothing.
 *
 * The engine refuses a malformed session at load (OS6012) rather than reading
 * it as absent, which would stop the whole study. Nothing is always the safer
 * answer here: the study draws, and only its session facts are missing.
 */
function parseSession(value: unknown): SessionHours | undefined {
  if (!isRecord(value)) return undefined
  const { start, end, days } = value
  if (typeof start !== 'string' || !CLOCK.test(start)) return undefined
  if (typeof end !== 'string' || !CLOCK.test(end)) return undefined
  if (days === undefined) return Object.freeze({ start, end })
  if (!Array.isArray(days) || days.length === 0) return undefined
  if (!days.every((day) => Number.isInteger(day) && day >= 1 && day <= 7)) return undefined
  return Object.freeze({ start, end, days: Object.freeze([...days] as number[]) })
}

function parseToday(value: unknown): TodayWindow | undefined {
  if (!isRecord(value)) return undefined
  if (typeof value.date !== 'string' || typeof value.open !== 'boolean') return undefined
  const session = parseSession(value.session)
  return Object.freeze({
    date: value.date,
    open: value.open,
    isSpecial: value.isSpecial === true,
    ...(session ? { session } : {}),
  })
}

/** The route's answer as an entry, or nothing when it is not one. */
function parseEntry(body: unknown): Entry | undefined {
  if (!isRecord(body) || body.status !== 'success' || !isRecord(body.instrument)) return undefined
  const raw = body.instrument
  // The one fact the engine requires of a host (4.2). An answer without it is
  // not an answer.
  if (typeof raw.hasVolume !== 'boolean') return undefined

  const facts: Writable<InstrumentFacts> = { hasVolume: raw.hasVolume }
  if (typeof raw.exchange === 'string' && raw.exchange) facts.exchange = raw.exchange
  if (typeof raw.timezone === 'string' && raw.timezone) facts.timezone = raw.timezone
  const tick = positive(raw.tickSize)
  if (tick !== undefined) facts.tickSize = tick
  const lot = positive(raw.lotSize)
  if (lot !== undefined) facts.lotSize = lot
  if (typeof raw.instrumentType === 'string' && INSTRUMENT_TYPES.has(raw.instrumentType)) {
    facts.instrumentType = raw.instrumentType
  }
  if (typeof raw.hasOpenInterest === 'boolean') facts.hasOpenInterest = raw.hasOpenInterest
  // A session is wall clock, so one with no zone to read it in is refused at
  // load. They travel together or the session stays behind.
  const session = parseSession(raw.session)
  if (session && facts.timezone) facts.session = session

  return { facts: Object.freeze(facts), today: parseToday(body.today) }
}

/** Today's date in a zone, `YYYY-MM-DD`, or nothing for a zone this browser cannot read. */
function dateIn(zone: string): string | undefined {
  try {
    const parts = new Intl.DateTimeFormat('en-US', {
      timeZone: zone,
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
    }).formatToParts(new Date())
    const part = (type: string) => parts.find((one) => one.type === type)?.value
    return `${part('year')}-${part('month')}-${part('day')}`
  } catch {
    return undefined
  }
}

/**
 * Whether the day an entry's `today` describes has ended.
 *
 * A chart left open overnight would otherwise go on offering yesterday's
 * window as today's. The regular facts do not change with the date, so a stale
 * entry keeps serving them while a fresh one is fetched.
 */
function isStale(entry: Entry): boolean {
  const zone = entry.facts.timezone
  if (!entry.today || !zone) return false
  const now = dateIn(zone)
  return now !== undefined && now !== entry.today.date
}

function mayRequest(key: string): boolean {
  if (inflight.has(key)) return false
  const at = failedAt.get(key)
  return at === undefined || Date.now() - at >= RETRY_AFTER_MS
}

function notify(symbol: string, exchange: string): void {
  for (const listener of [...listeners]) {
    try {
      listener(symbol, exchange)
    } catch {
      // One subscriber's failure is its own and must not keep the news from
      // the rest.
    }
  }
}

async function request(id: Identity): Promise<Entry | undefined> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS)
  try {
    const query = new URLSearchParams({ symbol: id.symbol, exchange: id.exchange })
    // JSON asked for explicitly, so an expired session answers 401 rather than
    // a redirect that fetch would follow into the login page's HTML.
    const response = await fetch(`${URL_BASE}?${query}`, {
      headers: { Accept: 'application/json' },
      signal: controller.signal,
    })
    if (!response.ok) return undefined
    return parseEntry(await response.json())
  } catch {
    return undefined
  } finally {
    clearTimeout(timer)
  }
}

/** One request per instrument at a time; every caller waiting on it shares it. */
function load(id: Identity): Promise<Entry | undefined> {
  const pending = inflight.get(id.key)
  if (pending) return pending

  const asked = generation
  const promise = request(id).then((entry) => {
    if (asked !== generation) return entry
    inflight.delete(id.key)
    if (entry) {
      entries.set(id.key, entry)
      failedAt.delete(id.key)
      notify(id.symbol, id.exchange)
    } else {
      failedAt.set(id.key, Date.now())
    }
    return entry
  })
  inflight.set(id.key, promise)
  return promise
}

/** Starts a request in the background when one is due, for the callers that cannot wait. */
function refresh(id: Identity): void {
  if (mayRequest(id.key)) void load(id)
}

/**
 * The facts for an instrument, once they are here.
 *
 * Resolves to undefined when they cannot be had, and never rejects. After a
 * failure it answers undefined without asking again until `RETRY_AFTER_MS` has
 * passed, so a chart repainting does not become a stream of requests.
 */
export function factsFor(symbol: string, exchange: string): Promise<InstrumentFacts | undefined> {
  const id = identify(symbol, exchange)
  if (!id) return Promise.resolve(undefined)
  const entry = entries.get(id.key)
  if (entry) {
    if (isStale(entry)) refresh(id)
    return Promise.resolve(entry.facts)
  }
  const pending = inflight.get(id.key)
  if (pending) return pending.then((found) => found?.facts)
  if (!mayRequest(id.key)) return Promise.resolve(undefined)
  return load(id).then((found) => found?.facts)
}

/**
 * The facts already here, for code that cannot await.
 *
 * Undefined when there are none yet, in which case the request is started (or
 * left running) and `subscribeFacts` announces the answer.
 */
export function cachedFacts(symbol: string, exchange: string): InstrumentFacts | undefined {
  const id = identify(symbol, exchange)
  if (!id) return undefined
  const entry = entries.get(id.key)
  if (!entry || isStale(entry)) refresh(id)
  return entry?.facts
}

/**
 * The calendar's window for today, when it is known and still today.
 *
 * Undefined for an exchange the calendar does not hold, and while a new day's
 * window is being fetched. A caller running live may prefer its `session` on a
 * day it is `isSpecial`; a caller drawing history should keep the regular one.
 */
export function cachedToday(symbol: string, exchange: string): TodayWindow | undefined {
  const id = identify(symbol, exchange)
  if (!id) return undefined
  const entry = entries.get(id.key)
  if (!entry || isStale(entry)) {
    refresh(id)
    return undefined
  }
  return entry.today
}

/** Hears about every instrument whose facts arrive. Returns the unsubscribe. */
export function subscribeFacts(listener: FactsListener): () => void {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

/** Forgets every answer and every failure, so the next read asks again. */
export function clearInstrumentFacts(): void {
  generation += 1
  entries.clear()
  inflight.clear()
  failedAt.clear()
}
