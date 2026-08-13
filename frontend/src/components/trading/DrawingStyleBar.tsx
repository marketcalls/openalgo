/**
 * Floating style bar for the selected drawing — colour, thickness, dash, lock,
 * delete. Appears on selection and disappears with it, the way a charting
 * package's inline properties toolbar does.
 *
 * Lives inside the pane rather than being portalled, so it stays visible in
 * full screen where only the fullscreen element and its descendants paint.
 */
import { useEffect, useRef, useState } from 'react'
import type { DrawSelection } from '@/lib/trading/terminal'
import { cn } from '@/lib/utils'

interface Props {
  sel: DrawSelection | null
  onStyle(patch: {
    color?: string
    lineWidth?: number
    lineStyle?: 'solid' | 'dashed' | 'dotted'
    locked?: boolean
  }): void
  onDelete(): void
  /** Edit the content of a text-bearing drawing. */
  onEditText(): void
}

const SWATCHES = [
  '#4f8cff', '#26a69a', '#ef5350', '#f5a623', '#ab47bc',
  '#26c6da', '#9aa0b4', '#ffffff',
]
const WIDTHS = [1, 1.5, 2, 3, 4]
const DASHES: { value: 'solid' | 'dashed' | 'dotted'; label: string }[] = [
  { value: 'solid', label: '──' },
  { value: 'dashed', label: '- -' },
  { value: 'dotted', label: '···' },
]

export function DrawingStyleBar({ sel, onStyle, onDelete, onEditText }: Props) {
  const [open, setOpen] = useState<'color' | 'width' | 'dash' | null>(null)
  const ref = useRef<HTMLDivElement>(null)

  // Close the popovers when the selection changes or on an outside click.
  useEffect(() => setOpen(null), [])
  useEffect(() => {
    if (!open) return
    const close = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(null)
    }
    window.addEventListener('mousedown', close)
    return () => window.removeEventListener('mousedown', close)
  }, [open])

  if (!sel) return null

  const btn =
    'flex h-7 items-center justify-center gap-1 rounded px-1.5 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground'

  return (
    <div
      ref={ref}
      className="absolute left-1/2 top-2 z-30 flex -translate-x-1/2 items-center gap-0.5 rounded-lg border bg-background/95 p-1 shadow-lg backdrop-blur"
    >
      {/* Colour */}
      <div className="relative">
        <button
          type="button"
          title="Colour"
          aria-label="Colour"
          onClick={() => setOpen(open === 'color' ? null : 'color')}
          className={btn}
        >
          <span
            className="h-4 w-4 rounded-sm border border-border"
            style={{ background: sel.color }}
          />
        </button>
        {open === 'color' && (
          <div className="absolute left-0 top-9 grid w-40 grid-cols-4 gap-1 rounded-md border bg-popover p-2 shadow-lg">
            {SWATCHES.map((c) => (
              <button
                type="button"
                key={c}
                aria-label={c}
                onClick={() => {
                  onStyle({ color: c })
                  setOpen(null)
                }}
                style={{ background: c }}
                className={cn(
                  'h-6 w-6 rounded border',
                  c === sel.color ? 'ring-2 ring-primary' : 'border-border'
                )}
              />
            ))}
          </div>
        )}
      </div>

      {/* Thickness */}
      <div className="relative">
        <button
          type="button"
          title="Thickness"
          aria-label="Thickness"
          onClick={() => setOpen(open === 'width' ? null : 'width')}
          className={btn}
        >
          <span className="text-xs font-medium">{sel.lineWidth}px</span>
        </button>
        {open === 'width' && (
          <div className="absolute left-0 top-9 w-24 rounded-md border bg-popover p-1 shadow-lg">
            {WIDTHS.map((w) => (
              <button
                type="button"
                key={w}
                onClick={() => {
                  onStyle({ lineWidth: w })
                  setOpen(null)
                }}
                className={cn(
                  'flex w-full items-center gap-2 rounded-sm px-2 py-1 text-left text-xs hover:bg-accent',
                  w === sel.lineWidth && 'text-primary'
                )}
              >
                <span className="w-8 rounded bg-current" style={{ height: w }} />
                {w}px
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Dash */}
      <div className="relative">
        <button
          type="button"
          title="Line style"
          aria-label="Line style"
          onClick={() => setOpen(open === 'dash' ? null : 'dash')}
          className={btn}
        >
          <span className="text-xs">
            {DASHES.find((d) => d.value === sel.lineStyle)?.label ?? '──'}
          </span>
        </button>
        {open === 'dash' && (
          <div className="absolute left-0 top-9 w-24 rounded-md border bg-popover p-1 shadow-lg">
            {DASHES.map((d) => (
              <button
                type="button"
                key={d.value}
                onClick={() => {
                  onStyle({ lineStyle: d.value })
                  setOpen(null)
                }}
                className={cn(
                  'w-full rounded-sm px-2 py-1 text-left text-xs hover:bg-accent',
                  d.value === sel.lineStyle && 'text-primary'
                )}
              >
                {d.label} {d.value}
              </button>
            ))}
          </div>
        )}
      </div>

      {sel.hasText && (
        <>
          <div className="mx-0.5 h-5 w-px bg-border" />
          <button type="button" title="Edit text" aria-label="Edit text" onClick={onEditText} className={btn}>
            <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth={1.7} strokeLinecap="round" aria-hidden="true">
              <path d="M5 5.5h14M12 5.5V19" />
            </svg>
          </button>
        </>
      )}

      <div className="mx-0.5 h-5 w-px bg-border" />

      <button
        type="button"
        title={sel.locked ? 'Unlock' : 'Lock'}
        aria-label={sel.locked ? 'Unlock drawing' : 'Lock drawing'}
        onClick={() => onStyle({ locked: !sel.locked })}
        className={cn(btn, sel.locked && 'text-primary')}
      >
        <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth={1.7} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <rect x="4.5" y="10.5" width="15" height="9.5" rx="2" />
          {sel.locked ? (
            <path d="M8 10.5V7a4 4 0 0 1 8 0v3.5" />
          ) : (
            <path d="M8 10.5V7a4 4 0 0 1 7.6-1.7" />
          )}
        </svg>
      </button>

      <button type="button" title="Delete" aria-label="Delete drawing" onClick={onDelete} className={btn}>
        <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth={1.7} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M3.5 6.5h17M9.5 6.5v-3h5v3M6 6.5l1 14h10l1-14" />
        </svg>
      </button>
    </div>
  )
}
