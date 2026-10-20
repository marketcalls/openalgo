/**
 * What a live card is made of, shared by both of them.
 *
 * Two cards stream: `live_quotes`, which is a set of instruments, and
 * `live_combo`, which is one number built out of several. They differ in what
 * they draw and agree on everything underneath, so everything underneath is
 * here. A third live card would add a renderer and nothing else.
 *
 * ## Honesty is the design constraint, not a feature of it
 *
 * A card that looks like it is streaming while showing a REST poll from two
 * minutes ago is worse than a card that says it is not connected, because the
 * operator may be about to trade on it. Three separate facts therefore travel
 * to the screen and none of them is inferred from another:
 *
 * - **Where the connection is.** `useMarketData` reports connected, paused and
 *   fallback, and `feedState` turns those into one word the header shows.
 * - **Where each value came from.** `SymbolData.updateSource` says whether the
 *   cache line was written by the WebSocket or by the REST poller, and
 *   `sourceOf` adds the third case the manager cannot report, which is that
 *   nothing has arrived at all and what is on screen is the snapshot the frame
 *   was served with. Every number that is not a tick is labelled, with its age.
 * - **Whether the market is even open.** The frame carries the session windows
 *   for every exchange on it, so this is recomputed against the clock rather
 *   than read off the verdict the backend reached when it drew the card. A
 *   message outlives the moment it was written and gets scrolled back to.
 *
 * ## Subscriptions are bounded on two axes, because a thread is long
 *
 * Every card holds subscriptions while it is mounted, and a conversation
 * mounts cards without limit. `useMarketData` already releases them on unmount
 * through its own effect cleanup, which is the path that must never fail; what
 * it cannot do is decide that a card nobody is looking at should not be
 * holding any.
 *
 * - **Off screen is off.** An `IntersectionObserver` disables the hook, which
 *   drops the subscriptions through the same cleanup as unmounting. Scrolling
 *   back re-subscribes and the manager replays its cache immediately.
 * - **Four cards stream at once, and the rest queue.** `BUDGET` is a plain
 *   FIFO with a fixed number of slots. A card without one renders its seeded
 *   snapshot, says so in as many words, and offers to take a slot from the
 *   card that has held one longest. Slots are released on unmount and handed
 *   straight to the next waiter.
 *
 * Neither bound is a substitute for the cleanup and neither is load bearing
 * for correctness. They exist so that ten cards in one thread is a small,
 * known number of subscriptions rather than a hundred and twenty.
 *
 * There is no second WebSocket client here and no second poller. Everything
 * goes through `useMarketData`, which goes through the one shared
 * `MarketDataManager` that the trading terminal, the option chain and the
 * scalping surface already share.
 */

import {
  type ReactNode,
  type RefObject,
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
} from 'react'
import { useMarketData } from '@/hooks/useMarketData'
import type { MarketData, SubscriptionMode, SymbolData } from '@/lib/MarketDataManager'
import { cn } from '@/lib/utils'
import { ago, type FeedState, TONE, type Tone } from './cards'
import { asNumber, asRecord, asText, nonZero } from './spec'

/** Cards that may hold subscriptions at the same time in one browser tab. */
export const MAX_LIVE_CARDS = 4

/** How long a changed value stays tinted. Long enough to catch, short enough to leave. */
const FLASH_MS = 700

/** Values a sparkline remembers. Bounded, so a card left open all day cannot grow. */
const SPARK_POINTS = 120

/** How often a mounted card re-reads the clock, for ages and session boundaries. */
const CLOCK_MS = 5000

/** Beyond this, a value on screen is old enough that the card stops calling it live. */
const STALE_MS = 60_000

/** Most notices shown under a card. */
const MAX_NOTICES = 4

// ---------------------------------------------------------------------------
// Reading the parts of a spec both cards carry
// ---------------------------------------------------------------------------

/** One instrument to subscribe to. */
export interface Pair {
  symbol: string
  exchange: string
}

/**
 * The nine field quote a frame seeds a row with.
 *
 * `ltp` is the one field kept at zero, because there the card has to be able
 * to tell "nothing has printed yet" from "no quote came back at all". Every
 * other zero is the feed spelling absence and is dropped on the way in.
 */
