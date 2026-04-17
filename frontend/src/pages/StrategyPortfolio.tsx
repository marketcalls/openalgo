import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  ArrowLeft,
  Briefcase,
  ChevronDown,
  FlaskConical,
  Play,
  Trash2,
} from 'lucide-react'
import { apiClient } from '@/api/client'
import { useAuthStore } from '@/stores/authStore'
import { Button } from '@/components/ui/button'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { showToast } from '@/utils/toast'
import { cn } from '@/lib/utils'
import {
  strategyPortfolioApi,
  type PortfolioEntry,
  type PortfolioLeg,
  type Watchlist,
} from '@/api/strategy-portfolio'

// Map a portfolio entry's `exchange` (which may be NSE_INDEX / BSE_INDEX etc.
// since it's the index underlying's exchange) to the F&O exchange that the
// broker uses to look up option/future instruments.
function optionExchangeFor(exchange: string): string {
  const e = exchange.toUpperCase()
  if (e === 'NFO' || e === 'NSE_INDEX') return 'NFO'
  if (e === 'BFO' || e === 'BSE_INDEX') return 'BFO'
  return e
}

const MONTHS: Record<string, number> = {
  JAN: 0, FEB: 1, MAR: 2, APR: 3, MAY: 4, JUN: 5,
  JUL: 6, AUG: 7, SEP: 8, OCT: 9, NOV: 10, DEC: 11,
}

/**
 * Parse a leg expiry in the canonical DDMMMYY format (e.g. "21APR26") to a
 * Date at end-of-day IST. Returns null if the string isn't parseable — in that
 * case we treat the leg as NOT expired so the live-price fetch still runs.
 */
function parseExpiry(expiry: string): Date | null {
  const m = /^(\d{2})([A-Z]{3})(\d{2})$/.exec(expiry.toUpperCase())
  if (!m) return null
  const day = Number(m[1])
  const mon = MONTHS[m[2]]
  if (mon === undefined) return null
  const year = 2000 + Number(m[3])
  // End of expiry day — only skip quotes once the whole day has passed.
  return new Date(year, mon, day, 23, 59, 59)
}

/**
 * A leg is "expired" when today is after its expiry date. Once expired the
 * option/future symbol will not be found in the master contract and any
 * broker quote call returns 404 — so we must NOT request quotes for these.
 */
function isExpired(leg: PortfolioLeg, now: Date): boolean {
  const d = parseExpiry(leg.expiry)
  if (!d) return false
  return now > d
}

/** P&L for a single leg given a current LTP. Open legs MTM, closed legs realised. */
function legPnl(leg: PortfolioLeg, currentLtp: number | undefined): number {
  const sign = leg.side === 'BUY' ? 1 : -1
  const qty = leg.lots * leg.lotSize
  if (leg.exitPrice !== undefined && leg.exitPrice > 0) {
    return sign * (leg.exitPrice - leg.price) * qty
  }
  if (currentLtp === undefined) return 0
  return sign * (currentLtp - leg.price) * qty
}

