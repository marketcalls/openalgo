/**
 * The controls that appear under a message: copy, edit, retry.
 *
 * **They appear on hover and on focus, not permanently.** A row of buttons
 * under every turn competes with the answer for attention, and most turns are
 * read rather than acted on. `focus-within` is what keeps that from being a
 * mouse-only feature: tabbing into the row reveals it exactly as hovering does.
 *
 * **Copy takes the raw text, not the rendered DOM.** Copying the rendered node
 * would carry the markdown as it was *displayed* - bullet glyphs, code block
 * chrome, table borders - and paste it into an editor as something nobody
 * wrote. The stored string is what the model actually produced.
 *
 * **Editing is destructive and says so by doing it, not by asking.** Saving an
 * edit deletes the answer that followed and everything after it, which is the
 * behaviour the operator asked for. A confirmation dialog on every edit would
 * be worse than the thing it guards: the answer visibly disappearing is its own
 * warning, and it is undone by asking again rather than by an undo stack.
 */

import { Check, Copy, Pencil, RotateCcw } from 'lucide-react'
import { useCallback, useState } from 'react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

/** How long the copy control shows its confirmation, in milliseconds. */
const COPIED_MS = 1500

/**
 * Put text on the clipboard, with a fallback for an insecure origin.
 *
 * `navigator.clipboard` is undefined on plain http, which a self-hosted install
 * reached over a LAN address is, so the textarea path is not legacy support: it
 * is the path most OpenAlgo installs actually take.
 */
async function copyText(text: string): Promise<boolean> {
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text)
      return true
    } catch {
      // Fall through. A permissions policy can reject it even on https.
    }
  }
  const area = document.createElement('textarea')
  area.value = text
  area.setAttribute('readonly', '')
  area.style.position = 'fixed'
  area.style.opacity = '0'
  document.body.appendChild(area)
  area.select()
  try {
    return document.execCommand('copy')
  } catch {
    return false
  } finally {
    document.body.removeChild(area)
  }
}

function ActionButton({
  label,
  onClick,
  disabled,
  children,
}: {
  label: string
  onClick: () => void
  disabled?: boolean
  children: React.ReactNode
}) {
  return (
    <Button
      type="button"
      variant="ghost"
      size="icon-sm"
      onClick={onClick}
      disabled={disabled}
      aria-label={label}
      title={label}
      className="h-7 w-7 text-muted-foreground hover:text-foreground"
    >
      {children}
    </Button>
  )
}

export interface MessageActionsProps {
  /** The text copy puts on the clipboard. */
  text: string
  /** Shown only when supplied. Absent on a surface that cannot edit. */
  onEdit?: () => void
  /** Shown only when supplied, and only worth offering on a failed turn. */
  onRetry?: () => void
  /** True while a turn streams: acting mid-run would race the answer. */
  disabled?: boolean
  className?: string
}

export function MessageActions({
  text,
  onEdit,
  onRetry,
  disabled = false,
  className,
}: MessageActionsProps) {
  const [copied, setCopied] = useState(false)

  const copy = useCallback(() => {
    void copyText(text).then((ok) => {
      if (!ok) return
      setCopied(true)
      window.setTimeout(() => setCopied(false), COPIED_MS)
    })
  }, [text])

  return (
    <div
      className={cn(
        'flex items-center gap-0.5 opacity-0 transition-opacity',
        'group-hover:opacity-100 focus-within:opacity-100',
        className
      )}
    >
      <ActionButton label={copied ? 'Copied' : 'Copy'} onClick={copy}>
        {copied ? (
          <Check className="h-3.5 w-3.5 text-emerald-600 dark:text-emerald-400" aria-hidden />
        ) : (
          <Copy className="h-3.5 w-3.5" aria-hidden />
        )}
      </ActionButton>

      {onRetry && (
        <ActionButton label="Try again" onClick={onRetry} disabled={disabled}>
          <RotateCcw className="h-3.5 w-3.5" aria-hidden />
        </ActionButton>
      )}

      {onEdit && (
        <ActionButton label="Edit message" onClick={onEdit} disabled={disabled}>
          <Pencil className="h-3.5 w-3.5" aria-hidden />
        </ActionButton>
      )}
    </div>
  )
}
