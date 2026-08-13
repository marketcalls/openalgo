/**
 * Order Update Trigger Node
 * Fires a workflow the moment a matching order's status changes (filled,
 * rejected, cancelled, ...) - push-based via the account order-update
 * stream, instead of polling getOrderStatus in a loop
 */

import { Handle, Position } from '@xyflow/react'
import { PackageCheck } from 'lucide-react'
import { memo } from 'react'
import { cn } from '@/lib/utils'
import type { OrderUpdateTriggerNodeData } from '@/types/flow'

interface OrderUpdateTriggerNodeProps {
  data: OrderUpdateTriggerNodeData
  selected?: boolean
}

export const OrderUpdateTriggerNode = memo(({ data, selected }: OrderUpdateTriggerNodeProps) => {
  const watchTarget = data.orderId || data.symbol || 'Any order'

  return (
    <div className={cn('workflow-node node-trigger min-w-[120px]', selected && 'selected')}>
      <div className="p-2">
        <div className="mb-1.5 flex items-center gap-1.5">
          <div className="node-icon flex h-5 w-5 items-center justify-center rounded bg-node-trigger/20">
            <PackageCheck className="h-3 w-3 text-node-trigger" />
          </div>
          <div>
            <div className="text-xs font-medium leading-tight">Order Update</div>
            <div className="text-[9px] text-muted-foreground">{data.status || 'complete'}</div>
          </div>
        </div>
        <div className="rounded bg-muted/50 px-1.5 py-1 text-center">
          <span className="mono-data text-[10px] font-medium">{watchTarget}</span>
        </div>
      </div>
      <Handle type="source" position={Position.Bottom} className="!bottom-0 !translate-y-1/2" />
    </div>
  )
})

OrderUpdateTriggerNode.displayName = 'OrderUpdateTriggerNode'
