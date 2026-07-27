/**
 * Log Node
 * Log messages for debugging workflows
 * Supports variable interpolation with {{variableName}}
 */

import { memo } from 'react'
import { Handle, Position } from '@xyflow/react'
import { FileText } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { LogNodeData } from '@/types/flow'

interface LogNodeProps {
  data: LogNodeData
  selected?: boolean
}

const levelColors: Record<string, string> = {
  info: 'text-blue-400',
  warn: 'text-yellow-400',
  error: 'text-red-400',
}

const levelLabels: Record<string, string> = {
  info: 'INFO',
  warn: 'WARN',
  error: 'ERROR',
}

export const LogNode = memo(({ data, selected }: LogNodeProps) => {
  const truncatedMessage = (data.message || 'Log message').slice(0, 30)
  const hasMore = (data.message || '').length > 30

  return (
    <div
      className={cn(
        'workflow-node node-utility min-w-[110px]',
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
            <FileText className="h-3 w-3" />
          </div>
          <div>
            <div className="text-xs font-medium leading-tight">Log</div>
            <div className={cn('text-[9px]', levelColors[data.level] || 'text-muted-foreground')}>
              {levelLabels[data.level] || 'INFO'}
            </div>
          </div>
        </div>
        <div className="rounded bg-muted/50 px-1.5 py-1">
          <span className="text-[10px] text-muted-foreground">
            {truncatedMessage}{hasMore && '...'}
          </span>
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

LogNode.displayName = 'LogNode'
