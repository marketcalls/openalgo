import { StatusBadge } from './StatusBadge'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import type { ExitBreakdownEntry, ExitReason } from '@/types/strategy-dashboard'

interface ExitBreakdownTableProps {
  data: ExitBreakdownEntry[]
}

const currencyFormat = new Intl.NumberFormat('en-IN', {
  style: 'currency',
  currency: 'INR',
  maximumFractionDigits: 2,
})

export function ExitBreakdownTable({ data }: ExitBreakdownTableProps) {
  if (data.length === 0) {
    return (
      <div className="flex items-center justify-center py-8 text-muted-foreground text-sm">
        No exit data available
      </div>
    )
  }

  return (
    <div className="relative w-full overflow-x-auto">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Exit Type</TableHead>
            <TableHead className="text-right">Count</TableHead>
            <TableHead className="text-right">Total P&L</TableHead>
            <TableHead className="text-right">Avg P&L</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {data.map((entry) => (
            <TableRow key={entry.exit_reason}>
              <TableCell>
                <StatusBadge
                  positionState="closed"
                  exitReason={entry.exit_reason as ExitReason}
                />
              </TableCell>
              <TableCell className="text-right font-mono tabular-nums">
                {entry.count}
              </TableCell>
              <TableCell
                className={`text-right font-mono tabular-nums ${
                  entry.total_pnl >= 0 ? 'text-green-600' : 'text-red-600'
                }`}
              >
                {entry.total_pnl >= 0 ? '+' : ''}
                {currencyFormat.format(entry.total_pnl)}
              </TableCell>
              <TableCell
                className={`text-right font-mono tabular-nums ${
                  entry.avg_pnl >= 0 ? 'text-green-600' : 'text-red-600'
                }`}
              >
                {entry.avg_pnl >= 0 ? '+' : ''}
                {currencyFormat.format(entry.avg_pnl)}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}
