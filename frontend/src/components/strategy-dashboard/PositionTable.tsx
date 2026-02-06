import { PackageOpen } from 'lucide-react'
import {
  Table,
  TableBody,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { PositionRow } from './PositionRow'
import type { RiskMonitoringState, StrategyPosition } from '@/types/strategy-dashboard'

interface PositionTableProps {
  positions: StrategyPosition[]
  flashMap: Map<number, 'profit' | 'loss'>
  riskMonitoring: RiskMonitoringState
  onClosePosition: (positionId: number) => Promise<void>
}

export function PositionTable({
  positions,
  flashMap,
  riskMonitoring,
  onClosePosition,
}: PositionTableProps) {
  if (positions.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
        <PackageOpen className="h-10 w-10 mb-3 opacity-40" />
        <p className="text-sm">No open positions</p>
        <p className="text-xs mt-1">Waiting for webhook signals...</p>
      </div>
    )
  }

  // Sort: active first, then by opened_at desc
  const sorted = [...positions].sort((a, b) => {
    const stateOrder = { pending_entry: 0, active: 1, exiting: 2, closed: 3 }
    const aOrder = stateOrder[a.position_state] ?? 4
    const bOrder = stateOrder[b.position_state] ?? 4
    if (aOrder !== bOrder) return aOrder - bOrder
    return new Date(b.opened_at).getTime() - new Date(a.opened_at).getTime()
  })

  return (
    <div className="relative w-full overflow-x-auto">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Symbol</TableHead>
            <TableHead>Qty</TableHead>
            <TableHead>Avg</TableHead>
            <TableHead>LTP</TableHead>
            <TableHead>P&L</TableHead>
            <TableHead>SL / TGT / TSL</TableHead>
            <TableHead>Status</TableHead>
            <TableHead className="w-12"></TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {sorted.map((position) => (
            <PositionRow
              key={position.id}
              position={position}
              flash={flashMap.get(position.id) ?? null}
              onClose={onClosePosition}
              riskMonitoring={riskMonitoring}
            />
          ))}
        </TableBody>
      </Table>
    </div>
  )
}
