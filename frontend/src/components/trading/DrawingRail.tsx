/**
 * Vertical drawing-tool rail, overlaid on the left edge of a chart pane.
 *
 * Purely additive: the pane's existing trading controls (symbol, timeframe,
 * chart type, product, qty, right-click order entry) are untouched. A group
 * button opens a flyout of its tools; a plain click re-arms the last tool used
 * in that group, which is what makes a 40-tool set usable from eight buttons.
 */
import { useEffect, useRef, useState } from 'react'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { DRAW_GROUPS, drawToolIcon } from '@/lib/trading/drawTools'
import type { DrawStats } from '@/lib/trading/terminal'
import { cn } from '@/lib/utils'

interface Props {
  stats: DrawStats
  onPick(toolId: string | null): void
  onUndo(): void
  onRedo(): void
  onRemove(all: boolean): void
  onMagnet(on: boolean): void
  /**
   * Where to portal the flyouts. Menus default to `document.body`, which is
   * invisible while the pane is in the Fullscreen API's top layer — so in full
   * screen no tool could be picked at all.
   */
  portalHost?: HTMLElement | null
}

/** Which group owns a tool id, so the rail can highlight the active button. */
function groupOf(toolId: string | null): string | null {
  if (!toolId) return null
  for (const g of DRAW_GROUPS) {
    for (const sec of g.sections) {
      if (sec.tools.some((t) => t.id === toolId)) return g.key
    }
  }
  return null
}

export function DrawingRail({ stats, onPick, onUndo, onRedo, onRemove, onMagnet, portalHost }: Props) {
  // Last tool chosen per group, so the bare button re-arms it instead of
  // reopening the flyout every time.
  const lastRef = useRef<Record<string, string>>({})
  const [open, setOpen] = useState<string | null>(null)
  const activeGroup = groupOf(stats.tool)

  if (stats.tool) lastRef.current[activeGroup ?? ''] = stats.tool

  // Esc returns to the cursor, matching the chart's own drawing shortcuts.
  useEffect(() => {
    if (!stats.tool) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onPick(null)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [stats.tool, onPick])

  const btn =
    'flex h-8 w-8 items-center justify-center rounded-md border border-transparent text-muted-foreground transition-colors hover:bg-accent hover:text-foreground disabled:pointer-events-none disabled:opacity-30'
  const on = 'border-primary/40 bg-primary/15 text-primary'

  return (
    // A flush column with a divider, not a floating card: the plot starts to
    // its right, so nothing the chart draws in that corner can sit under it.
    <div className="flex w-10 shrink-0 flex-col items-center gap-0.5 no-scrollbar overflow-y-auto border-r bg-background/40 py-1">
      {/* Cursor — disarms whatever is active */}
      <button
        type="button"
        title="Cursor (Esc)"
        aria-label="Cursor"
        onClick={() => onPick(null)}
        className={cn(btn, !stats.tool && on)}
      >
        <span className="h-[18px] w-[18px]">{drawToolIcon('cursor')}</span>
      </button>

      <div className="my-0.5 h-px w-5 bg-border" />

      {DRAW_GROUPS.map((g) => {
        const last = lastRef.current[g.key]
        return (
          <DropdownMenu
            key={g.key}
            open={open === g.key}
            onOpenChange={(o) => setOpen(o ? g.key : null)}
          >
            <div className="relative">
              <button
                type="button"
                title={g.label}
                aria-label={g.label}
                onClick={() => {
                  // Re-arm the group's last tool; open the list if there is none.
                  if (last) onPick(last)
                  else setOpen(g.key)
                }}
                onContextMenu={(e) => {
                  e.preventDefault()
                  setOpen(g.key)
                }}
                className={cn(btn, activeGroup === g.key && on)}
              >
                <span className="h-[18px] w-[18px]">{drawToolIcon(g.iconKey)}</span>
              </button>
              {/* Caret opens the flyout without changing the armed tool. */}
              <DropdownMenuTrigger asChild>
                <button
                  type="button"
                  aria-label={`${g.label} menu`}
                  className="absolute -bottom-0.5 -right-0.5 h-3 w-3 rounded-sm text-muted-foreground/60 hover:text-foreground"
                >
                  <svg viewBox="0 0 10 10" className="h-3 w-3" aria-hidden="true">
                    <path d="M2 3.5 5 6.5 8 3.5" fill="none" stroke="currentColor" strokeWidth={1.6} />
                  </svg>
                </button>
              </DropdownMenuTrigger>
            </div>

            <DropdownMenuContent container={portalHost} side="right" align="start" className="w-56">
              {g.sections.map((sec, si) => (
                <div key={sec.head ?? `s${si}`}>
                  {sec.head && (
                    <div className="px-2 pb-1 pt-2 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                      {sec.head}
                    </div>
                  )}
                  {sec.tools.map((t) => (
                    <DropdownMenuItem
                      key={t.id ?? 'cursor'}
                      onSelect={() => {
                        if (t.id) lastRef.current[g.key] = t.id
                        onPick(t.id)
                      }}
                      className={cn('gap-2 text-sm', t.id === stats.tool && 'text-primary')}
                    >
                      <span className="h-4 w-4">{drawToolIcon(t.iconKey)}</span>
                      {t.label}
                    </DropdownMenuItem>
                  ))}
                </div>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
        )
      })}

      <div className="my-0.5 h-px w-5 bg-border" />

      <button
        type="button"
        title="Magnet: snap anchors to O/H/L/C"
        aria-label="Magnet"
        onClick={() => onMagnet(!stats.magnet)}
        className={cn(btn, stats.magnet && on)}
      >
        <span className="h-[18px] w-[18px]">{drawToolIcon('magnet')}</span>
      </button>
      <button
        type="button"
        title="Undo (Ctrl+Z)"
        aria-label="Undo drawing"
        disabled={!stats.canUndo}
        onClick={onUndo}
        className={btn}
      >
        <svg viewBox="0 0 24 24" className="h-[18px] w-[18px]" fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M4 10a7 7 0 1 1 2.5 5.3" />
          <path d="M3 5v5h5" />
        </svg>
      </button>
      <button
        type="button"
        title="Redo"
        aria-label="Redo drawing"
        disabled={!stats.canRedo}
        onClick={onRedo}
        className={btn}
      >
        <svg viewBox="0 0 24 24" className="h-[18px] w-[18px]" fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M20 10a7 7 0 1 0-2.5 5.3" />
          <path d="M21 5v5h-5" />
        </svg>
      </button>
      <button
        type="button"
        title={stats.hasSelection ? 'Delete selected drawing' : `Remove all drawings (${stats.count})`}
        aria-label="Delete drawings"
        disabled={stats.count === 0}
        onClick={() => onRemove(!stats.hasSelection)}
        className={btn}
      >
        <svg viewBox="0 0 24 24" className="h-[18px] w-[18px]" fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M3.5 6.5h17M9.5 6.5v-3h5v3M6 6.5l1 14h10l1-14" />
        </svg>
      </button>
    </div>
  )
}
