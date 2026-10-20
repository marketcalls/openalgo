/**
 * A set of instruments, streaming, inside the conversation.
 *
 * The frame names the instruments and seeds them with one snapshot; the card
 * subscribes to exactly that set in exactly the mode the tool asked for and
 * lets the shared feed take over. Nothing here chooses an instrument, a mode
 * or a price: the model made a selection, a service produced the numbers, and
 * this file draws them.
 *
 * **Three modes, three shapes, because the feed delivers three things.** This
 * follows what `/websocket/test` shows each mode actually carries rather than
 * drawing an optimistic superset and leaving blanks where a mode has nothing
 * to say:
 *
 * - `LTP` is a row per instrument: price, change, change percent.
 * - `Quote` adds the session, open through previous close, plus volume and the
 *   top of book.
 * - `Depth` adds the ladder, both sides, with sizes. The backend caps a depth
 *   card at four instruments, because a book per instrument per tick is a very
 *   different amount of feed from a price.
 *
 * **What is live and what is not is written down, per instrument.** A row
 * showing the snapshot it was served with says `snapshot 22:44`; a row being
 * polled over REST says `polled 3s ago`; only a row the WebSocket has actually
 * delivered says `tick`. The header states the connection, and the session is
 * recomputed from the window the frame carried rather than trusted from the
 * verdict the backend reached when it drew the card, because a message gets
 * scrolled back to hours later.
 *
 * Everything shared with the combo card lives in `live.tsx`, and everything
 * shared with the instrument card lives in `cards.tsx` and `spec.ts`.
 */

import { useMemo, useRef } from 'react'
import type { SubscriptionMode } from '@/lib/MarketDataManager'
import { fmtPrice } from '@/lib/trading/format'
import { cn } from '@/lib/utils'
import {
  asOfLabel,
  Chip,
  compact,
  FeedBadge,
  percent,
  Stat,
  signed,
  TONE,
  toneOf,
  whole,
} from './cards'
import {
  anyOpen,
  feedState,
  HeldNotice,
  type Market,
  merged,
  type Pair,
  Provenance,
  readMarket,
  readNotices,
  readPairs,
  readSeed,
  type Seed,
  sourceOf,
  statusLine,
  Tick,
  Unreadable,
  useLiveCard,
} from './live'
import { asNumber, asRecord, asText, type DepthRow, nonZero, parseLevels } from './spec'

/** Most refused instruments named under a card. */
const MAX_REFUSED = 6

/** The three modes the proxy understands. Anything else is read as Quote. */
const MODES: SubscriptionMode[] = ['LTP', 'Quote', 'Depth']

// ---------------------------------------------------------------------------
// The spec
// ---------------------------------------------------------------------------

interface Book {
  bids: DepthRow[]
  asks: DepthRow[]
  totalBuy?: number
  totalSell?: number
}

interface Row {
  symbol: string
  exchange: string
  /** The session to look up, already resolved: NSE_INDEX becomes NSE. */
  calendarExchange: string
  isIndex: boolean
  isDerivative: boolean
  seed: Seed | null
  change?: number
  changePercent?: number
  depth?: Book
  /** Why a part of this row is missing, in the backend's own prose. */
  unavailable: Array<{ part: string; reason: string }>
}

interface Refused {
  symbol: string
  exchange: string
  reason: string
}

interface QuotesSpec {
  mode: SubscriptionMode
  currency: string
  analyze: boolean
  asOf?: string
  timezone?: string
  instruments: Row[]
  subscribe: Pair[]
  refused: Refused[]
  market: Market
  notices: string[]
}

/** How a missing part of a row is named, in the order the row draws them. */
const PART_NAMES: Record<string, string> = {
  seed: 'the opening quote',
  depth: 'the order book',
}

function readBook(value: unknown): Book | undefined {
  const row = asRecord(value)
  if (!row) return undefined
  const bids = parseLevels(row.bids)
  const asks = parseLevels(row.asks)
  if (bids.length === 0 && asks.length === 0) return undefined
  return {
    bids,
    asks,
    totalBuy: nonZero(row.total_buy_quantity),
    totalSell: nonZero(row.total_sell_quantity),
  }
}

function readUnavailable(value: unknown): Array<{ part: string; reason: string }> {
  const row = asRecord(value)
  if (!row) return []
  const parts: Array<{ part: string; reason: string }> = []
  for (const [key, reason] of Object.entries(row)) {
    const part = PART_NAMES[key]
    // A key this client has no name for is a newer backend describing a
    // section this build does not draw. Saying nothing is right.
    if (!part) continue
    parts.push({ part, reason: asText(reason) ?? 'the platform did not say why' })
  }
  return parts
}

