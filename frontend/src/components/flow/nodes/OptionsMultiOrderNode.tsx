/**
 * Options Multi-Order Node
 * Multi-leg options strategies (Iron Condor, Straddle, etc.)
 */

import { memo } from 'react'
import { Handle, Position } from '@xyflow/react'
import { Layers } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { OptionsMultiOrderNodeData } from '@/types/flow'

interface OptionsMultiOrderNodeProps {
  data: OptionsMultiOrderNodeData
  selected?: boolean
}

const strategyLabels: Record<string, string> = {
  iron_condor: 'Iron Condor',
  straddle: 'Straddle',
  strangle: 'Strangle',
  bull_call_spread: 'Bull Call',
  bear_put_spread: 'Bear Put',
  custom: 'Custom',
}

const expiryLabels: Record<string, string> = {
  current_week: 'This Week',
  next_week: 'Next Week',
  current_month: 'This Month',
  next_month: 'Next Month',
}

// Get strategy leg count
const getStrategyLegCount = (strategy: string): number => {
  switch (strategy) {
    case 'straddle':
    case 'strangle':
    case 'bull_call_spread':
    case 'bear_put_spread':
      return 2
    case 'iron_condor':
      return 4
    default:
      return 0
  }
}

export const OptionsMultiOrderNode = memo(({ data, selected }: OptionsMultiOrderNodeProps) => {
  const legCount = data.legs?.length || getStrategyLegCount(data.strategy)
  const nodeData = data as unknown as Record<string, unknown>

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
            <Layers className="h-3 w-3" />
          </div>
          <div>
            <div className="text-xs font-medium leading-tight">Multi-Leg</div>
            <div className="text-[9px] text-muted-foreground">
              {data.underlying || 'NIFTY'}
            </div>
          </div>
        </div>
        <div className="space-y-1">
          <div className="flex items-center justify-between rounded bg-muted/50 px-1.5 py-1">
            <span className="text-[10px] text-muted-foreground">Strategy</span>
            <span className="text-[10px] font-medium">
              {strategyLabels[data.strategy] || data.strategy}
            </span>
          </div>
          <div className="flex items-center justify-between rounded bg-muted/50 px-1.5 py-1">
            <span className="text-[10px] text-muted-foreground">Legs</span>
            <span className="mono-data text-[10px] font-medium">{legCount}</span>
          </div>
          <div className="flex items-center justify-between rounded bg-muted/50 px-1.5 py-1">
            <span className="text-[10px] text-muted-foreground">Expiry</span>
            <span className="text-[10px] font-medium">
              {expiryLabels[(nodeData.expiryType as string) || ''] || 'This Week'}
            </span>
          </div>
          <div className="flex items-center justify-between text-[9px] text-muted-foreground">
            <span className={cn(
              'font-medium',
              (nodeData.action as string) === 'BUY' ? 'text-buy' : 'text-sell'
            )}>
              {(nodeData.action as string) || 'SELL'}
            </span>
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

OptionsMultiOrderNode.displayName = 'OptionsMultiOrderNode'
