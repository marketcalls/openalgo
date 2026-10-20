/**
 * One number, built out of several instruments, ticking.
 *
 * A straddle is not a price anybody quotes. It is the sum of two prices, and
 * an operator watching one wants the sum, wants to see the legs it came from,
 * and wants to know whether the sum is still the thing they asked for. This
 * card is those three answers and nothing else.
 *
 * **The arithmetic is the frame's, not this file's.** The backend resolved the
 * contracts, signed each leg, and wrote the rule down:
 *
 *     value = (formula.constant ?? 0) + sum over legs of multiplier * ltp(leg)
 *
 * `multiplier` is signed lots and is the only field the sum needs, which is
 * what keeps a short leg from being added and a two lot leg from being counted
 * once. This file evaluates that expression against live prices and does not
 * decide any part of it. A structure the backend learns tomorrow arrives with
 * its own multipliers and its own constant and draws correctly here with no
 * change, because there is nothing here that knows what a straddle is.
 *
 * **The legs are pinned and the label can go stale, so the card says so.** The
 * strikes were chosen against the spot at resolution and are never
 * resubscribed: an at the money straddle that silently rolled to a new strike
 * would be a different position drawn under the same heading, and the operator
 * would have no way to see the substitution. So when spot walks more than half
 * a strike interval away from where the legs sit, the card keeps showing this
 * combination and states plainly that it is no longer at the money. That
 * warning is only shown when the label claimed the money in the first place;
 * a strangle drifts by design and saying so under it would be noise.
 *
 * **The headline is only as live as its stalest leg.** A combined value made
 * from one tick and one snapshot is a snapshot, and it is labelled as one.
 */

import { useMemo, useRef } from 'react'
import { fmtPrice } from '@/lib/trading/format'
import { cn } from '@/lib/utils'
import { asOfLabel, Chip, FeedBadge, percent, plain, Stat, signed, TONE, toneOf } from './cards'
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
  Sparkline,
  sourceLabel,
  sourceOf,
  statusLine,
  Tick,
  Unreadable,
  useLiveCard,
  type ValueSource,
  worstSource,
} from './live'
import { asNumber, asRecord, asText, nonZero } from './spec'

/** Most legs drawn. The backend caps at eight; this is the guard. */
const MAX_LEGS = 8

// ---------------------------------------------------------------------------
// The spec
// ---------------------------------------------------------------------------

interface Leg {
  symbol: string
  exchange: string
  segment: string
  side: string
  lots: number
  /** Signed lots. The only field the formula needs. */
  multiplier: number
  origin: string
  role: string
  optionType?: string
  strike?: number
  expiry?: string
  lotSize?: number
  tickSize?: number
  seed: Seed | null
}

interface Atm {
  strike: number
  interval: number | null
  spotAtResolution: number | null
  rollThreshold: number | null
  claimsAtm: boolean
}

interface ComboSpec {
  structure: string
  summary: string
  label: string
  underlying: string
  underlyingExchange: string
  expiry: string
  expiryChoice: string
  analyze: boolean
  asOf?: string
  timezone?: string
  spot: { symbol: string; exchange: string; ltp?: number; seed: Seed | null }
  legs: Leg[]
  constant: number | null
  expression: string
  seedValue: number | null
  seedComplete: boolean
  lotSize?: number
  atm?: Atm
  subscribe: Pair[]
  market: Market
  notices: string[]
}

function readLegs(value: unknown): Leg[] {
  if (!Array.isArray(value)) return []
  const legs: Leg[] = []
  for (const entry of value) {
    if (legs.length >= MAX_LEGS) break
    const row = asRecord(entry)
    if (!row) continue
    const symbol = asText(row.symbol)?.toUpperCase()
    const exchange = asText(row.exchange)?.toUpperCase()
    const multiplier = asNumber(row.multiplier)
    // A leg with no multiplier cannot take part in the sum, and a leg with no
    // symbol cannot be subscribed. Either one silently contributing zero would
    // make the headline wrong in a way nothing on screen would reveal.
    if (!symbol || !exchange || multiplier === null || multiplier === 0) continue
    legs.push({
      symbol,
      exchange,
      segment: asText(row.segment)?.toUpperCase() ?? '',
      side: asText(row.side)?.toUpperCase() === 'SELL' ? 'SELL' : 'BUY',
      lots: nonZero(row.lots) ?? 1,
      multiplier,
      origin: asText(row.origin) ?? 'structure',
      role: asText(row.role) ?? '',
      optionType: asText(row.option_type)?.toUpperCase() ?? undefined,
      strike: nonZero(row.strike),
      expiry: asText(row.expiry) ?? undefined,
      lotSize: nonZero(row.lot_size),
      tickSize: nonZero(row.tick_size),
      seed: readSeed(row.seed),
    })
  }
  return legs
}