export interface Seed {
  ltp?: number
  open?: number
  high?: number
  low?: number
  prevClose?: number
  volume?: number
  bid?: number
  ask?: number
  oi?: number
}

/** One exchange's session, as the frame recorded it. */
export interface SessionRow {
  exchange: string
  known: boolean
  isOpen: boolean
  opensAt?: number
  closesAt?: number
}

/** Today's trading sessions for every exchange on a card. */
export interface Market {
  date?: string
  known: boolean
  exchanges: SessionRow[]
  isHoliday?: boolean
}

/**
 * Read one seeded quote.
 *
 * @param value - A `seed` object from a frame.
 * @returns The quote, or `null` when the frame carried none. An absent seed is
 *   not an empty one: it means no quote came back, which the row says out loud
 *   rather than drawing as a set of blanks.
 */
export function readSeed(value: unknown): Seed | null {
  const row = asRecord(value)
  if (!row) return null
  const ltp = asNumber(row.ltp)
  const seed: Seed = {
    open: nonZero(row.open),
    high: nonZero(row.high),
    low: nonZero(row.low),
    prevClose: nonZero(row.prev_close),
    volume: nonZero(row.volume),
    bid: nonZero(row.bid),
    ask: nonZero(row.ask),
    oi: nonZero(row.oi),
  }
  if (ltp !== null) seed.ltp = ltp
  return seed
}

/**
 * Read a list of `{symbol, exchange}` pairs.
 *
 * @param value - The frame's `subscribe` list, or any list shaped like it.
 * @returns The pairs, upper cased and de-duplicated. Anything unreadable is
 *   dropped: a subscription to a symbol that is not a symbol would never tick,
 *   and would sit on the card looking like it might.
 */
export function readPairs(value: unknown): Pair[] {
  if (!Array.isArray(value)) return []
  const pairs: Pair[] = []
  const seen = new Set<string>()
  for (const entry of value) {
    const row = asRecord(entry)
    if (!row) continue
    const symbol = asText(row.symbol)?.toUpperCase()
    const exchange = asText(row.exchange)?.toUpperCase()
    if (!symbol || !exchange) continue
    const key = `${exchange}:${symbol}`
    if (seen.has(key)) continue
    seen.add(key)
    pairs.push({ symbol, exchange })
  }
  return pairs
}

/**
 * Read the market block.
 *
 * @param value - The frame's `market`.
 * @returns The sessions. `known: false` on the block means the calendar could
 *   not be read, and a card in that state says nothing at all about the
 *   session rather than guessing that it is shut.
 */
export function readMarket(value: unknown): Market {
  const row = asRecord(value)
  if (!row) return { known: false, exchanges: [] }
  const rows: SessionRow[] = []
  if (Array.isArray(row.exchanges)) {
    for (const entry of row.exchanges) {
      const item = asRecord(entry)
      const exchange = item ? asText(item.exchange)?.toUpperCase() : null
      if (!item || !exchange) continue
      rows.push({
        exchange,
        known: item.known === true,
        isOpen: item.is_open === true,
        opensAt: asNumber(item.opens_at) ?? undefined,
        closesAt: asNumber(item.closes_at) ?? undefined,
      })
    }
  }
  return {
    date: asText(row.date) ?? undefined,
    known: row.known === true,
    exchanges: rows,
    isHoliday: typeof row.is_holiday === 'boolean' ? row.is_holiday : undefined,
  }
}

/**
 * Whether an exchange is open, right now rather than when the card was drawn.
 *
 * A card is read long after the turn that produced it, so `is_open` is only the
 * value at resolution and is never what the screen should be showing. The
 * window is what travels, and the window is what this reads.
 *
 * @param market - The frame's sessions.
 * @param exchange - The calendar exchange, already resolved by the backend.
 * @param now - The clock.
 * @returns True or false, or `null` when nobody knows: an unreadable calendar,
 *   or an exchange the block does not carry. Null is not "closed"; it is the
 *   card having nothing to say.
 */
