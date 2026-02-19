import { useEffect, useState } from 'react'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { dashboardApi } from '@/api/strategy-dashboard'
import type { DashboardTrade } from '@/types/strategy-dashboard'
import { StatusBadge } from './StatusBadge'
import { EmptyState } from './EmptyState'

interface TradesPanelProps {
  strategyId: number
  strategyType: string
}

function pnlColor(v: number | null) {
  if (!v) return ''
  return v > 0 ? 'text-green-600' : v < 0 ? 'text-red-600' : ''
}

export function TradesPanel({ strategyId, strategyType }: TradesPanelProps) {
  const [trades, setTrades] = useState<DashboardTrade[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    dashboardApi
      .getTrades(strategyId, strategyType, { limit: 50 })
      .then((data) => {
        if (!cancelled) setTrades(data)
      })
      .catch(() => {})
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [strategyId, strategyType])

  if (loading) {
    return <div className="py-8 text-center text-sm text-muted-foreground">Loading trades...</div>
  }

  if (trades.length === 0) {
    return <EmptyState title="No trades" description="No trade history for this strategy." />
  }

  return (
    <div className="overflow-x-auto">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Symbol</TableHead>
            <TableHead>Action</TableHead>
            <TableHead>Type</TableHead>
            <TableHead className="text-right">Qty</TableHead>
            <TableHead className="text-right">Price</TableHead>
            <TableHead className="text-right">P&L</TableHead>
            <TableHead>Exit Reason</TableHead>
            <TableHead>Time</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {trades.map((trade) => (
            <TableRow key={trade.id}>
              <TableCell className="text-xs font-medium">{trade.symbol}</TableCell>
              <TableCell>
                <span
                  className={`text-xs font-medium ${trade.action === 'BUY' ? 'text-green-600' : 'text-red-600'}`}
                >
                  {trade.action}
                </span>
              </TableCell>
              <TableCell className="text-xs capitalize">{trade.trade_type}</TableCell>
              <TableCell className="text-right text-xs">{trade.quantity}</TableCell>
              <TableCell className="text-right text-xs">{trade.price.toFixed(2)}</TableCell>
              <TableCell className={`text-right text-xs font-medium ${pnlColor(trade.pnl)}`}>
                {trade.pnl != null ? trade.pnl.toFixed(2) : '-'}
              </TableCell>
              <TableCell>
                {trade.exit_reason && <StatusBadge value={trade.exit_reason} />}
              </TableCell>
              <TableCell className="text-xs text-muted-foreground">
                {trade.created_at
                  ? new Date(trade.created_at).toLocaleTimeString('en-IN', {
                      hour: '2-digit',
                      minute: '2-digit',
                    })
                  : '-'}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}
