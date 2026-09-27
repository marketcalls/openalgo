/**
 * The option chain picker on the right of the charting terminal.
 *
 * Click a leg and it charts, which is the whole point: getting from "what is
 * the 24800 call doing" to a chart of it currently means leaving the terminal
 * for /tools and coming back with a symbol to paste.
 *
 * Greeks come from the same request as the prices. get_option_chain inverts
 * Black-76 over the quotes it has already fetched, so implied volatility and
 * delta cost no extra broker call, which is why the metric switch can offer
 * them beside LTP and OI without making the panel any slower.
 *
 * Colour polarity and moneyness shading deliberately match
 * pages/OptionChain.tsx: it is the same product showing the same chain, and a
 * user with both open must not have to read one of them backwards.
 *
 * Bar ANCHORING deliberately differs. The reference grows its bars inward
 * from the outer edges, which it can afford across a full page. In a 340px
 * panel that puts the number at one edge and its bar at the other, so here
 * both grow outward from the strike instead, keeping each value beside the
 * strike it belongs to.
 */

import { Check, ChevronsUpDown, RefreshCw } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'

import { useOptionChainLive } from '@/hooks/useOptionChainLive'
import { scalpingApi } from '@/api/scalping'
import { Button } from '@/components/ui/button'
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from '@/components/ui/command'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { useMarketStatus } from '@/hooks/useMarketStatus'
import { needsPreviousClose } from '@/lib/trading/previousClose'
import type { SearchRow } from '@/lib/trading/terminal'
import { cn } from '@/lib/utils'
import type { OptionData } from '@/types/option-chain'
import { PlaceOrderDialog } from './PlaceOrderDialog'
import { PANEL_HEADER, PanelShell } from './panelShell'

/** Survives a reload so the panel reopens on the contract the user was watching. */
const PREFS_KEY = 'oa-trading-optionchain'

/** Derivative segments that carry an option chain. */
const EXCHANGES = ['NFO', 'BFO', 'MCX', 'CDS'] as const
type Exchange = (typeof EXCHANGES)[number]

/**
 * What the two side columns show.
 *
 * LTP is the default because it is what a chart click is about. Everything
 * else rides along in the same response, so offering it costs nothing: the
 * service inverts Black-76 over the quotes it has already fetched and returns
 * the whole Greek set with the prices, in one broker call.
 *
 * `dp` is per metric because the magnitudes are nothing alike. Gamma for an
 * index option is around 0.0019, so at the two decimals that suit delta and
 * theta every strike on the board would read 0.00.
 *
 * `symbol` is the notation the instrument is actually discussed in. A trader
 * reads a column of deltas under a bare capital delta without being told; the
 * name is kept beside it in the picker so nothing depends on recognising it.
 * Sigma for implied volatility, and vega keeps a Latin V because it is not a
 * Greek letter at all, whatever the family is called.
 */
const METRICS = [
  { id: 'ltp', label: 'LTP', symbol: 'LTP', group: 'Price', dp: 2 },
  { id: 'oi', label: 'OI', symbol: 'OI', group: 'Price', dp: 0 },
  { id: 'volume', label: 'Volume', symbol: 'Vol', group: 'Price', dp: 0 },
  { id: 'iv', label: 'IV', symbol: 'σ', group: 'Greeks', dp: 1 },
  { id: 'delta', label: 'Delta', symbol: 'Δ', group: 'Greeks', dp: 2 },
  { id: 'gamma', label: 'Gamma', symbol: 'Γ', group: 'Greeks', dp: 4 },
  { id: 'theta', label: 'Theta', symbol: 'Θ', group: 'Greeks', dp: 2 },
  { id: 'vega', label: 'Vega', symbol: 'V', group: 'Greeks', dp: 2 },
] as const
type Metric = (typeof METRICS)[number]['id']

/** The order the picker lists them in, so the groups stay together. */
const METRIC_GROUPS = ['Price', 'Greeks'] as const