export function openNow(market: Market, exchange: string, now: number): boolean | null {
  if (!market.known) return null
  const row = market.exchanges.find((entry) => entry.exchange === exchange)
  if (!row) return null
  // A session nobody published today is a day nothing trades on that venue.
  if (!row.known) return false
  if (row.opensAt !== undefined && row.closesAt !== undefined) {
    return now >= row.opensAt && now <= row.closesAt
  }
  return row.isOpen
}

/**
 * Whether anything on the card is trading.
 *
 * @param market - The frame's sessions.
 * @param exchanges - The calendar exchanges on the card.
 * @param now - The clock.
 * @returns True when at least one is open, false when all are shut, `null`
 *   when none of them is known.
 */
export function anyOpen(market: Market, exchanges: string[], now: number): boolean | null {
  let known = false
  for (const exchange of exchanges) {
    const open = openNow(market, exchange, now)
    if (open === null) continue
    known = true
    if (open) return true
  }
  return known ? false : null
}

// ---------------------------------------------------------------------------
// Where a number came from
// ---------------------------------------------------------------------------

/** Whether the value on screen is a tick, a poll, or the snapshot it opened with. */
export type ValueSource = 'tick' | 'poll' | 'seed'

/** The order these read as trustworthy, worst last. Used to grade a whole card. */
const SOURCE_RANK: Record<ValueSource, number> = { tick: 0, poll: 1, seed: 2 }

/**
 * How an instrument's numbers reached the screen.
 *
 * @param live - The manager's cache line for it, if any.
 * @returns `tick` only when the WebSocket actually delivered something for
 *   this instrument. A connected socket that has said nothing about this
 *   symbol is still `seed`, because the card is showing the served snapshot
 *   and saying otherwise is the lie this whole module is built to avoid.
 */
export function sourceOf(live: SymbolData | undefined): ValueSource {
  if (!live || live.lastUpdate === undefined) return 'seed'
  return live.updateSource === 'rest' ? 'poll' : 'tick'
}

/** The weakest source among several, which is all a derived number can claim. */
export function worstSource(sources: ValueSource[]): ValueSource {
  let worst: ValueSource = 'tick'
  for (const source of sources) {
    if (SOURCE_RANK[source] > SOURCE_RANK[worst]) worst = source
  }
  return worst
}

/**
 * The sentence under a value that says where it came from.
 *
 * @param source - What `sourceOf` decided.
 * @param age - Milliseconds since it arrived, when there is an arrival.
 * @param taken - When the served snapshot was taken, for the seed case.
 */
export function sourceLabel(source: ValueSource, age?: number, taken?: string | null): string {
  if (source === 'seed') return taken ? `snapshot ${taken}` : 'snapshot'
  const when = age === undefined ? '' : ` ${ago(age)}`
  return source === 'poll' ? `polled${when}` : `tick${when}`
}

// ---------------------------------------------------------------------------
// The budget
// ---------------------------------------------------------------------------

/**
 * How many cards may stream at once, and who is next when one stops.
 *
 * Module level and deliberately not React state: the thing being rationed is a
 * browser wide resource, the shared feed, so the count has to be shared by
 * every card in every thread on the page rather than by the ones under some
 * particular provider.
 *
 * FIFO in both directions. A card that arrives when the slots are full waits,
 * and the first waiter is served the moment a slot is released, which is what
 * makes scrolling through a thread work: the card leaving the viewport frees
 * the card entering it.
 */
class LiveBudget {
  private holders: string[] = []
  private queue: string[] = []
  private readonly listeners = new Map<string, (granted: boolean) => void>()

  /**
   * Ask for a slot.
   *
   * @param id - A stable id for the card, unique per mounted instance.
   * @param onChange - Called with the verdict now, and again whenever it
   *   changes.
   * @returns The release function. Calling it is not optional: a card that
   *   holds a slot after unmounting starves every card behind it.
   */
  claim(id: string, onChange: (granted: boolean) => void): () => void {
    this.listeners.set(id, onChange)
    if (this.holders.length < MAX_LIVE_CARDS) {
      this.holders.push(id)
      onChange(true)
    } else {
      this.queue.push(id)
      onChange(false)
    }
    return () => this.release(id)
  }

