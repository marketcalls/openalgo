/**
 * Holidays Node
 * Get market holidays for a year
 */

import { memo } from 'react'
import { Handle, Position } from '@xyflow/react'
import { CalendarX } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { HolidaysNodeData } from '@/types/flow'

interface HolidaysNodeProps {
  data: HolidaysNodeData
  selected?: boolean
}

export const HolidaysNode = memo(({ data, selected }: HolidaysNodeProps) => {
  return (
    <div
      className={cn(
        'workflow-node min-w-[110px] border-l-purple-400',
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
          <div className="flex h-5 w-5 items-center justify-center rounded bg-purple-400/20 text-purple-400">
            <CalendarX className="h-3 w-3" />
          </div>
          <div>
            <div className="text-xs font-medium leading-tight">Holidays</div>
            <div className="text-[9px] text-muted-foreground">Market holidays</div>
          </div>
        </div>
        <div className="rounded bg-muted/50 px-1.5 py-1">
          <div className="flex items-center justify-between">
            <span className="text-[10px] text-muted-foreground">Year</span>
            <span className="mono-data text-[10px] font-medium">
              {data.year || new Date().getFullYear()}
            </span>
          </div>
        </div>
        {data.outputVariable && (
          <div className="mt-1 text-center text-[9px] text-muted-foreground">
            {data.outputVariable}
          </div>
        )}
      </div>
      <Handle
        type="source"
        position={Position.Bottom}
        className="!bottom-0 !translate-y-1/2"
      />
    </div>
  )
})

HolidaysNode.displayName = 'HolidaysNode'
