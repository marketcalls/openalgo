/**
 * Cancel All Orders Node
 * Cancel all open orders
 */

import { memo } from 'react'
import { Handle, Position } from '@xyflow/react'
import { XCircle } from 'lucide-react'
import { cn } from '@/lib/utils'

interface CancelAllOrdersNodeProps {
  selected?: boolean
}

export const CancelAllOrdersNode = memo(({ selected }: CancelAllOrdersNodeProps) => {
  return (
    <div
      className={cn(
        'workflow-node node-action min-w-[110px]',
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
          <div className="node-icon flex h-5 w-5 items-center justify-center rounded bg-sell/20 text-sell">
            <XCircle className="h-3 w-3" />
          </div>
          <div>
            <div className="text-xs font-medium leading-tight">Cancel All</div>
            <div className="text-[9px] text-muted-foreground">
              Orders
            </div>
          </div>
        </div>
        <div className="rounded bg-sell/10 px-1.5 py-1 text-center">
          <span className="text-[9px] text-sell">
            Cancels all open orders
          </span>
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

CancelAllOrdersNode.displayName = 'CancelAllOrdersNode'
