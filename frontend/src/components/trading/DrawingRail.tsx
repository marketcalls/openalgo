/**
 * Vertical drawing-tool rail, on the left edge of the chart grid.
 *
 * Purely additive: the pane's existing trading controls (symbol, timeframe,
 * chart type, product, qty, right-click order entry) are untouched. A group
 * button re-arms the last tool used in that group, and shows it, so the button
 * reads as the tool it will pick; the caret in its corner opens the group's
 * list.
 *
 * The chart is the priority on this page, so the rail never grows a column:
 * the eraser lives in the cursor's flyout, the magnet modes in the magnet's,
 * and the actions on the selection (hide, lock, delete, select all, remove
 * all) in the trash button's. The one addition is the fold at the foot, which
 * gives the rail's width back to the chart.
 *
 * Presentation follows the engine's reference host: tool glyphs at the 20px
 * they are drawn for, chrome glyphs at 16px, 32 by 30 buttons, a soft accent
 * fill for the selected one, and the controls held at the bottom with the tools
 * fading out under them. The stylesheet is `.oa-rail` in index.css.
 */
import type { MagnetMode } from 'openalgo-charts/draw'
import { type ReactNode, useEffect, useState } from 'react'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { ERASER_TOOL } from '@/lib/trading/drawingActions'
import { chartMayTakeKey, MOD_KEY } from '@/lib/trading/drawingKeys'
import { DRAW_GROUPS, drawToolIcon } from '@/lib/trading/drawTools'
import { ChromeIcon } from '@/lib/trading/glyphs'
import type { DrawStats } from '@/lib/trading/terminal'
import { cn } from '@/lib/utils'
import { RAIL_BTN } from './railStyles'
import { Tip } from './Tip'

