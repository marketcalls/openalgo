/**
 * Cancel Order Node
 * Cancel a specific order by ID
 */

import { memo } from 'react'
import { Handle, Position } from '@xyflow/react'
import { XCircle } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { CancelOrderNodeData } from '@/types/flow'

interface CancelOrderNodeProps {
  data: CancelOrderNodeData
  selected?: boolean
}

export const CancelOrderNode = memo(({ data, selected }: CancelOrderNodeProps) => {
  return (
    <div
      className={cn(
        'workflow-node node-action min-w-[120px]',
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
            <XCircle className="h-3 w-3" />
          </div>
          <div>
            <div className="text-xs font-medium leading-tight">Cancel Order</div>
            <div className="text-[9px] text-muted-foreground">
              By Order ID
            </div>
          </div>
        </div>
        <div className="rounded bg-muted/50 px-1.5 py-1">
          <div className="flex items-center justify-between">
            <span className="text-[10px] text-muted-foreground">Order ID</span>
            <span className="mono-data text-[10px] font-medium">
              {data.orderId ? `...${data.orderId.slice(-6)}` : 'Variable'}
            </span>
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

CancelOrderNode.displayName = 'CancelOrderNode'
