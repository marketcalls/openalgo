/**
 * Calendar Node
 * Trading-day facts for a date: has a new day, week, month, quarter or year
 * started, and the surrounding trading days. Answered from the exchange
 * calendar, so it needs no state between runs.
 */

import { Handle, Position } from '@xyflow/react'
import { CalendarRange } from 'lucide-react'
import { memo } from 'react'
import { cn } from '@/lib/utils'
import type { CalendarNodeData } from '@/types/flow'

interface CalendarNodeProps {
  data: CalendarNodeData
  selected?: boolean
}

export const CalendarNode = memo(({ data, selected }: CalendarNodeProps) => {
  return (
    <div className={cn('workflow-node min-w-[130px] border-l-purple-400', selected && 'selected')}>
      <Handle type="target" position={Position.Top} className="!top-0 !-translate-y-1/2" />
      <div className="p-2">
        <div className="mb-1.5 flex items-center gap-1.5">
          <div className="flex h-5 w-5 items-center justify-center rounded bg-purple-400/20 text-purple-400">
            <CalendarRange className="h-3 w-3" />
          </div>
          <div>
            <div className="text-xs font-medium leading-tight">Calendar</div>
            <div className="text-[9px] text-muted-foreground">new day / week / month</div>
          </div>
        </div>
        <div className="rounded bg-muted/50 px-1.5 py-1">
          <div className="flex items-center justify-between">
            <span className="text-[10px] text-muted-foreground">Date</span>
            <span className="mono-data text-[10px] font-medium">{data.date || 'today'}</span>
          </div>
        </div>
        {data.outputVariable && (
          <div className="mt-1 text-center text-[9px] text-muted-foreground">
            {data.outputVariable}
          </div>
        )}
      </div>
      <Handle type="source" position={Position.Bottom} className="!bottom-0 !translate-y-1/2" />
    </div>
  )
})

CalendarNode.displayName = 'CalendarNode'
