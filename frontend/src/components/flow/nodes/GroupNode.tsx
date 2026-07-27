/**
 * Group Node
 * Container for grouping related nodes together
 */

import { memo } from 'react'
import { Handle, Position, NodeResizer } from '@xyflow/react'
import { Layers } from 'lucide-react'
import { cn } from '@/lib/utils'

interface GroupNodeData {
  label?: string
  color?: string
}

interface GroupNodeProps {
  data: GroupNodeData
  selected?: boolean
}

const colorClasses: Record<string, string> = {
  blue: 'border-blue-500/30 bg-blue-500/5',
  green: 'border-buy/30 bg-buy/5',
  red: 'border-sell/30 bg-sell/5',
  purple: 'border-purple-500/30 bg-purple-500/5',
  orange: 'border-orange-500/30 bg-orange-500/5',
  default: 'border-border/50 bg-muted/20',
}

export const GroupNode = memo(({ data, selected }: GroupNodeProps) => {
  const colorClass = colorClasses[data.color || 'default'] || colorClasses.default

  return (
    <div
      className={cn(
        'min-h-[150px] min-w-[200px] rounded-lg border-2 border-dashed',
        colorClass,
        selected && 'ring-2 ring-primary ring-offset-2 ring-offset-background'
      )}
    >
      <NodeResizer
        minWidth={200}
        minHeight={150}
        isVisible={selected}
        lineClassName="!border-primary"
        handleClassName="!h-2 !w-2 !rounded-full !border-2 !border-primary !bg-background"
      />
      <Handle
        type="target"
        position={Position.Top}
        className="!top-0 !-translate-y-1/2"
      />
      <div className="absolute -top-3 left-3 flex items-center gap-1.5 rounded bg-background px-2 py-0.5">
        <Layers className="h-3 w-3 text-muted-foreground" />
        <span className="text-xs font-medium">{data.label || 'Group'}</span>
      </div>
      <Handle
        type="source"
        position={Position.Bottom}
        className="!bottom-0 !translate-y-1/2"
      />
    </div>
  )
})

GroupNode.displayName = 'GroupNode'
