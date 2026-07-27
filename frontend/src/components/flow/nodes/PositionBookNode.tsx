/**
 * PositionBook Node
 * Fetch all open positions
 */

import { memo } from 'react'
import { Handle, Position } from '@xyflow/react'
import { Briefcase } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { PositionBookNodeData } from '@/types/flow'

interface PositionBookNodeProps {
  data: PositionBookNodeData
  selected?: boolean
}

export const PositionBookNode = memo(({ data, selected }: PositionBookNodeProps) => {
  return (
    <div
      className={cn(
        'workflow-node min-w-[110px] border-l-primary',
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
          <div className="flex h-5 w-5 items-center justify-center rounded bg-primary/20 text-primary">
            <Briefcase className="h-3 w-3" />
          </div>
          <div>
            <div className="text-xs font-medium leading-tight">Position Book</div>
            <div className="text-[9px] text-muted-foreground">All positions</div>
          </div>
        </div>
        {data.outputVariable && (
          <div className="rounded bg-muted/50 px-1.5 py-1 text-center">
            <span className="text-[9px] text-muted-foreground">{data.outputVariable}</span>
          </div>
        )}
      </div>
      <Handle
        type="source"
        position={Position.Bottom}
        className="!bottom-0 !translate-y-1/2"
      />
    </div>
  )
})

PositionBookNode.displayName = 'PositionBookNode'
