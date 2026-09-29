/**
 * One instrument, the way a broker terminal can show it.
 *
 * The reference for this card is a general-purpose answer engine's stock card,
 * and the thing worth copying from it was not the layout. It was the sentence
 * printed immediately above it: use your broker terminal for exact intraday
 * levels and volume. OpenAlgo **is** the broker terminal, so this card carries
 * the numbers that card had to disclaim, and adds the two a broker session is
 * the only thing that knows: the resting order book, and whether the operator
 * is holding this instrument right now.
 *
 * Four decisions shape everything below.
 *
 * **It is seeded, then it is live.** The frame arrives complete and the card
 * paints every value from it on the first render, before a socket has said
 * anything. `useLiveQuote` then takes over on top, exactly as it does for the
 * trading surfaces, and each field prefers the live value only when there is
 * one. This ordering is the whole point: a message can be scrolled to an hour
 * after the turn that produced it, and it has to read correctly then as well
 * as now. A card that renders empty and fills in later is worse than one that
 * renders what was served.
 *
 * **When it is not live it says so.** A price that stopped ticking at 15:30
 * shown in the same style as one ticking now is the failure this card exists
 * to avoid, so the header carries the state and the price carries the time it
 * was taken whenever the market is not open and delivering.
 *
 * **There are no fundamentals, and there is no placeholder for them.** OpenAlgo
 * has no fundamentals source: no P/E, no market capitalisation, no EPS, no
 * dividend yield, no company profile. Four tiles of the reference card have no
 * equivalent here and are simply absent. An empty tile or a dash invites
 * somebody to fill it, and a number a model remembered is indistinguishable, to
 * a reader, from one the broker returned.
 *
 * **The order controls place nothing.** Buy and Sell write a plain-language
 * request into the composer and stop. The order then travels the ordinary path
 * and pauses at the same human approval gate as every other order in this
 * product. Wiring a button to an order tool would be the single most dangerous
 * thing in this feature, so the channel these use (`lib/agent/composer.ts`) is
 * incapable of sending: it carries a string to a textarea. Where no composer is
 * mounted the controls are not rendered at all.
 *
 * The chart is `CandleViz` in its inline variant, which is the same
 * `openalgo-charts` instance the `/trading` terminal and the agent's own
 * `candles` frames draw with. No second driver of the engine exists for this
 * card, and no third charting stack was introduced for it.
 *
 * Every section below the quote is optional and the card is correct with only
 * the quote present. The spec is read defensively, because it is JSON off the
 * wire: a malformed one renders a sentence, never an exception.
 *
 * How a number is read off the wire lives in `spec.ts` and how it is written
 * on screen lives in `cards.tsx`, because the two live cards ask exactly the
 * same questions and a second copy of the answers is how two cards in one
 * thread end up disagreeing about what a value means.
 */

import type { Bar } from 'openalgo-charts'
import { useCallback, useMemo } from 'react'
import { Button } from '@/components/ui/button'
import { useLiveQuote } from '@/hooks/useLiveQuote'
import { useMarketStatus } from '@/hooks/useMarketStatus'
import { prefillComposer, useComposerPrefill } from '@/lib/agent/composer'
import { fmtPrice } from '@/lib/trading/format'
import { cn } from '@/lib/utils'
import { CandleViz } from './CandleViz'
import {
  asOfLabel,
  Chip,
  compact,
  FeedBadge,
  type FeedState,
  percent,
  plain,
  Stat,
  signed,
  TONE,
  type Tone,
  toneOf,
  whole,
} from './cards'
import { asNumber, asRecord, asText, type DepthRow, nonZero, parseBars, parseLevels } from './spec'

/** Most position legs listed before the rest are dropped. */
const MAX_LEGS = 6

/** Most notices shown under the card. */
const MAX_NOTICES = 4

/**
 * How a section that could not be read is named under the card.
 *
 * The frame's `unavailable` mapping is keyed by the spec's own section names,
 * and an entry in it is the difference between a section that had nothing to
 * say and one nobody could read. That distinction matters most for the
 * position: `{held: false}` is the book answering that the operator holds
 * nothing, while a missing section with a reason here is nobody knowing, and
 * drawing both as an empty space would tell an operator they are flat while
 * their broker holds the position. A key this map does not carry is a newer
 * backend naming a section this client has no renderer for, and is skipped.
 */
