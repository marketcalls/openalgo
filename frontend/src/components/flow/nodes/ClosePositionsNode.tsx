/**
 * Close Positions Node
 * Square off all open positions
 */

import { memo } from 'react'
import { Handle, Position } from '@xyflow/react'
import { Square } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { ClosePositionsNodeData } from '@/types/flow'

interface ClosePositionsNodeProps {
  data: ClosePositionsNodeData
  selected?: boolean
}

export const ClosePositionsNode = memo(({ data, selected }: ClosePositionsNodeProps) => {
  const hasFilter = data.exchange || data.product

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
            <Square className="h-3 w-3" />
          </div>
          <div>
            <div className="text-xs font-medium leading-tight">Close All</div>
            <div className="text-[9px] text-muted-foreground">
              Positions
            </div>
          </div>
        </div>
        {hasFilter ? (
          <div className="space-y-1">
            {data.exchange && (
              <div className="flex items-center justify-between rounded bg-muted/50 px-1.5 py-1">
                <span className="text-[10px] text-muted-foreground">Exchange</span>
                <span className="text-[10px] font-medium">{data.exchange}</span>
              </div>
            )}
            {data.product && (
              <div className="flex items-center justify-between rounded bg-muted/50 px-1.5 py-1">
                <span className="text-[10px] text-muted-foreground">Product</span>
                <span className="text-[10px] font-medium">{data.product}</span>
              </div>
            )}
          </div>
        ) : (
          <div className="rounded bg-sell/10 px-1.5 py-1 text-center">
            <span className="text-[9px] text-sell">
              Squares off all positions
            </span>
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

ClosePositionsNode.displayName = 'ClosePositionsNode'
