/**
 * The vocabulary every card in the conversation is written in.
 *
 * Three cards now draw market data inline in a thread: the instrument card, the
 * live quotes card and the live combo card. They ask the same questions of a
 * number over and over. Is it up or down. How is a rupee value written so it
 * groups the Indian way and never rounds paise into nothing. How is a nine
 * digit volume written in a tile a quarter of a narrow chat column wide. How
 * is the moment a snapshot was taken printed so it reads the same on every
 * operating system. What does the feed indicator say.
 *
 * Each of those answers is one function, and each of them was already written
 * once. A second copy is how two cards in the same thread end up disagreeing
 * about what `-1,250.50` means, and the copy that goes wrong is the one nobody
 * is looking at. So they live here and every card imports them.
 *
 * Two rules are encoded rather than merely followed:
 *
 * - **A size an operator would type is never shortened.** `compact` exists for
 *   volume and open interest, which are read, not typed. A position size, a
 *   lot, a resting order quantity all go through `whole`, because rounding a
 *   number somebody is about to put in an order ticket is not a formatting
 *   decision.
 * - **The feed indicator names a state, it does not imply one.** Every entry in
 *   `FEED` is a sentence a reader can act on, and the only one that pulses is
 *   the one where numbers are actually arriving. It pulses under
 *   `motion-safe:` alone, so a reader who has asked their system for less
 *   motion gets the colour without the animation.
 */

import type { ReactNode } from 'react'
import { groupIndian, money } from '@/lib/trading/format'
import { cn } from '@/lib/utils'

/** Up, down and neither, in the two themes. */
export const TONE = {
  up: 'text-emerald-600 dark:text-emerald-500',
  down: 'text-red-600 dark:text-red-400',
  flat: 'text-muted-foreground',
} as const

export type Tone = keyof typeof TONE

/** Which way a number moved. Zero and unknown are both neither. */
export function toneOf(value: number | undefined): Tone {
  if (value === undefined || value === 0) return 'flat'
  return value > 0 ? 'up' : 'down'
}

/**
 * What a card's header says about where its numbers are coming from.
 *
 * The states are deliberately more than "live or not". A card showing a REST
 * poll from two minutes ago while looking exactly like one taking ticks is the
 * failure these cards exist to avoid, and so is a card that looks broken when
 * the only thing that happened is that the market shut. Each of these is a
 * different thing for the operator to do about it: wait, reconnect, scroll
 * back, or nothing at all.
 */
export const FEED = {
  /** The socket is up, the session is open, and ticks are arriving. */
  live: { dot: 'motion-safe:animate-pulse bg-emerald-500', label: 'Live' },
  /** The socket failed and the manager is polling the REST snapshot instead. */
  polling: { dot: 'bg-sky-500', label: 'Polling' },
  /** Connected and open, but this card has not been sent a tick yet. */
  waiting: { dot: 'bg-amber-500', label: 'Waiting' },
  /** Connected, but the numbers on screen are older than the feed's cadence. */
  delayed: { dot: 'bg-amber-500', label: 'Delayed' },
  /** Subscriptions released on purpose: the tab is hidden, or the card is not. */
  paused: { dot: 'bg-amber-500', label: 'Paused' },
  /** No socket. Nothing on screen is going to move. */
  offline: { dot: 'bg-red-500', label: 'Not connected' },
  /** The session is shut. The last price is the closing one and that is fine. */
  closed: { dot: 'bg-muted-foreground/50', label: 'Closed' },
} as const

export type FeedState = keyof typeof FEED

/**
 * The feed indicator, as a dot and a word.
 *
 * @param state - Which state the card is in.
 * @param className - Extra classes, for a header that needs its own spacing.
 */
export function FeedBadge({ state, className }: { state: FeedState; className?: string }) {
  return (
    <span
      className={cn(
        'flex shrink-0 items-center gap-1.5 text-[10px] leading-4 tracking-wide text-muted-foreground uppercase',
        className
      )}
    >
      <span aria-hidden className={cn('h-1.5 w-1.5 rounded-full', FEED[state].dot)} />
      {FEED[state].label}
    </span>
  )
}