function formatDate(iso: string | null): string {
  if (!iso) return ''
  try {
    const d = new Date(iso)
    return d.toLocaleString('en-IN', {
      day: '2-digit',
      month: 'short',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return iso
  }
}

function describeLeg(leg: PortfolioEntry['legs'][number]): string {
  const sign = leg.side === 'BUY' ? '+' : '-'
  const desc =
    leg.segment === 'OPTION' && leg.strike !== undefined && leg.optionType
      ? `${leg.strike}${leg.optionType}`
      : 'FUT'
  return `${sign}${leg.lots}× ${leg.expiry} ${desc}`
}

function legCount(entry: PortfolioEntry): { long: number; short: number } {
  let long = 0
  let short = 0
  for (const leg of entry.legs) {
    if (leg.side === 'BUY') long++
    else short++
  }
  return { long, short }
}

export default function StrategyPortfolio() {
  const navigate = useNavigate()
  const { apiKey } = useAuthStore()
  const [tab, setTab] = useState<Watchlist>('mytrades')
  const [myTrades, setMyTrades] = useState<PortfolioEntry[]>([])
  const [simulation, setSimulation] = useState<PortfolioEntry[]>([])
  const [isLoading, setIsLoading] = useState(false)
  // Entries are collapsed by default — only ids in this set are expanded.
  // Keyed by entry id for both watchlists; ids are unique across the table.
  const [expandedIds, setExpandedIds] = useState<Set<number>>(new Set())
  // Live LTP cache for all open legs across both watchlists.
  const [pricesBySymbol, setPricesBySymbol] = useState<Record<string, number>>({})
  // Delete confirmation dialog state. null = closed.
  const [pendingDelete, setPendingDelete] = useState<PortfolioEntry | null>(null)
  const [isDeleting, setIsDeleting] = useState(false)

  const load = useCallback(async () => {
    setIsLoading(true)
    try {
      const [mt, sim] = await Promise.all([
        strategyPortfolioApi.list('mytrades').catch(() => []),
        strategyPortfolioApi.list('simulation').catch(() => []),
      ])
      setMyTrades(mt)
      setSimulation(sim)
    } finally {
      setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  // Fetch live LTPs for all open legs across both watchlists via /multiquotes.
  // One request for the whole page; closed legs are skipped since their P&L
  // is already locked in.
  useEffect(() => {
    if (!apiKey) return
    // Expired contracts are no longer in the master contract — calling the
    // broker for their LTP returns 404 / errors. Skip them entirely; their
    // row will show "—" for Current Price and the last-known entry → exit
    // still drives P&L for closed legs.
    const now = new Date()
    const pairs = new Map<string, { symbol: string; exchange: string }>()
    for (const entry of [...myTrades, ...simulation]) {
      const ex = optionExchangeFor(entry.exchange)
      for (const leg of entry.legs) {
        if (leg.exitPrice !== undefined && leg.exitPrice > 0) continue
        if (!leg.symbol) continue
        if (isExpired(leg, now)) continue
        pairs.set(leg.symbol, { symbol: leg.symbol, exchange: ex })
      }
    }
    if (pairs.size === 0) {
      setPricesBySymbol({})
      return
    }
    let cancelled = false
    ;(async () => {
      try {
        const res = await apiClient.post<{
          status: string
          results?: Array<{ symbol: string; data?: { ltp?: number } }>
        }>(
          '/multiquotes',
          { apikey: apiKey, symbols: Array.from(pairs.values()) },
          { validateStatus: () => true }
        )
        if (cancelled) return
        if (res.data.status === 'success' && res.data.results) {
          const map: Record<string, number> = {}
          for (const r of res.data.results) {
            if (r.data?.ltp !== undefined && r.data.ltp > 0) {
              map[r.symbol] = r.data.ltp
            }
          }
          setPricesBySymbol(map)
        }
      } catch {
        /* non-fatal — card falls back to "—" for Current P&L */
      }
    })()
    return () => {
      cancelled = true
    }
  }, [apiKey, myTrades, simulation])

  /**
   * Current P&L + open/closed status for a strategy.
   * Status:
   *  - 'open'   = every leg open
   *  - 'partial'= at least one leg closed but others open → still green
   *  - 'closed' = every leg closed → red
   */
  const getEntryMetrics = useMemo(() => {
    return (entry: PortfolioEntry) => {
      let pnl = 0
      let closedCount = 0
      for (const leg of entry.legs) {
        pnl += legPnl(leg, pricesBySymbol[leg.symbol])
        if (leg.exitPrice !== undefined && leg.exitPrice > 0) closedCount++
      }
      const status: 'open' | 'partial' | 'closed' =
        entry.legs.length === 0
          ? 'open'
          : closedCount === entry.legs.length
            ? 'closed'
            : closedCount > 0
              ? 'partial'
              : 'open'
      return { pnl, status }
    }
  }, [pricesBySymbol])

  const confirmDelete = async () => {
    if (!pendingDelete) return
    setIsDeleting(true)
    try {
      await strategyPortfolioApi.remove(pendingDelete.id)
      showToast.success('Deleted')
      setPendingDelete(null)
      load()
    } catch (err) {
      showToast.error(err instanceof Error ? err.message : 'Delete failed')
    } finally {
      setIsDeleting(false)
    }
  }

  const openInBuilder = (entry: PortfolioEntry) => {
    navigate(`/tools/strategy?load=${entry.id}`)
  }

  const toggleRow = useCallback((id: number) => {
    setExpandedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }, [])

  const expandAll = useCallback((items: PortfolioEntry[]) => {
    setExpandedIds((prev) => {
      const next = new Set(prev)
      for (const e of items) next.add(e.id)
      return next
    })
  }, [])

  const collapseAll = useCallback((items: PortfolioEntry[]) => {
    setExpandedIds((prev) => {
      const next = new Set(prev)
      for (const e of items) next.delete(e.id)
      return next
    })
  }, [])

  const tabConfig: Record<
    Watchlist,
    { label: string; icon: typeof Briefcase; accent: string; items: PortfolioEntry[] }
  > = {
    mytrades: {
      label: 'MyTrades',
      icon: Briefcase,
      accent: 'text-amber-600 dark:text-amber-400',
      items: myTrades,
    },
    simulation: {
      label: 'Simulation',
      icon: FlaskConical,
      accent: 'text-violet-600 dark:text-violet-400',
      items: simulation,
    },
  }

  return (
    <div className="space-y-4 py-6">
      <div className="flex items-center justify-between">
        <div className="flex items-start gap-3">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => navigate('/tools/strategy')}
            className="mt-1"
          >
            <ArrowLeft className="mr-1.5 h-3.5 w-3.5" />
            Back
          </Button>
          <div>
            <h1 className="text-2xl font-bold">Strategy Portfolio</h1>
            <p className="text-sm text-muted-foreground">
              Saved strategies across your two watchlists.
            </p>
          </div>
        </div>
      </div>

      <Tabs value={tab} onValueChange={(v) => setTab(v as Watchlist)}>
        <TabsList className="grid w-full max-w-md grid-cols-2">
          {(Object.keys(tabConfig) as Watchlist[]).map((key) => {
            const cfg = tabConfig[key]
            const Icon = cfg.icon
            return (
              <TabsTrigger key={key} value={key} className="gap-2">
                <Icon className={cn('h-3.5 w-3.5', tab === key && cfg.accent)} />
                {cfg.label}
                <span className="ml-1 rounded-full bg-muted px-1.5 py-0.5 text-[10px] font-semibold">
                  {cfg.items.length}
                </span>
              </TabsTrigger>
            )
          })}
        </TabsList>

        {(Object.keys(tabConfig) as Watchlist[]).map((key) => {
          const cfg = tabConfig[key]
          return (
            <TabsContent key={key} value={key} className="pt-4">
              {isLoading ? (
                <div className="flex h-40 items-center justify-center text-sm text-muted-foreground">
                  Loading…
                </div>
              ) : cfg.items.length === 0 ? (
                <div className="flex h-40 flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed text-sm text-muted-foreground">
                  <cfg.icon className="h-6 w-6 opacity-40" />
                  <p>No strategies in {cfg.label} yet.</p>
                  <Button variant="outline" size="sm" onClick={() => navigate('/tools/strategy')}>
                    Open Strategy Builder
                  </Button>
                </div>
              ) : (
                <div className="space-y-3">
                  {(() => {
                    // Cumulative P&L across every strategy in this watchlist.
                    let cum = 0
                    for (const e of cfg.items) cum += getEntryMetrics(e).pnl
                    const tone =
                      cum > 0
                        ? 'text-emerald-600 dark:text-emerald-400'
                        : cum < 0
                          ? 'text-rose-600 dark:text-rose-400'
                          : 'text-muted-foreground'
                    const sign = cum > 0 ? '+' : cum < 0 ? '-' : ''
                    return (
                      <div className="flex items-center justify-between gap-3 rounded-md border bg-card px-4 py-2.5 text-xs">
                        <span className="font-medium text-muted-foreground">
                          Cumulative P&amp;L · {cfg.label}
                        </span>
                        <span className={cn('text-base font-bold tabular-nums', tone)}>
                          {sign}₹
                          {Math.abs(cum).toLocaleString('en-IN', { maximumFractionDigits: 0 })}
                        </span>
                      </div>
                    )
                  })()}
                  {/* Expand/Collapse toolbar. Matches the "EXPAND ALL / COLLAPSE ALL"
                      pattern from the reference UI. */}
                  <div className="flex items-center justify-between gap-3 rounded-md border bg-muted/40 px-4 py-2 text-xs">
                    <span className="font-medium text-muted-foreground">
                      {cfg.items.length} strateg{cfg.items.length === 1 ? 'y' : 'ies'}
                    </span>
                    <div className="flex items-center gap-3">
                      <button
                        type="button"
                        onClick={() => expandAll(cfg.items)}
                        className="font-semibold uppercase tracking-wide text-primary hover:underline"
                      >
                        Expand All
                      </button>
                      <span className="text-muted-foreground/60">·</span>
                      <button
                        type="button"
                        onClick={() => collapseAll(cfg.items)}
                        className="font-semibold uppercase tracking-wide text-muted-foreground hover:underline"
                      >
                        Collapse All
                      </button>
                    </div>
                  </div>

                  <ul className="space-y-3">
                    {cfg.items.map((entry) => {
                      const counts = legCount(entry)
                      const expanded = expandedIds.has(entry.id)
                      const { pnl, status } = getEntryMetrics(entry)
                      const pnlKnown = Object.keys(pricesBySymbol).length > 0 || status === 'closed'
                      return (
                        <li
                          key={entry.id}
                          className="overflow-hidden rounded-lg border bg-card transition-shadow hover:shadow-md"
                        >
                          {/* Clickable summary row — plain div so the inner action
                              buttons (Open, Delete) remain real <button>s. Accessibility
                              handled via role/tabIndex/onKeyDown. */}
                          {/* biome-ignore lint/a11y/useSemanticElements: row contains nested <button> actions (View, Delete), so it cannot itself be a <button>. Accessibility is provided via role/tabIndex/onKeyDown. */}
                          <div
                            role="button"
                            tabIndex={0}
                            onClick={() => toggleRow(entry.id)}
                            onKeyDown={(e) => {
                              if (e.key === 'Enter' || e.key === ' ') {
                                e.preventDefault()
                                toggleRow(entry.id)
                              }
                            }}
                            aria-expanded={expanded}
                            className="flex flex-wrap items-start gap-3 p-4 text-left cursor-pointer outline-none focus-visible:ring-2 focus-visible:ring-ring"
                          >
                            <ChevronDown
                              className={cn(
                                'mt-1 h-4 w-4 shrink-0 text-muted-foreground transition-transform',
                                expanded && 'rotate-180'
                              )}
                            />
                            <div className="flex min-w-0 flex-1 flex-col gap-1">
                              <div className="flex items-center gap-2">
                                <span className="truncate text-base font-semibold">
                                  {entry.name}
                                </span>
                                <span className="rounded bg-muted px-2 py-0.5 text-[10px] font-semibold uppercase">
                                  {entry.underlying}
                                </span>
                                <span className="text-[11px] text-muted-foreground">
                                  {entry.exchange}
                                </span>
                              </div>
                              <p className="text-[11px] text-muted-foreground">
                                Updated {formatDate(entry.updated_at)} · {entry.legs.length} leg
                                {entry.legs.length === 1 ? '' : 's'}
                                {counts.long > 0 && ` · ${counts.long} long`}
                                {counts.short > 0 && ` · ${counts.short} short`}
                              </p>
                            </div>

                            {/* Status pill + Current P&L — visible even when collapsed. */}
                            <div className="flex items-center gap-3 pr-1">
                              <span
                                title={
                                  status === 'open'
                                    ? 'All legs open'
                                    : status === 'partial'
                                      ? 'Partially closed — some legs still open'
                                      : 'All legs closed'
                                }
                                className={cn(
                                  'rounded px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide',
                                  status === 'open' &&
                                    'bg-emerald-500/15 text-emerald-700 dark:text-emerald-400',
                                  status === 'partial' &&
                                    'bg-amber-500/15 text-amber-700 dark:text-amber-400',
                                  status === 'closed' &&
                                    'bg-rose-500/15 text-rose-700 dark:text-rose-400'
                                )}
                              >
                                {status}
                              </span>
                              <span
                                className={cn(
                                  'min-w-[80px] text-right text-sm font-semibold tabular-nums',
                                  pnl > 0 && 'text-emerald-600 dark:text-emerald-400',
                                  pnl < 0 && 'text-rose-600 dark:text-rose-400',
                                  pnl === 0 && 'text-muted-foreground'
                                )}
                              >
                                {pnlKnown
                                  ? `${pnl >= 0 ? '+' : '-'}₹${Math.abs(pnl).toLocaleString('en-IN', {
                                      maximumFractionDigits: 0,
                                    })}`
                                  : '—'}
                              </span>
                            </div>

                            <div className="flex items-center gap-2">
                              <Button
                                size="sm"
                                className="h-8 text-xs"
                                onClick={(e) => {
                                  e.stopPropagation()
                                  openInBuilder(entry)
                                }}
                              >
                                <Play className="mr-1 h-3 w-3" />
                                View
                              </Button>
                              <Button
                                size="icon"
                                variant="ghost"
                                className="h-8 w-8 text-rose-500 hover:bg-rose-500/10 hover:text-rose-600"
                                aria-label="Delete"
                                onClick={(e) => {
                                  e.stopPropagation()
                                  setPendingDelete(entry)
                                }}
                              >
                                <Trash2 className="h-3.5 w-3.5" />
                              </Button>
                            </div>
                          </div>

                          {expanded && (
                            <div className="border-t">
                              <table className="w-full text-xs">
                                <thead className="bg-muted/40 text-muted-foreground">
                                  <tr>
                                    <th className="px-4 py-2 text-left font-medium">Ticker</th>
                                    <th className="px-3 py-2 text-left font-medium">Trade Type</th>
                                    <th className="px-3 py-2 text-right font-medium">Qty</th>
                                    <th className="px-3 py-2 text-right font-medium">Entry Price</th>
                                    <th className="px-3 py-2 text-right font-medium">Current Price</th>
                                    <th className="px-3 py-2 text-right font-medium">Exit Price</th>
                                    <th className="px-3 py-2 text-right font-medium">P&amp;L</th>
                                    <th className="px-3 py-2 text-center font-medium">Status</th>
                                  </tr>
                                </thead>
                                <tbody className="divide-y">
                                  {entry.legs.map((leg, i) => {
                                    const isClosed =
                                      leg.exitPrice !== undefined && leg.exitPrice > 0
                                    const legExpired = !isClosed && isExpired(leg, new Date())
                                    const currentLtp = pricesBySymbol[leg.symbol]
                                    const qty = leg.lots * leg.lotSize
                                    const pnl = legPnl(leg, currentLtp)
                                    return (
                                      <tr
                                        key={i}
                                        className={cn(isClosed && 'bg-rose-500/5')}
                                      >
                                        <td className="px-4 py-2 font-medium">
                                          <div className="flex flex-col">
                                            <span className={cn(isClosed && 'line-through text-muted-foreground')}>
                                              {leg.symbol || describeLeg(leg)}
                                            </span>
                                            <span className="text-[10px] text-muted-foreground">
                                              {leg.expiry}
                                            </span>
                                          </div>
                                        </td>
                                        <td className="px-3 py-2">
                                          <span
                                            className={cn(
                                              'inline-flex items-center justify-center rounded px-2 py-0.5 text-[10px] font-semibold uppercase',
                                              leg.side === 'BUY'
                                                ? 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-400'
                                                : 'bg-rose-500/15 text-rose-700 dark:text-rose-400'
                                            )}
                                          >
                                            {leg.side}
                                          </span>
                                        </td>
                                        <td className="px-3 py-2 text-right tabular-nums">
                                          {qty}
                                          <span className="ml-1 text-[10px] text-muted-foreground">
                                            ({leg.lots}×{leg.lotSize})
                                          </span>
                                        </td>
                                        <td className="px-3 py-2 text-right tabular-nums">
                                          ₹{leg.price.toFixed(2)}
                                        </td>
                                        <td className="px-3 py-2 text-right tabular-nums">
                                          {isClosed
                                            ? '—'
                                            : currentLtp !== undefined
                                              ? `₹${currentLtp.toFixed(2)}`
                                              : '—'}
                                        </td>
                                        <td className="px-3 py-2 text-right tabular-nums">
                                          {isClosed
                                            ? `₹${(leg.exitPrice ?? 0).toFixed(2)}`
                                            : '—'}
                                        </td>
                                        <td
                                          className={cn(
                                            'px-3 py-2 text-right font-semibold tabular-nums',
                                            pnl > 0 && 'text-emerald-600 dark:text-emerald-400',
                                            pnl < 0 && 'text-rose-600 dark:text-rose-400'
                                          )}
                                        >
                                          {pnl === 0 && !isClosed && currentLtp === undefined
                                            ? '—'
                                            : `${pnl >= 0 ? '+' : '-'}₹${Math.abs(pnl).toLocaleString(
                                                'en-IN',
                                                { maximumFractionDigits: 0 }
                                              )}`}
                                        </td>
                                        <td className="px-3 py-2 text-center">
                                          <span
                                            className={cn(
                                              'rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase',
                                              isClosed
                                                ? 'bg-rose-500/15 text-rose-700 dark:text-rose-400'
                                                : legExpired
                                                  ? 'bg-muted text-muted-foreground'
                                                  : 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-400'
                                            )}
                                            title={
                                              legExpired
                                                ? 'Contract has expired — live quote unavailable'
                                                : undefined
                                            }
                                          >
                                            {isClosed ? 'Closed' : legExpired ? 'Expired' : 'Open'}
                                          </span>
                                        </td>
                                      </tr>
                                    )
                                  })}
                                </tbody>
                              </table>
                            </div>
                          )}
                        </li>
                      )
                    })}
                  </ul>
                </div>
              )}
            </TabsContent>
          )
        })}
      </Tabs>

      <AlertDialog
        open={pendingDelete !== null}
        onOpenChange={(open) => {
          if (!open && !isDeleting) setPendingDelete(null)
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete strategy?</AlertDialogTitle>
            <AlertDialogDescription>
              This will permanently remove{' '}
              <span className="font-semibold text-foreground">
                {pendingDelete?.name}
              </span>{' '}
              from your portfolio. This action cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={isDeleting}>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={(e) => {
                e.preventDefault()
                confirmDelete()
              }}
              disabled={isDeleting}
              className="bg-rose-500 text-white hover:bg-rose-600"
            >
              {isDeleting ? 'Deleting…' : 'Delete'}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
