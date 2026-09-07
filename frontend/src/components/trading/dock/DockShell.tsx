/**
 * The band under the chart grid: a tab strip that is the whole dock while it
 * is collapsed, and a resizable table under it while it is open.
 *
 * The resize is panelShell's gesture turned on its side: the handle is a
 * hairline on the dock's top edge, the width becomes a height, dragging up
 * makes it taller, and the value is written once, on pointerup, never per
 * frame. The tab strip is a real tablist, so the arrow keys move between
 * books and Escape can find the dock by where focus is.
 */

import { ChevronDown } from 'lucide-react'
import { type ReactNode, useCallback, useEffect, useRef, useState } from 'react'
import { cn } from '@/lib/utils'
import { RAIL_BTN, RailTip } from '../railStyles'
import {
  clampDockHeight,
  DOCK_MIN_HEIGHT,
  DOCK_STRIP_HEIGHT,
  DOCK_TABS,
  type DockTab,
  dockMaxHeight,
  readDockHeight,
  writeDockHeight,
} from './dockState'

/** The element Escape looks inside to decide whether the dock has focus. */
export const DOCK_ID = 'oa-trading-dock'

interface Props {
  /** The open tab, or null while the dock is collapsed to its strip. */
  tab: DockTab | null
  onTabChange(tab: DockTab | null): void
  /** A live figure beside each label. Absent means no badge, not zero. */
  counts: Partial<Record<DockTab, number>>
  /** Rendered in the open header, after the tabs: the P&L strip. */
  header?: ReactNode
  children?: ReactNode
}

function viewportHeight(): number {
  return typeof window === 'undefined' ? 800 : window.innerHeight
}