/**
 * A change or a result, with its sign in front of it.
 *
 * `money` supplies the magnitude, so a four figure profit is grouped the same
 * way every other rupee value in this product is and never rounds paise away.
 */
export function signed(value: number): string {
  if (value === 0) return money(0)
  return `${value > 0 ? '+' : '-'}${money(value)}`
}

/** A percentage, magnitude only. The sign travels with the number beside it. */
export function percent(value: number, digits = 2): string {
  return `${Math.abs(value).toFixed(digits)}%`
}

/** A whole number, grouped the Indian way, sign kept. */
export function whole(value: number): string {
  const sign = value < 0 ? '-' : ''
  return `${sign}${groupIndian(Math.round(Math.abs(value)).toString())}`
}

/**
 * A size, shortened once grouping stops being readable.
 *
 * Volume runs to nine digits on a liquid stock, and `12,34,56,789` in a tile
 * that is a quarter of a narrow chat column wraps or truncates. Lakh and crore
 * are what the exchange, the broker and the operator all use.
 */
export function compact(value: number): string {
  const sign = value < 0 ? '-' : ''
  const size = Math.abs(value)
  if (size >= 1e7) return `${sign}${(size / 1e7).toFixed(2)} Cr`
  if (size >= 1e5) return `${sign}${(size / 1e5).toFixed(2)} L`
  return whole(value)
}

/** A number as written, grouped when it is whole and left alone when it is not. */
export function plain(value: number): string {
  return Number.isInteger(value) ? whole(value) : String(value)
}

/**
 * When a served value was taken, as a fixed string.
 *
 * Sliced out of the ISO timestamp rather than run through `Intl`, for the
 * reason `lib/trading/format.ts` gives: 'en-IN' data varies across operating
 * systems and browsers, and the offset in the string is already IST.
 *
 * @param asOf - An ISO 8601 timestamp with an offset.
 * @param timezone - The zone the backend named, so IST is only claimed when it
 *   is IST.
 * @returns The moment, or `null` when the timestamp cannot be read.
 */
export function asOfLabel(asOf: string | undefined, timezone: string | undefined): string | null {
  if (!asOf || asOf.length < 16) return null
  const date = asOf.slice(0, 10)
  const time = asOf.slice(11, 16)
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date) || !/^\d{2}:\d{2}$/.test(time)) return null
  return `${date} ${time}${timezone === 'Asia/Kolkata' ? ' IST' : ''}`
}

/** Just the clock part of an ISO timestamp, for a line that already has a date. */
export function clockLabel(asOf: string | undefined): string | null {
  if (!asOf || asOf.length < 16) return null
  const time = asOf.slice(11, 16)
  return /^\d{2}:\d{2}$/.test(time) ? time : null
}

/**
 * How long ago something happened, in the coarsest unit that is still true.
 *
 * @param ms - Age in milliseconds.
 * @returns A phrase, never a precision the age does not have.
 */
export function ago(ms: number): string {
  const seconds = Math.max(0, Math.round(ms / 1000))
  if (seconds < 60) return `${seconds}s ago`
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  return `${Math.round(minutes / 60)}h ago`
}

/** A small bordered label: an exchange code, an instrument type, a side. */
export function Chip({ children, className }: { children: string; className?: string }) {
  return (
    <span
      className={cn(
        'rounded border border-border px-1.5 py-px text-[10px] leading-4 font-medium tracking-wide text-muted-foreground uppercase',
        className
      )}
    >
      {children}
    </span>
  )
}

/** One labelled number in a grid of them. */
export function Stat({
  label,
  value,
  className,
}: {
  label: string
  value: ReactNode
  className?: string
}) {
  return (
    <div className="min-w-0">
      <div className="text-[10px] leading-4 tracking-wide text-muted-foreground uppercase">
        {label}
      </div>
      <div className={cn('truncate font-mono text-[12px] tabular-nums text-foreground', className)}>
        {value}
      </div>
    </div>
  )
}
