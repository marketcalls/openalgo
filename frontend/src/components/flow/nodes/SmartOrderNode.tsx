/**
 * Smart Order Node
 * Position-aware order placement
 */

import { memo } from 'react'
import { Handle, Position } from '@xyflow/react'
import { Zap } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { SmartOrderNodeData } from '@/types/flow'

interface SmartOrderNodeProps {
  data: SmartOrderNodeData
  selected?: boolean
}

export const SmartOrderNode = memo(({ data, selected }: SmartOrderNodeProps) => {
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
            <Zap className="h-3 w-3" />
          </div>
          <div>
            <div className="text-xs font-medium leading-tight">Smart Order</div>
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
          <div className="flex items-center justify-between">
            <span
              className={cn(
                'rounded px-1 py-0.5 text-[9px] font-semibold',
                data.action === 'BUY' ? 'badge-buy' : 'badge-sell'
              )}
            >
              {data.action || 'BUY'}
            </span>
            <div className="flex items-center gap-1 text-[10px]">
              <span className="text-muted-foreground">Qty:</span>
              <span className="mono-data font-medium">{data.quantity || 0}</span>
            </div>
          </div>
          <div className="flex items-center justify-between rounded bg-muted/50 px-1.5 py-1">
            <span className="text-[10px] text-muted-foreground">Target Pos</span>
            <span className="mono-data text-[10px] font-medium">{data.positionSize ?? 0}</span>
          </div>
          <div className="flex items-center justify-between text-[9px] text-muted-foreground">
            <span>{data.priceType || 'MARKET'}</span>
            <span>{data.product || 'MIS'}</span>
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

SmartOrderNode.displayName = 'SmartOrderNode'
