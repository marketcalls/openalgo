/**
 * Open Position Node
 * Get current open position for a symbol
 */

import { memo } from 'react'
import { Handle, Position } from '@xyflow/react'
import { Briefcase } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { OpenPositionNodeData } from '@/types/flow'

interface OpenPositionNodeProps {
  data: OpenPositionNodeData
  selected?: boolean
}

export const OpenPositionNode = memo(({ data, selected }: OpenPositionNodeProps) => {
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
            <div className="text-xs font-medium leading-tight">Position</div>
            <div className="text-[9px] text-muted-foreground">
              {data.exchange || 'NSE'}
            </div>
          </div>
        </div>
        <div className="space-y-1">
          <div className="flex items-center justify-between rounded bg-muted/50 px-1.5 py-1">
            <span className="text-[10px] text-muted-foreground">Symbol</span>
            <span className="mono-data text-[10px] font-medium">{data.symbol || '-'}</span>
          </div>
          <div className="text-center text-[9px] text-muted-foreground">
            {data.product || 'MIS'}
          </div>
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

OpenPositionNode.displayName = 'OpenPositionNode'
