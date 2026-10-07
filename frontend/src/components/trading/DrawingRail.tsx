/**
 * Vertical drawing-tool rail, overlaid on the left edge of a chart pane.
 *
 * Purely additive: the pane's existing trading controls (symbol, timeframe,
 * chart type, product, qty, right-click order entry) are untouched. A group
 * button opens a flyout of its tools; a plain click re-arms the last tool used
 * in that group, and shows it, so the button reads as the tool it will pick.
 *
 * The chart is the priority on this page, so the rail never grows a column:
 * the eraser lives in the cursor's flyout, the magnet modes in the magnet's,
 * and the actions on the selection (hide, lock, delete, select all, remove
 * all) in the trash button's. Each of those is the same 32px slot it was.
 */
import { EyeOff, Lock, SquareDashedMousePointer, Trash2 } from 'lucide-react'
import type { MagnetMode } from 'openalgo-charts/draw'
import { type ReactNode, useEffect, useState } from 'react'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuShortcut,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { ERASER_TOOL } from '@/lib/trading/drawingActions'
import { chartMayTakeKey, MOD_KEY } from '@/lib/trading/drawingKeys'
import { DRAW_GROUPS, drawToolIcon } from '@/lib/trading/drawTools'
import type { DrawStats } from '@/lib/trading/terminal'
import { cn } from '@/lib/utils'
import { RAIL_BTN, RAIL_BTN_ON, RAIL_ICON_STROKE } from './railStyles'
import { Tip } from './Tip'