  /** Hand this card a slot, taking one from whoever has held it longest. */
  promote(id: string): void {
    if (this.holders.includes(id)) return
    const waiting = this.queue.indexOf(id)
    if (waiting < 0) return
    this.queue.splice(waiting, 1)
    if (this.holders.length >= MAX_LIVE_CARDS) {
      const evicted = this.holders.shift()
      if (evicted !== undefined) {
        this.queue.push(evicted)
        this.listeners.get(evicted)?.(false)
      }
    }
    this.holders.push(id)
    this.listeners.get(id)?.(true)
  }

  /** How many cards are streaming right now. */
  get streaming(): number {
    return this.holders.length
  }

  private release(id: string): void {
    this.listeners.delete(id)
    const held = this.holders.indexOf(id)
    if (held >= 0) {
      this.holders.splice(held, 1)
      this.fill()
      return
    }
    const waiting = this.queue.indexOf(id)
    if (waiting >= 0) this.queue.splice(waiting, 1)
  }

  private fill(): void {
    while (this.holders.length < MAX_LIVE_CARDS && this.queue.length > 0) {
      const next = this.queue.shift()
      if (next === undefined) return
      this.holders.push(next)
      this.listeners.get(next)?.(true)
    }
  }

  /** Test seam. Nothing in the application calls this. */
  reset(): void {
    this.holders = []
    this.queue = []
    this.listeners.clear()
  }
}

export const BUDGET = new LiveBudget()

// ---------------------------------------------------------------------------
// Hooks
// ---------------------------------------------------------------------------

/**
 * Whether an element is in or near the viewport.
 *
 * Starts true and can only be corrected downward, for two reasons. A real
 * observer reports the current state on its first callback, so a card that is
 * genuinely off screen is demoted within a frame; and where no observer exists
 * at all, which is every test environment and any browser too old for one, the
 * card streams rather than sitting mute forever.
 *
 * @param ref - The element to watch.
 */
export function useOnScreen(ref: RefObject<HTMLElement | null>): boolean {
  const [onScreen, setOnScreen] = useState(true)

  useEffect(() => {
    const node = ref.current
    if (!node || typeof IntersectionObserver === 'undefined') return
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) setOnScreen(entry.isIntersecting)
      },
      // A card just above or below the fold keeps its subscriptions, so a
      // small scroll does not churn the feed.
      { rootMargin: '250px 0px' }
    )
    observer.observe(node)
    return () => observer.disconnect()
  }, [ref])

  return onScreen
}

/**
 * Hold one of the streaming slots while `wanted` is true.
 *
 * @param wanted - Whether this card would stream if it could.
 * @returns Whether it may, and the action that takes a slot by force.
 */
export function useLiveSlot(wanted: boolean): { granted: boolean; take: () => void } {
  const id = useId()
  const [granted, setGranted] = useState(false)

  useEffect(() => {
    if (!wanted) {
      setGranted(false)
      return
    }
    return BUDGET.claim(id, setGranted)
  }, [id, wanted])

  const take = useCallback(() => BUDGET.promote(id), [id])
  return { granted, take }
}

/**
 * The clock, while a card is streaming.
 *
 * Ages and session boundaries both move without anything arriving, so a card
 * showing "tick 2s ago" needs a reason to re-render even when nothing has
 * ticked. One interval per streaming card, and none at all for the rest.
 *
 * @param active - Whether the card is streaming.
 */
export function useNow(active: boolean): number {
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    if (!active) return
    setNow(Date.now())
    const timer = setInterval(() => setNow(Date.now()), CLOCK_MS)
    return () => clearInterval(timer)
  }, [active])

  return now
}

/** What a card needs to know about its own subscription. */
export interface LiveFeed {
  /** The manager's cache, keyed `EXCHANGE:SYMBOL`. */
  data: Map<string, SymbolData>
  /** Whether this card is subscribed at all. */
  streaming: boolean
  /** Why it is not, when it is not: `offscreen` or `queued`. */
  held: 'offscreen' | 'queued' | null
  /** Take a streaming slot from the card that has held one longest. */
  take: () => void
  isConnected: boolean
  isPaused: boolean
  isFallbackMode: boolean
  /** Milliseconds, re-read every few seconds while streaming. */
  now: number
}

