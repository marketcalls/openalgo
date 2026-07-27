import { memo } from 'react'
import { Handle, Position } from '@xyflow/react'
import { WifiOff } from 'lucide-react'
import { cn } from '@/lib/utils'

interface UnsubscribeNodeData {
  label?: string
  symbol?: string
  exchange?: string
  streamType?: 'ltp' | 'quote' | 'depth' | 'all'
}

interface UnsubscribeNodeProps {
  data: UnsubscribeNodeData
  selected?: boolean
}

export const UnsubscribeNode = memo(({ data, selected }: UnsubscribeNodeProps) => {
  const streamLabels = {
    ltp: 'LTP',
    quote: 'Quote',
    depth: 'Depth',
    all: 'All Streams'
  }

  return (
    <div className={cn('workflow-node min-w-[120px] border-l-red-500', selected && 'selected')}>
      <Handle type="target" position={Position.Top} />
      <div className="p-2">
        <div className="mb-1.5 flex items-center gap-1.5">
          <div className="flex h-5 w-5 items-center justify-center rounded bg-red-500/20 text-red-500">
            <WifiOff className="h-3 w-3" />
          </div>
          <div>
            <div className="text-xs font-medium leading-tight">Unsubscribe</div>
            <div className="text-[9px] text-muted-foreground">Stop Stream</div>
          </div>
        </div>
        <div className="mt-1 space-y-0.5 text-[10px]">
          {data.symbol && (
            <div className="flex items-center justify-between">
              <span className="text-muted-foreground">Symbol:</span>
              <span className="mono-data font-medium">{data.symbol}</span>
            </div>
          )}
          <div className="flex items-center justify-between">
            <span className="text-muted-foreground">Type:</span>
            <span className="mono-data text-red-500">{streamLabels[data.streamType || 'all']}</span>
          </div>
        </div>
      </div>
      <Handle type="source" position={Position.Bottom} />
    </div>
  )
})

UnsubscribeNode.displayName = 'UnsubscribeNode'
