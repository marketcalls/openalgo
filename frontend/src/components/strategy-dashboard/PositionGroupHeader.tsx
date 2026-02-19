import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { X } from 'lucide-react'
import type { PositionGroupData } from '@/types/strategy-dashboard'

interface PositionGroupHeaderProps {
  group: PositionGroupData
  legCount: number
  combinedPnl: number
  onCloseGroup: () => void
}

export function PositionGroupHeader({
  group,
  legCount,
  combinedPnl,
  onCloseGroup,
}: PositionGroupHeaderProps) {
  const pnlColor =
    combinedPnl >= 0
      ? 'text-green-600 dark:text-green-400'
      : 'text-red-600 dark:text-red-400'

  const statusColor =
    group.group_status === 'complete'
      ? 'bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-300'
      : group.group_status === 'partial'
        ? 'bg-amber-100 text-amber-700 dark:bg-amber-900 dark:text-amber-300'
        : 'bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300'

  return (
    <div className="flex items-center justify-between px-3 py-2 bg-muted/50 border-b">
      <div className="flex items-center gap-2">
        <span className="text-xs font-medium">
          Group ({legCount}/{group.expected_legs} legs)
        </span>
        <Badge variant="outline" className={`text-[10px] ${statusColor}`}>
          {group.group_status}
        </Badge>
      </div>
      <div className="flex items-center gap-3">
        <span className={`text-sm font-semibold ${pnlColor}`}>
          {combinedPnl >= 0 ? '+' : ''}
          {combinedPnl.toFixed(2)}
        </span>
        <Button variant="ghost" size="sm" className="h-6 text-xs gap-1" onClick={onCloseGroup}>
          <X className="h-3 w-3" />
          Close Group
        </Button>
      </div>
    </div>
  )
}