/** Strikes either side of ATM. Twenty rows is about one panel-height of scroll. */
const STRIKE_COUNT = 10

/** The row and its column header share this, so the two cannot drift apart. */
const ROW_GRID = 'grid grid-cols-[1fr_64px_1fr]'

interface Props {
  apiKey: string
  /** Charts the leg that was clicked, in whichever pane was last touched. */
  onPick(row: SearchRow): void
  /**
   * The focused pane's instrument as `EXCHANGE:SYMBOL`, so the leg currently
   * on the chart is marked. The watchlist has always had this; without it
   * here, charting a leg gave no confirmation that anything had happened.
   */
  activeSymbol?: string | null
}

interface Prefs {
  exchange: Exchange
  underlying: string
  expiry: string
}

function readPrefs(): Prefs {
  try {
    const saved = JSON.parse(localStorage.getItem(PREFS_KEY) || '{}')
    return {
      exchange: EXCHANGES.includes(saved.exchange) ? saved.exchange : 'NFO',
      underlying: typeof saved.underlying === 'string' ? saved.underlying : 'NIFTY',
      expiry: typeof saved.expiry === 'string' ? saved.expiry : '',
    }
  } catch {
    return { exchange: 'NFO', underlying: 'NIFTY', expiry: '' }
  }
}

/** Lakhs and crores: OI in raw units does not fit a 64px column. */
function compact(value: number | undefined): string {
  if (typeof value !== 'number' || !Number.isFinite(value) || value === 0) return '-'
  if (value >= 1e7) return `${(value / 1e7).toFixed(2)}Cr`
  if (value >= 1e5) return `${(value / 1e5).toFixed(2)}L`
  if (value >= 1e3) return `${(value / 1e3).toFixed(1)}K`
  return String(Math.round(value))
}

/**
 * One leg's value for the selected metric.
 *
 * Everything unavailable renders as a dash rather than a zero. A leg with no
 * quote, or one on an expired chain, cannot be inverted, and printing 0.00
 * would read as a real measurement of zero volatility or zero sensitivity.
 * That distinction is the whole reason to show Greeks at all.
 */
function metricOf(leg: OptionData | null, metric: Metric): string {
  if (!leg) return '-'

  if (metric === 'ltp') return leg.ltp > 0 ? leg.ltp.toFixed(2) : '-'
  if (metric === 'oi') return compact(leg.oi)
  if (metric === 'volume') return compact(leg.volume)

  const dp = METRICS.find((m) => m.id === metric)?.dp ?? 2
  const value =
    metric === 'iv'
      ? leg.implied_volatility
      : metric === 'delta'
        ? leg.delta
        : metric === 'gamma'
          ? leg.gamma
          : metric === 'theta'
            ? leg.theta
            : leg.vega

  if (typeof value !== 'number' || !Number.isFinite(value)) return '-'
  return metric === 'iv' ? `${value.toFixed(dp)}%` : value.toFixed(dp)
}

/**
 * Buy and sell pills for one leg.
 *
 * They sit immediately beside the value, not at the panel's outer edge. The
 * value is what the trader is reading and what they are acting on, so putting
 * the controls an inch away across empty cell made the pair read as unrelated.
 *
 * Laid out in flow rather than absolutely positioned, so they hold their space
 * while hidden: revealing them on hover cannot shift the number the pointer is
 * aimed at. Nothing is ever covered to make room either, which is the failure
 * mode a hover control usually has in a column this narrow.
 *
 * Colours match pages/OptionChain.tsx exactly, green to buy and amber to sell.
 * Amber rather than red because red already means "put" in this table.
 */
