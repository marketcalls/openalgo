import type { DashboardPosition, PositionGroupData } from '@/types/strategy-dashboard'
import { PositionGroupHeader } from './PositionGroupHeader'
import { PositionRow } from './PositionRow'

interface PositionGroupProps {
  group: PositionGroupData
  positions: DashboardPosition[]
  onCloseGroup: (groupId: string) => Promise<void>
  onClosePosition: (positionId: number) => void
}

export function PositionGroup({
  group,
  positions,
  onCloseGroup,
  onClosePosition,
}: PositionGroupProps) {
  const combinedPnl = positions.reduce((sum, p) => sum + (p.unrealized_pnl || 0), 0)

  return (
    <div className="border rounded-lg overflow-hidden border-l-2 border-l-blue-500">
      <PositionGroupHeader
        group={group}
        legCount={positions.length}
        combinedPnl={combinedPnl}
        onCloseGroup={() => onCloseGroup(group.id)}
      />
      <table className="w-full text-xs">
        <tbody>
          {positions.map((pos) => (
            <PositionRow key={pos.id} position={pos} onClose={onClosePosition} />
          ))}
        </tbody>
      </table>
    </div>
  )
}