export function DockShell({ tab, onTabChange, counts, header, children }: Props) {
  const [height, setHeight] = useState(() => readDockHeight(viewportHeight()))
  const [dragging, setDragging] = useState(false)
  const heightRef = useRef(height)
  heightRef.current = height
  const tabRefs = useRef<Record<string, HTMLButtonElement | null>>({})

  // Detaches whatever the current drag attached to the window, for a dock
  // that is closed mid-drag and never sees its pointerup.
  const releaseRef = useRef<(() => void) | null>(null)
  useEffect(() => () => releaseRef.current?.(), [])

  /**
   * Where focus goes when the dock collapses. Escape with focus in a table
   * is the common case, and the table unmounts under it; without this the
   * next Tab restarts at the top of the document. The strip's tab for the
   * book that was open is still there, so focus lands on it, the way the
   * right rail reclaims focus for a closed panel.
   */
  const previous = useRef<DockTab | null>(tab)
  useEffect(() => {
    const closed = previous.current
    previous.current = tab
    if (tab !== null || closed === null) return
    if (document.activeElement === document.body) tabRefs.current[closed]?.focus()
  }, [tab])

  const startResize = useCallback((event: React.PointerEvent<HTMLDivElement>) => {
    if (event.button !== 0) return
    event.preventDefault()
    const startY = event.clientY
    const startHeight = heightRef.current
    const max = dockMaxHeight(viewportHeight())
    setDragging(true)
    const onMove = (e: PointerEvent) => {
      // The dock is at the bottom, so dragging up makes it taller.
      setHeight(Math.min(max, Math.max(DOCK_MIN_HEIGHT, startHeight + (startY - e.clientY))))
    }
    const onUp = () => {
      setDragging(false)
      document.body.classList.remove('select-none', 'cursor-row-resize')
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
      window.removeEventListener('pointercancel', onUp)
      writeDockHeight(heightRef.current)
      releaseRef.current = null
    }
    document.body.classList.add('select-none', 'cursor-row-resize')
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
    window.addEventListener('pointercancel', onUp)
    releaseRef.current = onUp
  }, [])

  /**
   * Arrow keys walk the tabs and select as they go, the tabs pattern. Home
   * and End jump. Only the selected tab (or the first, while collapsed) is
   * in the tab order, so the strip costs one stop, not four.
   */
  const onTabKey = (e: React.KeyboardEvent<HTMLButtonElement>, index: number) => {
    let next: number | null = null
    if (e.key === 'ArrowRight') next = (index + 1) % DOCK_TABS.length
    else if (e.key === 'ArrowLeft') next = (index - 1 + DOCK_TABS.length) % DOCK_TABS.length
    else if (e.key === 'Home') next = 0
    else if (e.key === 'End') next = DOCK_TABS.length - 1
    if (next === null) return
    e.preventDefault()
    const id = DOCK_TABS[next].id
    tabRefs.current[id]?.focus()
    onTabChange(id)
  }

  const open = tab !== null
  const focusIndex = open ? DOCK_TABS.findIndex((t) => t.id === tab) : 0

  // 24px buttons in a strip whose content box is 27px (28 less the top
  // border), so a selected tab's fill never overpaints the hairline.
  const tabs = (
    <div role="tablist" aria-label="Trading books" className="flex items-center gap-0.5">
      {DOCK_TABS.map(({ id, label }, index) => {
        const selected = tab === id
        const count = counts[id]
        return (
          <button
            key={id}
            type="button"
            role="tab"
            id={`${DOCK_ID}-tab-${id}`}
            ref={(node) => {
              tabRefs.current[id] = node
            }}
            aria-selected={selected}
            aria-controls={selected ? `${DOCK_ID}-panel` : undefined}
            tabIndex={index === focusIndex ? 0 : -1}
            // Clicking the open tab collapses the dock: the strip is the
            // only control the dock has, so the tab that opened a book has
            // to be able to put it away.
            onClick={() => onTabChange(selected ? null : id)}
            onKeyDown={(e) => onTabKey(e, index)}
            className={cn(
              'flex h-6 items-center gap-1.5 rounded-sm px-2.5 text-[12px] font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-inset focus-visible:ring-ring',
              selected && 'bg-accent text-foreground shadow-[inset_0_-2px_0_0_var(--color-primary)]'
            )}
          >
            {label}
            {count !== undefined && (
              <span
                className={cn(
                  'min-w-[18px] rounded-full px-1.5 py-px text-center text-[10px] tabular-nums',
                  count > 0 ? 'bg-primary/15 text-primary' : 'bg-muted text-muted-foreground'
                )}
              >
                {count}
              </span>
            )}
          </button>
        )
      })}
    </div>
  )

  // One tree for both states, with the tablist in the same slot of the same
  // row whether the dock is a strip or a panel. Two trees remounted every
  // tab button on the way from collapsed to open, and the button that had
  // just been pressed or arrowed to lost focus to body with it.
  return (
    <section
      id={DOCK_ID}
      aria-label="Trading dock"
      className="relative flex shrink-0 flex-col overflow-hidden border-t bg-background"
      style={open ? { height, maxHeight: '60vh' } : { height: DOCK_STRIP_HEIGHT }}
    >
      {open && (
        <>
          {/* biome-ignore lint/a11y/useSemanticElements: role=separator with tabindex
              and aria-valuenow is the ARIA window-splitter pattern, as in panelShell. */}
          <div
            role="separator"
            aria-orientation="horizontal"
            aria-label="Resize trading dock"
            aria-valuenow={height}
            aria-valuemin={DOCK_MIN_HEIGHT}
            aria-valuemax={dockMaxHeight(viewportHeight())}
            tabIndex={0}
            onPointerDown={startResize}
            onKeyDown={(e) => {
              const step = e.key === 'ArrowUp' ? 16 : e.key === 'ArrowDown' ? -16 : 0
              if (!step) return
              setHeight((h) => clampDockHeight(h + step, viewportHeight()))
              e.preventDefault()
            }}
            // Held-arrow auto-repeat fires about thirty times a second, so the
            // write waits for the key to come up, as the drag waits for pointerup.
            onKeyUp={() => writeDockHeight(heightRef.current)}
            onBlur={() => writeDockHeight(heightRef.current)}
            className={cn(
              'absolute inset-x-0 top-0 z-20 h-1 cursor-row-resize transition-colors hover:bg-primary/40 focus-visible:bg-primary/60 focus-visible:outline-none',
              dragging && 'bg-primary/60'
            )}
          />
        </>
      )}
      <div
        className={cn(
          'flex shrink-0 items-center gap-2 px-1',
          open ? 'h-9 border-b' : 'min-h-0 flex-1'
        )}
      >
        {tabs}
        {open && (
          <>
            <div className="flex min-w-0 flex-1 items-center justify-end gap-2">{header}</div>
            <div className="group relative">
              <button
                type="button"
                onClick={() => onTabChange(null)}
                className={cn(RAIL_BTN, 'h-7 w-7')}
                aria-label="Collapse trading dock"
              >
                <ChevronDown className="h-4 w-4" />
              </button>
              <RailTip text="Collapse" chord="Esc" side="left" />
            </div>
          </>
        )}
      </div>
      {open && (
        <div
          role="tabpanel"
          id={`${DOCK_ID}-panel`}
          aria-labelledby={`${DOCK_ID}-tab-${tab}`}
          className="min-h-0 flex-1 overflow-auto"
        >
          {children}
        </div>
      )}
    </section>
  )
}
