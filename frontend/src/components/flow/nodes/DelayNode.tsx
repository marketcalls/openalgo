/**
 * Delay Node
 * Wait for specified duration
 */

import { memo } from 'react'
import { Handle, Position } from '@xyflow/react'
import { Timer } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { DelayNodeData } from '@/types/flow'

interface DelayNodeProps {
  data: DelayNodeData
  selected?: boolean
}

function formatDelay(data: DelayNodeData): string {
  // New format: delayValue + delayUnit
  if (data.delayValue !== undefined) {
    const value = data.delayValue
    const unit = data.delayUnit || 'seconds'
    const unitLabels: Record<string, string> = {
      seconds: 's',
      minutes: 'm',
      hours: 'h',
    }
    return `${value}${unitLabels[unit] || 's'}`
  }
  // Backward compatibility: old delayMs format
  const ms = data.delayMs || 1000
  if (ms >= 60000) {
    const mins = Math.floor(ms / 60000)
    const secs = Math.floor((ms % 60000) / 1000)
    return secs > 0 ? `${mins}m ${secs}s` : `${mins}m`
  }
  if (ms >= 1000) {
    return `${ms / 1000}s`
  }
  return `${ms}ms`
}

export const DelayNode = memo(({ data, selected }: DelayNodeProps) => {
  return (
    <div
      className={cn(
        'workflow-node min-w-[100px] border-l-muted-foreground',
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
          <div className="flex h-5 w-5 items-center justify-center rounded bg-muted text-muted-foreground">
            <Timer className="h-3 w-3" />
          </div>
          <div>
            <div className="text-xs font-medium leading-tight">Wait Duration</div>
            <div className="text-[9px] text-muted-foreground">
              Delay
            </div>
          </div>
        </div>
        <div className="rounded bg-muted/50 px-1.5 py-1 text-center">
          <span className="mono-data text-sm font-semibold text-primary">
            {formatDelay(data)}
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

DelayNode.displayName = 'DelayNode'
