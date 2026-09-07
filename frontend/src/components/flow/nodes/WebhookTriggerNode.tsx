/**
 * Webhook Trigger Node
 * Triggers workflow from external HTTP requests.
 *
 * The node carries no instrument of its own. Everything the workflow acts on
 * arrives in the request and is read downstream as `{{webhook.<field>}}`, so a
 * symbol configured here would be a second source of truth that nothing reads.
 */

import { Handle, Position } from '@xyflow/react'
import { Webhook } from 'lucide-react'
import { memo } from 'react'
import { cn } from '@/lib/utils'

interface WebhookTriggerNodeProps {
  data: {
    label?: string
  }
  selected?: boolean
}

export const WebhookTriggerNode = memo(({ data, selected }: WebhookTriggerNodeProps) => {
  return (
    <div className={cn('workflow-node node-trigger min-w-[120px]', selected && 'selected')}>
      <div className="p-2">
        <div className="mb-1.5 flex items-center gap-1.5">
          <div className="node-icon flex h-5 w-5 items-center justify-center rounded bg-node-trigger/20">
            <Webhook className="h-3 w-3 text-node-trigger" />
          </div>
          <div>
            <div className="text-xs font-medium leading-tight">Webhook</div>
            <div className="text-[9px] text-muted-foreground">External Trigger</div>
          </div>
        </div>
        {data.label && (
          <div className="rounded bg-muted/50 px-1.5 py-1 text-center">
            <span className="text-[10px] text-muted-foreground">{data.label}</span>
          </div>
        )}
      </div>
      <Handle type="source" position={Position.Bottom} className="!bottom-0 !translate-y-1/2" />
    </div>
  )
})

WebhookTriggerNode.displayName = 'WebhookTriggerNode'
