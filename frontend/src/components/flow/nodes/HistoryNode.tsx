/**
 * History Node
 * Fetch historical OHLCV data for a symbol
 */

import { memo } from 'react'
import { Handle, Position } from '@xyflow/react'
import { TrendingUp } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { HistoryNodeData } from '@/types/flow'

interface HistoryNodeProps {
  data: HistoryNodeData
  selected?: boolean
}

const intervalLabels: Record<string, string> = {
  '1m': '1 Min',
  '5m': '5 Min',
  '15m': '15 Min',
  '30m': '30 Min',
  '1h': '1 Hour',
  '1d': 'Daily',
}

export const HistoryNode = memo(({ data, selected }: HistoryNodeProps) => {
  return (
    <div
      className={cn(
        'workflow-node min-w-[110px] border-l-primary',
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
            <TrendingUp className="h-3 w-3" />
          </div>
          <div>
            <div className="text-xs font-medium leading-tight">History</div>
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
          <div className="flex items-center justify-between text-[9px] text-muted-foreground">
            <span>{intervalLabels[data.interval] || data.interval || '1d'}</span>
            <span>{data.days || 30} days</span>
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

HistoryNode.displayName = 'HistoryNode'
