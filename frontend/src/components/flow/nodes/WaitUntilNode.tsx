/**
 * Wait Until Node
 * Pauses workflow execution until a specific time is reached
 */

import { memo } from 'react'
import { Handle, Position } from '@xyflow/react'
import { Hourglass } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { WaitUntilNodeData } from '@/types/flow'

interface WaitUntilNodeProps {
  data: WaitUntilNodeData
  selected?: boolean
}

export const WaitUntilNode = memo(({ data, selected }: WaitUntilNodeProps) => {
  return (
    <div
      className={cn(
        'workflow-node node-utility min-w-[120px]',
        selected && 'selected'
      )}
    >
      <Handle
        type="target"
        position={Position.Top}
        className="!top-0 !-translate-y-1/2"
      />
      <div className="p-2">
        <div className="mb-1.5 flex items-center gap-1.5">
          <div className="node-icon flex h-5 w-5 items-center justify-center rounded bg-amber-500/10">
            <Hourglass className="h-3 w-3 text-amber-500" />
          </div>
          <div>
            <div className="text-xs font-medium leading-tight">Wait Until</div>
            <div className="text-[9px] text-muted-foreground">
              Pause execution
            </div>
          </div>
        </div>
        <div className="space-y-1">
          <div className="flex items-center justify-between rounded bg-muted/50 px-1.5 py-1">
            <span className="text-[10px] text-muted-foreground">Time</span>
            <span className="mono-data text-[10px] font-medium text-amber-500">
              {data.targetTime || '09:30'}
            </span>
          </div>
          {data.label && (
            <div className="text-center text-[9px] text-muted-foreground truncate">
              {data.label}
            </div>
          )}
        </div>
      </div>
      <Handle
        type="source"
        position={Position.Bottom}
        className="!bottom-0 !translate-y-1/2"
      />
    </div>
  )
})

WaitUntilNode.displayName = 'WaitUntilNode'
