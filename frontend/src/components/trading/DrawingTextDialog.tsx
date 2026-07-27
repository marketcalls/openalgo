/**
 * Text entry for a text-bearing drawing (text, callout, price label).
 *
 * The chart engine renders `style.text` but ships no DOM, so collecting the
 * content is the host's job. Opens as soon as one of those tools is placed —
 * an empty text box on a chart is not useful — and again from the style bar's
 * T button to edit an existing one.
 */
import { useEffect, useRef, useState } from 'react'

interface Props {
  req: { id: string; tool: string; text: string } | null
  onSubmit(id: string, text: string): void
  onClose(): void
}

const TITLES: Record<string, string> = {
  text: 'Text',
  callout: 'Callout',
  'price-label': 'Price label',
}

export function DrawingTextDialog({ req, onSubmit, onClose }: Props) {
  const [value, setValue] = useState('')
  const ref = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    setValue(req?.text ?? '')
    if (req) {
      // Focus and select, so editing an existing note is type-over.
      const t = setTimeout(() => {
        ref.current?.focus()
        ref.current?.select()
      }, 0)
      return () => clearTimeout(t)
    }
  }, [req])

  if (!req) return null

  const commit = () => {
    onSubmit(req.id, value)
    onClose()
  }

  return (
    <div
      className="absolute inset-0 z-40 flex items-center justify-center bg-black/50"
      onMouseDown={(e) => e.target === e.currentTarget && onClose()}
      role="presentation"
    >
      <div className="w-72 rounded-lg border bg-popover shadow-2xl">
        <div className="flex items-center justify-between px-4 pb-2 pt-3">
          <h3 className="text-[15px] font-semibold tracking-tight">
            {TITLES[req.tool] ?? 'Text'}
          </h3>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="-mr-1 rounded p-1 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
          >
            <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" aria-hidden="true">
              <path d="M6 6l12 12M18 6L6 18" />
            </svg>
          </button>
        </div>

        <div className="px-4">
          <textarea
            ref={ref}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={(e) => {
              // Enter commits; Shift+Enter is a newline, which the renderer
              // honours. Escape abandons.
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                commit()
              }
              if (e.key === 'Escape') onClose()
            }}
            rows={3}
            placeholder="Type a note. Shift+Enter for a new line."
            className="w-full resize-none rounded border border-border bg-background p-2 text-[13px] outline-none focus:border-primary"
          />
        </div>

        <div className="flex justify-end gap-2 px-4 py-3">
          <button
            type="button"
            onClick={onClose}
            className="rounded border border-foreground/25 px-3.5 py-1 text-[13px] transition-colors hover:border-foreground/50 hover:bg-accent"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={commit}
            className="rounded bg-foreground px-5 py-1 text-[13px] font-medium text-background transition-opacity hover:opacity-90"
          >
            Ok
          </button>
        </div>
      </div>
    </div>
  )
}
