/**
 * Expiry Node
 * Get expiry dates for a symbol
 */

import { memo } from 'react'
import { Handle, Position } from '@xyflow/react'
import { Calendar } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { ExpiryNodeData } from '@/types/flow'

interface ExpiryNodeProps {
  data: ExpiryNodeData
  selected?: boolean
}

export const ExpiryNode = memo(({ data, selected }: ExpiryNodeProps) => {
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
            <Calendar className="h-3 w-3" />
          </div>
          <div>
            <div className="text-xs font-medium leading-tight">Expiry</div>
            <div className="text-[9px] text-muted-foreground">
              {data.exchange || 'NFO'}
            </div>
          </div>
        </div>
        <div className="space-y-1">
          <div className="flex items-center justify-between rounded bg-muted/50 px-1.5 py-1">
            <span className="text-[10px] text-muted-foreground">Symbol</span>
            <span className="mono-data text-[10px] font-medium">{data.symbol || 'NIFTY'}</span>
          </div>
          {data.outputVariable && (
            <div className="text-center text-[9px] text-muted-foreground">
              {data.outputVariable}
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

ExpiryNode.displayName = 'ExpiryNode'
