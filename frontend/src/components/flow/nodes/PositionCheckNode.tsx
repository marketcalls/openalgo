/**
 * Position Check Node
 * Check position status before action
 */

import { memo } from 'react'
import { Handle, Position } from '@xyflow/react'
import { Briefcase } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { PositionCheckNodeData } from '@/types/flow'

interface PositionCheckNodeProps {
  data: PositionCheckNodeData
  selected?: boolean
}

const conditionLabels: Record<string, string> = {
  exists: 'Has Position',
  not_exists: 'No Position',
  quantity_above: 'Qty Above',
  quantity_below: 'Qty Below',
  pnl_above: 'P&L Above',
  pnl_below: 'P&L Below',
}

export const PositionCheckNode = memo(({ data, selected }: PositionCheckNodeProps) => {
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
        className="!top-0 !-translate-y-1/2 !h-3 !w-3 !rounded-full !border-2 !border-background !bg-muted-foreground"
      />
      <div className="p-2">
        <div className="mb-1.5 flex items-center gap-1.5">
          <div className="node-icon flex h-5 w-5 items-center justify-center rounded">
            <Briefcase className="h-3 w-3" />
          </div>
          <div>
            <div className="text-xs font-medium leading-tight">Position</div>
            <div className="text-[9px] text-muted-foreground">
              Check
            </div>
          </div>
        </div>
        <div className="space-y-1">
          <div className="flex items-center justify-between rounded bg-muted/50 px-1.5 py-1">
            <span className="text-[10px] text-muted-foreground">Symbol</span>
            <span className="mono-data text-[10px] font-medium">{data.symbol || '-'}</span>
          </div>
          <div className="flex items-center justify-between rounded bg-muted/50 px-1.5 py-1">
            <span className="text-[10px] text-muted-foreground">Check</span>
            <span className="text-[10px] font-medium">
              {conditionLabels[data.condition] || data.condition}
            </span>
          </div>
          {(data.condition?.includes('above') || data.condition?.includes('below')) && (
            <div className="flex items-center justify-between text-[9px] text-muted-foreground">
              <span>Threshold:</span>
              <span className="mono-data">{data.threshold ?? 0}</span>
            </div>
          )}
        </div>
        {/* Handle labels */}
        <div className="mt-2 flex justify-between px-1 text-[8px]">
          <span className="text-buy">True</span>
          <span className="text-sell">False</span>
        </div>
      </div>
      {/* True output (left) */}
      <Handle
        type="source"
        position={Position.Bottom}
        id="true"
        className="!bottom-0 !translate-y-1/2 !bg-buy !h-3 !w-3 !rounded-full !border-2 !border-background"
        style={{ left: '25%' }}
      />
      {/* False output (right) */}
      <Handle
        type="source"
        position={Position.Bottom}
        id="false"
        className="!bottom-0 !translate-y-1/2 !bg-sell !h-3 !w-3 !rounded-full !border-2 !border-background"
        style={{ left: '75%' }}
      />
    </div>
  )
})

PositionCheckNode.displayName = 'PositionCheckNode'
