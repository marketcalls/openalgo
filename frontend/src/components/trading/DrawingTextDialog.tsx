/**
 * Settings for a text-bearing drawing (text, callout, price label).
 *
 * The chart engine renders every one of these style keys but ships no DOM, so
 * the form is the host's. It opens as soon as one of those tools is placed — an
 * empty text box on a chart is not useful — and again from the style bar's T
 * button to edit an existing one.
 *
 * Background and border are **off** unless the drawing already has them: text
 * dropped on a chart should be the words, not a filled plate.
 */
import { useEffect, useRef, useState } from 'react'
import type { DrawTextStyle } from '@/lib/trading/terminal'
import { cn } from '@/lib/utils'

export interface TextRequest {
  id: string
  tool: string
  style: DrawTextStyle
}

interface Props {
  req: TextRequest | null
  onSubmit(id: string, value: DrawTextStyle): void
  onClose(): void
}

const TITLES: Record<string, string> = {
  text: 'Text',
  callout: 'Callout',
  'price-label': 'Price label',
}

const SIZES = [10, 11, 12, 14, 16, 20, 24, 28, 32, 40]

export function DrawingTextDialog({ req, onSubmit, onClose }: Props) {
  const [v, setV] = useState<DrawTextStyle | null>(null)
  const ref = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    setV(req ? { ...req.style } : null)
    if (req) {
      // Focus and select, so editing an existing note is type-over.
      const t = setTimeout(() => {
        ref.current?.focus()
        ref.current?.select()
      }, 0)
      return () => clearTimeout(t)
    }
  }, [req])

  if (!req || !v) return null

  const set = <K extends keyof DrawTextStyle>(k: K, val: DrawTextStyle[K]) =>
    setV((p) => (p ? { ...p, [k]: val } : p))

  const commit = () => {
    // finally: this dialog is a full-pane overlay, so if onSubmit throws and
    // onClose is skipped, an invisible overlay swallows every subsequent chart
    // click and the chart looks dead.
    try {
      onSubmit(req.id, v)
    } finally {
      onClose()
    }
  }

  const tog =
    'flex h-7 w-7 items-center justify-center rounded border border-border text-[13px] transition-colors hover:bg-accent'
  const swatch = 'h-7 w-9 shrink-0 cursor-pointer rounded border border-border bg-transparent p-0.5'

  return (
    <div
      className="absolute inset-0 z-40 flex items-center justify-center bg-black/50"
      onMouseDown={(e) => e.target === e.currentTarget && onClose()}
      role="presentation"
    >
      <div className="w-80 rounded-lg border bg-popover shadow-2xl">
        <div className="flex items-center justify-between border-b px-4 py-2.5">
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

        <div className="space-y-3 px-4 py-3">
          {/* Colour, size, bold, italic — one row, as a text properties panel shows it. */}
          <div className="flex items-center gap-2">
            <input
              type="color"
              value={v.color}
              onChange={(e) => set('color', e.target.value)}
              aria-label="Font colour"
              className={swatch}
            />
            <div className="relative">
              <select
                value={v.fontSize}
                onChange={(e) => set('fontSize', Number(e.target.value))}
                aria-label="Font size"
                className="h-7 w-[68px] appearance-none rounded border border-border bg-background pl-2 pr-6 text-[13px] outline-none transition-colors hover:bg-accent focus:border-primary"
              >
                {SIZES.map((n) => (
                  <option key={n} value={n}>{n}</option>
                ))}
              </select>
              <svg
                viewBox="0 0 24 24"
                className="pointer-events-none absolute right-1.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground"
                fill="none"
                stroke="currentColor"
                strokeWidth={2}
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden="true"
              >
                <path d="M6 9l6 6 6-6" />
              </svg>
            </div>
            <button
              type="button"
              aria-label="Bold"
              aria-pressed={v.bold}
              onClick={() => set('bold', !v.bold)}
              className={cn(tog, 'font-bold', v.bold && 'border-primary/50 bg-primary/15 text-primary')}
            >
              B
            </button>
            <button
              type="button"
              aria-label="Italic"
              aria-pressed={v.italic}
              onClick={() => set('italic', !v.italic)}
              className={cn(tog, 'italic', v.italic && 'border-primary/50 bg-primary/15 text-primary')}
            >
              I
            </button>
          </div>

          <textarea
            ref={ref}
            value={v.text}
            onChange={(e) => set('text', e.target.value)}
            onKeyDown={(e) => {
              // Enter commits; Shift+Enter is a newline, which the renderer
              // honours. Escape abandons.
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                commit()
              }
              if (e.key === 'Escape') onClose()
            }}
            rows={4}
            placeholder="Type a note. Shift+Enter for a new line."
            className="w-full resize-none rounded border border-border bg-background p-2 text-[13px] outline-none focus:border-primary"
          />

          {/* Each toggle owns its colour, which stays visible but inert while
              the toggle is off — so its value survives being switched off. */}
          <label className="flex items-center gap-2 text-[13px]">
            <input
              type="checkbox"
              checked={v.background}
              onChange={(e) => set('background', e.target.checked)}
              className="h-3.5 w-3.5 accent-primary"
            />
            <span className="flex-1">Background</span>
            <input
              type="color"
              value={v.backgroundColor}
              onChange={(e) => set('backgroundColor', e.target.value)}
              aria-label="Background colour"
              disabled={!v.background}
              className={cn(swatch, !v.background && 'opacity-40')}
            />
          </label>

          <label className="flex items-center gap-2 text-[13px]">
            <input
              type="checkbox"
              checked={v.border}
              onChange={(e) => set('border', e.target.checked)}
              className="h-3.5 w-3.5 accent-primary"
            />
            <span className="flex-1">Border</span>
            <input
              type="color"
              value={v.borderColor}
              onChange={(e) => set('borderColor', e.target.value)}
              aria-label="Border colour"
              disabled={!v.border}
              className={cn(swatch, !v.border && 'opacity-40')}
            />
          </label>

          <label className="flex items-center gap-2 text-[13px]">
            <input
              type="checkbox"
              checked={v.wrap}
              onChange={(e) => set('wrap', e.target.checked)}
              className="h-3.5 w-3.5 accent-primary"
            />
            <span className="flex-1">Text wrap</span>
          </label>
        </div>

        <div className="flex justify-end gap-2 border-t px-4 py-3">
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