function readRows(value: unknown): Row[] {
  if (!Array.isArray(value)) return []
  const rows: Row[] = []
  for (const entry of value) {
    const item = asRecord(entry)
    if (!item) continue
    const symbol = asText(item.symbol)?.toUpperCase()
    const exchange = asText(item.exchange)?.toUpperCase()
    if (!symbol || !exchange) continue
    rows.push({
      symbol,
      exchange,
      calendarExchange: asText(item.calendar_exchange)?.toUpperCase() ?? exchange,
      isIndex: item.is_index === true,
      isDerivative: item.is_derivative === true,
      seed: readSeed(item.seed),
      change: asNumber(item.change) ?? undefined,
      changePercent: asNumber(item.change_percent) ?? undefined,
      depth: readBook(item.depth),
      unavailable: readUnavailable(item.unavailable),
    })
  }
  return rows
}

function readRefused(value: unknown): Refused[] {
  if (!Array.isArray(value)) return []
  const refused: Refused[] = []
  for (const entry of value) {
    if (refused.length >= MAX_REFUSED) break
    const row = asRecord(entry)
    if (!row) continue
    const symbol = asText(row.symbol)
    if (!symbol) continue
    refused.push({
      symbol: symbol.toUpperCase(),
      exchange: asText(row.exchange)?.toUpperCase() ?? '',
      reason: asText(row.reason) ?? 'the platform did not say why',
    })
  }
  return refused
}

/**
 * Read a `kind: "live_quotes"` spec.
 *
 * @param value - The frame's `spec`, exactly as it came off the wire.
 * @returns The card, or `null` when the frame named no instrument. There is
 *   nothing to subscribe to in that case and nothing to draw, and a card that
 *   drew a header over an empty list would look like a feed that had gone
 *   quiet.
 */
function parseQuotesSpec(value: unknown): QuotesSpec | null {
  const root = asRecord(value)
  if (!root) return null
  const instruments = readRows(root.instruments)
  if (instruments.length === 0) return null
  const asked = asText(root.mode)
  const mode = MODES.find((entry) => entry === asked) ?? 'Quote'
  const subscribe = readPairs(root.subscribe)
  return {
    mode,
    currency: asText(root.currency) ?? 'INR',
    analyze: asText(root.account_mode)?.toLowerCase() === 'analyze',
    asOf: asText(root.as_of) ?? undefined,
    timezone: asText(root.timezone) ?? undefined,
    instruments,
    // The frame's own list is authoritative, but a frame that lost it must
    // still stream: the instruments are the same set by construction.
    subscribe: subscribe.length > 0 ? subscribe : readPairs(root.instruments),
    refused: readRefused(root.refused),
    market: readMarket(root.market),
    notices: readNotices(root.notices),
  }
}

// ---------------------------------------------------------------------------
// Pieces
// ---------------------------------------------------------------------------

/**
 * One side of a book.
 *
 * The bar behind each level is the size relative to the largest on that side,
 * which is how a book is read: the shape of the queue matters more than any
 * one number in it. Sizes are never shortened here, because a resting quantity
 * is a number an operator acts on.
 */
