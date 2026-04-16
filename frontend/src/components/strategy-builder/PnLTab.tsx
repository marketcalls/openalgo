import {
  Table,
  TableBody,
  TableCell,
  TableFooter,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import type { StrategyLeg } from '@/lib/strategyMath'
import { cn } from '@/lib/utils'

export interface PnLTabProps {
  legs: StrategyLeg[]
  currentPrices: Record<string, number>
}

function formatCurrency(v: number): string {
  if (!isFinite(v)) return '-'
  const abs = Math.abs(v)
  const sign = v < 0 ? '-' : v > 0 ? '+' : ''
  return `${sign}₹${abs.toLocaleString('en-IN', { maximumFractionDigits: 2 })}`
}

export function PnLTab({ legs, currentPrices }: PnLTabProps) {
  const rows = legs.map((leg) => {
    const current = currentPrices[leg.id] ?? leg.price
    const qty = leg.lots * leg.lotSize
    const sign = leg.side === 'BUY' ? 1 : -1
    const isClosed = leg.exitPrice !== undefined && leg.exitPrice > 0
    // Closed legs realise at their exit price; open legs mark-to-market
    // against the current LTP. Applies identically to futures and options.
    const effectivePrice = isClosed ? (leg.exitPrice ?? leg.price) : current
    const pnl = sign * (effectivePrice - leg.price) * qty
    return { leg, current, pnl, isClosed }
  })
  const total = rows.reduce((acc, r) => acc + r.pnl, 0)

  return (
    <div className="rounded-lg border bg-card p-4">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="text-xs">Position</TableHead>
            <TableHead className="text-xs text-right">Entry Price</TableHead>
            <TableHead className="text-xs text-right">Current Price</TableHead>
            <TableHead className="text-xs text-right">Exit Price</TableHead>
            <TableHead className="text-xs text-right">P&L</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.length === 0 && (
            <TableRow>
              <TableCell colSpan={5} className="py-8 text-center text-xs text-muted-foreground">
                No legs yet.
              </TableCell>
            </TableRow>
          )}
          {rows.map(({ leg, current, pnl, isClosed }) => (
            <TableRow
              key={leg.id}
              className={cn(!leg.active && 'opacity-50', isClosed && 'bg-rose-500/5')}
            >
              <TableCell className="text-xs font-medium">
                <span className="flex items-center gap-2">
                  <span>
                    {leg.side === 'BUY' ? '+' : '-'}
                    {leg.lots}x {leg.expiry}{' '}
                    {leg.segment === 'OPTION' ? `${leg.strike}${leg.optionType}` : 'FUT'}
                  </span>
                  {isClosed && (
                    <span className="rounded bg-rose-500/15 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-rose-700 dark:text-rose-400">
                      Closed
                    </span>
                  )}
                </span>
              </TableCell>
              <TableCell className="text-right text-xs tabular-nums">
                ₹{leg.price.toFixed(2)}
              </TableCell>
              <TableCell className="text-right text-xs tabular-nums">
                {isClosed ? (
                  <span className="text-muted-foreground">—</span>
                ) : (
                  `₹${current.toFixed(2)}`
                )}
              </TableCell>
              <TableCell className="text-right text-xs tabular-nums">
                {isClosed ? (
                  <span className="font-semibold">₹{(leg.exitPrice ?? 0).toFixed(2)}</span>
                ) : (
                  <span className="text-muted-foreground">—</span>
                )}
              </TableCell>
              <TableCell
                className={cn(
                  'text-right text-xs font-semibold tabular-nums',
                  pnl > 0 && 'text-emerald-600 dark:text-emerald-400',
                  pnl < 0 && 'text-rose-600 dark:text-rose-400'
                )}
              >
                {formatCurrency(pnl)}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
        {rows.length > 0 && (
          <TableFooter>
            <TableRow>
              <TableCell colSpan={4} className="text-xs font-semibold">
                Total P&L
              </TableCell>
              <TableCell
                className={cn(
                  'text-right text-xs font-bold tabular-nums',
                  total > 0 && 'text-emerald-600 dark:text-emerald-400',
                  total < 0 && 'text-rose-600 dark:text-rose-400'
                )}
              >
                {formatCurrency(total)}
              </TableCell>
            </TableRow>
          </TableFooter>
        )}
      </Table>
    </div>
  )
}
