import { useEffect, useMemo, useRef, useState } from 'react'
import { Radio, Wifi, WifiOff } from 'lucide-react'
import {
  Table,
  TableBody,
  TableCell,
  TableFooter,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { useMarketData } from '@/hooks/useMarketData'
import type { StrategyLeg } from '@/lib/strategyMath'
import { cn } from '@/lib/utils'

export interface PnLTabProps {
  legs: StrategyLeg[]
  /** F&O exchange (NFO/BFO/MCX) used to subscribe leg symbols on the WebSocket. */
  fnoExchange: string
  /** Snapshot prices from the option chain — used only until the first WS tick. */
  fallbackPrices: Record<string, number>
}

function formatCurrency(v: number): string {
  if (!isFinite(v)) return '—'
  const abs = Math.abs(v)
  const sign = v < 0 ? '-' : v > 0 ? '+' : ''
  return `${sign}₹${abs.toLocaleString('en-IN', { maximumFractionDigits: 2 })}`
}

/** Briefly highlight a cell whenever its numeric value changes (WS tick). */
function useFlashOnChange(value: number | undefined): 'up' | 'down' | null {
  const prev = useRef<number | undefined>(value)
  const [flash, setFlash] = useState<'up' | 'down' | null>(null)

  useEffect(() => {
    if (value === undefined || prev.current === undefined) {
      prev.current = value
      return
    }
    if (value !== prev.current) {
      setFlash(value > prev.current ? 'up' : 'down')
      prev.current = value
      const t = setTimeout(() => setFlash(null), 450)
      return () => clearTimeout(t)
    }
  }, [value])

  return flash
}

function PriceCell({
  value,
  isClosed,
}: {
  value: number | undefined
  isClosed: boolean
}) {
  const flash = useFlashOnChange(isClosed ? undefined : value)
  if (isClosed || value === undefined) {
    return <span className="text-muted-foreground">—</span>
  }
  return (
    <span
      className={cn(
        'inline-block rounded px-1.5 py-0.5 tabular-nums transition-colors duration-300',
        flash === 'up' && 'bg-emerald-500/20 text-emerald-700 dark:text-emerald-300',
        flash === 'down' && 'bg-rose-500/20 text-rose-700 dark:text-rose-300'
      )}
    >
      ₹{value.toFixed(2)}
    </span>
  )
}

function PnlCell({ value }: { value: number }) {
  const flash = useFlashOnChange(value)
  return (
    <span
      className={cn(
        'inline-block rounded px-1.5 py-0.5 font-semibold tabular-nums transition-colors duration-300',
        value > 0 && 'text-emerald-600 dark:text-emerald-400',
        value < 0 && 'text-rose-600 dark:text-rose-400',
        flash === 'up' && 'bg-emerald-500/20',
        flash === 'down' && 'bg-rose-500/20'
      )}
    >
      {formatCurrency(value)}
    </span>
  )
}

export function PnLTab({ legs, fnoExchange, fallbackPrices }: PnLTabProps) {
  // Only active (user-included) legs are considered "open" for this tab.
  // Excluded legs don't appear in the table, don't contribute to the total,
  // and don't consume a WebSocket subscription.
  const openLegs = useMemo(
    () =>
      legs.filter(
        (l) => l.active && !(l.exitPrice !== undefined && l.exitPrice > 0) && l.symbol
      ),
    [legs]
  )

  // Build the subscription list from open legs only. Deduplicated on
  // (exchange, symbol). The memo ensures:
  //   • adding a new leg subscribes its symbol,
  //   • excluding a leg (uncheck) unsubscribes its symbol,
  //   • setting an exitPrice on a leg unsubscribes its symbol,
  //   • deleting a leg unsubscribes its symbol,
  //   • when no open legs remain, the hook is disabled and no WS traffic
  //     flows for this page (MarketDataManager ref-counts, so shared
  //     subscriptions elsewhere are unaffected).
  const legSubscriptions = useMemo(() => {
    const seen = new Set<string>()
    const out: Array<{ symbol: string; exchange: string }> = []
    for (const leg of openLegs) {
      const key = `${fnoExchange}:${leg.symbol}`
      if (seen.has(key)) continue
      seen.add(key)
      out.push({ symbol: leg.symbol, exchange: fnoExchange })
    }
    return out
  }, [openLegs, fnoExchange])

  const {
    data: marketData,
    isConnected,
    isPaused,
    isFallbackMode,
  } = useMarketData({
    symbols: legSubscriptions,
    mode: 'LTP',
    enabled: legSubscriptions.length > 0,
  })

  // Rows to display: included legs only. Closed legs stay (so user can see
  // their realised P&L) until they're explicitly excluded via the Positions
  // panel checkbox. Excluded legs disappear entirely.
  //
  // Price resolution per row:
  //   1) Live WebSocket LTP (true real-time),
  //   2) Option-chain snapshot (fallback until first tick),
  //   3) Leg entry price (last resort).
  // Closed legs don't need a current price — realised P&L is computed
  // directly from exitPrice vs entry.
  const rows = useMemo(() => {
    return legs
      .filter((leg) => leg.active)
      .map((leg) => {
        const isClosed = leg.exitPrice !== undefined && leg.exitPrice > 0
        let current: number | undefined
        if (!isClosed && leg.symbol) {
          const ws = marketData.get(`${fnoExchange}:${leg.symbol}`)
          if (ws?.data?.ltp !== undefined && ws.data.ltp > 0) {
            current = ws.data.ltp
          } else if (fallbackPrices[leg.id] !== undefined) {
            current = fallbackPrices[leg.id]
          } else {
            current = leg.price
          }
        }
        const qty = leg.lots * leg.lotSize
        const sign = leg.side === 'BUY' ? 1 : -1
        const effective = isClosed ? (leg.exitPrice ?? leg.price) : (current ?? leg.price)
        const pnl = sign * (effective - leg.price) * qty
        return { leg, current, pnl, isClosed }
      })
  }, [legs, marketData, fnoExchange, fallbackPrices])

  const total = useMemo(() => rows.reduce((acc, r) => acc + r.pnl, 0), [rows])
  const openCount = rows.filter((r) => !r.isClosed).length
  const closedCount = rows.filter((r) => r.isClosed).length
  const excludedCount = legs.length - rows.length
  const hasOpen = openCount > 0

  const streamingState: 'streaming' | 'paused' | 'fallback' | 'connecting' | 'idle' = !hasOpen
    ? 'idle'
    : isConnected
      ? 'streaming'
      : isPaused
        ? 'paused'
        : isFallbackMode
          ? 'fallback'
          : 'connecting'

  return (
    <div className="overflow-hidden rounded-xl border bg-card shadow-sm">
      {/* Header — live streaming status */}
      <div className="flex items-center justify-between gap-2 border-b bg-gradient-to-r from-muted/30 to-transparent px-4 py-2.5">
        <div className="flex items-center gap-2">
          <span className="text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
            Live P&amp;L
          </span>
          {streamingState === 'streaming' && (
            <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500/15 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-emerald-700 dark:text-emerald-400">
              <span className="relative flex h-1.5 w-1.5">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
                <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-emerald-500" />
              </span>
              Streaming
            </span>
          )}
          {streamingState === 'paused' && (
            <span className="inline-flex items-center gap-1 rounded-full bg-amber-500/15 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-amber-700 dark:text-amber-400">
              <Radio className="h-2.5 w-2.5" />
              Paused
            </span>
          )}
          {streamingState === 'fallback' && (
            <span className="inline-flex items-center gap-1 rounded-full bg-sky-500/15 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-sky-700 dark:text-sky-400">
              <Wifi className="h-2.5 w-2.5" />
              Polling
            </span>
          )}
          {streamingState === 'connecting' && (
            <span className="inline-flex items-center gap-1 rounded-full bg-muted px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
              <WifiOff className="h-2.5 w-2.5" />
              Connecting
            </span>
          )}
          {streamingState === 'idle' && (
            <span className="inline-flex items-center gap-1 rounded-full bg-muted px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
              Idle
            </span>
          )}
        </div>
        <span className="text-[10px] tabular-nums text-muted-foreground">
          {openCount} open · {closedCount} closed
          {excludedCount > 0 && ` · ${excludedCount} excluded`}
        </span>
      </div>

      {/* table-fixed + explicit column widths prevent layout jitter when
          streaming ticks change the character-length of Current/P&L cells
          (e.g. ₹29.20 → ₹29.5 → ₹129.00). Each numeric column reserves
          enough space for realistic maximum values and right-aligns content
          within; the Position column is the only fluid one. */}
      <Table className="table-fixed">
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead className="w-[72px] text-center text-[10px] font-semibold uppercase tracking-wider">
              Action
            </TableHead>
            <TableHead className="w-[56px] text-right text-[10px] font-semibold uppercase tracking-wider">
              Lots
            </TableHead>
            <TableHead className="text-[10px] font-semibold uppercase tracking-wider">
              Position
            </TableHead>
            <TableHead className="w-[96px] text-right text-[10px] font-semibold uppercase tracking-wider">
              Entry
            </TableHead>
            <TableHead className="w-[112px] text-right text-[10px] font-semibold uppercase tracking-wider">
              Current
            </TableHead>
            <TableHead className="w-[96px] text-right text-[10px] font-semibold uppercase tracking-wider">
              Exit
            </TableHead>
            <TableHead className="w-[128px] text-right text-[10px] font-semibold uppercase tracking-wider">
              P&amp;L
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.length === 0 && (
            <TableRow>
              <TableCell colSpan={7} className="py-8 text-center text-xs text-muted-foreground">
                {legs.length === 0
                  ? 'No legs yet.'
                  : 'All legs are excluded. Re-include at least one from the Positions panel.'}
              </TableCell>
            </TableRow>
          )}
          {rows.map(({ leg, current, pnl, isClosed }) => (
            <TableRow
              key={leg.id}
              className={cn(!leg.active && 'opacity-50', isClosed && 'bg-rose-500/5')}
            >
              <TableCell className="text-center">
                <span
                  className={cn(
                    'inline-flex h-5 w-9 items-center justify-center rounded-md text-[10px] font-bold uppercase tracking-wider ring-1 ring-inset',
                    leg.side === 'BUY'
                      ? 'bg-emerald-500/15 text-emerald-700 ring-emerald-500/20 dark:text-emerald-400'
                      : 'bg-rose-500/15 text-rose-700 ring-rose-500/20 dark:text-rose-400'
                  )}
                  title={leg.side === 'BUY' ? 'Buy' : 'Sell'}
                >
                  {leg.side === 'BUY' ? 'B' : 'S'}
                </span>
              </TableCell>
              <TableCell className="text-right text-xs font-semibold tabular-nums">
                {leg.lots}
              </TableCell>
              <TableCell className="min-w-0 text-xs font-medium">
                <span className="flex min-w-0 items-center gap-2 truncate">
                  <span className="font-semibold">
                    {leg.segment === 'OPTION' ? `${leg.strike}${leg.optionType}` : 'FUT'}
                  </span>
                  <span className="tabular-nums text-muted-foreground">{leg.expiry}</span>
                  {isClosed && (
                    <span className="rounded bg-rose-500/15 px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wider text-rose-700 dark:text-rose-400">
                      Closed
                    </span>
                  )}
                </span>
              </TableCell>
              <TableCell className="whitespace-nowrap text-right text-xs tabular-nums">
                ₹{leg.price.toFixed(2)}
              </TableCell>
              <TableCell className="whitespace-nowrap text-right text-xs">
                <PriceCell value={current} isClosed={isClosed} />
              </TableCell>
              <TableCell className="whitespace-nowrap text-right text-xs tabular-nums">
                {isClosed ? (
                  <span className="font-semibold">₹{(leg.exitPrice ?? 0).toFixed(2)}</span>
                ) : (
                  <span className="text-muted-foreground">—</span>
                )}
              </TableCell>
              <TableCell className="whitespace-nowrap text-right text-xs">
                <PnlCell value={pnl} />
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
        {rows.length > 0 && (
          <TableFooter>
            <TableRow>
              <TableCell
                colSpan={6}
                className="text-[10px] font-semibold uppercase tracking-wider"
              >
                Total P&amp;L
              </TableCell>
              <TableCell className="whitespace-nowrap text-right text-sm">
                <PnlCell value={total} />
              </TableCell>
            </TableRow>
          </TableFooter>
        )}
      </Table>
    </div>
  )
}