const SECTION_NAMES: Record<string, string> = {
  instrument: 'the instrument details',
  intraday: 'the intraday chart',
  week_52: 'the 52 week range',
  depth: 'the order book',
  position: 'your position',
}

// ---------------------------------------------------------------------------
// The spec
// ---------------------------------------------------------------------------

interface Quote {
  ltp: number
  open?: number
  high?: number
  low?: number
  prevClose?: number
  volume?: number
  bid?: number
  ask?: number
  oi?: number
}

interface Details {
  name?: string
  instrumentType?: string
  expiry?: string
  strike?: number
  lotSize?: number
  tickSize?: number
}

interface Intraday {
  interval: string
  bars: Bar[]
  barsOmitted?: number
}

interface Week52 {
  high: number
  low: number
  fullYear: boolean
  firstDate?: string
  highDate?: string
  lowDate?: string
}

/** One section the platform could not read, and why. */
interface Missing {
  name: string
  reason: string
}

interface Depth {
  bids: DepthRow[]
  asks: DepthRow[]
  totalBuyQuantity?: number
  totalSellQuantity?: number
}

interface Leg {
  product?: string
  quantity?: number
  averagePrice?: number
  pnl?: number
}

interface Position {
  held: boolean
  legs: Leg[]
  quantity?: number
  side?: string
  pnl?: number
  averagePrice?: number
  pnlPercent?: number
}

interface InstrumentSpec {
  symbol: string
  exchange: string
  currency: string
  analyze: boolean
  asOf?: string
  timezone?: string
  isDerivative: boolean
  isIndex: boolean
  quote: Quote
  change?: number
  changePercent?: number
  details?: Details
  intraday?: Intraday
  week52?: Week52
  depth?: Depth
  position?: Position
  missing: Missing[]
  notices: string[]
}

function parseQuote(value: unknown): Quote | null {
  const row = asRecord(value)
  if (!row) return null
  const ltp = nonZero(row.ltp)
  // No last price means no card. Every other field is optional.
  if (ltp === undefined) return null
  return {
    ltp,
    open: nonZero(row.open),
    high: nonZero(row.high),
    low: nonZero(row.low),
    prevClose: nonZero(row.prev_close),
    volume: nonZero(row.volume),
    bid: nonZero(row.bid),
    ask: nonZero(row.ask),
    oi: nonZero(row.oi),
  }
}

function parseDetails(value: unknown): Details | undefined {
  const row = asRecord(value)
  if (!row) return undefined
  const details: Details = {
    name: asText(row.name) ?? undefined,
    instrumentType: asText(row.instrument_type)?.toUpperCase() ?? undefined,
    expiry: asText(row.expiry) ?? undefined,
    strike: nonZero(row.strike),
    lotSize: nonZero(row.lot_size),
    tickSize: nonZero(row.tick_size),
  }
  return Object.values(details).some((entry) => entry !== undefined) ? details : undefined
}

function parseIntraday(value: unknown): Intraday | undefined {
  const row = asRecord(value)
  if (!row) return undefined
  const bars = parseBars(row.bars)
  if (bars.length === 0) return undefined
  return {
    interval: asText(row.interval) ?? '',
    bars,
    barsOmitted: nonZero(row.bars_omitted),
  }
}

function parseWeek52(value: unknown): Week52 | undefined {
  const row = asRecord(value)
  if (!row) return undefined
  const high = nonZero(row.high)
  const low = nonZero(row.low)
  if (high === undefined || low === undefined || high <= low) return undefined
  return {
    high,
    low,
    // Absent means unknown, and an unknown window must not be labelled a year.
    fullYear: row.full_year === true,
    firstDate: asText(row.first_date) ?? undefined,
    highDate: asText(row.high_date) ?? undefined,
    lowDate: asText(row.low_date) ?? undefined,
  }
}

function parseDepth(value: unknown): Depth | undefined {
  const row = asRecord(value)
  if (!row) return undefined
  const bids = parseLevels(row.bids)
  const asks = parseLevels(row.asks)
  const totalBuyQuantity = nonZero(row.total_buy_quantity)
  const totalSellQuantity = nonZero(row.total_sell_quantity)
  if (bids.length === 0 && asks.length === 0 && totalBuyQuantity === undefined) return undefined
  return { bids, asks, totalBuyQuantity, totalSellQuantity }
}

