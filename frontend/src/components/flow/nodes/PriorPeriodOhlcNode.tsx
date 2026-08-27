/**
 * Prior Period OHLC Node
 * Last fully-closed hour/day/week/month candle for a symbol
 * (e.g. previous day's high/low for a PDH/PDL breakout strategy)
 */

import { Handle, Position } from '@xyflow/react'
import { CalendarClock } from 'lucide-react'
import { memo } from 'react'
import { cn } from '@/lib/utils'
import type { PriorPeriodOhlcNodeData } from '@/types/flow'

interface PriorPeriodOhlcNodeProps {
  data: PriorPeriodOhlcNodeData
  selected?: boolean
}

const periodLabels: Record<string, string> = {
  previous_hour: 'Prev Hour',
  previous_day: 'Prev Day',
  previous_week: 'Prev Week',
  previous_month: 'Prev Month',
}

export const PriorPeriodOhlcNode = memo(({ data, selected }: PriorPeriodOhlcNodeProps) => {
  return (
    <div className={cn('workflow-node min-w-[120px] border-l-primary', selected && 'selected')}>
      <Handle type="target" position={Position.Top} className="!top-0 !-translate-y-1/2" />
      <div className="p-2">
        <div className="mb-1.5 flex items-center gap-1.5">
          <div className="flex h-5 w-5 items-center justify-center rounded bg-primary/20 text-primary">
            <CalendarClock className="h-3 w-3" />
          </div>
          <div>
            <div className="text-xs font-medium leading-tight">
              {periodLabels[data.period] || 'Prev Day'}
            </div>
            <div className="text-[9px] text-muted-foreground">{data.exchange || 'NSE'}</div>
          </div>
        </div>
        <div className="rounded bg-muted/50 px-1.5 py-1">
          <div className="flex items-center justify-between">
            <span className="text-[10px] text-muted-foreground">Symbol</span>
            <span className="mono-data text-[10px] font-medium">{data.symbol || '-'}</span>
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

PriorPeriodOhlcNode.displayName = 'PriorPeriodOhlcNode'