/**
 * Subscribe a card, for as long as it is on screen and holds a slot.
 *
 * @param ref - The card's own element, watched for visibility.
 * @param pairs - The instruments to subscribe to. Memoize this: it is the
 *   hook's identity for the subscription set.
 * @param mode - `LTP`, `Quote` or `Depth`, exactly as the frame asked for.
 * @returns Everything the card needs to render honestly.
 */
export function useLiveCard(
  ref: RefObject<HTMLElement | null>,
  pairs: Pair[],
  mode: SubscriptionMode
): LiveFeed {
  const onScreen = useOnScreen(ref)
  // A card with nothing to subscribe to never asks for a slot, so it cannot
  // starve one that would use it, and it must not report itself as held: there
  // is nothing being withheld from it.
  const wanted = pairs.length > 0
  const { granted, take } = useLiveSlot(onScreen && wanted)
  const streaming = onScreen && granted && wanted

  const { data, isConnected, isPaused, isFallbackMode } = useMarketData({
    symbols: pairs,
    mode,
    enabled: streaming,
  })

  const now = useNow(streaming)

  return {
    data,
    streaming,
    held: !wanted || streaming ? null : onScreen ? 'queued' : 'offscreen',
    take,
    isConnected,
    isPaused,
    isFallbackMode,
    now,
  }
}

/**
 * What the card's header says, from the connection and the calendar.
 *
 * The order is the order an operator would want to be told. Being unsubscribed
 * outranks everything, because nothing else on the card is moving either way.
 * A shut market outranks a quiet feed, because it explains it.
 *
 * @param feed - The subscription state.
 * @param open - Whether anything on the card is trading, or `null` when the
 *   calendar could not be read.
 * @param newest - Age of the freshest value on the card, when one has arrived.
 */
export function feedState(feed: LiveFeed, open: boolean | null, newest?: number): FeedState {
  if (!feed.streaming) return 'paused'
  if (feed.isPaused) return 'paused'
  if (feed.isFallbackMode) return 'polling'
  if (!feed.isConnected) return 'offline'
  if (open === false) return 'closed'
  if (newest === undefined) return 'waiting'
  return newest > STALE_MS ? 'delayed' : 'live'
}

// ---------------------------------------------------------------------------
// Pieces
// ---------------------------------------------------------------------------

/**
 * A number that tints when it changes.
 *
 * A card in a conversation is read, not watched, so a tick has to be visible
 * without anybody staring at the digits. The tint is a background rather than
 * a movement, it lasts less than a second, and it carries the direction so the
 * signal survives being seen out of the corner of an eye.
 *
 * The transition is `motion-safe:` only. A reader who has asked their system
 * for less motion still gets the tint, appearing and clearing at once instead
 * of fading, which is the part of this that is information rather than
 * decoration.
 */
export function Tick({
  value,
  children,
  className,
}: {
  /** The number behind the text. A change in this is what tints. */
  value: number | undefined
  /** The formatted value. */
  children: ReactNode
  className?: string
}) {
  const previous = useRef<number | undefined>(undefined)
  const [flash, setFlash] = useState<Tone | null>(null)

  useEffect(() => {
    const before = previous.current
    previous.current = value
    // The first value is not a change. Tinting on mount would make every card
    // flash its whole surface as it appeared.
    if (before === undefined || value === undefined || value === before) return
    setFlash(value > before ? 'up' : 'down')
    const timer = setTimeout(() => setFlash(null), FLASH_MS)
    return () => clearTimeout(timer)
  }, [value])

  return (
    <span
      className={cn(
        'rounded-sm motion-safe:transition-colors motion-safe:duration-500',
        flash === 'up' && 'bg-emerald-500/20',
        flash === 'down' && 'bg-red-500/20',
        className
      )}
    >
      {children}
    </span>
  )
}

/**
 * The shape of a number since the card was mounted.
 *
 * A combined value is a magnitude with no context: 41.85 is neither good nor
 * bad, and the operator cannot tell whether it has been sitting there or has
 * just fallen twenty points. The line is the cheapest way to answer that, and
 * it is honest about its own window, which starts when the card was drawn and
 * not when the session did.
 *
 * The buffer is capped, so a card left open through a whole session holds a
 * fixed amount of memory rather than a growing one.
 */
