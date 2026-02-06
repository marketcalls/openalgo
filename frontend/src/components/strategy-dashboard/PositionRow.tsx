import { Loader2, X } from 'lucide-react'
import React, { useState } from 'react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { TableCell, TableRow } from '@/components/ui/table'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog'
import { RiskBadges } from './RiskBadges'
import { StatusBadge } from './StatusBadge'
import type { RiskMonitoringState, StrategyPosition } from '@/types/strategy-dashboard'

interface PositionRowProps {
  position: StrategyPosition
  flash: 'profit' | 'loss' | null
  onClose: (positionId: number) => Promise<void>
  riskMonitoring: RiskMonitoringState
}

const currencyFormat = new Intl.NumberFormat('en-IN', {
  style: 'currency',
  currency: 'INR',
  maximumFractionDigits: 2,
})

function formatPnl(value: number): string {
  const formatted = currencyFormat.format(Math.abs(value))
  return value >= 0 ? `+${formatted}` : `-${formatted}`
}

const PositionRow = React.memo(function PositionRow({
  position,
  flash,
  onClose,
  riskMonitoring,
}: PositionRowProps) {
  const [closing, setClosing] = useState(false)

  const isActive = position.position_state === 'active'
  const isExiting = position.position_state === 'exiting'
  const isClosed = position.position_state === 'closed'

  const flashClass = flash === 'profit'
    ? 'bg-green-500/10'
    : flash === 'loss'
      ? 'bg-red-500/10'
      : ''

  const handleClose = () => {
    setClosing(true)
    onClose(position.id).finally(() => setClosing(false))
  }

  return (
    <TableRow className={`transition-colors duration-500 ${flashClass}`}>
      <TableCell className="font-medium">{position.symbol}</TableCell>
      <TableCell className="font-mono tabular-nums">
        <span className={position.action === 'BUY' ? 'text-green-600' : 'text-red-600'}>
          {position.action === 'BUY' ? '+' : '-'}{position.quantity}
        </span>
      </TableCell>
      <TableCell className="font-mono tabular-nums">
        {currencyFormat.format(position.average_entry_price)}
      </TableCell>
      <TableCell className="font-mono tabular-nums">
        {position.ltp ? currencyFormat.format(position.ltp) : '—'}
      </TableCell>
      <TableCell className={`font-mono tabular-nums font-medium ${
        position.unrealized_pnl >= 0 ? 'text-green-600' : 'text-red-600'
      }`}>
        {formatPnl(position.unrealized_pnl)}
      </TableCell>
      <TableCell>
        <RiskBadges
          stoploss={position.stoploss_price}
          target={position.target_price}
          trailstop={position.trailstop_price}
          breakeven={position.breakeven_activated}
        />
      </TableCell>
      <TableCell>
        <StatusBadge
          positionState={position.position_state}
          exitReason={position.exit_reason}
          riskMonitoring={riskMonitoring}
        />
      </TableCell>
      <TableCell>
        {isActive && (
          <AlertDialog>
            <AlertDialogTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                className="h-7 w-7 text-red-500 hover:text-red-600 hover:bg-red-50 dark:hover:bg-red-950"
                disabled={closing}
              >
                {closing ? <Loader2 className="h-4 w-4 animate-spin" /> : <X className="h-4 w-4" />}
              </Button>
            </AlertDialogTrigger>
            <AlertDialogContent>
              <AlertDialogHeader>
                <AlertDialogTitle>Close Position</AlertDialogTitle>
                <AlertDialogDescription>
                  Close {position.symbol} ({position.action} {position.quantity}) at MARKET?
                  This will place an immediate exit order.
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel>Cancel</AlertDialogCancel>
                <AlertDialogAction
                  onClick={handleClose}
                  className="bg-red-600 hover:bg-red-700"
                >
                  Close Position
                </AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        )}
        {isExiting && (
          <Loader2 className="h-4 w-4 animate-spin text-amber-500" />
        )}
        {isClosed && (
          <Badge variant="secondary" className="text-xs">
            Closed
          </Badge>
        )}
      </TableCell>
    </TableRow>
  )
})

export { PositionRow }
