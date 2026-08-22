/**
 * Basket Order Node
 * Place multiple orders at once
 */

import { Handle, Position } from '@xyflow/react'
import { Package } from 'lucide-react'
import { memo } from 'react'
import { cn } from '@/lib/utils'
import type { BasketOrderNodeData } from '@/types/flow'

interface BasketOrderNodeProps {
  data: BasketOrderNodeData
  selected?: boolean
}

export const BasketOrderNode = memo(({ data, selected }: BasketOrderNodeProps) => {
  // The config panel writes `orders` as newline-delimited CSV text, not an
  // array, so the array-only count rendered "Orders: 0" for every basket
  // however many legs it had. The stale array type in types/flow.ts is what
  // let the drift through the compiler.
  // Widened before narrowing: `orders` is typed as the string the editor
  // writes, but a workflow imported from an older export may still carry the
  // array shape, and that should count rather than render 0.
  const ordersRaw: unknown = data.orders
  const orderCount =
    typeof ordersRaw === 'string'
      ? ordersRaw.split('\n').filter((line) => line.trim()).length
      : Array.isArray(ordersRaw)
        ? ordersRaw.length
        : 0

  return (
    <div className={cn('workflow-node node-action min-w-[120px]', selected && 'selected')}>
      <Handle type="target" position={Position.Top} className="!top-0 !-translate-y-1/2" />
      <div className="p-2">
        <div className="mb-1.5 flex items-center gap-1.5">
          <div className="node-icon flex h-5 w-5 items-center justify-center rounded">
            <Package className="h-3 w-3" />
          </div>
          <div>
            <div className="text-xs font-medium leading-tight">Basket Order</div>
            <div className="text-[9px] text-muted-foreground">Multi-order</div>
          </div>
        </div>
        <div className="space-y-1">
          <div className="flex items-center justify-between rounded bg-muted/50 px-1.5 py-1">
            <span className="text-[10px] text-muted-foreground">Orders</span>
            <span className="mono-data text-[10px] font-medium">{orderCount}</span>
          </div>
          <div className="text-center text-[9px] text-muted-foreground">
            {data.basketName || 'Batch execution'}
          </div>
        </div>
      </div>
      <Handle type="source" position={Position.Bottom} className="!bottom-0 !translate-y-1/2" />
    </div>
  )
})

BasketOrderNode.displayName = 'BasketOrderNode'