function parseLegs(value: unknown): Leg[] {
  if (!Array.isArray(value)) return []
  const legs: Leg[] = []
  for (const entry of value) {
    if (legs.length >= MAX_LEGS) break
    const row = asRecord(entry)
    if (!row) continue
    legs.push({
      product: asText(row.product)?.toUpperCase() ?? undefined,
      quantity: nonZero(row.quantity),
      averagePrice: nonZero(row.average_price),
      pnl: asNumber(row.pnl) ?? undefined,
    })
  }
  return legs
}

function parsePosition(value: unknown): Position | undefined {
  const row = asRecord(value)
  if (!row) return undefined
  // `{held: false}` is the book answering that nothing is held, and a section
  // that is absent altogether is nobody knowing. Both render nothing, which is
  // the one thing they have in common: neither is an invitation to draw a zero.
  if (row.held !== true) return undefined
  const side = asText(row.side)?.toLowerCase()
  return {
    held: true,
    legs: parseLegs(row.legs),
    quantity: nonZero(row.quantity),
    side: side === 'long' || side === 'short' ? side : undefined,
    pnl: asNumber(row.pnl) ?? undefined,
    averagePrice: nonZero(row.average_price),
    pnlPercent: asNumber(row.pnl_percent) ?? undefined,
  }
}

/**
 * Read the sections that could not be gathered.
 *
 * @param value - The spec's `unavailable` mapping, section name to reason.
 * @param isIndex - Whether the instrument is an index. An index has no order
 *   book at all, so its absence is a fact about the instrument rather than
 *   something that went wrong, and saying so under every index card would be
 *   noise where the point of this list is to be read.
 * @returns One entry per section this client knows how to name.
 */
function parseMissing(value: unknown, isIndex: boolean): Missing[] {
  const row = asRecord(value)
  if (!row) return []
  const missing: Missing[] = []
  for (const [section, reason] of Object.entries(row)) {
    const name = SECTION_NAMES[section]
    if (!name) continue
    if (isIndex && section === 'depth') continue
    missing.push({ name, reason: asText(reason) ?? 'the platform did not say why' })
  }
  return missing
}

