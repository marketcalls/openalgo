/**
 * Indicator Node
 * Run any openalgo.ta indicator over a symbol's history, or nest on top of
 * another Indicator node's output series (SMA(RSI(14), 9)-style composition)
 */

import { Handle, Position } from '@xyflow/react'
import { Activity } from 'lucide-react'
import { memo } from 'react'
import { cn } from '@/lib/utils'
import type { IndicatorNodeData } from '@/types/flow'

interface IndicatorNodeProps {
  data: IndicatorNodeData
  selected?: boolean
}

export const IndicatorNode = memo(({ data, selected }: IndicatorNodeProps) => {
  const isNested = Boolean(data.sourceSeries)

  return (
    <div className={cn('workflow-node min-w-[130px] border-l-primary', selected && 'selected')}>
      <Handle type="target" position={Position.Top} className="!top-0 !-translate-y-1/2" />
      <div className="p-2">
        <div className="mb-1.5 flex items-center gap-1.5">
          <div className="flex h-5 w-5 items-center justify-center rounded bg-primary/20 text-primary">
            <Activity className="h-3 w-3" />
          </div>
          <div>
            <div className="text-xs font-medium leading-tight">
              {(data.indicatorName || 'sma').toUpperCase()}
            </div>
            <div className="text-[9px] text-muted-foreground">
              {isNested ? 'Nested' : data.interval || 'D'}
            </div>
          </div>
        </div>
        <div className="rounded bg-muted/50 px-1.5 py-1">
          <div className="flex items-center justify-between">
            <span className="text-[10px] text-muted-foreground">
              {isNested ? 'Source' : 'Symbol'}
            </span>
            <span className="mono-data truncate text-[10px] font-medium" style={{ maxWidth: 70 }}>
              {isNested ? data.sourceSeries : data.symbol || '-'}
            </span>
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

IndicatorNode.displayName = 'IndicatorNode'
