/**
 * NOT Gate Node
 * Inverts a condition - Yes becomes No, No becomes Yes
 */

import { memo } from 'react'
import { Handle, Position } from '@xyflow/react'
import { cn } from '@/lib/utils'

interface NotGateNodeProps {
  data: {
    label?: string
  }
  selected?: boolean
}

export const NotGateNode = memo(({ selected }: NotGateNodeProps) => {
  return (
    <div
      className={cn(
        'workflow-node node-condition min-w-[100px]',
        selected && 'selected'
      )}
    >
      {/* Single input handle */}
      <Handle
        type="target"
        position={Position.Top}
        id="input"
        className="!top-0 !-translate-y-1/2"
      />
      <div className="p-2">
        <div className="mb-1.5 flex items-center justify-center gap-1.5">
          <div className="node-icon flex h-6 w-6 items-center justify-center rounded bg-node-condition/20">
            <span className="text-[10px] font-bold text-node-condition">NOT</span>
          </div>
        </div>
        <div className="rounded bg-muted/50 px-2 py-1 text-center">
          <div className="text-[9px] text-muted-foreground">
            Inverts condition
          </div>
        </div>
        {/* Handle labels */}
        <div className="mt-2 flex justify-between px-1 text-[8px]">
          <span className="text-buy">Yes</span>
          <span className="text-sell">No</span>
        </div>
      </div>
      {/* Yes output (left) */}
      <Handle
        type="source"
        position={Position.Bottom}
        id="yes"
        className="!bottom-0 !translate-y-1/2 !bg-buy"
        style={{ left: '25%' }}
      />
      {/* No output (right) */}
      <Handle
        type="source"
        position={Position.Bottom}
        id="no"
        className="!bottom-0 !translate-y-1/2 !bg-sell"
        style={{ left: '75%' }}
      />
    </div>
  )
})

NotGateNode.displayName = 'NotGateNode'