function Ladder({
  title,
  rows,
  total,
  tone,
  price,
}: {
  title: string
  rows: DepthRow[]
  total?: number
  tone: 'up' | 'down'
  price: (value: number) => string
}) {
  const largest = Math.max(1, ...rows.map((row) => row.quantity ?? 0))
  return (
    <div className="min-w-0">
      <div className="flex items-baseline justify-between gap-2 text-[10px] leading-4 tracking-wide text-muted-foreground uppercase">
        <span>{title}</span>
        {total !== undefined && <span className="truncate normal-case">{compact(total)}</span>}
      </div>
      {rows.length === 0 ? (
        <p className="mt-1 text-[11px] text-muted-foreground">No resting orders.</p>
      ) : (
        <table className="mt-1 w-full font-mono text-[11px] tabular-nums">
          <tbody>
            {rows.map((row, index) => (
              <tr key={`${row.price ?? 'x'}-${index}`} className="relative">
                <td className={cn('relative py-px text-left', TONE[tone])}>
                  <span
                    aria-hidden
                    className={cn(
                      'absolute inset-y-0 left-0 rounded-sm',
                      tone === 'up' ? 'bg-emerald-500/10' : 'bg-red-500/10'
                    )}
                    style={{ width: `${((row.quantity ?? 0) / largest) * 100}%` }}
                  />
                  <span className="relative">
                    {row.price === undefined ? '' : price(row.price)}
                  </span>
                </td>
                <td className="py-px text-right text-muted-foreground">
                  {row.quantity === undefined ? '' : whole(row.quantity)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// The component
// ---------------------------------------------------------------------------

export interface LiveQuotesCardProps {
  /**
   * The `spec` of a `kind: "live_quotes"` frame, unvalidated. Read defensively
   * here, so a malformed one renders a sentence rather than throwing.
   *
   * Pass the frame's own object: its identity is what keeps the parse and the
   * subscription set from being rebuilt on every streamed token.
   */
  spec: unknown
  /** The frame's `title`. Used only when the spec cannot be read. */
  title?: string
  /** The frame's `source`, reported to screen readers. */
  source?: string
  /** Extra classes on the card. */
  className?: string
}

/**
 * Draw one live quotes card.
 *
 * @param spec - The frame's `spec`.
 * @param title - The frame's `title`.
 * @param source - The frame's `source`.
 * @param className - Extra classes on the card.
 */
export function LiveQuotesCard({ spec, title, source, className }: LiveQuotesCardProps) {
  const parsed = useMemo(() => parseQuotesSpec(spec), [spec])
  const host = useRef<HTMLElement | null>(null)

  // Hooks run whatever the spec turned out to be, so an unreadable frame
  // subscribes to nothing and the budget is never charged for it.
  const pairs = useMemo(() => parsed?.subscribe ?? [], [parsed])
  const feed = useLiveCard(host, pairs, parsed?.mode ?? 'Quote')

  const open = useMemo(
    () =>
      parsed
        ? anyOpen(
            parsed.market,
            parsed.instruments.map((row) => row.calendarExchange),
            feed.now
          )
        : null,
    [parsed, feed.now]
  )

  if (!parsed) {
    return <Unreadable label={asText(title) ?? 'Live quotes'} what="live card" />
  }

  const taken = asOfLabel(parsed.asOf, parsed.timezone)
  const clock = feed.now

  // Every row is resolved before anything is drawn, because the header's own
  // state depends on the freshest value anywhere on the card.
  const rows = parsed.instruments.map((row) => {
    const live = feed.data.get(`${row.exchange}:${row.symbol}`)
    const values = merged(row.seed, live?.data)
    const rowSource = sourceOf(live)
    const age = live?.lastUpdate === undefined ? undefined : Math.max(0, clock - live.lastUpdate)
    const liveBids = parseLevels(live?.data.depth?.buy)
    const liveAsks = parseLevels(live?.data.depth?.sell)
    const fromFeed = liveBids.length > 0 || liveAsks.length > 0
    return {
      row,
      values,
      source: rowSource,
      age,
      bids: fromFeed ? liveBids : (row.depth?.bids ?? []),
      asks: fromFeed ? liveAsks : (row.depth?.asks ?? []),
      // The totals came with the served ladder and the feed publishes none, so
      // they are shown only beside the levels they were counted with.
      totalBuy: fromFeed ? undefined : row.depth?.totalBuy,
      totalSell: fromFeed ? undefined : row.depth?.totalSell,
      // A change the card derived from what is on screen beats the served one,
      // so the price and its move can never disagree.
      change: values.change ?? row.change,
      changePercent: values.changePercent ?? row.changePercent,
    }
  })

  const ages = rows
    .map((entry) => entry.age)
    .filter((value): value is number => value !== undefined)
  const newest = ages.length > 0 ? Math.min(...ages) : undefined
  const state = feedState(feed, open, newest)

  const label = [
    `Live ${parsed.mode} card`,
    `${rows.length} instrument${rows.length === 1 ? '' : 's'}`,
    source ? `data from ${source}` : null,
  ]
    .filter((part): part is string => Boolean(part))
    .join(', ')

  return (
    <figure
      ref={host}
      className={cn(
        'my-3 min-w-0 overflow-hidden rounded-lg border border-border bg-card',
        className
      )}
      aria-label={label}
    >
      {/* Header */}
      <div className="flex items-start gap-2 px-3 pt-2.5 pb-2">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-[13px] font-semibold text-foreground">Live {parsed.mode}</span>
            <Chip>{`${rows.length} instrument${rows.length === 1 ? '' : 's'}`}</Chip>
            {parsed.analyze && (
              <Chip className="border-amber-500/40 text-amber-600 dark:text-amber-400">
                Analyze
              </Chip>
            )}
          </div>
          <p className="mt-0.5 text-[11px] text-muted-foreground">
            {statusLine(state, {
              what: 'every instrument',
              newest,
              taken,
              holiday: parsed.market.isHoliday,
            })}
          </p>
        </div>
        <FeedBadge state={state} />
      </div>

      {/* Instruments */}
      <ul className="divide-y divide-border/60 border-t border-border">
        {rows.map((entry) => {
          const { row, values } = entry
          const price = (value: number) => fmtPrice(value, undefined, values.ltp ?? value)
          const tone = toneOf(entry.change)
          const hasLadder = entry.bids.length > 0 || entry.asks.length > 0
          return (
            <li key={`${row.exchange}:${row.symbol}`} className="px-3 py-2">
              {/* The row every mode draws */}
              <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
                <span className="font-mono text-[12px] font-semibold text-foreground">
                  {row.symbol}
                </span>
                <Chip>{row.exchange}</Chip>
                <span className="ml-auto font-mono text-[15px] leading-none font-semibold tabular-nums text-foreground">
                  {values.ltp === undefined ? (
                    <span className="text-[12px] font-normal text-muted-foreground">
                      No price yet
                    </span>
                  ) : values.ltp === 0 ? (
                    <span
                      className="text-[12px] font-normal text-muted-foreground"
                      title="The last traded price is zero, so nothing has printed on this instrument yet."
                    >
                      No trade yet
                    </span>
                  ) : (
                    <Tick value={values.ltp} className="px-1">
                      {price(values.ltp)}
                    </Tick>
                  )}
                </span>
                {entry.change !== undefined && (
                  <span
                    className={cn('font-mono text-[12px] font-medium tabular-nums', TONE[tone])}
                  >
                    <Tick value={entry.change} className="px-1">
                      {signed(entry.change)}
                      {entry.changePercent !== undefined && ` (${percent(entry.changePercent)})`}
                    </Tick>
                  </span>
                )}
              </div>

              <div className="mt-1 flex flex-wrap items-baseline gap-x-2 gap-y-1">
                <Provenance source={entry.source} age={entry.age} taken={taken} />
                {row.unavailable.map((part) => (
                  <span key={part.part} className="text-[10px] text-muted-foreground">
                    Could not read {part.part}: {part.reason}
                  </span>
                ))}
              </div>

              {/* Quote and Depth both carry the session. LTP does not. */}
              {parsed.mode !== 'LTP' && (
                <div className="mt-2 grid grid-cols-2 gap-x-3 gap-y-2 sm:grid-cols-4">
                  {values.open !== undefined && <Stat label="Open" value={price(values.open)} />}
                  {values.high !== undefined && (
                    <Stat
                      label="High"
                      value={<Tick value={values.high}>{price(values.high)}</Tick>}
                    />
                  )}
                  {values.low !== undefined && (
                    <Stat label="Low" value={<Tick value={values.low}>{price(values.low)}</Tick>} />
                  )}
                  {values.prevClose !== undefined && (
                    <Stat label="Prev close" value={price(values.prevClose)} />
                  )}
                  {values.volume !== undefined && (
                    <Stat
                      label="Volume"
                      value={<Tick value={values.volume}>{compact(values.volume)}</Tick>}
                    />
                  )}
                  {values.bid !== undefined && (
                    <Stat
                      label="Bid"
                      value={<Tick value={values.bid}>{price(values.bid)}</Tick>}
                      className={TONE.up}
                    />
                  )}
                  {values.ask !== undefined && (
                    <Stat
                      label="Ask"
                      value={<Tick value={values.ask}>{price(values.ask)}</Tick>}
                      className={TONE.down}
                    />
                  )}
                  {row.isDerivative && values.oi !== undefined && (
                    <Stat label="Open interest" value={compact(values.oi)} />
                  )}
                </div>
              )}

              {/* The book, only where one exists and only in Depth mode. */}
              {parsed.mode === 'Depth' && !row.isIndex && hasLadder && (
                <div className="mt-2 grid grid-cols-2 gap-x-4">
                  <Ladder
                    title="Bids"
                    rows={entry.bids}
                    total={entry.totalBuy}
                    tone="up"
                    price={price}
                  />
                  <Ladder
                    title="Asks"
                    rows={entry.asks}
                    total={entry.totalSell}
                    tone="down"
                    price={price}
                  />
                </div>
              )}
            </li>
          )
        })}
      </ul>

      {/*
        Instruments the backend resolved against the master and rejected. These
        were never subscribed, so a card that simply left them out would read
        as though the operator had not asked for them.
      */}
      {parsed.refused.length > 0 && (
        <div className="border-t border-border px-3 py-1.5">
          {parsed.refused.map((entry) => (
            <p
              key={`${entry.exchange}:${entry.symbol}`}
              className="text-[11px] text-muted-foreground"
            >
              {entry.symbol}
              {entry.exchange ? ` on ${entry.exchange}` : ''} is not on this card: {entry.reason}
            </p>
          ))}
        </div>
      )}

      {feed.held && <HeldNotice held={feed.held} take={feed.take} />}

      {parsed.notices.map((notice) => (
        <p
          key={notice}
          className="border-t border-border px-3 py-1.5 text-[11px] text-muted-foreground"
        >
          {notice}
        </p>
      ))}
    </figure>
  )
}