export function Sparkline({
  value,
  tone,
  className,
}: {
  value: number | null
  tone: Tone
  className?: string
}) {
  const [points, setPoints] = useState<number[]>([])

  useEffect(() => {
    if (value === null || !Number.isFinite(value)) return
    setPoints((previous) => {
      if (previous.length > 0 && previous[previous.length - 1] === value) return previous
      return [...previous, value].slice(-SPARK_POINTS)
    })
  }, [value])

  const path = useMemo(() => {
    if (points.length < 2) return null
    const low = Math.min(...points)
    const high = Math.max(...points)
    const span = high - low || 1
    const step = 100 / (points.length - 1)
    return points
      .map(
        (point, index) =>
          `${(index * step).toFixed(2)},${(24 - ((point - low) / span) * 22 - 1).toFixed(2)}`
      )
      .join(' ')
  }, [points])

  if (!path) {
    return (
      <span className={cn('text-[10px] text-muted-foreground', className)}>
        No movement yet since this card opened.
      </span>
    )
  }

  return (
    <svg
      className={cn('h-6 w-full', TONE[tone], className)}
      viewBox="0 0 100 24"
      preserveAspectRatio="none"
      role="img"
      aria-label={`${points.length} values seen since this card opened`}
    >
      <polyline
        points={path}
        fill="none"
        stroke="currentColor"
        strokeWidth="1.25"
        strokeLinejoin="round"
        strokeLinecap="round"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  )
}

/**
 * Where one value came from, said next to it.
 *
 * A tick is unremarkable and reads as ordinary text. Everything else is
 * amber, because everything else means the number beside it is not what the
 * feed is saying right now, and that is the one thing an operator must not
 * have to work out for themselves.
 */
export function Provenance({
  source,
  age,
  taken,
  className,
}: {
  source: ValueSource
  age?: number
  taken: string | null
  className?: string
}) {
  return (
    <span
      className={cn(
        'shrink-0 text-[10px] leading-4 tracking-wide uppercase',
        source === 'tick' ? 'text-muted-foreground' : 'text-amber-600 dark:text-amber-500',
        className
      )}
      title={
        source === 'seed'
          ? 'This is the snapshot the card was served with. Nothing has arrived on the feed yet.'
          : source === 'poll'
            ? 'The WebSocket is unavailable, so this came from a REST poll.'
            : 'Delivered by the market data WebSocket.'
      }
    >
      {sourceLabel(source, age, taken)}
    </span>
  )
}

/**
 * The sentence a card puts under its numbers.
 *
 * Every branch is a different thing for the operator to do, which is why this
 * is a sentence rather than the badge word repeated. A card that has stopped
 * moving must never read like one that is moving slowly.
 *
 * @param state - What the badge is showing.
 * @param what - What is being streamed, named so the sentence reads: "every
 *   instrument", "every leg".
 * @param newest - Age of the freshest value on the card, when one arrived.
 * @param taken - When the served snapshot was taken.
 * @param holiday - Whether the calendar called today a holiday.
 */
export function statusLine(
  state: FeedState,
  {
    what,
    newest,
    taken,
    holiday,
  }: { what: string; newest?: number; taken: string | null; holiday?: boolean }
): string {
  const served = taken ? `these are the ${taken} snapshot values` : 'these are the served values'
  switch (state) {
    case 'live':
      return newest === undefined
        ? `Streaming ${what}.`
        : `Streaming ${what}. Last update ${ago(newest)}.`
    case 'delayed':
      return `Connected, but the last update was ${ago(newest ?? 0)}.`
    case 'waiting':
      return `Subscribed to ${what}. Nothing has arrived yet, so ${served}.`
    case 'polling':
      return `The market data socket is unavailable, so ${what} comes from REST polls rather than ticks.${
        newest === undefined ? '' : ` Last poll ${ago(newest)}.`
      }`
    case 'offline':
      return `Not connected to the market data feed, so ${served} and nothing here is moving.`
    case 'closed':
      return `${holiday ? 'Market holiday' : 'Market closed'}, so ${served}.`
    default:
      return `Not streaming, so ${served}.`
  }
}

