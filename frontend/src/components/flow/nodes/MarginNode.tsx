import { memo } from 'react'
import { Handle, Position } from '@xyflow/react'
import { Calculator } from 'lucide-react'
import { cn } from '@/lib/utils'

interface MarginNodeData {
  label?: string
  positions?: Array<{
    symbol: string
    exchange: string
    action: 'BUY' | 'SELL'
    quantity: number
    product: string
    priceType: string
  }>
  outputVariable?: string
}

interface MarginNodeProps {
  data: MarginNodeData
  selected?: boolean
}

export const MarginNode = memo(({ data, selected }: MarginNodeProps) => {
  const positionCount = data.positions?.length || 0

  return (
    <div className={cn('workflow-node min-w-[120px] border-l-amber-500', selected && 'selected')}>
      <Handle type="target" position={Position.Top} />
      <div className="p-2">
        <div className="mb-1.5 flex items-center gap-1.5">
          <div className="flex h-5 w-5 items-center justify-center rounded bg-amber-500/20 text-amber-500">
            <Calculator className="h-3 w-3" />
          </div>
          <div>
            <div className="text-xs font-medium leading-tight">Margin Calc</div>
            <div className="text-[9px] text-muted-foreground">Risk Check</div>
          </div>
        </div>
        <div className="mt-1 space-y-0.5 text-[10px]">
          <div className="flex items-center justify-between">
            <span className="text-muted-foreground">Positions:</span>
            <span className="mono-data font-medium">{positionCount}</span>
          </div>
          {data.outputVariable && (
            <div className="flex items-center justify-between">
              <span className="text-muted-foreground">Output:</span>
              <span className="mono-data text-amber-500">{`{{${data.outputVariable}}}`}</span>
            </div>
          )}
        </div>
      </div>
      <Handle type="source" position={Position.Bottom} />
    </div>
  )
})

MarginNode.displayName = 'MarginNode'
