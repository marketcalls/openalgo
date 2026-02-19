import { useState } from 'react'
import { XCircleIcon } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { dashboardApi } from '@/api/strategy-dashboard'
import { showToast } from '@/utils/toast'
import type { DashboardPosition } from '@/types/strategy-dashboard'
import { StatusBadge } from './StatusBadge'
import { RiskBadges } from './RiskBadges'
import { EmptyState } from './EmptyState'

interface PositionTableProps {
  strategyId: number
  strategyType: string
  positions: DashboardPosition[]
  onRefresh: () => void
}

function pnlColor(v: number | null | undefined) {
  if (!v) return ''
  return v > 0 ? 'text-green-600' : v < 0 ? 'text-red-600' : ''
}

function distanceText(entry: number, target: number | null | undefined, action: string) {
  if (!target || !entry) return null
  const diff = action === 'BUY' ? target - entry : entry - target
  const pct = (diff / entry) * 100
  return `${diff > 0 ? '+' : ''}${diff.toFixed(2)} (${pct.toFixed(1)}%)`
}

export function PositionTable({
  strategyId,
  strategyType,
  positions,
  onRefresh,
}: PositionTableProps) {
  const [closing, setClosing] = useState<number | null>(null)

  if (positions.length === 0) {
    return <EmptyState title="No positions" description="No active positions for this strategy." />
  }

  const handleClose = async (positionId: number) => {
    setClosing(positionId)
    try {
      await dashboardApi.closePosition(strategyId, positionId, strategyType)
      showToast.success('Exit order placed')
      onRefresh()
    } catch {
      showToast.error('Failed to close position')
    } finally {
      setClosing(null)
    }
  }

  return (
    <div className="overflow-x-auto">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="w-[120px]">Symbol</TableHead>
            <TableHead>Action</TableHead>
            <TableHead className="text-right">Qty</TableHead>
            <TableHead className="text-right">Entry</TableHead>
            <TableHead className="text-right">LTP</TableHead>
            <TableHead className="text-right">P&L</TableHead>
            <TableHead className="text-right">P&L %</TableHead>
            <TableHead>Risk</TableHead>
            <TableHead>State</TableHead>
            <TableHead className="w-[60px]" />
          </TableRow>
        </TableHeader>
        <TableBody>
          {positions.map((pos) => (
            <TableRow key={pos.id}>
              <TableCell className="font-medium text-xs">
                <div>{pos.symbol}</div>
                <div className="text-muted-foreground text-[10px]">{pos.exchange}</div>
              </TableCell>
              <TableCell>
                <span
                  className={`text-xs font-medium ${pos.action === 'BUY' ? 'text-green-600' : 'text-red-600'}`}
                >
                  {pos.action}
                </span>
              </TableCell>
              <TableCell className="text-right text-xs">{pos.quantity}</TableCell>
              <TableCell className="text-right text-xs">
                {pos.average_entry_price ? pos.average_entry_price.toFixed(2) : '-'}
              </TableCell>
              <TableCell className="text-right text-xs">
                {pos.ltp ? pos.ltp.toFixed(2) : '-'}
              </TableCell>
              <TableCell className={`text-right text-xs font-medium ${pnlColor(pos.unrealized_pnl)}`}>
                {pos.unrealized_pnl != null ? pos.unrealized_pnl.toFixed(2) : '-'}
              </TableCell>
              <TableCell className={`text-right text-xs ${pnlColor(pos.unrealized_pnl_pct)}`}>
                {pos.unrealized_pnl_pct != null ? `${pos.unrealized_pnl_pct.toFixed(2)}%` : '-'}
              </TableCell>
              <TableCell>
                <RiskBadges position={pos} />
                {pos.stoploss_price && pos.ltp && (
                  <div className="text-[10px] text-muted-foreground mt-0.5">
                    SL dist: {distanceText(pos.ltp, pos.stoploss_price, pos.action)}
                  </div>
                )}
              </TableCell>
              <TableCell>
                <StatusBadge value={pos.position_state} />
              </TableCell>
              <TableCell>
                {pos.position_state === 'active' && (
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-7 w-7"
                    disabled={closing === pos.id}
                    onClick={() => handleClose(pos.id)}
                    title="Close position"
                  >
                    <XCircleIcon className="h-4 w-4 text-red-500" />
                  </Button>
                )}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}