function OrderPills({
  leg,
  onOrder,
}: {
  leg: OptionData | null
  onOrder(leg: OptionData, action: 'BUY' | 'SELL'): void
}) {
  if (!leg?.symbol) return null
  return (
    <span
      className={cn(
        'relative z-10 flex shrink-0 items-center gap-0.5 opacity-0 transition-opacity',
        'group-hover/leg:opacity-100 focus-within:opacity-100'
      )}
    >
      {(['BUY', 'SELL'] as const).map((action) => (
        <button
          key={action}
          type="button"
          onClick={() => onOrder(leg, action)}
          className={cn(
            'rounded px-1 py-0.5 text-[9px] font-bold leading-none text-white transition-colors',
            'focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring',
            action === 'BUY'
              ? 'bg-emerald-600 hover:bg-emerald-700'
              : 'bg-amber-600 hover:bg-amber-700'
          )}
          aria-label={`${action === 'BUY' ? 'Buy' : 'Sell'} ${leg.symbol}`}
          title={`${action === 'BUY' ? 'Buy' : 'Sell'} ${leg.symbol}`}
        >
          {action === 'BUY' ? 'B' : 'S'}
        </button>
      ))}
    </span>
  )
}

export function OptionChainPanel({ apiKey, onPick, activeSymbol }: Props) {
  const [prefs, setPrefs] = useState<Prefs>(readPrefs)
  const [underlyings, setUnderlyings] = useState<string[]>([])
  const [expiries, setExpiries] = useState<string[]>([])
  const [metric, setMetric] = useState<Metric>('ltp')
  const [pickerOpen, setPickerOpen] = useState(false)
  /**
   * One slot per loader, not one shared between them.
   *
   * Shared, the failures cancelled each other: an underlyings request that
   * 500s set the message, the expiries then resolved from the persisted
   * symbol, the chain loaded fine and cleared it. The user was left with a
   * combobox reading "No underlying found", no error and no retry, which is
   * exactly the reading these states exist to prevent.
   */
  const [underlyingError, setUnderlyingError] = useState<string | null>(null)
  const [expiryError, setExpiryError] = useState<string | null>(null)

  /** Bumped to re-run the loaders after a Retry. */
  const [attempt, setAttempt] = useState(0)

  /**
   * The leg an order is being placed on, or null.
   *
   * Opens PlaceOrderDialog, the same component pages/OptionChain.tsx uses, so
   * quantity, product and price type are confirmed there rather than fired off
   * a 20px pill. Nothing here places an order by itself.
   */
  const [order, setOrder] = useState<{
    leg: OptionData
    action: 'BUY' | 'SELL'
  } | null>(null)

  const { isMarketOpen } = useMarketStatus()

  useEffect(() => {
    localStorage.setItem(PREFS_KEY, JSON.stringify(prefs))
  }, [prefs])

  /* ── underlyings for the chosen segment ───────────────────────────────── */
  // biome-ignore lint/correctness/useExhaustiveDependencies: `attempt` is a deliberate re-run trigger, not a value this effect reads; Retry bumps it to refetch without changing the contract
  useEffect(() => {
    let alive = true
    ;(async () => {
      try {
        const res = await scalpingApi.getAllUnderlyings(prefs.exchange, 'options')
        if (!alive) return
        const names = res.data ?? []
        setUnderlyings(names)
        setUnderlyingError(null)
        // Switching segment leaves the old underlying selected and it will not
        // resolve, so fall back to the first one the new segment actually has.
        setPrefs((p) =>
          names.length === 0 || names.includes(p.underlying)
            ? p
            : { ...p, underlying: names[0], expiry: '' }
        )
      } catch {
        if (!alive) return
        setUnderlyings([])
        // Reported rather than swallowed. Silently emptying the list left a
        // combobox saying "No underlying found", which reads as "this segment
        // has no options" rather than "the request failed".
        setUnderlyingError(`Could not load ${prefs.exchange} underlyings`)
      }
    })()
    return () => {
      alive = false
    }
  }, [prefs.exchange, attempt])

  /* ── expiries for the chosen underlying ───────────────────────────────── */
  // biome-ignore lint/correctness/useExhaustiveDependencies: `attempt` is a deliberate re-run trigger, not a value this effect reads; Retry bumps it to refetch without changing the contract
  useEffect(() => {
    if (!prefs.underlying) return
    let alive = true
    ;(async () => {
      try {
        const res = await scalpingApi.getExpiry(prefs.underlying, prefs.exchange, 'options')
        if (!alive) return
        const dates = res.data ?? []
        setExpiries(dates)
        setExpiryError(null)
        setPrefs((p) =>
          dates.length === 0 || dates.includes(p.expiry) ? p : { ...p, expiry: dates[0] }
        )
      } catch {
        if (!alive) return
        setExpiries([])
        setExpiryError(`Could not load expiries for ${prefs.underlying}`)
      }
    })()
    return () => {
      alive = false
    }
  }, [prefs.underlying, prefs.exchange, attempt])

  /* ── the chain itself ─────────────────────────────────────────────────── */
  /**
   * The same stream `/optionchain` runs on.
   *
   * This panel used to fetch the whole chain over REST on a five second timer,
   * which is why it lagged the dedicated page so badly: every quote was up to
   * five seconds old, and each refresh was a full broker round trip for eighty
   * legs. `useOptionChainLive` polls only the structural columns (open interest,
   * volume) on a slow interval and takes every price off the websocket, then
   * recomputes the Greeks client-side on each tick batch. Prices move as they
   * happen and the broker sees a fraction of the calls.
   *
   * `exchange` and `optionExchange` are the same segment here, as they are on
   * the dedicated page: the panel only lists derivative segments, so the
   * underlying and its options are quoted on the one the user picked.
   */
  const {
    data: chain,
    isLoading: loading,
    isStreaming,
    error: chainError,
    lastUpdate,
    refetch,
  } = useOptionChainLive(
    apiKey,
    prefs.underlying,
    prefs.exchange,
    prefs.exchange,
    prefs.expiry,
    STRIKE_COUNT,
    { enabled: Boolean(prefs.underlying && prefs.expiry), oiRefreshInterval: 30000, pauseWhenHidden: true }
  )

  const marketOpen = isMarketOpen(prefs.exchange)

  const retry = () => {
    setUnderlyingError(null)
    setExpiryError(null)
    setAttempt((n) => n + 1)
    refetch()
  }

  /* ── derived ──────────────────────────────────────────────────────────── */
  const rows = chain?.chain ?? []

  /** The widest OI on screen, so the bars are scaled to what is visible. */
  const peakOi = useMemo(
    () => Math.max(1, ...rows.flatMap((r) => [r.ce?.oi ?? 0, r.pe?.oi ?? 0])),
    [rows]
  )

  const pcr = useMemo(() => {
    const ce = rows.reduce((sum, r) => sum + (r.ce?.oi ?? 0), 0)
    const pe = rows.reduce((sum, r) => sum + (r.pe?.oi ?? 0), 0)
    return ce > 0 ? pe / ce : 0
  }, [rows])

  const chartLeg = (leg: OptionData | null) => {
    if (!leg?.symbol) return
    onPick({ symbol: leg.symbol, exchange: prefs.exchange })
  }

  /**
   * Tri-state, not a boolean. With no previous close there is no direction, and
   * collapsing that into "down" paints the spot red pre-open and on any
   * underlying whose previous close comes back as zero.
   */
  const spotDirection: 'up' | 'down' | 'flat' = (() => {
    const ltp = chain?.underlying_ltp
    if (typeof ltp !== 'number') return 'flat'
    // The same broker field previousClose.ts exists because it cannot be
    // trusted: where it carries the CURRENT session's close it equals the LTP,
    // and `>=` then painted the spot green every hour of every day.
    if (needsPreviousClose(chain?.underlying_prev_close, ltp)) return 'flat'
    const prev = chain?.underlying_prev_close as number
    if (ltp === prev) return 'flat'
    return ltp > prev ? 'up' : 'down'
  })()

  const activeMetric = METRICS.find((m) => m.id === metric)
  const metricLabel = activeMetric?.symbol ?? ''

  return (
    <PanelShell
      id="oa-panel-options"
      label="Option chain"
      storageKey="oa-trading-optionchain-width"
      defaultWidth={340}
    >
      {/* Header: the contract. Its rule lands on the same line as every pane
          toolbar's, so the workspace reads as one horizon. */}
      <div className={PANEL_HEADER}>
        <Select
          value={prefs.exchange}
          onValueChange={(value) =>
            setPrefs((p) => ({ ...p, exchange: value as Exchange, expiry: '' }))
          }
        >
          <SelectTrigger className="h-8 w-[76px] text-[12px]" aria-label="Exchange segment">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {EXCHANGES.map((ex) => (
              <SelectItem key={ex} value={ex} className="text-[12px]">
                {ex}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        {/* A searchable combobox, not a Select: NFO alone lists nearly two
            hundred underlyings and scrolling to one is not a UI. */}
        <Popover open={pickerOpen} onOpenChange={setPickerOpen}>
          <PopoverTrigger asChild>
            <Button
              variant="outline"
              role="combobox"
              aria-expanded={pickerOpen}
              aria-label="Underlying"
              className="h-8 min-w-0 flex-1 justify-between px-2 text-[12px] font-medium"
            >
              <span className="truncate">{prefs.underlying || 'Select'}</span>
              <ChevronsUpDown className="h-3 w-3 shrink-0 opacity-50" />
            </Button>
          </PopoverTrigger>
          <PopoverContent className="w-[220px] p-0" align="start">
            <Command>
              <CommandInput placeholder="Search underlying..." className="h-8 text-[12px]" />
              <CommandList>
                <CommandEmpty className="py-4 text-center text-[12px]">
                  {/* "No underlying found" reads as "this segment has none".
                      When the request failed, say that instead. */}
                  {underlyingError ?? 'No underlying found.'}
                </CommandEmpty>
                <CommandGroup>
                  {underlyings.map((name) => (
                    <CommandItem
                      key={name}
                      value={name}
                      onSelect={() => {
                        setPrefs((p) => ({ ...p, underlying: name, expiry: '' }))
                        setPickerOpen(false)
                      }}
                      className="text-[12px]"
                    >
                      <Check
                        className={cn(
                          'mr-2 h-3.5 w-3.5',
                          prefs.underlying === name ? 'opacity-100' : 'opacity-0'
                        )}
                      />
                      {name}
                    </CommandItem>
                  ))}
                </CommandGroup>
              </CommandList>
            </Command>
          </PopoverContent>
        </Popover>

        <Button
          variant="ghost"
          size="icon"
          className="h-8 w-8 shrink-0"
          onClick={() => refetch()}
          title="Refresh"
          aria-label="Refresh option chain"
        >
          <RefreshCw className={cn('h-3.5 w-3.5', loading && 'animate-spin')} />
        </Button>
      </div>

      {/* Second band: expiry and what the side columns are showing */}
      <div className="flex shrink-0 items-center gap-1.5 border-b px-2 py-1.5">
        <Select
          value={prefs.expiry}
          onValueChange={(value) => setPrefs((p) => ({ ...p, expiry: value }))}
        >
          <SelectTrigger
            className={cn(
              'h-8 min-w-0 flex-1 text-[12px]',
              expiryError && 'border-destructive text-destructive'
            )}
            aria-label="Expiry"
            title={expiryError ?? undefined}
          >
            <SelectValue placeholder={expiryError ? 'Expiry unavailable' : 'Expiry'} />
          </SelectTrigger>
          <SelectContent>
            {expiries.map((date) => (
              <SelectItem key={date} value={date} className="text-[12px]">
                {date}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Select value={metric} onValueChange={(value) => setMetric(value as Metric)}>
          <SelectTrigger className="h-8 w-[104px] text-[12px]" aria-label="Metric shown">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {METRIC_GROUPS.map((group) => (
              <SelectGroup key={group}>
                <SelectLabel className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground/70">
                  {group}
                </SelectLabel>
                {METRICS.filter((m) => m.group === group).map((m) => (
                  <SelectItem key={m.id} value={m.id} className="text-[12px]">
                    {/* Notation and name together: the column header carries
                        only the notation, so this is where the two are tied. */}
                    <span className="inline-flex w-4 shrink-0 justify-center font-medium">
                      {m.symbol === m.label ? '' : m.symbol}
                    </span>
                    <span>{m.label}</span>
                  </SelectItem>
                ))}
              </SelectGroup>
            ))}
          </SelectContent>
        </Select>
      </div>

      {/* Spot, ATM, PCR */}
      {chain && (
        <div className="flex shrink-0 items-center justify-between border-b px-2 py-1 text-[11px]">
          <span className="flex items-center gap-1">
            <span className="text-muted-foreground">Spot</span>
            <span
              className={cn(
                'font-medium tabular-nums',
                spotDirection === 'up' && 'text-emerald-600 dark:text-emerald-400',
                spotDirection === 'down' && 'text-rose-600 dark:text-rose-400',
                spotDirection === 'flat' && 'text-foreground'
              )}
            >
              {chain.underlying_ltp?.toFixed(2) ?? '-'}
            </span>
          </span>
          <span className="flex items-center gap-1">
            <span className="text-muted-foreground">ATM</span>
            <span className="font-medium tabular-nums">{chain.atm_strike}</span>
          </span>
          {/* Labelled with the strike count, because this is the ratio across
              the strikes on screen, not the whole chain a trader may expect. */}
          <span
            className="flex items-center gap-1"
            title={`Across ${rows.length} strikes on screen`}
          >
            <span className="text-muted-foreground">PCR({rows.length})</span>
            <span className="font-medium tabular-nums">{pcr ? pcr.toFixed(2) : '-'}</span>
          </span>
        </div>
      )}

      {/* Column header. It names the metric, because the cells hold whichever
          of LTP, OI, IV or Delta is selected and "Calls | Puts" alone would
          leave two columns of unlabelled numbers. */}
      <div
        className={cn(
          ROW_GRID,
          'shrink-0 border-b px-2 py-1 text-[10px] font-medium uppercase tracking-wider text-muted-foreground/70'
        )}
      >
        {/* Each label sits on the side its numbers do. Calls are right
            aligned against the strike and puts left aligned, so a label at
            the outer edge sat ~130px from the column it names. */}
        {/* normal-case on the notation: CSS uppercase maps sigma to capital
            sigma, which in this domain reads as a sum rather than volatility,
            so selecting IV rendered "CALLS Σ". */}
        <span className="text-right">
          Calls <span className="normal-case">{metricLabel}</span>
        </span>
        <span className="text-center">Strike</span>
        <span className="text-left">
          Puts <span className="normal-case">{metricLabel}</span>
        </span>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {chainError && rows.length === 0 ? (
          <div className="flex flex-col items-center gap-2 p-6 text-center">
            <p className="text-[12px] text-muted-foreground">{chainError}</p>
            <Button variant="outline" size="sm" className="h-7 gap-1.5" onClick={retry}>
              <RefreshCw className="h-3.5 w-3.5" />
              Retry
            </Button>
          </div>
        ) : loading && rows.length === 0 ? (
          <p className="p-3 text-[12px] text-muted-foreground">Loading chain...</p>
        ) : rows.length === 0 ? (
          <p className="p-3 text-[12px] text-muted-foreground">
            No chain for this contract. Check the expiry, or that master contracts are downloaded.
          </p>
        ) : (
          rows.map((row) => {
            const atm = chain != null && row.strike === chain.atm_strike
            // Above ATM the call is out of the money; below it, the put is.
            const ceOtm = chain != null && !atm && row.strike > chain.atm_strike
            const peOtm = chain != null && !atm && row.strike < chain.atm_strike
            return (
              <div
                key={row.strike}
                className={cn(ROW_GRID, 'items-stretch border-b border-border/40 text-[12px]')}
              >
                {/* Both values sit against the strike and both OI bars grow
                    away from it. Anchoring them to the panel's outer edges
                    instead put 120px of empty cell between the number and the
                    strike it belongs to, and turned the OI profile into an
                    hourglass rather than the butterfly it is read as.

                    Calls green and puts red, matching pages/OptionChain.tsx.
                    The same chain rendered with the colours swapped in another
                    tab is a way to read resistance as support. */}
                {/* A wrapper, so the order pills are SIBLINGS of the chart
                    button rather than nested inside it: a button within a
                    button is invalid HTML and behaves like it. */}
                <div
                  className={cn(
                    'group/leg relative flex items-center gap-1 justify-end px-2 py-1 transition-colors',
                    ceOtm ? 'bg-amber-500/5 hover:bg-amber-500/15' : 'hover:bg-accent',
                    activeSymbol === `${prefs.exchange}:${row.ce?.symbol}` &&
                      'font-medium ring-1 ring-inset ring-primary/60'
                  )}
                >
                  {/* Only while the cells show OI. A bar encoding one quantity
                      under a number showing another says two different things
                      in the same cell with nothing to tell them apart. */}
                  {metric === 'oi' && (
                    <span
                      className="pointer-events-none absolute inset-y-0 right-0 bg-gradient-to-l from-emerald-500/25 to-transparent"
                      style={{ width: `${Math.min(100, ((row.ce?.oi ?? 0) / peakOi) * 100)}%` }}
                      aria-hidden="true"
                    />
                  )}
                  {/* The click target, stretched underneath. The value and the
                      order pills are siblings above it rather than children: a
                      button inside a button is invalid HTML, and keeping the
                      value out here is what lets the pills sit against it. */}
                  <button
                    type="button"
                    onClick={() => chartLeg(row.ce)}
                    disabled={!row.ce?.symbol}
                    className="absolute inset-0 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-inset focus-visible:ring-ring disabled:pointer-events-none"
                    title={row.ce?.symbol ? `Chart ${row.ce.symbol}` : undefined}
                    aria-current={
                      activeSymbol === `${prefs.exchange}:${row.ce?.symbol}` ? true : undefined
                    }
                    aria-label={
                      row.ce?.symbol
                        ? `Chart ${row.ce.symbol}, ${metricLabel} ${metricOf(row.ce, metric)}`
                        : undefined
                    }
                  />
                  <OrderPills leg={row.ce} onOrder={(leg, action) => setOrder({ leg, action })} />
                  <span className="pointer-events-none relative tabular-nums">
                    {metricOf(row.ce, metric)}
                  </span>
                </div>

                {/* ATM as a tinted, ringed chip rather than a filled one.
                    `--primary` in this app is near-black in light and near-white
                    in dark, so bg-primary would put the loudest element on the
                    page in the middle of a 21-row table. */}
                <span
                  className={cn(
                    'flex items-center justify-center border-x border-border/40 py-1 tabular-nums',
                    atm
                      ? 'bg-primary/10 font-semibold text-foreground ring-1 ring-inset ring-primary/50'
                      : 'text-muted-foreground'
                  )}
                >
                  {row.strike}
                </span>

                {/* A wrapper, so the order pills are SIBLINGS of the chart
                    button rather than nested inside it: a button within a
                    button is invalid HTML and behaves like it. */}
                <div
                  className={cn(
                    'group/leg relative flex items-center gap-1 justify-start px-2 py-1 transition-colors',
                    peOtm ? 'bg-amber-500/5 hover:bg-amber-500/15' : 'hover:bg-accent',
                    activeSymbol === `${prefs.exchange}:${row.pe?.symbol}` &&
                      'font-medium ring-1 ring-inset ring-primary/60'
                  )}
                >
                  {/* Only while the cells show OI. A bar encoding one quantity
                      under a number showing another says two different things
                      in the same cell with nothing to tell them apart. */}
                  {metric === 'oi' && (
                    <span
                      className="pointer-events-none absolute inset-y-0 left-0 bg-gradient-to-r from-rose-500/25 to-transparent"
                      style={{ width: `${Math.min(100, ((row.pe?.oi ?? 0) / peakOi) * 100)}%` }}
                      aria-hidden="true"
                    />
                  )}
                  {/* The click target, stretched underneath. The value and the
                      order pills are siblings above it rather than children: a
                      button inside a button is invalid HTML, and keeping the
                      value out here is what lets the pills sit against it. */}
                  <button
                    type="button"
                    onClick={() => chartLeg(row.pe)}
                    disabled={!row.pe?.symbol}
                    className="absolute inset-0 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-inset focus-visible:ring-ring disabled:pointer-events-none"
                    title={row.pe?.symbol ? `Chart ${row.pe.symbol}` : undefined}
                    aria-current={
                      activeSymbol === `${prefs.exchange}:${row.pe?.symbol}` ? true : undefined
                    }
                    aria-label={
                      row.pe?.symbol
                        ? `Chart ${row.pe.symbol}, ${metricLabel} ${metricOf(row.pe, metric)}`
                        : undefined
                    }
                  />
                  <span className="pointer-events-none relative tabular-nums">
                    {metricOf(row.pe, metric)}
                  </span>
                  <OrderPills leg={row.pe} onOrder={(leg, action) => setOrder({ leg, action })} />
                </div>
              </div>
            )
          })
        )}
      </div>

      {/* A chain that stopped updating an hour ago otherwise looks live. The
          poll is silent by design, so this line is the only thing that says
          the numbers above have stopped moving. */}
      {rows.length > 0 &&
        (chainError && lastUpdate ? (
          <p className="shrink-0 border-t px-2 py-1 text-[10px] text-amber-600 dark:text-amber-400">
            Not updating. Last loaded {lastUpdate.toLocaleTimeString()}
          </p>
        ) : marketOpen && !isStreaming && lastUpdate ? (
          // Streaming is the point of this panel. If the socket is not up the
          // numbers are still refreshed by the structural poll, just far more
          // slowly, and saying so beats letting them read as live.
          <p className="shrink-0 border-t px-2 py-1 text-[10px] text-amber-600 dark:text-amber-400">
            Not streaming. Last update {lastUpdate.toLocaleTimeString()}
          </p>
        ) : !marketOpen ? (
          // The panel already backs the poll off to a minute when the market is
          // shut; saying so is what stops a static chain reading as a stalled
          // one. The watchlist has carried this caption from the start.
          <p className="shrink-0 border-t px-2 py-1 text-[10px] text-muted-foreground">
            Market closed. Showing last traded prices.
          </p>
        ) : null)}

      {/* The same dialog pages/OptionChain.tsx opens. Quantity, product and
          price type are confirmed there, so a pill starts an order but never
          places one, and analyze mode is honoured the same way everywhere. */}
      <PlaceOrderDialog
        open={order !== null}
        onOpenChange={(next) => !next && setOrder(null)}
        symbol={order?.leg.symbol}
        exchange={prefs.exchange}
        action={order?.action}
        lotSize={order?.leg.lotsize ?? 1}
        tickSize={order?.leg.tick_size ?? 0.05}
        product="NRML"
        onSuccess={() => setOrder(null)}
      />
    </PanelShell>
  )
}
