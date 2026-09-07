/**
 * The frame every right-hand panel sits in.
 *
 * Two jobs, both of which have to be identical across panels or the workspace
 * stops reading as one surface:
 *
 * - **A shared horizon.** The chart grid is `p-2` and each pane is a bordered
 *   card with a `py-1.5` toolbar of `h-8` controls, so the pane toolbar's rule
 *   lands 46px below the top of the card: 1px of card border, then 45px of
 *   toolbar. A panel whose own header rule sits anywhere else is what makes
 *   it look bolted on rather than shipped.
 * - **A width the user owns.** A watchlist of option symbols needs more room
 *   than one of index names, and no single default serves both. The width is
 *   dragged from the panel's inner edge and remembered per panel.
 */

import { type ReactNode, useCallback, useEffect, useRef, useState } from 'react'
import { cn } from '@/lib/utils'

/**
 * A panel header, sized to land its bottom rule on the same line as the pane
 * toolbar's. Kept as a class string rather than a component so a panel can put
 * whatever controls it likes inside it.
 */
export const PANEL_HEADER = 'flex h-[46px] shrink-0 items-center gap-1.5 border-b px-2 py-1.5'

/** Narrower than this and the symbol column cannot hold an option symbol. */
const MIN_WIDTH = 260

/** Wider than this and the chart, which is the point of the page, is squeezed. */
const MAX_WIDTH = 520

function readWidth(storageKey: string, fallback: number): number {
  const saved = Number(localStorage.getItem(storageKey))
  return Number.isFinite(saved) && saved >= MIN_WIDTH && saved <= MAX_WIDTH ? saved : fallback
}

interface Props {
  /** Referenced by the rail button's aria-controls. */
  id: string
  /** Names the landmark, so a screen reader says more than "complementary". */
  label: string
  /** Where this panel's width is remembered. */
  storageKey: string
  defaultWidth?: number
  /**
   * The narrowest this panel's own content can be drawn at.
   *
   * The watchlist raises it as columns are added: four numeric columns need
   * about 240px between them, and without this the symbol column absorbed
   * the whole cost and collapsed to two letters. Choosing more columns
   * genuinely needs more room, so the panel grows to fit rather than
   * silently ruining the one column every row is identified by.
   */
  minWidth?: number
  children: ReactNode
}

export function PanelShell({
  id,
  label,
  storageKey,
  defaultWidth = 340,
  minWidth,
  children,
}: Props) {
  const floor = Math.max(MIN_WIDTH, minWidth ?? 0)
  const [width, setWidth] = useState(() => readWidth(storageKey, defaultWidth))

  // Grow to the floor when it rises, but never shrink back: a user who
  // widened the panel and then removed a column keeps the width they chose.
  useEffect(() => {
    setWidth((w) => (w < floor ? Math.min(MAX_WIDTH, floor) : w))
  }, [floor])
  const [dragging, setDragging] = useState(false)
  const widthRef = useRef(width)
  widthRef.current = width
  /**
   * Detaches whatever the current drag attached to the window.
   *
   * The drag's own pointerup normally does this, but a panel closed
   * mid-drag never sees one, and its listeners would stay attached to the
   * window holding this component's closure for the life of the page.
   */
  const releaseRef = useRef<(() => void) | null>(null)
  useEffect(() => () => releaseRef.current?.(), [])

  /**
   * Written once the gesture ends, not on every frame of it. A drag moves
   * the width dozens of times a second, and localStorage is synchronous and
   * disk-backed, so persisting per change put a write on the critical path
   * of every pointermove.
   */
  const persist = useCallback(
    (value: number) => localStorage.setItem(storageKey, String(value)),
    [storageKey]
  )

  const startResize = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      // Left button only. A right-click opens the context menu and never
      // delivers a pointerup here, which would leave the body stuck in
      // select-none with the move listener still attached.
      if (event.button !== 0) return
      event.preventDefault()
      const startX = event.clientX
      const startWidth = widthRef.current
      setDragging(true)

      // Pointer events on the window rather than the handle: the pointer routinely
      // leaves a 4px strip mid-drag, and a handle-local listener would drop the
      // gesture the moment it did.
      const onMove = (e: PointerEvent) => {
        // The panel is on the right, so dragging left makes it wider.
        const next = startWidth + (startX - e.clientX)
        setWidth(Math.min(MAX_WIDTH, Math.max(floor, next)))
      }
      const onUp = () => {
        setDragging(false)
        // The gesture owns the cursor and suppresses selection for its
        // duration: without this, dragging selects the panel and chart text
        // and the cursor flickers whenever the pointer leaves the 4px strip.
        document.body.classList.remove('select-none', 'cursor-col-resize')
        window.removeEventListener('pointermove', onMove)
        window.removeEventListener('pointerup', onUp)
        window.removeEventListener('pointercancel', onUp)
        persist(widthRef.current)
        releaseRef.current = null
      }
      document.body.classList.add('select-none', 'cursor-col-resize')
      window.addEventListener('pointermove', onMove)
      window.addEventListener('pointerup', onUp)
      // Touch cancels the gesture without a pointerup. Without this the body
      // keeps select-none and the col-resize cursor for the life of the page.
      window.addEventListener('pointercancel', onUp)
      releaseRef.current = onUp
    },
    // floor: a drag started before a column change must clamp to the new
    // minimum, not the one that was live when the pointer went down.
    [persist, floor]
  )

  return (
    <aside
      id={id}
      aria-label={label}
      className="relative flex shrink-0 flex-col overflow-hidden border-l bg-background pt-2"
      style={{ width }}
    >
      {/* The drag handle: a hairline that only announces itself on approach.
          Keyboard users get the arrow keys rather than a pointer gesture. */}
      {/* biome-ignore lint/a11y/useSemanticElements: the rule points at <hr>,
          which cannot be focusable or carry pointer handlers. role=separator
          with tabindex and aria-valuenow IS the ARIA window-splitter pattern. */}
      <div
        role="separator"
        aria-orientation="vertical"
        aria-label={`Resize ${label.toLowerCase()}`}
        aria-valuenow={width}
        aria-valuemin={floor}
        aria-valuemax={MAX_WIDTH}
        tabIndex={0}
        onPointerDown={startResize}
        onKeyDown={(e) => {
          const step = e.key === 'ArrowLeft' ? 16 : e.key === 'ArrowRight' ? -16 : 0
          if (!step) return
          setWidth((w) => Math.min(MAX_WIDTH, Math.max(floor, w + step)))
          e.preventDefault()
        }}
        // Held-arrow auto-repeat fires about thirty times a second, so the
        // write waits for the key to come up, the same way the drag waits
        // for pointerup.
        onKeyUp={() => persist(widthRef.current)}
        onBlur={() => persist(widthRef.current)}
        className={cn(
          'absolute inset-y-0 left-0 z-20 w-1 cursor-col-resize transition-colors hover:bg-primary/40 focus-visible:outline-none focus-visible:bg-primary/60',
          dragging && 'bg-primary/60'
        )}
      />
      {children}
    </aside>
  )
}
