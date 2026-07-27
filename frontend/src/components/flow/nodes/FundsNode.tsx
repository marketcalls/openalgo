import { memo } from 'react'
import { Handle, Position } from '@xyflow/react'
import { Wallet } from 'lucide-react'
import { cn } from '@/lib/utils'

interface FundsNodeData {
  label?: string
  outputVariable?: string
}

interface FundsNodeProps {
  data: FundsNodeData
  selected?: boolean
}

export const FundsNode = memo(({ data, selected }: FundsNodeProps) => {
  return (
    <div className={cn('workflow-node min-w-[120px] border-l-amber-500', selected && 'selected')}>
      <Handle type="target" position={Position.Top} />
      <div className="p-2">
        <div className="mb-1.5 flex items-center gap-1.5">
          <div className="flex h-5 w-5 items-center justify-center rounded bg-amber-500/20 text-amber-500">
            <Wallet className="h-3 w-3" />
          </div>
          <div>
            <div className="text-xs font-medium leading-tight">Funds</div>
            <div className="text-[9px] text-muted-foreground">Account Balance</div>
          </div>
        </div>
        {data.outputVariable && (
          <div className="mt-1 text-[10px]">
            <div className="flex items-center justify-between">
              <span className="text-muted-foreground">Output:</span>
              <span className="mono-data text-amber-500">{`{{${data.outputVariable}}}`}</span>
            </div>
          </div>
        )}
      </div>
      <Handle type="source" position={Position.Bottom} />
    </div>
  )
})

FundsNode.displayName = 'FundsNode'
