/**
 * Multi Quotes Node
 * Fetch quotes for multiple symbols at once
 */

import { memo } from 'react'
import { Handle, Position } from '@xyflow/react'
import { BarChart3 } from 'lucide-react'
import { cn } from '@/lib/utils'

interface MultiQuotesNodeData {
  symbols?: string
  exchange?: string
  outputVariable?: string
}

interface MultiQuotesNodeProps {
  data: MultiQuotesNodeData
  selected?: boolean
}

export const MultiQuotesNode = memo(({ data, selected }: MultiQuotesNodeProps) => {
  const symbolList = (data.symbols || '').split(',').filter(s => s.trim())

  return (
    <div
      className={cn(
        'workflow-node node-data min-w-[130px]',
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
            <BarChart3 className="h-3 w-3" />
          </div>
          <div>
            <div className="text-xs font-medium leading-tight">Multi Quotes</div>
            <div className="text-[9px] text-muted-foreground">
              {data.exchange || 'NSE'}
            </div>
          </div>
        </div>
        <div className="space-y-1">
          <div className="rounded bg-muted/50 px-1.5 py-1">
            <span className="text-[10px] text-muted-foreground">Symbols: </span>
            <span className="mono-data text-[10px] font-medium">
              {symbolList.length > 0 ? symbolList.length : 0}
            </span>
          </div>
          {symbolList.length > 0 && (
            <div className="rounded bg-muted/50 px-1.5 py-1">
              <span className="mono-data text-[9px] text-muted-foreground truncate block">
                {symbolList.slice(0, 3).join(', ')}
                {symbolList.length > 3 && '...'}
              </span>
            </div>
          )}
          {data.outputVariable && (
            <div className="rounded border border-border/50 bg-surface-2 px-1.5 py-0.5">
              <span className="text-[9px] text-muted-foreground">Output: </span>
              <span className="mono-data text-[9px] font-medium text-primary">
                {data.outputVariable}
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

MultiQuotesNode.displayName = 'MultiQuotesNode'
