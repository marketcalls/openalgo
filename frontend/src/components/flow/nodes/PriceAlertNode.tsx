/**
 * Price Alert Node
 * Trigger workflow when price condition is met
 * Uses quotes API to fetch LTP and compare with target price
 */

import { memo } from 'react'
import { Handle, Position } from '@xyflow/react'
import { Bell } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { PriceAlertNodeData } from '@/types/flow'

interface PriceAlertNodeProps {
  data: PriceAlertNodeData
  selected?: boolean
}

const conditionLabels: Record<string, string> = {
  above: '>',
  below: '<',
  crosses_above: 'crosses >',
  crosses_below: 'crosses <',
}

const conditionDescriptions: Record<string, string> = {
  above: 'LTP Above',
  below: 'LTP Below',
  crosses_above: 'Crosses Above',
  crosses_below: 'Crosses Below',
}

export const PriceAlertNode = memo(({ data, selected }: PriceAlertNodeProps) => {
  return (
    <div
      className={cn(
        'workflow-node node-condition min-w-[120px]',
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
            <Bell className="h-3 w-3" />
          </div>
          <div>
            <div className="text-xs font-medium leading-tight">Price Alert</div>
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
          <div className="flex items-center justify-between rounded bg-muted/50 px-1.5 py-1">
            <span className="text-[10px] text-muted-foreground">
              {conditionDescriptions[data.condition] || 'Condition'}
            </span>
            <span className="mono-data text-[10px] font-medium text-primary">
              {data.price || 0}
            </span>
          </div>
          {data.ltp !== undefined && (
            <div className="flex items-center justify-between rounded border border-border/50 bg-surface-2 px-1.5 py-0.5">
              <span className="text-[9px] text-muted-foreground">LTP</span>
              <span className="mono-data text-[10px] font-semibold">
                {data.ltp.toFixed(2)}
              </span>
            </div>
          )}
          <div className="text-center text-[8px] text-muted-foreground">
            LTP {conditionLabels[data.condition] || '>'} {data.price || 0}
          </div>
        </div>
        {/* Handle labels */}
        <div className="mt-2 flex justify-between px-1 text-[8px]">
          <span className="text-buy">Yes</span>
          <span className="text-sell">No</span>
        </div>
      </div>
      {/* True output (left) - Condition met */}
      <Handle
        type="source"
        position={Position.Bottom}
        id="true"
        className="!bottom-0 !left-1/4 !translate-y-1/2 !bg-buy"
        style={{ left: '25%' }}
      />
      {/* False output (right) - Condition not met */}
      <Handle
        type="source"
        position={Position.Bottom}
        id="false"
        className="!bottom-0 !left-3/4 !translate-y-1/2 !bg-sell"
        style={{ left: '75%' }}
      />
    </div>
  )
})

PriceAlertNode.displayName = 'PriceAlertNode'
