import { BarChart3, RefreshCw, TrendingDown, TrendingUp } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { strategyDashboardApi } from '@/api/strategy-dashboard'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableFooter,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { StatusBadge } from './StatusBadge'

interface TradesPanelProps {
  strategyId: number
  strategyName: string
}

const currencyFormat = new Intl.NumberFormat('en-IN', {
  style: 'currency',
  currency: 'INR',
  maximumFractionDigits: 2,
})

function formatTime(dateStr: string): string {
  return new Date(dateStr).toLocaleString('en-IN', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    day: '2-digit',
    month: 'short',
  })
}

export function TradesPanel({ strategyId, strategyName }: TradesPanelProps) {
  const { data: trades = [], isLoading, refetch } = useQuery({
    queryKey: ['strategy-trades', strategyId],
    queryFn: () => strategyDashboardApi.getTrades(strategyId),
  })

  const totalPnl = trades.reduce((sum, t) => sum + (t.pnl ?? 0), 0)
  const winCount = trades.filter((t) => t.pnl !== null && t.pnl > 0).length
  const lossCount = trades.filter((t) => t.pnl !== null && t.pnl < 0).length

  if (isLoading) {
    return (
      <div className="space-y-2">
        {Array.from({ length: 5 }).map((_, i) => (
          <Skeleton key={i} className="h-10 w-full" />
        ))}
      </div>
    )
  }

  if (trades.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
        <BarChart3 className="h-10 w-10 mb-3 opacity-40" />
        <p className="text-sm">No trades recorded yet for {strategyName}</p>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {/* Summary stats + refresh */}
      <div className="flex items-center justify-between">
        <div className="flex flex-wrap gap-2">
          <Badge variant="outline">{trades.length} total</Badge>
          <Badge variant="outline" className="text-green-600">
            <TrendingUp className="h-3 w-3 mr-1" /> {winCount} wins
          </Badge>
          <Badge variant="outline" className="text-red-600">
            <TrendingDown className="h-3 w-3 mr-1" /> {lossCount} losses
          </Badge>
        </div>
        <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => refetch()}>
          <RefreshCw className="h-3.5 w-3.5" />
        </Button>
      </div>

      <div className="relative w-full overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Time</TableHead>
              <TableHead>Symbol</TableHead>
              <TableHead>Action</TableHead>
              <TableHead className="text-right">Qty</TableHead>
              <TableHead className="text-right">Price</TableHead>
              <TableHead>Type</TableHead>
              <TableHead>Exit Reason</TableHead>
              <TableHead className="text-right">P&L</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {trades.map((trade) => (
              <TableRow key={trade.id}>
                <TableCell className="text-xs text-muted-foreground whitespace-nowrap">
                  {formatTime(trade.created_at)}
                </TableCell>
                <TableCell className="font-medium">{trade.symbol}</TableCell>
                <TableCell>
                  <Badge
                    className={
                      trade.action === 'BUY'
                        ? 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400'
                        : 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400'
                    }
                  >
                    {trade.action}
                  </Badge>
                </TableCell>
                <TableCell className="text-right font-mono tabular-nums">
                  {trade.quantity}
                </TableCell>
                <TableCell className="text-right font-mono tabular-nums">
                  {currencyFormat.format(trade.price)}
                </TableCell>
                <TableCell>
                  <Badge variant="outline" className="text-xs">
                    {trade.trade_type}
                  </Badge>
                </TableCell>
                <TableCell>
                  {trade.exit_reason ? (
                    <StatusBadge
                      positionState="closed"
                      exitReason={trade.exit_reason}
                    />
                  ) : (
                    <span className="text-muted-foreground text-xs">—</span>
                  )}
                </TableCell>
                <TableCell className="text-right font-mono tabular-nums">
                  {trade.pnl !== null ? (
                    <span
                      className={`flex items-center justify-end gap-1 ${
                        trade.pnl >= 0 ? 'text-green-600' : 'text-red-600'
                      }`}
                    >
                      {trade.pnl >= 0 ? (
                        <TrendingUp className="h-3 w-3" />
                      ) : (
                        <TrendingDown className="h-3 w-3" />
                      )}
                      {currencyFormat.format(trade.pnl)}
                    </span>
                  ) : (
                    <span className="text-muted-foreground">—</span>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
          <TableFooter>
            <TableRow>
              <TableCell colSpan={7} className="font-medium">
                Total P&L
              </TableCell>
              <TableCell
                className={`text-right font-mono tabular-nums font-bold ${
                  totalPnl >= 0 ? 'text-green-600' : 'text-red-600'
                }`}
              >
                {totalPnl >= 0 ? '+' : ''}
                {currencyFormat.format(totalPnl)}
              </TableCell>
            </TableRow>
          </TableFooter>
        </Table>
      </div>
    </div>
  )
}