function readAtm(value: unknown): Atm | undefined {
  const row = asRecord(value)
  if (!row) return undefined
  const strike = nonZero(row.strike)
  if (strike === undefined) return undefined
  return {
    strike,
    interval: nonZero(row.strike_interval) ?? null,
    spotAtResolution: nonZero(row.spot_at_resolution) ?? null,
    rollThreshold: nonZero(row.roll_threshold) ?? null,
    claimsAtm: row.claims_atm === true,
  }
}

/**
 * Read a `kind: "live_combo"` spec.
 *
 * @param value - The frame's `spec`, exactly as it came off the wire.
 * @returns The card, or `null` when it carries no leg with a multiplier. A
 *   combination with no legs has no value to show and nothing to subscribe to.
 */
function parseComboSpec(value: unknown): ComboSpec | null {
  const root = asRecord(value)
  if (!root) return null
  const legs = readLegs(root.legs)
  if (legs.length === 0) return null

  const spotRow = asRecord(root.spot) ?? {}
  const spotSymbol = asText(spotRow.symbol)?.toUpperCase() ?? ''
  const spotExchange = asText(spotRow.exchange)?.toUpperCase() ?? ''
  const formula = asRecord(root.formula) ?? {}
  const seed = asRecord(root.seed) ?? {}
  const subscribe = readPairs(root.subscribe)

  return {
    structure: asText(root.structure) ?? 'custom',
    summary: asText(root.summary) ?? '',
    label: asText(root.label) ?? asText(root.underlying) ?? 'Combination',
    underlying: asText(root.underlying)?.toUpperCase() ?? '',
    underlyingExchange: asText(root.underlying_exchange)?.toUpperCase() ?? '',
    expiry: asText(root.expiry) ?? '',
    expiryChoice: asText(root.expiry_choice) ?? '',
    analyze: asText(root.account_mode)?.toLowerCase() === 'analyze',
    asOf: asText(root.as_of) ?? undefined,
    timezone: asText(root.timezone) ?? undefined,
    spot: {
      symbol: spotSymbol,
      exchange: spotExchange,
      ltp: nonZero(spotRow.ltp),
      seed: readSeed(spotRow.seed),
    },
    legs,
    // Null is the contract here, and it means zero. Only a synthetic or a
    // basis carries one, where it is the option legs' shared strike.
    constant: asNumber(formula.constant),
    expression: asText(formula.expression) ?? '',
    seedValue: asNumber(seed.value),
    seedComplete: seed.complete === true,
    lotSize: nonZero(root.lot_size),
    atm: readAtm(root.atm),
    subscribe:
      subscribe.length > 0
        ? subscribe
        : readPairs([...legs, { symbol: spotSymbol, exchange: spotExchange }]),
    market: readMarket(root.market),
    notices: readNotices(root.notices),
  }
}

// ---------------------------------------------------------------------------
// The component
// ---------------------------------------------------------------------------

