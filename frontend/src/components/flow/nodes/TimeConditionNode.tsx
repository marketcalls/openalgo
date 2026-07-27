/**
 * Time Condition Node
 * Check if current time matches/passes a specific time (Entry/Exit condition)
 */

import { memo } from 'react'
import { Handle, Position } from '@xyflow/react'
import { Clock } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { TimeConditionNodeData } from '@/types/flow'

interface TimeConditionNodeProps {
  data: TimeConditionNodeData
  selected?: boolean
}

const operatorLabels: Record<string, string> = {
  '==': '=',
  '>=': '>=',
  '<=': '<=',
  '>': '>',
  '<': '<',
}

export const TimeConditionNode = memo(({ data, selected }: TimeConditionNodeProps) => {
  const operatorLabel = operatorLabels[data.operator] || '='

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
        className="!top-0 !-translate-y-1/2"
      />
      <div className="p-2">
        <div className="mb-1.5 flex items-center gap-1.5">
          <div className="node-icon flex h-5 w-5 items-center justify-center rounded">
            <Clock className="h-3 w-3" />
          </div>
          <div>
            <div className="text-xs font-medium leading-tight">Time</div>
            <div className="text-[9px] text-muted-foreground">
              {data.conditionType === 'entry' ? 'Entry' : data.conditionType === 'exit' ? 'Exit' : 'Condition'}
            </div>
          </div>
        </div>
        <div className="space-y-1">
          <div className="flex items-center justify-between rounded bg-muted/50 px-1.5 py-1">
            <span className="text-[10px] text-muted-foreground">Time</span>
            <span className="mono-data text-[10px] font-medium">
              {operatorLabel} {data.targetTime || '09:30'}
            </span>
          </div>
          {data.label && (
            <div className="text-center text-[9px] text-muted-foreground truncate">
              {data.label}
            </div>
          )}
        </div>
        {/* Handle labels */}
        <div className="mt-2 flex justify-between px-1 text-[8px]">
          <span className="text-buy">Yes</span>
          <span className="text-sell">No</span>
        </div>
      </div>
      {/* True output (left) - Condition met */}
      <Handle
        type="source"
        position={Position.Bottom}
        id="yes"
        className="!bottom-0 !left-1/4 !translate-y-1/2 !bg-buy"
        style={{ left: '25%' }}
      />
      {/* False output (right) - Condition not met */}
      <Handle
        type="source"
        position={Position.Bottom}
        id="no"
        className="!bottom-0 !left-3/4 !translate-y-1/2 !bg-sell"
        style={{ left: '75%' }}
      />
    </div>
  )
})

TimeConditionNode.displayName = 'TimeConditionNode'