function parseNotices(value: unknown): string[] {
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
 * Read a `kind: "instrument"` spec.
 *
 * @param value - The frame's `spec`, exactly as it came off the wire.
 * @returns The card's data, or `null` when there is no instrument in it. The
 *   bar for a card is a symbol and a last price; everything else is optional
 *   and simply absent when it did not arrive.
 */
function parseInstrumentSpec(value: unknown): InstrumentSpec | null {
  const root = asRecord(value)
  if (!root) return null
  const symbol = asText(root.symbol)
  const exchange = asText(root.exchange)
  const quote = parseQuote(root.quote)
  if (!symbol || !exchange || !quote) return null
  const isIndex = root.is_index === true
  return {
    symbol: symbol.toUpperCase(),
    exchange: exchange.toUpperCase(),
    currency: asText(root.currency) ?? 'INR',
    analyze: asText(root.mode)?.toLowerCase() === 'analyze',
    asOf: asText(root.as_of) ?? undefined,
    timezone: asText(root.timezone) ?? undefined,
    isDerivative: root.is_derivative === true,
    isIndex,
    quote,
    change: asNumber(root.change) ?? undefined,
    changePercent: asNumber(root.change_percent) ?? undefined,
    details: parseDetails(root.instrument),
    intraday: parseIntraday(root.intraday),
    week52: parseWeek52(root.week_52),
    depth: parseDepth(root.depth),
    position: parsePosition(root.position),
    missing: parseMissing(root.unavailable, isIndex),
    notices: parseNotices(root.notices),
  }
}

// ---------------------------------------------------------------------------
// Formatting
// ---------------------------------------------------------------------------

/**
 * How far the price on screen sits below the high of its range.
 *
 * Computed here from the last price actually being shown rather than taken from
 * the spec, for the same reason the day's change is: the marker on the bar
 * moves with the live tick, and a note beside it derived from the served price
 * would contradict it as soon as the instrument traded.
 */
function belowHigh(ltp: number, high: number): string {
  if (ltp >= high) return 'at the high'
  return `${percent(((ltp - high) / high) * 100, 1)} from high`
}

/** How an unrealised result is named, so a loss cannot be read as a gain. */
function pnlLabel(value: number): string {
  if (value < 0) return 'Unrealised loss'
  if (value > 0) return 'Unrealised gain'
  return 'Unrealised'
}

/**
 * The request a Buy or Sell control writes into the composer.
 *
 * One lot for anything with a lot size, one share otherwise, because a
 * derivative cannot be dealt in anything but lots and a request that asks for
 * one share of a futures contract is a request the operator has to correct
 * before they can use it.
 */
function orderRequest(side: 'Buy' | 'Sell', spec: InstrumentSpec): string {
  const lot = spec.details?.lotSize
  const size = spec.isDerivative && lot && lot > 1 ? `1 lot (${whole(lot)} quantity)` : '1 share'
  return `${side} ${size} of ${spec.symbol} on ${spec.exchange} at market.`
}

// ---------------------------------------------------------------------------
// Pieces
// ---------------------------------------------------------------------------

interface RangeBarProps {
  label: string
  low: number
  high: number
  value: number
  format: (value: number) => string
  note?: string
}

/**
 * Where the last price sits between two extremes.
 *
 * This is the one thing a range tells a trader that its two numbers do not: a
 * stock a rupee off its low and one a rupee off its high read identically as
 * "1,302 to 1,316" and are not the same instrument to hold. The marker is
 * clamped rather than allowed to leave the track, because a live tick can and
 * does breach a served high.
 */
function RangeBar({ label, low, high, value, format, note }: RangeBarProps) {
  const span = high - low
  const raw = span > 0 ? ((value - low) / span) * 100 : 50
  const at = Math.min(Math.max(raw, 0), 100)
  return (
    <div className="min-w-0">
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-[10px] leading-4 tracking-wide text-muted-foreground uppercase">
          {label}
        </span>
        {note && <span className="truncate text-[10px] text-muted-foreground">{note}</span>}
      </div>
      <div
        className="relative mt-1.5 h-1.5 rounded-full bg-muted"
        role="img"
        aria-label={`${label}: ${format(low)} to ${format(high)}, last ${format(value)}`}
      >
        <div
          className="absolute inset-y-0 left-0 rounded-full bg-foreground/20"
          style={{ width: `${at}%` }}
        />
        <span
          className="absolute top-1/2 h-3 w-0.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-foreground"
          style={{ left: `${at}%` }}
        />
      </div>
      <div className="mt-1 flex justify-between gap-2 font-mono text-[11px] tabular-nums text-muted-foreground">
        <span className="truncate">{format(low)}</span>
        <span className="truncate">{format(high)}</span>
      </div>
    </div>
  )
}

interface DepthSideProps {
  title: string
  total?: number
  rows: DepthRow[]
  tone: Tone
  format: (value: number) => string
}

function DepthSide({ title, total, rows, tone, format }: DepthSideProps) {
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
              <tr key={`${row.price ?? 'x'}-${index}`}>
                <td className={cn('py-px text-left', TONE[tone])}>
                  {row.price === undefined ? '' : format(row.price)}
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

export interface InstrumentCardProps {
  /**
   * The `spec` object of a `kind: "instrument"` viz frame, unvalidated. It is
   * read defensively here, so an incomplete or malformed one renders a message
   * rather than throwing.
   *
   * Pass the frame's own object. Its identity is what keeps the parse and the
   * chart's own spec from being rebuilt on every render of the thread.
   */
  spec: unknown
  /** The frame's `title`, e.g. `RELIANCE NSE`. Used only when the spec is unreadable. */
  title?: string
  /** The frame's `source`, e.g. `quotes_service`. Reported to screen readers. */
  source?: string
  /** Extra classes on the card, for a host that needs to adjust its margins. */
  className?: string
}

/**
 * Draw one instrument card from a viz frame.
 *
 * Args:
 *   spec: The frame's `spec`.
 *   title: The frame's `title`.
 *   source: The frame's `source`.
 *   className: Extra classes on the card.
 */
export function InstrumentCard({ spec, title, source, className }: InstrumentCardProps) {
  const parsed = useMemo(() => parseInstrumentSpec(spec), [spec])
  const composerReady = useComposerPrefill()
  const { isMarketOpen } = useMarketStatus()

  // Hooks run whatever the spec turned out to be, so the live layer is asked
  // for an empty symbol on an unreadable frame and disables itself.
  const live = useLiveQuote(parsed?.symbol ?? '', parsed?.exchange ?? '', {
    enabled: parsed !== null,
    // An index has no book. Subscribing at Depth for one buys a heavier feed
    // and a REST call for something that does not exist.
    mode: parsed?.isIndex ? 'Quote' : 'Depth',
  })

  // The chart's spec is a `candles` payload built once from the frame, so the
  // engine is not torn down and rebuilt as ticks arrive. Nothing live reaches
  // it: the served session is a finished series, and the price above it is
  // where the current number belongs.
  const chartSpec = useMemo(() => {
    if (!parsed?.intraday) return null
    return {
      symbol: parsed.symbol,
      exchange: parsed.exchange,
      interval: parsed.intraday.interval,
      chart_type: 'area',
      timezone: parsed.timezone,
      bars: parsed.intraday.bars,
      indicators: [],
    }
  }, [parsed])

  const handleBuy = useCallback(() => {
    if (parsed) prefillComposer(orderRequest('Buy', parsed))
  }, [parsed])

  const handleSell = useCallback(() => {
    if (parsed) prefillComposer(orderRequest('Sell', parsed))
  }, [parsed])

  if (!parsed) {
    return (
      <figure
        className={cn(
          'my-3 min-w-0 overflow-hidden rounded-lg border border-border bg-card',
          className
        )}
        aria-label={asText(title) ?? 'Instrument'}
      >
        <p className="px-3 py-6 text-center text-[12px] text-muted-foreground">
          This instrument card could not be drawn: the quote did not arrive in a shape this page can
          read.
        </p>
      </figure>
    )
  }

  const { quote, details, week52 } = parsed
  const tick = details?.tickSize
  const ltp = live.data.ltp ?? quote.ltp
  const price = (value: number) => fmtPrice(value, tick, ltp)

  const prevClose = live.data.close ?? quote.prevClose
  // Derived from the price on screen rather than taken from the feed's own
  // change field, so the two can never disagree in front of the reader.
  let change = parsed.change
  let changePercent = parsed.changePercent
  if (prevClose !== undefined && prevClose !== 0) {
    change = ltp - prevClose
    changePercent = (change / prevClose) * 100
  }
  const tone = toneOf(change)

  const open = live.data.open ?? quote.open
  const high = live.data.high ?? quote.high
  const low = live.data.low ?? quote.low
  const volume = nonZero(live.data.volume) ?? quote.volume
  const oi = nonZero(live.data.oi) ?? quote.oi
  // Through `nonZero`, because the live layer takes its bid and ask from the
  // top of the depth ladder with a plain `??` and a closed book publishes that
  // as 0. A served bid replaced by a zero would render as 0.00, and the spread
  // taken from it would be the whole ask.
  const bid = nonZero(live.data.bidPrice) ?? quote.bid
  const ask = nonZero(live.data.askPrice) ?? quote.ask
  const spread = bid !== undefined && ask !== undefined && ask > bid ? ask - bid : undefined
  // A range needs two ends and some distance between them. One of the two, or a
  // session that has not moved, draws a bar with nothing in it to read.
  const hasDayRange = low !== undefined && high !== undefined && high > low

  const liveBids = parseLevels(live.data.depth?.buy)
  const liveAsks = parseLevels(live.data.depth?.sell)
  const liveLadder = liveBids.length > 0 || liveAsks.length > 0
  const bids = liveBids.length > 0 ? liveBids : (parsed.depth?.bids ?? [])
  const asks = liveAsks.length > 0 ? liveAsks : (parsed.depth?.asks ?? [])
  const hasDepth = !parsed.isIndex && (bids.length > 0 || asks.length > 0)
  // The totals came with the served ladder and the live feed publishes none, so
  // they are shown only beside the levels they were counted with. A total from
  // the moment of the answer sitting over a ladder that has since moved reads
  // as the sum of what is on screen, and is not.
  const buyTotal = liveLadder ? undefined : parsed.depth?.totalBuyQuantity
  const sellTotal = liveLadder ? undefined : parsed.depth?.totalSellQuantity

  // Three states, not two. "Not live" covers a closed market and a feed that
  // has not delivered yet, and those are different sentences: one is nothing to
  // wait for, the other is.
  let state: FeedState = 'closed'
  if (live.isLive) state = 'live'
  else if (isMarketOpen(parsed.exchange)) state = 'delayed'
  const taken = asOfLabel(parsed.asOf, parsed.timezone)

  const subtitle = [
    details?.name,
    details?.expiry ? `Expiry ${details.expiry}` : null,
    details?.strike !== undefined ? `Strike ${plain(details.strike)}` : null,
    details?.lotSize !== undefined ? `Lot ${whole(details.lotSize)}` : null,
  ]
    .filter((part): part is string => Boolean(part))
    .join(', ')

  const stats: Array<{ label: string; value: string }> = []
  if (open !== undefined) stats.push({ label: 'Open', value: price(open) })
  if (high !== undefined) stats.push({ label: 'High', value: price(high) })
  if (low !== undefined) stats.push({ label: 'Low', value: price(low) })
  if (prevClose !== undefined) stats.push({ label: 'Prev close', value: price(prevClose) })
  if (volume !== undefined) stats.push({ label: 'Volume', value: compact(volume) })
  if (bid !== undefined) stats.push({ label: 'Bid', value: price(bid) })
  if (ask !== undefined) stats.push({ label: 'Ask', value: price(ask) })
  if (spread !== undefined) stats.push({ label: 'Spread', value: price(spread) })
  // Open interest is only a number on a contract that has one. On equity it is
  // meaningless, and on an index it does not exist.
  if (parsed.isDerivative && oi !== undefined)
    stats.push({ label: 'Open interest', value: compact(oi) })

  const position = parsed.position
  const pnlTone = toneOf(position?.pnl)
  const canOrder = !parsed.isIndex && composerReady

  const label = [
    parsed.symbol,
    parsed.exchange,
    `last ${price(ltp)}`,
    change !== undefined ? `change ${signed(change)}` : null,
    source ? `data from ${source}` : null,
  ]
    .filter((part): part is string => Boolean(part))
    .join(', ')

  return (
    <figure
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
            <span className="font-mono text-[13px] font-semibold text-foreground">
              {parsed.symbol}
            </span>
            <Chip>{parsed.exchange}</Chip>
            {details?.instrumentType && <Chip>{details.instrumentType}</Chip>}
            {parsed.analyze && (
              <Chip className="border-amber-500/40 text-amber-600 dark:text-amber-400">
                Analyze
              </Chip>
            )}
          </div>
          {subtitle && (
            <p className="mt-0.5 truncate text-[11px] text-muted-foreground">{subtitle}</p>
          )}
        </div>
        <FeedBadge state={state} />
      </div>

      {/* Price */}
      <div className="px-3 pb-2.5">
        <div className="flex flex-wrap items-baseline gap-x-2.5 gap-y-1">
          <span className="font-mono text-2xl leading-none font-semibold tabular-nums text-foreground">
            {price(ltp)}
          </span>
          {change !== undefined && (
            <span className={cn('font-mono text-[13px] font-medium tabular-nums', TONE[tone])}>
              {signed(change)}
              {changePercent !== undefined && ` (${percent(changePercent)})`}
            </span>
          )}
          <span className="ml-auto text-[10px] tracking-wide text-muted-foreground uppercase">
            {parsed.currency}
          </span>
        </div>
        {state !== 'live' && taken && (
          <p className="mt-1 text-[11px] text-muted-foreground">
            {state === 'closed' ? 'Market closed. Last read ' : 'Not ticking. Last read '}
            {taken}.
          </p>
        )}
      </div>

      {/* Chart */}
      {chartSpec && (
        <div className="border-t border-border">
          <CandleViz
            spec={chartSpec}
            title={`${parsed.symbol} ${parsed.exchange}`}
            source={source}
            variant="inline"
          />
          <p className="px-3 pb-2 text-[11px] text-muted-foreground">
            {parsed.intraday?.interval ? `${parsed.intraday.interval} bars, ` : ''}
            {parsed.intraday?.bars.length} shown
            {parsed.intraday?.barsOmitted
              ? `, ${whole(parsed.intraday.barsOmitted)} older trimmed`
              : ''}
          </p>
        </div>
      )}

      {/* Ranges */}
      {(hasDayRange || week52) && (
        <div className="space-y-3 border-t border-border px-3 py-2.5">
          {hasDayRange && low !== undefined && high !== undefined && (
            <RangeBar label="Day range" low={low} high={high} value={ltp} format={price} />
          )}
          {week52 && (
            <RangeBar
              label={
                week52.fullYear ? '52 week range' : `Range since ${week52.firstDate ?? 'open'}`
              }
              low={week52.low}
              high={week52.high}
              value={ltp}
              format={price}
              note={belowHigh(ltp, week52.high)}
            />
          )}
        </div>
      )}

      {/* Statistics */}
      {stats.length > 0 && (
        <div className="grid grid-cols-2 gap-x-3 gap-y-2 border-t border-border px-3 py-2.5 sm:grid-cols-4">
          {stats.map((stat) => (
            <Stat key={stat.label} label={stat.label} value={stat.value} />
          ))}
        </div>
      )}

      {/* The operator's own position. Nothing is drawn when nothing is held. */}
      {position && (
        <div className="border-t border-border px-3 py-2.5">
          <div
            className={cn(
              'rounded-md border px-2.5 py-2',
              pnlTone === 'down'
                ? 'border-red-500/40 bg-red-500/5'
                : 'border-emerald-500/40 bg-emerald-500/5'
            )}
          >
            <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
              <span className="text-[10px] leading-4 tracking-wide text-muted-foreground uppercase">
                Your position
              </span>
              {position.side && (
                <Chip
                  className={cn('border-current', TONE[position.side === 'short' ? 'down' : 'up'])}
                >
                  {position.side}
                </Chip>
              )}
            </div>
            <div className="mt-1.5 grid grid-cols-2 gap-x-3 gap-y-2 sm:grid-cols-3">
              {position.quantity !== undefined && (
                <Stat label="Quantity" value={whole(position.quantity)} />
              )}
              {position.averagePrice !== undefined && (
                <Stat label="Average" value={price(position.averagePrice)} />
              )}
              {position.pnl !== undefined && (
                <Stat
                  label={pnlLabel(position.pnl)}
                  value={`${signed(position.pnl)}${
                    position.pnlPercent !== undefined ? ` (${percent(position.pnlPercent)})` : ''
                  }`}
                  className={cn('text-[13px] font-semibold', TONE[pnlTone])}
                />
              )}
            </div>
            {position.legs.length > 1 && (
              <ul className="mt-2 space-y-0.5 font-mono text-[11px] tabular-nums text-muted-foreground">
                {position.legs.map((leg, index) => (
                  <li key={`${leg.product ?? 'leg'}-${index}`} className="flex gap-2">
                    <span className="w-12 shrink-0">{leg.product ?? ''}</span>
                    <span className="w-16 shrink-0 text-right">
                      {leg.quantity === undefined ? '' : whole(leg.quantity)}
                    </span>
                    <span className="w-20 shrink-0 text-right">
                      {leg.averagePrice === undefined ? '' : price(leg.averagePrice)}
                    </span>
                    <span className={cn('flex-1 text-right', TONE[toneOf(leg.pnl)])}>
                      {leg.pnl === undefined ? '' : signed(leg.pnl)}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}

      {/* Order book */}
      {hasDepth && (
        <div className="grid grid-cols-2 gap-x-4 border-t border-border px-3 py-2.5">
          <DepthSide title="Bids" total={buyTotal} rows={bids} tone="up" format={price} />
          <DepthSide title="Asks" total={sellTotal} rows={asks} tone="down" format={price} />
        </div>
      )}

      {/* Actions. These fill the composer. They do not place anything. */}
      {canOrder && (
        <div className="flex flex-wrap items-center gap-2 border-t border-border px-3 py-2">
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={handleBuy}
            className="h-7 border-emerald-500/40 px-3 text-emerald-700 hover:bg-emerald-500/10 hover:text-emerald-700 dark:text-emerald-400 dark:hover:text-emerald-400"
          >
            Buy
          </Button>
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={handleSell}
            className="h-7 border-red-500/40 px-3 text-red-700 hover:bg-red-500/10 hover:text-red-700 dark:text-red-400 dark:hover:text-red-400"
          >
            Sell
          </Button>
          <span className="min-w-0 flex-1 text-[11px] text-muted-foreground">
            Writes the request into the message box. Nothing is ordered until you send it and
            approve it.
          </span>
        </div>
      )}

      {/*
        What could not be read. This is the counterpart of every absent section
        above: a section left out because the platform had nothing to say draws
        nothing at all, and one left out because the lookup failed says so here.
        The position is why this exists. A card that drew the same empty space
        whether the book answered "you hold none" or never answered would tell
        an operator they are flat while their broker holds the position.
      */}
      {parsed.missing.length > 0 && (
        <div className="border-t border-border px-3 py-1.5">
          {parsed.missing.map((section) => (
            <p key={section.name} className="text-[11px] text-muted-foreground">
              Could not read {section.name}: {section.reason}
            </p>
          ))}
        </div>
      )}

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
