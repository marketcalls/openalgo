/**
 * HTTP Request Node
 * Make external API calls with configurable method, headers, and body
 */

import { memo } from 'react'
import { Handle, Position } from '@xyflow/react'
import { Globe } from 'lucide-react'
import { cn } from '@/lib/utils'

interface HttpRequestNodeProps {
  data: {
    label?: string
    method?: string
    url?: string
    outputVariable?: string
  }
  selected?: boolean
}

const methodColors: Record<string, string> = {
  GET: 'text-green-500',
  POST: 'text-blue-500',
  PUT: 'text-orange-500',
  DELETE: 'text-red-500',
  PATCH: 'text-purple-500',
}

export const HttpRequestNode = memo(({ data, selected }: HttpRequestNodeProps) => {
  const method = data.method || 'GET'
  const url = data.url || ''
  const displayUrl = url.length > 20 ? `${url.substring(0, 20)}...` : url

  return (
    <div
      className={cn(
        'workflow-node min-w-[140px] border-l-primary',
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
          <div className="node-icon flex h-5 w-5 items-center justify-center rounded bg-primary/20">
            <Globe className="h-3 w-3 text-primary" />
          </div>
          <div>
            <div className="text-xs font-medium leading-tight">HTTP Request</div>
            <div className="text-[9px] text-muted-foreground">
              API Call
            </div>
          </div>
        </div>
        <div className="space-y-1">
          <div className="flex items-center gap-1.5">
            <span className={cn('text-[10px] font-bold', methodColors[method] || 'text-muted-foreground')}>
              {method}
            </span>
            {displayUrl && (
              <span className="truncate text-[9px] text-muted-foreground">
                {displayUrl}
              </span>
            )}
          </div>
          {data.outputVariable && (
            <div className="rounded bg-muted/50 px-1.5 py-0.5">
              <span className="text-[9px] text-muted-foreground">
                {`{{${data.outputVariable}}}`}
              </span>
            </div>
          )}
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

HttpRequestNode.displayName = 'HttpRequestNode'
