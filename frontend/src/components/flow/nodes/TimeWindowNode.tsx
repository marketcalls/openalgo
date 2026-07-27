/**
 * Time Window Node
 * Check if current time is within specified range
 */

import { memo } from 'react'
import { Handle, Position } from '@xyflow/react'
import { Clock } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { TimeWindowNodeData } from '@/types/flow'

interface TimeWindowNodeProps {
  data: TimeWindowNodeData
  selected?: boolean
}

export const TimeWindowNode = memo(({ data, selected }: TimeWindowNodeProps) => {
  return (
    <div
      className={cn(
        'workflow-node node-condition min-w-[120px]',
        selected && 'selected'
      )}
    >
      <Handle
        type="target"
        position={Position.Top}
        className="!top-0 !-translate-y-1/2 !h-3 !w-3 !rounded-full !border-2 !border-background !bg-muted-foreground"
      />
      <div className="p-2">
        <div className="mb-1.5 flex items-center gap-1.5">
          <div className="node-icon flex h-5 w-5 items-center justify-center rounded">
            <Clock className="h-3 w-3" />
          </div>
          <div>
            <div className="text-xs font-medium leading-tight">Time</div>
            <div className="text-[9px] text-muted-foreground">
              Window
            </div>
          </div>
        </div>
        <div className="space-y-1">
          <div className="flex items-center justify-between rounded bg-muted/50 px-1.5 py-1">
            <span className="text-[10px] text-muted-foreground">Start</span>
            <span className="mono-data text-[10px] font-medium">{data.startTime || '09:15'}</span>
          </div>
          <div className="flex items-center justify-between rounded bg-muted/50 px-1.5 py-1">
            <span className="text-[10px] text-muted-foreground">End</span>
            <span className="mono-data text-[10px] font-medium">{data.endTime || '15:30'}</span>
          </div>
          {data.invertCondition && (
            <div className="text-center text-[9px] text-muted-foreground">
              Outside window
            </div>
          )}
        </div>
        {/* Handle labels */}
        <div className="mt-2 flex justify-between px-1 text-[8px]">
          <span className="text-buy">True</span>
          <span className="text-sell">False</span>
        </div>
      </div>
      {/* True output (left) - Within time window */}
      <Handle
        type="source"
        position={Position.Bottom}
        id="true"
        className="!bottom-0 !translate-y-1/2 !bg-buy !h-3 !w-3 !rounded-full !border-2 !border-background"
        style={{ left: '25%' }}
      />
      {/* False output (right) - Outside time window */}
      <Handle
        type="source"
        position={Position.Bottom}
        id="false"
        className="!bottom-0 !translate-y-1/2 !bg-sell !h-3 !w-3 !rounded-full !border-2 !border-background"
        style={{ left: '75%' }}
      />
    </div>
  )
})

TimeWindowNode.displayName = 'TimeWindowNode'
