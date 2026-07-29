/**
 * Var Condition Node
 * Compare any two interpolated values (a workflow variable, an indicator
 * output, a prior-period level, or a literal) for branching logic
 */

import { Handle, Position } from '@xyflow/react'
import { SlidersHorizontal } from 'lucide-react'
import { memo } from 'react'
import { cn } from '@/lib/utils'
import type { VarConditionNodeData } from '@/types/flow'

interface VarConditionNodeProps {
  data: VarConditionNodeData
  selected?: boolean
}

const operatorLabels: Record<string, string> = {
  '>': '>',
  '<': '<',
  '==': '=',
  '>=': '>=',
  '<=': '<=',
  '!=': '!=',
}

export const VarConditionNode = memo(({ data, selected }: VarConditionNodeProps) => {
  return (
    <div className={cn('workflow-node node-condition min-w-[130px]', selected && 'selected')}>
      <Handle
        type="target"
        position={Position.Top}
        className="!top-0 !-translate-y-1/2 !h-3 !w-3 !rounded-full !border-2 !border-background !bg-muted-foreground"
      />
      <div className="p-2">
        <div className="mb-1.5 flex items-center gap-1.5">
          <div className="node-icon flex h-5 w-5 items-center justify-center rounded">
            <SlidersHorizontal className="h-3 w-3" />
          </div>
          <div>
            <div className="text-xs font-medium leading-tight">Var</div>
            <div className="text-[9px] text-muted-foreground">Condition</div>
          </div>
        </div>
        <div className="rounded bg-muted/50 px-1.5 py-1 text-center">
          {/* Truncate via CSS, not slice(): a hard cut renders two distinct
              operands sharing a prefix as the same incomplete token. */}
          <span
            className="mono-data block truncate text-[9px] font-medium"
            title={`${data.leftValue || 'left'} ${operatorLabels[data.operator] || '>'} ${
              data.rightValue || 'right'
            }`}
          >
            {data.leftValue || 'left'} {operatorLabels[data.operator] || '>'}{' '}
            {data.rightValue || 'right'}
          </span>
        </div>
        <div className="mt-2 flex justify-between px-1 text-[8px]">
          <span className="text-buy">True</span>
          <span className="text-sell">False</span>
        </div>
      </div>
      <Handle
        type="source"
        position={Position.Bottom}
        id="true"
        className="!bottom-0 !translate-y-1/2 !bg-buy !h-3 !w-3 !rounded-full !border-2 !border-background"
        style={{ left: '25%' }}
      />
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

VarConditionNode.displayName = 'VarConditionNode'