interface Props {
  stats: DrawStats
  /** The armed tool is held after each placement until Escape (a double-click). */
  latched?: boolean
  /**
   * Folded: the rail is not drawn and the chart takes its width. It stays
   * mounted, so the tool, the drawings and the keyboard chords carry on.
   */
  folded?: boolean
  /** Fold the rail away. Without it the rail offers no fold. */
  onFold?(): void
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
   * invisible while the pane is in the Fullscreen API's top layer, so in full
   * screen no tool could be picked at all.
   */
  portalHost?: HTMLElement | null
  /**
   * Arm the tool bound to a key event; returns true if one matched, so the rail
   * can swallow the key. The chord table ships with the draw tier, which the
   * terminal loads lazily; the rail must not import it and undo that.
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
 * The caret that opens a button's list without pressing the button: a small
 * chevron laid over the button's bottom right corner. It shows on hover, on
 * focus and while its list is open, so a column of resting buttons stays
 * quiet. A button of its own, beside the tool rather than inside it, because
 * a button cannot hold another.
 */
function Caret({ label }: { label: string }) {
  return (
    <DropdownMenuTrigger asChild>
      <button type="button" aria-label={label} className="oa-rail__chev">
        <ChromeIcon id="chevron-right" size={9} />
      </button>
    </DropdownMenuTrigger>
  )
}

/** A chrome glyph in a rail button, at the 16px the chrome set is drawn for. */
const chrome = (id: string) => <ChromeIcon id={id} />

/** A list row's glyph. The size class keeps the menu's own 16px rule off it. */
const rowTool = (id: string) => drawToolIcon(id, 20, 'size-5 text-current')
const rowChrome = (id: string) => <ChromeIcon id={id} className="size-4 text-current" />

/** The flyout's rows, after the reference host's: glyph, name, chord. */
const ROW =
  'min-h-8 gap-2 rounded-[7px] py-1 pl-2 pr-1.5 text-[13px] text-foreground focus:bg-[var(--oa-rail-elev-2)] focus:text-foreground'
const ROW_ON =
  'bg-[var(--oa-rail-on-bg)] text-[var(--oa-rail-acc)] focus:bg-[var(--oa-rail-on-bg)] focus:text-[var(--oa-rail-acc)]'
const HEAD =
  'px-2.5 pb-1 pt-2 text-[10px] font-medium uppercase tracking-[0.07em] text-muted-foreground/80'
const NOTE = 'px-2 pb-1 pt-1.5 text-[11px] leading-snug text-muted-foreground'
const CHORD =
  'min-w-10 shrink-0 text-right font-mono text-[11px] tabular-nums text-muted-foreground/80'

export function DrawingRail({
  stats,
  latched = false,
  folded = false,
  onFold,
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

  // A folded rail has no flyout to show.
  useEffect(() => {
    if (folded) setOpen(null)
  }, [folded])

  // Esc returns to the cursor; Alt+<key> arms a tool; Ctrl+C, X and V move
  // drawings. The chord tables live in the draw tier, so `onShortcut` forwards
  // the event and reports whether the chart claimed it. This listens while the
  // rail is folded too: folding hides the tools, it does not switch them off.
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

  const btn = RAIL_BTN
  const menu = (key: string) => ({
    open: open === key,
    onOpenChange: (o: boolean) => setOpen(o ? key : null),
  })
  const menuContent = (children: ReactNode, width = 'min-w-[244px] max-w-[320px]') => (
    <DropdownMenuContent
      container={portalHost}
      side="right"
      align="start"
      sideOffset={6}
      className={cn(width, 'rounded-[10px] p-1.5 shadow-[0_14px_40px_rgba(0,0,0,0.4)]')}
    >
      {children}
    </DropdownMenuContent>
  )

  return (
    // A flush column with a divider, not a floating card: the plot starts to
    // its right, so nothing the chart draws in that corner can sit under it.
    <div className={cn('oa-rail border-r', folded && 'hidden')} data-drawing-rail>
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
          <div className="oa-rail__slot">
            <button
              type="button"
              aria-label={erasing ? 'Eraser' : 'Cursor'}
              aria-pressed={erasing || !stats.tool}
              onClick={() => onPick(null)}
              onContextMenu={(e) => {
                e.preventDefault()
                setOpen('cursor')
              }}
              className={btn}
            >
              <span className="oa-rail__glyph">
                {erasing ? chrome('eraser') : drawToolIcon('cursor')}
              </span>
            </button>
            <Caret label="Cursor menu" />
          </div>
        </Tip>
        {menuContent(
          <>
            <DropdownMenuItem
              onSelect={() => onPick(null)}
              className={cn(ROW, !stats.tool && ROW_ON)}
            >
              {rowTool('cursor')}
              <span className="flex-1">Cursor</span>
              <span className={CHORD}>Esc</span>
            </DropdownMenuItem>
            <DropdownMenuItem
              onSelect={() => onPick(ERASER_TOOL)}
              className={cn(ROW, erasing && ROW_ON)}
            >
              <span className="grid size-5 shrink-0 place-items-center">{rowChrome('eraser')}</span>
              <span className="flex-1">Eraser</span>
            </DropdownMenuItem>
            <p className={NOTE}>
              Click a drawing, or drag across several, to delete them. {MOD_KEY} + Z brings them
              back.
            </p>
          </>,
          'w-60'
        )}
      </DropdownMenu>

      <div className="oa-rail__sep" aria-hidden="true" />

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
                    : 'Double-click to keep it for several drawings. The corner caret lists the rest.'
                  : 'Choose a tool from the list',
              }}
            >
              <div className="oa-rail__slot">
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
                  className={cn(btn, held && 'is-held')}
                >
                  <span className="oa-rail__glyph">{drawToolIcon(lastTool ?? g.iconKey)}</span>
                </button>
                <Caret label={`${g.label} menu`} />
              </div>
            </Tip>

            {menuContent(
              g.sections.map((sec, si) => (
                <div key={sec.head ?? `s${si}`}>
                  {sec.head && <div className={cn(HEAD, si > 0 && 'mt-1')}>{sec.head}</div>}
                  {sec.tools.map((t) => {
                    const chord = t.id ? stats.shortcuts[t.id] : undefined
                    return (
                      <DropdownMenuItem
                        key={t.id ?? 'cursor'}
                        onSelect={() => onPick(t.id)}
                        className={cn(ROW, t.id === stats.tool && ROW_ON)}
                      >
                        {rowTool(t.iconKey)}
                        <span className="flex-1 truncate">{t.label}</span>
                        {/* Right-aligned and dimmed: discoverable, never competing
                            with the name it belongs to. */}
                        {chord && <span className={CHORD}>{chord.replace('+', ' + ')}</span>}
                      </DropdownMenuItem>
                    )
                  })}
                </div>
              ))
            )}
          </DropdownMenu>
        )
      })}

      {/* The controls, held at the foot while the tools above scroll under them. */}
      <div className="oa-rail__ctl">
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
            <div className="oa-rail__slot">
              <button
                type="button"
                aria-label="Magnet"
                aria-pressed={stats.magnetMode !== 'off'}
                // The dot in the corner: solid for strong, a ring for weak.
                data-mode={stats.magnetMode === 'off' ? undefined : stats.magnetMode}
                onClick={() => onMagnet(stats.magnetMode === 'off' ? magnetOn : 'off')}
                onContextMenu={(e) => {
                  e.preventDefault()
                  setOpen('magnet')
                }}
                className={btn}
              >
                {chrome('magnet')}
              </button>
              <Caret label="Magnet menu" />
            </div>
          </Tip>
          {menuContent(
            <>
              {(['off', 'weak', 'strong'] as const).map((mode) => (
                <DropdownMenuItem
                  key={mode}
                  onSelect={() => onMagnet(mode)}
                  className={cn(
                    ROW,
                    'flex-col items-start gap-0 py-1.5',
                    stats.magnetMode === mode && ROW_ON
                  )}
                >
                  <span className="text-[13px]">{MAGNET_LABEL[mode]}</span>
                  <span className="text-[11px] text-muted-foreground">{MAGNET_HINT[mode]}</span>
                </DropdownMenuItem>
              ))}
              <p className={NOTE}>
                Hold {MOD_KEY} while placing or dragging an anchor to snap with the magnet off.
              </p>
            </>
          )}
        </DropdownMenu>

        {/*
          The tier disarms a tool once it has drawn, so three trend lines are
          three trips to the rail. This latches the armed tool instead, and the
          cursor button is still one press away. A link, as the reference host
          draws it: the padlock means locking a drawing, which is another thing.
        */}
        <Tip
          side="right"
          tip={{
            title: 'Keep tool selected',
            sub: 'The tool stays picked after each drawing, until Esc',
          }}
        >
          <div className="oa-rail__slot">
            <button
              type="button"
              aria-label="Keep tool selected"
              aria-pressed={stats.stay}
              onClick={() => onStay(!stats.stay)}
              className={btn}
            >
              {chrome('link')}
            </button>
          </div>
        </Tip>

        <div className="oa-rail__sep" aria-hidden="true" />

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
            <div className="oa-rail__slot">
              <button
                type="button"
                aria-label={stats.hasSelection ? 'Delete selected drawings' : 'Drawing actions'}
                disabled={stats.count === 0}
                onClick={() => (stats.hasSelection ? onDeleteSelected() : setOpen('trash'))}
                onContextMenu={(e) => {
                  e.preventDefault()
                  setOpen('trash')
                }}
                className={cn(btn, 'oa-rail__btn--danger')}
              >
                {chrome('trash')}
              </button>
              {stats.count > 0 && <Caret label="Drawing actions menu" />}
            </div>
          </Tip>
          {menuContent(
            <>
              {stats.hasSelection && (
                <>
                  <DropdownMenuItem onSelect={onHideSelected} className={ROW}>
                    {rowChrome('eye-off')}
                    <span className="flex-1">Hide selected</span>
                  </DropdownMenuItem>
                  <DropdownMenuItem onSelect={onLockSelected} className={ROW}>
                    {rowChrome('lock')}
                    <span className="flex-1">Lock selected</span>
                  </DropdownMenuItem>
                  <DropdownMenuItem onSelect={onDeleteSelected} className={ROW}>
                    {rowChrome('trash')}
                    <span className="flex-1">Delete selected</span>
                    <span className={CHORD}>Del</span>
                  </DropdownMenuItem>
                  <DropdownMenuSeparator />
                </>
              )}
              <DropdownMenuItem
                disabled={stats.selectable === 0}
                onSelect={onSelectAll}
                className={ROW}
              >
                {rowChrome('cursor')}
                <span className="flex-1">Select all drawings ({stats.selectable})</span>
              </DropdownMenuItem>
              <DropdownMenuItem
                disabled={stats.removable === 0}
                onSelect={onRemoveAll}
                className={cn(ROW, 'text-destructive focus:text-destructive')}
              >
                {rowChrome('trash')}
                <span className="flex-1">Remove all drawings ({stats.removable})</span>
              </DropdownMenuItem>
            </>,
            'w-64'
          )}
        </DropdownMenu>

        <div className="oa-rail__sep" aria-hidden="true" />

        <Tip
          side="right"
          tip={{
            title: 'Undo chart change',
            chord: `${MOD_KEY} + Z`,
            sub: 'Orders are never undone',
          }}
        >
          <div className="oa-rail__slot">
            <button
              type="button"
              aria-label="Undo chart change"
              disabled={!stats.canUndo}
              onClick={onUndo}
              className={btn}
            >
              {chrome('undo')}
            </button>
          </div>
        </Tip>
        <Tip side="right" tip={{ title: 'Redo chart change', chord: `${MOD_KEY} + Y` }}>
          <div className="oa-rail__slot">
            <button
              type="button"
              aria-label="Redo chart change"
              disabled={!stats.canRedo}
              onClick={onRedo}
              className={btn}
            >
              {chrome('redo')}
            </button>
          </div>
        </Tip>

        {onFold && (
          <>
            <div className="oa-rail__sep" aria-hidden="true" />
            <Tip
              side="right"
              tip={{
                title: 'Hide drawing tools',
                sub: 'The chart takes the width. The tab at its lower left brings the tools back.',
              }}
            >
              <div className="oa-rail__slot">
                <button
                  type="button"
                  aria-label="Hide drawing tools"
                  onClick={onFold}
                  className={btn}
                >
                  {chrome('chevrons-left')}
                </button>
              </div>
            </Tip>
          </>
        )}
      </div>
    </div>
  )
}

/**
 * The tab a folded rail leaves at the chart's lower left, just above the time
 * axis, that brings the rail back. It stops the press, because the chart under
 * it captures the pointer and would otherwise take the click for itself.
 */
export function DrawingRailTab({ onUnfold, bottom }: { onUnfold(): void; bottom: number }) {
  return (
    <Tip side="right" tip={{ title: 'Show drawing tools' }}>
      <button
        type="button"
        aria-label="Show drawing tools"
        className="oa-rail-tab"
        style={{ bottom }}
        onPointerDown={(e) => e.stopPropagation()}
        onClick={onUnfold}
      >
        <ChromeIcon id="chevrons-right" size={12} />
      </button>
    </Tip>
  )
}
