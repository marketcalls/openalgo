/**
 * Bar Offset Node
 * OHLCV of the Nth closed bar back at any interval - covers "N bars/hours/
 * days back" style lookback without a separate node per time unit
 */

import { Handle, Position } from '@xyflow/react'
import { History } from 'lucide-react'
import { memo } from 'react'
import { cn } from '@/lib/utils'
import type { BarOffsetNodeData } from '@/types/flow'

interface BarOffsetNodeProps {
  data: BarOffsetNodeData
  selected?: boolean
}

export const BarOffsetNode = memo(({ data, selected }: BarOffsetNodeProps) => {
  return (
    <div className={cn('workflow-node min-w-[120px] border-l-primary', selected && 'selected')}>
      <Handle type="target" position={Position.Top} className="!top-0 !-translate-y-1/2" />
      <div className="p-2">
        <div className="mb-1.5 flex items-center gap-1.5">
          <div className="flex h-5 w-5 items-center justify-center rounded bg-primary/20 text-primary">
            <History className="h-3 w-3" />
          </div>
          <div>
            <div className="text-xs font-medium leading-tight">Bar Offset</div>
            <div className="text-[9px] text-muted-foreground">{data.interval || 'D'}</div>
          </div>
        </div>
        <div className="space-y-1">
          <div className="flex items-center justify-between rounded bg-muted/50 px-1.5 py-1">
            <span className="text-[10px] text-muted-foreground">Symbol</span>
            <span className="mono-data text-[10px] font-medium">{data.symbol || '-'}</span>
          </div>
          <div className="flex items-center justify-between rounded bg-muted/50 px-1.5 py-1">
            <span className="text-[10px] text-muted-foreground">Bars back</span>
            <span className="mono-data text-[10px] font-medium">{data.offsetBars ?? 0}</span>
          </div>
        </div>
        {data.outputVariable && (
          <div className="mt-1 text-center text-[9px] text-muted-foreground">
            {data.outputVariable}
          </div>
        )}
      </div>
      <Handle type="source" position={Position.Bottom} className="!bottom-0 !translate-y-1/2" />
    </div>
  )
})

BarOffsetNode.displayName = 'BarOffsetNode'
