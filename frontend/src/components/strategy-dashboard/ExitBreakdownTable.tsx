import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { StatusBadge } from './StatusBadge'

interface ExitBreakdownTableProps {
  breakdown: Record<string, number>
}

export function ExitBreakdownTable({ breakdown }: ExitBreakdownTableProps) {
  const entries = Object.entries(breakdown).sort((a, b) => b[1] - a[1])
  const total = entries.reduce((sum, [, count]) => sum + count, 0)

  if (entries.length === 0) return null

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Exit Reason</TableHead>
          <TableHead className="text-right">Count</TableHead>
          <TableHead className="text-right">% of Total</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {entries.map(([reason, count]) => (
          <TableRow key={reason}>
            <TableCell>
              <StatusBadge value={reason} />
            </TableCell>
            <TableCell className="text-right text-xs">{count}</TableCell>
            <TableCell className="text-right text-xs">
              {total > 0 ? ((count / total) * 100).toFixed(1) : 0}%
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}