export interface LiveComboCardProps {
  /**
   * The `spec` of a `kind: "live_combo"` frame, unvalidated. Read defensively,
   * so a malformed one renders a sentence rather than throwing.
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
 * Draw one live combination card.
 *
 * @param spec - The frame's `spec`.
 * @param title - The frame's `title`.
 * @param source - The frame's `source`.
 * @param className - Extra classes on the card.
 */
export function LiveComboCard({ spec, title, source, className }: LiveComboCardProps) {
  const parsed = useMemo(() => parseComboSpec(spec), [spec])
  const host = useRef<HTMLElement | null>(null)

  const pairs = useMemo(() => parsed?.subscribe ?? [], [parsed])
  // Every leg and the spot are subscribed in Quote, which is what the backend
  // asked for: the value needs a last price per leg and nothing deeper.
  const feed = useLiveCard(host, pairs, 'Quote')

  const open = useMemo(() => {
    if (!parsed) return null
    const venues = parsed.legs.map((leg) => calendarOf(leg.exchange))
    venues.push(calendarOf(parsed.spot.exchange))
    return anyOpen(parsed.market, venues, feed.now)
  }, [parsed, feed.now])

  if (!parsed) {
    return <Unreadable label={asText(title) ?? 'Live combination'} what="live combination" />
  }

  const taken = asOfLabel(parsed.asOf, parsed.timezone)
  const clock = feed.now

  // Each leg, priced. A leg with neither a tick nor a seeded last price has no
  // price at all, and the sum it belongs to has no value: a missing leg
  // counted as zero would read as a real number and be wrong by a whole leg.
  const priced = parsed.legs.map((leg) => {
    const live = feed.data.get(`${leg.exchange}:${leg.symbol}`)
    const values = merged(leg.seed, live?.data)
    const ltp = values.ltp === 0 ? undefined : values.ltp
    return {
      leg,
      values,
      ltp,
      prevClose: values.prevClose,
      source: sourceOf(live),
      age: live?.lastUpdate === undefined ? undefined : Math.max(0, clock - live.lastUpdate),
    }
  })

  const constant = parsed.constant ?? 0
  const missing = priced.filter((entry) => entry.ltp === undefined)
  const value =
    missing.length === 0
      ? priced.reduce((total, entry) => total + entry.leg.multiplier * (entry.ltp ?? 0), constant)
      : null

  // The same expression evaluated at yesterday's closes. Every number in it is
  // a served previous close, so this is the structure's own session move
  // rather than a figure derived from anything the model said.
  const baseline = priced.every((entry) => entry.prevClose !== undefined)
    ? priced.reduce(
        (total, entry) => total + entry.leg.multiplier * (entry.prevClose ?? 0),
        constant
      )
    : null
  const change = value !== null && baseline !== null ? value - baseline : undefined
  const changePercent =
    change !== undefined && baseline !== null && baseline !== 0
      ? (change / baseline) * 100
      : undefined

  const spotLive = feed.data.get(`${parsed.spot.exchange}:${parsed.spot.symbol}`)
  const spotValues = merged(parsed.spot.seed, spotLive?.data)
  const spot = spotValues.ltp === 0 ? parsed.spot.ltp : (spotValues.ltp ?? parsed.spot.ltp)

  // The headline can claim no more than its stalest leg.
  const valueSource: ValueSource = worstSource(priced.map((entry) => entry.source))
  const ages = priced
    .map((entry) => entry.age)
    .filter((entry): entry is number => entry !== undefined)
  const newest = ages.length > 0 ? Math.min(...ages) : undefined
  const state = feedState(feed, open, newest)
  const tone = toneOf(change)

  const drift =
    parsed.atm && spot !== undefined && parsed.atm.rollThreshold
      ? Math.abs(spot - parsed.atm.strike) > parsed.atm.rollThreshold
      : false

  const money = (amount: number) => fmtPrice(amount, undefined, Math.abs(amount) || 1)
  const label = [
    parsed.label,
    value === null ? 'value incomplete' : `value ${money(value)}`,
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
            <span className="text-[13px] font-semibold text-foreground">{parsed.label}</span>
            <Chip>{parsed.structure.replace(/_/g, ' ')}</Chip>
            {parsed.analyze && (
              <Chip className="border-amber-500/40 text-amber-600 dark:text-amber-400">
                Analyze
              </Chip>
            )}
          </div>
          {parsed.summary && (
            <p className="mt-0.5 text-[11px] text-muted-foreground">{parsed.summary}</p>
          )}
        </div>
        <FeedBadge state={state} />
      </div>

      {/* The number */}
      <div className="border-t border-border px-3 py-2.5">
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          {value === null ? (
            <span className="text-[13px] text-muted-foreground">
              No value yet: {missing.length} of {priced.length} legs have no price.
            </span>
          ) : (
            <span className="font-mono text-2xl leading-none font-semibold tabular-nums text-foreground">
              <Tick value={value} className="px-1">
                {money(value)}
              </Tick>
            </span>
          )}
          {change !== undefined && (
            <span className={cn('font-mono text-[13px] font-medium tabular-nums', TONE[tone])}>
              <Tick value={change} className="px-1">
                {signed(change)}
                {changePercent !== undefined && ` (${percent(changePercent)})`}
              </Tick>
            </span>
          )}
          <span className="ml-auto text-[10px] tracking-wide text-muted-foreground uppercase">
            {sourceLabel(valueSource, newest, taken)}
          </span>
        </div>

        <div className="mt-1.5">
          <Sparkline value={value} tone={tone} />
        </div>

        <p className="mt-1 text-[11px] text-muted-foreground">
          Per unit.
          {parsed.lotSize !== undefined && value !== null
            ? ` One lot of ${plain(parsed.lotSize)} is ${money(value * parsed.lotSize)}.`
            : ''}
          {change !== undefined
            ? ''
            : ' No session change: not every leg carries a previous close.'}
        </p>
        {parsed.expression && (
          <p className="mt-1 overflow-x-auto font-mono text-[10px] whitespace-nowrap text-muted-foreground">
            {parsed.expression}
          </p>
        )}
      </div>

      {/*
        The roll. The legs never move, so this is the only thing standing
        between an operator and a card headed "ATM straddle" that stopped
        being one an hour ago.
      */}
      {drift && parsed.atm && (
        <p
          className={cn(
            'border-t border-border px-3 py-1.5 text-[11px]',
            parsed.atm.claimsAtm
              ? 'bg-amber-500/5 text-amber-700 dark:text-amber-400'
              : 'text-muted-foreground'
          )}
        >
          {parsed.atm.claimsAtm
            ? `Spot is ${spot === undefined ? 'away from' : money(spot)}, so ${plain(parsed.atm.strike)} is no longer the at the money strike. These legs are pinned and still the ones shown; the heading is stale, not the prices.`
            : `Spot has moved to ${spot === undefined ? 'another strike' : money(spot)}, away from the ${plain(parsed.atm.strike)} these legs were chosen around.`}
        </p>
      )}

      {/* Spot, and where the strikes were chosen from */}
      {parsed.spot.symbol && (
        <div className="grid grid-cols-2 gap-x-3 gap-y-2 border-t border-border px-3 py-2.5 sm:grid-cols-4">
          <Stat
            label={`Spot ${parsed.spot.symbol}`}
            value={spot === undefined ? 'no price' : <Tick value={spot}>{money(spot)}</Tick>}
          />
          {parsed.atm && <Stat label="Strike" value={plain(parsed.atm.strike)} />}
          {parsed.atm?.interval !== null && parsed.atm?.interval !== undefined && (
            <Stat label="Strike interval" value={plain(parsed.atm.interval)} />
          )}
          {parsed.expiry && (
            <Stat
              label={
                parsed.expiryChoice
                  ? `Expiry (${parsed.expiryChoice.replace(/_/g, ' ')})`
                  : 'Expiry'
              }
              value={parsed.expiry}
            />
          )}
        </div>
      )}

      {/* The legs the number is made of */}
      <ul className="divide-y divide-border/60 border-t border-border">
        {priced.map((entry) => {
          const { leg } = entry
          const price = (amount: number) => fmtPrice(amount, leg.tickSize, entry.ltp ?? amount)
          return (
            <li
              key={`${leg.exchange}:${leg.symbol}:${leg.role}`}
              className="flex flex-wrap items-baseline gap-x-2 gap-y-1 px-3 py-1.5 text-[11px]"
            >
              <span
                className={cn(
                  'w-9 shrink-0 font-medium',
                  TONE[leg.side === 'SELL' ? 'down' : 'up']
                )}
              >
                {leg.side}
              </span>
              <span className="shrink-0 font-mono text-muted-foreground">
                {leg.multiplier > 0 ? '+' : ''}
                {plain(leg.multiplier)}
              </span>
              <span className="min-w-0 truncate font-mono text-foreground">{leg.symbol}</span>
              <Chip className="shrink-0">{leg.exchange}</Chip>
              <span className="ml-auto shrink-0 font-mono tabular-nums text-foreground">
                {entry.ltp === undefined ? (
                  <span className="text-muted-foreground">no price</span>
                ) : (
                  <Tick value={entry.ltp} className="px-1">
                    {price(entry.ltp)}
                  </Tick>
                )}
              </span>
              <Provenance
                source={entry.source}
                age={entry.age}
                taken={taken}
                className="w-24 text-right"
              />
            </li>
          )
        })}
      </ul>

      <p className="border-t border-border px-3 py-1.5 text-[11px] text-muted-foreground">
        {statusLine(state, {
          what: 'every leg',
          newest,
          taken,
          holiday: parsed.market.isHoliday,
        })}
      </p>

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

/**
 * The exchange whose calendar an instrument follows.
 *
 * The quotes frame resolves this per instrument and carries it; the combo
 * frame does not, because its legs are contracts rather than a list the
 * operator named. The rule is the same one `useMarketStatus` applies: an index
 * has no session of its own, it trades when its exchange does.
 *
 * @param exchange - An OpenAlgo exchange code.
 */
function calendarOf(exchange: string): string {
  return exchange.endsWith('_INDEX') ? exchange.slice(0, -'_INDEX'.length) : exchange
}
