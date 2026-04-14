/**
 * Get Order Status Node
 * Check status of a specific order
 */

import { memo } from 'react'
import { Handle, Position } from '@xyflow/react'
import { FileSearch } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { GetOrderStatusNodeData } from '@/types/flow'

interface GetOrderStatusNodeProps {
  data: GetOrderStatusNodeData
  selected?: boolean
}

export const GetOrderStatusNode = memo(({ data, selected }: GetOrderStatusNodeProps) => {
  return (
    <div
      className={cn(
        'workflow-node min-w-[120px] border-l-primary',
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
            <FileSearch className="h-3 w-3" />
          </div>
          <div>
            <div className="text-xs font-medium leading-tight">Order Status</div>
            <div className="text-[9px] text-muted-foreground">
              Check order
            </div>
          </div>
        </div>
        <div className="space-y-1">
          <div className="flex items-center justify-between rounded bg-muted/50 px-1.5 py-1">
            <span className="text-[10px] text-muted-foreground">Order ID</span>
            <span className="mono-data text-[10px] font-medium">
              {data.orderId ? `...${data.orderId.slice(-6)}` : '-'}
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

GetOrderStatusNode.displayName = 'GetOrderStatusNode'
