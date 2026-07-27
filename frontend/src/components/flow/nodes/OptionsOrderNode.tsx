/**
 * Options Order Node
 * Place ATM/ITM/OTM options orders
 */

import { memo } from 'react'
import { Handle, Position } from '@xyflow/react'
import { TrendingUp } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { OptionsOrderNodeData } from '@/types/flow'

interface OptionsOrderNodeProps {
  data: OptionsOrderNodeData
  selected?: boolean
}

const expiryLabels: Record<string, string> = {
  current_week: 'This Week',
  next_week: 'Next Week',
  current_month: 'This Month',
  next_month: 'Next Month',
}

export const OptionsOrderNode = memo(({ data, selected }: OptionsOrderNodeProps) => {
  const nodeData = data as unknown as Record<string, unknown>
  const expiryType = (nodeData.expiryType as string) || 'current_week'

  return (
    <div
      className={cn(
        'workflow-node node-action min-w-[130px]',
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
            <TrendingUp className="h-3 w-3" />
          </div>
          <div>
            <div className="text-xs font-medium leading-tight">Options</div>
            <div className="text-[9px] text-muted-foreground">
              {data.underlying || 'NIFTY'}
            </div>
          </div>
        </div>
        <div className="space-y-1">
          <div className="flex items-center justify-between rounded bg-muted/50 px-1.5 py-1">
            <span className="text-[10px] text-muted-foreground">Strike</span>
            <span className="mono-data text-[10px] font-medium">
              {data.offset || 'ATM'} {data.optionType || 'CE'}
            </span>
          </div>
          <div className="flex items-center justify-between rounded bg-muted/50 px-1.5 py-1">
            <span className="text-[10px] text-muted-foreground">Expiry</span>
            <span className="text-[10px] font-medium">
              {expiryLabels[expiryType] || 'This Week'}
            </span>
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
          <div className="flex items-center justify-between text-[9px] text-muted-foreground">
            <span>{data.product || 'MIS'}</span>
            <span>{data.priceType || 'MARKET'}</span>
          </div>
          {data.ltp !== undefined && (
            <div className="mt-0.5 flex items-center justify-between rounded border border-border/50 bg-surface-2 px-1.5 py-0.5">
              <span className="text-[9px] text-muted-foreground">LTP</span>
              <span className="mono-data text-[10px] font-semibold text-primary">
                {data.ltp.toFixed(2)}
              </span>
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

OptionsOrderNode.displayName = 'OptionsOrderNode'
