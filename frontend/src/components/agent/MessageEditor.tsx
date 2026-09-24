/**
 * Editing a question in place.
 *
 * The bubble becomes a textarea with Cancel and Send, which is the shape the
 * operator asked for and the one every chat surface has converged on. Sending
 * replaces the message and discards the answer that followed it.
 *
 * **The textarea starts focused with the caret at the end**, because an edit is
 * almost always an addition or a correction at the tail. Selecting the whole
 * text instead would make the first keystroke destroy the question, which is
 * only what somebody wants when they are rewriting from scratch.
 *
 * **Escape cancels and Enter sends**, matching the composer directly beneath
 * it. Shift and Enter is a newline in both, so a multi-line question can be
 * edited into another one without the two boxes disagreeing about what Enter
 * means.
 *
 * The height follows the content up to a cap, so a long question does not turn
 * into a two-line scroll box while it is being edited.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

/** Tallest the editor grows before it scrolls internally, in pixels. */
const MAX_HEIGHT = 320

export interface MessageEditorProps {
  /** The text as it stands. */
  value: string
  /** Called with the trimmed text. Not called when it is empty or unchanged. */
  onSend: (text: string) => void
  onCancel: () => void
  className?: string
}

export function MessageEditor({ value, onSend, onCancel, className }: MessageEditorProps) {
  const [draft, setDraft] = useState(value)
  const ref = useRef<HTMLTextAreaElement>(null)

  const resize = useCallback(() => {
    const node = ref.current
    if (!node) return
    node.style.height = 'auto'
    node.style.height = `${Math.min(node.scrollHeight, MAX_HEIGHT)}px`
  }, [])

  useEffect(() => {
    const node = ref.current
    if (!node) return
    node.focus()
    // Caret at the end rather than a full selection: see the module docstring.
    node.setSelectionRange(node.value.length, node.value.length)
    resize()
  }, [resize])

  const trimmed = draft.trim()
  // An unchanged question would truncate the answer and then reproduce it, so
  // the operator pays for a turn to arrive back where they started.
  const canSend = trimmed.length > 0 && trimmed !== value.trim()

  const submit = useCallback(() => {
    if (!canSend) return
    onSend(trimmed)
  }, [canSend, onSend, trimmed])

  return (
    <div
      className={cn(
        'w-full rounded-2xl border border-input bg-background p-2 shadow-xs',
        'focus-within:border-ring focus-within:ring-[3px] focus-within:ring-ring/50',
        className
      )}
    >
      <textarea
        ref={ref}
        value={draft}
        rows={1}
        onChange={(event) => {
          setDraft(event.target.value)
          resize()
        }}
        onKeyDown={(event) => {
          if (event.key === 'Escape') {
            event.preventDefault()
            onCancel()
            return
          }
          if (event.key === 'Enter' && !event.shiftKey) {
            event.preventDefault()
            submit()
          }
        }}
        aria-label="Edit your message"
        className="max-h-[320px] w-full resize-none bg-transparent px-1.5 py-1 text-sm leading-relaxed text-foreground outline-none"
      />
      <div className="flex items-center justify-end gap-2 pt-1">
        <Button type="button" variant="ghost" size="sm" onClick={onCancel} className="h-7 text-xs">
          Cancel
        </Button>
        <Button
          type="button"
          size="sm"
          onClick={submit}
          disabled={!canSend}
          className="h-7 text-xs"
        >
          Send
        </Button>
      </div>
      <p className="px-1 pt-1 text-[11px] text-muted-foreground">
        Sending replaces this message and discards the reply below it.
      </p>
    </div>
  )
}
