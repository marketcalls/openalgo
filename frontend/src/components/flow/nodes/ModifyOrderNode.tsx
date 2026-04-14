/**
 * Modify Order Node
 * Modify an existing order's price, quantity, or trigger price
 */

import { memo } from 'react'
import { Handle, Position } from '@xyflow/react'
import { Pencil } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { ModifyOrderNodeData } from '@/types/flow'

interface ModifyOrderNodeProps {
  data: ModifyOrderNodeData
  selected?: boolean
}

export const ModifyOrderNode = memo(({ data, selected }: ModifyOrderNodeProps) => {
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
            <Pencil className="h-3 w-3" />
          </div>
          <div>
            <div className="text-xs font-medium leading-tight">Modify Order</div>
            <div className="text-[9px] text-muted-foreground">
              Edit order
            </div>
          </div>
        </div>
        <div className="space-y-1">
          <div className="flex items-center justify-between rounded bg-muted/50 px-1.5 py-1">
            <span className="text-[10px] text-muted-foreground">Order ID</span>
            <span className="mono-data text-[10px] font-medium">
              {data.orderId ? `...${data.orderId.slice(-6)}` : 'Variable'}
            </span>
          </div>
          {data.newPrice && (
            <div className="flex items-center justify-between text-[9px] text-muted-foreground">
              <span>New Price</span>
              <span className="mono-data">{data.newPrice}</span>
            </div>
          )}
          {data.newQuantity && (
            <div className="flex items-center justify-between text-[9px] text-muted-foreground">
              <span>New Qty</span>
              <span className="mono-data">{data.newQuantity}</span>
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

ModifyOrderNode.displayName = 'ModifyOrderNode'
