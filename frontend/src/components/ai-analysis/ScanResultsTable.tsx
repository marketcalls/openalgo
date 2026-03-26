// frontend/src/components/ai-analysis/ScanResultsTable.tsx
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { SignalBadge } from './SignalBadge'
import type { ScanResult } from '@/types/ai-analysis'

interface ScanResultsTableProps {
  results: ScanResult[]
}

export function ScanResultsTable({ results }: ScanResultsTableProps) {
  if (results.length === 0) {
    return <p className="text-sm text-muted-foreground py-8 text-center">No results yet</p>
  }

  const sorted = [...results].sort((a, b) => b.score - a.score)

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Symbol</TableHead>
          <TableHead>Signal</TableHead>
          <TableHead className="text-right">Confidence</TableHead>
          <TableHead className="text-right">Score</TableHead>
          <TableHead>Regime</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {sorted.map((r) => (
          <TableRow key={r.symbol}>
            <TableCell className="font-medium">{r.symbol}</TableCell>
            <TableCell>
              {r.signal ? <SignalBadge signal={r.signal} size="sm" /> : <span className="text-muted-foreground">---</span>}
            </TableCell>
            <TableCell className="text-right">{r.confidence.toFixed(1)}%</TableCell>
            <TableCell className="text-right font-mono">{r.score.toFixed(4)}</TableCell>
            <TableCell>{r.regime ?? '---'}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}