interface Props {
  stats: DrawStats
  /** The armed tool is held after each placement until Escape (a double-click). */
  latched?: boolean
  /** Arm a tool, the eraser, or the cursor (null). `latch` holds it until Escape. */
  onPick(toolId: string | null, latch?: boolean): void
  onUndo(): void
  onRedo(): void
  onDeleteSelected(): void
  onRemoveAll(): void
  onSelectAll(): void
  onHideSelected(): void
  onLockSelected(): void
  onMagnet(mode: MagnetMode): void
  onStay(on: boolean): void
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

/** Where the last tool picked in each group is remembered across visits. */
export const RAIL_LAST_KEY = 'oa-trading-rail-last'

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

/** The remembered last tool per group, keeping only ids that still belong to it. */
function readLast(): Record<string, string> {
  try {
    const saved: unknown = JSON.parse(localStorage.getItem(RAIL_LAST_KEY) ?? '{}')
    if (!saved || typeof saved !== 'object') return {}
    const out: Record<string, string> = {}
    for (const [group, id] of Object.entries(saved)) {
      if (typeof id === 'string' && groupOf(id) === group) out[group] = id
    }
    return out
  } catch {
    // Storage refused or a malformed entry: every group starts on its own glyph.
    return {}
  }
}

function toolLabel(toolId: string): string {
  for (const g of DRAW_GROUPS)
    for (const sec of g.sections) {
      const tool = sec.tools.find((t) => t.id === toolId)
      if (tool) return tool.label
    }
  return toolId
}

const MAGNET_LABEL: Record<MagnetMode, string> = {
  off: 'Magnet off',
  weak: 'Weak magnet',
  strong: 'Strong magnet',
}
const MAGNET_HINT: Record<MagnetMode, string> = {
  off: 'Anchors land where you click',
  weak: 'Snaps when a price is within a few pixels',
  strong: 'Every anchor snaps to the nearest O/H/L/C',
}

/**
 * The caret that opens a button's flyout without pressing the button. A filled
 * corner wedge rather than a chevron in a box: at 8px a chevron's strokes blur.
 * It shows on hover, focus or while the button is active, so a column of
 * resting buttons stays quiet.
 */
function Caret({ label, shown, accent }: { label: string; shown: boolean; accent: boolean }) {
  return (
    <DropdownMenuTrigger asChild>
      <button
        type="button"
        aria-label={label}
        className={cn(
          'absolute bottom-0 right-0 h-2.5 w-2.5 opacity-0 transition-opacity group-hover:opacity-100 focus-visible:opacity-100',
          shown && 'opacity-100'
        )}
      >
        <svg viewBox="0 0 10 10" className="h-2.5 w-2.5" aria-hidden="true">
          <path
            d="M10 2 10 10 2 10 Z"
            fill="currentColor"
            className={cn('text-muted-foreground/70', accent && 'text-primary')}
          />
        </svg>
      </button>
    </DropdownMenuTrigger>
  )
}

const ERASER_GLYPH = (
  <svg
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth={1.5}
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-hidden="true"
  >
    <path d="M3 15 12 6l7 7-6 6H8zM8 11l7 7M13 19h8" />
  </svg>
)

const iconBox = 'h-[18px] w-[18px]'
const rowIcon = 'h-4 w-4 shrink-0 text-muted-foreground'

export function DrawingRail({
  stats,
  latched = false,
  onPick,
  onUndo,
  onRedo,
  onDeleteSelected,
  onRemoveAll,
  onSelectAll,
  onHideSelected,
  onLockSelected,
  onMagnet,
  onStay,
  portalHost,
  onShortcut,
}: Props) {
  // Last tool chosen per group: the bare button re-arms it and shows its glyph.
  const [last, setLast] = useState<Record<string, string>>(readLast)
  const [open, setOpen] = useState<string | null>(null)
  // The mode the magnet button turns back on to: the last one that was on.
  const [magnetOn, setMagnetOn] = useState<MagnetMode>(
    stats.magnetMode === 'weak' ? 'weak' : 'strong'
  )
  const activeGroup = groupOf(stats.tool)
  const erasing = stats.tool === ERASER_TOOL

  // An armed tool becomes its group's last one, wherever it was armed from
  // (a flyout row, a keyboard chord), so the button shows what it will pick.
  useEffect(() => {
    if (!stats.tool || !activeGroup) return
    setLast((prev) => {
      if (prev[activeGroup] === stats.tool) return prev
      const next = { ...prev, [activeGroup]: stats.tool as string }
      try {
        localStorage.setItem(RAIL_LAST_KEY, JSON.stringify(next))
      } catch {
        // Storage refused: the choice holds for this visit.
      }
      return next
    })
  }, [stats.tool, activeGroup])

  useEffect(() => {
    if (stats.magnetMode !== 'off') setMagnetOn(stats.magnetMode)
  }, [stats.magnetMode])

  // Esc returns to the cursor; Alt+<key> arms a tool; Ctrl+C, X and V move
  // drawings. The chord tables live in the draw tier, so `onShortcut` forwards
  // the event and reports whether the chart claimed it.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && stats.tool) {
        onPick(null)
        return
      }
      // Never steal a key from a field, a dialog or an open menu.
      if (!chartMayTakeKey(e)) return
      if (onShortcut?.(e)) e.preventDefault()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [stats.tool, onPick, onShortcut])

  // Shared with RightRail so the two edges of the workspace cannot drift.
  const btn = RAIL_BTN
  const on = RAIL_BTN_ON
  const menu = (key: string) => ({
    open: open === key,
    onOpenChange: (o: boolean) => setOpen(o ? key : null),
  })
  const menuContent = (children: ReactNode, width = 'w-64') => (
    <DropdownMenuContent
      container={portalHost}
      side="right"
      align="start"
      className={cn(width, 'p-1')}
    >
      {children}
    </DropdownMenuContent>
  )
  const row = 'h-8 gap-2.5 rounded px-2 text-[13px]'

  return (
    // A flush column with a divider, not a floating card: the plot starts to
    // its right, so nothing the chart draws in that corner can sit under it.
    <div className="flex w-10 shrink-0 flex-col items-center gap-0.5 no-scrollbar overflow-y-auto border-r bg-background/40 py-1">
      {/* Cursor, with the eraser in its flyout */}
      <DropdownMenu {...menu('cursor')}>
        <Tip
          side="right"
          disabled={open === 'cursor'}
          tip={{
            title: erasing ? 'Eraser' : 'Cursor',
            chord: 'Esc',
            sub: erasing
              ? 'Click a drawing to delete it. Esc returns to the cursor.'
              : 'Select and move drawings. Right-click for the eraser.',
          }}
        >
          <div className="group relative">
            <button
              type="button"
              aria-label={erasing ? 'Eraser' : 'Cursor'}
              aria-pressed={erasing || !stats.tool}
              onClick={() => onPick(null)}
              onContextMenu={(e) => {
                e.preventDefault()
                setOpen('cursor')
              }}
              className={cn(btn, (erasing || !stats.tool) && on)}
            >
              <span className={iconBox}>{erasing ? ERASER_GLYPH : drawToolIcon('cursor')}</span>
            </button>
            <Caret label="Cursor menu" shown={erasing || open === 'cursor'} accent={erasing} />
          </div>
        </Tip>
        {menuContent(
          <>
            <DropdownMenuItem
              onSelect={() => onPick(null)}
              className={cn(row, !stats.tool && 'text-primary')}
            >
              <span className={rowIcon}>{drawToolIcon('cursor')}</span>
              <span className="flex-1">Cursor</span>
              <DropdownMenuShortcut>Esc</DropdownMenuShortcut>
            </DropdownMenuItem>
            <DropdownMenuItem
              onSelect={() => onPick(ERASER_TOOL)}
              className={cn(row, erasing && 'text-primary')}
            >
              <span className={rowIcon}>{ERASER_GLYPH}</span>
              <span className="flex-1">Eraser</span>
            </DropdownMenuItem>
            <p className="px-2 pb-1 pt-1.5 text-[11px] leading-snug text-muted-foreground">
              Click a drawing, or drag across several, to delete them. {MOD_KEY} + Z brings them
              back.
            </p>
          </>,
          'w-60'
        )}
      </DropdownMenu>

      <div className="my-0.5 h-px w-5 bg-border" />

      {DRAW_GROUPS.map((g) => {
        const lastTool = last[g.key]
        const active = activeGroup === g.key
        const held = active && latched
        return (
          <DropdownMenu key={g.key} {...menu(g.key)}>
            <Tip
              side="right"
              disabled={open === g.key}
              tip={{
                title: lastTool ? toolLabel(lastTool) : g.label,
                chord: lastTool ? stats.shortcuts[lastTool]?.replace('+', ' + ') : undefined,
                sub: lastTool
                  ? held
                    ? 'Held until Esc'
                    : 'Double-click to keep it for several drawings. Right-click for the list.'
                  : 'Choose a tool from the list',
              }}
            >
              <div className="group relative">
                <button
                  type="button"
                  aria-label={g.label}
                  aria-pressed={active}
                  onClick={() => {
                    // Re-arm the group's last tool; open the list if there is none.
                    if (lastTool) onPick(lastTool)
                    else setOpen(g.key)
                  }}
                  // A double-click holds the tool after each drawing until Escape.
                  onDoubleClick={() => {
                    if (lastTool) onPick(lastTool, true)
                  }}
                  onContextMenu={(e) => {
                    e.preventDefault()
                    setOpen(g.key)
                  }}
                  className={cn(btn, active && on)}
                >
                  <span className={iconBox}>{drawToolIcon(lastTool ?? g.iconKey)}</span>
                </button>
                {held && (
                  <span
                    aria-hidden="true"
                    className="pointer-events-none absolute left-1 top-1 h-1.5 w-1.5 rounded-full bg-primary"
                  />
                )}
                <Caret label={`${g.label} menu`} shown={active || open === g.key} accent={active} />
              </div>
            </Tip>

            {menuContent(
              g.sections.map((sec, si) => (
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
                        onSelect={() => onPick(t.id)}
                        className={cn(row, t.id === stats.tool && 'text-primary')}
                      >
                        <span className={rowIcon}>{drawToolIcon(t.iconKey)}</span>
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
              ))
            )}
          </DropdownMenu>
        )
      })}

      <div className="my-0.5 h-px w-5 bg-border" />

      {/* Magnet: the button turns it on and off, the flyout picks how hard */}
      <DropdownMenu {...menu('magnet')}>
        <Tip
          side="right"
          disabled={open === 'magnet'}
          tip={{
            title: MAGNET_LABEL[stats.magnetMode],
            chord: `Hold ${MOD_KEY}`,
            sub: `${MAGNET_HINT[stats.magnetMode]}. Hold ${MOD_KEY} to snap with it off.`,
          }}
        >
          <div className="group relative">
            <button
              type="button"
              aria-label="Magnet"
              aria-pressed={stats.magnetMode !== 'off'}
              onClick={() => onMagnet(stats.magnetMode === 'off' ? magnetOn : 'off')}
              onContextMenu={(e) => {
                e.preventDefault()
                setOpen('magnet')
              }}
              className={cn(btn, stats.magnetMode !== 'off' && on)}
            >
              <span className={iconBox}>{drawToolIcon('magnet')}</span>
            </button>
            {stats.magnetMode !== 'off' && (
              <span
                aria-hidden="true"
                className="pointer-events-none absolute right-0.5 top-0 text-[9px] font-bold leading-none text-primary"
              >
                {stats.magnetMode === 'weak' ? 'W' : 'S'}
              </span>
            )}
            <Caret
              label="Magnet menu"
              shown={open === 'magnet'}
              accent={stats.magnetMode !== 'off'}
            />
          </div>
        </Tip>
        {menuContent(
          <>
            {(['off', 'weak', 'strong'] as const).map((mode) => (
              <DropdownMenuItem
                key={mode}
                onSelect={() => onMagnet(mode)}
                className={cn(
                  'flex-col items-start gap-0 rounded px-2 py-1.5',
                  stats.magnetMode === mode && 'text-primary'
                )}
              >
                <span className="text-[13px]">{MAGNET_LABEL[mode]}</span>
                <span className="text-[11px] text-muted-foreground">{MAGNET_HINT[mode]}</span>
              </DropdownMenuItem>
            ))}
            <p className="px-2 pb-1 pt-1.5 text-[11px] leading-snug text-muted-foreground">
              Hold {MOD_KEY} while placing or dragging an anchor to snap with the magnet off.
            </p>
          </>
        )}
      </DropdownMenu>

      {/*
        The tier disarms a tool once it has drawn, so three trend lines are
        three trips to the rail. This latches the armed tool instead, and the
        cursor button is still one press away.
      */}
      <Tip
        side="right"
        tip={{
          title: 'Keep tool selected',
          sub: 'The tool stays picked after each drawing, until Esc',
        }}
      >
        <div className="group relative">
          <button
            type="button"
            aria-label="Keep tool selected"
            aria-pressed={stats.stay}
            onClick={() => onStay(!stats.stay)}
            className={cn(btn, stats.stay && on)}
          >
            <span className={iconBox}>{drawToolIcon('lock')}</span>
          </button>
        </div>
      </Tip>
      <Tip side="right" tip={{ title: 'Undo chart change', chord: `${MOD_KEY} + Z`, sub: 'Orders are never undone' }}>
        <div className="group relative">
          <button
            type="button"
            aria-label="Undo chart change"
            disabled={!stats.canUndo}
            onClick={onUndo}
            className={btn}
          >
            <svg
              viewBox="0 0 24 24"
              className={iconBox}
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
        </div>
      </Tip>
      <Tip side="right" tip={{ title: 'Redo chart change', chord: `${MOD_KEY} + Y` }}>
        <div className="group relative">
          <button
            type="button"
            aria-label="Redo chart change"
            disabled={!stats.canRedo}
            onClick={onRedo}
            className={btn}
          >
            <svg
              viewBox="0 0 24 24"
              className={iconBox}
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
        </div>
      </Tip>

      {/* Trash: deletes the selection, and holds every other drawing action */}
      <DropdownMenu {...menu('trash')}>
        <Tip
          side="right"
          disabled={open === 'trash'}
          tip={
            stats.hasSelection
              ? {
                  title: 'Delete selected',
                  chord: 'Del',
                  sub: 'Right-click to hide or lock them instead',
                }
              : {
                  title: 'Drawing actions',
                  sub: 'Select all drawings, or remove every drawing on this chart',
                }
          }
        >
          <div className="group relative">
            <button
              type="button"
              aria-label={stats.hasSelection ? 'Delete selected drawings' : 'Drawing actions'}
              disabled={stats.count === 0}
              onClick={() => (stats.hasSelection ? onDeleteSelected() : setOpen('trash'))}
              onContextMenu={(e) => {
                e.preventDefault()
                setOpen('trash')
              }}
              className={btn}
            >
              <svg
                viewBox="0 0 24 24"
                className={iconBox}
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
            {stats.count > 0 && (
              <Caret label="Drawing actions menu" shown={open === 'trash'} accent={false} />
            )}
          </div>
        </Tip>
        {menuContent(
          <>
            {stats.hasSelection && (
              <>
                <DropdownMenuItem onSelect={onHideSelected} className={row}>
                  <EyeOff className={rowIcon} strokeWidth={RAIL_ICON_STROKE} />
                  <span className="flex-1">Hide selected</span>
                </DropdownMenuItem>
                <DropdownMenuItem onSelect={onLockSelected} className={row}>
                  <Lock className={rowIcon} strokeWidth={RAIL_ICON_STROKE} />
                  <span className="flex-1">Lock selected</span>
                </DropdownMenuItem>
                <DropdownMenuItem onSelect={onDeleteSelected} className={row}>
                  <Trash2 className={rowIcon} strokeWidth={RAIL_ICON_STROKE} />
                  <span className="flex-1">Delete selected</span>
                  <DropdownMenuShortcut>Del</DropdownMenuShortcut>
                </DropdownMenuItem>
                <DropdownMenuSeparator />
              </>
            )}
            <DropdownMenuItem
              disabled={stats.selectable === 0}
              onSelect={onSelectAll}
              className={row}
            >
              <SquareDashedMousePointer className={rowIcon} strokeWidth={RAIL_ICON_STROKE} />
              <span className="flex-1">Select all drawings ({stats.selectable})</span>
            </DropdownMenuItem>
            <DropdownMenuItem
              disabled={stats.removable === 0}
              onSelect={onRemoveAll}
              className={cn(row, 'text-destructive focus:text-destructive')}
            >
              <Trash2 className="h-4 w-4 shrink-0" strokeWidth={RAIL_ICON_STROKE} />
              <span className="flex-1">Remove all drawings ({stats.removable})</span>
            </DropdownMenuItem>
          </>
        )}
      </DropdownMenu>
    </div>
  )
}