/**
 * Read the notices a card carries under it.
 *
 * @param value - The frame's `notices`.
 * @returns At most `MAX_NOTICES` of them. A card is a card, not a log: past a
 *   handful the reader stops reading and the important one is lost with the
 *   rest.
 */
export function readNotices(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  const notices: string[] = []
  for (const entry of value) {
    if (notices.length >= MAX_NOTICES) break
    const text = asText(entry)
    if (text) notices.push(text)
  }
  return notices
}

/**
 * The line under a card that explains why it is not streaming.
 *
 * A card that quietly stopped updating is the failure this whole file is
 * about, so a card that is deliberately not subscribed says so and offers the
 * way back.
 */
export function HeldNotice({ held, take }: { held: 'offscreen' | 'queued'; take: () => void }) {
  if (held === 'offscreen') {
    return (
      <p className="border-t border-border px-3 py-1.5 text-[11px] text-muted-foreground">
        Not streaming while off screen. Scroll it back into view to resume.
      </p>
    )
  }
  return (
    <p className="border-t border-border px-3 py-1.5 text-[11px] text-muted-foreground">
      Not streaming: {MAX_LIVE_CARDS} cards are already live in this tab, so this one is showing the
      snapshot it was served with.{' '}
      <button
        type="button"
        onClick={take}
        className="underline underline-offset-2 hover:text-foreground"
      >
        Stream this one instead
      </button>
      .
    </p>
  )
}

/** A card that could not be read at all. Never an exception, always a sentence. */
export function Unreadable({ label, what }: { label: string; what: string }) {
  return (
    <figure
      className="my-3 min-w-0 overflow-hidden rounded-lg border border-border bg-card"
      aria-label={label}
    >
      <p className="px-3 py-6 text-center text-[12px] text-muted-foreground">
        This {what} could not be drawn: the frame did not arrive in a shape this page can read.
      </p>
    </figure>
  )
}

// ---------------------------------------------------------------------------
// Merging a tick over a seed
// ---------------------------------------------------------------------------

/**
 * One instrument's numbers, with the live tick preferred over the snapshot.
 *
 * The `??` chain is `nonZero` first for every field but the last traded price,
 * for the reason spelled out in `spec.ts`: a tick that carries only a book
 * publishes zeros for the fields it has nothing to say about, and a served bid
 * replaced by one of those would render as `0.00` and take the spread with it.
 *
 * @param seed - The frame's snapshot for this instrument.
 * @param live - The manager's cache line, if anything has arrived.
 * @returns The numbers to draw. `undefined` throughout means absent, and an
 *   absent number is drawn as nothing rather than as zero.
 */
export function merged(seed: Seed | null, live: MarketData | undefined) {
  const ltp = nonZero(live?.ltp) ?? seed?.ltp
  const prevClose = nonZero(live?.close) ?? seed?.prevClose
  let change: number | undefined
  let changePercent: number | undefined
  // Derived from the price on screen rather than from the feed's own change
  // field, so the two can never disagree in front of the reader. A last price
  // of zero is nothing having printed, not a hundred percent fall.
  if (ltp !== undefined && ltp !== 0 && prevClose !== undefined && prevClose !== 0) {
    change = ltp - prevClose
    changePercent = (change / prevClose) * 100
  }
  return {
    ltp,
    prevClose,
    change,
    changePercent,
    open: nonZero(live?.open) ?? seed?.open,
    high: nonZero(live?.high) ?? seed?.high,
    low: nonZero(live?.low) ?? seed?.low,
    volume: nonZero(live?.volume) ?? seed?.volume,
    bid: nonZero(live?.bid_price) ?? nonZero(live?.depth?.buy?.[0]?.price) ?? seed?.bid,
    ask: nonZero(live?.ask_price) ?? nonZero(live?.depth?.sell?.[0]?.price) ?? seed?.ask,
    // Open interest is not carried on this platform's tick payload at all, so
    // it is the snapshot's or it is nothing.
    oi: seed?.oi,
  }
}
