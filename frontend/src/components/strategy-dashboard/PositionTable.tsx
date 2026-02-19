import { useState } from 'react'
import { dashboardApi } from '@/api/strategy-dashboard'
import { showToast } from '@/utils/toast'
import type { DashboardPosition, PositionGroupData } from '@/types/strategy-dashboard'
import { PositionRow } from './PositionRow'
import { PositionGroup } from './PositionGroup'
import { EmptyState } from './EmptyState'

interface PositionTableProps {
  strategyId: number
  strategyType: string
  positions: DashboardPosition[]
  groups?: PositionGroupData[]
  onRefresh: () => void
}

const HEADERS = [
  'Symbol',
  'Qty',
  'Entry',
  'LTP',
  'P&L',
  'SL',
  'SL Dist',
  'TGT',
  'TGT Dist',
  'TSL',
  'TSL Dist',
  'BE',
  'Status',
  '',
]

export function PositionTable({
  strategyId,
  strategyType,
  positions,
  groups,
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

  const handleCloseGroup = async (groupId: string) => {
    try {
      await dashboardApi.closePositionGroup(strategyId, groupId, strategyType)
      showToast.success('Group close orders placed')
      onRefresh()
    } catch {
      showToast.error('Failed to close group')
    }
  }

  // Separate grouped vs ungrouped positions
  const groupedIds = new Set<string>()
  const groupMap = new Map<string, DashboardPosition[]>()
  if (groups && groups.length > 0) {
    for (const g of groups) {
      groupedIds.add(g.id)
      groupMap.set(g.id, [])
    }
    for (const pos of positions) {
      if (pos.position_group_id && groupMap.has(pos.position_group_id)) {
        groupMap.get(pos.position_group_id)!.push(pos)
      }
    }
  }

  const ungrouped = positions.filter(
    (p) => !p.position_group_id || !groupedIds.has(p.position_group_id)
  )

  return (
    <div className="space-y-3">
      {/* Grouped positions first */}
      {groups &&
        groups.map((group) => {
          const groupPositions = groupMap.get(group.id) || []
          if (groupPositions.length === 0) return null
          return (
            <PositionGroup
              key={group.id}
              group={group}
              positions={groupPositions}
              onCloseGroup={handleCloseGroup}
              onClosePosition={handleClose}
            />
          )
        })}

      {/* Ungrouped positions */}
      {ungrouped.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b">
                {HEADERS.map((h, i) => (
                  <th key={i} className="py-2 px-2 text-left font-medium text-muted-foreground">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {ungrouped.map((pos) => (
                <PositionRow
                  key={pos.id}
                  position={pos}
                  onClose={handleClose}
                  closing={closing === pos.id}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
