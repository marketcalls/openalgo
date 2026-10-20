/**
 * One attached file, as a chip.
 *
 * Two places show a file and they are the same object at two moments: the
 * composer, where it can still be taken off, and the question in the thread,
 * where it can not. So this is one component with an optional remove control
 * rather than two that would drift the first time the label or the size
 * formatting changed.
 *
 * The thumbnail comes from the data URL the composer already holds for the
 * request, so nothing is allocated to show it and there is no object URL to
 * revoke. A sent message has no bytes to show, by design: the server stores a
 * file's name, type, size and digest and never its content, so the chip in the
 * thread is a label rather than a picture.
 */

import { FileText, X } from 'lucide-react'
import type { AttachmentKind } from '@/lib/agent/attachments'
import { formatBytes } from '@/lib/agent/attachments'
import { cn } from '@/lib/utils'

export interface AttachmentChipProps {
  name: string
  kind: AttachmentKind
  size: number
  /** The image itself, when this file is still in hand. */
  src?: string
  /** Offered in the composer, withheld once the message is sent. */
  onRemove?: () => void
  className?: string
}

export function AttachmentChip({
  name,
  kind,
  size,
  src,
  onRemove,
  className,
}: AttachmentChipProps) {
  return (
    <div
      className={cn(
        'flex min-w-0 items-center gap-2 rounded-lg border border-border bg-muted/40 py-1 pr-1 pl-1.5',
        className
      )}
    >
      {kind === 'image' && src ? (
        <img
          src={src}
          alt={name}
          className="h-8 w-8 shrink-0 rounded object-cover"
          // Decorative at this size: the name beside it is the real label.
          draggable={false}
        />
      ) : (
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded bg-background">
          <FileText className="h-4 w-4 text-muted-foreground" aria-hidden />
        </span>
      )}
      <span className="flex min-w-0 flex-col leading-tight">
        <span className="max-w-[10rem] truncate text-xs">{name}</span>
        <span className="text-[10px] text-muted-foreground">{formatBytes(size)}</span>
      </span>
      {onRemove && (
        <button
          type="button"
          onClick={onRemove}
          aria-label={`Remove ${name}`}
          title="Remove"
          className={cn(
            'flex h-6 w-6 shrink-0 items-center justify-center rounded text-muted-foreground',
            'transition-colors hover:bg-accent hover:text-foreground',
            'focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring'
          )}
        >
          <X className="h-3.5 w-3.5" aria-hidden />
        </button>
      )}
    </div>
  )
}
