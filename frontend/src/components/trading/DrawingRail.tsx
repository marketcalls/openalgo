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
import { RAIL_BTN, RAIL_BTN_ON, RailTip } from './railStyles'

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
  /**
   * Arm the tool bound to a key event; returns true if one matched, so the rail
   * can swallow the key. The chord table ships with the draw tier, which the
   * terminal loads lazily — the rail must not import it and undo that.
   */
  onShortcut?(e: KeyboardEvent): boolean
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

export function DrawingRail({
  stats,
  onPick,
  onUndo,
  onRedo,
  onRemove,
  onMagnet,
  portalHost,
  onShortcut,
}: Props) {
  // Last tool chosen per group, so the bare button re-arms it instead of
  // reopening the flyout every time.
  const lastRef = useRef<Record<string, string>>({})
  const [open, setOpen] = useState<string | null>(null)
  const activeGroup = groupOf(stats.tool)

  if (stats.tool) lastRef.current[activeGroup ?? ''] = stats.tool

  // Esc returns to the cursor; Alt+<key> arms a tool. The chord table lives in
  // the draw tier, so `onShortcut` forwards the event and reports whether a
  // tool claimed it.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && stats.tool) {
        onPick(null)
        return
      }
      // Never steal a key from a field, or from a chord the browser owns.
      const t = e.target as HTMLElement | null
      if (t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName))) return
      if (onShortcut?.(e)) e.preventDefault()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [stats.tool, onPick, onShortcut])

  // Shared with RightRail so the two edges of the workspace cannot drift.
  const btn = RAIL_BTN
  const on = RAIL_BTN_ON

  return (
    // A flush column with a divider, not a floating card: the plot starts to
    // its right, so nothing the chart draws in that corner can sit under it.
    <div className="flex w-10 shrink-0 flex-col items-center gap-0.5 no-scrollbar overflow-y-auto border-r bg-background/40 py-1">
      {/* Cursor — disarms whatever is active */}
      <div className="group relative">
        <button
          type="button"
          aria-label="Cursor"
          onClick={() => onPick(null)}
          className={cn(btn, !stats.tool && on)}
        >
          <span className="h-[18px] w-[18px]">{drawToolIcon('cursor')}</span>
        </button>
        <RailTip text="Cursor" chord="Esc" />
      </div>

      <div className="my-0.5 h-px w-5 bg-border" />

      {DRAW_GROUPS.map((g) => {
        const last = lastRef.current[g.key]
        return (
          <DropdownMenu
            key={g.key}
            open={open === g.key}
            onOpenChange={(o) => setOpen(o ? g.key : null)}
          >
            <div className="group relative">
              <button
                type="button"
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
              {/*
                Caret opens the flyout without changing the armed tool. A filled
                corner wedge rather than a chevron in a box: at 8px a chevron's
                strokes blur, and the wedge is what reads as "there is more here"
                without competing with the glyph it sits under. It only appears on
                hover or while active, so eleven resting buttons stay quiet.
              */}
              <DropdownMenuTrigger asChild>
                <button
                  type="button"
                  aria-label={`${g.label} menu`}
                  className={cn(
                    'absolute bottom-0 right-0 h-2.5 w-2.5 opacity-0 transition-opacity group-hover:opacity-100 focus-visible:opacity-100',
                    (activeGroup === g.key || open === g.key) && 'opacity-100'
                  )}
                >
                  <svg viewBox="0 0 10 10" className="h-2.5 w-2.5" aria-hidden="true">
                    <path
                      d="M10 2 10 10 2 10 Z"
                      fill="currentColor"
                      className={cn(
                        'text-muted-foreground/70',
                        activeGroup === g.key && 'text-primary'
                      )}
                    />
                  </svg>
                </button>
              </DropdownMenuTrigger>
              {open !== g.key && <RailTip text={g.label} />}
            </div>

            <DropdownMenuContent
              container={portalHost}
              side="right"
              align="start"
              className="w-64 p-1"
            >
              {g.sections.map((sec, si) => (
                <div key={sec.head ?? `s${si}`}>
                  {sec.head && (
                    <div
                      className={cn(
                        'px-2 pb-1.5 text-[10px] font-semibold uppercase tracking-widest text-muted-foreground',
                        si === 0 ? 'pt-1.5' : 'mt-1.5 border-t pt-2.5'
                      )}
                    >
                      {sec.head}
                    </div>
                  )}
                  {sec.tools.map((t) => {
                    const chord = t.id ? stats.shortcuts[t.id] : undefined
                    return (
                      <DropdownMenuItem
                        key={t.id ?? 'cursor'}
                        onSelect={() => {
                          if (t.id) lastRef.current[g.key] = t.id
                          onPick(t.id)
                        }}
                        className={cn(
                          'h-8 gap-2.5 rounded px-2 text-[13px]',
                          t.id === stats.tool && 'text-primary'
                        )}
                      >
                        <span className="h-4 w-4 shrink-0 text-muted-foreground">
                          {drawToolIcon(t.iconKey)}
                        </span>
                        <span className="flex-1 truncate">{t.label}</span>
                        {/* Right-aligned and dimmed: discoverable, never competing
                            with the name it belongs to. */}
                        {chord && (
                          <span className="shrink-0 text-[11px] tabular-nums text-muted-foreground/70">
                            {chord.replace('+', ' + ')}
                          </span>
                        )}
                      </DropdownMenuItem>
                    )
                  })}
                </div>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
        )
      })}

      <div className="my-0.5 h-px w-5 bg-border" />

      <div className="group relative">
        <button
          type="button"
          aria-label="Magnet"
          onClick={() => onMagnet(!stats.magnet)}
          className={cn(btn, stats.magnet && on)}
        >
          <span className="h-[18px] w-[18px]">{drawToolIcon('magnet')}</span>
        </button>
        <RailTip text="Magnet: snap to O/H/L/C" />
      </div>
      <div className="group relative">
        <button
          type="button"
          aria-label="Undo drawing"
          disabled={!stats.canUndo}
          onClick={onUndo}
          className={btn}
        >
          <svg
            viewBox="0 0 24 24"
            className="h-[18px] w-[18px]"
            fill="none"
            stroke="currentColor"
            strokeWidth={1.6}
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <path d="M4 10a7 7 0 1 1 2.5 5.3" />
            <path d="M3 5v5h5" />
          </svg>
        </button>
        <RailTip text="Undo" chord="Ctrl + Z" />
      </div>
      <div className="group relative">
        <button
          type="button"
          aria-label="Redo drawing"
          disabled={!stats.canRedo}
          onClick={onRedo}
          className={btn}
        >
          <svg
            viewBox="0 0 24 24"
            className="h-[18px] w-[18px]"
            fill="none"
            stroke="currentColor"
            strokeWidth={1.6}
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <path d="M20 10a7 7 0 1 0-2.5 5.3" />
            <path d="M21 5v5h-5" />
          </svg>
        </button>
        <RailTip text="Redo" chord="Ctrl + Shift + Z" />
      </div>
      <div className="group relative">
        <button
          type="button"
          aria-label="Delete drawings"
          disabled={stats.count === 0}
          onClick={() => onRemove(!stats.hasSelection)}
          className={btn}
        >
          <svg
            viewBox="0 0 24 24"
            className="h-[18px] w-[18px]"
            fill="none"
            stroke="currentColor"
            strokeWidth={1.6}
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <path d="M3.5 6.5h17M9.5 6.5v-3h5v3M6 6.5l1 14h10l1-14" />
          </svg>
        </button>
        <RailTip text={stats.hasSelection ? 'Delete selected' : `Remove all (${stats.count})`} />
      </div>
    </div>
  )
}
