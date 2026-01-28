/**
 * OR Gate Node
 * Combines multiple condition inputs - outputs Yes if ANY input is Yes
 */

import { memo } from 'react'
import { Handle, Position } from '@xyflow/react'
import { cn } from '@/lib/utils'

interface OrGateNodeProps {
  data: {
    label?: string
    inputCount?: number
  }
  selected?: boolean
}

export const OrGateNode = memo(({ data, selected }: OrGateNodeProps) => {
  const inputCount = data.inputCount || 2

  return (
    <div
      className={cn(
        'workflow-node node-condition min-w-[100px]',
        selected && 'selected'
      )}
    >
      {/* Multiple input handles */}
      {Array.from({ length: inputCount }).map((_, i) => {
        const position = (i + 1) / (inputCount + 1) * 100
        return (
          <Handle
            key={`input-${i}`}
            type="target"
            position={Position.Top}
            id={`input-${i}`}
            className="!top-0 !-translate-y-1/2"
            style={{ left: `${position}%` }}
          />
        )
      })}
      <div className="p-2">
        <div className="mb-1.5 flex items-center justify-center gap-1.5">
          <div className="node-icon flex h-6 w-6 items-center justify-center rounded bg-node-condition/20">
            <span className="text-[10px] font-bold text-node-condition">OR</span>
          </div>
        </div>
        <div className="rounded bg-muted/50 px-2 py-1 text-center">
          <div className="text-[9px] text-muted-foreground">
            Any condition can be true
          </div>
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
        className="!bottom-0 !translate-y-1/2 !bg-buy !w-3 !h-3"
        style={{ left: '25%' }}
      />
      {/* False output (right) */}
      <Handle
        type="source"
        position={Position.Bottom}
        id="false"
        className="!bottom-0 !translate-y-1/2 !bg-sell !w-3 !h-3"
        style={{ left: '75%' }}
      />
    </div>
  )
})

OrGateNode.displayName = 'OrGateNode'
