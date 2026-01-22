/**
 * Telegram Alert Node
 * Send notification via Telegram
 */

import { memo } from 'react'
import { Handle, Position } from '@xyflow/react'
import { Send } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { TelegramAlertNodeData } from '@/types/flow'

interface TelegramAlertNodeProps {
  data: TelegramAlertNodeData
  selected?: boolean
}

export const TelegramAlertNode = memo(({ data, selected }: TelegramAlertNodeProps) => {
  const nodeData = data as unknown as Record<string, unknown>
  const truncatedMessage = data.message
    ? data.message.length > 25
      ? `${data.message.substring(0, 25)}...`
      : data.message
    : 'No message'

  return (
    <div
      className={cn(
        'workflow-node min-w-[120px] border-l-muted-foreground',
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
          <div className="flex h-5 w-5 items-center justify-center rounded bg-[#0088cc]/20 text-[#0088cc]">
            <Send className="h-3 w-3" />
          </div>
          <div>
            <div className="text-xs font-medium leading-tight">Telegram</div>
            <div className="text-[9px] text-muted-foreground">
              {(nodeData.username as string) || 'No user'}
            </div>
          </div>
        </div>
        <div className="rounded bg-muted/50 px-1.5 py-1">
          <span className="text-[9px] text-muted-foreground line-clamp-2">
            {truncatedMessage}
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

TelegramAlertNode.displayName = 'TelegramAlertNode'
